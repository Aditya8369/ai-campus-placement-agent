"""
Unit tests for Personalized weekly preparation timetable (#605)
"""

import pytest
from utils.prep_timetable_service import (
    validate_daily_availability,
    generate_weekly_timetable
)


def test_validate_daily_availability_valid():
    avail = {
        "Monday": 2, "Tuesday": 2.5, "Wednesday": 3,
        "Thursday": 2, "Friday": 4, "Saturday": 5, "Sunday": 0
    }
    is_valid, err, cleaned = validate_daily_availability(avail)
    assert is_valid is True
    assert err is None
    assert sum(cleaned.values()) == 18.5


def test_validate_daily_availability_invalid():
    # Negative hours
    is_valid, err, _ = validate_daily_availability({"Monday": -1, "Tuesday": 3})
    assert is_valid is False
    assert "negative" in err.lower()

    # Unrealistic hours (>16)
    is_valid, err, _ = validate_daily_availability({"Monday": 20})
    assert is_valid is False
    assert "exceeds" in err.lower() or "limit" in err.lower()

    # Empty
    is_valid, err, _ = validate_daily_availability({})
    assert is_valid is False


def test_generate_weekly_timetable():
    avail = {
        "Monday": 3, "Tuesday": 3, "Wednesday": 3,
        "Thursday": 3, "Friday": 3, "Saturday": 4, "Sunday": 2
    }
    result = generate_weekly_timetable(avail, preferred_slot="Morning (08:00 - 11:00)")
    assert result["status"] == "success"
    assert result["total_weekly_hours"] == 21.0
    assert result["total_allocated_hours"] <= 21.0
    assert "Monday" in result["timetable"]
    assert len(result["timetable"]["Monday"]) > 0
    assert result["timetable"]["Monday"][0]["time_slot"] == "Morning (08:00 - 11:00)"


def test_api_generate_timetable(client):
    resp = client.post(
        "/api/timetable/generate",
        json={
            "availability": {
                "Monday": 3, "Tuesday": 3, "Wednesday": 3,
                "Thursday": 3, "Friday": 3, "Saturday": 4, "Sunday": 0
            },
            "preferred_slot": "Evening (18:00 - 21:00)"
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "timetable" in data
    assert data["total_allocated_hours"] > 0
