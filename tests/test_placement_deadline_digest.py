import pytest
from datetime import datetime, timezone, timedelta
from utils.placement_deadline_digest_service import get_placement_deadline_digest
from db.connection import get_db_connection

def test_deadline_digest():
    user = "student_digest_1"
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=2)
    next_month = today + timedelta(days=30)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_applications WHERE student_id = ?", (user,))
        cursor.execute("""
            INSERT INTO job_applications (id, student_id, company_name, role_title, status, application_date, deadline_date, is_archived)
            VALUES 
            ('d1', ?, 'Google', 'SDE', 'Applied', '2026-01-01', ?, 0),
            ('d2', ?, 'Microsoft', 'PM', 'Applied', '2026-01-01', ?, 0),
            ('d3', ?, 'Apple', 'QA', 'Applied', '2026-01-01', ?, 0),
            ('d4', ?, 'Meta', 'Data', 'Applied', '2026-01-01', ?, 0)
        """, (
            user, yesterday.isoformat(),
            user, today.isoformat(),
            user, tomorrow.isoformat(),
            user, next_month.isoformat()
        ))
        conn.commit()

    digest = get_placement_deadline_digest(user)
    assert digest["success"] is True
    assert len(digest["groups"]["overdue"]) == 1
    assert len(digest["groups"]["today"]) == 1
    assert len(digest["groups"]["this_week"]) == 1
    assert len(digest["groups"]["later"]) == 1

def test_deadline_digest_api(client):
    res = client.get("/api/deadlines/digest")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "groups" in data["digest"]
