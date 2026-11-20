"""
Tests for Active Sessions Management and Device Revocation (#473).

Covers:
1. Session record creation on login (ID, client label, created_at, last_seen_at).
2. Active sessions listing with device summary and 'is_current' identification.
3. User agent parsing to coarse device/browser summary (privacy-friendly, no IP by default).
4. Revoking a single session and rejecting it on the next request (both HTML and API).
5. Revoking the current session immediately logging out.
6. "Sign out of all other devices" revoking all other sessions while keeping the current one active.
7. Cross-user isolation: User A cannot see or revoke User B's sessions.
8. Password reset invalidating all active sessions for that user.
9. Password change invalidating all other active sessions while preserving current session.
10. Profile page UI rendering: active sessions table, badges, buttons, and change password form.
"""

import time
import uuid
import hashlib
import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash, check_password_hash
import config
from app import app
from utils.migrations import run_database_migrations
from utils.database import (
    init_db,
    create_user,
    get_user_by_id,
    create_auth_session,
    get_active_auth_sessions,
    get_active_auth_session,
    revoke_auth_session,
    revoke_other_auth_sessions,
    revoke_all_auth_sessions,
    change_user_password,
    create_password_reset_token,
    reset_user_password,
)


@pytest.fixture
def auth_app(tmp_path):
    """Setup clean isolated test database and test context."""
    test_db = tmp_path / "test_active_sessions.db"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "DATABASE_PATH", str(test_db)), \
         patch.object(config, "REPORT_FOLDER", str(report_dir)):
        init_db()
        run_database_migrations()

        orig_enforce = app.config.get("ENFORCE_LOGIN_IN_TESTS")
        orig_timeout = app.config.get("SESSION_TIMEOUT_SECONDS")
        orig_warning = app.config.get("SESSION_WARNING_SECONDS")
        orig_bypass = app.config.get("TESTING_BYPASS_VERIFICATION")
        orig_testing = app.config.get("TESTING")

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = True
        app.config["TESTING_BYPASS_VERIFICATION"] = True
        app.config["SESSION_TIMEOUT_SECONDS"] = 1800
        app.config["SESSION_WARNING_SECONDS"] = 120

        try:
            with app.app_context():
                yield app
        finally:
            if orig_enforce is not None:
                app.config["ENFORCE_LOGIN_IN_TESTS"] = orig_enforce
            else:
                app.config.pop("ENFORCE_LOGIN_IN_TESTS", None)

            if orig_timeout is not None:
                app.config["SESSION_TIMEOUT_SECONDS"] = orig_timeout
            else:
                app.config.pop("SESSION_TIMEOUT_SECONDS", None)

            if orig_warning is not None:
                app.config["SESSION_WARNING_SECONDS"] = orig_warning
            else:
                app.config.pop("SESSION_WARNING_SECONDS", None)

            if orig_bypass is not None:
                app.config["TESTING_BYPASS_VERIFICATION"] = orig_bypass
            else:
                app.config.pop("TESTING_BYPASS_VERIFICATION", None)

            app.config["TESTING"] = orig_testing


def _create_test_user(email_prefix="student"):
    """Helper to create a verified user."""
    user_id = str(uuid.uuid4())
    email = f"{email_prefix}_{uuid.uuid4().hex[:6]}@example.com"
    password = "InitialPassword@123"
    name = f"Test User {user_id[:4]}"
    create_user(user_id, name, email, generate_password_hash(password))
    return {
        "id": user_id,
        "email": email,
        "password": password,
        "name": name,
    }


def test_login_creates_auth_session_record(auth_app):
    """Logging in must create a record in auth_sessions table with device summary."""
    user = _create_test_user("login_test")
    client = auth_app.test_client()

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    resp = client.post(
        "/login",
        data={"email": user["email"], "password": user["password"]},
        headers={"User-Agent": ua},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # Verify session in DB
    sessions = get_active_auth_sessions(user["id"])
    assert len(sessions) == 1
    sess = sessions[0]
    assert sess["id"] is not None
    assert "Chrome on Windows" in sess["client_label"]
    assert sess["created_at"] is not None
    assert sess["last_seen_at"] is not None


def test_active_sessions_list_and_current_session_flag(auth_app):
    """
    /api/account/sessions must return active sessions and mark the caller's session as is_current.
    """
    user = _create_test_user("two_devices")
    client1 = auth_app.test_client()
    client2 = auth_app.test_client()

    # Device 1: Chrome on Windows
    client1.post(
        "/login",
        data={"email": user["email"], "password": user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
    )

    # Device 2: Safari on iPhone
    client2.post(
        "/login",
        data={"email": user["email"], "password": user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 Version/16.5 Mobile/15E148 Safari/604.1"},
    )

    # Query from Client 1
    resp1 = client1.get("/api/account/sessions")
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["success"] is True
    session_list1 = data1["sessions"]
    assert len(session_list1) == 2

    # Exactly one session should have is_current == True
    current_items1 = [s for s in session_list1 if s["is_current"]]
    assert len(current_items1) == 1
    assert "Windows" in current_items1[0]["client_label"]

    # Query from Client 2
    resp2 = client2.get("/api/account/sessions")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    session_list2 = data2["sessions"]
    current_items2 = [s for s in session_list2 if s["is_current"]]
    assert len(current_items2) == 1
    assert "iOS" in current_items2[0]["client_label"] or "Safari" in current_items2[0]["client_label"]


def test_device_user_agent_summary_parsing(auth_app):
    """User agent strings should parse to clean coarse descriptions without leaking IPs."""
    user = _create_test_user("ua_test")

    test_cases = [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "Chrome on macOS"),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0", "Firefox on Linux"),
        ("Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 Chrome/112.0.0.0 Mobile Safari/537.36", "Chrome on Android"),
    ]

    for ua_header, expected_label in test_cases:
        client = auth_app.test_client()
        client.post(
            "/login",
            data={"email": user["email"], "password": user["password"]},
            headers={"User-Agent": ua_header},
        )

    sessions = get_active_auth_sessions(user["id"])
    labels = [s["client_label"] for s in sessions]
    for _, expected_label in test_cases:
        assert any(expected_label in l for l in labels), f"Expected '{expected_label}' in {labels}"


def test_revoke_single_session_and_reject_on_next_request(auth_app):
    """
    Signing out a specific remote session must invalidate it, causing its next request
    to be rejected (redirect to /login or 401 JSON).
    """
    user = _create_test_user("revoke_single")
    client1 = auth_app.test_client()  # Current device
    client2 = auth_app.test_client()  # Remote device 1 (makes API request)
    client3 = auth_app.test_client()  # Remote device 2 (makes HTML request)

    client1.post("/login", data={"email": user["email"], "password": user["password"]})
    client2.post("/login", data={"email": user["email"], "password": user["password"]})
    client3.post("/login", data={"email": user["email"], "password": user["password"]})

    with client2.session_transaction() as sess2:
        dev2_session_id = sess2.get("auth_session_id")
    with client3.session_transaction() as sess3:
        dev3_session_id = sess3.get("auth_session_id")

    assert dev2_session_id is not None
    assert dev3_session_id is not None

    # Device 1 revokes device 2 and device 3
    client1.post("/account/sessions/revoke", data={"session_id": dev2_session_id, "next": "/profile"})
    client1.post("/account/sessions/revoke", data={"session_id": dev3_session_id, "next": "/profile"})

    # Device 1 remains active
    d1_resp = client1.get("/profile")
    assert d1_resp.status_code == 200

    # Device 2 makes next request to API route -> must return 401 session_revoked
    d2_api = client2.get("/api/account/sessions", headers={"Accept": "application/json"})
    assert d2_api.status_code == 401
    assert d2_api.get_json()["error"] == "session_revoked"

    # Device 3 makes next request to HTML route -> must be rejected and redirected to /login
    d3_html = client3.get("/profile", follow_redirects=False)
    assert d3_html.status_code == 302
    assert "/login" in d3_html.headers.get("Location", "")

    # Following redirect brings to login with notice
    d3_followed = client3.get("/profile", follow_redirects=True)
    assert d3_followed.status_code == 200
    assert "This session is no longer active" in d3_followed.get_data(as_text=True)


def test_revoke_current_session_logs_user_out(auth_app):
    """Revoking the current session immediately terminates the session and redirects to /login."""
    user = _create_test_user("revoke_self")
    client = auth_app.test_client()
    client.post("/login", data={"email": user["email"], "password": user["password"]})

    with client.session_transaction() as sess:
        current_sess_id = sess.get("auth_session_id")
    assert current_sess_id is not None

    resp = client.post(
        "/account/sessions/revoke",
        data={"session_id": current_sess_id},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")

    # Session cookie must be cleared
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_sign_out_of_all_other_devices(auth_app):
    """
    POST /account/sessions/revoke-others should revoke all other sessions
    while keeping the requesting session alive.
    """
    user = _create_test_user("revoke_all_others")
    client_current = auth_app.test_client()
    client_other1 = auth_app.test_client()
    client_other2 = auth_app.test_client()

    client_current.post("/login", data={"email": user["email"], "password": user["password"]})
    client_other1.post("/login", data={"email": user["email"], "password": user["password"]})
    client_other2.post("/login", data={"email": user["email"], "password": user["password"]})

    # Verify 3 active sessions exist
    active = get_active_auth_sessions(user["id"])
    assert len(active) == 3

    # Client current requests "Sign out of all other devices"
    revoke_res = client_current.post(
        "/account/sessions/revoke-others",
        data={"next": "/profile"},
        follow_redirects=True,
    )
    assert revoke_res.status_code == 200
    assert "Signed out of 2 other devices." in revoke_res.get_data(as_text=True)

    # Active sessions in DB should now only be 1
    active_after = get_active_auth_sessions(user["id"])
    assert len(active_after) == 1

    # Current client is still logged in
    res_curr = client_current.get("/profile")
    assert res_curr.status_code == 200

    # Other clients are rejected on their next request
    res_other1 = client_other1.get("/profile", follow_redirects=False)
    assert res_other1.status_code == 302
    assert "/login" in res_other1.headers.get("Location", "")

    res_other2 = client_other2.get("/api/account/sessions", headers={"Accept": "application/json"})
    assert res_other2.status_code == 401


def test_cross_user_isolation(auth_app):
    """
    User A must not be able to list, revoke, or affect User B's active sessions.
    """
    user_a = _create_test_user("user_a")
    user_b = _create_test_user("user_b")

    client_a = auth_app.test_client()
    client_b = auth_app.test_client()

    client_a.post("/login", data={"email": user_a["email"], "password": user_a["password"]})
    client_b.post("/login", data={"email": user_b["email"], "password": user_b["password"]})

    with client_b.session_transaction() as sess_b:
        user_b_sess_id = sess_b.get("auth_session_id")
    assert user_b_sess_id is not None

    # User A listing sessions must only see User A's session
    resp_a_list = client_a.get("/api/account/sessions")
    data_a = resp_a_list.get_json()
    assert len(data_a["sessions"]) == 1
    assert data_a["sessions"][0]["id"] != user_b_sess_id

    # User A attempts to revoke User B's session_id
    resp_tamper = client_a.post(
        "/account/sessions/revoke",
        data={"session_id": user_b_sess_id},
        headers={"Accept": "application/json"},
    )
    # Should fail (404 not active / not found for this user)
    assert resp_tamper.status_code in (404, 400)

    # User B's session must still be active and valid
    resp_b_check = client_b.get("/profile")
    assert resp_b_check.status_code == 200

    # User A calls revoke-others -> must not affect User B
    client_a.post("/account/sessions/revoke-others", data={"next": "/profile"})
    resp_b_after = client_b.get("/profile")
    assert resp_b_after.status_code == 200


def test_password_reset_revokes_all_sessions(auth_app):
    """
    Completing a password reset must immediately invalidate ALL active sessions for that user.
    """
    user = _create_test_user("pwd_reset")
    client1 = auth_app.test_client()
    client2 = auth_app.test_client()

    client1.post("/login", data={"email": user["email"], "password": user["password"]})
    client2.post("/login", data={"email": user["email"], "password": user["password"]})

    assert len(get_active_auth_sessions(user["id"])) == 2

    # Simulate generating reset token
    raw_token = "secure-reset-token-xyz"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + 3600
    create_password_reset_token(user["id"], token_hash, expires_at)

    # User completes password reset
    new_password = "BrandNewPassword@2026"
    new_hash = generate_password_hash(new_password)
    reset_ok = reset_user_password(token_hash, new_hash)
    assert reset_ok is True

    # In DB, all sessions must be revoked
    active = get_active_auth_sessions(user["id"])
    assert len(active) == 0

    # Client 1 makes next request -> rejected
    res1 = client1.get("/profile", follow_redirects=False)
    assert res1.status_code == 302
    assert "/login" in res1.headers.get("Location", "")

    # Client 2 makes next API request -> 401
    res2 = client2.get("/api/account/sessions", headers={"Accept": "application/json"})
    assert res2.status_code == 401

    # User can log in with new password
    client3 = auth_app.test_client()
    res3 = client3.post("/login", data={"email": user["email"], "password": new_password})
    assert res3.status_code == 302


def test_password_change_revokes_all_other_sessions(auth_app):
    """
    Changing password on Device 1 must revoke Device 2 while keeping Device 1 signed in.
    """
    user = _create_test_user("pwd_change")
    client1 = auth_app.test_client()  # Device 1
    client2 = auth_app.test_client()  # Device 2

    client1.post("/login", data={"email": user["email"], "password": user["password"]})
    client2.post("/login", data={"email": user["email"], "password": user["password"]})

    assert len(get_active_auth_sessions(user["id"])) == 2

    # Device 1 changes password via /account/change-password
    new_pwd = "UpdatedPassword@2026"
    change_resp = client1.post(
        "/account/change-password",
        data={
            "current_password": user["password"],
            "new_password": new_pwd,
            "confirm_password": new_pwd,
            "next": "/profile",
        },
        follow_redirects=True,
    )
    assert change_resp.status_code == 200
    assert "Password updated successfully" in change_resp.get_data(as_text=True)

    # Check database: user's password was updated
    updated_user = get_user_by_id(user["id"])
    assert check_password_hash(updated_user["password_hash"], new_pwd)

    # Only 1 session should remain active (Device 1)
    active_sessions = get_active_auth_sessions(user["id"])
    assert len(active_sessions) == 1

    # Device 1 continues to have access to protected routes
    res1 = client1.get("/profile")
    assert res1.status_code == 200

    # Device 2 is rejected on next request
    res2 = client2.get("/profile", follow_redirects=False)
    assert res2.status_code == 302
    assert "/login" in res2.headers.get("Location", "")


def test_profile_page_renders_active_sessions_and_actions(auth_app):
    """
    GET /profile renders active sessions section, current session badge,
    sign out buttons, and 'Sign out of all other devices' button when multiple sessions exist.
    """
    user = _create_test_user("profile_ui")
    client1 = auth_app.test_client()
    client2 = auth_app.test_client()

    client1.post(
        "/login",
        data={"email": user["email"], "password": user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    )
    client2.post(
        "/login",
        data={"email": user["email"], "password": user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5) Version/16.5 Mobile Safari/604.1"},
    )

    resp = client1.get("/profile")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # UI Elements from profile.html
    assert 'id="activeSessionsSection"' in html
    assert 'id="activeSessionsTable"' in html
    assert "Current session" in html
    assert "Sign out of all other devices" in html
    assert "Sign out" in html
    assert 'id="passwordManagementSection"' in html
    assert 'action="/account/change-password"' in html
