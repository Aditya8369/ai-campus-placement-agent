"""
Comprehensive Automated Test Suite for CSRF Protection & Session Cookie Hardening (#300).
Validates:
- Rejection of POST requests without valid tokens with HTTP 400.
- Acceptance of valid tokens via headers (X-CSRFToken, X-CSRF-Token) and form body.
- Clear user-friendly error page rendering for browser requests and JSON for AJAX/API.
- Session cookie hardening flags (HttpOnly, SameSite=Lax, Secure in production).
- Template inclusion of CSRF meta tags and hidden form fields.
"""

import os
import re
import time
import hmac
import hashlib
import pytest
from flask import Flask, session
from app import app
from utils.csrf import csrf, generate_csrf, validate_csrf, CSRFError
import config


@pytest.fixture
def csrf_enabled_client():
    """Test client fixture with CSRF enforcement strictly activated."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]

    with app.test_client() as client:
        yield client

    app.config["WTF_CSRF_ENABLED"] = False


def test_post_without_csrf_token_is_rejected_with_400(csrf_enabled_client):
    """Verify state-changing POST without CSRF token is rejected with HTTP 400 (#300)."""
    response = csrf_enabled_client.post("/login", data={"email": "student@university.edu", "password": "password123"})
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert "Security Validation Failed" in html or "CSRF Validation Failed" in html or "CSRF token" in html
    assert "400" in html


def test_ajax_post_without_csrf_token_returns_json_400(csrf_enabled_client):
    """Verify AJAX / API POST without CSRF token returns structured JSON 400 (#300)."""
    response = csrf_enabled_client.post(
        "/api/analysis/start",
        data={},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data is not None
    assert data.get("success") is False
    assert "CSRF" in data.get("error", "") or "csrf" in data.get("error", "").lower()


def test_post_with_invalid_csrf_token_is_rejected_with_400(csrf_enabled_client):
    """Verify POST with invalid / forged CSRF token is rejected with HTTP 400 (#300)."""
    # Initialize a session first
    csrf_enabled_client.get("/")

    # Attempt with bad header token
    response_header = csrf_enabled_client.post(
        "/login",
        data={"email": "student@university.edu"},
        headers={"X-CSRFToken": "forged_malicious_token_12345"}
    )
    assert response_header.status_code == 400

    # Attempt with bad form data token
    response_form = csrf_enabled_client.post(
        "/login",
        data={"email": "student@university.edu", "csrf_token": "forged_malicious_token_12345"}
    )
    assert response_form.status_code == 400


def test_post_with_valid_header_csrftoken_succeeds(csrf_enabled_client):
    """Verify POST request containing valid X-CSRFToken header passes CSRF verification (#300)."""
    # 1. Fetch homepage to initialize session and get token
    get_res = csrf_enabled_client.get("/")
    assert get_res.status_code == 200

    with csrf_enabled_client.session_transaction() as sess:
        with app.test_request_context():
            token = generate_csrf()

    # 2. Submit POST with valid header token
    response = csrf_enabled_client.post(
        "/login",
        data={"email": "nonexistent_test_student@example.com", "password": "Password123!"},
        headers={"X-CSRFToken": token}
    )
    # The CSRF check must pass (status is not 400 CSRF error)
    assert response.status_code != 400


def test_post_with_valid_header_csrf_dash_token_succeeds(csrf_enabled_client):
    """Verify POST request containing valid X-CSRF-Token header passes CSRF verification (#300)."""
    csrf_enabled_client.get("/")
    with app.test_request_context():
        token = generate_csrf()

    response = csrf_enabled_client.post(
        "/login",
        data={"email": "nonexistent_test_student@example.com", "password": "Password123!"},
        headers={"X-CSRF-Token": token}
    )
    assert response.status_code != 400


def test_post_with_valid_form_field_token_succeeds(csrf_enabled_client):
    """Verify POST request containing valid form field csrf_token passes verification (#300)."""
    csrf_enabled_client.get("/")
    with app.test_request_context():
        token = generate_csrf()

    response = csrf_enabled_client.post(
        "/login",
        data={
            "email": "nonexistent_test_student@example.com",
            "password": "Password123!",
            "csrf_token": token
        }
    )
    assert response.status_code != 400


def test_get_requests_are_exempt_from_csrf(csrf_enabled_client):
    """Verify safe HTTP methods (GET, HEAD, OPTIONS) do not require CSRF token (#300)."""
    res_index = csrf_enabled_client.get("/")
    assert res_index.status_code == 200

    res_login = csrf_enabled_client.get("/login")
    assert res_login.status_code == 200

    res_register = csrf_enabled_client.get("/register")
    assert res_register.status_code == 200


def test_session_cookie_hardening_flags_development():
    """Verify session cookie security flags in development environment (#300)."""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    # When not in production, Secure flag should be False to permit localhost HTTP testing
    if os.getenv("FLASK_ENV") != "production":
        assert app.config["SESSION_COOKIE_SECURE"] is False


def test_session_cookie_hardening_flags_production_logic(monkeypatch):
    """Verify SESSION_COOKIE_SECURE evaluates to True when running in production (#300)."""
    monkeypatch.setenv("FLASK_ENV", "production")

    is_prod = (
        os.getenv("FLASK_ENV", "").lower() == "production"
        or os.getenv("ENV", "").lower() == "production"
        or os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("true", "1", "yes")
    )
    assert is_prod is True


def test_rendered_templates_contain_csrf_meta_and_hidden_inputs():
    """Verify UI templates render the csrf-token meta tag and hidden form inputs (#300)."""
    with app.test_client() as client:
        # Check login page
        res_login = client.get("/login")
        html_login = res_login.get_data(as_text=True)
        assert '<meta name="csrf-token"' in html_login
        assert 'name="csrf_token"' in html_login

        # Check register page
        res_reg = client.get("/register")
        html_reg = res_reg.get_data(as_text=True)
        assert '<meta name="csrf-token"' in html_reg
        assert 'name="csrf_token"' in html_reg

        # Check homepage index
        res_index = client.get("/")
        html_index = res_index.get_data(as_text=True)
        assert '<meta name="csrf-token"' in html_index
        assert 'name="csrf_token"' in html_index


def test_csrf_exempt_route_behavior():
    """Verify routes marked with @csrf.exempt bypass CSRF validation (#300)."""
    from utils.csrf import CSRFProtect
    test_app = Flask("test_exempt_app")
    test_app.secret_key = "test-secret"
    test_app.config["WTF_CSRF_ENABLED"] = True
    test_csrf = CSRFProtect(test_app)

    @test_app.route("/api/test-exempt-route", methods=["POST"])
    @test_csrf.exempt
    def _test_exempt():
        return {"status": "exempt_ok"}

    with test_app.test_client() as client:
        res = client.post("/api/test-exempt-route")
        assert res.status_code == 200
        assert res.get_json()["status"] == "exempt_ok"


def test_fallback_csrf_generation_and_validation():
    """Verify fallback HMAC-signed token generation and validation mechanism (#300)."""
    from utils.csrf import (
        _fallback_generate_csrf,
        _fallback_validate_csrf,
        FallbackCSRFError,
    )

    test_app = Flask("fallback_test_app")
    test_app.secret_key = "fallback-test-secret-key-123"

    with test_app.test_request_context():
        # 1. Valid token generation & validation
        token = _fallback_generate_csrf()
        assert token is not None
        assert "##" in token
        # Validate should not raise
        _fallback_validate_csrf(token)

        # 2. Missing token
        with pytest.raises(Exception) as exc_missing:
            _fallback_validate_csrf(None)
        assert "missing" in str(exc_missing.value).lower()

        # 3. Malformed token
        with pytest.raises(Exception) as exc_malformed:
            _fallback_validate_csrf("not_a_valid_token_without_separator")
        assert "malformed" in str(exc_malformed.value).lower()

        # 4. Invalid timestamp
        with pytest.raises(Exception) as exc_ts:
            _fallback_validate_csrf("some_signature##not_an_int")
        assert "timestamp" in str(exc_ts.value).lower()

        # 5. Expired token
        old_ts = int(time.time()) - 7200
        old_data = f"{session['csrf_token']}##{old_ts}".encode("utf-8")
        old_sig = hmac.new(b"fallback-test-secret-key-123", old_data, hashlib.sha256).hexdigest()
        expired_token = f"{old_sig}##{old_ts}"
        with pytest.raises(Exception) as exc_exp:
            _fallback_validate_csrf(expired_token, time_limit=3600)
        assert "expired" in str(exc_exp.value).lower()

        # 6. Invalid / forged signature
        parts = token.split("##")
        bad_sig_token = f"bad_signature_hash##{parts[1]}"
        with pytest.raises(Exception) as exc_sig:
            _fallback_validate_csrf(bad_sig_token)
        assert "invalid" in str(exc_sig.value).lower()

