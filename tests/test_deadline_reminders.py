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
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import config
from utils.database import (
    init_db,
    save_job_application,
    update_job_application,
    get_job_application_by_id,
    save_calendar_event,
    get_db_connection,
    get_email_notification_preferences,
    update_email_notification_preferences
)
from utils.deadline_reminders import (
    ensure_deadline_reminders_table,
    get_student_deadline_preferences,
    update_student_deadline_preferences,
    scan_and_generate_student_reminders,
    list_student_reminders,
    acknowledge_deadline_reminder,
    send_upcoming_deadline_reminders
)
from utils.email_service import EmailNotificationService
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


def test_job_application_deadline_date_field(reminder_test_env):
    """Verify storing, retrieving, and updating the dedicated deadline_date field (#298)."""
    save_job_application(
        app_id="app_deadline_field_1",
        student_id="student_df_test",
        company_name="Stripe",
        role_title="Backend Engineer",
        status="Applied",
        deadline_date="2026-11-20"
    )

    app = get_job_application_by_id("app_deadline_field_1", "student_df_test")
    assert app is not None
    assert app["deadline_date"] == "2026-11-20"

    # Update deadline_date
    updated = update_job_application(
        app_id="app_deadline_field_1",
        student_id="student_df_test",
        company_name="Stripe",
        role_title="Senior Backend Engineer",
        status="Applied",
        deadline_date="2026-11-25"
    )
    assert updated is True

    refreshed = get_job_application_by_id("app_deadline_field_1", "student_df_test")
    assert refreshed["deadline_date"] == "2026-11-25"
    assert refreshed["role_title"] == "Senior Backend Engineer"


def test_send_upcoming_deadline_reminders_next_2_days(reminder_test_env):
    """
    Verify scheduled job finds items due in next 2 days and sends one reminder per item (#298).
    Uses a fixed clock and mocked email client.
    """
    fixed_clock = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

    # 1 day away (due tomorrow) -> should be sent
    save_job_application(
        app_id="app_rem_due_1",
        student_id="student_due_test",
        company_name="Databricks",
        role_title="Data Engineer",
        status="Applied",
        deadline_date="2026-11-16"
    )
    # 2 days away -> should be sent
    save_job_application(
        app_id="app_rem_due_2",
        student_id="student_due_test",
        company_name="Airbnb",
        role_title="Full Stack Engineer",
        status="Applied",
        deadline_date="2026-11-17"
    )
    # 5 days away -> not in next 2 days, should be ignored
    save_job_application(
        app_id="app_rem_due_3",
        student_id="student_due_test",
        company_name="Uber",
        role_title="Systems Engineer",
        status="Applied",
        deadline_date="2026-11-20"
    )

    with patch.object(EmailNotificationService, "send_deadline_reminder_email", return_value=True) as mock_send:
        result = send_upcoming_deadline_reminders(
            student_id="student_due_test",
            reference_time=fixed_clock,
            days_ahead=2
        )

        assert result["status"] == "success"
        assert result["sent_count"] == 2
        assert mock_send.call_count == 2

        companies_sent = [call.kwargs["company_name"] for call in mock_send.call_args_list]
        assert "Databricks" in companies_sent
        assert "Airbnb" in companies_sent
        assert "Uber" not in companies_sent


def test_duplicate_reminders_prevented(reminder_test_env):
    """
    Verify duplicate reminders are strictly prevented by checking notification_dispatched_at (#298).
    Subsequent scheduler runs must send 0 emails for already-dispatched items.
    """
    fixed_clock = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

    save_job_application(
        app_id="app_dedup_1",
        student_id="student_dedup_test",
        company_name="Netflix",
        role_title="Software Engineer",
        status="Applied",
        deadline_date="2026-11-16"
    )

    # First scheduler run: 1 email sent
    with patch.object(EmailNotificationService, "send_deadline_reminder_email", return_value=True) as mock_send_1:
        result_1 = send_upcoming_deadline_reminders(
            student_id="student_dedup_test",
            reference_time=fixed_clock
        )
        assert result_1["sent_count"] == 1
        assert mock_send_1.call_count == 1

    # Second scheduler run at same or later time: 0 emails sent (deduplication check)
    with patch.object(EmailNotificationService, "send_deadline_reminder_email", return_value=True) as mock_send_2:
        result_2 = send_upcoming_deadline_reminders(
            student_id="student_dedup_test",
            reference_time=fixed_clock + timedelta(hours=2)
        )
        assert result_2["sent_count"] == 0
        assert mock_send_2.call_count == 0


def test_users_with_reminders_disabled_receive_nothing(reminder_test_env):
    """
    Verify users who turn off email alerts in preferences receive no reminder emails (#298).
    """
    fixed_clock = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

    save_job_application(
        app_id="app_opt_out_1",
        student_id="student_opt_out",
        company_name="Meta",
        role_title="Research Scientist",
        status="Applied",
        deadline_date="2026-11-16"
    )

    # Opt out via student deadline preferences
    update_student_deadline_preferences(
        student_id="student_opt_out",
        email_alerts_enabled=False
    )

    with patch.object(EmailNotificationService, "send_deadline_reminder_email") as mock_send:
        result = send_upcoming_deadline_reminders(
            student_id="student_opt_out",
            reference_time=fixed_clock
        )
        assert result["sent_count"] == 0
        assert result["skipped_count"] >= 1
        assert mock_send.call_count == 0

    # Also test opting out via email_notification_preferences
    update_student_deadline_preferences("student_opt_out", email_alerts_enabled=True)
    update_email_notification_preferences("student_opt_out", notify_deadline_reminder=False)

    with patch.object(EmailNotificationService, "send_deadline_reminder_email") as mock_send:
        result2 = send_upcoming_deadline_reminders(
            student_id="student_opt_out",
            reference_time=fixed_clock
        )
        assert result2["sent_count"] == 0
        assert result2["skipped_count"] >= 1
        assert mock_send.call_count == 0


def test_failed_email_does_not_crash_scheduler(reminder_test_env):
    """
    Verify a failed email dispatch (e.g. SMTP socket timeout) is caught gracefully
    and does not crash the scheduler or prevent other reminders from sending (#298).
    """
    fixed_clock = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)

    save_job_application(
        app_id="app_fail_1",
        student_id="student_failover",
        company_name="CompanyA",
        role_title="Role A",
        status="Applied",
        deadline_date="2026-11-16"
    )
    save_job_application(
        app_id="app_fail_2",
        student_id="student_failover",
        company_name="CompanyB",
        role_title="Role B",
        status="Applied",
        deadline_date="2026-11-16"
    )

    # First call raises Exception, second succeeds
    with patch.object(
        EmailNotificationService,
        "send_deadline_reminder_email",
        side_effect=[Exception("SMTP connection timeout"), True]
    ):
        result = send_upcoming_deadline_reminders(
            student_id="student_failover",
            reference_time=fixed_clock
        )
        # Did not crash!
        assert result["status"] == "success"
        assert result["failed_count"] == 1
        assert result["sent_count"] == 1


def test_email_bodies_never_logged(reminder_test_env, caplog):
    """
    Security check: verify email bodies are never logged under any circumstance (#298).
    """
    svc = EmailNotificationService()
    secret_body_marker = "SECRET_CANDIDATE_RESUME_INFO_987654"

    with caplog.at_level(logging.DEBUG):
        svc.send_deadline_reminder_email(
            recipient_email="candidate@test.edu",
            student_name="Test Student",
            title=f"Assessment with {secret_body_marker}",
            company_name="TestCorp",
            deadline_date="2026-11-16",
            days_remaining=1
        )

    # HTML body template markup or raw text must not be in log
    assert "<html" not in caplog.text.lower()
    assert "<body" not in caplog.text.lower()
    assert "automated reminder that your tracked application deadline" not in caplog.text


def test_cli_send_deadline_reminders(reminder_test_env):
    """Verify Flask CLI scheduled command runs smoothly (#298)."""
    today = datetime.now(timezone.utc).date()
    due = (today + timedelta(days=1)).isoformat()

    save_job_application(
        app_id="app_cli_test",
        student_id="student_cli",
        company_name="Apple",
        role_title="iOS Developer",
        status="Applied",
        deadline_date=due
    )

    runner = app.test_cli_runner()
    with patch.object(EmailNotificationService, "send_deadline_reminder_email", return_value=True):
        result = runner.invoke(args=["send-deadline-reminders"])
        assert result.exit_code == 0
        assert "Deadline reminders complete" in result.output


def test_api_send_upcoming_reminders(reminder_test_env):
    """Verify POST /api/reminders/send-upcoming API endpoint (#298)."""
    today = datetime.now(timezone.utc).date()
    due = (today + timedelta(days=1)).isoformat()

    save_job_application(
        app_id="app_api_send",
        student_id="student_api_send",
        company_name="Nvidia",
        role_title="Deep Learning Engineer",
        status="Applied",
        deadline_date=due
    )

    with patch.object(EmailNotificationService, "send_deadline_reminder_email", return_value=True):
        resp = reminder_test_env.post("/api/reminders/send-upcoming?student_id=student_api_send")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["sent_count"] >= 1

