"""
Unit tests for Weekly Preparation Summary Email (#521).
"""

import json
import pytest
from app import create_app
from utils.weekly_summary_email_service import WeeklySummaryEmailService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_weekly_summary_email_service():
    user = "weekly_student_521"

    summary = WeeklySummaryEmailService.compile_weekly_summary(user)
    assert summary["user_id"] == user
    assert "week_label" in summary
    assert "focus_recommendation" in summary

    # Render HTML
    html = WeeklySummaryEmailService.generate_html_email(summary)
    assert "Weekly Placement Preparation Digest" in html
    assert summary["week_label"] in html

    # Send / Log
    log_res = WeeklySummaryEmailService.send_or_log_summary(user, is_preview=True)
    assert log_res["status"] == "preview"
    assert "log_id" in log_res


def test_weekly_summary_email_preferences():
    user = "weekly_pref_user_521"
    WeeklySummaryEmailService.update_preference(user, is_enabled=False, recipient_email="optout@test.com")
    summary = WeeklySummaryEmailService.compile_weekly_summary(user)
    assert summary["is_subscribed"] is False

    res = WeeklySummaryEmailService.send_or_log_summary(user, is_preview=False)
    assert res["status"] == "unsubscribed"


def test_weekly_summary_api_routes(client):
    test_user = "api_weekly_student_521"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/reports/weekly-summary")
    assert view_res.status_code == 200
    assert b"Weekly Preparation Digest" in view_res.data

    # 2. JSON Digest API
    dig_res = client.get("/api/weekly-summary/digest")
    assert dig_res.status_code == 200
    d_data = json.loads(dig_res.data)
    assert d_data["status"] == "success"

    # 3. Preferences API
    pref_res = client.post("/api/weekly-summary/preferences", json={
        "is_enabled": True,
        "recipient_email": "student@college.edu"
    })
    assert pref_res.status_code == 200

    # 4. Trigger Email API
    send_res = client.post("/api/weekly-summary/send-now")
    assert send_res.status_code == 200
    s_data = json.loads(send_res.data)
    assert s_data["status"] == "sent"
