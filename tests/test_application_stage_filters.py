"""
Unit tests for Application Stage History Filters (#517).
"""

import json
import pytest
from app import create_app
from utils.application_stage_filters import ApplicationStageFilterService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_stage_history_filter_service():
    user = "stage_student_517"

    # Log transitions
    ApplicationStageFilterService.record_stage_transition(
        user_id=user,
        application_id=101,
        company_name="Google",
        job_title="Software Engineer",
        from_stage="applied",
        to_stage="online_assessment",
        notes="Cleared resume round"
    )

    ApplicationStageFilterService.record_stage_transition(
        user_id=user,
        application_id=102,
        company_name="Amazon",
        job_title="SDE-1",
        from_stage="applied",
        to_stage="technical_interview_1",
        notes="Online assessment passed"
    )

    # Filter by company
    res = ApplicationStageFilterService.filter_stage_history(user_id=user, company="Google")
    assert res["total_events"] == 1
    assert res["events"][0]["company_name"] == "Google"

    # Filter by stage
    res_stage = ApplicationStageFilterService.filter_stage_history(user_id=user, stage="online_assessment")
    assert res_stage["total_events"] == 1


def test_stage_history_api_routes(client):
    test_user = "api_stage_student_517"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML View
    view_res = client.get("/tracker/stage-history")
    assert view_res.status_code == 200
    assert b"Application Stage History" in view_res.data

    # 2. Record Stage API
    post_res = client.post("/api/stage-history/transition", json={
        "application_id": 201,
        "company_name": "Stripe",
        "job_title": "Backend Engineer",
        "to_stage": "technical_interview_1",
        "notes": "Passed take-home assignment"
    })
    assert post_res.status_code == 201
    data = json.loads(post_res.data)
    assert data["status"] == "success"

    # 3. Filter API
    get_res = client.get("/api/stage-history/filter?company=Stripe")
    assert get_res.status_code == 200
    f_data = json.loads(get_res.data)
    assert f_data["result"]["total_events"] >= 1
