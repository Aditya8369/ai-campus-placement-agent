"""
tests/test_password_security.py
Unit and integration tests for Breached and Weak Password Rejection (#850).

Verifies:
- Minimum length requirement (>= 8 characters).
- Contextual rejection (matching name, email, or email local part).
- Common password blocklist rejection.
- HaveIBeenPwned range API k-anonymity (only 5-character prefix sent).
- Range API mock detection for breached passwords.
- Fail-open resilience when the external API times out or throws errors.
- Route-level validation in registration and password changes.
"""

import hashlib
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from utils.password_security import (
    COMMON_PASSWORDS,
    check_pwned_password,
    validate_password_security,
)


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def test_password_too_short():
    """Verify passwords shorter than 8 characters are rejected."""
    valid, msg = validate_password_security("Short1!")
    assert not valid
    assert "at least 8 characters" in msg


def test_password_matching_email():
    """Verify passwords matching email or email local part are rejected."""
    email = "student@university.edu"
    # Exact email match
    valid, msg = validate_password_security("student@university.edu", email=email, check_pwned=False)
    assert not valid
    assert "cannot match your name or email" in msg

    # Case-insensitive email match
    valid, msg = validate_password_security("STUDENT@UNIVERSITY.EDU", email=email, check_pwned=False)
    assert not valid
    assert "cannot match your name or email" in msg

    # Local part match
    valid_long_local, msg_local = validate_password_security("student123", email="student123@uni.edu", check_pwned=False)
    assert not valid_long_local
    assert "cannot match your name or email" in msg_local


def test_password_matching_name():
    """Verify passwords matching user name or components are rejected."""
    name = "Alexander Hamilton"
    # Exact name match
    valid, msg = validate_password_security("alexander hamilton", name=name, check_pwned=False)
    assert not valid
    assert "cannot match your name or email" in msg

    # Name without spaces
    valid, msg = validate_password_security("AlexanderHamilton", name=name, check_pwned=False)
    assert not valid
    assert "cannot match your name or email" in msg

    # First name component
    valid, msg = validate_password_security("Alexander", name=name, check_pwned=False)
    assert not valid
    assert "cannot match your name or email" in msg


def test_common_passwords_rejected():
    """Verify easily guessed common passwords are systematically rejected."""
    assert "12345678" in COMMON_PASSWORDS
    assert "password123" in COMMON_PASSWORDS
    test_cases = ["12345678", "password123", "qwertyuiop", "admin123", "welcome123"]
    for pwd in test_cases:
        valid, msg = validate_password_security(pwd, check_pwned=False)
        assert not valid, f"Expected {pwd} to be rejected"
        assert "too common and easily guessed" in msg


def test_check_pwned_password_empty():
    """Verify empty or None candidate password returns False immediately without API call."""
    assert check_pwned_password("") is False


def test_pwned_password_k_anonymity_and_detection():
    """
    Verify that only the 5-character SHA-1 prefix is transmitted to the range API,
    and a breached suffix in the response causes rejection.
    """
    test_pwd = "P@ssword123Secure!"
    sha1 = hashlib.sha1(test_pwd.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]

    mock_body = f"0018A45C4D1DEF81644B54AB7F969B88D65:1\n{suffix}:42\n00D4F6E8FA6EEC4250F657B18082F231818:5\n"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_body.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        valid, msg = validate_password_security(test_pwd, check_pwned=True)

        assert not valid
        assert "known data breach" in msg

        # Assert only the 5-char prefix is in the URL requested
        assert mock_urlopen.call_count == 1
        call_req = mock_urlopen.call_args[0][0]
        assert call_req.full_url == f"https://api.pwnedpasswords.com/range/{prefix}"
        assert test_pwd not in call_req.full_url
        assert suffix not in call_req.full_url


def test_clean_password_passes_hibp_check():
    """Verify that a safe password not found in the breached range passes validation."""
    test_pwd = "Unique-Very-Secret-Key-2026!#"
    sha1 = hashlib.sha1(test_pwd.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]

    # Return entries that do not include the suffix
    mock_body = "0018A45C4D1DEF81644B54AB7F969B88D65:1\n00D4F6E8FA6EEC4250F657B18082F231818:5\n"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_body.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        valid, msg = validate_password_security(
            test_pwd,
            email="student@uni.edu",
            name="Alice Smith",
            check_pwned=True,
        )

        assert valid
        assert msg is None
        assert mock_urlopen.call_count == 1
        call_req = mock_urlopen.call_args[0][0]
        assert call_req.full_url == f"https://api.pwnedpasswords.com/range/{prefix}"


def test_pwned_api_failure_fails_open():
    """Verify that network, timeout, or HTTP errors do NOT block user registration/updates."""
    test_pwd = "ValidPassword2026!@"

    # 1. URLError / Network down
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        valid, msg = validate_password_security(test_pwd, check_pwned=True)
        assert valid
        assert msg is None

    # 2. Timeout error
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        valid, msg = validate_password_security(test_pwd, check_pwned=True)
        assert valid
        assert msg is None

    # 3. HTTP 500 error
    mock_500 = MagicMock()
    mock_500.status = 500
    mock_500.read.return_value = b"Internal Server Error"
    mock_500.__enter__.return_value = mock_500
    mock_500.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_500):
        valid, msg = validate_password_security(test_pwd, check_pwned=True)
        assert valid
        assert msg is None


def test_register_route_rejects_common_password(client):
    """Verify /register route rejects common passwords with an informative message."""
    res = client.post(
        "/register",
        data={
            "name": "Testing Student",
            "email": "unique_student_123@uni.edu",
            "password": "password123",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Password is too common and easily guessed" in res.data


def test_register_route_rejects_breached_password(client):
    """Verify /register route rejects passwords flagged as breached by the range API."""
    with patch("utils.password_security.check_pwned_password", return_value=True):
        res = client.post(
            "/register",
            data={
                "name": "Testing Student",
                "email": "unique_student_456@uni.edu",
                "password": "BreachedPassword123!",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert b"known data breach" in res.data


def test_account_change_password_route_rejects_weak_password(client):
    """Verify /account/change-password endpoint rejects weak or common passwords."""
    with client.session_transaction() as sess:
        sess["user_id"] = "test-user-id"
        sess["user_role"] = "student"
        sess["user_email"] = "student@uni.edu"

    with patch("routes.auth.get_user_by_id", return_value={"id": "test-user-id", "email": "student@uni.edu", "name": "Student", "password_hash": "dummy"}), \
         patch("routes.auth.check_password_hash", return_value=True):
        res = client.post(
            "/account/change-password",
            json={
                "current_password": "OldPassword123!",
                "new_password": "admin123",
                "confirm_password": "admin123",
            },
        )
        assert res.status_code == 400
        data = res.get_json()
        assert not data["success"]
        assert "too common" in data["error"]
