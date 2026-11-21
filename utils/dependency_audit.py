"""
Dependency Vulnerability Audit Runner (#649)
===========================================
Audits production dependencies using pip-audit against known vulnerability databases.
Enforces:
1. Pinned direct dependencies in requirements.txt.
2. Structured ignore file (.pip-audit-ignore.yml) requiring justification and expiration date.
3. Automated summary reporting and failure on unhandled high/critical vulnerabilities.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_ignore_yaml_lightweight(text: str) -> List[Dict[str, str]]:
    """
    Parses ignored advisories from YAML text without external hard dependency on PyYAML.
    Falls back to basic line-by-line block parsing if PyYAML is unavailable.
    """
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            return data.get("ignored_advisories", []) or []
        return []
    except ImportError:
        pass

    # Lightweight regex parser for YAML list of dictionaries
    advisories: List[Dict[str, str]] = []
    current_entry: Optional[Dict[str, str]] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- id:") or line.startswith("- "):
            if current_entry and "id" in current_entry:
                advisories.append(current_entry)
            current_entry = {}
            if line.startswith("- id:"):
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                current_entry["id"] = val
            continue

        if current_entry is not None and ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in ("id", "package", "reason", "expiry"):
                current_entry[key] = val

    if current_entry and "id" in current_entry:
        advisories.append(current_entry)

    return advisories


def validate_ignore_file(
    ignore_file_path: Union[str, Path],
    reference_date: Optional[dt.date] = None
) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Validates the structure and policy of the ignored advisories file.
    Policies:
    - Every entry MUST specify a non-empty `id`.
    - Every entry MUST specify a non-empty `reason`.
    - Every entry MUST specify an `expiry` date in YYYY-MM-DD.
    - If `expiry < today`: The advisory exception has EXPIRED and is rejected.

    Returns:
        (is_valid, valid_advisories, error_messages)
    """
    path = Path(ignore_file_path)
    if not path.exists():
        return True, [], []

    content = path.read_text(encoding="utf-8")
    entries = parse_ignore_yaml_lightweight(content)
    today = reference_date or dt.date.today()

    valid_entries: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, entry in enumerate(entries, start=1):
        vuln_id = (entry.get("id") or "").strip()
        package = (entry.get("package") or "").strip()
        reason = (entry.get("reason") or "").strip()
        expiry_str = (entry.get("expiry") or "").strip()

        if not vuln_id:
            errors.append(f"Entry #{idx}: Missing vulnerability 'id'.")
            continue

        if not reason:
            errors.append(f"Entry '{vuln_id}': Missing required 'reason'. Ignored advisories require a written justification.")

        if not expiry_str:
            errors.append(f"Entry '{vuln_id}': Missing required 'expiry' date (format: YYYY-MM-DD).")
            continue

        try:
            expiry_date = dt.datetime.strptime(expiry_str, "%Y-%m-%d").date()
        except ValueError:
            errors.append(f"Entry '{vuln_id}': Invalid expiry date format '{expiry_str}'. Expected YYYY-MM-DD.")
            continue

        if expiry_date < today:
            errors.append(
                f"Entry '{vuln_id}' for '{package or 'unknown'}' EXPIRED on {expiry_str}. "
                f"Expired exemptions are not permitted; please upgrade the dependency or renew with updated justification."
            )
            continue

        valid_entries.append({
            "id": vuln_id,
            "package": package,
            "reason": reason,
            "expiry": expiry_str,
            "expiry_date": expiry_date,
        })

    is_valid = len(errors) == 0
    return is_valid, valid_entries, errors


def check_direct_dependencies_pinned(requirements_path: Union[str, Path]) -> Tuple[bool, List[str], List[str]]:
    """
    Verifies that all non-comment, non-empty direct dependency declarations
    in requirements.txt are pinned to exact versions with '=='.

    Returns:
        (all_pinned, unpinned_lines, pinned_packages)
    """
    path = Path(requirements_path)
    if not path.exists():
        return False, ["requirements.txt not found."], []

    unpinned: List[str] = []
    pinned: List[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Look for exact version pinning
        if "==" in line:
            pinned.append(line)
        else:
            unpinned.append(line)

    return len(unpinned) == 0, unpinned, pinned


def run_dependency_audit(
    requirements_path: Union[str, Path] = "requirements.txt",
    ignore_file_path: Union[str, Path] = ".pip-audit-ignore.yml",
    fail_on_vulnerabilities: bool = True,
    service: str = "pypi",
    no_deps: bool = True,
) -> Dict[str, Any]:
    """
    Executes pip-audit with active, unexpired ignored advisories.
    Returns structured results dictionary.
    """
    req_file = Path(requirements_path)
    ignore_file = Path(ignore_file_path)

    if not req_file.exists():
        return {
            "success": False,
            "exit_code": 1,
            "summary": f"Requirements file not found at {requirements_path}",
            "errors": [f"File not found: {requirements_path}"],
            "vulnerabilities": [],
            "ignored_count": 0,
        }

    # 1. Validate ignore file
    is_valid, valid_ignores, ignore_errors = validate_ignore_file(ignore_file)
    if not is_valid:
        return {
            "success": False,
            "exit_code": 1,
            "summary": "Validation failed for ignored advisories file.",
            "errors": ignore_errors,
            "vulnerabilities": [],
            "ignored_count": len(valid_ignores),
        }

    # 2. Build pip-audit CLI command
    cmd = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(req_file),
        "-f",
        "json",
        "-s",
        service,
    ]
    if no_deps:
        cmd.extend(["--disable-pip", "--no-deps"])

    for ign in valid_ignores:
        cmd.extend(["--ignore-vuln", ign["id"]])

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False
        )
    except FileNotFoundError:
        return {
            "success": False,
            "exit_code": 1,
            "summary": "pip-audit module is not installed.",
            "errors": ["pip-audit not found. Install with: pip install pip-audit"],
            "vulnerabilities": [],
            "ignored_count": len(valid_ignores),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": 1,
            "summary": "pip-audit execution timed out.",
            "errors": ["Subprocess timed out after 120 seconds."],
            "vulnerabilities": [],
            "ignored_count": len(valid_ignores),
        }

    # 3. Parse JSON output
    unhandled_vulns: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        output_data = json.loads(proc.stdout) if proc.stdout.strip() else {}
        deps = output_data.get("dependencies", []) if isinstance(output_data, dict) else []
        for dep in deps:
            vulns = dep.get("vulns", [])
            for v in vulns:
                unhandled_vulns.append({
                    "package": dep.get("name"),
                    "version": dep.get("version"),
                    "id": v.get("id"),
                    "fix_versions": v.get("fix_versions", []),
                    "description": v.get("description", ""),
                    "aliases": v.get("aliases", []),
                })
    except json.JSONDecodeError:
        # Fallback if output was plain text or columns
        if proc.returncode != 0 and "Found" in proc.stdout:
            unhandled_vulns.append({"raw_output": proc.stdout.strip()})
        elif proc.returncode != 0:
            errors.append(proc.stderr.strip() or proc.stdout.strip())

    if proc.returncode != 0 and not unhandled_vulns and proc.stderr.strip():
        errors.append(proc.stderr.strip())

    success = (len(unhandled_vulns) == 0 and len(errors) == 0 and proc.returncode == 0)
    exit_code = 0 if success else (proc.returncode or 1)

    return {
        "success": success,
        "exit_code": exit_code,
        "vulnerabilities": unhandled_vulns,
        "ignored_count": len(valid_ignores),
        "errors": errors,
        "raw_stdout": proc.stdout,
        "raw_stderr": proc.stderr,
    }


def main() -> int:
    """CLI entrypoint for CI dependency audit workflow."""
    parser = argparse.ArgumentParser(description="Audit project dependencies for known security vulnerabilities.")
    parser.add_argument("-r", "--requirement", default="requirements.txt", help="Path to requirements.txt")
    parser.add_argument("--ignore-file", default=".pip-audit-ignore.yml", help="Path to ignore YAML file")
    parser.add_argument("--check-pinned", action="store_true", help="Assert that all direct dependencies are pinned")
    parser.add_argument("--include-deps", action="store_true", help="Resolve and audit transitive dependencies in addition to direct requirements")
    args = parser.parse_args()

    print("======================================================================")
    print("  AI Campus Placement Agent - Dependency Vulnerability Audit")
    print("======================================================================")

    # Check dependency pinning
    all_pinned, unpinned, pinned = check_direct_dependencies_pinned(args.requirement)
    if not all_pinned:
        print("[FAIL] Unpinned direct dependencies detected in requirements.txt:")
        for line in unpinned:
            print(f"  - {line}")
        print("  All direct dependencies must be pinned to exact versions (==).")
        return 1
    print(f"[PASS] All {len(pinned)} direct dependencies are pinned to exact versions.")

    # Validate ignore file
    is_valid, ignores, ignore_errors = validate_ignore_file(args.ignore_file)
    if not is_valid:
        print(f"[FAIL] Invalid ignore configuration in {args.ignore_file}:")
        for err in ignore_errors:
            print(f"  - {err}")
        return 1

    print(f"[INFO] Loaded {len(ignores)} active ignored advisories with verified justification and expiry.")
    for ign in ignores:
        print(f"  * {ign['id']} ({ign['package']}): expires {ign['expiry']} - {ign['reason']}")

    # Execute audit
    result = run_dependency_audit(
        requirements_path=args.requirement,
        ignore_file_path=args.ignore_file,
        no_deps=not args.include_deps,
    )

    if not result["success"]:
        print("\n[FAIL] Known security vulnerabilities detected:")
        for v in result.get("vulnerabilities", []):
            if "package" in v:
                fixes = ", ".join(v.get("fix_versions", [])) or "No fix available"
                print(f"  * {v['package']} {v['version']} | {v['id']} | Fixed in: {fixes}")
            elif "raw_output" in v:
                print(f"  * {v['raw_output']}")
        for err in result.get("errors", []):
            print(f"  [ERROR] {err}")
        return 1

    print(f"\n[PASS] Dependency audit completed successfully: 0 unhandled vulnerabilities ({len(ignores)} ignored).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
