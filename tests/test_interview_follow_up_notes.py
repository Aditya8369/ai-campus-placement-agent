"""
Unit and integration tests for Post-Interview Follow-Up Note & Outreach Helper (#847).

Acceptance Criteria:
1. Each type generates a draft under 150 words with the student's detail included.
2. Nothing is sent automatically (draft only, auto_send is False, no email sent).
3. Empty detail input is handled with a generic but polite draft.
4. Tests use a mocked model response.
"""

import json
import uuid
import tempfile
from pathlib import Path
import pytest

import config
from app import app
from utils.database import init_db, save_job_application, get_job_application_by_id
from agents.follow_up_note_agent import FollowUpNoteAgent, NOTE_TYPES, MAX_WORD_COUNT


@pytest.fixture
def test_client(monkeypatch):
    """Provides a Flask test client with an isolated SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "UPLOAD_FOLDER", Path(tmpdir) / "uploads")
        monkeypatch.setattr(config, "REPORT_FOLDER", Path(tmpdir) / "reports")
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        config.REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
        init_db()

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def sample_application(test_client):
    """Creates a sample tracked application in the test database."""
    app_id = str(uuid.uuid4())
    save_job_application(
        app_id=app_id,
        student_id="student_123",
        company_name="Google",
        role_title="Software Development Engineer",
        status="Interview",
        application_date="2026-11-20",
        location="Bengaluru",
        job_type="Full-Time",
        experience_level="Entry-Level",
        notes="Had round 1 interview yesterday.",
    )
    return app_id


# ==============================================================================
# Agent Unit Tests: Mocked Model Response & Heuristic Fallback
# ==============================================================================

def test_mocked_model_thank_you_with_detail(monkeypatch):
    """Verify thank-you note generated with mocked LLM response includes detail and is under 150 words."""
    agent = FollowUpNoteAgent()

    mock_llm_response = {
        "subject": "Thank You - Google Software Engineering Interview",
        "body": (
            "Dear Hiring Team,\n\n"
            "Thank you for taking the time to speak with me yesterday regarding the Software Development Engineer "
            "role at Google. I especially enjoyed our discussion regarding the distributed caching project.\n\n"
            "Our conversation confirmed my enthusiasm for Google's engineering mission. Please let me know if "
            "you need any additional details.\n\n"
            "Best regards,\n[Your Name]"
        ),
    }

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    detail = "our discussion regarding the distributed caching project"
    result = agent.generate_note(
        company_name="Google",
        note_type="thank_you",
        interview_detail=detail,
        role_title="Software Development Engineer",
    )

    assert result["success"] is True
    assert result["note_type"] == "thank_you"
    assert result["company_name"] == "Google"
    assert result["word_count"] < 150
    assert "distributed caching" in result["body"].lower()
    assert "Subject:" in result["draft"]
    assert "[Your Name]" in result["body"]


def test_mocked_model_follow_up_with_detail(monkeypatch):
    """Verify follow-up note after one week generated with mocked LLM response is under 150 words."""
    agent = FollowUpNoteAgent()

    mock_llm_response = {
        "subject": "Following Up - Google SDE Interview",
        "body": (
            "Dear Hiring Team,\n\n"
            "I hope your week is going well. I am following up on my interview last week for the SDE position at Google. "
            "I really enjoyed our discussion about the graph database indexing system.\n\n"
            "I remain very enthusiastic about the opportunity to join the team and would welcome any updates on next steps.\n\n"
            "Best regards,\n[Your Name]"
        ),
    }

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    detail = "graph database indexing system"
    result = agent.generate_note(
        company_name="Google",
        note_type="follow_up",
        interview_detail=detail,
        role_title="SDE",
    )

    assert result["success"] is True
    assert result["note_type"] == "follow_up"
    assert result["word_count"] < 150
    assert "graph database" in result["body"].lower()


def test_mocked_model_offer_acknowledgement_with_detail(monkeypatch):
    """Verify offer acknowledgement generated with mocked LLM response is under 150 words."""
    agent = FollowUpNoteAgent()

    mock_llm_response = {
        "subject": "Offer Acknowledgement - Google",
        "body": (
            "Dear Hiring Team,\n\n"
            "Thank you very much for extending an offer to join Google as an SDE. I am thrilled and honored. "
            "Our interview conversation about the team's distributed cache architecture made me even more excited "
            "about this opportunity.\n\n"
            "I am reviewing the offer terms and will follow up shortly with my response.\n\n"
            "Best regards,\n[Your Name]"
        ),
    }

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    detail = "the team's distributed cache architecture"
    result = agent.generate_note(
        company_name="Google",
        note_type="offer_acknowledgement",
        interview_detail=detail,
        role_title="SDE",
    )

    assert result["success"] is True
    assert result["note_type"] == "offer_acknowledgement"
    assert result["word_count"] < 150
    assert "distributed cache" in result["body"].lower()


def test_mocked_model_weaves_missing_detail(monkeypatch):
    """If the LLM response omitted the student's detail, the agent weaves it in."""
    agent = FollowUpNoteAgent()

    # LLM forgot to include the detail
    mock_llm_response = {
        "subject": "Thank You - Microsoft Interview",
        "body": (
            "Dear Hiring Team,\n\n"
            "Thank you for the interview yesterday. It was a pleasure meeting you.\n\n"
            "Best regards,\n[Your Name]"
        ),
    }

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    result = agent.generate_note(
        company_name="Microsoft",
        note_type="thank_you",
        interview_detail="discussion on cloud scaling pipelines",
    )

    assert result["success"] is True
    assert "cloud scaling pipelines" in result["body"].lower()
    assert result["word_count"] < 150


def test_mocked_model_enforces_word_limit_if_llm_rambles(monkeypatch):
    """If LLM returns a verbose response exceeding 150 words, agent enforces under 150 words."""
    agent = FollowUpNoteAgent()

    # Generate 180 words
    verbose_body = "word " * 180 + "\n\nBest regards,\n[Your Name]"
    mock_llm_response = {
        "subject": "Verbose Subject",
        "body": verbose_body,
    }

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    result = agent.generate_note(
        company_name="Amazon",
        note_type="thank_you",
        interview_detail="microservices migration",
    )

    assert result["success"] is True
    assert result["word_count"] < 150


def test_heuristic_fallback_with_details_all_types():
    """Verify heuristic generator properly generates drafts under 150 words for each type with detail."""
    agent = FollowUpNoteAgent()
    detail = "learning about the low-latency matching engine"

    for ntype in ["thank_you", "follow_up", "offer_acknowledgement"]:
        result = agent._generate_heuristic_note(
            company_name="Goldman Sachs",
            note_type=ntype,
            interview_detail=detail,
            role_title="Software Engineer",
        )
        assert result["success"] is True
        assert result["note_type"] == ntype
        assert result["word_count"] < 150, f"{ntype} exceeded 150 words: {result['word_count']}"
        assert "low-latency matching engine" in result["body"].lower()
        assert "Goldman Sachs" in result["body"]
        assert "[Your Name]" in result["body"]


def test_empty_detail_handled_with_polite_generic_draft():
    """Acceptance criterion: Empty detail input is handled with a generic but polite draft under 150 words."""
    agent = FollowUpNoteAgent()

    for ntype in ["thank_you", "follow_up", "offer_acknowledgement"]:
        for empty_val in ["", "   ", None]:
            result = agent._generate_heuristic_note(
                company_name="Atlassian",
                note_type=ntype,
                interview_detail=empty_val or "",
                role_title="Backend Developer",
            )
            assert result["success"] is True
            assert result["word_count"] < 150
            assert "Atlassian" in result["body"]
            assert "[Your Name]" in result["body"]
            assert "Dear Hiring Team" in result["body"]


def test_llm_failure_falls_back_gracefully(monkeypatch):
    """When Gemini raises an error, agent gracefully falls back to deterministic heuristic."""
    agent = FollowUpNoteAgent()

    def mock_broken_gemini(*args, **kwargs):
        raise ConnectionError("Gemini endpoint unreachable")

    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", mock_broken_gemini)

    result = agent.generate_note(
        company_name="Adobe",
        note_type="thank_you",
        interview_detail="the rendering pipeline demo",
    )

    assert result["success"] is True
    assert result["company_name"] == "Adobe"
    assert "rendering pipeline demo" in result["body"]
    assert result["word_count"] < 150


# ==============================================================================
# API Integration Tests
# ==============================================================================

def test_api_generate_follow_up_note_by_app_id(test_client, sample_application, monkeypatch):
    """Verify POST /api/applications/<app_id>/follow-up-note returns draft under 150 words with detail."""
    mock_llm_response = {
        "subject": "Thank You - Google SDE Interview",
        "body": (
            "Dear Hiring Team,\n\n"
            "Thank you for taking the time to interview me yesterday for the SDE position at Google. "
            "I thoroughly enjoyed our conversation about machine learning model quantization.\n\n"
            "I look forward to hearing about next steps.\n\n"
            "Best regards,\n[Your Name]"
        ),
    }
    import agents.follow_up_note_agent as fna
    monkeypatch.setattr(fna, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    res = test_client.post(
        f"/api/applications/{sample_application}/follow-up-note",
        json={
            "type": "thank_you",
            "detail": "machine learning model quantization",
            "student_id": "student_123",
        },
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["company_name"] == "Google"
    assert data["note_type"] == "thank_you"
    assert data["word_count"] < 150
    assert "machine learning model quantization" in data["body"]
    assert data["auto_send"] is False  # Nothing sent automatically


def test_api_generate_follow_up_note_empty_detail(test_client, sample_application):
    """Verify empty detail handled with polite generic draft via API."""
    res = test_client.post(
        f"/api/applications/{sample_application}/follow-up-note",
        json={
            "type": "follow_up",
            "detail": "",
            "student_id": "student_123",
        },
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["company_name"] == "Google"
    assert data["word_count"] < 150
    assert "Google" in data["body"]
    assert data["auto_send"] is False


def test_api_generic_endpoint_by_company_name(test_client):
    """Verify POST /api/applications/follow-up-note works directly with company_name."""
    res = test_client.post(
        "/api/applications/follow-up-note",
        json={
            "company_name": "Microsoft",
            "role_title": "Software Engineer",
            "type": "offer_acknowledgement",
            "detail": "the Azure cloud storage team vision",
            "student_id": "student_123",
        },
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["company_name"] == "Microsoft"
    assert data["note_type"] == "offer_acknowledgement"
    assert data["word_count"] < 150
    assert "azure cloud storage" in data["body"].lower()
    assert data["auto_send"] is False


def test_api_unauthorized_or_missing_application(test_client):
    """Verify 404 when application ID does not exist or belongs to another student."""
    res = test_client.post(
        "/api/applications/non-existent-app-999/follow-up-note",
        json={"student_id": "student_123"},
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False


def test_api_missing_company_name(test_client):
    """Verify 400 when neither application ID nor company name is provided."""
    res = test_client.post(
        "/api/applications/follow-up-note",
        json={"type": "thank_you"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
