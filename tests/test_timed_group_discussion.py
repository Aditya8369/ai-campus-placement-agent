"""
Unit tests for Timed Group Discussion Rounds (#518).
"""

import json
import pytest
from app import create_app
from utils.timed_gd_service import TimedGroupDiscussionService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_timed_gd_service_full_lifecycle():
    user = "timed_gd_student_518"
    topic = "Artificial Intelligence: Threat or Catalyst for Junior Developers?"

    # Start session -> Phase 1: preparation
    sess = TimedGroupDiscussionService.start_timed_session(user, topic)
    assert sess["current_phase"] == "preparation"
    assert sess["phase_duration_seconds"] == 60
    assert sess["topic"] == topic

    # Advance to Phase 2: opening
    sess2 = TimedGroupDiscussionService.advance_phase(
        user, sess["id"], "My key notes are productivity gains and automated tests."
    )
    assert sess2["current_phase"] == "opening"
    assert sess2["preparation_notes"] != ""

    # Advance to Phase 3: discussion
    sess3 = TimedGroupDiscussionService.advance_phase(
        user, sess["id"], "I believe AI amplifies skilled engineers rather than replaces them."
    )
    assert sess3["current_phase"] == "discussion"

    # Advance to Phase 4: conclusion
    sess4 = TimedGroupDiscussionService.advance_phase(
        user, sess["id"], "While automation speeds boilerplate, architectural decisions require human judgment."
    )
    assert sess4["current_phase"] == "conclusion"

    # Complete round
    sess_done = TimedGroupDiscussionService.advance_phase(
        user, sess["id"], "In conclusion, AI acts as a strong catalyst when paired with foundational CS skills."
    )
    assert sess_done["current_phase"] == "completed"
    assert sess_done["overall_score"] > 0
    assert "opening_score" in sess_done["evaluation_feedback"]


def test_timed_gd_api_routes(client):
    test_user = "api_timed_gd_student_518"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. Start Session API
    start_res = client.post("/api/group-discussion/timed/start", json={
        "topic": "Remote Work vs In-Office Collaboration for Campus Placements"
    })
    assert start_res.status_code == 201
    s_data = json.loads(start_res.data)
    sess_id = s_data["session"]["id"]

    # 2. HTML View
    view_res = client.get(f"/interview/group-discussion/timed/{sess_id}")
    assert view_res.status_code == 200
    assert b"Timed Group Discussion Round" in view_res.data

    # 3. State API
    state_res = client.get(f"/api/group-discussion/timed/{sess_id}/state")
    assert state_res.status_code == 200
    st_data = json.loads(state_res.data)
    assert st_data["session"]["current_phase"] == "preparation"

    # 4. Advance API
    adv_res = client.post(f"/api/group-discussion/timed/{sess_id}/advance", json={
        "contribution_text": "Brainstorming notes for remote work"
    })
    assert adv_res.status_code == 200
    adv_data = json.loads(adv_res.data)
    assert adv_data["session"]["current_phase"] == "opening"
