"""
Unit tests for Interview Communication Feedback (#511).
"""

import json
import pytest
from app import create_app
from utils.interview_communication_service import InterviewCommunicationService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_communication_feedback_analysis():
    user = "student_comm_511"
    sess = "sess_comm_101"

    # Confident, well-structured answer
    res = InterviewCommunicationService.evaluate_communication(
        user_id=user,
        session_id=sess,
        question_id="q1",
        answer_text="In our microservices project, we faced a high-latency database bottleneck. I led the migration to Redis caching, which reduced load by 45%. In conclusion, this improved overall system reliability and throughput."
    )

    assert res["communication_score"] >= 80
    assert res["length_status"] == "optimal"
    assert res["has_vague_opener"] is False
    assert res["has_conclusion"] is True
    assert len(res["suggestions"]) >= 1


def test_communication_feedback_fillers_and_vague_opener():
    user = "student_comm_511"
    sess = "sess_comm_102"

    res = InterviewCommunicationService.evaluate_communication(
        user_id=user,
        session_id=sess,
        question_id="q2",
        answer_text="I think maybe um like we basically did some stuff with python and actually like it was sort of working."
    )

    assert res["has_vague_opener"] is True
    assert res["filler_words_count"] > 0
    assert "um" in res["filler_words_breakdown"] or "like" in res["filler_words_breakdown"]
    assert any("filler" in s.lower() for s in res["suggestions"])


def test_communication_feedback_api(client):
    test_user = "api_student_comm_511"
    with client.session_transaction() as s:
        s["user_id"] = test_user

    payload = {
        "session_id": "api_comm_sess_511",
        "question_id": "q1",
        "answer_text": "I implemented a load balancing algorithm using round robin. Overall, this ensured balanced network traffic."
    }

    res = client.post("/api/interview/communication/evaluate", json=payload)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert "communication_feedback" in data

    # Audit endpoint
    audit_res = client.get("/api/interview/communication/api_comm_sess_511/audit")
    assert audit_res.status_code == 200
    audit_data = json.loads(audit_res.data)
    assert audit_data["audit"]["total_evaluated"] == 1
