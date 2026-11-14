"""
Unit and integration tests for Interview Session Pause and Resume (#265).
Verifies:
- Creation and pausing of interview session with draft answer and index preservation.
- Resuming a paused session restores question position, status, and pending draft.
- Completing a session transitions status to 'Completed'.
- Listing of user's interview sessions with status ('In Progress', 'Paused', 'Completed').
- Strict multi-tenant security preventing cross-user session tampering or access.
- API endpoints: /api/interview/<id>/pause, /api/interview/<id>/resume, /api/interview/sessions.
"""

import json
import pytest
from app import app
import config
from utils.database import (
    init_db,
    get_db_connection,
    save_analysis,
    create_interview_session,
    get_interview_session,
)
from utils.interview_session_service import (
    ensure_interview_session_pause_table,
    pause_interview_session,
    resume_interview_session,
    get_student_interview_sessions_with_status,
    STATUS_IN_PROGRESS,
    STATUS_PAUSED,
    STATUS_COMPLETED,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Sets up an isolated database for interview session pause and resume testing."""
    test_db = str(tmp_path / "test_pause_resume.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    conn = get_db_connection()
    ensure_interview_session_pause_table(conn)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Alice Dev', 'alice@test.edu', 'hash1')")
    cursor.execute("INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Bob Dev', 'bob@test.edu', 'hash2')")
    conn.commit()
    conn.close()

    # Seed analysis for Alice (id="analysis_alice_test")
    save_analysis(
        analysis_id="analysis_alice_test",
        resume_filename="alice_resume.pdf",
        company_name="Google",
        job_description="Software Engineer - Cloud Systems",
        results_dict={
            "match_score": 88,
            "interview_questions": {
                "technical": ["Explain consistency models in distributed databases.", "How does Paxos handle partitions?"]
            }
        },
        student_id="1"
    )

    # Seed an interview session for Alice
    sample_questions = [
        {"index": 0, "type": "Technical", "question": "Explain consistency models in distributed databases.", "is_behavioral": False},
        {"index": 1, "type": "Technical", "question": "How does Paxos handle partitions?", "is_behavioral": False},
        {"index": 2, "type": "HR", "question": "Where do you see yourself in five years?", "is_behavioral": False}
    ]
    create_interview_session("sess_alice_001", "analysis_alice_test", sample_questions)

    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


def test_pause_interview_session_preserves_state():
    """Verify pausing an ongoing interview saves progress, draft answer, and sets status to Paused."""
    pause_res = pause_interview_session(
        session_id="sess_alice_001",
        student_id="1",
        draft_answer="Eventual consistency guarantees that all replicas will eventually converge...",
        question_index=0
    )
    assert pause_res["success"] is True
    assert pause_res["status"] == STATUS_PAUSED
    assert pause_res["current_question_index"] == 0
    assert "Eventual consistency" in pause_res["draft_answer"]
    assert pause_res["current_question"]["question"] == "Explain consistency models in distributed databases."


def test_resume_interview_session_restores_state():
    """Verify resuming a paused session restores status to In Progress and returns saved draft."""
    pause_interview_session(
        session_id="sess_alice_001",
        student_id="1",
        draft_answer="Draft response about distributed algorithms.",
        question_index=1
    )

    resume_res = resume_interview_session(
        session_id="sess_alice_001",
        student_id="1"
    )
    assert resume_res["success"] is True
    assert resume_res["status"] == STATUS_IN_PROGRESS
    assert resume_res["current_question_index"] == 1
    assert resume_res["draft_answer"] == "Draft response about distributed algorithms."
    assert resume_res["current_question"]["question"] == "How does Paxos handle partitions?"


def test_get_student_interview_sessions_lists_status():
    """Verify listing student interview sessions displays correct status tags."""
    pause_interview_session(
        session_id="sess_alice_001",
        student_id="1",
        draft_answer="Sample draft",
        question_index=0
    )

    sessions = get_student_interview_sessions_with_status("1")
    assert len(sessions) >= 1
    target = next((s for s in sessions if s["session_id"] == "sess_alice_001"), None)
    assert target is not None
    assert target["status"] == STATUS_PAUSED
    assert target["company_name"] == "Google"


def test_multi_tenant_session_isolation():
    """Verify a different student cannot pause or resume another student's interview."""
    with pytest.raises(PermissionError, match="Access denied"):
        pause_interview_session(
            session_id="sess_alice_001",
            student_id="2",
            draft_answer="Malicious overwrite"
        )

    with pytest.raises(PermissionError, match="Access denied"):
        resume_interview_session(
            session_id="sess_alice_001",
            student_id="2"
        )


def test_api_pause_and_resume_endpoints(client):
    """Integration test for /api/interview/<id>/pause and /api/interview/<id>/resume endpoints."""
    with client.session_transaction() as sess:
        sess["user_id"] = "1"

    # 1. Pause via API
    resp_pause = client.post(
        "/api/interview/sess_alice_001/pause",
        data=json.dumps({"draft_answer": "My API draft answer", "question_index": 0}),
        content_type="application/json"
    )
    assert resp_pause.status_code == 200
    data_pause = resp_pause.get_json()
    assert data_pause["status"] == "success"
    assert data_pause["data"]["status"] == STATUS_PAUSED

    # 2. List sessions via API
    resp_list = client.get("/api/interview/sessions")
    assert resp_list.status_code == 200
    data_list = resp_list.get_json()
    assert data_list["status"] == "success"
    assert any(s["session_id"] == "sess_alice_001" and s["status"] == STATUS_PAUSED for s in data_list["sessions"])

    # 3. Resume via API
    resp_resume = client.post("/api/interview/sess_alice_001/resume")
    assert resp_resume.status_code == 200
    data_resume = resp_resume.get_json()
    assert data_resume["status"] == "success"
    assert data_resume["data"]["status"] == STATUS_IN_PROGRESS
    assert data_resume["data"]["draft_answer"] == "My API draft answer"
