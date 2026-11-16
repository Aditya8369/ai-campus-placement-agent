import pytest
from app import app
from utils.recommendation_dismissal_service import (
    RecommendationDismissalService,
    recommendation_dismissal_service
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_dismiss_and_filter():
    service = RecommendationDismissalService()
    student = "student_dismiss_1"

    # Dismiss item 1
    res = service.dismiss_recommendation(
        student_id=student,
        recommendation_id="rec_react_101",
        recommendation_title="Learn React Hooks",
        reason="Already know this skill / topic"
    )
    assert res["success"] is True
    assert res["recommendation_id"] == "rec_react_101"

    # Feed filter check
    feed = [
        {"id": "rec_react_101", "title": "Learn React Hooks"},
        {"id": "rec_docker_202", "title": "Learn Docker Containers"}
    ]
    filtered = service.filter_active_recommendations(student, feed, id_key="id")
    assert len(filtered) == 1
    assert filtered[0]["id"] == "rec_docker_202"


def test_undismiss_recommendation():
    service = RecommendationDismissalService()
    student = "student_dismiss_2"

    service.dismiss_recommendation(
        student_id=student,
        recommendation_id="rec_cloud_303",
        recommendation_title="GCP Architect Exam",
        reason="Irrelevant to my target career track"
    )

    dismissed_list = service.list_dismissed_recommendations(student)
    assert len(dismissed_list) >= 1

    # Undismiss
    undismissed = service.undismiss_recommendation(student, "rec_cloud_303")
    assert undismissed is True

    # Check that it's no longer in dismissed
    remaining = service.get_dismissed_recommendation_ids(student)
    assert "rec_cloud_303" not in remaining


def test_dismissal_analytics():
    service = RecommendationDismissalService()
    student = "student_analytics_dismiss"
    service.dismiss_recommendation(
        student_id=student,
        recommendation_id="rec_python_base",
        recommendation_title="Basics of Python",
        reason="Already know this skill / topic"
    )
    stats = service.get_dismissal_analytics(student)
    assert stats["total_dismissed"] >= 1
    assert "Already know this skill / topic" in stats["reasons_breakdown"]


def test_api_recommendation_dismissal_endpoints(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student_api_dismiss"

    # POST dismiss
    post_res = client.post("/api/recommendations/dismiss", json={
        "recommendation_id": "rec_api_99",
        "recommendation_title": "Advanced Redux Patterns",
        "reason": "Not interested in this technology / domain"
    })
    assert post_res.status_code == 200
    assert post_res.get_json()["success"] is True

    # GET list dismissed
    list_res = client.get("/api/recommendations/dismissed")
    assert list_res.status_code == 200
    list_data = list_res.get_json()
    assert list_data["count"] >= 1
    assert any(r["recommendation_id"] == "rec_api_99" for r in list_data["dismissed"])

    # POST undismiss
    undis_res = client.post("/api/recommendations/undismiss/rec_api_99")
    assert undis_res.status_code == 200
    assert undis_res.get_json()["success"] is True


def test_api_dismiss_missing_id(client):
    res = client.post("/api/recommendations/dismiss", json={
        "reason": "Other"
    })
    assert res.status_code == 400
    assert res.get_json()["success"] is False
