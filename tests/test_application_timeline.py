"""
Unit & Integration Tests for Job Application Activity Timeline (#259)
=====================================================================
Tests:
1. Dynamic timeline schema creation and table initialization.
2. Automatic logging of status transitions (recording previous and new status).
3. Chronological timeline ordering by ascending timestamp.
4. Custom milestone and activity note logging.
5. Handling of applications without prior activity records (synthetic baseline milestone).
6. Multi-tenant access restrictions (students cannot access another's timeline).
7. REST API Endpoints:
   - GET /api/job-applications/<app_id>/timeline
   - POST /api/job-applications/<app_id>/transition
   - POST /api/job-applications/<app_id>/activity
"""

import pytest
import json

import config
from utils.database import (
    init_db,
    save_job_application,
    get_db_connection
)
from utils.application_timeline_service import (
    ensure_application_timeline_table,
    log_application_activity,
    get_application_timeline,
    transition_application_status_with_timeline
)
from app import app


@pytest.fixture
def timeline_env(tmp_path, monkeypatch):
    """Sets up an isolated test database with seeded applications."""
    test_db = tmp_path / "test_app_timeline.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_application_timeline_table(conn)

    # Seed an application for Alice
    save_job_application(
        app_id="app_time_alice",
        student_id="student_alice",
        company_name="Stripe",
        role_title="Backend Software Engineer",
        status="Applied",
        application_date="2026-11-01"
    )

    # Seed an application for Eve
    save_job_application(
        app_id="app_time_eve",
        student_id="student_eve",
        company_name="Netflix",
        role_title="Distributed Systems Engineer",
        status="Applied",
        application_date="2026-11-02"
    )

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "timeline-secret-key"

    with app.test_client() as client:
        yield client


def test_synthetic_baseline_timeline_for_legacy_apps(timeline_env):
    """Verify legacy applications without activity records generate a synthetic initial event."""
    timeline = get_application_timeline("app_time_alice", "student_alice")
    assert timeline["application_id"] == "app_time_alice"
    assert timeline["company_name"] == "Stripe"
    assert timeline["total_activities"] == 1
    assert timeline["timeline"][0]["event_type"] == "created"
    assert timeline["timeline"][0]["new_status"] == "Applied"


def test_transition_status_with_timeline(timeline_env):
    """Verify status transitions are recorded with previous and new status."""
    res = transition_application_status_with_timeline(
        application_id="app_time_alice",
        student_id="student_alice",
        new_status="Online Assessment",
        notes="Received HackerRank link due in 48 hours."
    )
    assert res["success"] is True
    assert res["previous_status"] == "Applied"
    assert res["current_status"] == "Online Assessment"

    # Transition again to Interviewing
    transition_application_status_with_timeline(
        application_id="app_time_alice",
        student_id="student_alice",
        new_status="Interviewing",
        notes="Passed OA with 100% test cases."
    )

    timeline = get_application_timeline("app_time_alice", "student_alice")
    assert timeline["total_activities"] == 2
    assert timeline["current_status"] == "Interviewing"
    assert timeline["timeline"][0]["previous_status"] == "Applied"
    assert timeline["timeline"][0]["new_status"] == "Online Assessment"
    assert timeline["timeline"][1]["previous_status"] == "Online Assessment"
    assert timeline["timeline"][1]["new_status"] == "Interviewing"


def test_log_custom_activity_note(timeline_env):
    """Verify students can record custom notes and milestones on an application."""
    activity = log_application_activity(
        application_id="app_time_alice",
        student_id="student_alice",
        new_status="Current",
        event_type="interview_prep",
        notes="Practiced system design for payment gateway API."
    )
    assert activity["event_type"] == "interview_prep"
    assert "payment gateway" in activity["notes"]


def test_multi_tenant_timeline_isolation(timeline_env):
    """Verify students are strictly blocked from viewing or logging another's application timeline."""
    # Alice attempts to view Eve's timeline
    with pytest.raises(PermissionError):
        get_application_timeline("app_time_eve", "student_alice")

    # Alice attempts to transition Eve's application
    with pytest.raises(PermissionError):
        transition_application_status_with_timeline("app_time_eve", "student_alice", "Rejected")


def test_api_timeline_endpoints(timeline_env):
    """Verify REST endpoints for retrieving and modifying application timelines."""
    # 1. Transition endpoint
    resp_trans = timeline_env.post("/api/job-applications/app_time_alice/transition", json={
        "status": "Interview Scheduled",
        "notes": "Technical round on Zoom"
    })
    # Alice is not logged into session, should use default_student or return 403
    # Let's verify session context
    with timeline_env.session_transaction() as sess:
        sess["user_id"] = "student_alice"

    resp_auth_trans = timeline_env.post("/api/job-applications/app_time_alice/transition", json={
        "status": "Interview Scheduled",
        "notes": "Technical round on Zoom"
    })
    assert resp_auth_trans.status_code == 200
    assert resp_auth_trans.get_json()["transition"]["current_status"] == "Interview Scheduled"

    # 2. Timeline GET
    resp_get = timeline_env.get("/api/job-applications/app_time_alice/timeline")
    assert resp_get.status_code == 200
    t_data = resp_get.get_json()["data"]
    assert t_data["current_status"] == "Interview Scheduled"
    assert len(t_data["timeline"]) >= 1

    # 3. Custom activity note POST
    resp_note = timeline_env.post("/api/job-applications/app_time_alice/activity", json={
        "event_type": "preparation_note",
        "notes": "Reviewed distributed systems concepts."
    })
    assert resp_note.status_code == 201
