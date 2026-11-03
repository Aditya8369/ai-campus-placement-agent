"""
Comprehensive test suite for OutreachGeneratorAgent and Outreach Pitch Generator endpoints.

Tests:
1. OutreachGeneratorAgent unit tests:
   - Heuristic fallback across formal, enthusiastic, and concise tones.
   - Default tone handling for invalid tone inputs.
   - Mocked Gemini LLM success response parsing.
   - Graceful fallback when Gemini LLM raises an error.
   - Word Document (.docx) export generation and structure verification.
   - Plain text (.txt) export generation and header verification.
2. API Route integration tests:
   - POST /api/generate-outreach/<analysis_id> with valid and non-existent IDs.
   - POST /api/generate-outreach/<analysis_id> tone switching.
   - GET /api/outreach/<analysis_id>/download (.docx and .txt).
   - POST /api/outreach/download (.docx and .txt) with custom/cached content.
3. Dashboard rendering verification:
   - Presence of outreach studio card, tabs, tone controls, and preview modal.
"""

import io
import json
import tempfile
from pathlib import Path
import pytest
import docx

import config
from app import app
from utils.database import init_db, save_analysis
from agents.outreach_agent import OutreachGeneratorAgent


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
def sample_analysis_record():
    """Provides a sample analysis record dictionary for outreach tests."""
    return {
        "analysis_id": "test-outreach-1234",
        "company_name": "Google",
        "job_description": "We are seeking a Software Development Engineer with Python and distributed systems expertise.",
        "resume_filename": "candidate_cv.pdf",
        "results": {
            "resume_analysis": {
                "ats_score": 88,
                "summary": "Full-stack engineer with strong problem-solving skills in Python and distributed systems.",
                "strengths": ["Strong algorithmic foundations", "System design and microservices"],
                "weaknesses": ["Cloud deployment depth"],
                "skills": ["Python", "Algorithms", "Docker", "REST APIs"],
                "project_feedback": "Built scalable distributed indexing engine handling 10k RPS."
            },
            "job_match": {
                "match_percentage": 85,
                "matched_skills": ["Python", "Algorithms", "REST APIs"],
                "missing_skills": ["Kubernetes", "gRPC"]
            }
        }
    }


# ==============================================================================
# Unit Tests for OutreachGeneratorAgent
# ==============================================================================

def test_outreach_agent_heuristic_formal(sample_analysis_record):
    """Verify formal tone generation includes expected sections and respectful tone."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="formal", role_title="Software Engineer")

    assert outreach["tone"] == "formal"
    assert outreach["role_title"] == "Software Engineer"
    assert outreach["company_name"] == "Google"
    assert "cover_letter" in outreach and len(outreach["cover_letter"]) > 100
    assert "linkedin_inmail" in outreach and len(outreach["linkedin_inmail"]) > 50
    assert "cold_email" in outreach and len(outreach["cold_email"]) > 50
    assert isinstance(outreach["subject_lines"], list) and len(outreach["subject_lines"]) >= 3
    assert isinstance(outreach["key_highlights"], list) and len(outreach["key_highlights"]) >= 3

    assert "Dear Hiring Team at Google" in outreach["cover_letter"]
    assert "Sincerely" in outreach["cover_letter"]
    assert "Subject:" in outreach["cold_email"]


def test_outreach_agent_heuristic_enthusiastic(sample_analysis_record):
    """Verify enthusiastic tone incorporates high-energy language."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="enthusiastic")

    assert outreach["tone"] == "enthusiastic"
    assert "thrilled" in outreach["cover_letter"].lower() or "excited" in outreach["cover_letter"].lower()
    assert "Google" in outreach["cover_letter"]
    assert len(outreach["subject_lines"]) >= 2


def test_outreach_agent_heuristic_concise(sample_analysis_record):
    """Verify concise tone focuses on direct bulleted qualifications."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="concise")

    assert outreach["tone"] == "concise"
    assert "Core Qualifications" in outreach["cover_letter"] or "Summary of" in outreach["cover_letter"]
    assert len(outreach["cover_letter"]) > 0


def test_outreach_agent_invalid_tone_defaults_to_formal(sample_analysis_record):
    """Verify unsupported tone parameter gracefully defaults to 'formal'."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="nonexistent_tone_123")

    assert outreach["tone"] == "formal"
    assert "Dear Hiring Team at Google" in outreach["cover_letter"]


def test_outreach_agent_llm_success(monkeypatch, sample_analysis_record):
    """Verify that when Gemini LLM returns valid structured JSON, it is parsed and used."""
    agent = OutreachGeneratorAgent()

    mock_llm_response = {
        "tone": "formal",
        "role_title": "Backend SDE",
        "company_name": "Google",
        "cover_letter": "Custom LLM Cover Letter for Google with tailored metrics.",
        "linkedin_inmail": "Custom LLM LinkedIn note reaching out to engineering lead.",
        "cold_email": "Subject: SDE Role\n\nCustom LLM cold outreach message.",
        "subject_lines": ["Subject 1", "Subject 2", "Subject 3"],
        "key_highlights": ["Highlight 1", "Highlight 2", "Highlight 3"]
    }

    import agents.outreach_agent as oa
    monkeypatch.setattr(oa, "generate_json_response", lambda *args, **kwargs: mock_llm_response)

    res = agent.generate_outreach(sample_analysis_record, tone="formal", role_title="Backend SDE")
    assert res["cover_letter"] == "Custom LLM Cover Letter for Google with tailored metrics."
    assert res["linkedin_inmail"] == "Custom LLM LinkedIn note reaching out to engineering lead."
    assert len(res["subject_lines"]) == 3


def test_outreach_agent_llm_failure_falls_back_to_heuristic(monkeypatch, sample_analysis_record):
    """Verify that when Gemini raises an exception, the agent falls back to heuristic generation."""
    agent = OutreachGeneratorAgent()

    def mock_broken_gemini(*args, **kwargs):
        raise RuntimeError("Gemini API connection timed out.")

    import agents.outreach_agent as oa
    monkeypatch.setattr(oa, "generate_json_response", mock_broken_gemini)

    res = agent.generate_outreach(sample_analysis_record, tone="enthusiastic")
    assert res["tone"] == "enthusiastic"
    assert "Google" in res["company_name"]
    assert len(res["cover_letter"]) > 100


def test_outreach_export_to_docx(sample_analysis_record):
    """Verify export_to_docx produces a valid Word document buffer with appropriate headings."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="formal")

    docx_bytes = agent.export_to_docx(outreach, candidate_name="Test Student", company_name="Google")
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 1000

    # Parse with python-docx to verify document structure integrity
    doc = docx.Document(io.BytesIO(docx_bytes))
    headings = [p.text for p in doc.paragraphs if p.text]
    assert any("JOB APPLICATION OUTREACH PORTFOLIO" in h for h in headings)
    assert any("Tailored Cover Letter" in h for h in headings)
    assert any("LinkedIn InMail" in h for h in headings)


def test_outreach_export_to_txt(sample_analysis_record):
    """Verify export_to_txt produces clean formatted plain text."""
    agent = OutreachGeneratorAgent()
    outreach = agent.generate_outreach(sample_analysis_record, tone="formal")

    txt = agent.export_to_txt(outreach, candidate_name="Test Student", company_name="Google")
    assert isinstance(txt, str)
    assert "JOB APPLICATION OUTREACH PORTFOLIO" in txt
    assert "1. TAILORED COVER LETTER" in txt
    assert "2. LINKEDIN INMAIL / REFERRAL PITCH" in txt
    assert "3. COLD RECRUITER OUTREACH EMAIL" in txt


# ==============================================================================
# API Integration Tests
# ==============================================================================

def test_api_generate_outreach_endpoint(test_client, sample_analysis_record):
    """Verify POST /api/generate-outreach/<analysis_id> generates and returns materials."""
    aid = sample_analysis_record["analysis_id"]
    save_analysis(
        analysis_id=aid,
        resume_filename="cv.pdf",
        company_name="Google",
        job_description="Software Engineering vacancy",
        results_dict=sample_analysis_record["results"],
        student_id="student_123"
    )

    res = test_client.post(
        f"/api/generate-outreach/{aid}",
        data=json.dumps({"tone": "enthusiastic", "role_title": "Full Stack Engineer"}),
        content_type="application/json"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["analysis_id"] == aid
    assert data["tone"] == "enthusiastic"
    assert "outreach" in data
    assert "cover_letter" in data["outreach"]
    assert "linkedin_inmail" in data["outreach"]
    assert "cold_email" in data["outreach"]


def test_api_generate_outreach_not_found(test_client):
    """Verify POST /api/generate-outreach/<non_existent_id> returns 404."""
    res = test_client.post(
        "/api/generate-outreach/non-existent-analysis-id",
        data=json.dumps({"tone": "formal"}),
        content_type="application/json"
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False
    assert "not found" in data["error"].lower()


def test_api_download_outreach_docx_get(test_client, sample_analysis_record):
    """Verify GET /api/outreach/<analysis_id>/download?format=docx serves Word document."""
    aid = sample_analysis_record["analysis_id"]
    save_analysis(
        analysis_id=aid,
        resume_filename="cv.pdf",
        company_name="Google",
        job_description="Software Engineering vacancy",
        results_dict=sample_analysis_record["results"],
        student_id="student_123"
    )

    res = test_client.get(f"/api/outreach/{aid}/download?format=docx&tone=formal")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in res.content_type
    assert "attachment" in res.headers.get("Content-Disposition", "")
    assert ".docx" in res.headers.get("Content-Disposition", "")
    assert len(res.data) > 1000


def test_api_download_outreach_txt_get(test_client, sample_analysis_record):
    """Verify GET /api/outreach/<analysis_id>/download?format=txt serves plain text file."""
    aid = sample_analysis_record["analysis_id"]
    save_analysis(
        analysis_id=aid,
        resume_filename="cv.pdf",
        company_name="Google",
        job_description="Software Engineering vacancy",
        results_dict=sample_analysis_record["results"],
        student_id="student_123"
    )

    res = test_client.get(f"/api/outreach/{aid}/download?format=txt&tone=concise")
    assert res.status_code == 200
    assert "text/plain" in res.content_type
    assert "attachment" in res.headers.get("Content-Disposition", "")
    assert ".txt" in res.headers.get("Content-Disposition", "")
    assert b"JOB APPLICATION OUTREACH PORTFOLIO" in res.data


def test_api_download_outreach_custom_content_post(test_client):
    """Verify POST /api/outreach/download serves edited text as a download."""
    payload = {
        "format": "txt",
        "content_type": "cover_letter",
        "content": "Dear Hiring Manager,\n\nThis is my custom edited cover letter.",
        "company_name": "Microsoft",
        "candidate_name": "Alice Smith"
    }

    res = test_client.post(
        "/api/outreach/download",
        data=json.dumps(payload),
        content_type="application/json"
    )
    assert res.status_code == 200
    assert "text/plain" in res.content_type
    assert b"custom edited cover letter" in res.data


def test_dashboard_renders_outreach_components(test_client, sample_analysis_record):
    """Verify the dashboard page contains the outreach section card, tabs, and interactive modal."""
    aid = sample_analysis_record["analysis_id"]
    save_analysis(
        analysis_id=aid,
        resume_filename="cv.pdf",
        company_name="Google",
        job_description="Software Engineering vacancy",
        results_dict=sample_analysis_record["results"],
        student_id="student_123"
    )

    res = test_client.get(f"/dashboard/{aid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Assert Outreach section elements
    assert 'id="outreachSectionCard"' in html
    assert 'id="outreachToneGroup"' in html
    assert 'id="btnGenerateOutreach"' in html
    assert 'id="coverLetterContent"' in html
    assert 'id="linkedinInmailContent"' in html
    assert 'id="coldEmailContent"' in html

    # Assert Interactive Preview Modal
    assert 'id="outreachPreviewModal"' in html
    assert 'id="modalOutreachEditor"' in html
    assert 'id="btnModalCopyText"' in html
    assert 'id="btnModalDownloadDocx"' in html
    assert 'id="btnModalDownloadTxt"' in html

