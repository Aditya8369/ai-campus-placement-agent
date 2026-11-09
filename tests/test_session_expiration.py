"""
Tests for Session Expiration and Automatic Logout System.

Covers:
1. Session expiration configuration in config and app.config.
2. Authenticated session tracking (login sets user_id, last_activity, and login_time).
3. Activity timestamp refresh on non-status requests.
4. Automatic logout after inactivity period (redirect to login with flash warning).
5. Protection of sensitive routes after expiration (HTML redirects, API returns 401).
6. Keep-alive endpoint (/api/session/keep-alive) extending active sessions.
7. Keep-alive rejection (401) on expired or unauthenticated requests.
8. Session status endpoint (/api/session/status) reporting remaining seconds and warning flag without bumping last_activity.
9. Secure logout clearing flask_session, deleting cookies, and setting no-cache headers.
10. Testing session expiration across diverse protected endpoints (/dashboard, /company-checklist, /calendar, /profile, /applications, /notes).
"""

import time
import uuid
import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
import config
from app import app
from utils.migrations import run_database_migrations
from utils.database import (
    init_db,
    create_user,
    get_user_by_email,
)


@pytest.fixture
def auth_client(tmp_path):
    """
    Test client fixture with clean test database and enforced login checking.
    """
    test_db = tmp_path / "test_session_auth.db"
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

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = True
        app.config["TESTING_BYPASS_VERIFICATION"] = True
        app.config["SESSION_TIMEOUT_SECONDS"] = 1800
        app.config["SESSION_WARNING_SECONDS"] = 120

        try:
            with app.test_client() as client:
                with app.app_context():
                    yield client
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


@pytest.fixture
def registered_user(auth_client):
    """Create a verified test user in the database."""
    user_id = str(uuid.uuid4())
    email = f"session_student_{uuid.uuid4().hex[:6]}@example.com"
    password = "StrongPassword@2026"
    name = "Test Student"
    create_user(user_id, name, email, generate_password_hash(password))
    return {
        "id": user_id,
        "email": email,
        "password": password,
        "name": name,
    }


def test_session_configuration_defaults():
    """Verify session expiration and warning thresholds are loaded from configuration."""
    assert hasattr(config, "SESSION_TIMEOUT_SECONDS")
    assert hasattr(config, "SESSION_WARNING_SECONDS")
    assert config.SESSION_TIMEOUT_SECONDS > 0
    assert config.SESSION_WARNING_SECONDS > 0
    assert config.SESSION_WARNING_SECONDS < config.SESSION_TIMEOUT_SECONDS


def test_login_tracks_session_activity(auth_client, registered_user):
    """Successful login must set user_id, user_name, last_activity, and login_time."""
    login_res = auth_client.post("/login", data={
        "email": registered_user["email"],
        "password": registered_user["password"],
    }, follow_redirects=False)

    assert login_res.status_code == 302
    with auth_client.session_transaction() as sess:
        assert sess.get("user_id") == registered_user["id"]
        assert sess.get("user_name") == registered_user["name"]
        assert "last_activity" in sess
        assert "login_time" in sess
        assert isinstance(sess["last_activity"], (int, float))
        assert time.time() - sess["last_activity"] < 5


def test_session_status_endpoint_reports_activity_without_bumping(auth_client, registered_user):
    """
    /api/session/status should report accurate remaining seconds and warning status,
    and must NOT update last_activity timestamp.
    """
    # 1. Unauthenticated state
    status_unauth = auth_client.get("/api/session/status")
    assert status_unauth.status_code == 200
    data_unauth = status_unauth.get_json()
    assert data_unauth["authenticated"] is False

    # 2. Authenticated state
    t0 = time.time() - 300  # 300s of inactivity
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = t0

    status_auth = auth_client.get("/api/session/status")
    assert status_auth.status_code == 200
    data_auth = status_auth.get_json()
    assert data_auth["authenticated"] is True
    assert data_auth["user_id"] == registered_user["id"]
    assert data_auth["inactivity_seconds"] >= 299
    assert data_auth["remaining_seconds"] <= 1501
    assert data_auth["warning"] is False
    assert data_auth["expired"] is False

    # Check last_activity was not changed
    with auth_client.session_transaction() as sess:
        assert abs(sess["last_activity"] - t0) < 1.0


def test_session_status_reports_warning_near_expiration(auth_client, registered_user):
    """When remaining session time is within SESSION_WARNING_SECONDS, warning flag is True."""
    # 1750 seconds idle on an 1800s timeout -> 50s remaining (<= 120s warning threshold)
    t_warning = time.time() - 1750
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = t_warning

    res = auth_client.get("/api/session/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["authenticated"] is True
    assert data["warning"] is True
    assert data["remaining_seconds"] <= 120
    assert data["expired"] is False


def test_keep_alive_extends_active_session(auth_client, registered_user):
    """POST /api/session/keep-alive should refresh last_activity to current time."""
    old_time = time.time() - 600
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = old_time

    res = auth_client.post("/api/session/keep-alive")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["remaining_seconds"] == 1800

    with auth_client.session_transaction() as sess:
        assert time.time() - sess["last_activity"] < 5


def test_keep_alive_rejects_expired_or_unauthenticated_session(auth_client):
    """POST /api/session/keep-alive must return 401 when session has already expired."""
    # Unauthenticated
    res1 = auth_client.post("/api/session/keep-alive")
    assert res1.status_code == 401

    # Already expired session
    with auth_client.session_transaction() as sess:
        sess["user_id"] = "expired_user"
        sess["last_activity"] = time.time() - 2500  # > 1800s

    res2 = auth_client.post("/api/session/keep-alive")
    assert res2.status_code == 401
    assert res2.get_json()["error"] == "session_expired"


def test_automatic_logout_and_redirect_on_inactivity(auth_client, registered_user):
    """
    When an inactive user accesses a protected route after timeout,
    they must be redirected to /login with flash message, and session cleared.
    """
    expired_activity = time.time() - 2000  # 2000s > 1800s
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = expired_activity

    res = auth_client.get("/calendar", follow_redirects=True)
    assert res.status_code == 200
    # Must be on the login page now
    assert "Login" in res.get_data(as_text=True)
    assert "Your session has expired due to inactivity" in res.get_data(as_text=True)

    # Session must be completely cleared
    with auth_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_api_returns_401_session_expired(auth_client, registered_user):
    """API requests with an expired session must receive HTTP 401 session_expired JSON."""
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["last_activity"] = time.time() - 3600  # 1 hour ago

    res = auth_client.get("/api/calendar/events", headers={"Accept": "application/json"})
    assert res.status_code == 401
    data = res.get_json()
    assert data["status"] == "error"
    assert data["error"] == "session_expired"


@pytest.mark.parametrize("route", [
    "/calendar",
    "/company-checklist",
    "/profile",
    "/applications",
    "/notes",
])
def test_protected_routes_prevent_access_after_expiration(auth_client, registered_user, route):
    """Multiple distinct protected routes must strictly block access once session expires."""
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["last_activity"] = time.time() - 1900  # expired

    res = auth_client.get(route, follow_redirects=False)
    # Must redirect to login
    assert res.status_code == 302
    assert "/login" in res.headers.get("Location", "")

    # Following redirect brings to login with expiry message
    res_followed = auth_client.get(route, follow_redirects=True)
    assert res_followed.status_code == 200
    assert "Your session has expired due to inactivity" in res_followed.get_data(as_text=True)


def test_secure_logout_clears_session_and_deletes_cookie(auth_client, registered_user):
    """Logout endpoint must purge session, delete cookie, and set no-cache headers."""
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = time.time()

    res = auth_client.get("/logout")
    assert res.status_code == 302
    assert res.headers.get("Location") == "/"

    # Session cookie must be cleared
    cookie_header = res.headers.get("Set-Cookie", "")
    assert "session=" in cookie_header or "Expires=" in cookie_header or "Max-Age=0" in cookie_header

    # Cache control must prevent browser caching
    cache_control = res.headers.get("Cache-Control", "")
    assert "no-cache" in cache_control
    assert "no-store" in cache_control

    with auth_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_api_session_logout(auth_client, registered_user):
    """POST /api/session/logout terminates session and clears cookies via JSON API."""
    with auth_client.session_transaction() as sess:
        sess["user_id"] = registered_user["id"]
        sess["user_name"] = registered_user["name"]
        sess["last_activity"] = time.time()

    res = auth_client.post("/api/session/logout")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"

    with auth_client.session_transaction() as sess:
        assert "user_id" not in sess


def test_logout_with_expired_flag_shows_warning(auth_client):
    """GET /logout?expired=1 redirects to login with session expired warning."""
    res = auth_client.get("/logout?expired=1", follow_redirects=True)
    assert res.status_code == 200
    assert "Your session has expired due to inactivity" in res.get_data(as_text=True)
