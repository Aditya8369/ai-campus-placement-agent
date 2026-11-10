"""
Unit tests for AI Analysis Feedback and Correction Reporting System (#262).
Verifies:
- Feedback submission with required validation (category, description length).
- Rejection of invalid feedback categories.
- Multi-tenant student ownership enforcement (cannot report feedback on another student's analysis).
- Status lifecycle updates (pending -> under_review -> resolved).
- Feedback report retrieval and aggregation statistics.
- REST API endpoints for feedback reporting and review.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db, get_db_connection, save_analysis
from utils.analysis_feedback_service import (
    FEEDBACK_CATEGORIES,
    submit_analysis_feedback,
    get_analysis_feedback_reports,
    update_feedback_report_status,
    get_feedback_summary_statistics,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated SQLite database with sample analyses."""
    test_db = str(tmp_path / "test_feedback_report.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Alice Student', 'alice@campus.edu', 'hash1')"
    )
    cursor.execute(
        "INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Bob Student', 'bob@campus.edu', 'hash2')"
    )
    conn.commit()
    conn.close()

    # Seed analysis owned by student 1
    save_analysis(
        analysis_id="analysis_alice_1",
        resume_filename="alice_resume.pdf",
        company_name="Google",
        job_description="Seeking Senior Backend Engineer with Python and Kubernetes.",
        results_dict={
            "match_score": 75,
            "skill_gap": {"missing_skills": ["Kubernetes", "AWS"]},
        },
        student_id="1",
    )

    # Seed analysis owned by student 2
    save_analysis(
        analysis_id="analysis_bob_1",
        resume_filename="bob_resume.pdf",
        company_name="Meta",
        job_description="Looking for Frontend React Developer.",
        results_dict={
            "match_score": 88,
            "skill_gap": {"missing_skills": ["Next.js"]},
        },
        student_id="2",
    )

    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    with app.test_client() as client:
        yield client


def test_submit_valid_analysis_feedback():
    """Verify student can submit a valid correction report on their analysis."""
    report = submit_analysis_feedback(
        analysis_id="analysis_alice_1",
        student_id="1",
        category="inaccurate_skill_gap",
        field_affected="missing_skills",
        claim_detail="Kubernetes experience is explicitly mentioned on line 12 of my project section.",
        proposed_correction="Recognize container orchestration experience with k8s.",
    )
    assert report["report_id"].startswith("fb_")
    assert report["category"] == "inaccurate_skill_gap"
    assert report["status"] == "pending"

    # Verify retrieval
    reports = get_analysis_feedback_reports("analysis_alice_1", "1")
    assert len(reports) == 1
    assert reports[0]["claim_detail"] == report["claim_detail"]


def test_validation_errors():
    """Verify validation on category and claim description length."""
    with pytest.raises(ValueError, match="Invalid feedback category"):
        submit_analysis_feedback(
            analysis_id="analysis_alice_1",
            student_id="1",
            category="non_existent_category",
            claim_detail="Valid detailed description explaining why this was wrong.",
        )

    with pytest.raises(ValueError, match="minimum 10 characters"):
        submit_analysis_feedback(
            analysis_id="analysis_alice_1",
            student_id="1",
            category="wrong_match_score",
            claim_detail="Too short",
        )


def test_unauthorized_feedback_submission():
    """Verify a student cannot report feedback on another student's analysis."""
    # Student 2 tries to submit feedback on Alice's analysis
    with pytest.raises(PermissionError, match="Unauthorized"):
        submit_analysis_feedback(
            analysis_id="analysis_alice_1",
            student_id="2",
            category="wrong_match_score",
            claim_detail="I think Alice's match score is unfair.",
        )


def test_status_lifecycle_and_statistics():
    """Verify status update lifecycle and feedback summary aggregation."""
    report = submit_analysis_feedback(
        analysis_id="analysis_alice_1",
        student_id="1",
        category="poor_learning_roadmap",
        claim_detail="Roadmap suggests basic Python syntax when candidate is already senior.",
    )
    
    # Update status to under_review
    up1 = update_feedback_report_status(report["report_id"], "under_review", admin_notes="Investigating prompt logic")
    assert up1["status"] == "under_review"

    # Resolve report
    up2 = update_feedback_report_status(report["report_id"], "resolved", admin_notes="Fixed system prompt for senior candidates")
    assert up2["status"] == "resolved"
    assert up2["resolved_at"] is not None

    # Check stats
    stats = get_feedback_summary_statistics()
    assert stats["total_reports"] >= 1
    assert "resolved" in stats["reports_by_status"]


def test_api_feedback_routes(client):
    """Test REST API routes for feedback reporting."""
    # Unauthenticated
    resp = client.get("/api/analyses/analysis_alice_1/feedback")
    assert resp.status_code == 401

    # Log in as Alice (user_id = 1)
    with client.session_transaction() as sess:
        sess["user_id"] = "1"

    # Post feedback
    post_resp = client.post(
        "/api/analyses/analysis_alice_1/feedback",
        data=json.dumps({
            "category": "irrelevant_interview_questions",
            "field_affected": "interview_questions",
            "claim_detail": "Questions asked about PHP even though job description is Python only.",
            "proposed_correction": "Generate Python asyncio questions instead.",
        }),
        content_type="application/json",
    )
    assert post_resp.status_code == 201
    rep_data = post_resp.get_json()
    assert rep_data["success"] is True
    assert rep_data["report"]["category"] == "irrelevant_interview_questions"

    # Get feedback list for analysis
    get_resp = client.get("/api/analyses/analysis_alice_1/feedback")
    assert get_resp.status_code == 200
    list_data = get_resp.get_json()
    assert list_data["success"] is True
    assert len(list_data["reports"]) >= 1

    # Get feedback categories catalog
    cat_resp = client.get("/api/analyses/feedback/categories")
    assert cat_resp.status_code == 200
    assert "categories" in cat_resp.get_json()
