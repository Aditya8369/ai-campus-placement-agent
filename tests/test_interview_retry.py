"""
Unit and integration tests for Mock Interview Answer Retry Loop & Attempt Comparison (#467).

Verifies:
1. Comparison calculation in code (zero extra AI calls):
   - Improvement case: score increases, positive diffs, addressed feedback points.
   - Decline case: score decreases, negative diffs, unaddressed points.
   - No-change case: identical scores, zero diffs, unchanged status.
   - Behavioral STAR score comparison and addressed components.
2. Retry limit enforcement:
   - Initial attempt (Attempt 1) has 2 retries left.
   - First retry (Attempt 2) has 1 retry left.
   - Second retry (Attempt 3) has 0 retries left.
   - Third retry attempt is strictly rejected with HTTP 400 / error message.
3. Session summary calculations:
   - Session summary consumes the latest (final) attempt scores.
4. Transcripts:
   - Markdown and PDF transcripts present the final attempt and list earlier attempt history.
5. API endpoints:
   - Both `/interview/<analysis_id>/submit` and `/interview/<analysis_id>/retry` support retries.
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from app import app
import config
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    get_interview_session,
    update_interview_session,
)
from agents.interview_agent import InterviewAgent
from utils.interview_retry_service import (
    MAX_RETRIES_PER_QUESTION,
    compare_answer_attempts,
    process_retry_answer,
    initialize_initial_attempt_record,
)
from utils.report_generator import (
    generate_interview_transcript_markdown,
    generate_interview_transcript_pdf,
)


@pytest.fixture
def interview_agent():
    return InterviewAgent()


@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with an isolated temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_interview_retry.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Comparison In-Code Tests (Improvement, Decline, No-Change, STAR)
# ==============================================================================

def test_retry_comparison_improvement():
    """Verify Attempt 2 with higher scores reports 'improved', positive diffs, and addressed feedback."""
    prev_eval = {
        "technical_accuracy": 60,
        "communication_score": 65,
        "confidence_score": 55,
        "verbal_clarity_score": 60,
        "filler_words_detected": ["um", "like"],
        "filler_word_count": 2,
    }
    curr_eval = {
        "technical_accuracy": 85,
        "communication_score": 85,
        "confidence_score": 80,
        "verbal_clarity_score": 80,
        "filler_words_detected": [],
        "filler_word_count": 0,
    }
    prev_ans = "Short answer about indexes."
    curr_ans = (
        "In relational database design, indexing with B-Trees drastically accelerates query retrieval "
        "by maintaining an ordered balanced search tree across disk blocks, effectively replacing expensive full table scans "
        "with logarithmic depth page lookups, which minimizes disk input output overhead and latency."
    )

    res = compare_answer_attempts(prev_eval, curr_eval, prev_ans, curr_ans)

    assert res["overall"]["status"] == "improved"
    assert res["overall"]["diff"] > 0
    assert "Great improvement" in res["verdict"]

    criteria = res["criteria"]
    assert criteria["technical_accuracy"]["diff"] == 25
    assert criteria["technical_accuracy"]["status"] == "improved"
    assert criteria["communication_score"]["diff"] == 20
    assert criteria["communication_score"]["status"] == "improved"
    assert criteria["confidence_score"]["diff"] == 25
    assert criteria["verbal_clarity_score"]["diff"] == 20

    # Check addressed points
    addressed = " ".join(res["addressed_points"])
    assert "Strengthened Technical Accuracy" in addressed
    assert "Reduced filler words" in addressed
    assert "Eliminated filler words" in addressed
    assert "Expanded response depth" in addressed


def test_retry_comparison_decline():
    """Verify Attempt 2 with lower scores reports 'declined', negative diffs, and unaddressed points."""
    prev_eval = {
        "technical_accuracy": 85,
        "communication_score": 80,
        "confidence_score": 85,
        "verbal_clarity_score": 80,
        "filler_words_detected": [],
        "filler_word_count": 0,
    }
    curr_eval = {
        "technical_accuracy": 55,
        "communication_score": 60,
        "confidence_score": 50,
        "verbal_clarity_score": 55,
        "filler_words_detected": ["uh", "like", "basically"],
        "filler_word_count": 3,
    }

    res = compare_answer_attempts(prev_eval, curr_eval, "Detailed first answer", "Vague second answer")

    assert res["overall"]["status"] == "declined"
    assert res["overall"]["diff"] < 0
    assert "Performance declined" in res["verdict"]

    criteria = res["criteria"]
    assert criteria["technical_accuracy"]["diff"] == -30
    assert criteria["technical_accuracy"]["status"] == "declined"
    assert criteria["communication_score"]["diff"] == -20

    unaddressed = " ".join(res["unaddressed_points"])
    assert "Technical Accuracy dropped" in unaddressed
    assert "Filler word count increased" in unaddressed


def test_retry_comparison_no_change():
    """Verify Attempt 2 with identical scores reports 'unchanged' with 0 diffs."""
    prev_eval = {
        "technical_accuracy": 75,
        "communication_score": 75,
        "confidence_score": 75,
        "verbal_clarity_score": 75,
        "filler_words_detected": ["like"],
        "filler_word_count": 1,
    }
    curr_eval = {
        "technical_accuracy": 75,
        "communication_score": 75,
        "confidence_score": 75,
        "verbal_clarity_score": 75,
        "filler_words_detected": ["like"],
        "filler_word_count": 1,
    }

    res = compare_answer_attempts(prev_eval, curr_eval, "Answer text", "Answer text")

    assert res["overall"]["status"] == "unchanged"
    assert res["overall"]["diff"] == 0
    assert "Overall score was unchanged" in res["verdict"]

    for crit_key, crit in res["criteria"].items():
        assert crit["diff"] == 0
        assert crit["status"] == "unchanged"


def test_retry_comparison_behavioral_star():
    """Verify behavioral questions track STAR story structure and component improvements."""
    prev_eval = {
        "technical_accuracy": 70,
        "communication_score": 70,
        "confidence_score": 70,
        "verbal_clarity_score": 70,
        "star_score": 60,
        "star_analysis": {
            "situation": "present",
            "task": "present",
            "action": "weak",
            "result": "missing",
        },
    }
    curr_eval = {
        "technical_accuracy": 80,
        "communication_score": 85,
        "confidence_score": 80,
        "verbal_clarity_score": 80,
        "star_score": 85,
        "star_analysis": {
            "situation": "present",
            "task": "present",
            "action": "present",
            "result": "present",
        },
    }

    res = compare_answer_attempts(prev_eval, curr_eval)

    assert "star_score" in res["criteria"]
    assert res["criteria"]["star_score"]["diff"] == 25
    assert res["criteria"]["star_score"]["status"] == "improved"

    addressed = " ".join(res["addressed_points"])
    assert "STAR Action component" in addressed
    assert "STAR Result component" in addressed


# ==============================================================================
# 2. Retry Limit Enforcement (2 retries per question)
# ==============================================================================

def test_retry_limit_enforcement():
    """Verify initial attempt allows 2 retries, subsequent retries decrement count, and 4th attempt is rejected."""
    target_q = {"type": "Technical", "question": "What is normalization?"}
    eval_1 = {
        "technical_accuracy": 60,
        "communication_score": 60,
        "confidence_score": 60,
        "verbal_clarity_score": 60,
    }
    eval_2 = {
        "technical_accuracy": 75,
        "communication_score": 75,
        "confidence_score": 75,
        "verbal_clarity_score": 75,
    }
    eval_3 = {
        "technical_accuracy": 85,
        "communication_score": 85,
        "confidence_score": 85,
        "verbal_clarity_score": 85,
    }
    eval_4 = {
        "technical_accuracy": 95,
        "communication_score": 95,
        "confidence_score": 95,
        "verbal_clarity_score": 95,
    }

    # Attempt 1 (Initial)
    record = initialize_initial_attempt_record(0, target_q, "Answer 1", eval_1)
    assert record["attempt_number"] == 1
    assert record["retry_count"] == 0
    assert record["retries_left"] == 2
    assert record["can_retry"] is True
    assert len(record["attempts"]) == 1

    # Attempt 2 (Retry 1)
    ok, record, err = process_retry_answer(record, "Answer 2 (Refined)", eval_2)
    assert ok is True
    assert err is None
    assert record["attempt_number"] == 2
    assert record["retry_count"] == 1
    assert record["retries_left"] == 1
    assert record["can_retry"] is True
    assert len(record["attempts"]) == 2
    assert record["comparison"]["overall"]["diff"] == 15

    # Attempt 3 (Retry 2 - final allowed retry)
    ok, record, err = process_retry_answer(record, "Answer 3 (Mastered)", eval_3)
    assert ok is True
    assert err is None
    assert record["attempt_number"] == 3
    assert record["retry_count"] == 2
    assert record["retries_left"] == 0
    assert record["can_retry"] is False
    assert len(record["attempts"]) == 3

    # Attempt 4 (Exceeds limit - rejected)
    ok, record_after, err = process_retry_answer(record, "Answer 4 (Disallowed)", eval_4)
    assert ok is False
    assert "Maximum retry limit reached" in err
    assert len(record_after["attempts"]) == 3


# ==============================================================================
# 3. Session Summary Calculation Uses Latest (Final) Attempt
# ==============================================================================

def test_session_summary_uses_final_attempt(interview_agent):
    """Verify session summary scores reflect the final attempt, not the earlier weak attempts."""
    target_q = {"type": "Technical", "question": "Explain ACID properties."}
    initial_eval = {
        "technical_accuracy": 40,
        "communication_score": 40,
        "confidence_score": 40,
        "verbal_clarity_score": 40,
    }
    retry_eval = {
        "technical_accuracy": 90,
        "communication_score": 90,
        "confidence_score": 90,
        "verbal_clarity_score": 90,
    }

    record = initialize_initial_attempt_record(0, target_q, "Initial weak response", initial_eval)
    ok, updated_record, _ = process_retry_answer(record, "Polished ACID response", retry_eval)
    assert ok is True

    answers_list = [updated_record]
    summary = interview_agent.calculate_session_summary(answers_list)

    assert summary["overall_score"] == 90
    assert summary["category_scores"]["Technical"]["technical_accuracy"] == 90
    assert summary["category_scores"]["Technical"]["communication_score"] == 90
    assert summary["readiness_verdict"] == "Placement Ready"


# ==============================================================================
# 4. Transcripts Include Final Attempt and List Earlier Attempts
# ==============================================================================

def test_transcripts_include_final_and_earlier_attempts():
    """Verify Markdown and PDF transcript outputs present final attempt details and earlier history."""
    target_q = {"type": "Technical", "question": "What is indexing?"}
    eval_1 = {
        "technical_accuracy": 50,
        "communication_score": 50,
        "confidence_score": 50,
        "feedback": "Needs more detail on indexing structures.",
        "suggestions": ["Explain B-Trees."],
    }
    eval_2 = {
        "technical_accuracy": 85,
        "communication_score": 85,
        "confidence_score": 80,
        "feedback": "Excellent explanation of B-Trees.",
        "suggestions": ["Keep practicing query optimizations."],
    }

    record = initialize_initial_attempt_record(0, target_q, "Attempt 1 text.", eval_1)
    _, updated_record, _ = process_retry_answer(record, "Attempt 2 improved text.", eval_2)

    answers_list = [updated_record]
    session_data = {
        "session_id": "test_session_retry_1",
        "company": "Amazon",
        "role": "SDE-1",
        "date": "2026-11-19",
        "answers": answers_list,
    }

    # Markdown Transcript
    md = generate_interview_transcript_markdown(session_data)
    assert "Question 1 [Technical Round] (Attempt 2 of 2 - Final Attempt)" in md
    assert "Candidate Response (Final Attempt):" in md
    assert "Attempt 2 improved text." in md
    assert "Attempt Comparison (Score Differences):" in md
    assert "+35 pts" in md
    assert "Earlier Attempt History:" in md
    assert "Attempt 1:" in md
    assert "Attempt 1 text." in md

    # PDF Transcript
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "transcript_retry.pdf")
        res_path = generate_interview_transcript_pdf(
            session_data=session_data,
            output_path=out_pdf,
            company_name="Amazon",
        )
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000
        with open(res_path, "rb") as f:
            pdf_bytes = f.read()
        assert pdf_bytes.startswith(b"%PDF")


# ==============================================================================
# 5. End-to-End API Routes: /submit and /retry
# ==============================================================================

def test_api_submit_and_retry_workflow(test_app_client, mock_gemini_client):
    """Verify complete end-to-end API workflow for answer submission, retrying, and max-retry blocking."""
    aid = "test_retry_api_aid"
    questions = [
        {
            "index": 0,
            "type": "Technical",
            "question": "What is the difference between TCP and UDP?",
            "is_behavioral": False,
        },
        {
            "index": 1,
            "type": "HR",
            "question": "Describe a challenge you solved.",
            "is_behavioral": True,
        },
    ]

    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "interview_questions": {
            "technical": ["What is the difference between TCP and UDP?"],
            "hr": ["Describe a challenge you solved."],
        },
    }
    save_analysis(aid, "resume.pdf", "Google", "Network Engineer", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    # 1. Initial Submission for Question 0
    mock_gemini_client(payload={
        "technical_accuracy": 55,
        "communication_score": 60,
        "confidence_score": 50,
        "feedback": "A bit brief on packet transmission guarantees.",
        "suggestions": ["Mention connection-oriented vs connectionless."],
    })

    resp1 = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "TCP is reliable, UDP is fast.",
        "question_index": 0,
    })
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["attempt_number"] == 1
    assert data1["retry_count"] == 0
    assert data1["retries_left"] == 2
    assert data1["can_retry"] is True
    assert data1["comparison"] is None

    # 2. First Retry for Question 0 (/retry route)
    mock_gemini_client(payload={
        "technical_accuracy": 80,
        "communication_score": 85,
        "confidence_score": 80,
        "feedback": "Much better explanation with handshakes and reliability.",
        "suggestions": ["Mention head-of-line blocking."],
    })

    resp2 = test_app_client.post(f"/interview/{aid}/retry", json={
        "answer": "TCP provides reliable, ordered data delivery via a 3-way handshake, while UDP sends datagrams without connection setup for low latency.",
        "question_index": 0,
        "is_retry": True,
    })
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["attempt_number"] == 2
    assert data2["retry_count"] == 1
    assert data2["retries_left"] == 1
    assert data2["can_retry"] is True
    assert data2["is_retry"] is True
    assert data2["comparison"] is not None
    assert data2["comparison"]["overall"]["status"] == "improved"
    assert data2["comparison"]["criteria"]["technical_accuracy"]["diff"] == 25

    # 3. Second Retry for Question 0 (/submit route with is_retry)
    mock_gemini_client(payload={
        "technical_accuracy": 92,
        "communication_score": 90,
        "confidence_score": 90,
        "feedback": "Outstanding answer covering TCP flow control and UDP streaming use-cases.",
        "suggestions": [],
    })

    resp3 = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "TCP is connection-oriented, guarantees delivery, and does flow control. UDP is connectionless with minimal overhead.",
        "question_index": 0,
        "is_retry": True,
    })
    assert resp3.status_code == 200
    data3 = resp3.get_json()
    assert data3["attempt_number"] == 3
    assert data3["retry_count"] == 2
    assert data3["retries_left"] == 0
    assert data3["can_retry"] is False

    # 4. Third Retry for Question 0 (Exceeds limit -> 400 rejection)
    resp4 = test_app_client.post(f"/interview/{aid}/retry", json={
        "answer": "Fourth attempt trying to exceed max retries.",
        "question_index": 0,
        "is_retry": True,
    })
    assert resp4.status_code == 400
    data4 = resp4.get_json()
    assert data4["max_retries_reached"] is True
    assert "Maximum retry limit reached" in data4["error"]

    # Verify database state has 3 attempts recorded and final evaluation is Attempt 3
    session = get_interview_session(aid)
    answers = session["answers"]
    assert len(answers) == 1
    q0_record = answers[0]
    assert len(q0_record["attempts"]) == 3
    assert q0_record["evaluation"]["technical_accuracy"] == 92
    assert q0_record["retry_count"] == 2
    assert q0_record["retries_left"] == 0
