"""
Unit & Integration Tests for Dependency Vulnerability Audit & Pinning (#649)
============================================================================
Validates:
1. All direct dependencies in requirements.txt are pinned to exact versions (==).
2. Dependabot configuration (.github/dependabot.yml) exists with weekly grouping for pip and github-actions.
3. Ignored advisories (.pip-audit-ignore.yml) strictly enforce non-empty reason and valid expiry date.
4. Expired advisories fail validation.
5. The audit runner fails when a vulnerable test package is encountered.
6. The audit runner succeeds when running on valid pinned requirements.
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
    parse_ignore_yaml_lightweight,
    run_dependency_audit,
)


def test_all_direct_dependencies_pinned():
    """Verify that every direct dependency in requirements.txt is pinned to an exact version (==)."""
    req_path = Path("requirements.txt")
    assert req_path.exists(), "requirements.txt must exist at the project root."

    all_pinned, unpinned, pinned = check_direct_dependencies_pinned(req_path)
    assert unpinned == [], f"Unpinned dependencies found: {unpinned}. All dependencies must use exact '==' pins."
    assert all_pinned is True
    assert len(pinned) >= 5, "At least 5 core direct dependencies should be declared and pinned."

    # Verify no inequality or range operators appear in active requirement lines
    lines = [
        line.strip()
        for line in req_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for line in lines:
        assert "==" in line, f"Requirement '{line}' must be pinned with '=='."
        assert ">=" not in line, f"Requirement '{line}' must not use '>='."
        assert "<=" not in line, f"Requirement '{line}' must not use '<='."
        assert "~=" not in line, f"Requirement '{line}' must not use '~='."


def test_dependabot_configuration():
    """Verify .github/dependabot.yml exists and defines weekly grouped updates for pip and github-actions."""
    dep_path = Path(".github/dependabot.yml")
    assert dep_path.exists(), ".github/dependabot.yml must exist."

    content = dep_path.read_text(encoding="utf-8")
    assert "version: 2" in content

    # Check package ecosystems
    assert 'package-ecosystem: "github-actions"' in content or "package-ecosystem: 'github-actions'" in content or "package-ecosystem: github-actions" in content
    assert 'package-ecosystem: "pip"' in content or "package-ecosystem: 'pip'" in content or "package-ecosystem: pip" in content

    # Check weekly schedule interval
    assert 'interval: "weekly"' in content or "interval: 'weekly'" in content or "interval: weekly" in content

    # Check grouping of minor and patch updates
    assert "groups:" in content
    assert "update-types:" in content
    assert '"minor"' in content or "'minor'" in content or "- minor" in content
    assert '"patch"' in content or "'patch'" in content or "- patch" in content


def test_ignored_advisories_policy_enforcement(tmp_path):
    """Verify that ignored advisories strictly require both a written reason and an unexpired date."""
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


def test_audit_fails_on_vulnerable_package(tmp_path):
    """
    Acceptance Criteria: Verify that the audit runner detects and fails
    when presented with a requirements file containing an unhandled vulnerable package.
    """
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

    # Must fail because urllib3 1.26.4 has known unhandled vulnerabilities
    assert result["success"] is False, "Audit should fail on vulnerable package urllib3==1.26.4"
    assert result["exit_code"] != 0
    assert len(result["vulnerabilities"]) > 0
    package_names = [v.get("package") for v in result["vulnerabilities"]]
    assert "urllib3" in package_names
    assert result["vulnerabilities"][0]["id"] == "PYSEC-2021-108"


def test_audit_passes_when_no_vulnerabilities(tmp_path):
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
