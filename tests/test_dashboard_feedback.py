"""
Unit and integration tests for Dashboard Analysis Section Feedback Widget (#302).

Verifies:
1. Database operations: save, change/update rating, retrieve, and summarize ratings.
2. Comment length limitation and validation.
3. User rating persistence: users can rate and later change their rating.
4. API endpoints: POST /api/analysis/<aid>/feedback, GET /api/analysis/<aid>/feedback.
5. Admin authorization: unauthorized requests return 403; authorized admins receive 200 and CSV export.
6. Safe HTML escaping of feedback comments to prevent XSS.
7. Dashboard template renders section feedback controls.
"""

import os
import io
import csv
import pytest
from unittest.mock import patch
from pathlib import Path

import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    save_analysis_section_feedback,
    get_analysis_section_feedback,
    get_analysis_section_feedback_summary,
    export_analysis_section_feedback_csv,
)


@pytest.fixture
def feedback_test_env(tmp_path, monkeypatch):
    """Sets up an isolated test database and configured testing context."""
    db_file = tmp_path / "test_feedback_302.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-admin-secret-key-302")
    init_db()

    aid = "aid_feedback_test_100"
    sample_results = {
        "resume_analysis": {"ats_score": 82},
        "job_match": {"match_percentage": 78},
        "skill_gap": [{"skill": "Docker", "priority": "High"}],
        "learning_roadmap": [{"week": "Week 1", "focus": "Docker fundamentals", "topics": ["Containers"], "coding_practice": [], "mini_projects": [], "interview_questions": [], "revision_tasks": [], "estimated_hours": 10}],
        "overall_recommendation_summary": "Solid backend profile with containerization gaps."
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield {
            "client": client,
            "aid": aid,
            "db_path": str(db_file),
            "admin_key": "test-admin-secret-key-302"
        }


# ==============================================================================
# 1. Database Operations: Create, Update (Change Rating), and Validation
# ==============================================================================

def test_database_feedback_create_and_change_rating(feedback_test_env):
    """Verify user can rate a section and later change their rating without creating duplicate rows."""
    aid = feedback_test_env["aid"]
    uid = "student_alpha"
    sec = "resume_analysis"

    # 1. Initial rating: thumbs up
    rec1 = save_analysis_section_feedback(
        analysis_id=aid,
        user_id=uid,
        section=sec,
        rating="up",
        comment="Very accurate ATS score breakdown."
    )
    assert rec1["rating"] == "up"
    assert rec1["comment"] == "Very accurate ATS score breakdown."

    # Verify retrieval
    saved1 = get_analysis_section_feedback(aid, user_id=uid, section=sec)
    assert saved1 is not None
    assert saved1["rating"] == "up"

    # 2. Change rating: student updates to thumbs down with new comment
    rec2 = save_analysis_section_feedback(
        analysis_id=aid,
        user_id=uid,
        section=sec,
        rating="down",
        comment="On second thought, the experience points lacked specificity."
    )
    assert rec2["rating"] == "down"
    assert rec2["comment"] == "On second thought, the experience points lacked specificity."
    assert rec2["id"] == rec1["id"]  # Row updated in-place via UNIQUE constraint

    # Verify updated row
    saved2 = get_analysis_section_feedback(aid, user_id=uid, section=sec)
    assert saved2["rating"] == "down"
    assert "specificity" in saved2["comment"]

    # Verify all records for this analysis contains exactly 1 row for student_alpha
    all_recs = get_analysis_section_feedback(aid)
    user_recs = [r for r in all_recs if r["user_id"] == uid and r["section"] == sec]
    assert len(user_recs) == 1


def test_database_feedback_validation():
    """Verify validation for empty analysis_id, invalid ratings, and oversized comments."""
    # 1. Missing analysis_id
    with pytest.raises(ValueError, match="Analysis ID is required"):
        save_analysis_section_feedback(analysis_id="", user_id="u1", section="resume_analysis", rating="up")

    # 2. Invalid rating
    with pytest.raises(ValueError, match="Rating must be 'up' or 'down'"):
        save_analysis_section_feedback(analysis_id="aid1", user_id="u1", section="resume_analysis", rating="mediocre")

    # 3. Comment exceeding maximum length limit (default 500)
    oversized_comment = "A" * 501
    with pytest.raises(ValueError, match="Comment exceeds maximum length"):
        save_analysis_section_feedback(
            analysis_id="aid1",
            user_id="u1",
            section="resume_analysis",
            rating="up",
            comment=oversized_comment,
            max_comment_length=500
        )

    # 4. Rating normalizations (thumbs_up, positive, -1, false)
    rec_up = save_analysis_section_feedback("aid1", "u1", "roadmap", rating="thumbs_up")
    assert rec_up["rating"] == "up"

    rec_down = save_analysis_section_feedback("aid1", "u1", "roadmap", rating="thumbs_down")
    assert rec_down["rating"] == "down"


def test_database_feedback_summary_and_csv_export(feedback_test_env):
    """Verify summary calculations and CSV export data."""
    aid = feedback_test_env["aid"]

    # Seed feedback across multiple sections
    save_analysis_section_feedback(aid, "u1", "resume_analysis", rating="up", comment="Helpful resume tips.")
    save_analysis_section_feedback(aid, "u2", "resume_analysis", rating="up")
    save_analysis_section_feedback(aid, "u3", "resume_analysis", rating="down", comment="ATS was too strict.")
    save_analysis_section_feedback(aid, "u1", "skill_gaps", rating="up", comment="Great coursera course links.")
    save_analysis_section_feedback(aid, "u2", "skill_gaps", rating="down")
    save_analysis_section_feedback(aid, "u1", "roadmap", rating="up")

    summary = get_analysis_section_feedback_summary()
    assert summary["overall"]["total"] == 6
    assert summary["overall"]["up"] == 4
    assert summary["overall"]["down"] == 2
    assert summary["overall"]["percentage"] == pytest.approx(66.7, 0.1)

    resume_summary = summary["sections"]["resume_analysis"]
    assert resume_summary["total"] == 3
    assert resume_summary["up"] == 2
    assert resume_summary["down"] == 1
    assert resume_summary["percentage"] == pytest.approx(66.7, 0.1)
    assert resume_summary["comments_count"] == 2

    # CSV Export verification
    csv_str = export_analysis_section_feedback_csv()
    reader = list(csv.reader(io.StringIO(csv_str)))
    header = reader[0]
    assert header == ["id", "analysis_id", "user_id", "section", "rating", "comment", "created_at", "updated_at"]
    assert len(reader) >= 7  # Header + 6 seeded rows


# ==============================================================================
# 2. HTTP Endpoints: /api/analysis/<aid>/feedback
# ==============================================================================

def test_api_submit_feedback_create_and_update(feedback_test_env):
    """Verify HTTP API endpoint allows submitting rating and later changing it."""
    client = feedback_test_env["client"]
    aid = feedback_test_env["aid"]

    with client.session_transaction() as sess:
        sess["user_id"] = "http_student_01"

    # 1. Initial POST: thumbs up
    res1 = client.post(f"/api/analysis/{aid}/feedback", json={
        "section": "resume_analysis",
        "rating": "up",
        "comment": "Good feedback on formatting."
    })
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1["success"] is True
    assert data1["feedback"]["rating"] == "up"

    # 2. GET feedback for the user
    res_get = client.get(f"/api/analysis/{aid}/feedback?section=resume_analysis")
    assert res_get.status_code == 200
    get_data = res_get.get_json()
    assert get_data["success"] is True
    assert get_data["feedback"]["rating"] == "up"

    # 3. Update POST: change rating to thumbs down
    res2 = client.post(f"/api/analysis/{aid}/feedback", json={
        "section": "resume_analysis",
        "rating": "down",
        "comment": "Changed my mind, missed key skills."
    })
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["success"] is True
    assert data2["feedback"]["rating"] == "down"
    assert data2["feedback"]["comment"] == "Changed my mind, missed key skills."


def test_api_submit_feedback_validation_errors(feedback_test_env):
    """Verify HTTP API returns 400 on invalid payload or oversized comment."""
    client = feedback_test_env["client"]
    aid = feedback_test_env["aid"]

    # Missing section
    res_no_sec = client.post(f"/api/analysis/{aid}/feedback", json={"rating": "up"})
    assert res_no_sec.status_code == 400
    assert "Section is required" in res_no_sec.get_json()["error"]

    # Invalid rating
    res_bad_rating = client.post(f"/api/analysis/{aid}/feedback", json={"section": "roadmap", "rating": "maybe"})
    assert res_bad_rating.status_code == 400
    assert "Rating must be 'up' or 'down'" in res_bad_rating.get_json()["error"]

    # Oversized comment (> 500 chars)
    res_oversized = client.post(f"/api/analysis/{aid}/feedback", json={
        "section": "roadmap",
        "rating": "up",
        "comment": "X" * 501
    })
    assert res_oversized.status_code == 400
    assert "exceeds maximum allowed length" in res_oversized.get_json()["error"]


# ==============================================================================
# 3. Admin Authorization and Permission Checks
# ==============================================================================

def test_admin_feedback_view_and_export_permission_denied_for_regular_users(feedback_test_env):
    """Verify non-admin users cannot access the feedback summary view or CSV export."""
    client = feedback_test_env["client"]

    # Regular unauthenticated / student session
    with client.session_transaction() as sess:
        sess["user_id"] = "regular_student"
        sess["is_admin"] = False

    # 1. GET /admin/analysis-feedback -> 403 Forbidden
    res_view = client.get("/admin/analysis-feedback")
    assert res_view.status_code == 403
    assert "Unauthorized" in res_view.get_json()["error"]

    # 2. GET /admin/analysis-feedback/export.csv -> 403 Forbidden
    res_export = client.get("/admin/analysis-feedback/export.csv")
    assert res_export.status_code == 403
    assert "Unauthorized" in res_export.get_json()["error"]


def test_admin_feedback_view_and_export_authorized_via_session(feedback_test_env):
    """Verify administrator with is_admin session flag can view summary and export CSV."""
    client = feedback_test_env["client"]
    aid = feedback_test_env["aid"]

    # Seed feedback
    save_analysis_section_feedback(aid, "stud_1", "roadmap", rating="up", comment="Great timeline.")

    # Admin session
    with client.session_transaction() as sess:
        sess["user_id"] = "admin_user"
        sess["is_admin"] = True

    # 1. Summary view
    res_view = client.get("/admin/analysis-feedback")
    assert res_view.status_code == 200
    html = res_view.get_data(as_text=True)
    assert "Analysis Section Feedback Summary" in html
    assert "roadmap" in html
    assert "Great timeline." in html

    # 2. CSV export
    res_export = client.get("/admin/analysis-feedback/export.csv")
    assert res_export.status_code == 200
    assert res_export.headers.get("Content-Type").startswith("text/csv")
    assert "attachment; filename=analysis_section_feedback.csv" in res_export.headers.get("Content-Disposition", "")
    assert "Great timeline." in res_export.get_data(as_text=True)


def test_admin_feedback_view_authorized_via_admin_header(feedback_test_env):
    """Verify admin access via X-Admin-Key header."""
    client = feedback_test_env["client"]
    admin_key = feedback_test_env["admin_key"]

    res_view = client.get("/admin/analysis-feedback", headers={"X-Admin-Key": admin_key})
    assert res_view.status_code == 200
    assert "Analysis Section Feedback Summary" in res_view.get_data(as_text=True)

    res_export = client.get("/admin/analysis-feedback/export.csv", headers={"X-Admin-Key": admin_key})
    assert res_export.status_code == 200
    assert res_export.headers.get("Content-Type").startswith("text/csv")


# ==============================================================================
# 4. Safe HTML Output & XSS Escaping
# ==============================================================================

def test_comments_safely_escaped_in_admin_display(feedback_test_env):
    """Verify malicious HTML/JavaScript tags in comments are escaped safely to prevent XSS."""
    client = feedback_test_env["client"]
    aid = feedback_test_env["aid"]
    xss_payload = "<script>alert('pwned')</script><b>Bold Text</b>"

    save_analysis_section_feedback(aid, "hacker_user", "resume_analysis", rating="down", comment=xss_payload)

    with client.session_transaction() as sess:
        sess["is_admin"] = True

    res = client.get("/admin/analysis-feedback")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Raw script tags must NOT be present unescaped
    assert "<script>alert('pwned')</script>" not in html
    # Escaped version must be present
    assert "&lt;script&gt;alert(" in html or "&lt;script&gt;" in html


# ==============================================================================
# 5. Dashboard UI Template Rendering
# ==============================================================================

def test_dashboard_renders_section_feedback_widgets(feedback_test_env):
    """Verify dashboard.html includes section-feedback-widget for resume, skills, roadmap, and overall."""
    client = feedback_test_env["client"]
    aid = feedback_test_env["aid"]

    res = client.get(f"/dashboard/{aid}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "section-feedback-widget" in html
    assert 'data-section="resume_analysis"' in html
    assert 'data-section="skill_gaps"' in html
    assert 'data-section="roadmap"' in html
    assert 'data-section="overall"' in html
    assert "btn-feedback-rate" in html
    assert "Was this resume analysis helpful?" in html
    assert "Was this skill gap analysis helpful?" in html
    assert "Was this learning roadmap helpful?" in html
    assert "Was this overall analysis helpful?" in html
