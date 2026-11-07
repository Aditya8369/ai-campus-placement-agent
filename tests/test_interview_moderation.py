"""
Unit & Integration Tests for Interview Experience Moderation Dashboard (#252)
==============================================================================
Tests:
1. Dynamic moderation schema migration and moderation columns verification.
2. Queue retrieval with state metrics (pending_review, approved, rejected, flagged).
3. Moderation actions: approve, reject, flag, dismiss_report.
4. Audit trail logging in experience_moderation_logs.
5. Administrative authorization enforcement on /api/admin/moderation/experiences endpoints.
"""

import pytest
import json
import uuid

import config
from utils.database import (
    init_db,
    save_interview_experience,
    get_db_connection
)
from utils.interview_moderation import (
    ensure_interview_moderation_schema,
    get_moderation_queue,
    moderate_interview_experience,
    get_experience_moderation_logs
)
from app import app


@pytest.fixture
def moderation_env(tmp_path, monkeypatch):
    """Sets up an isolated database for interview moderation testing."""
    test_db = tmp_path / "test_moderation.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "mod-admin-secret-777")
    init_db()

    with get_db_connection() as conn:
        ensure_interview_moderation_schema(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "mod-app-secret"

    with app.test_client() as client:
        yield client


def test_schema_migration(moderation_env):
    """Verify moderation columns and log tables are provisioned."""
    with get_db_connection() as conn:
        ensure_interview_moderation_schema(conn)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(interview_experiences)")
        cols = {r["name"] for r in cursor.fetchall()}
        assert "moderation_status" in cols
        assert "moderated_by" in cols
        assert "moderated_at" in cols


def test_moderation_queue_and_actions(moderation_env):
    """Verify queue metrics, approval, and rejection workflow."""
    # Seed interview experiences
    exp_id_1 = "exp_mod_google_1"
    save_interview_experience(
        exp_id=exp_id_1,
        student_id="cand_1",
        candidate_name="Alice Smith",
        company_name="Google",
        role_title="Software Engineer",
        interview_date="2026-10-15",
        rounds=[{"round_name": "Coding 1", "round_type": "Technical", "difficulty": "Hard"}],
        overall_verdict="Offer",
        difficulty_level="Hard",
        tips_and_preparation="Practice dynamic programming and graphs extensively."
    )

    exp_id_2 = "exp_mod_spam_2"
    save_interview_experience(
        exp_id=exp_id_2,
        student_id="cand_2",
        candidate_name="Bob Jones",
        company_name="SpamCorp",
        role_title="Data Scientist",
        interview_date="2026-10-20",
        rounds=[{"round_name": "Screen", "round_type": "HR", "difficulty": "Easy"}],
        overall_verdict="Rejected",
        difficulty_level="Easy",
        tips_and_preparation="Suspicious promo links http://spam.xyz"
    )

    # 1. Fetch initial queue
    queue = get_moderation_queue()
    assert queue["total_matches"] >= 2
    assert queue["status_counts"]["approved"] >= 2

    # 2. Reject SpamCorp submission
    rejected = moderate_interview_experience(
        experience_id=exp_id_2,
        action="reject",
        moderator_id="admin_mod",
        reason="Violates community standards / contains spam."
    )
    assert rejected["moderation_status"] == "rejected"
    assert rejected["moderated_by"] == "admin_mod"

    # 3. Flag Google submission for review
    flagged = moderate_interview_experience(
        experience_id=exp_id_1,
        action="flag",
        moderator_id="user_reporter",
        reason="Check if NDA information was leaked."
    )
    assert flagged["moderation_status"] == "flagged"
    assert flagged["reported_flag"] == 1

    # 4. Check queue after changes
    updated_queue = get_moderation_queue()
    assert updated_queue["status_counts"]["rejected"] >= 1
    assert updated_queue["status_counts"]["flagged"] >= 1

    # 5. Dismiss report and reinstate Google submission
    dismissed = moderate_interview_experience(
        experience_id=exp_id_1,
        action="approve",
        moderator_id="senior_admin",
        reason="Verified safe: no NDA violation."
    )
    assert dismissed["moderation_status"] == "approved"
    assert dismissed["reported_flag"] == 0

    # 6. Verify audit logs
    logs = get_experience_moderation_logs(exp_id_1)
    assert len(logs) >= 2
    actions = [l["action"] for l in logs]
    assert "flag" in actions
    assert "approve" in actions


def test_api_moderation_endpoints_admin_guard(moderation_env):
    """Test /api/admin/moderation endpoints are secured and operate properly."""
    exp_id = "exp_mod_msft_3"
    save_interview_experience(
        exp_id=exp_id,
        student_id="cand_3",
        candidate_name="Charlie",
        company_name="Microsoft",
        role_title="Cloud Engineer",
        interview_date="2026-11-01",
        rounds=[],
        overall_verdict="Offer"
    )

    # 1. Unauthorized GET attempt
    unauth = moderation_env.get("/api/admin/moderation/experiences")
    assert unauth.status_code == 403

    # 2. Authorized GET queue
    auth_get = moderation_env.get(
        "/api/admin/moderation/experiences",
        headers={"X-Admin-Key": "mod-admin-secret-777"}
    )
    assert auth_get.status_code == 200
    assert auth_get.get_json()["status"] == "success"

    # 3. Authorized moderation POST action
    act_resp = moderation_env.post(
        f"/api/admin/moderation/experiences/{exp_id}/action",
        json={"action": "reject", "reason": "Low quality content."},
        headers={"X-Admin-Key": "mod-admin-secret-777"}
    )
    assert act_resp.status_code == 200
    assert act_resp.get_json()["experience"]["moderation_status"] == "rejected"

    # 4. Authorized audit logs query
    logs_resp = moderation_env.get(
        f"/api/admin/moderation/experiences/{exp_id}/logs",
        headers={"X-Admin-Key": "mod-admin-secret-777"}
    )
    assert logs_resp.status_code == 200
    assert len(logs_resp.get_json()["logs"]) >= 1
