"""
Unit tests for Subject-Wise Confidence Tracker (#513).
"""

import json
import pytest
from app import create_app
from utils.subject_confidence_service import SubjectConfidenceService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_subject_confidence_service():
    user = "confidence_student_513"

    # Default ratings
    data = SubjectConfidenceService.get_subject_ratings(user)
    assert data["total_subjects"] == 7
    assert data["average_confidence"] == 3.0

    # Rate DSA high, DBMS low
    SubjectConfidenceService.update_rating(user, "dsa", 5, "Solid with trees/graphs")
    SubjectConfidenceService.update_rating(user, "dbms", 2, "Need SQL join practice")

    updated = SubjectConfidenceService.get_subject_ratings(user)
    assert updated["weak_subjects_count"] >= 1
    weak_keys = [w["key"] for w in updated["weak_areas"]]
    assert "dbms" in weak_keys

    # Check history
    hist = SubjectConfidenceService.get_confidence_history(user, "dbms")
    assert len(hist) == 1
    assert hist[0]["score"] == 2


def test_subject_confidence_invalid_scores():
    with pytest.raises(ValueError):
        SubjectConfidenceService.update_rating("u1", "dsa", 10)

    with pytest.raises(ValueError):
        SubjectConfidenceService.update_rating("u1", "invalid_subject", 4)


def test_subject_confidence_api_routes(client):
    test_user = "api_confidence_student_513"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. HTML view
    view_res = client.get("/subject-confidence")
    assert view_res.status_code == 200
    assert b"Subject-Wise Placement Confidence Tracker" in view_res.data

    # 2. Update API
    up_res = client.post("/api/subject-confidence/update", json={
        "subject_key": "os",
        "score": 4,
        "notes": "Reviewed deadlock algorithms"
    })
    assert up_res.status_code == 200
    data = json.loads(up_res.data)
    assert data["status"] == "success"

    # 3. GET API
    get_res = client.get("/api/subject-confidence")
    assert get_res.status_code == 200
    g_data = json.loads(get_res.data)
    os_subject = next(s for s in g_data["ratings"]["subjects"] if s["key"] == "os")
    assert os_subject["score"] == 4

    # 4. History API
    hist_res = client.get("/api/subject-confidence/history?subject_key=os")
    assert hist_res.status_code == 200
    h_data = json.loads(hist_res.data)
    assert len(h_data["history"]) >= 1
