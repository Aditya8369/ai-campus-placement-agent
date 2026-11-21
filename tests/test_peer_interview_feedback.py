"""
Unit tests for Peer Feedback Requests for Mock Interviews (#519).
"""

import json
import pytest
from app import create_app
from utils.peer_interview_feedback_service import PeerInterviewFeedbackService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_peer_feedback_service_lifecycle():
    user = "peer_student_519"
    sess = "sess_peer_101"

    # Create request
    req = PeerInterviewFeedbackService.create_review_request(
        user_id=user,
        session_id=sess,
        role_title="Backend Developer",
        interview_qa_list=[
            {"question": "Explain indexing in Postgres.", "answer": "I used B-tree indexes at email test@example.com."}
        ]
    )

    token = req["share_token"]
    assert token.startswith("peer_")

    # Retrieve request
    fetched = PeerInterviewFeedbackService.get_review_request(token)
    assert fetched is not None
    assert "[EMAIL REDACTED]" in fetched["transcript"][0]["answer"]

    # Submit feedback
    sub = PeerInterviewFeedbackService.submit_peer_feedback(
        share_token=token,
        technical_rating=5,
        communication_rating=4,
        conciseness_rating=4,
        positive_feedback="Great technical understanding",
        constructive_critique="Could slow down pacing"
    )
    assert sub["status"] == "success"

    # Review results
    results = PeerInterviewFeedbackService.get_feedback_for_session(user, sess)
    assert results["submissions_count"] == 1
    assert results["average_peer_rating"] > 4.0

    # Revoke
    rev = PeerInterviewFeedbackService.revoke_review_request(user, token)
    assert rev is True
    assert PeerInterviewFeedbackService.get_review_request(token) is None


def test_peer_feedback_api_routes(client):
    test_user = "api_peer_student_519"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    # 1. Create API
    create_res = client.post("/api/interview/peer-review/create", json={
        "session_id": "sess_api_519",
        "role_title": "Frontend Engineer",
        "interview_qa_list": [{"question": "What is the Virtual DOM?", "answer": "Virtual representation in React"}]
    })
    assert create_res.status_code == 201
    c_data = json.loads(create_res.data)
    token = c_data["review_request"]["share_token"]

    # 2. HTML View
    view_res = client.get(f"/interview/peer-review/{token}")
    assert view_res.status_code == 200
    assert b"Peer Mock Interview Evaluation" in view_res.data

    # 3. Submit Review API
    sub_res = client.post(f"/api/interview/peer-review/{token}/submit", json={
        "technical_rating": 4,
        "communication_rating": 5,
        "conciseness_rating": 4,
        "positive_feedback": "Clear explanation",
        "constructive_critique": "None"
    })
    assert sub_res.status_code == 200

    # 4. Results API
    res_res = client.get("/api/interview/peer-review/sess_api_519/results")
    assert res_res.status_code == 200
    r_data = json.loads(res_res.data)
    assert r_data["feedback"]["submissions_count"] == 1
