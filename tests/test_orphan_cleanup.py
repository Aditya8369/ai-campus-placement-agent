"""
Unit tests for Orphaned File Cleanup Service (#352).
"""

import os
import time
from pathlib import Path
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.orphan_cleanup_service import (
    get_active_referenced_filenames,
    is_file_orphaned,
    cleanup_orphaned_files
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def temp_storage_dirs(tmp_path):
    upload_dir = tmp_path / "uploads"
    report_dir = tmp_path / "reports"
    upload_dir.mkdir()
    report_dir.mkdir()
    return upload_dir, report_dir


def test_get_active_referenced_filenames():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-orphan-%'")
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES ('test-orphan-aid-1', 'student-1', 'active_resume_sample.pdf', 'Google', 'SWE', '{}')
        """
    )
    conn.commit()
    conn.close()

    refs = get_active_referenced_filenames()
    assert "active_resume_sample.pdf" in refs
    assert "test-orphan-aid-1" in refs

    # Clean up
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analyses WHERE id = 'test-orphan-aid-1'")
    conn.commit()
    conn.close()


def test_is_file_orphaned(tmp_path):
    active_refs = {"active_resume.pdf", "aid-12345678"}

    # 1. Active file (referenced)
    active_file = tmp_path / "active_resume.pdf"
    active_file.write_text("dummy")
    # Backdate mtime
    os.utime(active_file, (time.time() - 3600, time.time() - 3600))
    assert is_file_orphaned(active_file, active_refs, min_age_seconds=1800) is False

    # 2. In-flight upload (orphaned by reference, but too young < 30 mins)
    recent_file = tmp_path / "recent_upload.pdf"
    recent_file.write_text("in-flight")
    # Current time
    assert is_file_orphaned(recent_file, active_refs, min_age_seconds=1800) is False

    # 3. Report containing active analysis ID
    report_file = tmp_path / "report_aid-12345678.pdf"
    report_file.write_text("report content")
    os.utime(report_file, (time.time() - 3600, time.time() - 3600))
    assert is_file_orphaned(report_file, active_refs, min_age_seconds=1800) is False

    # 4. Confirmed orphaned file (old, unreferenced)
    orphan_file = tmp_path / "abandoned_resume.pdf"
    orphan_file.write_text("abandoned")
    os.utime(orphan_file, (time.time() - 3600, time.time() - 3600))
    assert is_file_orphaned(orphan_file, active_refs, min_age_seconds=1800) is True


def test_cleanup_orphaned_files_dry_run_and_execution(temp_storage_dirs):
    upload_dir, report_dir = temp_storage_dirs
    active_refs = {"valid_user_resume.pdf"}

    # Seed active file
    valid_file = upload_dir / "valid_user_resume.pdf"
    valid_file.write_text("valid content")
    os.utime(valid_file, (time.time() - 3600, time.time() - 3600))

    # Seed orphaned file in uploads
    orphan_upload = upload_dir / "leftover_abandoned.pdf"
    orphan_upload.write_text("garbage content")
    os.utime(orphan_upload, (time.time() - 3600, time.time() - 3600))

    # Seed orphaned report
    orphan_report = report_dir / "dead_analysis_report.pdf"
    orphan_report.write_text("orphan report content")
    os.utime(orphan_report, (time.time() - 3600, time.time() - 3600))

    # Run dry run
    dry_stats = cleanup_orphaned_files(
        min_age_minutes=10,
        dry_run=True,
        target_dirs=[upload_dir, report_dir]
    )
    assert dry_stats["scanned_files"] == 3
    assert dry_stats["orphaned_files_found"] == 2
    assert dry_stats["orphaned_files_deleted"] == 0
    assert orphan_upload.exists()
    assert orphan_report.exists()
    assert valid_file.exists()

    # Run actual deletion
    del_stats = cleanup_orphaned_files(
        min_age_minutes=10,
        dry_run=False,
        target_dirs=[upload_dir, report_dir]
    )
    assert del_stats["orphaned_files_deleted"] == 2
    assert not orphan_upload.exists()
    assert not orphan_report.exists()
    # Active file MUST never be deleted
    assert valid_file.exists()


def test_api_admin_cleanup_orphaned_files_endpoint(client):
    res = client.post("/api/admin/cleanup-orphaned-files", json={"dry_run": True, "min_age_minutes": 60})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "orphaned_files_found" in data
    assert data["dry_run"] is True
