"""
Unit and API integration tests for Personalized preparation timetable
and Daily Study-Time Allocation (#605).
"""

import pytest
from utils.prep_timetable_service import (
    validate_daily_availability,
    generate_weekly_timetable,
    generate_daily_study_schedule,
    allocate_daily_study_time,
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


def test_validate_daily_availability_single_hours_number_and_dict():
    """Verify single daily study time can be passed directly as a number or dict key."""
    # Direct float
    is_valid, err, cleaned = validate_daily_availability(2.5)
    assert is_valid is True
    assert err is None
    assert cleaned["Monday"] == 2.5
    assert cleaned["Sunday"] == 2.5

    # Dict with daily_hours key
    is_valid2, err2, cleaned2 = validate_daily_availability({"daily_hours": 3.0})
    assert is_valid2 is True
    assert cleaned2["Wednesday"] == 3.0


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

    # Negative scalar
    is_valid_neg, err_neg, _ = validate_daily_availability(-2)
    assert is_valid_neg is False


def test_generate_daily_study_schedule_valid():
    """Verify structured daily preparation schedule generation for varying study allocations."""
    # 1-hour focused schedule
    res_1h = generate_daily_study_schedule(1.0, preferred_slot="Morning (08:00 - 11:00)")
    assert res_1h["status"] == "success"
    assert res_1h["daily_hours"] == 1.0
    assert res_1h["total_allocated_hours"] <= 1.05
    assert len(res_1h["schedule"]) >= 2
    assert res_1h["preferred_slot"] == "Morning (08:00 - 11:00)"

    # 2.5-hour standard schedule
    res_2h5 = generate_daily_study_schedule(2.5, preferred_slot="Evening (18:00 - 21:00)")
    assert res_2h5["status"] == "success"
    assert res_2h5["total_allocated_hours"] <= 2.55
    categories = [b["category"] for b in res_2h5["schedule"]]
    assert "Coding" in categories
    assert "Projects" in categories

    # 4-hour comprehensive schedule
    res_4h = generate_daily_study_schedule(4.0)
    assert res_4h["status"] == "success"
    assert len(res_4h["schedule"]) == 4
    assert "Coding" in res_4h["pillar_breakdown"]
    assert "Projects" in res_4h["pillar_breakdown"]
    assert "Interviews" in res_4h["pillar_breakdown"]
    assert "Revision" in res_4h["pillar_breakdown"]


def test_generate_daily_study_schedule_invalid():
    """Verify error handling on invalid or unrealistic daily study hours."""
    with pytest.raises(ValueError, match="greater than 0"):
        generate_daily_study_schedule(0)

    with pytest.raises(ValueError, match="greater than 0"):
        generate_daily_study_schedule(-1.5)

    with pytest.raises(ValueError, match="exceeds realistic"):
        generate_daily_study_schedule(20)


def test_allocate_daily_study_time_unified_entrypoint():
    """Verify unified allocate_daily_study_time returns daily schedule and weekly overview."""
    res = allocate_daily_study_time(3.0, preferred_slot="Evening (18:00 - 21:00)")
    assert res["status"] == "success"
    assert "daily_schedule" in res
    assert "weekly_timetable" in res
    assert res["daily_hours"] == 3.0
    assert len(res["daily_schedule"]["schedule"]) >= 3


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
    assert "daily_schedules" in result
    assert "Monday" in result["daily_schedules"]


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


def test_api_allocate_daily_study_time(client):
    """Verify POST /api/study-time/allocate returns structured daily preparation schedule."""
    resp = client.post(
        "/api/study-time/allocate",
        json={
            "daily_hours": 2.5,
            "preferred_slot": "Afternoon (14:00 - 17:00)"
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "daily_schedule" in data
    assert data["daily_hours"] == 2.5
    assert len(data["daily_schedule"]["schedule"]) >= 2


def test_api_study_schedule_daily_get(client):
    """Verify GET /api/study-schedule/daily endpoint."""
    resp = client.get("/api/study-schedule/daily?hours=3.0&preferred_slot=Evening%20(18:00%20-%2021:00)")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["daily_hours"] == 3.0
