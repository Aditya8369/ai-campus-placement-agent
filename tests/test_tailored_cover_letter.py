"""
Comprehensive tests for Tailored Cover Letter Generator (#537).

Covers all acceptance criteria:
1. Short 3 to 4 paragraph letter structure.
2. Grounded strictly in resume facts (never claims missing skills or experience).
3. Missing job description returns a clear, helpful error message.
4. Tone choice (formal and friendly) supported.
5. Editable text area, copy, and download buttons supported.
6. Regeneration of cover letter supported.
7. Both standalone (/cover-letter) and dashboard (#pills-cover) integrations.
"""

import io
import json
import tempfile
from pathlib import Path
import pytest

import config
from app import app
from utils.database import init_db, save_analysis
from agents.outreach_agent import (
    generate_tailored_cover_letter,
    _extract_resume_facts,
    _generate_heuristic_cover_letter,
    export_cover_letter_docx,
    export_cover_letter_txt,
    OutreachGeneratorAgent,
)


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
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client


@pytest.fixture
def sample_resume():
    return """
    Jane Doe
    jane.doe@example.com | (555) 123-4567 | linkedin.com/in/janedoe | github.com/janedoe

    PROFESSIONAL SUMMARY
    Passionate Software Engineer with 2+ years of hands-on experience building web applications and backend microservices with Python, Flask, Docker, and PostgreSQL.

    EDUCATION
    B.Tech in Computer Science and Engineering, State University, 2024 - GPA: 3.8/4.0

    SKILLS
    Languages & Frameworks: Python, Flask, FastAPI, JavaScript, SQL, HTML/CSS
    Databases & Tools: PostgreSQL, Redis, Docker, Git, Linux, CI/CD

    EXPERIENCE
    Software Engineering Intern | Acme Solutions | June 2023 - Dec 2023
    - Designed and implemented high-throughput REST APIs using Flask and PostgreSQL.
    - Improved database query response times by 35% with Redis caching and index optimization.
    - Dockerized backend services for reproducible continuous deployment environments.

    PROJECTS
    Campus Placement Portal | Python, Flask, PostgreSQL, Docker
    - Developed full-stack placement portal serving 1,200+ active university students.
    - Automated resume score evaluation and company-specific interview preparation tracking.
    """


@pytest.fixture
def sample_job_description():
    return """
    We are looking for a Software Engineer to join our Platform Engineering team.
    Requirements:
    - Experience in Python backend services and REST APIs
    - Familiarity with PostgreSQL databases and Docker containerization
    - Nice to have: Rust, Kubernetes, GraphQL, AWS Cloud
    - Strong problem solving and team collaboration skills
    """


# -------------------------------------------------------------------------
# Unit Tests: Factual Extraction and Deterministic Grounding
# -------------------------------------------------------------------------

def test_extract_resume_facts(sample_resume):
    """Verify factual extractor correctly parses facts without fabrication."""
    facts = _extract_resume_facts(sample_resume)
    assert facts["candidate_name"] == "Jane Doe"
    assert "Python" in facts["skills"]
    assert "PostgreSQL" in facts["skills"]
    assert "Docker" in facts["skills"]
    # Skills never mentioned in the resume must NOT be present
    assert "Rust" not in facts["skills"]
    assert "Kubernetes" not in facts["skills"]
    assert "GraphQL" not in facts["skills"]
    assert len(facts["projects"]) >= 1
    assert any("placement" in p.lower() or "resume" in p.lower() for p in facts["projects"])


def test_cover_letter_paragraph_count(sample_resume, sample_job_description):
    """Acceptance criterion: short 3 to 4 paragraph letter."""
    result = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="Acme Tech",
        tone="formal"
    )
    assert result["success"] is True
    paras_count = result["paragraphs_count"]
    assert 3 <= paras_count <= 4, f"Expected 3 to 4 paragraphs, got {paras_count}"

    # Also verify double newline paragraph splitting
    letter_text = result["cover_letter"]
    raw_paras = [p.strip() for p in letter_text.split("\n\n") if p.strip()]
    # Including greeting and sign-off, the main body has 3 to 4 paragraphs
    body_paras = [p for p in raw_paras if not p.lower().startswith("dear ") and not p.lower().startswith("sincerely") and not p.lower().startswith("best regards")]
    assert 3 <= len(body_paras) <= 4, f"Expected 3 to 4 body paragraphs, got {len(body_paras)}"


def test_cover_letter_never_claims_missing_skills(sample_resume, sample_job_description):
    """
    Acceptance criterion: The letter never claims skills or experience missing from the resume.
    Job description mentions Rust, Kubernetes, GraphQL, AWS.
    Candidate only knows Python, Flask, Docker, PostgreSQL.
    Verify letter NEVER claims expertise in Rust, Kubernetes, or GraphQL.
    """
    result = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="Acme Tech",
        tone="formal"
    )
    letter_text = result["cover_letter"].lower()

    # Must highlight verified skills
    assert "python" in letter_text
    assert "postgresql" in letter_text or "docker" in letter_text

    # Must NOT claim unverified skills missing from the candidate's resume
    assert "rust" not in letter_text
    assert "kubernetes" not in letter_text
    assert "graphql" not in letter_text


def test_cover_letter_tone_choice(sample_resume, sample_job_description):
    """Acceptance criterion: Offer a tone choice (formal or friendly)."""
    formal_res = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="InnovateCorp",
        tone="formal"
    )
    friendly_res = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="InnovateCorp",
        tone="friendly"
    )

    assert formal_res["success"] is True
    assert friendly_res["success"] is True
    assert formal_res["tone"] == "formal"
    assert friendly_res["tone"] == "friendly"

    # Tone variations should produce distinctly different salutations or wording
    assert "Sincerely," in formal_res["cover_letter"] or "Sincerely" in formal_res["cover_letter"]
    assert "Best regards," in friendly_res["cover_letter"] or "Warmly" in friendly_res["cover_letter"] or "Best regards" in friendly_res["cover_letter"]
    assert formal_res["cover_letter"] != friendly_res["cover_letter"]


def test_cover_letter_missing_job_description():
    """Acceptance criterion: A missing job description shows a helpful message."""
    # Direct function call with empty JD
    res = generate_tailored_cover_letter(
        resume_text="Some resume text with Python",
        job_description="",
        company_name="Test Company",
        tone="formal"
    )
    assert res["success"] is False
    assert "required" in res["error"].lower()
    assert res.get("missing_field") == "job_description"

    # Direct function call with whitespace-only JD
    res_ws = generate_tailored_cover_letter(
        resume_text="Some resume text with Python",
        job_description="   \n  \t  ",
        company_name="Test Company",
        tone="formal"
    )
    assert res_ws["success"] is False
    assert "job description is required" in res_ws["error"].lower()


def test_cover_letter_regeneration(sample_resume, sample_job_description):
    """Acceptance criterion: The student can regenerate the letter."""
    # First generation
    res1 = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="TechStart",
        tone="formal"
    )
    assert res1["success"] is True
    letter1 = res1["cover_letter"]

    # Student regenerates with friendly tone
    res2 = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="TechStart",
        tone="friendly"
    )
    assert res2["success"] is True
    letter2 = res2["cover_letter"]

    assert len(letter1) > 100
    assert len(letter2) > 100
    assert letter1 != letter2


def test_export_cover_letter_txt(sample_resume, sample_job_description):
    """Test plain text file formatting and headers."""
    gen = generate_tailored_cover_letter(
        resume_text=sample_resume,
        job_description=sample_job_description,
        company_name="Stripe",
        tone="formal"
    )
    txt_out = export_cover_letter_txt(
        cover_letter_text=gen["cover_letter"],
        candidate_name="Jane Doe",
        company_name="Stripe",
        role_title="Software Engineer"
    )
    assert isinstance(txt_out, str)
    assert "Jane Doe" in txt_out
    assert "Stripe" in txt_out
    assert len(txt_out) > 100


# -------------------------------------------------------------------------
# Integration Tests: Flask Endpoints
# -------------------------------------------------------------------------

def test_api_generate_cover_letter_missing_jd(test_client, sample_resume):
    """POST /api/cover-letter/generate returns 400 when job description is missing."""
    resp = test_client.post(
        "/api/cover-letter/generate",
        data=json.dumps({
            "resume_text": sample_resume,
            "job_description": "",
            "company_name": "Meta"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "job description is required" in data["error"].lower()
    assert data["missing_field"] == "job_description"


def test_api_generate_cover_letter_success(test_client, sample_resume, sample_job_description):
    """POST /api/cover-letter/generate generates tailored letter with tone choice."""
    resp = test_client.post(
        "/api/cover-letter/generate",
        data=json.dumps({
            "resume_text": sample_resume,
            "job_description": sample_job_description,
            "company_name": "Microsoft",
            "tone": "friendly"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "cover_letter" in data
    assert 3 <= data["paragraphs_count"] <= 4
    assert data["word_count"] > 100
    assert data["tone"] == "friendly"
    assert "Microsoft" in data["cover_letter"]


def test_api_analysis_cover_letter_success(test_client, sample_job_description):
    """POST /api/analysis/<analysis_id>/cover-letter retrieves resume from analysis and generates letter."""
    # Seed analysis record
    analysis_record = {
        "analysis_id": "test-tailored-cov-999",
        "company_name": "Amazon",
        "job_description": sample_job_description,
        "resume_filename": "jane_cv.pdf",
        "results": {
            "resume_text": "Jane Doe\nSkills: Python, Flask, Docker, PostgreSQL\nExperience: Built microservices at Acme",
            "resume_analysis": {
                "ats_score": 85,
                "skills": ["Python", "Flask", "Docker", "PostgreSQL"],
                "summary": "Software engineer with microservices expertise."
            },
            "job_match": {
                "match_percentage": 80,
                "matched_skills": ["Python", "Docker", "PostgreSQL"]
            }
        }
    }
    save_analysis(analysis_record)

    # Call endpoint with pasted JD
    resp = test_client.post(
        "/api/analysis/test-tailored-cov-999/cover-letter",
        data=json.dumps({
            "job_description": sample_job_description,
            "company_name": "Amazon AWS",
            "tone": "formal"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert 3 <= data["paragraphs_count"] <= 4
    assert "Amazon AWS" in data["cover_letter"]


def test_api_analysis_cover_letter_missing_jd(test_client):
    """POST /api/analysis/<analysis_id>/cover-letter returns 400 when JD is missing."""
    analysis_record = {
        "analysis_id": "test-tailored-cov-missing",
        "company_name": "Apple",
        "job_description": "",
        "resume_filename": "cv.pdf",
        "results": {
            "resume_text": "Alex Smith\nSkills: Java, Spring Boot",
            "resume_analysis": {"ats_score": 80}
        }
    }
    save_analysis(analysis_record)

    resp = test_client.post(
        "/api/analysis/test-tailored-cov-missing/cover-letter",
        data=json.dumps({
            "job_description": "   ",
            "company_name": "Apple"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "job description is required" in data["error"].lower()


def test_api_download_cover_letter_txt(test_client):
    """POST /api/cover-letter/download for plain text file."""
    letter_content = (
        "Dear Hiring Manager,\n\n"
        "I am writing to express my enthusiastic interest in the Software Engineer role.\n\n"
        "With hands-on experience developing backend microservices in Python and PostgreSQL, I improved query performance by 35%.\n\n"
        "Thank you for your time and consideration.\n\n"
        "Sincerely,\nJane Doe"
    )
    resp = test_client.post(
        "/api/cover-letter/download",
        data=json.dumps({
            "content": letter_content,
            "format": "txt",
            "company_name": "Google",
            "candidate_name": "Jane Doe"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    assert "text/plain" in resp.content_type
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert b"Jane Doe" in resp.data
    assert b"Google" in resp.data


def test_api_download_cover_letter_docx(test_client):
    """POST /api/cover-letter/download for Word document (.docx)."""
    letter_content = (
        "Dear Hiring Team,\n\n"
        "I am excited to apply for the Engineer position.\n\n"
        "My verified background in Python and Docker directly aligns with your requirements.\n\n"
        "Best regards,\nJane Doe"
    )
    resp = test_client.post(
        "/api/cover-letter/download",
        data=json.dumps({
            "content": letter_content,
            "format": "docx",
            "company_name": "Netflix",
            "candidate_name": "Jane Doe"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    assert "wordprocessingml.document" in resp.content_type or "octet-stream" in resp.content_type
    assert len(resp.data) > 0


def test_api_download_cover_letter_empty_error(test_client):
    """POST /api/cover-letter/download fails gracefully when content is empty."""
    resp = test_client.post(
        "/api/cover-letter/download",
        data=json.dumps({
            "content": "   ",
            "format": "docx"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "empty" in data["error"].lower()


def test_standalone_cover_letter_view(test_client):
    """GET /cover-letter renders the standalone generator page."""
    resp = test_client.get("/cover-letter")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Tailored Cover Letter Generator" in html
    assert "standaloneJdInput" in html
    assert "standaloneJdWarning" in html
    assert "toneFormalBtn" in html
    assert "toneFriendlyBtn" in html
    assert "standaloneLetterEditor" in html
    assert "btnStandaloneCopy" in html
    assert "btnStandaloneDocx" in html
    assert "btnStandaloneTxt" in html


def test_dashboard_tailored_cover_letter_studio(test_client, sample_job_description):
    """Dashboard (#pills-cover) contains all tailored cover letter controls."""
    analysis_record = {
        "analysis_id": "test-dash-cover-537",
        "company_name": "Spotify",
        "job_description": sample_job_description,
        "resume_filename": "candidate.pdf",
        "results": {
            "resume_text": "Jane Doe\nSkills: Python, Docker",
            "resume_analysis": {"ats_score": 90, "skills": ["Python", "Docker"]},
            "job_match": {"match_percentage": 85, "matched_skills": ["Python"]}
        }
    }
    save_analysis(analysis_record)

    resp = test_client.get("/dashboard/test-dash-cover-537")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Check key studio elements
    assert "coverLetterJobDescInput" in html
    assert "coverLetterJdWarning" in html
    assert "coverLetterToneFormal" in html
    assert "coverLetterToneFriendly" in html
    assert "btnGenerateTailoredLetter" in html
    assert "coverLetterEditor" in html
    assert "btnCopyCoverLetter" in html
    assert "btnDownloadCoverDocx" in html
    assert "btnDownloadCoverTxt" in html
    assert "coverLetterParaCount" in html
    assert "coverLetterWordCount" in html
