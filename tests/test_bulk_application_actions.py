"""
Unit and integration tests for Bulk Job Application Actions (#848).

Acceptance Criteria:
1. Selected rows are updated or deleted in one request.
2. Other users' rows can never be changed by sending their IDs (strict ownership).
3. CSV cells beginning with =, +, - or @ are escaped (formula injection protection).
4. Tests cover ownership, limits and escaping.
"""

import csv
import io
import tempfile
import uuid
from pathlib import Path
import pytest

import config
from app import app
from utils.database import (
    init_db,
    save_job_application,
    get_job_application_by_id,
    get_job_applications,
    MAX_BULK_BATCH_SIZE,
    escape_csv_cell,
    bulk_update_application_status,
    bulk_add_application_tag,
    bulk_delete_applications,
    bulk_export_applications_csv,
)


@pytest.fixture
def test_client(monkeypatch):
    """Provides a Flask test client with an isolated SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "UPLOAD_FOLDER", Path(tmpdir) / "uploads")
        monkeypatch.setattr(config, "REPORT_FOLDER", Path(tmpdir) / "reports")
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        config.REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
        init_db()

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def seeded_applications(test_client):
    """Creates sample applications for two distinct students (student_1 and student_2)."""
    # Student 1 applications
    s1_ids = []
    for comp in ["Google", "Amazon", "Microsoft", "Meta"]:
        aid = str(uuid.uuid4())
        save_job_application(
            app_id=aid,
            student_id="student_1",
            company_name=comp,
            role_title="Software Engineer",
            status="Applied",
            application_date="2026-11-20",
        )
        s1_ids.append(aid)

    # Student 2 applications (unauthorized target)
    s2_ids = []
    for comp in ["Apple", "Netflix"]:
        aid = str(uuid.uuid4())
        save_job_application(
            app_id=aid,
            student_id="student_2",
            company_name=comp,
            role_title="Data Scientist",
            status="Applied",
            application_date="2026-11-20",
        )
        s2_ids.append(aid)

    return {"student_1_ids": s1_ids, "student_2_ids": s2_ids}


# ==============================================================================
# Unit Tests: CSV Formula Injection Escaping (#848)
# ==============================================================================

def test_csv_formula_escaping_dangerous_characters():
    """Acceptance criterion: CSV cells beginning with =, +, - or @ are escaped."""
    assert escape_csv_cell("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert escape_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert escape_csv_cell("+123456789") == "'+123456789"
    assert escape_csv_cell("-1000") == "'-1000"
    assert escape_csv_cell("@username") == "'@username"
    assert escape_csv_cell("  =HYPERLINK(...)") == "'  =HYPERLINK(...)"


def test_csv_formula_escaping_safe_characters():
    """Cells with safe content remain unaltered."""
    assert escape_csv_cell("Google") == "Google"
    assert escape_csv_cell("Software Development Engineer") == "Software Development Engineer"
    assert escape_csv_cell("") == ""
    assert escape_csv_cell(None) == ""
    assert escape_csv_cell("Applied") == "Applied"
    assert escape_csv_cell(42) == "42"


def test_bulk_csv_export_escapes_injected_formulas(seeded_applications):
    """Verify that export of applications with dangerous characters has escaped cells."""
    s1_ids = seeded_applications["student_1_ids"]
    # Update one application with formula injection in company name and notes
    save_job_application(
        app_id=s1_ids[0],
        student_id="student_1",
        company_name="=MALICIOUS_EXEC()",
        role_title="+PAYLOAD",
        notes="@ATTACKER_NOTE",
        status="Applied",
    )

    csv_text = bulk_export_applications_csv(s1_ids[:2], student_id="student_1")
    assert csv_text is not None
    assert "'=MALICIOUS_EXEC()" in csv_text
    assert "'+PAYLOAD" in csv_text
    assert "'@ATTACKER_NOTE" in csv_text


# ==============================================================================
# Unit Tests: Batch Operations & Ownership (#848)
# ==============================================================================

def test_bulk_status_update_in_one_request(seeded_applications):
    """Acceptance criterion: Selected rows are updated in one request."""
    s1_ids = seeded_applications["student_1_ids"]
    target_ids = s1_ids[:3]

    res = bulk_update_application_status(target_ids, student_id="student_1", new_status="Interview")
    assert res["success"] is True
    assert res["affected_count"] == 3
    assert "Updated status to 'Interview' for 3 applications." in res["message"]

    # Verify each was updated
    for aid in target_ids:
        app_rec = get_job_application_by_id(aid, "student_1")
        assert app_rec["status"] == "Interview"

    # Untargeted 4th application remains 'Applied'
    untargeted = get_job_application_by_id(s1_ids[3], "student_1")
    assert untargeted["status"] == "Applied"


def test_bulk_status_update_enforces_strict_ownership(seeded_applications):
    """Acceptance criterion: Other users' rows can never be changed by sending their IDs."""
    s1_ids = seeded_applications["student_1_ids"]
    s2_ids = seeded_applications["student_2_ids"]

    # Student 1 attempts to update their own + Student 2's IDs
    mixed_ids = [s1_ids[0], s2_ids[0], s2_ids[1]]

    res = bulk_update_application_status(mixed_ids, student_id="student_1", new_status="Selected")
    assert res["success"] is True
    assert res["affected_count"] == 1  # Only student 1's single record was updated!

    # Verify student 1's record changed
    s1_app = get_job_application_by_id(s1_ids[0], "student_1")
    assert s1_app["status"] == "Selected"

    # Verify student 2's records are untouched
    for s2_aid in s2_ids:
        s2_app = get_job_application_by_id(s2_aid, "student_2")
        assert s2_app["status"] == "Applied"


def test_bulk_add_tag_to_selected_applications(seeded_applications):
    """Verify adding tags to multiple applications in one request without duplication."""
    s1_ids = seeded_applications["student_1_ids"]
    target_ids = s1_ids[:2]

    # Add tag "Dream"
    res1 = bulk_add_application_tag(target_ids, student_id="student_1", tag="Dream")
    assert res1["success"] is True
    assert res1["affected_count"] == 2
    assert "Added tag 'Dream' to 2 applications." in res1["message"]

    for aid in target_ids:
        rec = get_job_application_by_id(aid, "student_1")
        assert "Dream" in rec["tags"]

    # Add second tag "Tier 1"
    res2 = bulk_add_application_tag(target_ids, student_id="student_1", tag="Tier 1")
    assert res2["success"] is True
    for aid in target_ids:
        rec = get_job_application_by_id(aid, "student_1")
        assert "Dream" in rec["tags"]
        assert "Tier 1" in rec["tags"]


def test_bulk_tagging_enforces_strict_ownership(seeded_applications):
    """Student cannot tag another user's application."""
    s2_ids = seeded_applications["student_2_ids"]

    res = bulk_add_application_tag(s2_ids, student_id="student_1", tag="Hacked")
    assert res["affected_count"] == 0

    # Student 2's applications have no tags
    for aid in s2_ids:
        rec = get_job_application_by_id(aid, "student_2")
        assert not rec.get("tags")


def test_bulk_delete_in_one_request(seeded_applications):
    """Acceptance criterion: Selected rows are deleted in one request."""
    s1_ids = seeded_applications["student_1_ids"]
    to_delete = s1_ids[:2]

    res = bulk_delete_applications(to_delete, student_id="student_1")
    assert res["success"] is True
    assert res["affected_count"] == 2
    assert "Deleted 2 applications." in res["message"]

    # Verify deleted
    assert get_job_application_by_id(to_delete[0], "student_1") is None
    assert get_job_application_by_id(to_delete[1], "student_1") is None

    # Remaining applications for student 1 still exist
    assert get_job_application_by_id(s1_ids[2], "student_1") is not None


def test_bulk_delete_enforces_strict_ownership(seeded_applications):
    """Student cannot delete another user's applications."""
    s1_ids = seeded_applications["student_1_ids"]
    s2_ids = seeded_applications["student_2_ids"]

    # Student 1 tries to delete Student 2's application
    res = bulk_delete_applications(s2_ids, student_id="student_1")
    assert res["affected_count"] == 0

    # Student 2's applications are intact
    assert get_job_application_by_id(s2_ids[0], "student_2") is not None
    assert get_job_application_by_id(s2_ids[1], "student_2") is not None


def test_batch_size_limit_enforced():
    """Acceptance criterion: Limit batch size (max 100)."""
    large_batch = [f"app-{i}" for i in range(MAX_BULK_BATCH_SIZE + 10)]

    res_status = bulk_update_application_status(large_batch, "student_1", "Rejected")
    assert res_status["success"] is False
    assert f"Batch size exceeds maximum limit of {MAX_BULK_BATCH_SIZE}" in res_status["error"]

    res_delete = bulk_delete_applications(large_batch, "student_1")
    assert res_delete["success"] is False
    assert f"Batch size exceeds maximum limit of {MAX_BULK_BATCH_SIZE}" in res_delete["error"]

    res_tag = bulk_add_application_tag(large_batch, "student_1", "Test")
    assert res_tag["success"] is False
    assert f"Batch size exceeds maximum limit of {MAX_BULK_BATCH_SIZE}" in res_tag["error"]

    with pytest.raises(ValueError, match="Batch size exceeds maximum limit"):
        bulk_export_applications_csv(large_batch, "student_1")


# ==============================================================================
# API Endpoint Integration Tests (#848)
# ==============================================================================

def test_api_bulk_status_update(test_client, seeded_applications):
    """POST /api/applications/bulk update status endpoint."""
    s1_ids = seeded_applications["student_1_ids"]
    target_ids = s1_ids[:2]

    res = test_client.post(
        "/api/applications/bulk",
        json={
            "action": "status",
            "status": "Assessment",
            "application_ids": target_ids,
            "student_id": "student_1",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["affected_count"] == 2
    assert "Assessment" in data["message"]


def test_api_bulk_tag(test_client, seeded_applications):
    """POST /api/applications/bulk add tag endpoint."""
    s1_ids = seeded_applications["student_1_ids"]

    res = test_client.post(
        "/api/applications/bulk",
        json={
            "action": "tag",
            "tag": "Dream Company",
            "application_ids": s1_ids[:2],
            "student_id": "student_1",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["affected_count"] == 2
    assert "Dream Company" in data["message"]


def test_api_bulk_delete(test_client, seeded_applications):
    """POST /api/applications/bulk delete endpoint."""
    s1_ids = seeded_applications["student_1_ids"]

    res = test_client.post(
        "/api/applications/bulk",
        json={
            "action": "delete",
            "application_ids": [s1_ids[0]],
            "student_id": "student_1",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["affected_count"] == 1


def test_api_bulk_export_csv_escapes_formulas(test_client, seeded_applications):
    """POST /api/applications/bulk/export returns downloadable CSV with escaped formulas."""
    s1_ids = seeded_applications["student_1_ids"]

    # Seed formula into company name
    save_job_application(
        app_id=s1_ids[0],
        student_id="student_1",
        company_name="=1+1",
        role_title="-PAYLOAD",
        status="Applied",
    )

    res = test_client.post(
        "/api/applications/bulk/export",
        json={
            "application_ids": [s1_ids[0], s1_ids[1]],
            "student_id": "student_1",
        },
    )
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    csv_text = res.get_data(as_text=True)

    # Formulas must be escaped with single quote
    assert "'=1+1" in csv_text
    assert "'-PAYLOAD" in csv_text


def test_api_bulk_batch_size_limit_rejection(test_client):
    """POST /api/applications/bulk rejects batches exceeding 100."""
    huge_ids = [f"id-{i}" for i in range(101)]

    res = test_client.post(
        "/api/applications/bulk",
        json={
            "action": "status",
            "status": "Applied",
            "application_ids": huge_ids,
            "student_id": "student_1",
        },
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "Batch size exceeds" in data["error"]
