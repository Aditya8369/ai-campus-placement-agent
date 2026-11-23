import pytest
from utils.application_archive_service import (
    archive_application,
    restore_application,
    renew_application
)
from db.connection import get_db_connection

def test_archive_and_restore_application():
    user = "student_arch_1"
    app_id = "app_test_arch_001"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_applications WHERE id = ?", (app_id,))
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, is_archived, cycle_number)
            VALUES (?, ?, 'Google', 'SDE', 'Applied', '2026-01-01', 0, 1)
        """, (app_id, user))
        conn.commit()

    # Archive
    assert archive_application(app_id, user) is True

    # Restore
    assert restore_application(app_id, user) is True

    # Renew
    renewed = renew_application(app_id, user)
    assert renewed is not None
    assert renewed["cycle_number"] == 2

def test_archive_api(client):
    app_id = "app_api_arch_002"
    user = "default_student"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_applications WHERE id = ?", (app_id,))
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, is_archived, cycle_number)
            VALUES (?, ?, 'Amazon', 'SDE', 'Applied', '2026-01-01', 0, 1)
        """, (app_id, user))
        conn.commit()

    # Archive via API
    res = client.post(f"/api/applications/{app_id}/archive")
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"

    # Renew via API
    renew_res = client.post(f"/api/applications/{app_id}/renew")
    assert renew_res.status_code == 200
    assert renew_res.get_json()["status"] == "success"
