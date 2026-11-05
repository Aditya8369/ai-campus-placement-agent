import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_calendar_event,
    get_calendar_events,
    update_calendar_event,
    delete_calendar_event
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_calendar.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_calendar_events_crud(tmp_path):
    test_db = tmp_path / "test_cal_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # 1. Create calendar event
        evt_id = "evt-interview-001"
        saved_id = save_calendar_event(
            event_id=evt_id,
            student_id="student_dan",
            title="Google Technical Round 1",
            event_type="interview",
            event_date="2026-03-15",
            event_time="11:00",
            company_name="Google",
            description="Graphs and Trie questions",
            priority="High",
            completed=False
        )
        assert saved_id == evt_id

        # 2. Retrieve events
        events = get_calendar_events("student_dan")
        assert len(events) == 1
        assert events[0]["title"] == "Google Technical Round 1"
        assert events[0]["event_type"] == "interview"

        # 3. Filter by month
        march_events = get_calendar_events("student_dan", month="2026-03")
        assert len(march_events) == 1
        april_events = get_calendar_events("student_dan", month="2026-04")
        assert len(april_events) == 0

        # 4. Filter by event_type
        interview_events = get_calendar_events("student_dan", event_type="interview")
        assert len(interview_events) == 1
        deadline_events = get_calendar_events("student_dan", event_type="deadline")
        assert len(deadline_events) == 0

        # 5. Update event
        updated = update_calendar_event(
            event_id=evt_id,
            student_id="student_dan",
            title="Google Technical Round 1 (Completed)",
            event_type="interview",
            event_date="2026-03-15",
            event_time="11:00",
            company_name="Google",
            description="Cleared to Round 2",
            priority="High",
            completed=True
        )
        assert updated is True

        evts_after = get_calendar_events("student_dan")
        assert evts_after[0]["title"] == "Google Technical Round 1 (Completed)"
        assert evts_after[0]["completed"] == 1

        # 6. Delete event
        deleted = delete_calendar_event(evt_id, "student_dan")
        assert deleted is True
        assert len(get_calendar_events("student_dan")) == 0

def test_calendar_endpoints(client):
    # GET calendar page
    get_res = client.get("/calendar?student_id=default_student")
    assert get_res.status_code == 200
    assert b"Placement Preparation Calendar" in get_res.data

    # POST new activity
    post_res = client.post("/calendar", data={
        "student_id": "default_student",
        "title": "Amazon OA Deadline",
        "event_type": "deadline",
        "event_date": "2026-03-20",
        "event_time": "23:59",
        "company_name": "Amazon",
        "priority": "High",
        "description": "Complete 90 minute coding challenge"
    }, follow_redirects=True)
    assert post_res.status_code == 200
    assert b"Amazon OA Deadline" in post_res.data

    # Fetch events JSON
    api_res = client.get("/calendar?month=2026-03", headers={"X-Requested-With": "XMLHttpRequest"})
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert len(data["events"]) >= 1
    evt_id = data["events"][0]["id"]

    # Delete event API
    del_res = client.delete(f"/api/calendar/{evt_id}?student_id=default_student")
    assert del_res.status_code == 200
    del_data = json.loads(del_res.data)
    assert del_data["success"] is True
