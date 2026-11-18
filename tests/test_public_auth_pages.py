"""
Regression tests for #476: the forgot password page, the reset link page and the
privacy notice must be reachable without being logged in when login is enforced.

The normal test client skips the login check when TESTING is set, so these tests
turn on ENFORCE_LOGIN_IN_TESTS to exercise the real require_login() behaviour.
"""

import pytest

import app as app_module
from app import app


@pytest.fixture
def enforced_client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    try:
        with app.test_client() as client:
            yield client
    finally:
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False


@pytest.mark.parametrize("path", ["/forgot-password", "/privacy"])
def test_public_pages_load_when_logged_out(enforced_client, path):
    res = enforced_client.get(path)
    assert res.status_code == 200


def test_reset_password_page_loads_when_logged_out(enforced_client, monkeypatch):
    # A valid token must show the reset form, not bounce to /login.
    monkeypatch.setattr(
        app_module, "get_valid_password_reset_token", lambda token_hash: {"user_id": "u1"}
    )
    res = enforced_client.get("/reset-password/x")
    assert res.status_code == 200


def test_reset_password_bad_token_goes_to_forgot_password_not_login(enforced_client):
    # An unknown token is handled by the route itself (redirect to /forgot-password),
    # the login check must not get in the way.
    res = enforced_client.get("/reset-password/x")
    assert res.status_code == 302
    assert "/forgot-password" in res.headers["Location"]
    assert enforced_client.get("/reset-password/x", follow_redirects=True).status_code == 200


def test_login_page_still_public_when_logged_out(enforced_client):
    assert enforced_client.get("/login").status_code == 200


def test_private_page_still_redirects_to_login_when_logged_out(enforced_client):
    res = enforced_client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]
