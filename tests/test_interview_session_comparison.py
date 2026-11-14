"""
Tests for Interview Session Comparison (#273).
"""

import json
import pytest
from app import app
from utils.database import get_db_connection, init_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    # Clean up test records
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'test-cmp-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-cmp-ana-%'")
    conn.commit()
    conn.close()
    yield
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM interviews WHERE id LIKE 'test-cmp-%'")
    cursor.execute("DELETE FROM analyses WHERE id LIKE 'test-cmp-ana-%'")
    conn.commit()
    conn.close()


def create_mock_session(session_id, analysis_id, student_id, answers):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO analyses (id, student_id, resume_filename, company_name, job_description, results_json)
        VALUES (?, ?, 'resume.pdf', 'Acme Corp', 'Software Engineer', '{}')
        """,
        (analysis_id, student_id)
    )
    cursor.execute(
        """
        INSERT INTO interviews (id, analysis_id, current_question_index, questions_json, answers_json, completed)
        VALUES (?, ?, 2, '["Q1", "Q2"]', ?, 1)
        """,
        (session_id, analysis_id, json.dumps(answers))
    )
    conn.commit()
    conn.close()


def test_compare_interview_sessions_improvement(client):
    answers_baseline = [
        {"type": "Technical", "evaluation": {"score": 60, "technical_accuracy": 60}},
        {"type": "HR", "evaluation": {"score": 65}}
    ]
    answers_latest = [
        {"type": "Technical", "evaluation": {"score": 85, "technical_accuracy": 85}},
        {"type": "HR", "evaluation": {"score": 80}}
    ]

    create_mock_session("test-cmp-1", "test-cmp-ana-1", "student-alice", answers_baseline)
    create_mock_session("test-cmp-2", "test-cmp-ana-2", "student-alice", answers_latest)

    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    response = client.post(
        "/api/interview/compare",
        json={"session_ids": ["test-cmp-1", "test-cmp-2"]}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["session_count"] == 2
    summary = data["comparison_summary"]
    assert summary["overall_trajectory"] == "Improved"
    assert summary["overall_score_delta"] > 0
    assert summary["category_deltas"]["Technical"] == 25.0
    assert len(summary["key_improvements"]) > 0


def test_compare_interview_sessions_isolation_denied(client):
    answers = [{"type": "Technical", "evaluation": {"score": 70}}]
    create_mock_session("test-cmp-1", "test-cmp-ana-1", "student-alice", answers)
    create_mock_session("test-cmp-2", "test-cmp-ana-2", "student-bob", answers)

    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    # Alice trying to compare with Bob's session
    response = client.post(
        "/api/interview/compare",
        json={"session_ids": ["test-cmp-1", "test-cmp-2"]}
    )
    assert response.status_code == 403
    assert "Access denied" in response.get_json()["error"]


def test_compare_interview_sessions_insufficient_sessions(client):
    response = client.post(
        "/api/interview/compare",
        json={"session_ids": ["only-one"]}
    )
    assert response.status_code == 400


def test_compare_interview_sessions_not_found(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "student-alice"

    response = client.post(
        "/api/interview/compare",
        json={"session_ids": ["non-existent-1", "non-existent-2"]}
    )
    assert response.status_code == 404
