"""
Unit tests for Coding Problem Spaced-Repetition System (#509).
"""

import json
import pytest
from app import create_app
from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_coding_spaced_repetition_service_lifecycle():
    user = "test_sr_user_509"
    prob = "two-sum-sr"

    # Enroll
    rec = CodingSpacedRepetitionService.enroll_problem(
        user_id=user,
        problem_id=prob,
        title="Two Sum",
        topic="Hash Maps",
        difficulty="Easy",
        initial_rating="good"
    )
    assert rec["problem_id"] == prob
    assert rec["interval_days"] == 2
    assert rec["status"] == "active"

    # Review good
    rec2 = CodingSpacedRepetitionService.record_review(user, prob, "good")
    assert rec2["repetition_level"] == 1
    assert rec2["interval_days"] == 3

    # Review easy
    rec3 = CodingSpacedRepetitionService.record_review(user, prob, "easy")
    assert rec3["repetition_level"] == 3
    assert rec3["interval_days"] == 14

    # Review forgot
    rec4 = CodingSpacedRepetitionService.record_review(user, prob, "forgot")
    assert rec4["repetition_level"] == 0
    assert rec4["interval_days"] == 1

    # Toggle pause
    paused = CodingSpacedRepetitionService.toggle_pause_schedule(user, prob)
    assert paused["status"] == "paused"
    resumed = CodingSpacedRepetitionService.toggle_pause_schedule(user, prob)
    assert resumed["status"] == "active"

    # Reset
    reset_rec = CodingSpacedRepetitionService.reset_schedule(user, prob)
    assert reset_rec["repetition_level"] == 0
    assert reset_rec["interval_days"] == 1


def test_coding_spaced_repetition_api(client):
    test_user = "api_sr_student_509"
    with client.session_transaction() as sess:
        sess["user_id"] = test_user

    # 1. Enroll API
    res = client.post("/api/coding-practice/spaced-repetition/enroll", json={
        "problem_id": "reverse-linked-list",
        "title": "Reverse Linked List",
        "topic": "Linked Lists",
        "difficulty": "Easy",
        "rating": "good"
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["status"] == "success"

    # 2. View Queue
    view_res = client.get("/coding-practice/spaced-repetition")
    assert view_res.status_code == 200
    assert b"Coding Spaced-Repetition Queue" in view_res.data

    # 3. Review API
    rev_res = client.post("/api/coding-practice/spaced-repetition/reverse-linked-list/review", json={
        "rating": "good"
    })
    assert rev_res.status_code == 200

    # 4. Pause API
    pause_res = client.post("/api/coding-practice/spaced-repetition/reverse-linked-list/pause")
    assert pause_res.status_code == 200
    p_data = json.loads(pause_res.data)
    assert p_data["record"]["status"] == "paused"

    # 5. Reset API
    reset_res = client.post("/api/coding-practice/spaced-repetition/reverse-linked-list/reset")
    assert reset_res.status_code == 200
    r_data = json.loads(reset_res.data)
    assert r_data["record"]["interval_days"] == 1
