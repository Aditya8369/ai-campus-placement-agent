"""
Unit tests for Bulk Application Actions (#522).
"""

import json
import sqlite3
import pytest
from app import create_app
from utils.bulk_applications_service import BulkApplicationsService, _get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def _seed_test_applications(user_id: str) -> list:
    conn = _get_db_connection()
    ids = []
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    job_title TEXT NOT NULL,
                    status TEXT DEFAULT 'applied',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for comp in ["AppCorp1", "AppCorp2", "AppCorp3"]:
                c = conn.execute(
                    "INSERT INTO applications (user_id, company_name, job_title, status) VALUES (?, ?, 'SDE', 'applied')",
                    (user_id, comp)
                )
                ids.append(c.lastrowid)
    finally:
        conn.close()
    return ids


def test_bulk_status_update_and_archive():
    user = "bulk_student_522"
    app_ids = _seed_test_applications(user)

    # 1. Bulk Status Update
    res = BulkApplicationsService.execute_bulk_action(
        user_id=user,
        application_ids=app_ids[:2],
        action="status_update",
        parameters={"status": "online_assessment"}
    )
    assert res["success"] is True
    assert res["affected_count"] == 2

    # 2. Bulk Archive
    res_arch = BulkApplicationsService.execute_bulk_action(
        user_id=user,
        application_ids=[app_ids[2]],
        action="archive"
    )
    assert res_arch["affected_count"] == 1

    # 3. History
    history = BulkApplicationsService.get_action_history(user)
    assert len(history) >= 2


def test_bulk_action_isolation():
    user_a = "user_bulk_a"
    user_b = "user_bulk_b"
    app_ids_b = _seed_test_applications(user_b)

    # User A tries to delete User B's applications
    res = BulkApplicationsService.execute_bulk_action(
        user_id=user_a,
        application_ids=app_ids_b,
        action="delete"
    )
    assert res["affected_count"] == 0


def test_bulk_action_api_routes(client):
    test_user = "api_bulk_student_522"
    app_ids = _seed_test_applications(test_user)

    with client.session_transaction() as s:
        s["user_id"] = test_user

    # Execute Bulk API
    res = client.post("/api/tracker/applications/bulk-action", json={
        "application_ids": app_ids,
        "action": "add_tag",
        "parameters": {"tag": "Campus_Drive"}
    })
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["affected_count"] == len(app_ids)

    # History API
    hist_res = client.get("/api/tracker/applications/bulk-history")
    assert hist_res.status_code == 200
    h_data = json.loads(hist_res.data)
    assert h_data["count"] >= 1
