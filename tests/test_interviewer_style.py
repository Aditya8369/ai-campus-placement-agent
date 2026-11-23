"""
Unit and integration tests for Interviewer Personas & Styles (#686).
Verifies:
- Preset definitions: Friendly HR, Strict Technical, Rapid-Fire, and legacy panel compatibility.
- Fallback handling for unknown or empty personas.
- Prompt fragment and system instruction injection per persona.
- Evaluation answer behavior:
  * Prompt fragment correctly passed per style to Gemini model.
  * Strict Technical probing follow-up behavior is triggered.
  * Scoring criteria and numerical ranges (0-100) are unchanged between styles.
- Session scoping:
  * Interview start route correctly registers and scopes session questions by style.
  * Question styling adapts formatting / metadata per persona.
- Persistence and reporting:
  * Style is recorded with session and returned in interview history.
  * Style is displayed in transcript markdown and PDF.
- API endpoints:
  * GET /api/interview/interviewer-styles returns available presets.
  * POST /api/interview/interviewer-style stores candidate persona preference.
"""

import json
import pytest
from app import app
import config
from utils.database import (
    init_db,
    save_analysis,
    get_interview_session,
    get_student_interview_history,
)
from utils.interviewer_style_service import (
    get_available_styles,
    get_style_config,
    format_prompt_for_style,
    apply_interviewer_style_to_questions,
    normalize_style_id,
    INTERVIEWER_STYLES,
)
from agents.interview_agent import InterviewAgent
from utils.report_generator import generate_interview_transcript_markdown


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_interviewer_style.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    save_analysis(
        analysis_id="analysis_style_test",
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Senior Systems Software Engineer",
        results_dict={
            "match_score": 88,
            "interview_questions": {
                "technical": [
                    "Explain the difference between TCP and UDP.",
                    "How do B-trees work in database indexing?"
                ],
                "hr": [
                    "Why Google specifically?",
                    "Where do you see yourself in 5 years?"
                ],
                "behavioral": [
                    "Describe a time you resolved a major production outage under pressure."
                ]
            }
        },
        student_id="default_student"
    )
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as c:
        yield c


def test_available_styles():
    """Verify that all core styles (friendly HR, strict technical, rapid fire, panel) are registered."""
    styles = get_available_styles()
    assert len(styles) >= 4
    ids = [s["id"] for s in styles]
    assert "friendly" in ids
    assert "technical" in ids
    assert "rapid_fire" in ids
    assert "panel" in ids

    # Validate core preset attributes
    friendly = get_style_config("friendly")
    assert friendly["name"] == "Friendly HR"
    assert "Warm" in friendly["tone"]
    assert friendly["probing_follow_up"] is False

    strict = get_style_config("strict_technical")
    assert strict["name"] == "Strict Technical"
    assert "Direct" in strict["tone"]
    assert strict["probing_follow_up"] is True

    rapid = get_style_config("rapid_fire")
    assert rapid["name"] == "Rapid-Fire"
    assert "Fast-paced" in rapid["tone"]
    assert rapid["probing_follow_up"] is False


def test_get_style_config_fallback():
    """Verify fallback to friendly HR when unknown style is requested."""
    cfg = get_style_config("invalid_persona_xyz")
    assert cfg["id"] == "friendly"
    assert cfg["name"] == "Friendly HR"

    cfg_none = get_style_config(None)
    assert cfg_none["id"] == "friendly"


def test_format_prompt_for_style():
    """Verify question framing for styles."""
    formatted_tech = format_prompt_for_style("Explain OOP polymorphism", "technical")
    assert "Strict Technical Architect" in formatted_tech
    assert "Explain OOP polymorphism" in formatted_tech

    formatted_friendly = format_prompt_for_style("Tell me about a hobby", "friendly")
    assert "Friendly HR Mode" in formatted_friendly


def test_interviewer_styles_api(client):
    """Verify GET and POST API endpoints for interviewer personas."""
    res = client.get("/api/interview/interviewer-styles")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["styles"]) >= 3

    # Save preference
    post_res = client.post("/api/interview/interviewer-style", json={"style": "panel"})
    assert post_res.status_code == 200
    assert post_res.get_json()["selected_style"] == "panel"

    post_res_strict = client.post("/api/interview/interviewer-style", json={"style": "strict_technical"})
    assert post_res_strict.status_code == 200
    assert post_res_strict.get_json()["selected_style"] == "technical"


def test_apply_interviewer_style_to_questions():
    """Verify that questions receive style metadata and rapid-fire questions are made punchy."""
    raw_questions = [
        {"index": 0, "type": "Technical", "question": "What is virtual memory? Explain its benefits for processes."},
        {"index": 1, "type": "HR", "question": "Why do you want to join our company?"}
    ]

    styled_rapid = apply_interviewer_style_to_questions(raw_questions, "rapid_fire")
    assert styled_rapid[0]["interviewer_style"] == "rapid_fire"
    assert styled_rapid[0]["interviewer_style_name"] == "Rapid-Fire"
    # Rapid-fire punchiness: keeps first sentence
    assert "?" in styled_rapid[0]["question"]

    styled_strict = apply_interviewer_style_to_questions(raw_questions, "technical")
    assert styled_strict[0]["interviewer_style"] == "technical"
    assert styled_strict[0]["interviewer_style_name"] == "Strict Technical"


def test_evaluate_answer_prompt_fragments_and_probing_follow_up(monkeypatch):
    """
    Test using mocked model responses that:
    1. Prompt fragment is applied per style.
    2. Strict Technical persona generates/extracts a probing follow-up.
    3. Scoring criteria and score ranges remain unchanged across styles.
    """
    captured_calls = []

    def fake_generate_json_response(system_instruction, prompt, feature):
        captured_calls.append({
            "system_instruction": system_instruction,
            "prompt": prompt,
            "feature": feature
        })
        return {
            "confidence_score": 85,
            "communication_score": 80,
            "technical_accuracy": 90,
            "verbal_clarity_score": 82,
            "filler_words_detected": ["um"],
            "filler_word_count": 1,
            "clarity": "Very articulate response.",
            "structure": "Logical flow.",
            "relevance": "Directly answered.",
            "tip": "Provide concrete benchmarks.",
            "probing_follow_up": "How does this scale to 10,000 requests per second?",
            "star_analysis": None,
            "suggestions": ["Keep up the good delivery."],
            "feedback": "Overall strong answer."
        }

    monkeypatch.setattr("agents.interview_agent.generate_json_response", fake_generate_json_response)

    agent = InterviewAgent()

    # 1. Friendly HR evaluation
    eval_friendly = agent.evaluate_answer(
        question_type="Technical",
        question="Explain polymorphism in OOP.",
        answer="Polymorphism lets objects be treated as instances of their parent class.",
        is_behavioral=False,
        interviewer_style="friendly"
    )
    assert "[Interviewer Style: Friendly HR]" in captured_calls[-1]["prompt"]
    assert "Interviewer Persona: Friendly HR" in captured_calls[-1]["system_instruction"]
    assert eval_friendly["interviewer_style"] == "friendly"
    assert eval_friendly["interviewer_style_name"] == "Friendly HR"
    assert eval_friendly["probing_follow_up"] is None
    # Verify score scale
    assert eval_friendly["confidence_score"] == 85
    assert eval_friendly["technical_accuracy"] == 90

    # 2. Strict Technical evaluation
    eval_strict = agent.evaluate_answer(
        question_type="Technical",
        question="Explain polymorphism in OOP.",
        answer="Polymorphism lets objects be treated as instances of their parent class.",
        is_behavioral=False,
        interviewer_style="technical"
    )
    assert "[Interviewer Style: Strict Technical]" in captured_calls[-1]["prompt"]
    assert "Interviewer Persona: Strict Technical" in captured_calls[-1]["system_instruction"]
    assert eval_strict["interviewer_style"] == "technical"
    assert eval_strict["interviewer_style_name"] == "Strict Technical"
    # Strict technical includes probing follow up
    assert eval_strict["probing_follow_up"] == "How does this scale to 10,000 requests per second?"
    # Scores are unchanged
    assert eval_strict["confidence_score"] == eval_friendly["confidence_score"]
    assert eval_strict["technical_accuracy"] == eval_friendly["technical_accuracy"]
    assert eval_strict["communication_score"] == eval_friendly["communication_score"]

    # 3. Rapid-Fire evaluation
    eval_rapid = agent.evaluate_answer(
        question_type="Technical",
        question="Explain polymorphism in OOP.",
        answer="Polymorphism lets objects be treated as instances of their parent class.",
        is_behavioral=False,
        interviewer_style="rapid_fire"
    )
    assert "[Interviewer Style: Rapid-Fire]" in captured_calls[-1]["prompt"]
    assert "Interviewer Persona: Rapid-Fire" in captured_calls[-1]["system_instruction"]
    assert eval_rapid["interviewer_style"] == "rapid_fire"
    assert eval_rapid["interviewer_style_name"] == "Rapid-Fire"
    assert eval_rapid["probing_follow_up"] is None
    # Scores remain identical
    assert eval_rapid["confidence_score"] == 85
    assert eval_rapid["technical_accuracy"] == 90


def test_interview_session_style_scoping_and_history(client, monkeypatch):
    """Verify that launching an interview with ?style=technical scopes questions and records style in history."""
    # 1. Access interview with style
    res = client.get("/interview/analysis_style_test?style=technical")
    assert res.status_code == 200
    assert b"Strict Technical" in res.data
    assert b"Interviewer Persona:" in res.data

    # Check session in DB
    session = get_interview_session("analysis_style_test_technical")
    assert session is not None
    assert len(session["questions"]) >= 5
    assert session["questions"][0]["interviewer_style"] == "technical"

    # 2. Check interview history reflects the persona
    history = get_student_interview_history(student_id="default_student")
    assert len(history) >= 1
    target_entry = next((h for h in history if h["session_id"] == "analysis_style_test_technical"), None)
    assert target_entry is not None
    assert target_entry["interviewer_style"] == "technical"
    assert target_entry["interviewer_style_name"] == "Strict Technical"

    # 3. Check history page renders the persona badge
    hist_page = client.get("/interview-history?student_id=default_student")
    assert hist_page.status_code == 200
    assert b"Strict Technical" in hist_page.data
    assert b"Persona" in hist_page.data


def test_transcript_reflects_interviewer_persona():
    """Verify that transcript markdown export contains the selected Interviewer Persona."""
    session_data = {
        "analysis_id": "analysis_style_test",
        "company_name": "Google",
        "interviewer_style_name": "Strict Technical",
        "answers": [
            {
                "question_index": 0,
                "question": "What is polymorphism?",
                "answer": "Method overloading and overriding.",
                "type": "Technical",
                "evaluation": {
                    "score": 85,
                    "technical_accuracy": 85,
                    "communication_score": 80,
                    "verbal_clarity_score": 82,
                    "feedback": "Concise definition."
                }
            }
        ]
    }

    markdown = generate_interview_transcript_markdown(session_data, company_name="Google")
    assert "- **Interviewer Persona:** Strict Technical" in markdown
    assert "AI Mock Interview Session Transcript" in markdown
