import pytest
from utils.calendar_recurrence_service import generate_recurring_occurrences

def test_daily_recurrence():
    res = generate_recurring_occurrences("DSA Daily Practice", "2026-11-25T09:00:00Z", 60, "daily", max_occurrences=3)
    assert res["success"] is True
    assert res["total_occurrences"] == 3
    assert res["occurrences"][0]["title"] == "DSA Daily Practice"

def test_weekdays_recurrence():
    # Starting Friday 2026-11-27
    res = generate_recurring_occurrences("Mock Prep", "2026-11-27T10:00:00Z", 45, "weekdays", max_occurrences=3)
    assert res["success"] is True
    # Next should skip Saturday and Sunday
    assert len(res["occurrences"]) == 3

def test_calendar_recurrence_api(client):
    res = client.post("/api/calendar/recurring", json={
        "title": "System Design",
        "start_time": "2026-11-25T11:00:00Z",
        "duration_minutes": 60,
        "recurrence_type": "weekly",
        "max_occurrences": 4
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert res.get_json()["recurrence"]["total_occurrences"] == 4
