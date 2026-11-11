"""
Lightweight Deployment & Pre-Flight Verification Check (#346).
=============================================================
Quickly verifies deployment readiness before release:
1. Validates configuration files (vercel.json, api/index.py, requirements.txt).
2. Simulates serverless runtime environment (VERCEL=1).
3. Verifies zero top-level import/runtime errors on WSGI app initialization.
4. Performs smoke requests against critical public routes (/, /healthz, /login, /register, /privacy, /api/company/Google).
5. Emits structured report with exit code 0 on success, 1 on failure.

Usage:
    python utils/deployment_check.py
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def check_configuration_files() -> Tuple[bool, List[str]]:
    """Verifies that all required deployment and configuration files exist."""
    issues = []
    required_files = [
        ("vercel.json", "Vercel deployment configuration"),
        ("api/index.py", "Vercel serverless WSGI entrypoint"),
        ("requirements.txt", "Production Python dependencies"),
        ("app.py", "Main Flask application"),
        ("config.py", "Application configuration module"),
    ]

    for file_rel, desc in required_files:
        full_path = BASE_DIR / file_rel
        if not full_path.exists():
            issues.append(f"Missing required deployment file: {file_rel} ({desc})")

    # Validate vercel.json format if present
    vercel_json_path = BASE_DIR / "vercel.json"
    if vercel_json_path.exists():
        try:
            with open(vercel_json_path, "r", encoding="utf-8") as f:
                v_data = json.load(f)
                if "rewrites" not in v_data and "builds" not in v_data and "routes" not in v_data:
                    issues.append("vercel.json is missing 'rewrites' routing configuration.")
        except Exception as e:
            issues.append(f"Invalid vercel.json syntax: {e}")

    return len(issues) == 0, issues


def check_app_import_and_init(simulated_vercel: bool = True) -> Tuple[bool, Any, List[str]]:
    """Verifies that the WSGI Flask application boots cleanly without import or NameErrors."""
    errors = []
    if simulated_vercel:
        os.environ["VERCEL"] = "1"

    app_instance = None
    try:
        import config
        from app import app as flask_app
        app_instance = flask_app
    except Exception as exc:
        errors.append(f"Application import failed: {type(exc).__name__}: {exc}")

    # Also check api/index entrypoint
    try:
        from api.index import app as vercel_app
        if vercel_app is None:
            errors.append("api.index app export is None.")
    except Exception as exc:
        errors.append(f"api.index entrypoint import failed: {type(exc).__name__}: {exc}")

    return len(errors) == 0, app_instance, errors


def check_public_routes(app_instance) -> Tuple[bool, List[Dict[str, Any]]]:
    """Sends test HTTP requests to critical public routes ensuring 200 OK responses."""
    if not app_instance:
        return False, [{"route": "*", "status": "FAIL", "error": "App instance not available"}]

    app_instance.config["TESTING"] = True
    client = app_instance.test_client()

    routes_to_probe = [
        ("/", "AI Campus Placement Agent", "Home landing page"),
        ("/healthz", "healthy", "Health probe / readiness endpoint"),
        ("/health", "healthy", "Health alias endpoint"),
        ("/api/health", "healthy", "API health check"),
        ("/login", "Login", "Authentication login page"),
        ("/register", "Create Account", "Student registration page"),
        ("/privacy", "Privacy Notice", "Privacy policy page"),
        ("/forgot-password", "Forgot Password", "Password recovery page"),
        ("/api/company/Google", "Google", "Company hiring guide profile API"),
    ]

    results = []
    all_passed = True

    for path, expected_content, description in routes_to_probe:
        t0 = time.time()
        try:
            res = client.get(path)
            latency_ms = round((time.time() - t0) * 1000, 2)
            passed = (res.status_code == 200)

            body = res.get_data(as_text=True) if hasattr(res, "get_data") else ""
            content_match = expected_content.lower() in body.lower()
            if not content_match and passed:
                passed = False
                err_msg = f"Expected content '{expected_content}' not found in response body"
            else:
                err_msg = "" if passed else f"HTTP {res.status_code} != 200"

            if not passed:
                all_passed = False

            results.append({
                "route": path,
                "description": description,
                "status_code": res.status_code,
                "latency_ms": latency_ms,
                "passed": passed,
                "error": err_msg
            })
        except Exception as exc:
            all_passed = False
            results.append({
                "route": path,
                "description": description,
                "status_code": 500,
                "latency_ms": 0.0,
                "passed": False,
                "error": f"Exception: {type(exc).__name__}: {exc}"
            })

    return all_passed, results


def run_deployment_check() -> int:
    """Executes the complete deployment pre-flight verification."""
    print("=" * 70)
    print("  AI Campus Placement Agent - Deployment Pre-Flight Smoke Check")
    print("=" * 70)

    # 1. Configuration files
    files_ok, file_issues = check_configuration_files()
    if files_ok:
        print("[PASS] Configuration Files: vercel.json, api/index.py, requirements.txt verified.")
    else:
        print("[FAIL] Configuration Files:")
        for issue in file_issues:
            print(f"       - {issue}")

    # 2. Application Import & Initialization
    import_ok, app_inst, import_errors = check_app_import_and_init(simulated_vercel=True)
    if import_ok:
        print("[PASS] App WSGI Initialization: Module imports clean without runtime NameErrors.")
    else:
        print("[FAIL] App WSGI Initialization:")
        for err in import_errors:
            print(f"       - {err}")

    # 3. Public Routes Smoke Test
    routes_ok = False
    route_results = []
    if import_ok and app_inst:
        routes_ok, route_results = check_public_routes(app_inst)
        print("\n--- Public Routes Probe ---")
        for r in route_results:
            status_tag = "PASS" if r["passed"] else "FAIL"
            err_note = f" (Error: {r['error']})" if r["error"] else ""
            print(f"  [{status_tag}] {r['route']:<22} {r['status_code']} {r['latency_ms']:>6.1f}ms - {r['description']}{err_note}")

    print("=" * 70)
    overall_success = files_ok and import_ok and routes_ok
    if overall_success:
        print("  RESULT: DEPLOYMENT CHECK PASSED (Release ready for Vercel)")
        print("=" * 70)
        return 0
    else:
        print("  RESULT: DEPLOYMENT CHECK FAILED (Resolve issues before deploying)")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(run_deployment_check())
