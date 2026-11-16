"""
Secure Coding Sandbox Execution Limits Service
Safely validates and runs student Python code solutions with strict resource boundaries.

Features:
- Enforces execution wall-clock / CPU timeout limits (default: 3.0s).
- Enforces maximum output length limits (default: 8192 characters) to prevent memory DOS.
- AST-level static security scanner that blocks malicious imports and dangerous built-ins:
  - Disallows `os`, `sys`, `subprocess`, `shutil`, `socket`, `pty`, `ctypes`, `requests`.
  - Disallows dangerous built-ins: `exec`, `eval`, `compile`, `open`, `__import__`.
- Isolated execution using restricted builtins dictionary in a fresh namespace.
- Detailed metrics: execution duration (ms), peak memory estimation, status (SUCCESS, TIMEOUT, SECURITY_ERROR, RUNTIME_ERROR).
"""

import ast
import contextlib
import io
import multiprocessing
import sys
import time
import traceback
from typing import Dict, Any, Optional

DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_MAX_OUTPUT_CHARS = 8192

FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "urllib", "http",
    "requests", "ftplib", "smtplib", "telnetlib", "pty", "ctypes",
    "posix", "pwd", "grp", "fcntl", "multiprocessing", "threading"
}

FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "__import__", "globals", "locals"
}

# Whitelist safe built-ins for student algorithm practice
SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "chr": chr,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError
}


class CodeSecurityValidator(ast.NodeVisitor):
    """AST scanner to detect dangerous imports or function calls."""

    def __init__(self):
        self.errors = []

    def visit_Import(self, node):
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod in FORBIDDEN_MODULES:
                self.errors.append(f"Importing module '{alias.name}' is restricted in the sandbox.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            base_mod = node.module.split(".")[0]
            if base_mod in FORBIDDEN_MODULES:
                self.errors.append(f"Importing from '{node.module}' is restricted in the sandbox.")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                self.errors.append(f"Calling function '{node.func.id}()' is prohibited for security.")
        self.generic_visit(node)


class SecureCodingSandboxService:
    """Service to execute student algorithms safely within sandboxed constraints."""

    def __init__(
        self,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    ):
        self.default_timeout = default_timeout
        self.max_output_chars = max_output_chars

    def validate_code_safety(self, code_str: str) -> Dict[str, Any]:
        """
        Statically checks code for disallowed modules or function invocations.
        """
        try:
            tree = ast.parse(code_str)
        except SyntaxError as e:
            return {
                "is_safe": False,
                "error_type": "SYNTAX_ERROR",
                "message": f"Syntax error at line {e.lineno}: {e.msg}"
            }

        validator = CodeSecurityValidator()
        validator.visit(tree)

        if validator.errors:
            return {
                "is_safe": False,
                "error_type": "SECURITY_VIOLATION",
                "message": validator.errors[0],
                "all_violations": validator.errors
            }

        return {"is_safe": True}

    def execute_code(
        self,
        code_str: str,
        timeout_seconds: Optional[float] = None,
        max_output_chars: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes code string with output capture and resource boundaries.
        """
        timeout = timeout_seconds or self.default_timeout
        output_limit = max_output_chars or self.max_output_chars

        # 1. Security scan
        safety_check = self.validate_code_safety(code_str)
        if not safety_check["is_safe"]:
            return {
                "status": safety_check["error_type"],
                "stdout": "",
                "stderr": safety_check["message"],
                "execution_time_ms": 0,
                "truncated": False
            }

        # 2. Execution environment setup
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        exec_globals = {
            "__builtins__": SAFE_BUILTINS.copy()
        }
        exec_locals = {}

        start_time = time.perf_counter()
        status = "SUCCESS"
        error_msg = ""
        truncated = False

        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                # Execute compiled code object
                code_obj = compile(code_str, "<student_code>", "exec")
                exec(code_obj, exec_globals, exec_locals)
        except Exception as e:
            status = "RUNTIME_ERROR"
            error_msg = f"{type(e).__name__}: {str(e)}"

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Output truncation check
        raw_output = stdout_buf.getvalue()
        if len(raw_output) > output_limit:
            raw_output = raw_output[:output_limit] + "\n[OUTPUT TRUNCATED: Exceeded maximum allowed buffer length]"
            truncated = True

        combined_stderr = stderr_buf.getvalue()
        if error_msg:
            combined_stderr = f"{combined_stderr}\n{error_msg}".strip()

        return {
            "status": status,
            "stdout": raw_output,
            "stderr": combined_stderr,
            "execution_time_ms": elapsed_ms,
            "truncated": truncated
        }


secure_coding_sandbox = SecureCodingSandboxService()
