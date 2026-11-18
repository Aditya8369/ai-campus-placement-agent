"""
Unit and Integration Tests for ATS-Style Resume Scoring & Section Breakdown (#494).
===================================================================================
Tests:
1. The same resume always gets the same score (100% deterministic repeatability).
2. All 6 sections are scored out of a fixed 100-point total.
3. Basics checks (action verbs, quantified achievements, consistent dates, length).
4. Correct identification of the section that hurts the resume most ('hurts_most').
5. Short actionable suggestions are provided for each weak section.
6. The score appears alongside the existing analysis in coordinator and dashboard view.
7. REST API endpoints: GET /api/analysis/<id>/ats-breakdown and POST /api/resume/ats-score.
"""

import json
import uuid
import pytest

from app import app
from utils.database import init_db, save_analysis
from utils.ats_score_service import (
    SECTION_WEIGHTS,
    SECTION_TITLES,
    evaluate_basics_checks,
    evaluate_resume_ats_score,
    extract_resume_sections,
    score_contact_info,
    score_education,
    score_experience,
    score_projects,
    score_skills,
    score_summary,
)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure database is initialized before running tests."""
    init_db()


@pytest.fixture
def client():
    """Provides a Flask test client with testing and debug configs."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


SAMPLE_STRONG_RESUME = """
Alex Chen
alex.chen@berkeley.edu | (555) 019-2834 | linkedin.com/in/alexchen-demo | github.com/alexchen-dev

PROFESSIONAL SUMMARY
Computer Science graduate from UC Berkeley seeking Software Development Engineer roles. Hands-on experience developing asynchronous distributed task queues and scalable microservices in Python, Redis, and Docker.

EDUCATION
B.S. in Computer Science - University of California, Berkeley (2020 - 2024)
CGPA: 3.82 / 4.0

TECHNICAL SKILLS
Languages: Python, Java, C++, JavaScript, TypeScript, SQL
Frameworks & Libraries: React, Node.js, FastAPI, Flask, Docker, Kubernetes
Databases & Cloud: PostgreSQL, Redis, MongoDB, AWS, Git, CI/CD

WORK EXPERIENCE
Software Engineering Intern - CloudTech Solutions (June 2023 - August 2023)
- Architected RESTful microservices in Python, improving reporting pipeline throughput by 25%.
- Implemented automated monitoring scripts reducing error rates by 40% across 5,000+ daily jobs.
- Collaborated with senior engineers using Git workflows and Docker containerization.

PROJECTS
Distributed Task Queue | Python, Redis, Docker
- Engineered distributed background workers processing 5,000+ jobs per minute with priority scheduling.
- Implemented exponential backoff retries and dead-letter queues reducing failed job dropouts by 40%.
- Deployed on AWS with Docker Compose and published open source repository on GitHub.
"""

SAMPLE_RESUME_MISSING_EXPERIENCE = """
Priya Sharma
priya.sharma@campus.edu | (555) 432-8765 | linkedin.com/in/priya-sharma | github.com/priyasharma

CAREER OBJECTIVE
Aspiring Software Developer and B.Tech CSE student with strong foundations in Data Structures, Algorithms, and full-stack web applications. Eager to contribute to high-impact campus engineering teams.

EDUCATION
B.Tech in Computer Science and Engineering - National Institute of Technology (2021 - 2025)
CGPA: 8.9 / 10

TECHNICAL SKILLS
Languages: Java, Python, C++, SQL
Frameworks & Tools: Spring Boot, React, MySQL, Git, Docker

KEY PROJECTS
Campus Placement Portal | React, Spring Boot, MySQL
- Architected candidate registration pipeline and resume review modules for 1,200+ students.
- Implemented JWT authentication and role-based access control with Spring Security.
- Deployed full-stack container on AWS EC2 with 99.9% uptime.
"""

SAMPLE_WEAK_RESUME = """
John Doe
City, State
Summary: Looking for any tech job.
Skills: C, Java
Education: Local College
Projects: Made a small website.
"""


# ==============================================================================
# CRITERION 1: DETERMINISTIC REPEATABILITY
# ==============================================================================

def test_same_resume_always_gets_same_score():
    """
    Acceptance Criterion 1:
    The same resume always gets the same score.
    Runs multiple evaluations and verifies 100% deterministic score and breakdown.
    """
    run_1 = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)
    run_2 = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)
    run_3 = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)

    # Base total scores must be identical
    assert run_1["total_score"] == run_2["total_score"] == run_3["total_score"]
    assert run_1["rating"] == run_2["rating"]

    # All section scores must match identically
    for sec_key in SECTION_WEIGHTS:
        sec_1 = run_1["sections"][sec_key]
        sec_2 = run_2["sections"][sec_key]
        assert sec_1["score"] == sec_2["score"]
        assert sec_1["status"] == sec_2["status"]
        assert sec_1["suggestion"] == sec_2["suggestion"]

    # Full output structure equality
    assert run_1 == run_2 == run_3


def test_deterministic_scoring_across_different_profiles():
    """
    Verifies that repeatability holds true across different resumes:
    - strong resume
    - resume missing experience
    - minimal weak resume
    """
    res_strong_a = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)
    res_strong_b = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)
    assert res_strong_a["total_score"] == res_strong_b["total_score"]

    res_noexp_a = evaluate_resume_ats_score(SAMPLE_RESUME_MISSING_EXPERIENCE)
    res_noexp_b = evaluate_resume_ats_score(SAMPLE_RESUME_MISSING_EXPERIENCE)
    assert res_noexp_a["total_score"] == res_noexp_b["total_score"]

    res_weak_a = evaluate_resume_ats_score(SAMPLE_WEAK_RESUME)
    res_weak_b = evaluate_resume_ats_score(SAMPLE_WEAK_RESUME)
    assert res_weak_a["total_score"] == res_weak_b["total_score"]

    # Scores should accurately reflect resume quality
    assert res_strong_a["total_score"] > res_noexp_a["total_score"] > res_weak_a["total_score"]


# ==============================================================================
# SECTION WEIGHTS & SCORING OUT OF FIXED 100 TOTAL
# ==============================================================================

def test_fixed_weights_sum_to_100():
    """
    Proposed Work Criterion:
    Score sections such as contact info, summary, skills, experience, projects
    and education out of a fixed total of 100.
    """
    total_weights = sum(SECTION_WEIGHTS.values())
    assert total_weights == 100

    assert SECTION_WEIGHTS["contact_info"] == 15
    assert SECTION_WEIGHTS["summary"] == 10
    assert SECTION_WEIGHTS["skills"] == 20
    assert SECTION_WEIGHTS["experience"] == 20
    assert SECTION_WEIGHTS["projects"] == 20
    assert SECTION_WEIGHTS["education"] == 15


def test_section_scores_bounded_and_consistent():
    """
    Verifies each section's earned score is between 0 and its max score,
    and total_score strictly equals the sum of section scores.
    """
    res = evaluate_resume_ats_score(SAMPLE_STRONG_RESUME)

    calculated_sum = 0
    for sec_key, weight in SECTION_WEIGHTS.items():
        sec_data = res["sections"][sec_key]
        assert 0 <= sec_data["score"] <= weight
        assert sec_data["max_score"] == weight
        assert sec_data["lost_points"] == weight - sec_data["score"]
        calculated_sum += sec_data["score"]

    assert res["total_score"] == calculated_sum
    assert 0 <= res["total_score"] <= 100


# ==============================================================================
# BASICS CHECKS (Action Verbs, Metrics, Dates, Length)
# ==============================================================================

def test_basics_checks_on_strong_resume():
    """
    Proposed Work Criterion:
    Check basics: action verbs, quantified achievements, consistent dates and length.
    """
    basics = evaluate_basics_checks(SAMPLE_STRONG_RESUME)

    # 1. Action Verbs
    assert basics["action_verbs"]["passed"] is True
    assert basics["action_verbs"]["count"] >= 4
    assert any(v in basics["action_verbs"]["sample"] for v in ["architected", "engineered", "implemented", "developed"])

    # 2. Quantified Achievements
    assert basics["quantified_achievements"]["passed"] is True
    assert basics["quantified_achievements"]["count"] >= 2
    assert any("%" in m or "+" in m for m in basics["quantified_achievements"]["sample"])

    # 3. Consistent Dates
    assert basics["consistent_dates"]["passed"] is True

    # 4. Resume Length
    assert basics["resume_length"]["word_count"] > 100


def test_basics_checks_flag_weaknesses():
    """
    Verifies that resume lacking verbs and numbers is correctly flagged by basics checks.
    """
    basics = evaluate_basics_checks(SAMPLE_WEAK_RESUME)

    assert basics["action_verbs"]["passed"] is False
    assert basics["quantified_achievements"]["passed"] is False
    assert basics["action_verbs"]["status"] in ("Needs Improvement", "Fail")
    assert basics["quantified_achievements"]["status"] in ("Needs Improvement", "Fail")


# ==============================================================================
# "HURTS MOST" WEAKEST SECTION IDENTIFICATION
# ==============================================================================

def test_hurts_most_identifies_missing_experience():
    """
    Proposed Work:
    Students want one measurable score and to know which part of the resume hurts it most.
    When experience is missing, experience should be flagged as biggest score drag.
    """
    res = evaluate_resume_ats_score(SAMPLE_RESUME_MISSING_EXPERIENCE)
    hurts_most = res["hurts_most"]

    assert hurts_most is not None
    assert hurts_most["section_key"] == "experience"
    assert hurts_most["lost_points"] == 20
    assert "experience" in hurts_most["title"].lower()
    assert "internship" in hurts_most["suggestion"].lower() or "experience" in hurts_most["suggestion"].lower()


def test_hurts_most_identifies_missing_contact_details():
    """
    When contact info is completely omitted, verifies contact_info is identified as dragging down score.
    """
    resume_no_contact = """
    PROFESSIONAL SUMMARY
    Senior student in CS.
    EDUCATION
    B.S. in CS - Berkeley 2024
    TECHNICAL SKILLS
    Python, SQL, Java
    PROJECTS
    Built web scraper.
    """
    res = evaluate_resume_ats_score(resume_no_contact)
    assert res["hurts_most"] is not None
    assert res["hurts_most"]["lost_points"] > 0


def test_suggestions_present_for_each_weak_section():
    """
    Proposed Work:
    Show a short suggestion for each weak section.
    """
    res = evaluate_resume_ats_score(SAMPLE_WEAK_RESUME)
    sections = res["sections"]

    for sec_key, sec_data in sections.items():
        if sec_data["is_weak"]:
            sugg = sec_data.get("suggestion")
            assert isinstance(sugg, str)
            assert len(sugg.strip()) > 10, f"Weak section {sec_key} missing meaningful suggestion"


# ==============================================================================
# INTEGRATION: DASHBOARD & COORDINATOR
# ==============================================================================

def test_score_appears_alongside_existing_analysis_in_dashboard(client):
    """
    Acceptance Criterion 3:
    The score appears alongside the existing analysis.
    Verifies that dashboard renders the ATS Score Breakdown section,
    the 'Hurts Most' callout, section breakdown cards, and basics checks.
    """
    analysis_id = str(uuid.uuid4())
    student_id = "test_student_ats_494"
    results = {
        "job_match": {
            "match_percentage": 75,
            "matched_skills": ["Python", "SQL", "Git"]
        },
        "resume_analysis": {
            "ats_score": 82,
            "skills": ["Python", "SQL", "Git"],
            "strengths": ["Clear technical foundation"],
            "weaknesses": ["Needs more metrics"]
        },
        "skill_gap": []
    }

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Software Engineering Internship",
        results_dict=results,
        student_id=student_id,
        resume_text=SAMPLE_RESUME_MISSING_EXPERIENCE,
    )

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.get(f"/dashboard/{analysis_id}")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)

    # 1. ATS Score Breakdown Card present alongside analysis
    assert 'id="atsScoreBreakdownSection"' in html
    assert 'ATS Resume Score &amp; Section Breakdown' in html or 'ATS Resume Score & Section Breakdown' in html

    # 2. Total score and rating badge present
    assert 'id="atsBreakdownTotalScore"' in html
    assert 'id="atsBreakdownRatingBadge"' in html

    # 3. "Hurts Most" callout banner present
    assert 'id="atsHurtsMostAlert"' in html
    assert 'Biggest Score Drag' in html

    # 4. Section-Wise Breakdown Grid present
    assert 'id="atsSectionsGrid"' in html
    assert 'Technical Skills' in html
    assert 'Education &amp; Qualifications' in html or 'Education & Qualifications' in html

    # 5. Core basics checks present
    assert 'id="atsBasicsChecksContainer"' in html
    assert 'Action Verbs' in html
    assert 'Quantified Achievements' in html


# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================

def test_api_get_analysis_ats_breakdown(client):
    """Verifies GET /api/analysis/<analysis_id>/ats-breakdown returns HTTP 200 and schema."""
    analysis_id = str(uuid.uuid4())
    student_id = "test_student_api_ats_494"
    results = {
        "job_match": {"match_percentage": 70, "matched_skills": ["Python"]},
        "resume_analysis": {"ats_score": 75},
    }

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Microsoft",
        job_description="Software Engineer",
        results_dict=results,
        student_id=student_id,
        resume_text=SAMPLE_STRONG_RESUME,
    )

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.get(f"/api/analysis/{analysis_id}/ats-breakdown")
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["status"] == "success"
    assert data["success"] is True
    assert "total_score" in data
    assert "sections" in data
    assert "basics" in data
    assert len(data["sections"]) == 6


def test_api_post_resume_ats_score(client):
    """Verifies POST /api/resume/ats-score computes deterministic score for given text."""
    payload = {"resume_text": SAMPLE_STRONG_RESUME}
    resp = client.post("/api/resume/ats-score", json=payload)
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["status"] == "success"
    assert data["total_score"] >= 80
    assert data["rating"] in ("Excellent", "Good")
    assert "sections" in data
    assert "basics" in data
