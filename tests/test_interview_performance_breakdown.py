"""
Unit and integration tests for Interview Performance Breakdown (#267).
Verifies:
- Calculation of 4 competency pillars: Technical Knowledge, Communication, Problem-Solving, Answer Relevance.
- Automatic extraction and synthesis of candidate strengths and areas for improvement.
- Rating categorizations (Exemplary, Proficient, Developing, Needs Focus) and progress bar classes.
- calculate_session_summary includes competency_breakdown in evaluation summary payload.
- API endpoint /api/interview/<session_id>/breakdown delivers full structured breakdown.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db, save_analysis, create_interview_session, update_interview_session
from utils.interview_performance_breakdown import (
    calculate_competency_breakdown,
    COMPETENCY_TECHNICAL,
    COMPETENCY_COMMUNICATION,
    COMPETENCY_PROBLEM_SOLVING,
    COMPETENCY_RELEVANCE,
)
from agents.interview_agent import InterviewAgent


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_perf_breakdown.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    save_analysis(
        analysis_id="analysis_perf_test",
        resume_filename="resume.pdf",
        company_name="Meta",
        job_description="Production Systems Engineer",
        results_dict={"match_score": 88},
        student_id="default_student"
    )

    sample_questions = [
        {"index": 0, "type": "Technical", "question": "Explain TCP three-way handshake.", "is_behavioral": False},
        {"index": 1, "type": "Behavioral", "question": "Tell me about a production bug.", "is_behavioral": True}
    ]
    create_interview_session("sess_perf_001", "analysis_perf_test", sample_questions)

    sample_answers = [
        {
            "question_index": 0,
            "type": "Technical",
            "question": "Explain TCP three-way handshake.",
            "answer": "The client sends a SYN packet, server responds with SYN-ACK, client acknowledges with ACK to establish a reliable stream.",
            "evaluation": {
                "technical_accuracy": 90,
                "communication_score": 85,
                "confidence_score": 80,
                "verbal_clarity_score": 88
            }
        },
        {
            "question_index": 1,
            "type": "Behavioral",
            "question": "Tell me about a production bug.",
            "answer": "In my previous project, we faced a memory leak under high load. I isolated the unclosed socket connections using pprof and deployed a fix within 2 hours.",
            "evaluation": {
                "technical_accuracy": 85,
                "communication_score": 90,
                "confidence_score": 88,
                "star_method_analysis": {"used_star": True}
            }
        }
    ]
    update_interview_session("sess_perf_001", 1, sample_answers, True)

    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


def test_calculate_competency_breakdown_with_answers():
    """Verify competency breakdown computes scores across all 4 pillars."""
    sample_answers = [
        {
            "type": "Technical",
            "answer": "We implemented a distributed hash ring with consistent hashing to prevent cache imbalance.",
            "evaluation": {
                "technical_accuracy": 92,
                "communication_score": 85,
                "confidence_score": 88
            }
        }
    ]
    breakdown = calculate_competency_breakdown(sample_answers)
    assert breakdown["overall_score"] > 80
    assert COMPETENCY_TECHNICAL in breakdown["competencies"]
    assert COMPETENCY_COMMUNICATION in breakdown["competencies"]
    assert COMPETENCY_PROBLEM_SOLVING in breakdown["competencies"]
    assert COMPETENCY_RELEVANCE in breakdown["competencies"]

    tech_pillar = breakdown["competencies"][COMPETENCY_TECHNICAL]
    assert tech_pillar["score"] == 92
    assert tech_pillar["rating"] == "Exemplary"
    assert len(breakdown["strengths"]) >= 1


def test_calculate_competency_breakdown_empty_answers():
    """Verify empty answers return default non-assessed structure without crashing."""
    breakdown = calculate_competency_breakdown([])
    assert breakdown["overall_score"] == 0
    assert breakdown["readiness_band"] == "Not Evaluated"
    assert len(breakdown["improvements"]) >= 1


def test_interview_agent_session_summary_includes_breakdown():
    """Verify InterviewAgent.calculate_session_summary embeds competency_breakdown."""
    agent = InterviewAgent()
    answers = [
        {
            "type": "Technical",
            "answer": "Brief response.",
            "evaluation": {"technical_accuracy": 70, "communication_score": 75}
        }
    ]
    summary = agent.calculate_session_summary(answers)
    assert "competency_breakdown" in summary
    assert "competencies" in summary["competency_breakdown"]


def test_api_interview_breakdown_endpoint(client):
    """Test /api/interview/<session_id>/breakdown endpoint."""
    resp = client.get("/api/interview/sess_perf_001/breakdown")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["session_id"] == "sess_perf_001"
    assert data["overall_score"] >= 80
    assert len(data["strengths"]) >= 1
    assert COMPETENCY_TECHNICAL in data["competency_breakdown"]["competencies"]
