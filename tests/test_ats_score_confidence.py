"""
Tests for ATS Score Confidence Indicator (#598).
=================================================
Validates:
1. calculate_ats_score_confidence calculation for high, medium, and low scenarios.
2. Missing sections, text length, and layout warnings correctly lower confidence.
3. Plain-English diagnostic explanations and remedies are provided.
4. API endpoint /api/analysis/<analysis_id>/ats-confidence returns accurate data.
5. Dashboard correctly renders confidence badges and notice banners.
"""

import json
import uuid
import pytest
from app import create_app
from utils.database import init_db, save_analysis, get_analysis
from utils.ats_confidence_service import calculate_ats_score_confidence


@pytest.fixture
def test_client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client


def test_high_confidence_calculation():
    """Complete resume text with standard headers and clean formatting gets High confidence."""
    resume_text = (
        "John Doe\nEmail: john@example.com | Phone: 1234567890 | github.com/johndoe\n"
        "Education:\nB.Tech in Computer Science and Engineering, 8.8 CGPA, Graduating 2025.\n"
        "Technical Skills:\nPython, Flask, JavaScript, SQL, Git, Docker, REST APIs, Linux.\n"
        "Projects:\n"
        "AI Campus Placement Agent: Developed full-stack placement portal with automated evaluation.\n"
        "Cloud Data Pipeline: Automated daily ETL ingestion using Python and SQLite.\n"
        "Experience & Internships:\n"
        "Software Engineering Intern at Acme Corp: Built microservices handling high traffic.\n"
    ) * 2

    res = calculate_ats_score_confidence(resume_text, format_compat=None)
    assert res["confidence_level"] == "High"
    assert res["confidence_score"] >= 80
    assert not res["is_low_confidence"]
    assert "High confidence" in res["plain_explanation"]
    assert len(res["factors"]) > 0
    # Core sections detected
    factors_names = [f["factor"] for f in res["factors"]]
    assert "All Core Sections Detected" in factors_names


def test_medium_confidence_with_layout_warnings():
    """Complete resume with multi-column or table formatting warnings gets Medium confidence."""
    resume_text = (
        "Jane Doe | jane@test.com\n"
        "Education: Bachelor of Science, GPA 3.9.\n"
        "Skills: C++, Java, React, SQL.\n"
        "Projects: Portfolio site and database manager.\n"
        "Work Experience: Intern at TechLabs.\n"
    ) * 3

    format_compat = {
        "checks": [
            {"id": "multi_column", "status": "warn", "name": "Single Column Layout"},
            {"id": "tables", "status": "warn", "name": "Tables and Grids"},
            {"id": "images", "status": "pass", "name": "Embedded Images"}
        ]
    }

    res = calculate_ats_score_confidence(resume_text, format_compat=format_compat)
    assert res["confidence_level"] in ("Medium", "Low")
    assert res["confidence_score"] < 80
    factor_names = [f["factor"] for f in res["factors"]]
    assert "Multi-Column Layout Detected" in factor_names
    assert "Table Grids Detected" in factor_names


def test_low_confidence_on_sparse_text():
    """Extremely sparse or missing core sections should result in Low confidence and warnings."""
    sparse_text = "I am a developer looking for a job."

    res = calculate_ats_score_confidence(sparse_text)
    assert res["confidence_level"] == "Low"
    assert res["is_low_confidence"] is True
    assert res["confidence_score"] < 55
    assert "Low confidence" in res["plain_explanation"]
    assert len(res["recommendations"]) > 0


def test_api_ats_confidence_endpoint(test_client):
    """GET /api/analysis/<analysis_id>/ats-confidence returns 200 and confidence payload."""
    analysis_id = f"test_conf_analysis_{uuid.uuid4().hex[:8]}"
    analysis_record = {
        "analysis_id": analysis_id,
        "resume_filename": "resume.pdf",
        "company_name": "Tech Corp",
        "job_description": "Software engineer proficient in Python and SQL.",
        "results": {
            "resume_analysis": {
                "ats_score": 75,
                "skills": ["Python", "SQL", "Flask"],
                "summary": "Junior engineer"
            },
            "job_match": {
                "match_percentage": 80
            },
            "extracted_resume_text": (
                "Alice Smith\nEmail: alice@test.com\n"
                "Education: B.Tech in IT\n"
                "Skills: Python, SQL, Git, Linux\n"
                "Projects: Placement Tracker web application\n"
                "Experience: Junior developer intern"
            ) * 4
        }
    }
    save_analysis(
        analysis_id,
        "resume.pdf",
        "Tech Corp",
        "Software engineer proficient in Python and SQL.",
        analysis_record["results"]
    )

    resp = test_client.get(f"/api/analysis/{analysis_id}/ats-confidence")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["status"] == "success"
    assert "confidence" in data
    assert data["confidence"]["confidence_level"] in ("High", "Medium", "Low")
    assert "plain_explanation" in data["confidence"]
    assert "factors" in data["confidence"]


def test_dashboard_renders_confidence_indicator(test_client):
    """Dashboard HTML contains ATS confidence badge, factors, and review link."""
    analysis_id = f"test_conf_dash_{uuid.uuid4().hex[:8]}"
    results = {
        "resume_analysis": {
            "ats_score": 60,
            "skills": ["Python"],
            "summary": "Short resume"
        },
        "job_match": {
            "match_percentage": 50
        },
        "extracted_resume_text": "Short minimal text with no education and no contact."
    }
    save_analysis(
        analysis_id,
        "sample.pdf",
        "General",
        "Junior Developer",
        results
    )

    resp = test_client.get(f"/dashboard/{analysis_id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "atsConfidenceBadge" in html
    assert "atsConfidenceCard" in html
    assert "ATS Score Confidence:" in html
    assert "/resume/review" in html
