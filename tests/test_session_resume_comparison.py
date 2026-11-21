"""
Comprehensive Automated Tests for In-Session Resume Revision Comparison (#535).
================================================================================
Acceptance Criteria:
1. Improvements and regressions are clearly marked.
2. Identical files show a "no changes found" message.
3. Tests cover the comparison logic (score, detected skills, missing skills, sections).
4. Both versions are kept in memory for the session only (zero database writes).
"""

import json
import tempfile
from pathlib import Path
import pytest

import config
from app import app
from utils.database import init_db, get_db_connection
from utils.session_resume_comparator import (
    compare_resume_versions,
    extract_detected_skills,
    extract_resume_sections,
    calculate_resume_readiness_score,
    determine_missing_skills,
    store_session_comparison,
    get_session_comparison,
    clear_session_comparison,
    _SESSION_COMPARISON_CACHE,
)


@pytest.fixture
def client():
    """Provides a Flask test client with an isolated SQLite database."""
    _SESSION_COMPARISON_CACHE.clear()
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_session_compare.db"
        config.DATABASE_PATH = test_db
        config.UPLOAD_FOLDER = Path(tmpdir) / "uploads"
        config.REPORT_FOLDER = Path(tmpdir) / "reports"
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        config.REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
        init_db()

        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client
    _SESSION_COMPARISON_CACHE.clear()


# ==============================================================================
# 1. Core Comparison Logic: Identical Files & "No changes found"
# ==============================================================================

def test_identical_resume_shows_no_changes_found():
    """
    Acceptance criterion: Identical files show a 'no changes found' message.
    Score difference must be 0, is_identical must be True, and no fake improvements.
    """
    resume_text = (
        "John Doe\nEmail: john@example.com | Phone: 555-123-4567\n"
        "Education: B.Tech Computer Science, GPA: 3.8/4.0\n"
        "Skills: Python, Django, REST APIs, PostgreSQL, Git, Linux\n"
        "Projects: Built an e-commerce platform with automated payment integration.\n"
        "Experience: Software Engineer Intern at Tech Corp.\n"
    )

    result = compare_resume_versions(
        text_v1=resume_text,
        text_v2=resume_text,
        filename_v1="Resume_v1.pdf",
        filename_v2="Resume_v1_copy.pdf",
        target_role="Backend Developer"
    )

    assert result["success"] is True
    assert result["is_identical"] is True
    assert result["score_delta"] == 0
    assert result["score_v1"] == result["score_v2"]
    assert result["overall_status"] == "no_changes"
    assert "no changes found" in result["message"].lower()
    assert "no changes found" in result["summary"].lower()
    assert result["skills_added"] == []
    assert result["skills_removed"] == []
    assert result["sections_added"] == []
    assert result["sections_removed"] == []
    assert result["improvements"] == []
    assert result["regressions"] == []


# ==============================================================================
# 2. Clearly Marked Improvements
# ==============================================================================

def test_resume_improvements_are_clearly_marked():
    """
    Acceptance criterion: Improvements are clearly marked.
    V2 adds high-value skills (Docker, AWS, Redis), adds a Certifications section,
    and resolves missing competencies.
    """
    v1_text = (
        "Alice Smith\nEmail: alice@example.com\n"
        "Education: Bachelor of Science in Computer Science\n"
        "Skills: Python, JavaScript, HTML, CSS\n"
        "Projects: Developed a portfolio website.\n"
    )

    v2_text = (
        "Alice Smith\nEmail: alice@example.com | Phone: 555-987-6543\n"
        "Education: Bachelor of Science in Computer Science, GPA: 3.9\n"
        "Skills: Python, JavaScript, HTML, CSS, Docker, AWS, Redis, SQL, PostgreSQL, REST APIs, Git, Linux\n"
        "Experience: Software Engineering Intern at CloudWorks. Built high-throughput microservices.\n"
        "Projects: Architected a distributed task queue handling 50k requests/sec.\n"
        "Certifications: AWS Certified Developer, LeetCode 500+ Solved\n"
    )

    result = compare_resume_versions(
        text_v1=v1_text,
        text_v2=v2_text,
        filename_v1="Alice_v1.pdf",
        filename_v2="Alice_v2.pdf",
        target_role="Backend Developer"
    )

    assert result["success"] is True
    assert result["is_identical"] is False
    assert result["overall_status"] == "improvement"
    assert result["score_delta"] > 0
    assert result["score_v2"] > result["score_v1"]

    # Newly added skills are highlighted
    assert "Docker" in result["skills_added"]
    assert "AWS" in result["skills_added"]
    assert "PostgreSQL" in result["skills_added"]

    # Newly added sections are highlighted
    assert "Work Experience / Internships" in result["sections_added"]
    assert "Certifications & Achievements" in result["sections_added"]

    # Resolved missing skills are highlighted
    assert len(result["missing_skills_resolved"]) > 0

    # Human-readable improvements list
    assert len(result["improvements"]) >= 2
    assert any("ATS Readiness Score increased" in imp for imp in result["improvements"])
    assert any("Added" in imp and "proficiencies" in imp for imp in result["improvements"])


# ==============================================================================
# 3. Clearly Marked Regressions
# ==============================================================================

def test_resume_regressions_are_clearly_marked():
    """
    Acceptance criterion: Regressions are clearly marked.
    V2 omits previous technical skills and drops the Experience and Projects sections.
    """
    v1_text = (
        "Bob Taylor\nEmail: bob@example.com | Phone: 555-333-2222\n"
        "Education: B.Tech Computer Engineering\n"
        "Skills: Python, Java, Docker, Kubernetes, SQL, PostgreSQL, Git, Linux, REST APIs\n"
        "Experience: Backend Developer Intern at Enterprise Inc. Optimized query latency by 40%.\n"
        "Projects: Built scalable microservices cluster with automated CI/CD.\n"
    )

    v2_text = (
        "Bob Taylor\n"
        "Education: B.Tech Computer Engineering\n"
        "Skills: Python\n"
    )

    result = compare_resume_versions(
        text_v1=v1_text,
        text_v2=v2_text,
        filename_v1="Bob_full.pdf",
        filename_v2="Bob_stripped.pdf",
        target_role="Software Engineer"
    )

    assert result["success"] is True
    assert result["is_identical"] is False
    assert result["overall_status"] == "regression"
    assert result["score_delta"] < 0
    assert result["score_v2"] < result["score_v1"]

    # Removed skills are marked as regression
    assert "Java" in result["skills_removed"]
    assert "Docker" in result["skills_removed"]
    assert "Kubernetes" in result["skills_removed"]

    # Removed sections are marked as regression
    assert "Work Experience / Internships" in result["sections_removed"]
    assert "Projects" in result["sections_removed"]

    # Human-readable regressions list
    assert len(result["regressions"]) >= 2
    assert any("ATS Readiness Score decreased" in reg for reg in result["regressions"])
    assert any("Removed" in reg or "Omitted" in reg for reg in result["regressions"])


# ==============================================================================
# 4. In-Memory Session Storage: Zero Database Writes
# ==============================================================================

def test_both_versions_kept_in_memory_only(client):
    """
    Proposed work: Keep both versions in memory for the session only.
    Verifies that session comparison creates ZERO records in the SQLite database.
    """
    conn = get_db_connection()
    count_before = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    conn.close()

    v1_text = "Skills: Python, SQL. Education: B.Tech."
    v2_text = "Skills: Python, SQL, Docker, AWS. Education: B.Tech."

    # Perform session comparison via API
    resp = client.post(
        "/api/resume/session-compare",
        data=json.dumps({
            "text_v1": v1_text,
            "text_v2": v2_text,
            "filename_v1": "v1.pdf",
            "filename_v2": "v2.pdf"
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["comparison"]["score_delta"] >= 0

    # Ensure database was NOT touched
    conn = get_db_connection()
    count_after = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    conn.close()

    assert count_before == count_after, "Database count changed! Session comparison must be in-memory only."

    # Test in-memory cache lifecycle
    sess_key = "test_memory_session_123"
    comp_obj = {"is_identical": False, "score_delta": 5}
    store_session_comparison(sess_key, comp_obj)
    assert get_session_comparison(sess_key) == comp_obj
    clear_session_comparison(sess_key)
    assert get_session_comparison(sess_key) is None


# ==============================================================================
# 5. REST API & Web Route Integration Tests
# ==============================================================================

def test_api_session_resume_compare_get_empty_and_populated(client):
    """GET /api/resume/session-compare retrieves stored comparison without re-upload."""
    # Initially empty
    resp_empty = client.get("/api/resume/session-compare")
    assert resp_empty.status_code == 200
    assert resp_empty.get_json()["has_comparison"] is False

    # Perform comparison
    client.post(
        "/api/resume/session-compare",
        data=json.dumps({
            "text_v1": "Skills: Python, Flask.",
            "text_v2": "Skills: Python, Flask, FastAPI, Docker."
        }),
        content_type="application/json"
    )

    # Now populated
    resp_pop = client.get("/api/resume/session-compare")
    assert resp_pop.status_code == 200
    data = resp_pop.get_json()
    assert data["has_comparison"] is True
    assert "FastAPI" in data["comparison"]["skills_added"]

    # Reset
    resp_reset = client.post("/api/resume/session-compare/reset")
    assert resp_reset.status_code == 200
    assert resp_reset.get_json()["cleared"] is True


def test_api_session_resume_compare_validation_error(client):
    """POST /api/resume/session-compare returns 400 when texts/files are missing."""
    resp = client.post(
        "/api/resume/session-compare",
        data=json.dumps({"text_v1": ""}),
        content_type="application/json"
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "required" in data["error"].lower()


def test_web_session_resume_compare_get_and_post_form(client):
    """GET and POST /resume/session-compare web page rendering."""
    # GET renders page
    res_get = client.get("/resume/session-compare")
    assert res_get.status_code == 200
    html_get = res_get.get_data(as_text=True)
    assert "Resume Revision Comparison" in html_get
    assert "btnCompareSessionResumes" in html_get

    # POST with identical text shows "No changes found"
    res_post_identical = client.post(
        "/resume/session-compare",
        data={
            "text_v1": "Skills: Python, SQL. Education: B.Tech.",
            "text_v2": "Skills: Python, SQL. Education: B.Tech.",
        }
    )
    assert res_post_identical.status_code == 200
    html_identical = res_post_identical.get_data(as_text=True)
    assert "identicalFilesAlert" in html_identical
    assert "No changes found" in html_identical

    # POST with improved text shows side-by-side results
    res_post_improved = client.post(
        "/resume/session-compare",
        data={
            "text_v1": "Skills: Python. Education: B.Tech.",
            "text_v2": "Skills: Python, Docker, AWS, PostgreSQL. Education: B.Tech. Experience: Intern.",
        }
    )
    assert res_post_improved.status_code == 200
    html_improved = res_post_improved.get_data(as_text=True)
    assert "scoreComparisonRow" in html_improved
    assert "improvementsContainer" in html_improved
    assert "addedSkillsBadges" in html_improved
    assert "sectionsComparisonCard" in html_improved


def test_dashboard_renders_session_revision_action_buttons(client):
    """GET /dashboard/<analysis_id> includes session revision comparison links and pre-seeds session."""
    from utils.database import save_analysis
    save_analysis(
        analysis_id="test-session-compare-dash-01",
        resume_filename="candidate.pdf",
        company_name="Amazon",
        job_description="Software Development Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 75, "skills": ["Python", "Java"]},
            "job_match": {"matched_skills": ["Python"], "missing_skills": ["Docker"]}
        }
    )

    resp = client.get("/dashboard/test-session-compare-dash-01")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Links to test revision in-session
    assert "btnNavSessionCompare" in html
    assert "btnTestNewRevisionInSession" in html
    assert "/resume/session-compare" in html
