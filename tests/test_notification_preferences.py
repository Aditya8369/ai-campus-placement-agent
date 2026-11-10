"""
Unit tests for Student Notification Preferences Management System (#260).
Verifies:
- Default notification preferences retrieval for new users.
- Customized preference persistence and retrieval.
- Master toggle on/off functionality.
- Channel filtering (email vs. in-app).
- Multi-tenant student preferences isolation.
- REST API endpoints for preference retrieval and update.
"""

import json
import pytest
from app import app
from utils.database import init_db, get_db_connection
from utils.notification_preferences_manager import (
    NOTIFICATION_CATEGORIES,
    get_student_preferences,
    update_student_preferences,
    set_master_notification_toggle,
    is_notification_allowed,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated SQLite database for testing."""
    test_db = str(tmp_path / "test_notif_pref.db")
    import config
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Alice Student', 'alice@campus.edu', 'hash1')"
    )
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Bob Student', 'bob@campus.edu', 'hash2')"
    )
    conn.commit()
    conn.close()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    with app.test_client() as client:
        yield client


def test_default_student_preferences():
    """Verify default preferences are provided when user has never customized them."""
    prefs = get_student_preferences("1")
    assert prefs["user_id"] == "1"
    assert len(prefs["preferences"]) == len(NOTIFICATION_CATEGORIES)
    assert "application_status_updates" in [p["category_id"] for p in prefs["preferences"]]

    status_pref = next(p for p in prefs["preferences"] if p["category_id"] == "application_status_updates")
    assert status_pref["enabled"] is True
    assert status_pref["email_enabled"] is True
    assert status_pref["in_app_enabled"] is True
    assert status_pref["is_customized"] is False


def test_update_student_preferences():
    """Test updating specific notification categories."""
    update_payload = [
        {
            "category_id": "application_status_updates",
            "enabled": True,
            "email_enabled": False,
            "in_app_enabled": True,
            "frequency": "daily_digest",
        },
        {
            "category_id": "weekly_digest",
            "enabled": True,
            "email_enabled": True,
            "in_app_enabled": False,
            "frequency": "weekly_digest",
        },
    ]

    result = update_student_preferences(1, update_payload)
    app_pref = next(p for p in result["preferences"] if p["category_id"] == "application_status_updates")
    assert app_pref["email_enabled"] is False
    assert app_pref["in_app_enabled"] is True
    assert app_pref["frequency"] == "daily_digest"
    assert app_pref["is_customized"] is True

    # Check notification allow checks
    assert is_notification_allowed(1, "application_status_updates", channel="email") is False
    assert is_notification_allowed(1, "application_status_updates", channel="in_app") is True


def test_master_notification_toggle():
    """Test disabling all notifications via master switch."""
    res_off = set_master_notification_toggle(1, False)
    assert res_off["master_toggle_all"] is False
    for p in res_off["preferences"]:
        assert p["enabled"] is False

    assert is_notification_allowed(1, "application_status_updates", "email") is False
    assert is_notification_allowed(1, "interview_reminders", "in_app") is False

    # Turn back on
    res_on = set_master_notification_toggle(1, True)
    assert res_on["master_toggle_all"] is True
    for p in res_on["preferences"]:
        assert p["enabled"] is True


def test_multi_student_preference_isolation():
    """Verify preference changes for student 1 do not leak to student 2."""
    update_student_preferences(
        1,
        [{"category_id": "placement_drive_alerts", "enabled": False, "email_enabled": False}],
    )

    prefs_1 = get_student_preferences(1)
    prefs_2 = get_student_preferences(2)

    p1_alert = next(p for p in prefs_1["preferences"] if p["category_id"] == "placement_drive_alerts")
    p2_alert = next(p for p in prefs_2["preferences"] if p["category_id"] == "placement_drive_alerts")

    assert p1_alert["enabled"] is False
    assert p2_alert["enabled"] is True


def test_api_notification_preferences_routes(client):
    """Test GET and PUT /api/notifications/preferences endpoints."""
    # Test unauthenticated
    resp = client.get("/api/notifications/preferences")
    assert resp.status_code == 401

    # Simulate logged-in user 1
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    # GET preferences
    get_resp = client.get("/api/notifications/preferences")
    assert get_resp.status_code == 200
    data = get_resp.get_json()
    assert data["success"] is True
    assert len(data["preferences"]) == len(NOTIFICATION_CATEGORIES)

    # PUT update preferences
    put_resp = client.put(
        "/api/notifications/preferences",
        data=json.dumps({
            "preferences": [
                {
                    "category_id": "interview_reminders",
                    "enabled": True,
                    "email_enabled": True,
                    "in_app_enabled": False,
                    "frequency": "realtime",
                }
            ]
        }),
        content_type="application/json",
    )
    assert put_resp.status_code == 200
    put_data = put_resp.get_json()
    rem = next(p for p in put_data["preferences"] if p["category_id"] == "interview_reminders")
    assert rem["in_app_enabled"] is False

    # POST master toggle
    toggle_resp = client.post(
        "/api/notifications/preferences/master-toggle",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.get_json()["master_toggle_all"] is False
