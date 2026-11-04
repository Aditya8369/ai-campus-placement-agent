import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    update_interview_session,
    get_student_interview_history,
    get_student_interview_performance_analytics
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_history.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_interview_history_database_analytics(tmp_path):
    test_db = tmp_path / "test_db_history.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        analysis_id = str(uuid.uuid4())
        session_id = f"{analysis_id}_tech"

        # 1. Save an analysis record tied to student_alice
        dummy_results = {
            "ats_score": 85,
            "job_match_score": 80,
            "interview_questions": {
                "technical": ["Explain indexing in DB."],
                "hr": ["Why our company?"],
                "behavioral": ["Tell me about a conflict."]
            }
        }
        save_analysis(
            analysis_id=analysis_id,
            resume_filename="alice_resume.pdf",
            company_name="Google",
            job_description="Backend Dev",
            results_dict=dummy_results,
            student_id="student_alice"
        )

        # 2. Create interview session
        questions = [
            {"index": 0, "type": "Technical", "question": "Explain indexing in DB."},
            {"index": 1, "type": "HR", "question": "Why our company?"},
            {"index": 2, "type": "Behavioral", "question": "Tell me about a conflict."}
        ]
        create_interview_session(session_id, analysis_id, questions)

        # 3. Submit answers with scores
        answers = [
            {"question_index": 0, "type": "Technical", "question": "Explain indexing in DB.", "answer": "B-Tree indexes speed up lookups.", "evaluation": {"score": 90}},
            {"question_index": 1, "type": "HR", "question": "Why our company?", "answer": "I admire Google's scale.", "evaluation": {"score": 85}},
            {"question_index": 2, "type": "Behavioral", "question": "Tell me about a conflict.", "answer": "Used STAR method to resolve dispute.", "evaluation": {"score": 80}}
        ]
        update_interview_session(session_id, current_question_index=2, answers_list=answers, completed=True)

        # 4. Fetch history and verify calculations
        history = get_student_interview_history("student_alice")
        assert len(history) == 1
        assert history[0]["company_name"] == "Google"
        assert history[0]["completed"] is True
        assert history[0]["average_score"] == 85.0
        assert history[0]["technical_score"] == 90.0
        assert history[0]["hr_score"] == 85.0
        assert history[0]["behavioral_score"] == 80.0

        # 5. Fetch analytics and verify progression & strengths
        analytics = get_student_interview_performance_analytics("student_alice")
        assert analytics["total_sessions"] == 1
        assert analytics["completed_sessions"] == 1
        assert analytics["total_questions_answered"] == 3
        assert analytics["overall_average_score"] == 85.0
        assert len(analytics["score_trend"]) == 1
        assert len(analytics["strengths"]) >= 1

        # Student isolation check
        bob_history = get_student_interview_history("student_bob")
        assert len(bob_history) == 0

def test_interview_history_endpoints(client):
    # GET /interview-history HTML view
    response = client.get("/interview-history?student_id=default_student")
    assert response.status_code == 200
    assert b"Mock Interview Performance History" in response.data

    # GET /api/interview-history API endpoint
    api_res = client.get("/api/interview-history?student_id=default_student")
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert "analytics" in data
    assert "total_sessions" in data["analytics"]
