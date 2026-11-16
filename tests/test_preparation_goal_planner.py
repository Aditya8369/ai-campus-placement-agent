from datetime import date, timedelta
import pytest
from app import app
from utils.goal_planner_service import (
    PreparationGoalPlannerService,
    goal_planner_service
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_create_and_calculate_goal_progress():
    service = PreparationGoalPlannerService()
    student = "student_goal_1"
    future_date = (date.today() + timedelta(days=60)).isoformat()

    gid = service.create_goal(
        student_id=student,
        goal_title="Google SWE Placement 2026",
        target_role="Software Engineer",
        target_date_str=future_date,
        target_coding_problems=100,
        target_mock_interviews=10,
        resume_completed=True,
        notes="Focus on dynamic programming and system design."
    )
    assert gid > 0

    goals = service.list_student_goals(student)
    assert len(goals) >= 1
    target_goal = next(g for g in goals if g["id"] == gid)
    assert target_goal["goal_title"] == "Google SWE Placement 2026"
    assert target_goal["progress_metrics"]["days_remaining"] >= 58
    assert target_goal["progress_metrics"]["resume_ready"] is True
    assert "study guide" in target_goal["progress_metrics"]["disclaimer"]


def test_update_goal_progress():
    service = PreparationGoalPlannerService()
    student = "student_goal_2"
    target_date = (date.today() + timedelta(days=30)).isoformat()

    gid = service.create_goal(
        student_id=student,
        goal_title="Microsoft SDE Prep",
        target_role="SDE-1",
        target_date_str=target_date,
        target_coding_problems=50,
        target_mock_interviews=5
    )

    # Update progress
    updated = service.update_goal_progress(
        student_id=student,
        goal_id=gid,
        completed_coding=25,
        completed_interviews=3,
        resume_completed=True,
        status="ACTIVE"
    )
    assert updated is True

    # Verify updated values
    goals = service.list_student_goals(student)
    target = next(g for g in goals if g["id"] == gid)
    assert target["completed_coding_problems"] == 25
    assert target["completed_mock_interviews"] == 3
    assert target["progress_metrics"]["overall_progress_percent"] > 50


def test_api_goal_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_goal_user"

    future_date = (date.today() + timedelta(days=45)).isoformat()

    # POST create
    res = client.post("/api/goals", json={
        "goal_title": "Amazon Campus Drive",
        "target_role": "Backend Developer",
        "target_date": future_date,
        "target_coding_problems": 60,
        "target_mock_interviews": 4
    })
    assert res.status_code == 201
    gid = res.get_json()["goal_id"]

    # GET list
    list_res = client.get("/api/goals")
    assert list_res.status_code == 200
    assert list_res.get_json()["count"] >= 1

    # PUT/POST update progress
    update_res = client.post(f"/api/goals/{gid}/progress", json={
        "completed_coding_problems": 15,
        "completed_mock_interviews": 1,
        "resume_completed": True
    })
    assert update_res.status_code == 200
    assert update_res.get_json()["success"] is True


def test_api_goal_invalid_date(client):
    res = client.post("/api/goals", json={
        "goal_title": "Invalid Date Goal",
        "target_date": "not-a-valid-date"
    })
    assert res.status_code == 400
    assert res.get_json()["success"] is False
