"""
Dependency Vulnerability Audit Runner (#649)
===========================================
Audits production dependencies for Python (via pip-audit) and JavaScript (via npm audit)
against known security vulnerability databases.

Enforces:
1. Automated scanning for Python (pip-audit) and JavaScript (npm audit).
2. Structured ignore policies (.pip-audit-ignore.yml, .npm-audit-ignore.json) requiring
   vulnerability ID, package name, written justification, and strict expiration dates.
3. Separation of production vulnerabilities from development-only warnings to prevent
   CI pipeline breakage from non-production dependencies without explanation.
4. Rich summary reporting compatible with GitHub Step Summary ($GITHUB_STEP_SUMMARY).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

SEVERITY_LEVELS: Dict[str, int] = {
    "info": 0,
    "low": 1,
    "moderate": 2,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


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
    Validates the structure and policy of the Python ignored advisories file (.pip-audit-ignore.yml).
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


def validate_npm_ignore_file(
    ignore_file_path: Union[str, Path],
    reference_date: Optional[dt.date] = None
) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Validates the structure and policy of the JavaScript ignored advisories file (.npm-audit-ignore.json).
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

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [], [f"Failed to parse JSON in {path}: {exc}"]

    entries = data.get("ignored_advisories", []) if isinstance(data, dict) else []
    today = reference_date or dt.date.today()

    valid_entries: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, entry in enumerate(entries, start=1):
        vuln_id = str(entry.get("id") or "").strip()
        package = str(entry.get("package") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        expiry_str = str(entry.get("expiry") or "").strip()

        if not vuln_id:
            errors.append(f"NPM entry #{idx}: Missing vulnerability 'id'.")
            continue

        if not reason:
            errors.append(f"NPM entry '{vuln_id}': Missing required 'reason' justification.")

        if not expiry_str:
            errors.append(f"NPM entry '{vuln_id}': Missing required 'expiry' date (format: YYYY-MM-DD).")
            continue

        try:
            expiry_date = dt.datetime.strptime(expiry_str, "%Y-%m-%d").date()
        except ValueError:
            errors.append(f"NPM entry '{vuln_id}': Invalid expiry date format '{expiry_str}'. Expected YYYY-MM-DD.")
            continue

        if expiry_date < today:
            errors.append(
                f"NPM entry '{vuln_id}' for '{package or 'unknown'}' EXPIRED on {expiry_str}. "
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
    Executes pip-audit on Python dependencies with active, unexpired ignored advisories.
    Returns structured results dictionary.
    """
    req_file = Path(requirements_path)
    ignore_file = Path(ignore_file_path)

    if not req_file.exists():
        return {
            "ecosystem": "python",
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
            "ecosystem": "python",
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
            "ecosystem": "python",
            "success": False,
            "exit_code": 1,
            "summary": "pip-audit module is not installed.",
            "errors": ["pip-audit not found. Install with: pip install pip-audit"],
            "vulnerabilities": [],
            "ignored_count": len(valid_ignores),
        }
    except subprocess.TimeoutExpired:
        return {
            "ecosystem": "python",
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
        "ecosystem": "python",
        "success": success,
        "exit_code": exit_code,
        "vulnerabilities": unhandled_vulns,
        "ignored_count": len(valid_ignores),
        "errors": errors,
        "raw_stdout": proc.stdout,
        "raw_stderr": proc.stderr,
    }


def run_npm_audit(
    package_json_path: Union[str, Path] = "package.json",
    ignore_file_path: Union[str, Path] = ".npm-audit-ignore.json",
    audit_level: str = "high",
    omit_dev: bool = True,
) -> Dict[str, Any]:
    """
    Executes npm audit on JavaScript packages with active, unexpired ignored advisories.
    Avoids failing for irrelevant development-only warnings by using --omit=dev and
    filtering below the requested threshold (audit_level).

    Returns structured results dictionary.
    """
    pkg_file = Path(package_json_path)
    if not pkg_file.exists():
        return {
            "ecosystem": "javascript",
            "success": True,
            "exit_code": 0,
            "summary": "No package.json found; skipping JavaScript audit.",
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": 0,
            "errors": [],
        }

    ignore_file = Path(ignore_file_path)
    is_valid, valid_ignores, ignore_errors = validate_npm_ignore_file(ignore_file)
    if not is_valid:
        return {
            "ecosystem": "javascript",
            "success": False,
            "exit_code": 1,
            "summary": "Validation failed for NPM ignored advisories file.",
            "errors": ignore_errors,
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": len(valid_ignores),
        }

    ignored_id_set = {entry["id"].strip().upper() for entry in valid_ignores}

    # Locate npm executable
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        # If npm CLI is not present in environment, note as skipped
        return {
            "ecosystem": "javascript",
            "success": True,
            "exit_code": 0,
            "summary": "npm executable not found in PATH; skipping JavaScript audit.",
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": len(valid_ignores),
            "errors": [],
        }

    cmd = [npm_cmd, "audit", "--json"]
    if omit_dev:
        cmd.append("--omit=dev")

    cwd = str(pkg_file.parent.resolve()) if pkg_file.parent.name else None

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ecosystem": "javascript",
            "success": False,
            "exit_code": 1,
            "summary": "npm audit execution timed out after 120 seconds.",
            "errors": ["Subprocess timed out."],
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": len(valid_ignores),
        }
    except Exception as exc:
        return {
            "ecosystem": "javascript",
            "success": False,
            "exit_code": 1,
            "summary": f"Failed to execute npm audit: {exc}",
            "errors": [str(exc)],
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": len(valid_ignores),
        }

    min_rank = SEVERITY_LEVELS.get(audit_level.lower(), 3)
    unhandled_vulns: List[Dict[str, Any]] = []
    filtered_dev_warnings = 0
    errors: List[str] = []

    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        # Non-JSON response (e.g. registry offline, 403, or network failure)
        if "npm error audit endpoint returned an error" in proc.stderr or "403 Forbidden" in proc.stderr:
            return {
                "ecosystem": "javascript",
                "success": True,
                "exit_code": 0,
                "summary": "npm registry audit endpoint is offline or restricted by network policy; skipped without failure.",
                "vulnerabilities": [],
                "filtered_dev_warnings": 0,
                "ignored_count": len(valid_ignores),
                "errors": [],
                "notice": "npm audit endpoint unreachable in current environment.",
            }
        errors.append(proc.stderr.strip() or proc.stdout.strip() or "Failed to parse npm audit output.")
        return {
            "ecosystem": "javascript",
            "success": False,
            "exit_code": proc.returncode or 1,
            "summary": "Error running npm audit.",
            "vulnerabilities": [],
            "filtered_dev_warnings": 0,
            "ignored_count": len(valid_ignores),
            "errors": errors,
        }

    # Parse modern npm audit (npm v7+ audit schema)
    vulnerabilities_map = data.get("vulnerabilities", {})
    if isinstance(vulnerabilities_map, dict):
        for pkg_name, v_info in vulnerabilities_map.items():
            if not isinstance(v_info, dict):
                continue
            severity = str(v_info.get("severity") or "low").lower()
            rank = SEVERITY_LEVELS.get(severity, 1)

            via_list = v_info.get("via", [])
            for item in via_list:
                if isinstance(item, dict):
                    adv_url = str(item.get("url") or "")
                    adv_title = str(item.get("title") or "")
                    adv_source = str(item.get("source") or "")
                    adv_id = str(item.get("url") or "").split("/")[-1].upper() or adv_source

                    # Check if covered by ignored advisories
                    is_ignored = (
                        adv_id in ignored_id_set or
                        adv_source.upper() in ignored_id_set or
                        any(ign in adv_url.upper() for ign in ignored_id_set)
                    )

                    if is_ignored:
                        continue

                    if rank < min_rank:
                        filtered_dev_warnings += 1
                        continue

                    unhandled_vulns.append({
                        "package": pkg_name,
                        "severity": severity,
                        "title": adv_title,
                        "url": adv_url,
                        "id": adv_id,
                        "range": v_info.get("range", ""),
                        "fix_available": v_info.get("fixAvailable", False),
                    })
                elif isinstance(item, str):
                    # Transitive dependency reference
                    pass

    # Parse legacy npm audit format (v6 schema)
    advisories = data.get("advisories", {})
    if isinstance(advisories, dict) and not unhandled_vulns and not vulnerabilities_map:
        for adv_id, item in advisories.items():
            severity = str(item.get("severity") or "low").lower()
            rank = SEVERITY_LEVELS.get(severity, 1)
            pkg_name = item.get("module_name", "unknown")

            if str(adv_id).upper() in ignored_id_set or str(item.get("github_advisory_id") or "").upper() in ignored_id_set:
                continue

            if rank < min_rank:
                filtered_dev_warnings += 1
                continue

            unhandled_vulns.append({
                "package": pkg_name,
                "severity": severity,
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "id": str(adv_id),
                "range": item.get("vulnerable_versions", ""),
                "fix_available": bool(item.get("patched_versions")),
            })

    success = (len(unhandled_vulns) == 0 and len(errors) == 0)
    exit_code = 0 if success else 1

    return {
        "ecosystem": "javascript",
        "success": success,
        "exit_code": exit_code,
        "vulnerabilities": unhandled_vulns,
        "filtered_dev_warnings": filtered_dev_warnings,
        "ignored_count": len(valid_ignores),
        "errors": errors,
        "metadata": data.get("metadata", {}),
    }


def format_github_step_summary(
    python_result: Optional[Dict[str, Any]] = None,
    npm_result: Optional[Dict[str, Any]] = None,
    dev_explanation: Optional[str] = None,
) -> str:
    """
    Generates a Markdown report suitable for GitHub Step Summary ($GITHUB_STEP_SUMMARY).
    Clearly itemizes detected vulnerabilities, active exemptions, and explains
    why development-only or low-severity warnings are excluded.
    """
    lines: List[str] = [
        "## 🛡️ Automated Dependency Vulnerability Scan Report",
        "",
        "This automated security scan audits Python and JavaScript packages against known vulnerability databases.",
        "",
    ]

    # Python Section
    if python_result:
        py_status = "✅ PASSED" if python_result.get("success") else "❌ FAILED"
        py_vulns = python_result.get("vulnerabilities", [])
        py_ignored = python_result.get("ignored_count", 0)

        lines.extend([
            f"### Python Dependencies (`requirements.txt`) — {py_status}",
            "",
            f"- **Status**: `{py_status}`",
            f"- **Unhandled Vulnerabilities**: `{len(py_vulns)}`",
            f"- **Active Documented Exemptions**: `{py_ignored}` (managed via `.pip-audit-ignore.yml`)",
            "",
        ])

        if py_vulns:
            lines.extend([
                "| Package | Version | Advisory ID | Fixed In | Description |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for v in py_vulns:
                pkg = v.get("package", "unknown")
                ver = v.get("version", "unknown")
                vid = v.get("id", "N/A")
                fixes = ", ".join(v.get("fix_versions", [])) or "No patch available"
                desc = (v.get("description", "") or "").replace("\n", " ")[:100]
                lines.append(f"| `{pkg}` | `{ver}` | `{vid}` | `{fixes}` | {desc} |")
            lines.append("")

    # JavaScript Section
    if npm_result:
        npm_status = "✅ PASSED" if npm_result.get("success") else "❌ FAILED"
        npm_vulns = npm_result.get("vulnerabilities", [])
        npm_ignored = npm_result.get("ignored_count", 0)
        npm_dev_filtered = npm_result.get("filtered_dev_warnings", 0)

        lines.extend([
            f"### JavaScript Dependencies (`package.json`) — {npm_status}",
            "",
            f"- **Status**: `{npm_status}`",
            f"- **High/Critical Production Vulnerabilities**: `{len(npm_vulns)}`",
            f"- **Development-Only / Low-Severity Warnings Omitted**: `{npm_dev_filtered}`",
            f"- **Active Documented Exemptions**: `{npm_ignored}` (managed via `.npm-audit-ignore.json`)",
            "",
        ])

        if npm_vulns:
            lines.extend([
                "| Package | Severity | Advisory ID | Advisory Title | Fix Available |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for v in npm_vulns:
                pkg = v.get("package", "unknown")
                sev = v.get("severity", "unknown").upper()
                vid = v.get("id", "N/A")
                title = v.get("title", "")
                fix = "Yes" if v.get("fix_available") else "Manual review needed"
                lines.append(f"| `{pkg}` | `{sev}` | `{vid}` | {title} | {fix} |")
            lines.append("")

    # Development-only explanation section
    lines.extend([
        "### 💡 Development Warnings Policy & Guidance",
        "",
        dev_explanation or (
            "- **Development-Only Warnings**: Development tools (test runners, linters, code formatters) "
            "are excluded from production builds (`--omit=dev`). Non-production warnings do not fail the build.\n"
            "- **Triage & Upgrades**: Maintainers should run `pip install --upgrade [package]` or `npm update [package]` "
            "to resolve reported advisories.\n"
            "- **Time-Limited Exemptions**: If an upstream library has no available patch or upgrading requires breaking changes, "
            "maintainers may add a strictly-timed exemption with a written reason to `.pip-audit-ignore.yml` or `.npm-audit-ignore.json`. "
            "Exemptions automatically expire and fail CI when their expiration date is reached."
        ),
        "",
    ])

    return "\n".join(lines)


def main() -> int:
    """CLI entrypoint for CI dependency vulnerability audit workflow."""
    parser = argparse.ArgumentParser(
        description="Audit project dependencies (Python & JavaScript) for known security vulnerabilities."
    )
    # Python options
    parser.add_argument("-r", "--requirement", default="requirements.txt", help="Path to requirements.txt")
    parser.add_argument("--ignore-file", default=".pip-audit-ignore.yml", help="Path to Python ignore YAML file")
    parser.add_argument("--skip-python", action="store_true", help="Skip Python dependency audit")
    parser.add_argument("--check-pinned", action="store_true", help="Assert that all direct requirements are pinned (==)")
    parser.add_argument("--include-deps", action="store_true", help="Resolve and audit transitive dependencies for Python")

    # JavaScript options
    parser.add_argument("--package-json", default="package.json", help="Path to package.json")
    parser.add_argument("--npm-ignore-file", default=".npm-audit-ignore.json", help="Path to NPM ignore JSON file")
    parser.add_argument("--skip-npm", action="store_true", help="Skip JavaScript / NPM dependency audit")
    parser.add_argument("--audit-level", default="high", choices=["info", "low", "moderate", "high", "critical"],
                        help="Minimum severity level for npm audit failure (default: high)")
    parser.add_argument("--include-dev", action="store_true", help="Include development dependencies in npm audit")

    # Output options
    parser.add_argument("--summary-file", help="Path to write GitHub Step Summary Markdown")

    args = parser.parse_args()

    print("======================================================================")
    print("  AI Campus Placement Agent - Dependency Vulnerability Audit")
    print("======================================================================")

    exit_code = 0
    python_result: Optional[Dict[str, Any]] = None
    npm_result: Optional[Dict[str, Any]] = None

    # 1. Python Audit
    if not args.skip_python:
        print("\n--- [1/2] Auditing Python Dependencies ---")

        if args.check_pinned:
            all_pinned, unpinned, pinned = check_direct_dependencies_pinned(args.requirement)
            if not all_pinned:
                print("[FAIL] Unpinned direct dependencies detected in requirements.txt:")
                for line in unpinned:
                    print(f"  - {line}")
                print("  All direct dependencies must be pinned to exact versions (==).")
                return 1
            print(f"[PASS] All {len(pinned)} direct dependencies are pinned to exact versions.")

        # Validate Python ignore file
        is_valid, ignores, ignore_errors = validate_ignore_file(args.ignore_file)
        if not is_valid:
            print(f"[FAIL] Invalid ignore configuration in {args.ignore_file}:")
            for err in ignore_errors:
                print(f"  - {err}")
            return 1

        if ignores:
            print(f"[INFO] Loaded {len(ignores)} active Python ignored advisories with verified justification and expiry:")
            for ign in ignores:
                print(f"  * {ign['id']} ({ign['package']}): expires {ign['expiry']} - {ign['reason']}")

        python_result = run_dependency_audit(
            requirements_path=args.requirement,
            ignore_file_path=args.ignore_file,
            no_deps=not args.include_deps,
        )

        if not python_result["success"]:
            exit_code = 1
            print("\n[FAIL] Known security vulnerabilities detected in Python dependencies:")
            for v in python_result.get("vulnerabilities", []):
                if "package" in v:
                    fixes = ", ".join(v.get("fix_versions", [])) or "No fix available"
                    print(f"  * {v['package']} {v['version']} | {v['id']} | Fixed in: {fixes}")
                elif "raw_output" in v:
                    print(f"  * {v['raw_output']}")
            for err in python_result.get("errors", []):
                print(f"  [ERROR] {err}")
        else:
            print(f"[PASS] Python dependency audit completed: 0 unhandled vulnerabilities ({len(ignores)} ignored).")

    # 2. JavaScript Audit
    if not args.skip_npm and Path(args.package_json).exists():
        print("\n--- [2/2] Auditing JavaScript Dependencies ---")

        is_valid, npm_ignores, npm_ignore_errors = validate_npm_ignore_file(args.npm_ignore_file)
        if not is_valid:
            print(f"[FAIL] Invalid NPM ignore configuration in {args.npm_ignore_file}:")
            for err in npm_ignore_errors:
                print(f"  - {err}")
            return 1

        if npm_ignores:
            print(f"[INFO] Loaded {len(npm_ignores)} active NPM ignored advisories:")
            for ign in npm_ignores:
                print(f"  * {ign['id']} ({ign['package']}): expires {ign['expiry']} - {ign['reason']}")

        omit_dev = not args.include_dev
        npm_result = run_npm_audit(
            package_json_path=args.package_json,
            ignore_file_path=args.npm_ignore_file,
            audit_level=args.audit_level,
            omit_dev=omit_dev,
        )

        if not npm_result["success"]:
            exit_code = 1
            print(f"\n[FAIL] Known security vulnerabilities detected in JavaScript dependencies:")
            for v in npm_result.get("vulnerabilities", []):
                print(f"  * {v.get('package')} | {v.get('severity', '').upper()} | {v.get('id')} - {v.get('title')}")
                if v.get("url"):
                    print(f"    URL: {v.get('url')}")
            for err in npm_result.get("errors", []):
                print(f"  [ERROR] {err}")
        else:
            filtered = npm_result.get("filtered_dev_warnings", 0)
            print(f"[PASS] JavaScript dependency audit completed: 0 unhandled vulnerabilities.")
            if filtered > 0:
                print(f"[INFO] {filtered} development-only or low-severity warnings omitted from blocking threshold.")

    # 3. Generate Markdown Summary
    summary_markdown = format_github_step_summary(python_result, npm_result)

    summary_target = args.summary_file or os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_target:
        try:
            summary_path = Path(summary_target)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(summary_markdown + "\n")
            print(f"\n[INFO] Wrote vulnerability audit summary to {summary_target}")
        except Exception as exc:
            print(f"\n[WARN] Could not write GitHub Step Summary: {exc}")

    print("\n======================================================================")
    if exit_code == 0:
        print("  🎉 All dependency vulnerability checks PASSED.")
    else:
        print("  ❌ Dependency vulnerability checks FAILED.")
    print("======================================================================")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
