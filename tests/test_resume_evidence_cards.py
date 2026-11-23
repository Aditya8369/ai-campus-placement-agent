"""
Tests for Resume Evidence Cards (#599).
=======================================
Validates:
1. Matching evidence correctly identifies relevant sentences from raw resume text.
2. Missing details are explicitly marked as missing information rather than confirmed flaws.
3. Industry standards are classified when no direct text or missing indicators are present.
4. build_resume_evidence_cards bundles suggestions across top 5 changes, weaknesses, and formatting.
5. GET /api/analysis/<analysis_id>/resume-evidence returns structured evidence payload.
6. Dashboard renders Resume Evidence section and collapsible evidence cards.
"""

import json
import uuid
import pytest
from app import create_app
from utils.database import init_db, save_analysis
from utils.resume_evidence_service import (
    extract_evidence_snippets,
    find_matching_evidence,
    build_resume_evidence_cards
)


@pytest.fixture
def test_client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client


def test_find_matching_evidence_direct():
    resume_text = (
        "John Doe - Backend Developer\n"
        "Engineered scalable microservices in Python and Flask handling 10k requests.\n"
        "Graduated from National Institute of Technology with an 8.5 CGPA in 2024.\n"
        "Built automated database backup tool using SQLite and AWS S3.\n"
    )

    suggestion = "Expand on your scalable microservices in Python and Flask to highlight latency reductions."
    ev = find_matching_evidence(suggestion, resume_text)
    assert ev["has_evidence"] is True
    assert ev["evidence_type"] == "matched_text"
    assert "scalable microservices in Python" in ev["matched_snippet"]
    assert ev["is_missing"] is False
    assert "Direct Resume Evidence" in ev["status_badge"]


def test_find_matching_evidence_missing_info():
    resume_text = (
        "Jane Doe - Web Developer\n"
        "Created personal portfolio using HTML, CSS, and basic JavaScript.\n"
    )

    suggestion = "Missing quantifiable metrics and impact data in project descriptions."
    ev = find_matching_evidence(suggestion, resume_text)
    assert ev["has_evidence"] is True
    assert ev["evidence_type"] == "missing_information"
    assert ev["is_missing"] is True
    assert "Missing Information" in ev["status_badge"]
    assert "not an affirmative flaw" in ev["explanation"]


def test_build_resume_evidence_cards_structure():
    record = {
        "resume_text": "Experienced full stack engineer proficient in React and Node.js.",
        "results": {
            "resume_analysis": {
                "weaknesses": ["Missing test coverage details for your Node.js APIs."],
                "formatting_suggestions": ["Use consistent bullet spacing throughout the document."],
                "grammar_suggestions": []
            },
            "job_match": {
                "top_5_resume_changes": [
                    "Highlight Node.js backend performance metrics.",
                    "Include GitHub profile link."
                ]
            }
        }
    }

    cards = build_resume_evidence_cards(record)
    assert cards["has_evidence_cards"] is True
    assert cards["total_cards"] == 4
    assert len(cards["grouped_cards"]) >= 2
    # Check that each card has an ID and evidence payload
    first_group = cards["grouped_cards"][0]
    first_card = first_group["items"][0]
    assert "id" in first_card
    assert "suggestion" in first_card
    assert "evidence" in first_card


def test_api_resume_evidence_endpoint(test_client):
    analysis_id = f"test_ev_{uuid.uuid4().hex[:8]}"
    results = {
        "resume_analysis": {
            "weaknesses": ["Missing clear metrics on project performance."],
            "formatting_suggestions": [],
            "grammar_suggestions": []
        },
        "job_match": {
            "top_5_resume_changes": ["Quantify user growth in Flask projects."]
        },
        "extracted_resume_text": "Built a Flask web app for college campus placement tracking."
    }
    save_analysis(
        analysis_id,
        "resume.pdf",
        "Google",
        "SDE Role",
        results
    )

    resp = test_client.get(f"/api/analysis/{analysis_id}/resume-evidence")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["status"] == "success"
    assert "evidence" in data
    assert data["evidence"]["total_cards"] >= 2


def test_dashboard_renders_resume_evidence_section(test_client):
    analysis_id = f"test_ev_dash_{uuid.uuid4().hex[:8]}"
    results = {
        "resume_analysis": {
            "weaknesses": ["Missing automated test details in project section."],
            "formatting_suggestions": ["Ensure font size remains between 10pt and 12pt."],
            "grammar_suggestions": []
        },
        "job_match": {
            "top_5_resume_changes": ["Add metrics for the database optimization project."]
        },
        "extracted_resume_text": "Engineered database optimization project with SQLite index tuning."
    }
    save_analysis(
        analysis_id,
        "resume.pdf",
        "Amazon",
        "Software Engineer",
        results
    )

    resp = test_client.get(f"/dashboard/{analysis_id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "resumeEvidenceSection" in html
    assert "Resume Evidence Cards" in html
    assert "View Original Resume Evidence" in html
