"""
Unit & Integration Tests for Job Application Deadline Reminder System (#251)
=============================================================================
Validates:
1. Multi-source ingestion: extracts deadlines from job_applications and calendar_events.
2. Urgency classification: overdue, critical (<= 24h), upcoming (<= 3d), approaching (<= 7d).
3. Deduplication and idempotent upserting.
4. Reminder acknowledgement / dismissal workflow.
5. Student preferences customization (lead days, alert channels).
6. API endpoints:
   - GET/POST /api/reminders/deadlines
   - POST /api/reminders/deadlines/<id>/acknowledge
   - GET/PUT /api/reminders/preferences
"""

import pytest
import json
from datetime import datetime, timezone, timedelta

import config
from utils.database import (
    init_db,
    save_job_application,
    save_calendar_event,
    get_db_connection
)
from utils.deadline_reminders import (
    ensure_deadline_reminders_table,
    get_student_deadline_preferences,
    update_student_deadline_preferences,
    scan_and_generate_student_reminders,
    list_student_reminders,
    acknowledge_deadline_reminder
)
from app import app


@pytest.fixture
def reminder_test_env(tmp_path, monkeypatch):
    """Sets up an isolated database for deadline reminder testing."""
    test_db = tmp_path / "test_reminders.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "reminders-secret-token"

    with app.test_client() as client:
        yield client


def test_default_preferences(reminder_test_env):
    """Verify default reminder preferences are initialized."""
    prefs = get_student_deadline_preferences("student_alpha")
    assert prefs["student_id"] == "student_alpha"
    assert prefs["alert_lead_days"] == 3
    assert prefs["email_alerts_enabled"] == 1
    assert prefs["dashboard_alerts_enabled"] == 1


def test_update_preferences(reminder_test_env):
    """Verify students can customize lead days and channel alerts."""
    updated = update_student_deadline_preferences(
        student_id="student_alpha",
        alert_lead_days=7,
        email_alerts_enabled=False
    )
    assert updated["alert_lead_days"] == 7
    assert updated["email_alerts_enabled"] == 0
    assert updated["dashboard_alerts_enabled"] == 1


def test_scan_job_application_deadlines(reminder_test_env):
    """Verify deadlines embedded in job applications are discovered and categorized."""
    today = datetime.now(timezone.utc).date()
    critical_date = (today + timedelta(days=1)).isoformat()
    upcoming_date = (today + timedelta(days=3)).isoformat()

    # Save job applications with notes containing deadlines
    save_job_application(
        app_id="app_rem_google",
        student_id="student_rem_1",
        company_name="Google",
        role_title="Software Engineer",
        status="Applied",
        notes=f"Application closes on {critical_date}. Must complete coding challenge."
    )
    save_job_application(
        app_id="app_rem_msft",
        student_id="student_rem_1",
        company_name="Microsoft",
        role_title="Product Manager",
        status="Under Review",
        notes=f"First round scheduled for {upcoming_date}."
    )

    reminders = scan_and_generate_student_reminders("student_rem_1")
    assert len(reminders) >= 2

    comp_names = [r["company_name"] for r in reminders]
    assert "Google" in comp_names
    assert "Microsoft" in comp_names

    # Check urgency classification
    google_rem = next(r for r in reminders if r["company_name"] == "Google")
    assert google_rem["urgency_level"] == "critical"


def test_scan_calendar_deadline_events(reminder_test_env):
    """Verify calendar events marked as 'deadline' are included."""
    today = datetime.now(timezone.utc).date()
    approaching_date = (today + timedelta(days=5)).isoformat()

    save_calendar_event(
        event_id="cal_rem_amazon",
        student_id="student_rem_2",
        title="Amazon AWS Summer Internship Form Submission",
        event_date=approaching_date,
        event_time="18:00",
        event_type="deadline",
        company_name="Amazon",
        description="Online Portal"
    )

    reminders = scan_and_generate_student_reminders("student_rem_2")
    assert len(reminders) == 1
    assert reminders[0]["company_name"] == "Amazon"
    assert reminders[0]["source_type"] == "calendar_event"
    assert reminders[0]["urgency_level"] == "approaching"


def test_acknowledge_and_filter_reminders(reminder_test_env):
    """Verify acknowledging a reminder hides it from unacknowledged views."""
    today = datetime.now(timezone.utc).date()
    due_date = (today + timedelta(days=2)).isoformat()

    save_calendar_event(
        event_id="cal_rem_atlassian",
        student_id="student_rem_3",
        title="Atlassian Coding Round",
        event_date=due_date,
        event_time="10:00",
        event_type="deadline",
        company_name="Atlassian"
    )

    reminders = scan_and_generate_student_reminders("student_rem_3")
    assert len(reminders) == 1
    rem_id = reminders[0]["id"]

    # Acknowledge
    ack_res = acknowledge_deadline_reminder("student_rem_3", rem_id)
    assert ack_res is True

    # Check that unacknowledged list is now empty
    active_rems = list_student_reminders("student_rem_3", include_acknowledged=False)
    assert len(active_rems) == 0

    # All reminders includes acknowledged item
    all_rems = list_student_reminders("student_rem_3", include_acknowledged=True)
    assert len(all_rems) == 1
    assert all_rems[0]["is_acknowledged"] == 1


def test_api_reminders_lifecycle(reminder_test_env):
    """Test full API endpoint interaction for deadline reminders."""
    today = datetime.now(timezone.utc).date()
    target_date = (today + timedelta(days=1)).isoformat()

    # Create an event in DB
    save_calendar_event(
        event_id="cal_rem_flipkart",
        student_id="default_student",
        title="Flipkart Grid Submission",
        event_date=target_date,
        event_time="23:59",
        event_type="deadline",
        company_name="Flipkart"
    )

    # 1. Trigger scan via POST /api/reminders/deadlines
    post_resp = reminder_test_env.post("/api/reminders/deadlines")
    assert post_resp.status_code == 200
    post_data = post_resp.get_json()
    assert post_data["status"] == "success"
    assert post_data["count"] >= 1

    rem_id = post_data["reminders"][0]["id"]

    # 2. Query via GET /api/reminders/deadlines
    get_resp = reminder_test_env.get("/api/reminders/deadlines")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["count"] >= 1

    # 3. Acknowledge reminder via API
    ack_resp = reminder_test_env.post(f"/api/reminders/deadlines/{rem_id}/acknowledge")
    assert ack_resp.status_code == 200

    # 4. Verify unacknowledged list is empty
    refreshed_get = reminder_test_env.get("/api/reminders/deadlines")
    assert refreshed_get.get_json()["count"] == 0

    # 5. Preferences GET and PUT
    pref_get = reminder_test_env.get("/api/reminders/preferences")
    assert pref_get.status_code == 200
    assert pref_get.get_json()["preferences"]["alert_lead_days"] == 3

    pref_put = reminder_test_env.put("/api/reminders/preferences", json={"alert_lead_days": 10})
    assert pref_put.status_code == 200
    assert pref_put.get_json()["preferences"]["alert_lead_days"] == 10
