"""
Unit tests for Voice Recording in Mock Interviews (#510).
"""

import json
import pytest
from app import create_app
from utils.voice_interview_service import VoiceInterviewService, _get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_voice_interview_service_metrics():
    user = "voice_student_510"
    sess = "sess_voice_101"

    # Ensure clean state for test run
    conn = _get_db_connection()
    with conn:
        conn.execute("DELETE FROM voice_interview_submissions WHERE user_id = ? AND session_id = ?", (user, sess))
    conn.close()

    # Submission with fillers and pace
    result = VoiceInterviewService.process_voice_submission(
        user_id=user,
        session_id=sess,
        question_id="q1",
        question_text="Tell me about yourself.",
        duration_seconds=30.0,
        raw_transcript="Um hello I am basically an engineer and like I love coding.",
        edited_transcript="Hello I am an engineer and I love coding.",
        audio_format="webm"
    )

    assert result["session_id"] == sess
    assert result["duration_seconds"] == 30.0
    assert result["final_transcript"] == "Hello I am an engineer and I love coding."
    assert result["words_per_minute"] > 0
    assert "delivery_quality" in result

    # Summary
    summary = VoiceInterviewService.get_delivery_summary(user, sess)
    assert summary["total_voice_answers"] == 1
    assert summary["average_wpm"] > 0


def test_voice_interview_empty_transcript_error():
    with pytest.raises(ValueError):
        VoiceInterviewService.process_voice_submission(
            user_id="u1",
            session_id="s1",
            question_id="q1",
            question_text="Q?",
            duration_seconds=10.0,
            raw_transcript="   ",
            edited_transcript=""
        )


def test_voice_interview_api_routes(client):
    test_user = "api_voice_student_510"
    test_sess = "test_sess_voice_510"
    conn = _get_db_connection()
    with conn:
        conn.execute("DELETE FROM voice_interview_submissions WHERE session_id = ?", (test_sess,))
    conn.close()

    with client.session_transaction() as s:
        s["user_id"] = test_user

    payload = {
        "session_id": test_sess,
        "question_id": "q1",
        "question_text": "Explain OOP concepts.",
        "duration_seconds": 45.0,
        "raw_transcript": "Object oriented programming uses encapsulation, inheritance, polymorphism, and abstraction.",
        "edited_transcript": "Object oriented programming uses encapsulation, inheritance, polymorphism, and abstraction.",
        "audio_format": "webm"
    }

    resp = client.post("/api/interview/voice/submit", json=payload)
    assert resp.status_code == 201
    data = json.loads(resp.data)
    assert data["status"] == "success"
    assert "voice_analysis" in data
    assert data["voice_analysis"]["duration_seconds"] == 45.0

    # Summary endpoint
    sum_resp = client.get("/api/interview/voice/test_sess_voice_510/summary")
    assert sum_resp.status_code == 200
    sum_data = json.loads(sum_resp.data)
    assert sum_data["status"] == "success"
    assert sum_data["summary"]["total_voice_answers"] == 1
