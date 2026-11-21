"""
Unit and integration tests for Privacy-Friendly CAPTCHA (Turnstile / hCaptcha) (#653).

Acceptance Criteria:
- With no keys configured, nothing changes for users.
- With keys configured, a missing or invalid token blocks the request with a clear message.
- The CSP allows only the chosen provider.
- Tests mock the verification call and cover valid, invalid, missing and provider-down cases.
"""

import io
import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

import config
from app import app
from utils.captcha import (
    is_captcha_enabled,
    get_captcha_provider,
    get_captcha_site_key,
    get_captcha_secret_key,
    is_captcha_fail_open,
    should_require_captcha,
    record_failed_attempt,
    reset_failed_attempts,
    get_failed_attempts,
    extract_captcha_token,
    verify_captcha_token,
    verify_captcha,
)
from utils.database import init_db, create_user


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_captcha.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db(str(test_db))
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["TESTING_BYPASS_VERIFICATION"] = True

        # Reset any test CAPTCHA configuration
        app.config["CAPTCHA_PROVIDER"] = ""
        app.config["CAPTCHA_SITE_KEY"] = ""
        app.config["CAPTCHA_SECRET_KEY"] = ""
        app.config["CAPTCHA_FAIL_OPEN"] = False
        app.config["CAPTCHA_ALWAYS_ENFORCE"] = True
        app.config["CAPTCHA_REQUIRE_AFTER_FAILURES"] = 0

        reset_failed_attempts("127.0.0.1", "test@example.com")
        reset_failed_attempts("127.0.0.1", "bot@example.com")

        with app.test_client() as c:
            yield c


# ==============================================================================
# 1. Zero-Disruption When Unconfigured
# ==============================================================================

def test_captcha_disabled_when_keys_unset(client):
    assert is_captcha_enabled() is False

    # GET login, register, forgot-password should not render captcha widgets
    res_login = client.get("/login")
    assert res_login.status_code == 200
    assert b"cf-turnstile" not in res_login.data
    assert b"h-captcha" not in res_login.data

    res_reg = client.get("/register")
    assert res_reg.status_code == 200
    assert b"cf-turnstile" not in res_reg.data
    assert b"h-captcha" not in res_reg.data

    res_fp = client.get("/forgot-password")
    assert res_fp.status_code == 200
    assert b"cf-turnstile" not in res_fp.data
    assert b"h-captcha" not in res_fp.data


def test_registration_and_login_work_normally_without_captcha_when_unset(client):
    app.config["CAPTCHA_PROVIDER"] = ""
    app.config["CAPTCHA_SITE_KEY"] = ""
    app.config["CAPTCHA_SECRET_KEY"] = ""

    # Register without token
    res = client.post(
        "/register",
        data={
            "name": "Normal User",
            "email": "normal@example.com",
            "password": "Password123!",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration successful" in res.data

    # Login without token
    res_login = client.post(
        "/login",
        data={
            "email": "normal@example.com",
            "password": "Password123!",
        },
        follow_redirects=True,
    )
    assert res_login.status_code == 200
    assert b"Login successful" in res_login.data


# ==============================================================================
# 2. Content Security Policy (CSP) Directives
# ==============================================================================

def test_csp_allows_only_turnstile_when_turnstile_configured(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "0x4AAAAAAATurnstileSiteKey"
    app.config["CAPTCHA_SECRET_KEY"] = "0x4AAAAAAATurnstileSecretKey"

    res = client.get("/login")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")

    # Turnstile domains MUST be permitted
    assert "https://challenges.cloudflare.com" in csp
    # hCaptcha domains MUST NOT be permitted
    assert "hcaptcha.com" not in csp
    assert "newassets.hcaptcha.com" not in csp


def test_csp_allows_only_hcaptcha_when_hcaptcha_configured(client):
    app.config["CAPTCHA_PROVIDER"] = "hcaptcha"
    app.config["CAPTCHA_SITE_KEY"] = "10000000-ffff-ffff-ffff-000000000001"
    app.config["CAPTCHA_SECRET_KEY"] = "0x0000000000000000000000000000000000000000"

    res = client.get("/login")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")

    # hCaptcha domains MUST be permitted
    assert "https://js.hcaptcha.com" in csp
    assert "https://newassets.hcaptcha.com" in csp
    assert "https://api.hcaptcha.com" in csp
    # Turnstile domains MUST NOT be permitted
    assert "challenges.cloudflare.com" not in csp


def test_csp_excludes_both_providers_when_unconfigured(client):
    app.config["CAPTCHA_PROVIDER"] = ""
    app.config["CAPTCHA_SITE_KEY"] = ""
    app.config["CAPTCHA_SECRET_KEY"] = ""

    res = client.get("/login")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")

    assert "challenges.cloudflare.com" not in csp
    assert "hcaptcha.com" not in csp


# ==============================================================================
# 3. Missing Token Enforcement
# ==============================================================================

def test_missing_token_blocks_register(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site_key"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret_key"

    res = client.post(
        "/register",
        data={
            "name": "Bot User",
            "email": "bot@example.com",
            "password": "Password123!",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Please complete the CAPTCHA verification to proceed" in res.data


def test_missing_token_blocks_login(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site_key"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret_key"

    res = client.post(
        "/login",
        data={
            "email": "bot@example.com",
            "password": "Password123!",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Please complete the CAPTCHA verification to proceed" in res.data


def test_missing_token_blocks_forgot_password(client):
    app.config["CAPTCHA_PROVIDER"] = "hcaptcha"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site_key"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret_key"

    res = client.post(
        "/forgot-password",
        data={"email": "victim@example.com"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Please complete the CAPTCHA verification to proceed" in res.data


# ==============================================================================
# 4. Invalid Token Enforcement
# ==============================================================================

def test_invalid_token_blocks_request_with_clear_message(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site_key"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret_key"

    # Mock provider API returning invalid token response
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = json.dumps({
        "success": False,
        "error-codes": ["invalid-input-response"]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.post(
            "/login",
            data={
                "email": "user@example.com",
                "password": "Password123!",
                "cf-turnstile-response": "invalid_fake_token",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert b"CAPTCHA verification failed. Please try again." in res.data


# ==============================================================================
# 5. Valid Token Verification
# ==============================================================================

def test_valid_token_allows_login(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site_key"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret_key"

    # First register user
    create_user("u_valid_01", "Valid User", "valid@example.com", "dummy_hash")

    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = json.dumps({"success": True}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with patch("routes.auth.check_password_hash", return_value=True):
            res = client.post(
                "/login",
                data={
                    "email": "valid@example.com",
                    "password": "Password123!",
                    "cf-turnstile-response": "valid_token_123",
                },
                follow_redirects=True,
            )
            assert res.status_code == 200
            assert b"Login successful" in res.data


def test_hcaptcha_verification_call_format(client):
    app.config["CAPTCHA_PROVIDER"] = "hcaptcha"
    app.config["CAPTCHA_SITE_KEY"] = "hcap_site"
    app.config["CAPTCHA_SECRET_KEY"] = "hcap_secret"

    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = json.dumps({"success": True}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with app.app_context():
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            ok, err = verify_captcha_token("test_hcaptcha_token", remote_ip="192.168.1.50")
            assert ok is True
            assert err is None

            # Verify request parameters
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.full_url == "https://api.hcaptcha.com/siteverify"
            assert req.get_method() == "POST"
            body = req.data.decode("utf-8")
            assert "secret=hcap_secret" in body
            assert "response=test_hcaptcha_token" in body
            assert "remoteip=192.168.1.50" in body


# ==============================================================================
# 6. Provider Down Cases (Fail-Closed vs Fail-Open)
# ==============================================================================

def test_provider_down_fail_closed_by_default(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret"
    app.config["CAPTCHA_FAIL_OPEN"] = False

    # Mock connection error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        res = client.post(
            "/login",
            data={
                "email": "test@example.com",
                "password": "Password123!",
                "cf-turnstile-response": "token123",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert b"Security verification service is temporarily unavailable" in res.data


def test_provider_down_fail_open_when_configured(client, caplog):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret"
    app.config["CAPTCHA_FAIL_OPEN"] = True

    # Register user
    create_user("u_failopen_01", "FailOpen User", "failopen@example.com", "dummy_hash")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        with patch("routes.auth.check_password_hash", return_value=True):
            res = client.post(
                "/login",
                data={
                    "email": "failopen@example.com",
                    "password": "Password123!",
                    "cf-turnstile-response": "token123",
                },
                follow_redirects=True,
            )
            assert res.status_code == 200
            assert b"Login successful" in res.data
            assert "unreachable" in caplog.text or "Failing open" in caplog.text


# ==============================================================================
# 7. Repeated Failed Attempts Threshold
# ==============================================================================

def test_captcha_required_after_repeated_failed_attempts(client):
    app.config["CAPTCHA_PROVIDER"] = "turnstile"
    app.config["CAPTCHA_SITE_KEY"] = "dummy_site"
    app.config["CAPTCHA_SECRET_KEY"] = "dummy_secret"
    app.config["CAPTCHA_ALWAYS_ENFORCE"] = False
    app.config["CAPTCHA_REQUIRE_AFTER_FAILURES"] = 3

    create_user("u_brute_01", "Target User", "target@example.com", "hash_real")

    # Before threshold (0 failures): login without captcha token proceeds to credential check
    res1 = client.post(
        "/login",
        data={"email": "target@example.com", "password": "wrongpassword"},
        follow_redirects=True,
    )
    assert res1.status_code == 200
    assert b"Invalid email or password" in res1.data

    # 2nd failure
    res2 = client.post(
        "/login",
        data={"email": "target@example.com", "password": "wrongpassword2"},
        follow_redirects=True,
    )
    assert res2.status_code == 200
    assert b"Invalid email or password" in res2.data

    # 3rd failure
    res3 = client.post(
        "/login",
        data={"email": "target@example.com", "password": "wrongpassword3"},
        follow_redirects=True,
    )
    assert res3.status_code == 200
    assert b"Invalid email or password" in res3.data

    # 4th attempt without token: MUST now be blocked by CAPTCHA requirement!
    res4 = client.post(
        "/login",
        data={"email": "target@example.com", "password": "wrongpassword4"},
        follow_redirects=True,
    )
    assert res4.status_code == 200
    assert b"Please complete the CAPTCHA verification to proceed" in res4.data
