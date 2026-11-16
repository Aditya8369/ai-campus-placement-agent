"""
Unit tests for User Storage Limits and Quota Management Service (#353).
"""

import os
from pathlib import Path
import pytest
from app import app
from utils.database import get_db_connection, init_db
from utils.storage_quota_service import (
    calculate_user_storage_usage,
    check_upload_quota,
    get_user_storage_summary
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_quota_test_db():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analyses WHERE student_id LIKE 'test-quota-%'")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analyses WHERE student_id LIKE 'test-quota-%'")
    conn.commit()
    conn.close()


def test_calculate_user_storage_usage_empty():
    usage = calculate_user_storage_usage("test-quota-empty-student")
    assert usage["resumes_count"] == 0
    assert usage["total_bytes_used"] == 0
    assert usage["total_mb_used"] == 0.0


def test_check_upload_quota_file_too_large():
    # Pass a 10MB file when max allowed is 5MB
    incoming_size = 10 * 1024 * 1024
    allowed, err = check_upload_quota(
        student_id="test-quota-student-1",
        incoming_file_size_bytes=incoming_size,
        custom_limits={"max_upload_size_bytes": 5 * 1024 * 1024}
    )
    assert allowed is False
    assert "exceeds maximum allowed upload size" in err


def test_check_upload_quota_resume_count_exceeded():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Insert 3 analyses for this student
    for i in range(3):
        cursor.execute(
            """
            INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
            VALUES (?, 'test-quota-student-limit', 'resume.pdf', 'Company', 'Role', '{}')
            """,
            (f"quota-aid-{i}",)
        )
    conn.commit()
    conn.close()

    # If limit is 3, attempting 4th upload should be rejected
    allowed, err = check_upload_quota(
        student_id="test-quota-student-limit",
        incoming_file_size_bytes=1000,
        custom_limits={"max_resumes_per_user": 3}
    )
    assert allowed is False
    assert "Account resume limit reached" in err


def test_check_upload_quota_within_limits():
    allowed, err = check_upload_quota(
        student_id="test-quota-student-ok",
        incoming_file_size_bytes=500000,
        custom_limits={"max_upload_size_bytes": 5 * 1024 * 1024, "max_resumes_per_user": 10}
    )
    assert allowed is True
    assert err is None


def test_get_user_storage_summary_and_api(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "test-quota-api-user"

    res = client.get("/api/user/storage-quota")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "limits" in data
    assert "usage" in data
    assert "utilization_percentage" in data
    assert data["limits"]["max_upload_size_mb"] > 0


def test_format_storage_size_human():
    from utils.storage_quota_service import format_storage_size_human
    assert format_storage_size_human(500) == "500 B"
    assert "KB" in format_storage_size_human(2048)
    assert "MB" in format_storage_size_human(5 * 1024 * 1024)
    assert "GB" in format_storage_size_human(2 * 1024 * 1024 * 1024)


def test_can_generate_report():
    from utils.storage_quota_service import can_generate_report
    allowed, err = can_generate_report("test-quota-free-user", custom_max_reports=10)
    assert allowed is True
    assert err is None


def test_can_generate_report_blocked_when_limit_reached(monkeypatch):
    from utils.storage_quota_service import can_generate_report
    import utils.storage_quota_service as sqs

    # Monkeypatch usage to simulate user with max reports
    monkeypatch.setattr(
        sqs,
        "calculate_user_storage_usage",
        lambda sid: {"resumes_count": 5, "reports_count": 20, "total_bytes_used": 1000000, "total_mb_used": 1.0}
    )
    allowed, err = can_generate_report("test-user-full", custom_max_reports=20)
    assert allowed is False
    assert "report generation limit reached" in err


