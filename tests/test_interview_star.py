"""
Unit and integration tests for STAR Method Evaluation on Behavioural Interview Answers (#303).

Verifies:
1. Behavioral question detection by category and phrasing.
2. Complete STAR block evaluation (all 4 parts present + tip).
3. Partial STAR block evaluation with weak and missing components highlighted.
4. Missing STAR block handling (backward compatibility without crash).
5. Malformed STAR block handling (string, unexpected types, invalid statuses).
6. Technical questions remain unaffected (star_analysis is None).
7. Submit interview answer route returns STAR checklist for behavioral questions and None for technical questions.
8. Template rendering of STAR badges (present, weak, missing) and tips.
9. Markdown and PDF transcripts include STAR structure checklist.
"""

import os
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
    update_interview_session,
)
from agents.interview_agent import InterviewAgent
from utils.report_generator import (
    generate_interview_transcript_markdown,
    generate_interview_transcript_pdf,
)


@pytest.fixture
def interview_agent():
    return InterviewAgent()


# ==============================================================================
# 1. Behavioral Question Identification Tests
# ==============================================================================

def test_is_behavioral_question_by_category(interview_agent):
    """Verify categorization detects behavioral questions by category name."""
    assert interview_agent.is_behavioral_question("What is an array?", "Behavioral") is True
    assert interview_agent.is_behavioral_question("What is an array?", "behavioral") is True
    assert interview_agent.is_behavioral_question("Explain polymorphism", "Technical") is False
    assert interview_agent.is_behavioral_question("Solve two sum", "Coding") is False


def test_is_behavioral_question_by_phrasing(interview_agent):
    """Verify categorization detects behavioral phrasing even if category is HR or general."""
    assert interview_agent.is_behavioral_question("Tell me about a time you handled a difficult stakeholder.", "HR") is True
    assert interview_agent.is_behavioral_question("Describe a situation where a production deployment failed.", "General") is True
    assert interview_agent.is_behavioral_question("Give an example of a conflict you resolved with a teammate.", "HR") is True
    assert interview_agent.is_behavioral_question("How do you handle high pressure deadlines and burnout?", "HR") is True
    assert interview_agent.is_behavioral_question("Walk me through a project deliverable that did not go according to plan.", "HR") is True

    # Technical phrasing should not be flagged as behavioral
    assert interview_agent.is_behavioral_question("How does B-Tree indexing work in MySQL?", "Technical") is False
    assert interview_agent.is_behavioral_question("Explain the difference between TCP and UDP.", "Technical") is False


# ==============================================================================
# 2. Mocked Gemini Responses for Complete, Partial, Missing & Malformed STAR Blocks
# ==============================================================================

def test_evaluate_answer_complete_star_block(mock_gemini_client, interview_agent):
    """Complete STAR block: All 4 components present with improvement tip."""
    payload = {
        "technical_accuracy": 85,
        "communication_score": 90,
        "confidence_score": 88,
        "feedback": "Outstanding answer following the STAR methodology.",
        "suggestions": ["Keep up the structured delivery."],
        "star_analysis": {
            "situation": "present",
            "task": "present",
            "action": "present",
            "result": "present",
            "tip": "Excellent use of quantitative outcomes to anchor your result."
        }
    }
    mock_gemini_client(payload=payload)

    res = interview_agent.evaluate_answer(
        question_type="Behavioral",
        question="Tell me about a time you resolved a major production outage.",
        answer="During peak Black Friday sales, our checkout API threw 500 errors (Situation). I was tasked as the on-call engineer to restore payments within 15 minutes (Task). I analyzed server logs, identified a deadlock in the connection pool, and rolled back the latest migration (Action). Downtime was limited to 8 minutes and 99.9% of transactions succeeded (Result).",
        is_behavioral=True,
    )

    star = res.get("star_analysis")
    assert star is not None
    assert star["situation"] == "present"
    assert star["task"] == "present"
    assert star["action"] == "present"
    assert star["result"] == "present"
    assert "quantitative outcomes" in star["tip"]


def test_evaluate_answer_partial_star_block(mock_gemini_client, interview_agent):
    """Partial STAR block: Contains weak task and missing result."""
    payload = {
        "technical_accuracy": 70,
        "communication_score": 75,
        "confidence_score": 72,
        "feedback": "Good situation and action details, but your role's task was vague and you did not share the final outcome.",
        "suggestions": ["Explicitly mention what happened after your actions."],
        "star_analysis": {
            "situation": "present",
            "task": "weak",
            "action": "present",
            "result": "missing",
            "tip": "Conclude your answer with measurable results, such as latency reduction or team impact."
        }
    }
    mock_gemini_client(payload=payload)

    res = interview_agent.evaluate_answer(
        question_type="Behavioral",
        question="Describe a time you dealt with a difficult team member.",
        answer="We were working on our final year capstone project. One member was not contributing. I scheduled a private chat with him to understand his roadblocks.",
        is_behavioral=True,
    )

    star = res.get("star_analysis")
    assert star is not None
    assert star["situation"] == "present"
    assert star["task"] == "weak"
    assert star["action"] == "present"
    assert star["result"] == "missing"
    assert "measurable results" in star["tip"]


def test_evaluate_answer_missing_star_block_does_not_break(mock_gemini_client, interview_agent):
    """Missing STAR block: Response omits star_analysis; agent defaults safely without crashing."""
    payload = {
        "technical_accuracy": 80,
        "communication_score": 82,
        "confidence_score": 79,
        "feedback": "Solid response describing previous work experience.",
        "suggestions": ["Add more technical depth."]
    }
    mock_gemini_client(payload=payload)

    res = interview_agent.evaluate_answer(
        question_type="Behavioral",
        question="Tell me about a time you learned a new technology under tight deadlines.",
        answer="I learned Golang in two weeks to migrate our internal data pipeline service.",
        is_behavioral=True,
    )

    assert res["technical_accuracy"] == 80
    assert res["communication_score"] == 82
    # star_analysis should be None or empty safely
    assert res.get("star_analysis") is None


def test_evaluate_answer_malformed_star_block_does_not_break(mock_gemini_client, interview_agent):
    """Malformed STAR block: Non-dict types, invalid statuses, or corrupted json do not crash."""
    # Case 1: star_analysis is a plain string
    payload_str = {
        "technical_accuracy": 75,
        "communication_score": 75,
        "confidence_score": 75,
        "feedback": "Acceptable answer.",
        "suggestions": [],
        "star_analysis": "Candidate covered situation and action well."
    }
    mock_gemini_client(payload=payload_str)
    res1 = interview_agent.evaluate_answer(
        "Behavioral", "Tell me about a project", "I worked on a project.", is_behavioral=True
    )
    assert res1.get("star_analysis") is None

    # Case 2: star_analysis has non-standard values (e.g. 'done', 'yes', 'no')
    payload_variants = {
        "technical_accuracy": 75,
        "communication_score": 75,
        "confidence_score": 75,
        "feedback": "Acceptable answer.",
        "suggestions": [],
        "star_analysis": {
            "situation": "YES",
            "task": "PARTIAL",
            "action": "covered",
            "result": "NO",
            "tip": 12345  # Non-string tip
        }
    }
    mock_gemini_client(payload=payload_variants)
    res2 = interview_agent.evaluate_answer(
        "Behavioral", "Tell me about a conflict", "Conflict resolution.", is_behavioral=True
    )
    star2 = res2.get("star_analysis")
    assert star2 is not None
    assert star2["situation"] == "present"
    assert star2["task"] == "weak"
    assert star2["action"] == "present"
    assert star2["result"] == "missing"
    assert star2["tip"] == "12345"


def test_technical_questions_unaffected_by_star_evaluation(mock_gemini_client, interview_agent):
    """Technical questions should strictly have star_analysis set to None."""
    payload = {
        "technical_accuracy": 95,
        "communication_score": 90,
        "confidence_score": 88,
        "feedback": "Clear explanation of database normalization forms.",
        "suggestions": ["Include an example of Boyce-Codd normal form."],
        # Even if model erroneously returned a star_analysis block:
        "star_analysis": {
            "situation": "present",
            "task": "present",
            "action": "present",
            "result": "present",
            "tip": "Irrelevant for technical round."
        }
    }
    mock_gemini_client(payload=payload)

    res = interview_agent.evaluate_answer(
        question_type="Technical",
        question="Explain 1NF, 2NF, and 3NF normalization in relational databases.",
        answer="1NF removes repeating groups, 2NF eliminates partial dependencies, and 3NF removes transitive dependencies.",
        is_behavioral=False,
    )

    assert res["technical_accuracy"] == 95
    assert res["communication_score"] == 90
    assert res.get("star_analysis") is None


# ==============================================================================
# 3. Web Route & Live Submission Tests
# ==============================================================================

@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with temporary sqlite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_interview_star.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        init_db()

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_interview_submit_behavioral_and_technical(test_app_client, mock_gemini_client):
    """Verify /interview/<aid>/submit route parses is_behavioral and includes STAR analysis."""
    aid = "test_star_aid_303"
    questions = [
        {
            "index": 0,
            "type": "Behavioral",
            "question": "Tell me about a time you handled constructive criticism.",
            "is_behavioral": True,
        },
        {
            "index": 1,
            "type": "Technical",
            "question": "How do goroutines differ from operating system threads?",
            "is_behavioral": False,
        },
    ]

    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "interview_questions": {
            "behavioral": ["Tell me about a time you handled constructive criticism."],
            "technical": ["How do goroutines differ from operating system threads?"],
        },
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    # 1. Submit answer to question 0 (Behavioral)
    behav_payload = {
        "technical_accuracy": 82,
        "communication_score": 88,
        "confidence_score": 85,
        "feedback": "Great self-awareness.",
        "suggestions": ["Provide more context."],
        "star_analysis": {
            "situation": "present",
            "task": "present",
            "action": "present",
            "result": "weak",
            "tip": "Share what you accomplished after incorporating the feedback."
        }
    }
    mock_gemini_client(payload=behav_payload)

    resp0 = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "My team lead noted my tests lacked edge case coverage. I embraced the feedback, studied property-based testing, and refactored our test suite."
    })
    assert resp0.status_code == 200
    data0 = resp0.get_json()
    assert "evaluation" in data0
    eval0 = data0["evaluation"]
    assert eval0["star_analysis"] is not None
    assert eval0["star_analysis"]["situation"] == "present"
    assert eval0["star_analysis"]["result"] == "weak"
    assert "Share what you accomplished" in eval0["star_analysis"]["tip"]

    # 2. Submit answer to question 1 (Technical)
    tech_payload = {
        "technical_accuracy": 94,
        "communication_score": 88,
        "confidence_score": 90,
        "feedback": "Accurate distinction regarding user space multiplexing vs kernel scheduling.",
        "suggestions": [],
    }
    mock_gemini_client(payload=tech_payload)

    resp1 = test_app_client.post(f"/interview/{aid}/submit", json={
        "answer": "Goroutines are managed by the Go runtime in user space with a tiny 2KB initial stack, whereas OS threads are scheduled by the kernel with a 1-2MB stack."
    })
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert "evaluation" in data1
    eval1 = data1["evaluation"]
    assert eval1.get("star_analysis") is None


# ==============================================================================
# 4. Template Rendering Tests (Badges, Missing Parts Highlighted, Soft Fail)
# ==============================================================================

def test_interview_template_renders_star_badges(test_app_client):
    """Verify interview.html template renders STAR badges with appropriate colors."""
    aid = "test_star_ui_aid"
    questions = [
        {"index": 0, "type": "Behavioral", "question": "Tell me about a project failure.", "is_behavioral": True},
        {"index": 1, "type": "Behavioral", "question": "Tell me about a success.", "is_behavioral": True}
    ]
    answers = [
        {
            "question_index": 0,
            "type": "Behavioral",
            "question": "Tell me about a project failure.",
            "answer": "Our microservice ran out of memory.",
            "evaluation": {
                "technical_accuracy": 70,
                "communication_score": 75,
                "confidence_score": 72,
                "verbal_clarity_score": 75,
                "feedback": "Good attempt at explaining the outage.",
                "suggestions": ["Highlight what you learned."],
                "star_analysis": {
                    "situation": "present",
                    "task": "weak",
                    "action": "present",
                    "result": "missing",
                    "tip": "Explain the final lessons learned and how future failures were prevented."
                }
            }
        }
    ]
    save_analysis(aid, "test.pdf", "Amazon", "SDE", {"resume_analysis": {"ats_score": 80}})
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)
    update_interview_session(interview_id=aid, current_question_index=1, answers_list=answers, completed=False)

    resp = test_app_client.get(f"/interview/{aid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "STAR Structure Checklist" in html
    # Situation: present (bg-success-subtle)
    assert "Situation: Present" in html
    assert "bg-success-subtle" in html
    # Task: weak (bg-warning-subtle)
    assert "Task: Weak" in html
    assert "bg-warning-subtle" in html
    # Result: missing (bg-danger-subtle)
    assert "Result: Missing" in html
    assert "bg-danger-subtle" in html
    # Improvement tip displayed
    assert "Explain the final lessons learned" in html


def test_interview_template_missing_star_block_hides_checklist(test_app_client):
    """Verify template hides STAR checklist when star_analysis is None without throwing errors."""
    aid = "test_star_missing_ui_aid"
    questions = [
        {"index": 0, "type": "Technical", "question": "Explain quicksort.", "is_behavioral": False},
        {"index": 1, "type": "Technical", "question": "Explain mergesort.", "is_behavioral": False}
    ]
    answers = [
        {
            "question_index": 0,
            "type": "Technical",
            "question": "Explain quicksort.",
            "answer": "Quicksort is a divide and conquer algorithm choosing a pivot element.",
            "evaluation": {
                "technical_accuracy": 90,
                "communication_score": 85,
                "confidence_score": 85,
                "verbal_clarity_score": 85,
                "feedback": "Clear explanation of partitioning.",
                "suggestions": [],
                "star_analysis": None
            }
        }
    ]
    save_analysis(aid, "test.pdf", "Amazon", "SDE", {"resume_analysis": {"ats_score": 80}})
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)
    update_interview_session(interview_id=aid, current_question_index=1, answers_list=answers, completed=False)

    resp = test_app_client.get(f"/interview/{aid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "STAR Structure Checklist" not in html
    assert "Clear explanation of partitioning." in html


# ==============================================================================
# 5. Export Tests (Markdown & PDF Transcripts)
# ==============================================================================

def test_markdown_and_pdf_transcripts_include_star_summary():
    """Verify Markdown and PDF transcript generators format STAR checklist accurately."""
    session_data = {
        "analysis_id": "test_star_export_aid",
        "company_name": "Microsoft",
        "answers": [
            {
                "question_index": 0,
                "type": "Behavioral",
                "question": "Tell me about a time you demonstrated leadership under pressure.",
                "answer": "When our lead was absent, I took over sprint planning and unblocked our teammates.",
                "evaluation": {
                    "technical_accuracy": 85,
                    "communication_score": 90,
                    "confidence_score": 88,
                    "verbal_clarity_score": 89,
                    "feedback": "Strong initiative demonstrated.",
                    "suggestions": ["Mention specific velocity metrics."],
                    "star_analysis": {
                        "situation": "present",
                        "task": "present",
                        "action": "present",
                        "result": "weak",
                        "tip": "Share sprint completion percentage."
                    }
                }
            },
            {
                "question_index": 1,
                "type": "Technical",
                "question": "Explain deadlock conditions in OS.",
                "answer": "Mutual exclusion, hold and wait, no preemption, and circular wait.",
                "evaluation": {
                    "technical_accuracy": 98,
                    "communication_score": 92,
                    "confidence_score": 95,
                    "verbal_clarity_score": 94,
                    "feedback": "All Coffman conditions accurately listed.",
                    "suggestions": [],
                    "star_analysis": None
                }
            }
        ]
    }

    # 1. Markdown transcript verification
    md = generate_interview_transcript_markdown(session_data, company_name="Microsoft")
    assert "STAR Structure Checklist:" in md
    assert "Situation: **Present**" in md
    assert "Result: **Weak**" in md
    assert "STAR Tip:** Share sprint completion percentage." in md

    # 2. PDF transcript verification
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "star_transcript.pdf")
        out_path = generate_interview_transcript_pdf(
            session_data=session_data,
            output_path=pdf_path,
            company_name="Microsoft"
        )
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 1000
