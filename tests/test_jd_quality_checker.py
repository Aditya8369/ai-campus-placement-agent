"""
Unit tests for Job description quality checker (#602)
"""

import pytest
from utils.jd_quality_checker_service import evaluate_job_description_quality


def test_empty_job_description_quality():
    report = evaluate_job_description_quality("")
    assert report["quality_score"] == 0
    assert report["quality_rating"] == "Empty"
    assert report["allows_proceed"] is True
    assert len(report["missing_sections"]) == 3
    assert len(report["suggested_examples"]) > 0


def test_short_title_only_job_description():
    short_jd = "Senior Software Engineer"
    report = evaluate_job_description_quality(short_jd)
    assert report["is_short"] is True
    assert report["quality_rating"] == "Weak / Incomplete"
    assert report["allows_proceed"] is True
    assert report["warning_message"] is not None
    assert "brief" in report["warning_message"].lower() or "title" in report["warning_message"].lower()


def test_comprehensive_job_description():
    full_jd = """
    We are looking for a Software Development Engineer.
    Responsibilities:
    - You will develop, design, and maintain highly scalable backend services.
    - Collaborate with product teams and participate in code reviews.
    Qualifications:
    - Bachelor's or Master's degree in Computer Science or IT.
    - Strong problem solving skills and proficiency with data structures and algorithms.
    Skills:
    - Hands-on experience with Python, Flask, SQL, Docker, and Git.
    """
    report = evaluate_job_description_quality(full_jd)
    assert report["quality_score"] >= 75
    assert report["quality_rating"] == "Strong"
    assert report["detected_sections"]["skills"] is True
    assert report["detected_sections"]["responsibilities"] is True
    assert report["detected_sections"]["qualifications"] is True
    assert report["warning_message"] is None
    assert report["allows_proceed"] is True


def test_api_check_job_description_quality(client):
    resp = client.post(
        "/api/job-description/check-quality",
        json={"job_description": "Junior Developer with Python and SQL experience."}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "report" in data
    assert "quality_score" in data["report"]
    assert data["report"]["allows_proceed"] is True
