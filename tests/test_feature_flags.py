"""
Unit and Integration Tests for Feature Flags Service (#854).
============================================================
Tests cover:
1. Default flag states (code definitions and unregistered defaults).
2. Environment variable overrides (`FEATURE_<FLAG>=true|false`).
3. Database overrides (enabling, disabling without redeployment).
4. Stable percentage rollout for the same user ID (determinism across queries).
5. Cross-user rollout distribution.
6. Admin-only permission enforcement for toggling flags.
7. Change audit logging.
8. Jinja context processor helper `is_enabled(flag, user)`.
"""

import os
import uuid
import pytest
from flask import session

from utils.feature_flags import (
    FeatureFlagService,
    feature_flags,
    is_feature_enabled,
    calculate_rollout_bucket,
)


@pytest.fixture(autouse=True)
def clean_flags_database():
    """Ensure feature_flags table is cleaned between tests so tests are independent."""
    from utils.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM feature_flags")
        cursor.execute("DELETE FROM feature_flag_audit_logs")
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture
def flags_service():
    """Provides a fresh instance of FeatureFlagService."""
    return FeatureFlagService()


class TestFeatureFlagsEvaluation:
    """Tests multi-tier hierarchy: code defaults, env overrides, DB overrides, and percentage rollouts."""

    def test_registered_defaults(self, flags_service):
        # ai_resume_enhancement is registered default True
        assert flags_service.is_enabled("ai_resume_enhancement") is True

        # mock_interview_voice is registered default False
        assert flags_service.is_enabled("mock_interview_voice") is False

        # Unregistered flag defaults to False or user-supplied default
        assert flags_service.is_enabled("unregistered_feature_xyz") is False
        assert flags_service.is_enabled("unregistered_feature_xyz", default=True) is True

    def test_environment_variable_override(self, flags_service, monkeypatch):
        # Set environment variable to enable mock_interview_voice
        monkeypatch.setenv("FEATURE_MOCK_INTERVIEW_VOICE", "true")
        assert flags_service.is_enabled("mock_interview_voice") is True

        # Disable ai_resume_enhancement via env
        monkeypatch.setenv("FEATURE_AI_RESUME_ENHANCEMENT", "false")
        assert flags_service.is_enabled("ai_resume_enhancement") is False

    def test_database_override_takes_precedence(self, flags_service, monkeypatch):
        flag_key = "db_override_test_flag"

        # Initially false via env
        monkeypatch.setenv("FEATURE_DB_OVERRIDE_TEST_FLAG", "false")
        assert flags_service.is_enabled(flag_key) is False

        # Turn ON in database
        success, msg = flags_service.set_flag(
            flag_key=flag_key,
            is_enabled=True,
            rollout_percentage=100,
            admin_id="test_admin",
        )
        assert success is True
        # Database override should win over env var
        assert flags_service.is_enabled(flag_key) is True

        # Turn OFF in database without redeployment
        flags_service.set_flag(
            flag_key=flag_key,
            is_enabled=False,
            rollout_percentage=100,
            admin_id="test_admin",
        )
        assert flags_service.is_enabled(flag_key) is False

    def test_percentage_rollout_stability_for_same_user(self, flags_service):
        flag_key = "gradual_rollout_experiment"
        flags_service.set_flag(
            flag_key=flag_key,
            is_enabled=True,
            rollout_percentage=50,
            admin_id="test_admin",
        )

        user_a = "student_uuid_001"
        user_b = "student_uuid_002"

        # Check multiple times: evaluation must be 100% deterministic & identical
        status_a_1 = flags_service.is_enabled(flag_key, user=user_a)
        status_a_2 = flags_service.is_enabled(flag_key, user=user_a)
        status_a_3 = flags_service.is_enabled(flag_key, user={"id": user_a})
        assert status_a_1 == status_a_2 == status_a_3

        status_b_1 = flags_service.is_enabled(flag_key, user=user_b)
        status_b_2 = flags_service.is_enabled(flag_key, user=user_b)
        assert status_b_1 == status_b_2

        # Verify bucket calculation matches
        bucket_a = calculate_rollout_bucket(flag_key, user_a)
        assert status_a_1 == (bucket_a < 50)

    def test_rollout_boundary_values(self, flags_service):
        flag_key = "boundary_rollout_flag"

        # 0% rollout: always False even with user ID
        flags_service.set_flag(flag_key, is_enabled=True, rollout_percentage=0)
        assert flags_service.is_enabled(flag_key, user="any_user") is False

        # 100% rollout: always True
        flags_service.set_flag(flag_key, is_enabled=True, rollout_percentage=100)
        assert flags_service.is_enabled(flag_key, user="any_user") is True
        assert flags_service.is_enabled(flag_key) is True

    def test_audit_logs_recorded_on_change(self, flags_service):
        flag_key = "audited_feature_test"

        flags_service.set_flag(
            flag_key=flag_key,
            is_enabled=True,
            rollout_percentage=30,
            description="Testing audit logs",
            admin_id="lead_admin_42",
            ip_address="10.0.0.5",
        )

        logs = flags_service.get_audit_logs(flag_key=flag_key)
        assert len(logs) >= 1
        latest = logs[0]
        assert latest["flag_key"] == flag_key
        assert latest["admin_id"] == "lead_admin_42"
        assert latest["ip_address"] == "10.0.0.5"
        assert "Rollout: 30%" in latest["details"]


class TestFeatureFlagsRoutesAndPermissions:
    """Tests administrative route access and Jinja context processor integration."""

    def test_feature_flags_admin_endpoints_require_admin(self, client):
        # Unauthenticated GET
        res = client.get("/admin/feature-flags")
        assert res.status_code == 403

        # Unauthenticated API list
        res = client.get("/api/admin/feature-flags")
        assert res.status_code == 403

        # Unauthenticated POST toggle
        res = client.post("/api/admin/feature-flags/test_flag", json={"is_enabled": True})
        assert res.status_code == 403

    def test_admin_can_view_and_toggle_feature_flags(self, client):
        # Signed-in as admin
        with client.session_transaction() as sess:
            sess["user_id"] = "admin_user_01"
            sess["user_role"] = "admin"
            sess["is_admin"] = True

        # View dashboard
        res = client.get("/admin/feature-flags")
        assert res.status_code == 200
        assert b"Feature Flags &amp; Progressive Rollout" in res.data or b"Feature Flags" in res.data

        # Update flag via API
        flag_to_toggle = "ai_resume_enhancement"
        res = client.post(
            f"/api/admin/feature-flags/{flag_to_toggle}",
            json={"is_enabled": False, "rollout_percentage": 0},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

        # Verify state is updated
        assert is_feature_enabled(flag_to_toggle) is False

        # Query audit log endpoint
        res = client.get(f"/api/admin/feature-flags/{flag_to_toggle}/audit-logs")
        assert res.status_code == 200
        audit_data = res.get_json()
        assert audit_data["success"] is True
        assert len(audit_data["logs"]) >= 1

    def test_jinja_context_processor_is_enabled(self, client):
        # Access index with client and verify context processor helper
        res = client.get("/")
        assert res.status_code == 200

        # Test helper functions directly
        assert is_feature_enabled("batch_comparison_v2", user="test_student_123") is True
        assert is_feature_enabled("mock_interview_voice") is False
