import pytest
import json
import uuid
from unittest.mock import patch, MagicMock
import config
from app import app
from utils.email_service import EmailNotificationService
from utils.database import (
    init_db,
    get_email_notification_preferences,
    update_email_notification_preferences
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_notifications.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_email_service_templates_and_dispatch():
    svc = EmailNotificationService()

    # 1. Welcome email
    sent_welcome = svc.send_welcome_email("student@campus.edu", "Alice Smith")
    assert sent_welcome is True

    # 2. Application created email
    sent_app = svc.send_application_created_email(
        recipient_email="student@campus.edu",
        student_name="Alice Smith",
        company_name="Google",
        role_title="Software Engineer Intern",
        applied_date="2026-03-01"
    )
    assert sent_app is True

    # 3. Status change email
    sent_status = svc.send_status_change_email(
        recipient_email="student@campus.edu",
        student_name="Alice Smith",
        company_name="Microsoft",
        role_title="SDE",
        previous_status="Applied",
        new_status="Interview Scheduled",
        notes="First technical round with engineering team"
    )
    assert sent_status is True

    # 4. Interview reminder email
    sent_reminder = svc.send_interview_reminder_email(
        recipient_email="student@campus.edu",
        student_name="Alice Smith",
        company_name="Amazon",
        interview_round="Behavioral & STAR",
        scheduled_time="Tomorrow at 2:00 PM"
    )
    assert sent_reminder is True

    # 5. Invalid recipient validation
    assert svc.send_email("", "Subject", "<p>Body</p>") is False

def test_database_email_preferences(tmp_path):
    test_db = tmp_path / "test_pref.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # Default preferences check
        prefs = get_email_notification_preferences("student_bob")
        assert prefs["email_enabled"] is True
        assert prefs["notify_welcome"] is True

        # Update preferences
        updated = update_email_notification_preferences(
            student_id="student_bob",
            email="bob@campus.edu",
            email_enabled=False,
            notify_welcome=False,
            notify_application_created=True,
            notify_status_change=False,
            notify_interview_reminder=True
        )
        assert updated is True

        refetched = get_email_notification_preferences("student_bob")
        assert refetched["email"] == "bob@campus.edu"
        assert refetched["email_enabled"] is False
        assert refetched["notify_welcome"] is False
        assert refetched["notify_interview_reminder"] is True

def test_notification_settings_endpoints(client):
    # GET settings page
    get_res = client.get("/notification-settings?student_id=default_student")
    assert get_res.status_code == 200
    assert b"Email Notification Settings" in get_res.data

    # POST update settings
    post_res = client.post("/notification-settings", data={
        "student_id": "default_student",
        "email": "candidate@university.edu",
        "email_enabled": "on",
        "notify_welcome": "on",
        "notify_application_created": "on",
        "notify_status_change": "on",
        "notify_interview_reminder": "on"
    }, follow_redirects=True)
    assert post_res.status_code == 200
    assert b"Email notification preferences updated successfully!" in post_res.data

    # API send interview reminder
    api_res = client.post("/api/notifications/remind-interview", json={
        "student_id": "default_student",
        "company_name": "Google",
        "round_type": "Technical Round",
        "scheduled_time": "Friday 10:00 AM",
        "interview_link": "https://meet.google.com/abc-xyz"
    })
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
