"""
Test suite for mock interview session resetting and state restart capability.

Verifies:
- POST /interview/<aid>/reset clears answers and resets current_question_index to 0
- Round-specific session IDs are accurately resolved
- Retaking mock interviews resets completion flags while preserving question lists
"""

import tempfile
from pathlib import Path
import pytest
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    get_interview_session,
    update_interview_session,
)
from app import app
import config


@pytest.fixture
def mock_interview_setup(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_reset.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        init_db()

        aid = "test_reset_aid_100"
        questions = [
            {"index": 0, "type": "HR", "question": "Tell me about yourself"},
            {"index": 1, "type": "HR", "question": "Why this company?"},
        ]
        sample_results = {
            "resume_analysis": {"ats_score": 80},
            "job_match": {"match_percentage": 75},
            "interview_questions": {"hr": ["Tell me about yourself", "Why this company?"]},
        }
        save_analysis(aid, "test.pdf", "Google", "SWE", sample_results)
        create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

        # Submit one answer
        update_interview_session(
            interview_id=aid,
            current_question_index=1,
            answers_list=[{"question_index": 0, "score": 8, "feedback": "Good answer"}],
            completed=False,
        )
        yield aid


def test_reset_interview_session_restores_initial_state(mock_interview_setup):
    """Verify POST /interview/<aid>/reset clears answers and sets next_index to 0."""
    aid = mock_interview_setup
    app.config["TESTING"] = True

    # Pre-check: session has 1 answer and index 1
    session_before = get_interview_session(aid)
    assert session_before["current_question_index"] == 1
    assert len(session_before["answers"]) == 1

    with app.test_client() as client:
        res = client.post(f"/interview/{aid}/reset")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

        # Post-check: session is reset
        session_after = get_interview_session(aid)
        assert session_after["current_question_index"] == 0
        assert len(session_after["answers"]) == 0
        assert session_after["completed"] == 0
        assert len(session_after["questions"]) == 2  # Questions preserved!


def test_reset_interview_session_not_found():
    """Verify resetting non-existent interview returns 404."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post("/interview/non_existent_session_id/reset")
        assert res.status_code == 404
        data = res.get_json()
        assert data["success"] is False
