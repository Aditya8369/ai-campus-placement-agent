"""
Unit and integration tests for Resume Bullet Point Rewriter & Optimization (#429).

Verifies:
1. Candidate bullet extraction from experience and projects sections, filtering headers/dates.
2. Weakness scoring based on 3 criteria: length, missing action verbs, and missing metrics.
3. Selection of up to 5 weakest bullets ranked by weakness score.
4. Suggestions strictly use placeholders ([X%], [number]+, [X ms]) and NEVER invent metrics.
5. Sanitizer prevents any unbracketed invented numbers from leaking into rewrites.
6. Empty state handling when resumes contain no bullet points in experience or projects.
7. Mocked Gemini client integration, response parsing, and error fallback.
8. Dashboard view rendering of side-by-side cards, copy button with data-copy-text, and empty notice.
9. Dedicated JSON API endpoint /api/resume/bullet-rewrites/<analysis_id>.
"""

import html
import tempfile
from pathlib import Path
import pytest
from app import app
import config
from utils.database import init_db, save_analysis
from utils.bullet_rewriter import (
    extract_bullet_candidates,
    evaluate_bullet_weakness,
    select_weakest_bullets,
    sanitize_metrics_with_placeholders,
    sanitize_tools_with_placeholders,
    format_placeholders_for_display,
    extract_technology_from_bullet,
    is_tech_in_original,
    _generate_rule_based_rewrite,
    rewrite_weak_bullets,
    get_bullet_rewrites_for_analysis,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with temporary sqlite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_bullets.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Extraction from Experience & Projects
# ==============================================================================

def test_extract_bullet_candidates_from_experience_and_projects():
    """Verify bullet points are extracted strictly from experience and project sections."""
    sample_resume = """
    John Doe
    Email: john@example.com | Phone: 9876543210

    Technical Skills
    Python, Java, React, SQL, Docker

    Work Experience
    Software Engineer Intern - Acme Corp (May 2023 - Aug 2023)
    - Worked on python backend for user authentication.
    - Responsible for writing unit tests.
    - Architected scalable microservice in Go.

    Projects
    Campus Placement Portal (Jan 2023 - Apr 2023)
    • Helped with UI design in React.
    • Developed full stack web app using Django.
    • May 2023 - Present
    • Tech: React, Node.js, MongoDB

    Education
    B.Tech Computer Science - ABC University (2020 - 2024)
    """

    candidates = extract_bullet_candidates(sample_resume)
    extracted_texts = [c["original_bullet"] for c in candidates]

    # Should include bullets from experience and projects
    assert "Worked on python backend for user authentication." in extracted_texts
    assert "Responsible for writing unit tests." in extracted_texts
    assert "Architected scalable microservice in Go." in extracted_texts
    assert "Helped with UI design in React." in extracted_texts
    assert "Developed full stack web app using Django." in extracted_texts

    # Should filter out pure date lines and tech stack listings
    assert "May 2023 - Present" not in extracted_texts
    assert "Tech: React, Node.js, MongoDB" not in extracted_texts
    # Should not include education or skills lines
    assert "Python, Java, React, SQL, Docker" not in extracted_texts


# ==============================================================================
# 2. Weakness Scoring (Length, Action Verbs, Metrics)
# ==============================================================================

def test_evaluate_bullet_weakness_length_verb_metrics():
    """Verify weakness penalties for length, missing verbs, and missing metrics."""
    # 1. Very weak bullet: short, passive starter, no metrics
    weak_bullet = "Worked on frontend"
    weak_res = evaluate_bullet_weakness(weak_bullet)
    assert weak_res["weakness_score"] >= 80
    assert weak_res["has_weak_verb"] is True
    assert weak_res["has_no_metrics"] is True
    assert weak_res["length_issue"] is True
    assert any("passive" in r.lower() or "worked on" in r.lower() for r in weak_res["weakness_reasons"])

    # 2. Strong bullet: strong power verb, ideal length, quantified metrics
    strong_bullet = "Architected distributed REST microservices in FastAPI and Docker, reducing query latency by 45% and serving 10,000+ daily users."
    strong_res = evaluate_bullet_weakness(strong_bullet)
    assert strong_res["weakness_score"] == 0
    assert strong_res["has_weak_verb"] is False
    assert strong_res["has_no_action_verb"] is False
    assert strong_res["has_no_metrics"] is False
    assert strong_res["length_issue"] is False


def test_evaluate_bullet_weakness_ignores_calendar_years_as_metrics():
    """Verify 4-digit years like 2022 or 2023 are not mistakenly counted as performance metrics."""
    bullet_with_year = "Responsible for maintaining internal databases during 2023."
    res = evaluate_bullet_weakness(bullet_with_year)
    # 2023 is a calendar year, so has_no_metrics should be True
    assert res["has_no_metrics"] is True
    assert any("missing quantifiable metrics" in r.lower() for r in res["weakness_reasons"])


# ==============================================================================
# 3. Selection of Up to 5 Weakest Bullets
# ==============================================================================

def test_select_weakest_bullets_limit_and_ordering():
    """Verify candidate ranking selects top 5 weakest bullets in descending order of weakness."""
    candidates = [
        {"original_bullet": "Architected cloud pipelines cutting cost by 30% and supporting 50k users.", "section": "experience"},  # strong (score ~0)
        {"original_bullet": "Worked on a website", "section": "projects"},  # very weak (score ~100)
        {"original_bullet": "Responsible for testing", "section": "experience"},  # very weak (score ~100)
        {"original_bullet": "Helped with bugs", "section": "experience"},  # very weak (score ~100)
        {"original_bullet": "Assisted team in coding", "section": "projects"},  # very weak (score ~100)
        {"original_bullet": "Made an API in Node", "section": "projects"},  # weak (score ~80)
        {"original_bullet": "Engineered automated test suite achieving 92% coverage across 500 tests.", "section": "experience"},  # strong
    ]

    selected = select_weakest_bullets(candidates, limit=5)

    assert len(selected) == 5
    # The two strong bullets should NOT be in the top 5 weakest
    selected_texts = [s["original_bullet"] for s in selected]
    assert "Architected cloud pipelines cutting cost by 30% and supporting 50k users." not in selected_texts
    assert "Engineered automated test suite achieving 92% coverage across 500 tests." not in selected_texts
    # Weak bullets must be included
    assert "Worked on a website" in selected_texts
    assert "Responsible for testing" in selected_texts


def test_select_weakest_bullets_fewer_than_five():
    """Verify that when fewer than 5 bullets exist, all available bullets are returned."""
    candidates = [
        {"original_bullet": "Worked on database schema design.", "section": "projects"},
        {"original_bullet": "Responsible for bug fixes in Django app.", "section": "experience"}
    ]
    selected = select_weakest_bullets(candidates, limit=5)
    assert len(selected) == 2


# ==============================================================================
# 4. Strict Placeholders & Zero Invented Metrics
# ==============================================================================

def test_rule_based_rewrite_uses_placeholders_and_never_invents_metrics():
    """Verify that fallback rewrites use strict placeholders like [X%] and contain no raw invented metrics."""
    original = "Worked on python api for user auth"
    rewrite = _generate_rule_based_rewrite(original, section="experience", target_role="Software Engineer")

    suggested = rewrite["suggested_rewrite"]
    # Must start with a power action verb
    assert rewrite["action_verb"] in ["Architected", "Engineered", "Optimized", "Scaled", "Spearheaded", "Implemented"]
    assert suggested.startswith(rewrite["action_verb"])

    # Must contain placeholders
    assert "[X%]" in suggested or "[number]+" in suggested or "[Y hours]" in suggested or "[X ms]" in suggested

    # Must NOT contain hardcoded invented numbers like 38%, 15000, $50000
    assert "38%" not in suggested
    assert "15,000" not in suggested
    assert "$50" not in suggested


def test_sanitize_metrics_with_placeholders_replaces_invented_numbers():
    """Verify sanitizer strips newly invented percentages/numbers not present in the original bullet."""
    original = "Worked on react components for dashboard"
    # Simulated hallucinated AI output with invented numbers
    hallucinated = "Engineered modular React components, improving load speed by 45% and serving 12,000 daily users."

    sanitized = sanitize_metrics_with_placeholders(hallucinated, original)

    # 45% should become [X%]
    assert "45%" not in sanitized
    assert "[X%]" in sanitized

    # 12,000 should become [number]
    assert "12,000" not in sanitized
    assert "[number]" in sanitized


def test_sanitize_metrics_with_placeholders_preserves_candidate_original_metrics():
    """Verify that metrics already present in the candidate's original bullet are preserved."""
    original = "Led a student team of 4 developers building an app used by 200 classmates."
    ai_rewrite = "Orchestrated a student engineering team of 4 developers, scaling application adoption to 200 classmates and reducing latency by [X%]."

    sanitized = sanitize_metrics_with_placeholders(ai_rewrite, original)

    # Original '4' and '200' were in original, so they should be preserved
    assert "4 developers" in sanitized
    assert "200 classmates" in sanitized
    assert "[X%]" in sanitized


# ==============================================================================
# 5. Empty State Handling
# ==============================================================================

def test_get_bullet_rewrites_for_analysis_empty_state_when_no_bullets():
    """Verify helpful empty state is returned when resume has no experience or project bullets."""
    empty_resume_record = {
        "analysis_id": "aid_empty_resume",
        "company_name": "Google",
        "resume_text": "Jane Doe\nEmail: jane@test.com\n\nTechnical Skills\nJava, C++, Python\n\nEducation\nABC University"
    }

    result = get_bullet_rewrites_for_analysis(empty_resume_record)

    assert result["has_bullets"] is False
    assert len(result["bullets"]) == 0
    assert result["total_detected"] == 0
    assert "No bullet points detected" in result["empty_message"]


# ==============================================================================
# 6. Mock Gemini Model Responses & Fallback
# ==============================================================================

def test_mock_gemini_client_happy_path(mock_gemini_client):
    """Verify mock Gemini AI returns structured rewrites with action verb, task, and result."""
    mock_payload = {
        "rewrites": [
            {
                "original_bullet": "Worked on python api for user auth",
                "action_verb": "Architected",
                "task": "secure Python authentication endpoints with JWT verification",
                "measurable_result": "reducing authentication latency by [X%] and supporting [number]+ daily active users",
                "suggested_rewrite": "Architected secure Python authentication endpoints with JWT verification, reducing authentication latency by [X%] and supporting [number]+ daily active users."
            }
        ]
    }
    mock_gemini_client(payload=mock_payload)

    weak_bullets = [
        {"original_bullet": "Worked on python api for user auth", "section": "experience", "weakness_reasons": ["Starts with weak phrasing"]}
    ]

    res = rewrite_weak_bullets(weak_bullets, company_name="Google", target_role="Software Engineer")

    assert len(res) == 1
    assert res[0]["action_verb"] == "Architected"
    assert "reducing authentication latency by [X%]" in res[0]["suggested_rewrite"]
    assert '<span class="badge bg-primary-subtle' in res[0]["suggested_rewrite_formatted"]


def test_mock_gemini_client_sanitizes_invented_metrics(mock_gemini_client):
    """Verify that if Gemini inadvertently invents a metric, it is automatically sanitized to placeholders."""
    mock_payload = {
        "rewrites": [
            {
                "original_bullet": "Helped with UI design in React",
                "action_verb": "Implemented",
                "task": "modular React interface components",
                "measurable_result": "reducing page load time by 38% and supporting 15,000 users",
                "suggested_rewrite": "Implemented modular React interface components, reducing page load time by 38% and supporting 15,000 users."
            }
        ]
    }
    mock_gemini_client(payload=mock_payload)

    weak_bullets = [
        {"original_bullet": "Helped with UI design in React", "section": "projects"}
    ]

    res = rewrite_weak_bullets(weak_bullets)

    assert len(res) == 1
    # 38% and 15,000 should be sanitized
    assert "38%" not in res[0]["suggested_rewrite"]
    assert "15,000" not in res[0]["suggested_rewrite"]
    assert "[X%]" in res[0]["suggested_rewrite"]
    assert "[number]" in res[0]["suggested_rewrite"]


def test_mock_gemini_client_error_falls_back_to_rule_based(mock_gemini_client):
    """Verify that Gemini API errors trigger fallback to rule-based optimizer without raising."""
    mock_gemini_client(side_effect=Exception("API Quota Exceeded"))

    weak_bullets = [
        {"original_bullet": "Responsible for writing unit tests.", "section": "experience"}
    ]

    res = rewrite_weak_bullets(weak_bullets)

    assert len(res) == 1
    assert res[0]["action_verb"] in ["Automated", "Engineered", "Streamlined", "Standardized"]
    assert "[X%]" in res[0]["suggested_rewrite"] or "[number]" in res[0]["suggested_rewrite"]


# ==============================================================================
# 7. Dashboard View & Integration
# ==============================================================================

def test_dashboard_renders_bullet_point_rewriter_section(test_app_client):
    """Verify dashboard route serves the bullet rewriter card, side-by-side comparisons, and copy button."""
    aid = "aid_bullet_test_429"
    sample_resume = """
    Alex Chen
    Email: alex@example.com

    Work Experience
    Software Intern - TechCorp
    - Worked on python backend for user auth.
    - Responsible for testing features.

    Projects
    Student Tracker
    - Helped with database design.
    """
    sample_results = {
        "resume_analysis": {"ats_score": 82},
        "job_match": {"match_percentage": 75},
        "extracted_resume_text": sample_resume
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="alex_resume.pdf",
        company_name="Amazon",
        job_description="Software Engineer looking for Python, APIs, and databases.",
        results_dict=sample_results,
        student_id="default_student"
    )

    response = test_app_client.get(f"/dashboard/{aid}")
    assert response.status_code == 200
    html_content = response.data.decode("utf-8")

    # Section ID & Navigation
    assert 'id="bulletPointRewriterSection"' in html_content
    assert 'href="#bulletPointRewriterSection"' in html_content

    # Badge count and list
    assert 'id="badgeWeakestBulletsCount"' in html_content
    assert 'id="bulletRewritesList"' in html_content

    # Original weak bullet and Suggested Rewrite headers
    assert "Original Weak Bullet" in html_content
    assert "Suggested Rewrite (Action + Task + Result)" in html_content

    # Copy button with data-copy-text
    assert 'btn-copy-bullet-rewrite' in html_content
    assert 'data-copy-text=' in html_content


def test_dashboard_renders_empty_state_when_no_bullets(test_app_client):
    """Verify dashboard renders helpful empty state when resume has no bullet points in experience or projects."""
    aid = "aid_bullet_empty_429"
    sample_resume = """
    Jordan Smith
    Email: jordan@example.com
    Skills: Python, Java, SQL
    Education: BS Computer Science
    """
    sample_results = {
        "resume_analysis": {"ats_score": 60},
        "job_match": {"match_percentage": 50},
        "extracted_resume_text": sample_resume
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="jordan_resume.pdf",
        company_name="Microsoft",
        job_description="Software Engineer",
        results_dict=sample_results,
        student_id="default_student"
    )

    response = test_app_client.get(f"/dashboard/{aid}")
    assert response.status_code == 200
    html_content = response.data.decode("utf-8")

    assert 'id="bulletPointRewriterSection"' in html_content
    assert 'id="emptyBulletRewritesNotice"' in html_content
    assert "No Bullet Points Detected in Experience or Projects" in html_content
    assert "How to format your resume bullets for maximum impact" in html_content


# ==============================================================================
# 8. API Endpoint
# ==============================================================================

def test_api_resume_bullet_rewrites_endpoint(test_app_client):
    """Verify /api/resume/bullet-rewrites/<analysis_id> returns valid JSON payload."""
    aid = "aid_api_bullet_test"
    sample_resume = """
    Taylor Green
    Experience
    - Worked on payment gateway integration.
    """
    sample_results = {
        "resume_analysis": {"ats_score": 75},
        "extracted_resume_text": sample_resume
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="taylor.pdf",
        company_name="Stripe",
        job_description="Backend Engineer",
        results_dict=sample_results,
        student_id="default_student"
    )

    response = test_app_client.get(f"/api/resume/bullet-rewrites/{aid}")
    assert response.status_code == 200
    data = response.get_json()

    assert data["has_bullets"] is True
    assert len(data["bullets"]) >= 1
    first_b = data["bullets"][0]
    assert "original_bullet" in first_b
    assert "suggested_rewrite" in first_b
    assert "[X%]" in first_b["suggested_rewrite"] or "[number]" in first_b["suggested_rewrite"]


# ==============================================================================
# 9. XSS Prevention & Display Formatting
# ==============================================================================

def test_format_placeholders_for_display_xss_safety():
    """Verify that HTML characters are escaped safely and placeholders are wrapped in badges."""
    raw = '<script>alert("xss")</script> Engineered API, reducing latency by [X%] and supporting [number]+ users.'
    formatted = format_placeholders_for_display(raw)

    # HTML script tags must be escaped
    assert "<script>" not in formatted
    assert "&lt;script&gt;" in formatted

    # Placeholders should be formatted in badge spans
    assert '<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-1 py-0 rounded font-monospace small">[X%]</span>' in formatted
    assert '<span class="badge bg-primary-subtle text-primary border border-primary-subtle px-1 py-0 rounded font-monospace small">[number]</span>+ users.' in formatted


# ==============================================================================
# 10. Technology Extraction & Zero-Hallucination Tools (#429)
# ==============================================================================

def test_extract_technology_from_bullet_detects_tools():
    """Verify known technologies are extracted, or [add tool] placeholder is returned when absent."""
    # Bullet with explicit technologies
    bullet_with_tech = "Worked on FastAPI backend microservices with PostgreSQL database and Docker containers."
    detected = extract_technology_from_bullet(bullet_with_tech)
    assert "FastAPI" in detected
    assert "PostgreSQL" in detected
    assert "Docker" in detected

    # Bullet with NO technologies mentioned - must never invent tools
    bullet_no_tech = "Worked on user login and session management workflow."
    detected_none = extract_technology_from_bullet(bullet_no_tech)
    assert detected_none == "[add tool]"


def test_is_tech_in_original_validates_presence():
    """Verify tool grounding against candidate original text."""
    orig = "Responsible for building responsive interface in React and TypeScript."
    assert is_tech_in_original("React", orig) is True
    assert is_tech_in_original("TypeScript", orig) is True
    assert is_tech_in_original("[add tool]", orig) is True
    assert is_tech_in_original("Kubernetes", orig) is False
    assert is_tech_in_original("AWS", orig) is False


def test_rule_based_rewrite_technology_and_add_metric_placeholder():
    """Verify rule-based rewriter includes action verb, technology used, and [add metric] placeholders."""
    # Case 1: Bullet with no tools mentioned
    original_no_tool = "Worked on user authentication and session management."
    rewrite_no_tool = _generate_rule_based_rewrite(original_no_tool, section="experience", target_role="Software Engineer")

    assert rewrite_no_tool["technology_used"] == "[add tool]"
    assert "[add tool]" in rewrite_no_tool["suggested_rewrite"]
    assert "[add metric]" in rewrite_no_tool["suggested_rewrite"]
    assert "[add metric]" in rewrite_no_tool["measurable_result"]
    assert rewrite_no_tool["action_verb"] in ["Architected", "Engineered", "Optimized", "Scaled", "Spearheaded", "Implemented"]

    # Case 2: Bullet with tools mentioned (Python)
    original_with_tool = "Worked on Python script for data processing and analysis."
    rewrite_with_tool = _generate_rule_based_rewrite(original_with_tool, section="projects", target_role="Data Engineer")

    assert "Python" in rewrite_with_tool["technology_used"]
    assert "Python" in rewrite_with_tool["suggested_rewrite"]
    assert "[add metric]" in rewrite_with_tool["suggested_rewrite"]


def test_sanitize_tools_with_placeholders_replaces_hallucinated_technologies():
    """Verify sanitizer replaces newly hallucinated technologies not present in candidate's original bullet."""
    original = "Worked on user signup form and basic styling."
    hallucinated = "Engineered responsive signup workflow using Docker, AWS, and Kubernetes, reducing latency by [X%]."

    sanitized = sanitize_tools_with_placeholders(hallucinated, original)

    # Docker, AWS, Kubernetes were not in original - should be sanitized to [add tool]
    assert "Docker" not in sanitized
    assert "AWS" not in sanitized
    assert "Kubernetes" not in sanitized
    assert "[add tool]" in sanitized


def test_dashboard_renders_technology_badge_and_breakdown(test_app_client):
    """Verify dashboard renders Technology badge, key elements breakdown, and copy button."""
    aid = "aid_bullet_tech_test"
    sample_resume = """
    Jordan Lee
    Experience
    - Worked on Python backend API.
    - Helped with frontend interface.
    """
    sample_results = {
        "resume_analysis": {"ats_score": 78},
        "extracted_resume_text": sample_resume
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="jordan.pdf",
        company_name="Google",
        job_description="Full Stack Engineer",
        results_dict=sample_results,
        student_id="default_student"
    )

    response = test_app_client.get(f"/analysis/{aid}")
    assert response.status_code == 200
    html_content = response.get_data(as_text=True)

    # Technology header badge & Action Verb header badge
    assert "Technology:" in html_content
    assert "Action Verb:" in html_content

    # Key Elements breakdown pills
    assert "Verb:" in html_content
    assert "Tech:" in html_content

    # Copy button with data-copy-text
    assert "btn-copy-bullet-rewrite" in html_content
    assert "data-copy-text=" in html_content
