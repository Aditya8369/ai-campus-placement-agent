import pytest
from utils.calendar_conflict_service import detect_schedule_conflicts

def test_calendar_conflict_detection():
    events = [
        {"id": "ev1", "title": "Mock Interview", "start_time": "2026-11-25T10:00:00Z", "end_time": "2026-11-25T11:00:00Z", "is_all_day": False},
        {"id": "ev2", "title": "System Design Prep", "start_time": "2026-11-25T10:30:00Z", "end_time": "2026-11-25T11:30:00Z", "is_all_day": False},
        {"id": "ev3", "title": "Company Research", "start_time": "2026-11-25T00:00:00Z", "end_time": "2026-11-25T23:59:59Z", "is_all_day": True}
    ]
    res = detect_schedule_conflicts(events)
    assert res["has_conflicts"] is True
    assert res["conflict_count"] == 1
    assert "suggested_slot" in res["conflicts"][0]

    # Dismiss conflict
    key = res["conflicts"][0]["conflict_key"]
    res_dismissed = detect_schedule_conflicts(events, dismissed_conflict_keys=[key])
    assert res_dismissed["has_conflicts"] is False

def test_calendar_conflict_api(client):
    res = client.post("/api/calendar/conflicts", json={
        "events": [
            {"id": "e1", "title": "T1", "start_time": "2026-11-25T14:00:00Z", "end_time": "2026-11-25T15:00:00Z"},
            {"id": "e2", "title": "T2", "start_time": "2026-11-25T14:30:00Z", "end_time": "2026-11-25T15:30:00Z"}
        ]
    })
    assert res.status_code == 200
    assert res.get_json()["conflicts"]["has_conflicts"] is True
