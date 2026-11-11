"""
Automated Test Suite for Deployment Readiness & Serverless Configuration (#346).
Verifies:
- vercel.json routing and configuration syntax
- api/index.py WSGI entrypoint export
- App initialization and error-free execution in simulated Vercel serverless mode (VERCEL=1)
- Public route availability (/, /healthz, /login, /register, /privacy, /forgot-password, /api/company/Google)
- Full pass of deployment check utility
"""

import os
import json
import pytest
from pathlib import Path
from utils.deployment_check import (
    check_configuration_files,
    check_app_import_and_init,
    check_public_routes,
    run_deployment_check,
)


def test_vercel_configuration_files_exist():
    """Verify vercel.json and api/index.py exist and are structurally valid."""
    passed, issues = check_configuration_files()
    assert passed is True, f"Configuration file issues: {issues}"

    base_dir = Path(__file__).resolve().parent.parent
    vercel_json = base_dir / "vercel.json"
    with open(vercel_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "rewrites" in data
        assert any(r.get("destination") == "/api/index.py" for r in data["rewrites"])


def test_api_index_entrypoint():
    """Verify that api.index exports a valid WSGI Flask application callable."""
    from api.index import app as vercel_app
    from flask import Flask
    assert isinstance(vercel_app, Flask)
    assert vercel_app.name == "app"


def test_simulated_vercel_environment_app_init():
    """Verify that importing app in simulated Vercel mode creates directories safely."""
    passed, app_instance, errors = check_app_import_and_init(simulated_vercel=True)
    assert passed is True, f"App init errors: {errors}"
    assert app_instance is not None


def test_public_routes_respond_with_200():
    """Verify all critical public routes respond with HTTP 200 and expected content."""
    from app import app
    passed, results = check_public_routes(app)
    failed = [r for r in results if not r["passed"]]
    assert passed is True, f"Failed routes: {failed}"


def test_deployment_check_runner_returns_zero():
    """Verify the command-line deployment check returns exit code 0."""
    exit_code = run_deployment_check()
    assert exit_code == 0

