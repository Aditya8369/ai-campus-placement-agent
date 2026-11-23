"""
Unit & Integration Tests for Dependency Vulnerability Audit & Pinning (#649)
============================================================================
Validates:
1. Direct dependencies in requirements.txt declare explicit versions.
2. Direct pinning validation logic correctly identifies pinned (==) and unpinned packages.
3. Dependabot configuration (.github/dependabot.yml) defines weekly grouped updates
   for pip, github-actions, and npm.
4. Ignored advisories (.pip-audit-ignore.yml & .npm-audit-ignore.json) strictly enforce
   non-empty reasons and valid unexpired expiry dates.
5. Expired advisories fail validation in both ecosystems.
6. The Python audit runner detects and fails when an unhandled vulnerable package is found.
7. The JavaScript audit runner detects and fails when high/critical packages are found.
8. Development-only warnings and low-severity notices are filtered without breaking CI.
9. GitHub Step Summary report formats markdown tables properly.
"""

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from utils.dependency_audit import (
    check_direct_dependencies_pinned,
    validate_ignore_file,
    validate_npm_ignore_file,
    parse_ignore_yaml_lightweight,
    run_dependency_audit,
    run_npm_audit,
    format_github_step_summary,
)


def test_requirements_file_has_explicit_versions():
    """Verify that every direct dependency in requirements.txt specifies an explicit version requirement."""
    req_path = Path("requirements.txt")
    assert req_path.exists(), "requirements.txt must exist at the project root."

    lines = [
        line.strip()
        for line in req_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(lines) >= 5, "At least 5 core direct dependencies should be declared."
    for line in lines:
        assert "==" in line or ">=" in line or "<=" in line or "~=" in line, (
            f"Requirement '{line}' must declare an explicit version constraint."
        )


def test_check_direct_dependencies_pinned_logic(tmp_path):
    """Verify pinning checker differentiates between exact '==' pins and range/unpinned specifiers."""
    # Test pinned requirements
    pinned_file = tmp_path / "pinned.txt"
    pinned_file.write_text("Flask==3.0.3\nPyPDF2==3.0.1\nreportlab==4.2.2\n", encoding="utf-8")
    all_pinned, unpinned, pinned = check_direct_dependencies_pinned(pinned_file)
    assert all_pinned is True
    assert unpinned == []
    assert len(pinned) == 3

    # Test unpinned / range requirements
    unpinned_file = tmp_path / "unpinned.txt"
    unpinned_file.write_text("Flask>=3.0.0\nrequests\n", encoding="utf-8")
    all_pinned, unpinned, pinned = check_direct_dependencies_pinned(unpinned_file)
    assert all_pinned is False
    assert len(unpinned) == 2
    assert "Flask>=3.0.0" in unpinned
    assert "requests" in unpinned


def test_dependabot_configuration():
    """Verify .github/dependabot.yml exists and defines weekly grouped updates for pip, github-actions, and npm."""
    dep_path = Path(".github/dependabot.yml")
    assert dep_path.exists(), ".github/dependabot.yml must exist."

    content = dep_path.read_text(encoding="utf-8")
    assert "version: 2" in content

    # Check package ecosystems
    assert 'package-ecosystem: "github-actions"' in content or "package-ecosystem: 'github-actions'" in content or "package-ecosystem: github-actions" in content
    assert 'package-ecosystem: "pip"' in content or "package-ecosystem: 'pip'" in content or "package-ecosystem: pip" in content
    assert 'package-ecosystem: "npm"' in content or "package-ecosystem: 'npm'" in content or "package-ecosystem: npm" in content

    # Check weekly schedule interval
    assert 'interval: "weekly"' in content or "interval: 'weekly'" in content or "interval: weekly" in content

    # Check grouping of minor and patch updates
    assert "groups:" in content
    assert "update-types:" in content
    assert '"minor"' in content or "'minor'" in content or "- minor" in content
    assert '"patch"' in content or "'patch'" in content or "- patch" in content


def test_python_ignored_advisories_policy_enforcement(tmp_path):
    """Verify that ignored Python advisories strictly require both a written reason and an unexpired date."""
    today = dt.date(2026, 11, 21)

    # 1. Valid advisory entry
    valid_yaml = tmp_path / "valid_ignore.yml"
    valid_yaml.write_text("""
ignored_advisories:
  - id: "PYSEC-2026-9999"
    package: "sample-pkg"
    reason: "Upstream patch scheduled for Q1 release."
    expiry: "2026-12-31"
""", encoding="utf-8")

    is_valid, valid_entries, errors = validate_ignore_file(valid_yaml, reference_date=today)
    assert is_valid is True
    assert len(valid_entries) == 1
    assert errors == []
    assert valid_entries[0]["id"] == "PYSEC-2026-9999"
    assert valid_entries[0]["reason"] == "Upstream patch scheduled for Q1 release."

    # 2. Missing reason must fail
    missing_reason_yaml = tmp_path / "no_reason.yml"
    missing_reason_yaml.write_text("""
ignored_advisories:
  - id: "PYSEC-2026-9999"
    package: "sample-pkg"
    reason: ""
    expiry: "2026-12-31"
""", encoding="utf-8")

    is_valid, _, errors = validate_ignore_file(missing_reason_yaml, reference_date=today)
    assert is_valid is False
    assert any("Missing required 'reason'" in err for err in errors)

    # 3. Missing expiry must fail
    missing_expiry_yaml = tmp_path / "no_expiry.yml"
    missing_expiry_yaml.write_text("""
ignored_advisories:
  - id: "PYSEC-2026-9999"
    package: "sample-pkg"
    reason: "Some valid reason"
    expiry: ""
""", encoding="utf-8")

    is_valid, _, errors = validate_ignore_file(missing_expiry_yaml, reference_date=today)
    assert is_valid is False
    assert any("Missing required 'expiry'" in err for err in errors)

    # 4. Expired advisory must fail
    expired_yaml = tmp_path / "expired.yml"
    expired_yaml.write_text("""
ignored_advisories:
  - id: "PYSEC-2026-9999"
    package: "sample-pkg"
    reason: "Old waiver that was never updated"
    expiry: "2026-11-20"
""", encoding="utf-8")

    is_valid, _, errors = validate_ignore_file(expired_yaml, reference_date=today)
    assert is_valid is False
    assert any("EXPIRED on 2026-11-20" in err for err in errors)


def test_npm_ignored_advisories_policy_enforcement(tmp_path):
    """Verify that ignored NPM advisories strictly require both a written reason and an unexpired date."""
    today = dt.date(2026, 11, 21)

    # 1. Valid advisory entry
    valid_json = tmp_path / "valid_npm_ignore.json"
    valid_json.write_text(json.dumps({
        "ignored_advisories": [
            {
                "id": "GHSA-xxxx-yyyy-zzzz",
                "package": "sample-js-pkg",
                "reason": "Used only in isolated build step without user input.",
                "expiry": "2026-12-31"
            }
        ]
    }), encoding="utf-8")

    is_valid, valid_entries, errors = validate_npm_ignore_file(valid_json, reference_date=today)
    assert is_valid is True
    assert len(valid_entries) == 1
    assert errors == []
    assert valid_entries[0]["id"] == "GHSA-xxxx-yyyy-zzzz"

    # 2. Expired entry must fail
    expired_json = tmp_path / "expired_npm_ignore.json"
    expired_json.write_text(json.dumps({
        "ignored_advisories": [
            {
                "id": "GHSA-xxxx-yyyy-zzzz",
                "package": "sample-js-pkg",
                "reason": "Expired waiver",
                "expiry": "2026-11-15"
            }
        ]
    }), encoding="utf-8")

    is_valid, _, errors = validate_npm_ignore_file(expired_json, reference_date=today)
    assert is_valid is False
    assert any("EXPIRED on 2026-11-15" in err for err in errors)


def test_project_pip_audit_ignore_file_is_valid():
    """Verify that the project's actual .pip-audit-ignore.yml satisfies all policy rules."""
    actual_ignore = Path(".pip-audit-ignore.yml")
    assert actual_ignore.exists(), ".pip-audit-ignore.yml must exist at project root."

    is_valid, entries, errors = validate_ignore_file(actual_ignore)
    assert is_valid is True, f"Errors in .pip-audit-ignore.yml: {errors}"
    assert len(entries) > 0, ".pip-audit-ignore.yml should contain valid documented entries."
    for e in entries:
        assert e["reason"], f"Entry {e['id']} must have a non-empty reason."
        assert e["expiry"], f"Entry {e['id']} must have an expiry date."


def test_project_npm_audit_ignore_file_is_valid():
    """Verify that the project's actual .npm-audit-ignore.json satisfies all policy rules."""
    actual_ignore = Path(".npm-audit-ignore.json")
    assert actual_ignore.exists(), ".npm-audit-ignore.json must exist at project root."

    is_valid, entries, errors = validate_npm_ignore_file(actual_ignore)
    assert is_valid is True, f"Errors in .npm-audit-ignore.json: {errors}"


def test_audit_fails_on_vulnerable_python_package(tmp_path):
    """Verify that the audit runner detects and fails when an unhandled vulnerable package is found."""
    test_req = tmp_path / "test_vulnerable_requirements.txt"
    test_req.write_text("urllib3==1.26.4\n", encoding="utf-8")

    empty_ignore = tmp_path / "empty_ignore.yml"
    empty_ignore.write_text("ignored_advisories: []\n", encoding="utf-8")

    fake_json_output = json.dumps({
        "dependencies": [
            {
                "name": "urllib3",
                "version": "1.26.4",
                "vulns": [
                    {
                        "id": "PYSEC-2021-108",
                        "fix_versions": ["1.26.5"],
                        "description": "CRLF injection vulnerability",
                        "aliases": ["CVE-2021-33503"],
                    }
                ],
            }
        ],
        "fixes": [],
    })

    fake_proc = subprocess.CompletedProcess(
        args=["pip-audit"],
        returncode=1,
        stdout=fake_json_output,
        stderr="Found 1 known vulnerability\n",
    )

    with patch("subprocess.run", return_value=fake_proc):
        result = run_dependency_audit(
            requirements_path=test_req,
            ignore_file_path=empty_ignore,
        )

    assert result["success"] is False, "Audit should fail on vulnerable package urllib3==1.26.4"
    assert result["exit_code"] != 0
    assert len(result["vulnerabilities"]) > 0
    package_names = [v.get("package") for v in result["vulnerabilities"]]
    assert "urllib3" in package_names
    assert result["vulnerabilities"][0]["id"] == "PYSEC-2021-108"


def test_audit_passes_when_no_python_vulnerabilities(tmp_path):
    """Verify that the audit runner succeeds with code 0 when no unhandled vulnerabilities exist."""
    test_req = tmp_path / "clean_requirements.txt"
    test_req.write_text("Flask==3.0.3\n", encoding="utf-8")

    fake_json_output = json.dumps({
        "dependencies": [
            {"name": "Flask", "version": "3.0.3", "vulns": []}
        ],
        "fixes": [],
    })

    fake_proc = subprocess.CompletedProcess(
        args=["pip-audit"],
        returncode=0,
        stdout=fake_json_output,
        stderr="No known vulnerabilities found\n",
    )

    with patch("subprocess.run", return_value=fake_proc):
        result = run_dependency_audit(
            requirements_path=test_req,
            ignore_file_path=tmp_path / "non_existent_ignore.yml",
        )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert len(result["vulnerabilities"]) == 0


def test_npm_audit_detection_and_dev_filtering(tmp_path):
    """Verify that npm audit catches high vulnerabilities while filtering low/dev warnings."""
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(json.dumps({"name": "test-pkg", "dependencies": {"vulnerable-lib": "1.0.0"}}), encoding="utf-8")

    fake_npm_json = json.dumps({
        "vulnerabilities": {
            "vulnerable-lib": {
                "name": "vulnerable-lib",
                "severity": "high",
                "isDirect": True,
                "via": [
                    {
                        "source": "GHSA-1234-5678",
                        "name": "vulnerable-lib",
                        "title": "Remote code execution in vulnerable-lib",
                        "url": "https://github.com/advisories/GHSA-1234-5678",
                        "severity": "high",
                    }
                ],
                "fixAvailable": True,
            },
            "dev-tool": {
                "name": "dev-tool",
                "severity": "low",
                "isDirect": False,
                "via": [
                    {
                        "source": "GHSA-0000-0000",
                        "name": "dev-tool",
                        "title": "Minor prototype pollution",
                        "url": "https://github.com/advisories/GHSA-0000-0000",
                        "severity": "low",
                    }
                ],
                "fixAvailable": False,
            }
        }
    })

    fake_proc = subprocess.CompletedProcess(
        args=["npm", "audit", "--json", "--omit=dev"],
        returncode=1,
        stdout=fake_npm_json,
        stderr="",
    )

    with patch("shutil.which", return_value="npm"), patch("subprocess.run", return_value=fake_proc):
        result = run_npm_audit(
            package_json_path=pkg_file,
            ignore_file_path=tmp_path / "empty_ignore.json",
            audit_level="high",
            omit_dev=True,
        )

    assert result["success"] is False
    assert len(result["vulnerabilities"]) == 1
    assert result["vulnerabilities"][0]["package"] == "vulnerable-lib"
    assert result["vulnerabilities"][0]["severity"] == "high"
    # Low severity item should be filtered out without causing failure
    assert result["filtered_dev_warnings"] == 1


def test_format_github_step_summary():
    """Verify that the GitHub Step Summary markdown is properly formatted."""
    py_res = {
        "success": True,
        "vulnerabilities": [],
        "ignored_count": 2,
    }
    npm_res = {
        "success": True,
        "vulnerabilities": [],
        "filtered_dev_warnings": 1,
        "ignored_count": 0,
    }

    markdown = format_github_step_summary(py_res, npm_res)
    assert "Automated Dependency Vulnerability Scan Report" in markdown
    assert "Python Dependencies (`requirements.txt`)" in markdown
    assert "JavaScript Dependencies (`package.json`)" in markdown
    assert "Development Warnings Policy & Guidance" in markdown
    assert "PASSED" in markdown
