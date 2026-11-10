"""
Unit and integration tests for Privacy Notice page and mandatory resume upload consent (#304).
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from app import app
from agents.coordinator import CoordinatorAgent


SAMPLE_RESUME = (
    "Senior Computer Science candidate with Python, Docker, Algorithms, and System Design experience. "
    "Led campus placement club and developed microservice platforms for university events."
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test-privacy-student"
        yield client


def test_privacy_page_renders_successfully(client):
    """
    Verify GET /privacy returns HTTP 200 and clearly explains:
    - What data is collected
    - Third-party AI processing via Gemini API
    - Local storage in SQLite
    - Data retention policy
    - Deletion procedures via /history and /delete-account
    """
    res = client.get("/privacy")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Key plain-language sections
    assert "Privacy Notice" in html
    assert "What Data Is Collected" in html
    assert "Resume Content" in html
    assert "Gemini API" in html
    assert "What Is Stored and Where" in html
    assert "SQLite" in html or "campus_agent.db" in html
    assert "Data Retention" in html
    assert "How to Delete Your Data" in html
    assert "/history" in html
    assert "/delete-account" in html


def test_privacy_page_reachable_from_footer_and_upload_form(client):
    """
    Verify the privacy notice is reachable from both the upload form and the footer on the landing page.
    """
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Consent checkbox on upload form
    assert 'name="privacy_consent"' in html
    assert 'id="privacyConsentCheck"' in html
    assert 'required' in html

    # Link to privacy notice from within the consent label
    assert '/privacy' in html

    # Link to privacy notice in the page footer
    assert '<footer' in html
    footer_section = html[html.find('<footer'):]
    assert '/privacy' in footer_section
    assert 'Privacy Notice' in footer_section


def test_analyze_route_rejects_missing_consent(client):
    """
    Verify that submitting the analysis form without consent is rejected with a clear message.
    """
    app.config["ENFORCE_CONSENT_IN_TESTS"] = True
    try:
        data = {
            "resume_text": SAMPLE_RESUME,
            "company": "Google",
            "job_description": "Software Engineer"
            # Omitting privacy_consent
        }
        res = client.post("/analyze", data=data, follow_redirects=True)
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Please agree to the privacy notice and consent to data processing" in html
    finally:
        app.config.pop("ENFORCE_CONSENT_IN_TESTS", None)


def test_analyze_route_rejects_explicit_false_consent(client):
    """
    Verify that submitting with privacy_consent="false" is rejected.
    """
    data = {
        "resume_text": SAMPLE_RESUME,
        "company": "Microsoft",
        "privacy_consent": "false"
    }
    res = client.post("/analyze", data=data, follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Please agree to the privacy notice and consent to data processing" in html


def test_analyze_route_accepts_valid_consent(client, monkeypatch):
    """
    Verify that submitting with valid consent (privacy_consent="true") passes validation and proceeds.
    """
    dummy_payload = {
        "resume_analysis": {"skills": ["Python", "Docker"], "ats_score": 88, "strengths": ["Python"], "weaknesses": []},
        "job_compatibility": {"match_percentage": 92, "matching_skills": ["Python"]},
        "job_match": {"match_percentage": 92, "matched_skills": ["Python"], "missing_skills": [], "top_5_resume_changes": []},
        "skill_gap": [],
        "roadmap": {"weeks": []},
        "learning_roadmap": [],
        "interview_preparation": {"questions": []},
    }
    monkeypatch.setattr(CoordinatorAgent, "analyze", lambda self, *args, **kwargs: dummy_payload)

    app.config["ENFORCE_CONSENT_IN_TESTS"] = True
    try:
        data = {
            "resume_text": SAMPLE_RESUME,
            "company": "Amazon",
            "job_description": "Cloud Engineer",
            "privacy_consent": "true"
        }
        res = client.post("/analyze", data=data, follow_redirects=False)
        assert res.status_code == 302
        assert "/dashboard/" in res.headers["Location"]
    finally:
        app.config.pop("ENFORCE_CONSENT_IN_TESTS", None)


def test_api_analysis_start_rejects_missing_consent(client):
    """
    Verify that asynchronous API analysis start rejects requests lacking consent with HTTP 400.
    """
    app.config["ENFORCE_CONSENT_IN_TESTS"] = True
    try:
        data = {
            "resume_text": SAMPLE_RESUME,
            "company": "General"
            # Missing privacy_consent
        }
        res = client.post("/api/analysis/start", data=data)
        assert res.status_code == 400
        json_resp = res.get_json()
        assert json_resp["success"] is False
        assert "Please agree to the privacy notice and consent to data processing" in json_resp["error"]
    finally:
        app.config.pop("ENFORCE_CONSENT_IN_TESTS", None)


def test_api_analysis_start_accepts_valid_consent(client, monkeypatch):
    """
    Verify that API analysis start accepts valid consent and starts task.
    """
    app.config["ENFORCE_CONSENT_IN_TESTS"] = True
    try:
        data = {
            "resume_text": SAMPLE_RESUME,
            "company": "General",
            "privacy_consent": "true"
        }
        res = client.post("/api/analysis/start", data=data)
        assert res.status_code in (200, 202)
        json_resp = res.get_json()
        assert json_resp["success"] is True
        assert "task_id" in json_resp
        assert "stream_url" in json_resp
    finally:
        app.config.pop("ENFORCE_CONSENT_IN_TESTS", None)


def test_batch_compare_rejects_missing_consent(client):
    """
    Verify that multi-company batch comparison rejects missing consent.
    """
    app.config["ENFORCE_CONSENT_IN_TESTS"] = True
    try:
        # Form submission: redirects with flashed message
        form_data = {
            "resume_text": SAMPLE_RESUME,
            "companies": "Google,Microsoft",
            # missing consent
        }
        res_form = client.post("/api/analysis/batch-compare", data=form_data, follow_redirects=True)
        assert res_form.status_code == 200
        assert "Please agree to the privacy notice" in res_form.data.decode("utf-8")

        # AJAX / JSON submission: returns HTTP 400 with JSON error
        res_json = client.post(
            "/api/analysis/batch-compare",
            data=form_data,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert res_json.status_code == 400
        json_resp = res_json.get_json()
        assert json_resp["success"] is False
        assert "Please agree to the privacy notice" in json_resp["error"]
    finally:
        app.config.pop("ENFORCE_CONSENT_IN_TESTS", None)


def test_readme_documents_privacy_policy():
    """
    Verify README.md contains a dedicated Privacy section linking to /privacy and explaining consent.
    """
    from pathlib import Path
    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")

    assert "Privacy & Data Protection" in content
    assert "/privacy" in content
    assert "Gemini" in content
    assert "SQLite" in content
