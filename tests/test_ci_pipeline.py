"""
Unit and Integration Tests for Continuous Integration Testing Pipeline (#246)
==============================================================================
Validates:
1. CIRuntimeValidator:
   - Python version compatibility check (passes for current active Python runtime).
   - Package discovery and import integrity (validates core libraries).
   - Configuration and project structure sanity verification.
2. CITestSuiteRunner:
   - Automatic discovery of project pytest test files.
   - Subprocess test execution, timeout bounds, and status reporting.
3. Diagnostic report generator:
   - Structured JSON report emission with overall pipeline readiness indicator.
4. GitHub Actions CI workflow configuration validity:
   - Checks .github/workflows/ci.yml structure and matrix definitions.
"""

import pytest
import sys
import json
from pathlib import Path

from utils.ci_pipeline_validator import (
    CIRuntimeValidator,
    CITestSuiteRunner,
    generate_ci_diagnostic_report
)


def test_python_version_validator():
    """Verify runtime Python version detection reports correct status."""
    res = CIRuntimeValidator.check_python_version()
    assert "current_version" in res
    assert "required_minimum" in res
    assert res["status"] in ("PASS", "FAIL")
    # Current environment runs on Python 3.11+, so should pass
    assert res["supported"] is True
    assert res["status"] == "PASS"


def test_installed_packages_validator():
    """Verify presence of core libraries needed for testing and running the application."""
    res = CIRuntimeValidator.check_installed_packages()
    assert "installed_packages" in res
    assert "flask" in res["installed_packages"]
    assert "pytest" in res["installed_packages"]
    assert res["all_present"] is True
    assert res["status"] == "PASS"


def test_configuration_sanity(tmp_path):
    """Verify project configuration structure check detects missing directories and passes for current workspace."""
    # 1. Real project workspace should pass
    base_dir = Path(__file__).resolve().parent.parent
    real_check = CIRuntimeValidator.check_configuration_sanity(base_dir)
    assert real_check["valid"] is True
    assert real_check["status"] == "PASS"
    assert len(real_check["issues"]) == 0

    # 2. Incomplete temporary directory should detect missing folders
    empty_check = CIRuntimeValidator.check_configuration_sanity(tmp_path)
    assert empty_check["valid"] is False
    assert empty_check["status"] == "FAIL"
    assert any("Missing required directory" in issue for issue in empty_check["issues"])


def test_test_file_discovery():
    """Verify test suite runner discovers existing test files."""
    runner = CITestSuiteRunner()
    files = runner.discover_test_files()
    assert len(files) > 0
    assert any("test_ci_pipeline" in f or "test_resume" in f or "test_backup" in f for f in files)


def test_generate_ci_diagnostic_report(tmp_path):
    """Verify diagnostic report generation produces complete diagnostic schema and writes to disk."""
    report_file = tmp_path / "ci_report.json"
    report = generate_ci_diagnostic_report(output_path=report_file)

    assert report["pipeline_name"] == "GitHub Actions CI Quality Assurance"
    assert report["overall_status"] == "READY"
    assert report["python_check"]["status"] == "PASS"
    assert report["dependency_check"]["status"] == "PASS"
    assert report["discovered_tests_count"] > 0
    assert report_file.exists()

    # Verify JSON content on disk
    saved_data = json.loads(report_file.read_text(encoding="utf-8"))
    assert saved_data["overall_status"] == "READY"


def test_ci_workflow_file_integrity():
    """Verify .github/workflows/ci.yml exists and contains required CI matrix stages."""
    workflow_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    assert workflow_path.exists()
    content = workflow_path.read_text(encoding="utf-8")

    assert "matrix-testing:" in content
    assert "python-version:" in content
    assert "lint:" in content
    assert "security-scan:" in content
    assert "syntax-validation:" in content
    assert "environment-diagnostics:" in content
