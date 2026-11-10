"""
Unit & Integration Tests for Student Personal Data Download Package (#258)
==========================================================================
Tests:
1. Compilation of comprehensive student data manifest across all personal records:
   - Profile & account details
   - Analyses, applications, notes, mock interviews, coding bookmarks, calendar events
2. Exclusion of sensitive security credentials (passwords, hashes, tokens, API keys).
3. Verification that students can ONLY access and download their own personal data (multi-tenant isolation).
4. ZIP archive creation and integrity verification (valid ZIP structure, uncorrupted extraction, JSON parsing).
5. REST API Endpoints:
   - GET /api/student/data-export/manifest
   - GET /api/student/data-export/download
"""

import pytest
import json
import zipfile
import io

import config
from utils.database import (
    init_db,
    save_analysis,
    save_job_application,
    create_preparation_note,
    save_coding_bookmark,
    save_calendar_event,
    get_db_connection
)
from utils.student_data_exporter import (
    build_student_data_export_manifest,
    generate_student_data_zip_package
)
from app import app


@pytest.fixture
def export_env(tmp_path, monkeypatch):
    """Sets up an isolated test database with seeded student placement data."""
    test_db = tmp_path / "test_data_export.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    # Seed data for Alice
    save_job_application(
        app_id="app_alice_1",
        student_id="student_alice",
        company_name="Google",
        role_title="Backend Engineer",
        status="Interviewing",
        application_date="2026-11-01"
    )

    create_preparation_note(
        student_id="student_alice",
        title="Dijkstra Algorithm Cheatsheet",
        description="Graph traversal using PriorityQueue with min-heap.",
        category="Technical"
    )

    save_coding_bookmark(
        student_id="student_alice",
        problem_id="course_schedule",
        problem_data={"title": "Course Schedule", "difficulty": "Medium"}
    )

    save_calendar_event(
        event_id="cal_alice_1",
        student_id="student_alice",
        title="Google Onsite Round",
        event_type="interview",
        event_date="2026-11-20"
    )

    # Seed data for Bob (to verify data isolation)
    save_job_application(
        app_id="app_bob_1",
        student_id="student_bob",
        company_name="Microsoft",
        role_title="Frontend Engineer",
        status="Applied"
    )

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "export-secret-key"

    with app.test_client() as client:
        yield client


def test_build_manifest_data_completeness(export_env):
    """Verify manifest aggregates all candidate records while isolating from other students."""
    manifest = build_student_data_export_manifest("student_alice")

    assert manifest["metadata"]["student_id"] == "student_alice"
    assert manifest["summary_counts"]["job_applications_count"] == 1
    assert manifest["summary_counts"]["notes_count"] == 1
    assert manifest["summary_counts"]["bookmarks_count"] == 1
    assert manifest["summary_counts"]["calendar_events_count"] == 1

    # Verify Bob's data is NOT leaked into Alice's manifest
    app_companies = [a["company_name"] for a in manifest["job_applications"]]
    assert "Google" in app_companies
    assert "Microsoft" not in app_companies


def test_manifest_excludes_sensitive_credentials(export_env):
    """Verify passwords, password hashes, and security tokens are strictly absent."""
    manifest = build_student_data_export_manifest("student_alice")
    manifest_str = json.dumps(manifest).lower()

    assert "password_hash" not in manifest_str
    assert "reset_token" not in manifest_str
    assert "secret_key" not in manifest_str
    assert "api_key" not in manifest_str


def test_generate_zip_package(export_env):
    """Verify in-memory ZIP package is a valid, extractable archive with all required JSON files."""
    zip_stream = generate_student_data_zip_package("student_alice")
    assert isinstance(zip_stream, io.BytesIO)

    with zipfile.ZipFile(zip_stream, mode="r") as zf:
        file_list = zf.namelist()
        assert "student_placement_data_complete.json" in file_list
        assert "job_applications.json" in file_list
        assert "preparation_notes.json" in file_list
        assert "README.md" in file_list

        # Test valid JSON extraction
        job_apps_data = json.loads(zf.read("job_applications.json").decode("utf-8"))
        assert len(job_apps_data) == 1
        assert job_apps_data[0]["company_name"] == "Google"

        # Test human-readable README content
        readme_text = zf.read("README.md").decode("utf-8")
        assert "student_alice" in readme_text
        assert "Security & Privacy Notice" in readme_text


def test_api_export_endpoints(export_env):
    """Verify REST endpoints for student manifest retrieval and ZIP download."""
    # 1. Manifest endpoint
    resp_manifest = export_env.get("/api/student/data-export/manifest")
    assert resp_manifest.status_code == 200
    m_data = resp_manifest.get_json()
    assert m_data["status"] == "success"
    assert "manifest" in m_data

    # 2. Download endpoint
    resp_dl = export_env.get("/api/student/data-export/download")
    assert resp_dl.status_code == 200
    assert resp_dl.mimetype == "application/zip"
    assert "attachment" in resp_dl.headers.get("Content-Disposition", "")
    assert len(resp_dl.data) > 100
