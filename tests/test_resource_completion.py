"""
Unit tests for Learning Resource Completion Tracker (#520).
"""

import json
import pytest
from app import create_app
from utils.resource_completion_service import LearningResourceTrackerService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_learning_resource_tracker_lifecycle():
    user = "resource_student_520"

    # Default resources initialized
    res_list = LearningResourceTrackerService.get_or_initialize_resources(user)
    assert len(res_list) >= 5
    first = res_list[0]
    assert first["status"] == "not_started"

    # Update status to completed
    updated = LearningResourceTrackerService.update_resource_status(
        user_id=user,
        resource_id=first["resource_id"],
        status="completed",
        time_spent_minutes=90,
        notes="Understood all 75 patterns"
    )
    assert updated["status"] == "completed"
    assert updated["time_spent_minutes"] == 90
    assert updated["completed_at"] is not None

    # Check metrics
    metrics = LearningResourceTrackerService.get_progress_metrics(user)
    assert metrics["completed"] >= 1
    assert metrics["completion_percentage"] > 0


def test_learning_resource_api_routes(client):
    test_user = "api_resource_student_520"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/tracker/learning-resources")
    assert view_res.status_code == 200
    assert b"Learning Resource Completion Tracker" in view_res.data

    # 2. Add Custom API
    add_res = client.post("/api/learning-resources", json={
        "title": "Clean Code in Python",
        "category": "Software Engineering",
        "estimated_minutes": 120
    })
    assert add_res.status_code == 201
    a_data = json.loads(add_res.data)
    res_id = a_data["resource"]["resource_id"]

    # 3. Status Update API
    up_res = client.post(f"/api/learning-resources/{res_id}/status", json={
        "status": "in_progress",
        "time_spent_minutes": 30
    })
    assert up_res.status_code == 200
    u_data = json.loads(up_res.data)
    assert u_data["resource"]["status"] == "in_progress"

    # 4. JSON Progress Metrics API
    get_res = client.get("/api/learning-resources")
    assert get_res.status_code == 200
    g_data = json.loads(get_res.data)
    assert g_data["data"]["in_progress"] >= 1
