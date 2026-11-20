"""
Unit and integration tests for Mock Interview Timed Answer Mode (#431).

Verifies:
1. Server-side handling of timed submissions (/interview/<aid>/submit):
   - Timed submissions calculate and return `time_display` (e.g. "answered in 1:20 of 2:00").
   - Timed submissions include timing note in feedback.
   - Expiration detection when time taken equals or exceeds limit.
   - Persistence of `is_timed`, `time_taken_seconds`, `time_limit_seconds`, and `time_display` in SQLite.
2. Untimed submissions maintain full backward compatibility:
   - Untimed submissions do not attach timer notes to feedback.
   - `is_timed` remains False or None.
3. Session summary calculations (`calculate_session_summary`):
   - Generates `timing_summary` for sessions containing timed answers.
   - Calculates average time, formatted display ("1:20"), and within-limit percentage.
   - Returns None for untimed sessions.
4. Report and transcript compilation:
   - Includes timing breakdown in markdown and PDF transcript generation.
5. Template and Accessibility:
   - Renders optional toggle switch, per-category time selectors, timer bar, and `aria-live` announcer.
"""

import json
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
)
from agents.interview_agent import InterviewAgent
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
        test_db = Path(tmpdir) / "test_interview_timed.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Server-side Handling of Timed vs Untimed Submissions
# ==============================================================================

def test_interview_submit_timed_answer_under_limit(test_app_client, mock_gemini_client):
    """Verify submitting a timed answer formats 'answered in X:YY of A:BB' and records time metrics."""
    aid = "test_timed_aid_001"
    questions = [
        {
            "index": 0,
            "type": "Technical",
            "question": "Explain indexing in PostgreSQL and its performance trade-offs.",
            "is_behavioral": False,
        },
        {
            "index": 1,
            "type": "HR",
            "question": "Why do you want to join our engineering team?",
            "is_behavioral": False,
        },
    ]

    sample_results = {
        "resume_analysis": {"ats_score": 88},
        "interview_questions": {
            "technical": ["Explain indexing in PostgreSQL and its performance trade-offs."],
            "hr": ["Why do you want to join our engineering team?"],
        },
    }
    save_analysis(aid, "resume.pdf", "Google", "Backend Engineer", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    mock_gemini_client(payload={
        "technical_accuracy": 90,
        "communication_score": 85,
        "confidence_score": 88,
        "feedback": "Clear explanation of B-tree index lookups vs write overhead.",
        "suggestions": ["Mention BRIN indexes for time-series data."],
    })

    # Submit timed answer: 80 seconds used out of 120 seconds limit (1:20 of 2:00)
    response = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "B-tree indexes accelerate read queries from O(N) to O(log N), but incur write and storage penalties on INSERT/UPDATE operations.",
        "question_index": 0,
        "is_timed": True,
        "time_taken_seconds": 80,
        "time_limit_seconds": 120,
    })

    assert response.status_code == 200
    data = response.get_json()

    assert data["is_timed"] is True
    assert data["time_taken_seconds"] == 80
    assert data["time_limit_seconds"] == 120
    assert data["time_display"] == "answered in 1:20 of 2:00"

    evaluation = data["evaluation"]
    assert evaluation["is_timed"] is True
    assert evaluation["time_taken_seconds"] == 80
    assert evaluation["time_limit_seconds"] == 120
    assert evaluation["time_display"] == "answered in 1:20 of 2:00"
    assert "(Answered in 1:20 of 2:00)" in evaluation["feedback"]
    assert evaluation.get("time_expired") is not True

    # Verify database persistence
    session_row = get_interview_session(aid)
    assert session_row is not None
    answers = json.loads(session_row["answers_json"])
    assert len(answers) == 1
    assert answers[0]["is_timed"] is True
    assert answers[0]["time_taken_seconds"] == 80
    assert answers[0]["time_limit_seconds"] == 120
    assert answers[0]["time_display"] == "answered in 1:20 of 2:00"


def test_interview_submit_timed_answer_expired(test_app_client, mock_gemini_client):
    """Verify submitting when countdown expires flags time_expired and formats correct limit string."""
    aid = "test_timed_aid_002"
    questions = [
        {
            "index": 0,
            "type": "Behavioral",
            "question": "Tell me about a challenging team conflict you resolved.",
            "is_behavioral": True,
        }
    ]
    sample_results = {
        "resume_analysis": {"ats_score": 80},
        "interview_questions": {"behavioral": ["Tell me about a challenging team conflict you resolved."]},
    }
    save_analysis(aid, "resume.pdf", "Microsoft", "PM", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    mock_gemini_client(payload={
        "technical_accuracy": 78,
        "communication_score": 82,
        "confidence_score": 80,
        "feedback": "Good context, but needed more focus on resolution outcomes.",
        "suggestions": [],
    })

    # Expired answer: 180 seconds out of 180 seconds (3:00 of 3:00)
    response = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "When deadlines overlapped, our frontend and backend engineers disagreed on API contracts. I scheduled a sync...",
        "question_index": 0,
        "is_timed": True,
        "time_taken_seconds": 180,
        "time_limit_seconds": 180,
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data["time_display"] == "answered in 3:00 of 3:00"
    assert data["evaluation"]["time_expired"] is True
    assert "(Answered in 3:00 of 3:00)" in data["evaluation"]["feedback"]

    # Session completed
    assert data["completed"] is True
    assert "summary" in data
    timing_summary = data["summary"]["timing_summary"]
    assert timing_summary is not None
    assert timing_summary["total_timed_questions"] == 1
    assert timing_summary["answers_within_limit"] == 1
    assert timing_summary["formatted_avg_time"] == "3:00"


def test_interview_submit_untimed_mode_backward_compatibility(test_app_client, mock_gemini_client):
    """Verify that traditional untimed answers maintain default behavior without timing annotations."""
    aid = "test_untimed_aid_003"
    questions = [
        {
            "index": 0,
            "type": "Technical",
            "question": "What is the difference between TCP and UDP?",
            "is_behavioral": False,
        }
    ]
    sample_results = {
        "resume_analysis": {"ats_score": 92},
        "interview_questions": {"technical": ["What is the difference between TCP and UDP?"]},
    }
    save_analysis(aid, "resume.pdf", "Amazon", "SDE", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    mock_gemini_client(payload={
        "technical_accuracy": 95,
        "communication_score": 90,
        "confidence_score": 92,
        "feedback": "Strong answer explaining connection-oriented vs connectionless protocols.",
        "suggestions": [],
    })

    # Submit without timing parameters
    response = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "TCP is connection-oriented, providing reliable, ordered delivery with error checking, while UDP is connectionless with low latency."
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data.get("time_display") is None
    assert data.get("is_timed") is False
    assert "answered in" not in data["evaluation"]["feedback"].lower()


# ==============================================================================
# 2. Timing Summary Computation (agents/interview_agent.py)
# ==============================================================================

def test_calculate_session_summary_with_timed_answers(interview_agent):
    """Verify calculate_session_summary calculates timing aggregates, averages, and adherence rates."""
    answers_list = [
        {
            "question_index": 0,
            "type": "Technical",
            "is_timed": True,
            "time_taken_seconds": 90,
            "time_limit_seconds": 120,
            "evaluation": {"technical_accuracy": 85, "communication_score": 80, "confidence_score": 80},
        },
        {
            "question_index": 1,
            "type": "Behavioral",
            "is_timed": True,
            "time_taken_seconds": 150,
            "time_limit_seconds": 180,
            "evaluation": {"technical_accuracy": 80, "communication_score": 90, "confidence_score": 85},
        },
        {
            "question_index": 2,
            "type": "HR",
            "is_timed": True,
            "time_taken_seconds": 130,
            "time_limit_seconds": 120,  # Exceeded limit
            "evaluation": {"technical_accuracy": 75, "communication_score": 85, "confidence_score": 80},
        },
    ]

    summary = interview_agent.calculate_session_summary(answers_list)
    assert "timing_summary" in summary
    ts = summary["timing_summary"]

    assert ts["total_timed_questions"] == 3
    assert ts["total_time_seconds"] == 370
    assert ts["average_time_per_answer_seconds"] == 123
    assert ts["formatted_avg_time"] == "2:03"
    assert ts["answers_within_limit"] == 2
    assert ts["within_limit_percentage"] == 67


def test_calculate_session_summary_untimed_returns_none(interview_agent):
    """Verify calculate_session_summary does not produce timing_summary when no timed answers exist."""
    answers_list = [
        {
            "question_index": 0,
            "type": "Technical",
            "evaluation": {"technical_accuracy": 85, "communication_score": 80, "confidence_score": 80},
        },
        {
            "question_index": 1,
            "type": "HR",
            "evaluation": {"technical_accuracy": 90, "communication_score": 85, "confidence_score": 88},
        },
    ]

    summary = interview_agent.calculate_session_summary(answers_list)
    assert summary.get("timing_summary") is None


# ==============================================================================
# 3. Report & Transcript Compilation with Timed Metrics
# ==============================================================================

def test_markdown_and_pdf_transcript_contain_timed_mode_section():
    """Verify markdown and PDF transcripts include timed mode performance summary and question timing."""
    session_data = {
        "analysis_id": "test_aid_transcript",
        "company_name": "Adobe",
        "role": "Software Engineer",
        "answers": [
            {
                "question_index": 0,
                "type": "Technical",
                "question": "How do browser rendering engines process the critical rendering path?",
                "answer": "HTML is parsed to DOM, CSS to CSSOM, combined into the Render Tree, followed by Layout and Paint.",
                "is_timed": True,
                "time_display": "answered in 1:15 of 2:00",
                "time_taken_seconds": 75,
                "time_limit_seconds": 120,
                "evaluation": {
                    "technical_accuracy": 92,
                    "communication_score": 88,
                    "confidence_score": 90,
                    "verbal_clarity_score": 90,
                    "feedback": "Accurate breakdown of DOM, CSSOM, Render tree, and composite layers.",
                    "suggestions": ["Discuss requestAnimationFrame for animation smoothness."],
                },
            }
        ],
    }

    md_output = generate_interview_transcript_markdown(session_data)
    assert "Timed Answer Mode Performance" in md_output
    assert "Average Time per Answer:" in md_output
    assert "Timing: **Answered in 1:15 of 2:00**" in md_output

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "transcript_timed.pdf"
        generate_interview_transcript_pdf(session_data, str(pdf_path))
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 500


# ==============================================================================
# 4. Template & UI Controls Verification
# ==============================================================================

def test_interview_template_contains_timed_mode_elements():
    """Verify interview.html template includes the timed mode switch, selectors, timer bar, and aria-live."""
    with open("templates/interview.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Toggle switch (unchecked / untimed by default)
    assert 'id="toggleTimedMode"' in html
    assert 'role="switch"' in html

    # Config dropdown and category selectors
    assert 'id="timedModeConfigDropdown"' in html
    assert 'id="selectTechTimeLimit"' in html
    assert 'id="selectBehavTimeLimit"' in html
    assert 'id="selectHrTimeLimit"' in html

    # Countdown timer bar and accessibility
    assert 'id="interviewTimerBar"' in html
    assert 'id="timerCountdownBadge"' in html
    assert 'role="timer"' in html
    assert 'id="interviewTimerAnnouncer"' in html
    assert 'aria-live="assertive"' in html
    assert 'role="status"' in html

    # Pacing indicators in evaluation panel & completion modal
    assert 'id="evalTimingBadge"' in html
    assert 'id="evalTimingText"' in html
    assert 'id="modalTimingStatsCard"' in html
    assert 'id="modalTimedCount"' in html
    assert 'id="modalAvgAnswerTime"' in html
    assert 'id="modalWithinLimitRate"' in html


def test_script_js_contains_timed_mode_logic():
    """Verify script.js / interview.js has the countdown timer, 15s warning color change, autoSubmitAnswer, and aria-live."""
    js_path = Path("static/js/modules/interview.js")
    if not js_path.exists():
        js_path = Path("static/js/script.js")
    js = js_path.read_text(encoding="utf-8")

    assert "function startQuestionTimer" in js
    assert "function stopQuestionTimer" in js
    assert "function announceTimerWarning" in js
    assert "function autoSubmitAnswer" in js
    assert "15 seconds remaining" in js
    assert "bg-danger" in js
    assert "is_timed" in js
    assert "time_taken_seconds" in js
    assert "time_limit_seconds" in js
