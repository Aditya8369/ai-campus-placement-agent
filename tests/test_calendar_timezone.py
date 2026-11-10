"""
Unit tests for Calendar Timezone Handling System (#261).
Verifies:
- IANA timezone validation and fallback.
- Local time to UTC conversion across multiple regions (IST, EST, PST, UTC).
- UTC to local time conversion and formatting.
- Daylight saving time (DST) and offset metadata computation.
- Student timezone preference retrieval, update, and isolation.
- REST API endpoints for student timezone management and event localization.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db, get_db_connection
from utils.calendar_timezone_service import (
    is_valid_timezone,
    get_student_timezone,
    set_student_timezone,
    get_student_timezone_info,
    convert_local_to_utc,
    convert_utc_to_local,
    format_event_for_student,
    COMMON_TIMEZONES,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_calendar_tz.db")
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


def test_timezone_validation():
    """Verify IANA timezone validation handles valid and invalid identifiers."""
    assert is_valid_timezone("UTC") is True
    assert is_valid_timezone("Asia/Kolkata") is True
    assert is_valid_timezone("America/New_York") is True
    assert is_valid_timezone("Europe/London") is True
    assert is_valid_timezone("Invalid/Timezone_Name") is False
    assert is_valid_timezone("") is False


def test_local_to_utc_conversion():
    """Verify conversion of local dates/times to UTC."""
    # Asia/Kolkata is UTC+5:30. 15:30 IST is 10:00 UTC.
    res_ist = convert_local_to_utc("2026-11-15", "15:30", "Asia/Kolkata")
    assert res_ist["utc_date"] == "2026-11-15"
    assert res_ist["utc_time"] == "10:00:00"
    assert res_ist["utc_iso"] == "2026-11-15T10:00:00Z"

    # America/New_York in November is EST (UTC-5). 09:00 EST is 14:00 UTC.
    res_est = convert_local_to_utc("2026-11-15", "09:00", "America/New_York")
    assert res_est["utc_date"] == "2026-11-15"
    assert res_est["utc_time"] == "14:00:00"


def test_utc_to_local_conversion():
    """Verify converting UTC timestamps back to student local timezone."""
    # 10:00 UTC -> 15:30 IST
    res_local = convert_utc_to_local("2026-11-15T10:00:00Z", "Asia/Kolkata")
    assert res_local["local_date"] == "2026-11-15"
    assert res_local["local_time"] == "15:30"
    assert "IST" in res_local["abbreviation"] or "GMT" in res_local["abbreviation"] or "+0530" in res_local["abbreviation"]


def test_student_timezone_persistence_and_isolation():
    """Verify student timezone settings persist and remain isolated across students."""
    # Default is UTC
    assert get_student_timezone(1) == "UTC"

    # Update Student 1 to Asia/Kolkata
    set_student_timezone(1, "Asia/Kolkata")
    assert get_student_timezone(1) == "Asia/Kolkata"

    # Student 2 should still be UTC
    assert get_student_timezone(2) == "UTC"

    # Enrich metadata check
    info = get_student_timezone_info(1)
    assert info["timezone_id"] == "Asia/Kolkata"
    assert info["offset"] == "+05:30"
    assert len(info["available_timezones"]) > 5


def test_format_event_for_student():
    """Verify enrichment of calendar event dictionary with timezone-aware display attributes."""
    raw_event = {
        "id": "event_123",
        "title": "Google Mock Interview",
        "event_date": "2026-11-20",
        "event_time": "14:00",
        "category": "interview",
    }
    enriched = format_event_for_student(raw_event, "Asia/Kolkata")
    assert "display_date" in enriched
    assert "display_time" in enriched
    assert enriched["display_timezone"] == "Asia/Kolkata"


def test_api_calendar_timezone_endpoints(client):
    """Test REST API endpoints for retrieving and setting timezone preferences."""
    # Unauthenticated check
    resp = client.get("/api/calendar/timezone")
    assert resp.status_code == 401

    # Log in as Student 1
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    # GET initial timezone info
    get_resp = client.get("/api/calendar/timezone")
    assert get_resp.status_code == 200
    data = get_resp.get_json()
    assert data["success"] is True
    assert data["timezone"]["timezone_id"] == "UTC"

    # PUT update timezone
    put_resp = client.put(
        "/api/calendar/timezone",
        data=json.dumps({"timezone_id": "America/Los_Angeles"}),
        content_type="application/json",
    )
    assert put_resp.status_code == 200
    put_data = put_resp.get_json()
    assert put_data["timezone"]["timezone_id"] == "America/Los_Angeles"
    assert put_data["timezone"]["offset"] == "-08:00"

    # Test invalid timezone rejection
    bad_resp = client.put(
        "/api/calendar/timezone",
        data=json.dumps({"timezone_id": "Mars/Olympus_Mons"}),
        content_type="application/json",
    )
    assert bad_resp.status_code == 400
    assert "Invalid" in bad_resp.get_json()["error"]
