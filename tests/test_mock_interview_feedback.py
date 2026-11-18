"""
Unit and Integration Tests for Mock Interview Mode with Per-Answer Feedback (#496).

Verifies Acceptance Criteria:
1. A session contains at least 5 questions (even with sparse/empty coordinator payload or focused round).
2. Every answer receives feedback on clarity, structure, and relevance plus one tip to improve.
3. Empty answers are handled without errors (returns HTTP 200 with complete feedback fields).
4. Show a summary of strengths and weak areas at the end of the session.
5. The student can restart the session (resets index to 0, clears answers, allows retaking).
"""

import json
import tempfile
from pathlib import Path
import pytest
from unittest.mock import MagicMock
from app import app
import config
from agents.interview_agent import InterviewAgent
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    get_interview_session,
    update_interview_session,
)


@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with temporary sqlite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_db = Path(tmpdir) / "test_feedback.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        init_db()

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def interview_agent():
    return InterviewAgent()


# ==============================================================================
# 1. At Least 5 Questions Guarantee
# ==============================================================================

def test_ensure_minimum_session_questions_empty_and_sparse(interview_agent):
    """Verify ensure_minimum_session_questions expands empty or sparse lists to at least 5 questions."""
    # Empty list
    res_all = interview_agent.ensure_minimum_session_questions([], round_type="All", min_count=5)
    assert len(res_all) >= 5
    for idx, q in enumerate(res_all):
        assert q["index"] == idx
        assert q["question"]
        assert q["type"] in ["HR", "Technical", "Behavioral"]

    # Focused HR round with 1 question
    sparse_hr = [{"index": 0, "type": "HR", "question": "Why Google?", "is_behavioral": False}]
    res_hr = interview_agent.ensure_minimum_session_questions(sparse_hr, round_type="HR", min_count=5)
    assert len(res_hr) == 5
    for idx, q in enumerate(res_hr):
        assert q["index"] == idx
        assert q["type"] == "HR"

    # Focused Technical round with 2 questions
    sparse_tech = [
        {"index": 0, "type": "Technical", "question": "Explain TCP handshake.", "is_behavioral": False},
        {"index": 1, "type": "Technical", "question": "Explain deadlock.", "is_behavioral": False},
    ]
    res_tech = interview_agent.ensure_minimum_session_questions(sparse_tech, round_type="Technical", min_count=5)
    assert len(res_tech) == 5
    for idx, q in enumerate(res_tech):
        assert q["index"] == idx
        assert q["type"] == "Technical"

    # Focused Behavioral round with 2 questions
    sparse_beh = [
        {"index": 0, "type": "Behavioral", "question": "Describe a conflict in a team.", "is_behavioral": True},
    ]
    res_beh = interview_agent.ensure_minimum_session_questions(sparse_beh, round_type="Behavioral", min_count=5)
    assert len(res_beh) == 5
    for idx, q in enumerate(res_beh):
        assert q["index"] == idx
        assert q["type"] == "Behavioral"
        assert q["is_behavioral"] is True

    # Already has 6 questions (should not be truncated below 5)
    six_qs = [
        {"index": i, "type": "Technical", "question": f"Question {i}", "is_behavioral": False}
        for i in range(6)
    ]
    res_six = interview_agent.ensure_minimum_session_questions(six_qs, round_type="Technical", min_count=5)
    assert len(res_six) == 6


def test_interview_route_initializes_at_least_five_questions(test_app_client):
    """Verify GET /interview/<aid> bootstrap route generates at least 5 questions even with empty coordinator data."""
    aid = "test_min_5_questions_aid"
    # Parent analysis with empty interview questions in coordinator output
    sample_results = {
        "resume_analysis": {"ats_score": 75},
        "interview_questions": {
            "hr": [],
            "technical": [],
            "behavioral": [],
        },
    }
    save_analysis(aid, "resume.pdf", "Amazon", "Backend Developer", sample_results)

    # Initialize standard session
    res = test_app_client.get(f"/interview/{aid}")
    assert res.status_code == 200

    session = get_interview_session(aid)
    assert session is not None
    assert len(session["questions"]) >= 5


# ==============================================================================
# 2. Per-Answer Feedback (Clarity, Structure, Relevance, Tip)
# ==============================================================================

def test_evaluate_answer_includes_clarity_structure_relevance_and_tip(interview_agent, mock_gemini_client):
    """Verify evaluate_answer returns explicit feedback on clarity, structure, relevance, and one tip."""
    mock_payload = {
        "confidence_score": 88,
        "communication_score": 85,
        "technical_accuracy": 90,
        "verbal_clarity_score": 86,
        "clarity": "Articulate, crisp delivery with clear explanations.",
        "structure": "Logical flow beginning with definitions, followed by trade-offs, and concluding with a concrete example.",
        "relevance": "Directly and accurately addresses the database indexing concepts requested.",
        "tip": "Mention B-Tree vs Hash index lookup time complexities to demonstrate deeper knowledge.",
        "filler_words_detected": ["basically"],
        "filler_word_count": 1,
        "suggestions": ["Include time complexity notation."],
        "feedback": "Outstanding technical depth and clear articulation.",
    }
    mock_gemini_client(payload=mock_payload)

    res = interview_agent.evaluate_answer(
        question_type="Technical",
        question="How does database indexing work?",
        answer="Database indexes speed up data retrieval using data structures like B-Trees at the cost of additional write overhead.",
        is_behavioral=False,
    )

    assert "clarity" in res
    assert "structure" in res
    assert "relevance" in res
    assert "tip" in res

    assert res["clarity"] == "Articulate, crisp delivery with clear explanations."
    assert "Logical flow" in res["structure"]
    assert "Directly and accurately" in res["relevance"]
    assert "B-Tree vs Hash index" in res["tip"]


def test_evaluate_answer_fallbacks_for_clarity_structure_relevance_and_tip(interview_agent, mock_gemini_client):
    """Verify evaluate_answer synthesizes high quality clarity, structure, relevance and tip when LLM omits them."""
    # LLM omits clarity, structure, relevance, tip
    mock_payload = {
        "confidence_score": 80,
        "communication_score": 75,
        "technical_accuracy": 78,
        "verbal_clarity_score": 77,
        "filler_words_detected": [],
        "filler_word_count": 0,
        "suggestions": ["Use STAR method with quantitative results."],
        "feedback": "Solid answer with good fundamentals.",
    }
    mock_gemini_client(payload=mock_payload)

    res = interview_agent.evaluate_answer(
        question_type="Technical",
        question="Explain polymorphism in OOP.",
        answer="Polymorphism allows objects of different classes to be treated as objects of a common superclass.",
        is_behavioral=False,
    )

    assert res["clarity"]  # Non-empty synthesized clarity feedback
    assert res["structure"]  # Non-empty synthesized structure feedback
    assert res["relevance"]  # Non-empty synthesized relevance feedback
    assert res["tip"] == "Use STAR method with quantitative results."


# ==============================================================================
# 3. Empty Answers Handled Without Errors
# ==============================================================================

def test_evaluate_answer_empty_input_handled_without_errors(interview_agent):
    """Verify evaluate_answer handles empty strings and whitespace safely without exceptions."""
    for empty_input in ["", "   ", "\n\t  "]:
        res = interview_agent.evaluate_answer(
            question_type="Technical",
            question="What is a hash table?",
            answer=empty_input,
            is_behavioral=False,
        )
        assert res["confidence_score"] == 0
        assert res["technical_accuracy"] == 0
        assert "clarity" in res and res["clarity"]
        assert "structure" in res and res["structure"]
        assert "relevance" in res and res["relevance"]
        assert "tip" in res and res["tip"]
        assert "empty" in res["feedback"].lower() or "not provide" in res["feedback"].lower()


def test_interview_submit_empty_answer_returns_200(test_app_client):
    """Verify submitting an empty answer via POST /interview/<aid>/submit succeeds with 200 and evaluation payload."""
    aid = "test_empty_submit_aid"
    questions = [
        {"index": 0, "type": "Technical", "question": "What is an index?", "is_behavioral": False},
        {"index": 1, "type": "HR", "question": "Why work here?", "is_behavioral": False},
    ]
    sample_results = {
        "resume_analysis": {"ats_score": 80},
        "interview_questions": {"technical": ["What is an index?"], "hr": ["Why work here?"]},
    }
    save_analysis(aid, "resume.pdf", "Microsoft", "SWE", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    # Submit empty answer
    resp = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "",
        "question_index": 0,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "evaluation" in data
    eval_data = data["evaluation"]
    assert eval_data["technical_accuracy"] == 0
    assert eval_data["clarity"]
    assert eval_data["structure"]
    assert eval_data["relevance"]
    assert eval_data["tip"]
    assert data["next_index"] == 1
    assert data["completed"] is False


# ==============================================================================
# 4. End-of-Session Summary of Strengths and Weak Areas
# ==============================================================================

def test_calculate_session_summary_returns_strengths_and_weak_areas(interview_agent):
    """Verify calculate_session_summary extracts top-level strengths and weak areas."""
    answers = [
        {
            "question_index": 0,
            "type": "Technical",
            "question": "Explain quicksort.",
            "answer": "Quicksort is a divide and conquer algorithm that picks a pivot and partitions the array.",
            "evaluation": {
                "technical_accuracy": 85,
                "communication_score": 80,
                "confidence_score": 85,
                "verbal_clarity_score": 82,
                "clarity": "Clear explanation.",
                "structure": "Logical flow.",
                "relevance": "Direct answer.",
                "tip": "Mention average vs worst-case O(N^2) complexity.",
            },
        },
        {
            "question_index": 1,
            "type": "HR",
            "question": "Tell me about yourself.",
            "answer": "I am a computer science student specializing in distributed systems.",
            "evaluation": {
                "technical_accuracy": 75,
                "communication_score": 78,
                "confidence_score": 75,
                "verbal_clarity_score": 76,
                "clarity": "Good pacing.",
                "structure": "Chronological.",
                "relevance": "Relevant background.",
                "tip": "Connect your academic projects to the target company's mission.",
            },
        },
    ]

    summary = interview_agent.calculate_session_summary(answers)
    assert "strengths" in summary
    assert "weak_areas" in summary
    assert isinstance(summary["strengths"], list)
    assert isinstance(summary["weak_areas"], list)
    assert len(summary["strengths"]) > 0
    assert len(summary["weak_areas"]) > 0


def test_completion_submit_payload_includes_strengths_and_weak_areas(test_app_client):
    """Verify final question submission includes summary with strengths and weak_areas."""
    aid = "test_final_summary_aid"
    questions = [
        {"index": 0, "type": "Technical", "question": "What is an index?", "is_behavioral": False},
    ]
    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "interview_questions": {"technical": ["What is an index?"]},
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    resp = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "An index is a lookup data structure that improves read speed.",
        "question_index": 0,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["completed"] is True
    assert "summary" in data
    summary = data["summary"]
    assert "strengths" in summary
    assert "weak_areas" in summary
    assert len(summary["strengths"]) > 0
    assert len(summary["weak_areas"]) > 0


# ==============================================================================
# 5. Session Restart Capability
# ==============================================================================

def test_interview_session_restart_resets_progress(test_app_client):
    """Verify POST /interview/<aid>/reset clears answers, resets index to 0, and allows retaking."""
    aid = "test_restart_capability_aid"
    questions = [
        {"index": 0, "type": "Technical", "question": "What is an index?", "is_behavioral": False},
        {"index": 1, "type": "HR", "question": "Why work here?", "is_behavioral": False},
    ]
    sample_results = {
        "resume_analysis": {"ats_score": 80},
        "interview_questions": {"technical": ["What is an index?"], "hr": ["Why work here?"]},
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    # Submit first answer
    test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "An index accelerates database query performance.",
        "question_index": 0,
    })

    # Check progress
    session_mid = get_interview_session(aid)
    assert session_mid["current_question_index"] == 1
    assert len(session_mid["answers"]) == 1

    # Reset session
    reset_resp = test_app_client.post(f"/interview/{aid}/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.get_json()
    assert reset_data["success"] is True

    # Check session was reset
    session_reset = get_interview_session(aid)
    assert session_reset["current_question_index"] == 0
    assert len(session_reset["answers"]) == 0
    assert session_reset["completed"] == 0
    assert len(session_reset["questions"]) == 2  # Questions preserved

    # Verify student can now submit question 0 again cleanly
    resubmit_resp = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "A fresh improved answer detailing B-Tree indexes.",
        "question_index": 0,
    })
    assert resubmit_resp.status_code == 200
    data_after = resubmit_resp.get_json()
    assert data_after["next_index"] == 1
    assert data_after["completed"] is False
