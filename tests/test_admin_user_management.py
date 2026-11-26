"""
Unit and Integration Tests for Admin User Management (#853).
============================================================
Tests:
1. Deactivated users cannot log in.
2. Active sessions are revoked when a user is deactivated.
3. 'Sign out everywhere' terminates active sessions.
4. Administrative actions are audited and restricted to admins.
5. The last active admin cannot be deactivated.
6. User listings never expose password hashes, tokens, or 2FA secrets.
7. Search, filtering, and pagination work as expected.
"""

import json
import time
import uuid
import pytest
from flask import session
from werkzeug.security import generate_password_hash

from utils.database import (
    create_user,
    get_user_by_id,
    get_user_by_email,
    create_auth_session,
    get_active_auth_sessions,
    get_db_connection,
)
from utils.admin_user_service import (
    init_admin_user_management_schema,
    list_users_for_admin,
    set_user_active_status,
    sign_out_user_everywhere,
    get_admin_user_audit_logs,
    count_active_admins,
)


@pytest.fixture(autouse=True)
def setup_admin_user_schema():
    """Ensure schema is initialized before every test."""
    init_admin_user_management_schema()


class TestAdminUserManagementService:
    """Tests core service operations for admin user management."""

    def test_deactivate_and_reactivate_user(self):
        user_id = str(uuid.uuid4())
        email = f"student_{uuid.uuid4().hex[:8]}@example.com"
        create_user(user_id, "Active Student", email, generate_password_hash("password123"))

        # Create active sessions for this user
        s1 = create_auth_session(user_id, "Chrome on Mac")
        s2 = create_auth_session(user_id, "Safari on iPhone")

        active_sessions = get_active_auth_sessions(user_id)
        assert len(active_sessions) == 2

        # Deactivate user
        success, msg = set_user_active_status(
            target_user_id=user_id,
            is_active=False,
            admin_id="test_admin",
            ip_address="192.168.1.10",
        )
        assert success is True
        assert "deactivated" in msg.lower()

        # Check DB status
        user = get_user_by_id(user_id)
        assert user["is_active"] == 0

        # Verify all active sessions were revoked immediately
        remaining_sessions = get_active_auth_sessions(user_id)
        assert len(remaining_sessions) == 0

        # Reactivate user
        success, msg = set_user_active_status(
            target_user_id=user_id,
            is_active=True,
            admin_id="test_admin",
            ip_address="192.168.1.10",
        )
        assert success is True
        assert "reactivated" in msg.lower()

        user = get_user_by_id(user_id)
        assert user["is_active"] == 1

        # Check audit trail
        logs = get_admin_user_audit_logs(target_user_id=user_id)
        assert len(logs) >= 2
        actions = [log["action"] for log in logs]
        assert "USER_DEACTIVATED" in actions
        assert "USER_REACTIVATED" in actions

    def test_sign_out_everywhere(self):
        user_id = str(uuid.uuid4())
        email = f"student_{uuid.uuid4().hex[:8]}@example.com"
        create_user(user_id, "Multi-Session User", email, generate_password_hash("password123"))

        s1 = create_auth_session(user_id, "Session 1")
        s2 = create_auth_session(user_id, "Session 2")
        s3 = create_auth_session(user_id, "Session 3")

        assert len(get_active_auth_sessions(user_id)) == 3

        success, msg, count = sign_out_user_everywhere(
            target_user_id=user_id,
            admin_id="test_admin",
            ip_address="127.0.0.1",
        )
        assert success is True
        assert count == 3
        assert len(get_active_auth_sessions(user_id)) == 0

        # Verify audit log
        logs = get_admin_user_audit_logs(target_user_id=user_id)
        assert len(logs) >= 1
        assert logs[0]["action"] == "USER_SESSIONS_REVOKED"
        assert logs[0]["target_email"] == email

    def test_prevent_deactivating_last_admin(self):
        # Ensure only 1 active admin exists for this test
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE role = 'admin'")
        conn.commit()

        # Create sole admin
        admin_id = str(uuid.uuid4())
        admin_email = f"sole_admin_{uuid.uuid4().hex[:8]}@example.com"
        cursor.execute(
            """
            INSERT INTO users (id, name, email, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, 'admin', 1)
            """,
            (admin_id, "Sole Admin", admin_email, generate_password_hash("AdminPass123!")),
        )
        conn.commit()
        conn.close()

        assert count_active_admins() == 1

        # Attempt to deactivate the only admin
        success, msg = set_user_active_status(
            target_user_id=admin_id,
            is_active=False,
            admin_id=admin_id,
        )
        assert success is False
        assert "last active administrator" in msg.lower()

        # Check admin remains active
        admin_user = get_user_by_id(admin_id)
        assert admin_user["is_active"] == 1

        # Now create a second admin
        conn = get_db_connection()
        cursor = conn.cursor()
        second_admin_id = str(uuid.uuid4())
        second_email = f"second_admin_{uuid.uuid4().hex[:8]}@example.com"
        cursor.execute(
            """
            INSERT INTO users (id, name, email, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, 'admin', 1)
            """,
            (second_admin_id, "Second Admin", second_email, generate_password_hash("AdminPass123!")),
        )
        conn.commit()
        conn.close()

        assert count_active_admins() == 2

        # Now deactivating one admin should succeed
        success, msg = set_user_active_status(
            target_user_id=second_admin_id,
            is_active=False,
            admin_id=admin_id,
        )
        assert success is True
        assert count_active_admins() == 1

    def test_list_users_sanitization_and_filtering(self):
        # Create users with various states
        u1_id = str(uuid.uuid4())
        u1_email = f"searchable_alpha_{uuid.uuid4().hex[:6]}@domain.com"
        create_user(u1_id, "Alpha Candidate", u1_email, generate_password_hash("SecretPasswordHash1"))

        u2_id = str(uuid.uuid4())
        u2_email = f"searchable_beta_{uuid.uuid4().hex[:6]}@domain.com"
        create_user(u2_id, "Beta Candidate", u2_email, generate_password_hash("SecretPasswordHash2"))
        set_user_active_status(u2_id, is_active=False, admin_id="test_admin")

        # Query directory
        result = list_users_for_admin(search_query="searchable_alpha")
        assert result["total_count"] >= 1
        found = [u for u in result["users"] if u["id"] == u1_id]
        assert len(found) == 1
        user_data = found[0]

        # Sensitive field guarantees: password_hash, 2FA secrets, tokens are absent
        assert "password_hash" not in user_data
        assert "two_factor_secret" not in user_data
        assert "two_factor_backup_codes" not in user_data
        assert "verification_token" not in user_data

        # Status filtering
        active_res = list_users_for_admin(status_filter="active")
        assert all(u["is_active"] for u in active_res["users"])

        inactive_res = list_users_for_admin(status_filter="deactivated")
        assert all(not u["is_active"] for u in inactive_res["users"])


class TestAdminUserManagementRoutes:
    """Tests web endpoints and permission enforcement."""

    def test_admin_routes_require_admin_privileges(self, client):
        # Unauthenticated request to /admin/users
        res = client.get("/admin/users")
        assert res.status_code == 403

        # API endpoint unauthenticated
        res = client.get("/api/admin/users")
        assert res.status_code == 403

        # Status change unauthenticated
        res = client.post(f"/api/admin/users/{str(uuid.uuid4())}/status", json={"is_active": False})
        assert res.status_code == 403

        # Sign out everywhere unauthenticated
        res = client.post(f"/api/admin/users/{str(uuid.uuid4())}/sign-out-everywhere")
        assert res.status_code == 403

    def test_admin_can_access_directory_and_execute_actions(self, client):
        target_id = str(uuid.uuid4())
        target_email = f"victim_{uuid.uuid4().hex[:8]}@example.com"
        create_user(target_id, "Abusive User", target_email, generate_password_hash("pass123"))

        # Access with admin session
        with client.session_transaction() as sess:
            sess["user_id"] = "admin_user_1"
            sess["user_role"] = "admin"
            sess["is_admin"] = True

        # View directory
        res = client.get("/admin/users")
        assert res.status_code == 200
        assert b"User Directory &amp; Access Controls" in res.data or b"User Directory" in res.data

        # Deactivate via API
        res = client.post(f"/api/admin/users/{target_id}/status", json={"is_active": False})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

        user = get_user_by_id(target_id)
        assert user["is_active"] == 0

        # Sign out everywhere via API
        res = client.post(f"/api/admin/users/{target_id}/sign-out-everywhere")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

        # Fetch audit logs via API
        res = client.get(f"/api/admin/users/{target_id}/audit-logs")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["logs"]) >= 2

    def test_deactivated_user_cannot_login(self, client):
        user_id = str(uuid.uuid4())
        email = f"deactivated_{uuid.uuid4().hex[:8]}@example.com"
        password = "UserPassword123!"
        create_user(user_id, "Deactivated Account", email, generate_password_hash(password))

        # Ensure user is verified so email verification check passes
        conn = get_db_connection()
        conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

        # Deactivate user
        set_user_active_status(user_id, is_active=False, admin_id="test_admin")

        # Attempt to log in
        res = client.post("/login", data={
            "email": email,
            "password": password,
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Your account has been deactivated" in res.data
