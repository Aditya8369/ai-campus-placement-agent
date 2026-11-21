"""
Unit tests for Email Address Change with Verification (#405).
"""

import json
import sqlite3
import pytest
from routes import create_app
from utils.email_change_service import EmailChangeService, _get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def _setup_test_user(user_id: str, email: str):
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    is_verified INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("INSERT OR REPLACE INTO users (id, email) VALUES (?, ?)", (user_id, email.lower()))
    finally:
        conn.close()


def test_email_change_lifecycle():
    user = "email_user_405"
    old_email = "old.student@college.edu"
    new_email = "new.student@domain.org"

    _setup_test_user(user, old_email)

    # 1. Request email change
    success, msg, token = EmailChangeService.request_email_change(user, new_email)
    assert success is True
    assert token is not None

    # Verify old email is still active in users table
    conn = _get_db_connection()
    current = conn.execute("SELECT email FROM users WHERE id = ?", (user,)).fetchone()
    assert current["email"] == old_email
    conn.close()

    # 2. Verify pending request inspection
    pending = EmailChangeService.get_pending_request(user)
    assert pending is not None
    assert pending["pending_new_email"] == new_email

    # 3. Complete email verification with token
    res = EmailChangeService.verify_email_change(token)
    assert res["success"] is True
    assert res["new_email"] == new_email

    # Check database now holds new email
    conn = _get_db_connection()
    updated = conn.execute("SELECT email FROM users WHERE id = ?", (user,)).fetchone()
    assert updated["email"] == new_email
    conn.close()


def test_email_change_already_used_and_expired():
    user = "email_user_405_used"
    _setup_test_user(user, "user1@test.com")

    # Request change
    success, _, token = EmailChangeService.request_email_change(user, "user1_new@test.com")
    assert success is True

    # Use once
    res1 = EmailChangeService.verify_email_change(token)
    assert res1["success"] is True

    # Try using again -> already used error
    res2 = EmailChangeService.verify_email_change(token)
    assert res2["success"] is False
    assert res2["error_code"] == "ALREADY_USED"

    # Test expired token
    success2, _, token2 = EmailChangeService.request_email_change(user, "user1_new2@test.com")
    conn = _get_db_connection()
    with conn:
        conn.execute("UPDATE pending_email_changes SET expires_at = 100 WHERE user_id = ?", (user,))
    conn.close()

    res_exp = EmailChangeService.verify_email_change(token2)
    assert res_exp["success"] is False
    assert res_exp["error_code"] == "EXPIRED"


def test_email_enumeration_defense():
    # User B tries to switch to User A's already registered email
    _setup_test_user("user_a", "alice@corp.com")
    _setup_test_user("user_b", "bob@corp.com")

    success, msg, token = EmailChangeService.request_email_change("user_b", "alice@corp.com")
    # Returns generic success to protect enumeration without issuing real token
    assert success is True
    assert token is None
    assert "eligible" in msg.lower()


def test_email_change_api_routes(client):
    user = "api_email_user_405"
    _setup_test_user(user, "api_old@test.com")

    with client.session_transaction() as s:
        s["user_id"] = user

    # 1. HTML Settings View
    view_res = client.get("/settings/email")
    assert view_res.status_code == 200
    assert b"Change Account Email" in view_res.data

    # 2. API Request
    req_res = client.post("/api/user/email-change/request", json={
        "new_email": "api_new@test.com"
    })
    assert req_res.status_code == 200
    r_data = json.loads(req_res.data)
    token = r_data["verification_token"]
    assert token is not None

    # 3. HTML Verification View
    verify_html_res = client.get(f"/verify-email-change/{token}")
    assert verify_html_res.status_code == 200
    assert b"Email Address Updated" in verify_html_res.data

    # Verify email updated in users table
    conn = _get_db_connection()
    user_row = conn.execute("SELECT email FROM users WHERE id = ?", (user,)).fetchone()
    assert user_row["email"] == "api_new@test.com"
    conn.close()
