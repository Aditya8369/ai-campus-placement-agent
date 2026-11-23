import pytest
from utils.account_merge_service import preview_account_merge, execute_account_merge
from db.connection import get_db_connection

def test_account_merge():
    u1 = "user_primary_merge"
    u2 = "user_secondary_merge"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_applications WHERE student_id IN (?, ?)", (u1, u2))
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date)
            VALUES ('app_merge_1', ?, 'Google', 'SDE', 'Applied', '2026-01-01')
        """, (u2,))
        conn.commit()

    preview = preview_account_merge(u1, u2)
    assert preview["success"] is True
    assert preview["transferable_records"]["job_applications"] == 1

    # Unverified merge fails
    fail_merge = execute_account_merge(u1, u2, verified_token=False)
    assert fail_merge["success"] is False

    # Verified merge succeeds
    merged = execute_account_merge(u1, u2, verified_token=True)
    assert merged["success"] is True
    assert merged["transferred_applications"] == 1

def test_account_merge_api(client):
    res = client.post("/api/account/merge/preview", json={
        "primary_user_id": "u1",
        "secondary_user_id": "u2"
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
