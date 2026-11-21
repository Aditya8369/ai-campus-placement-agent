"""
Unit and integration tests for Approved College Email Domains and Student College storage (#654).

Acceptance Criteria covered:
1. With ALLOWED_EMAIL_DOMAINS empty, registration works for any domain as before.
2. With domains set, other domains are rejected with a clear message and allowed ones accepted.
3. Matching is case-insensitive (e.g. Student@COLLEGE.EDU matches college.edu).
4. Subdomain emails (e.g. user@dept.college.edu, user@cs.eng.college.edu) work when college.edu is configured.
5. Spoofed partial matches (e.g. user@fake-college.edu, user@college.edu.attacker.com) are rejected.
6. The student's college value is saved, editable, and properly escaped when displayed (XSS prevention).
7. Email domain validation applies to profile email updates, forgot password, and resend verification.
"""

import os
import pytest
import html
from unittest.mock import patch
from flask import current_app

import config
from app import app
from routes import create_app
from utils.database import (
    init_db,
    save_student_profile,
    get_student_profile,
    create_user,
    get_user_by_email,
)
from utils.email_domain_validator import (
    parse_allowed_email_domains,
    extract_email_domain,
    is_email_domain_allowed,
    get_email_domain_error_message,
    get_suggested_colleges,
)


# ==============================================================================
# 1. Pure Unit Tests for Validator Utility
# ==============================================================================

def test_parse_allowed_email_domains():
    # Empty or None cases
    assert parse_allowed_email_domains("") == []
    assert parse_allowed_email_domains(None) == []

    # Comma separation, whitespace, leading @, leading *., mixed case
    raw = " College.EDU , @stanford.edu, *.mit.edu , Harvard.EDU, college.edu "
    parsed = parse_allowed_email_domains(raw)
    assert parsed == ["college.edu", "stanford.edu", "mit.edu", "harvard.edu"]


def test_extract_email_domain():
    assert extract_email_domain("student@college.edu") == "college.edu"
    assert extract_email_domain("User@Dept.COLLEGE.Edu.") == "dept.college.edu"
    assert extract_email_domain("invalid-no-at-sign") is None
    assert extract_email_domain("") is None
    assert extract_email_domain("@domain.com") is None
    assert extract_email_domain("user@") is None


def test_is_email_domain_allowed_when_empty_setting():
    # When allowed_domains is empty/unset, any valid email is allowed
    assert is_email_domain_allowed("student@gmail.com", allowed_domains="") is True
    assert is_email_domain_allowed("user@yahoo.co.uk", allowed_domains=[]) is True
    assert is_email_domain_allowed("candidate@alumni.college.edu", allowed_domains=None) is True
    # Invalid syntax is still rejected
    assert is_email_domain_allowed("notanemail", allowed_domains="") is False


def test_is_email_domain_allowed_exact_and_mixed_case():
    allowed = "college.edu, university.ac.in"
    # Exact matches
    assert is_email_domain_allowed("student@college.edu", allowed_domains=allowed) is True
    assert is_email_domain_allowed("prof@university.ac.in", allowed_domains=allowed) is True

    # Case-insensitive matches
    assert is_email_domain_allowed("STUDENT@COLLEGE.EDU", allowed_domains=allowed) is True
    assert is_email_domain_allowed("Dean@University.Ac.In", allowed_domains=allowed) is True
    assert is_email_domain_allowed("Student@College.Edu", allowed_domains=allowed) is True


def test_is_email_domain_allowed_subdomains():
    allowed = "college.edu"
    # Single level subdomain
    assert is_email_domain_allowed("student@cs.college.edu", allowed_domains=allowed) is True
    assert is_email_domain_allowed("researcher@dept.college.edu", allowed_domains=allowed) is True
    # Multi level subdomain
    assert is_email_domain_allowed("lab@ai.cs.college.edu", allowed_domains=allowed) is True
    # Subdomain with mixed casing
    assert is_email_domain_allowed("User@DEPT.College.EDU", allowed_domains=allowed) is True


def test_is_email_domain_disallowed_and_spoofing():
    allowed = "college.edu"
    # Completely different domain
    assert is_email_domain_allowed("student@gmail.com", allowed_domains=allowed) is False
    assert is_email_domain_allowed("user@othercollege.edu", allowed_domains=allowed) is False

    # Partial match that is not a subdomain
    assert is_email_domain_allowed("user@fake-college.edu", allowed_domains=allowed) is False
    assert is_email_domain_allowed("user@notcollege.edu", allowed_domains=allowed) is False

    # Domain placed in subdomain of attacker domain
    assert is_email_domain_allowed("user@college.edu.attacker.com", allowed_domains=allowed) is False
    assert is_email_domain_allowed("user@college.edu.phishing.net", allowed_domains=allowed) is False


def test_get_email_domain_error_message():
    msg = get_email_domain_error_message("college.edu, univ.ac.in")
    assert "@college.edu" in msg
    assert "@univ.ac.in" in msg
    assert "restricted to approved college email domains" in msg


def test_get_suggested_colleges():
    # Known domains map to official names
    suggestions = get_suggested_colleges("stanford.edu, iitb.ac.in, mycollege.edu")
    assert "Stanford University" in suggestions
    assert "IIT Bombay" in suggestions
    # Unknown domain derives title-cased name
    assert any("Mycollege" in s for s in suggestions)


# ==============================================================================
# 2. Database Student Profile College Storage & Migration Tests
# ==============================================================================

def test_database_profile_college_save_and_retrieve(tmp_path):
    test_db = tmp_path / "test_profile_college.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db(str(test_db))
        student_id = "test_student_college_001"

        # Save profile with college
        saved = save_student_profile(
            student_id=student_id,
            full_name="Jordan Lee",
            email="jordan@engineering.college.edu",
            college="College of Engineering",
            db_path=str(test_db),
        )
        assert saved.get("college") == "College of Engineering"

        # Retrieve profile
        retrieved = get_student_profile(student_id, db_path=str(test_db))
        assert retrieved.get("college") == "College of Engineering"
        assert retrieved.get("full_name") == "Jordan Lee"

        # Update college
        updated = save_student_profile(
            student_id=student_id,
            college="Institute of Advanced Technology",
            db_path=str(test_db),
        )
        assert updated.get("college") == "Institute of Advanced Technology"
        retrieved2 = get_student_profile(student_id, db_path=str(test_db))
        assert retrieved2.get("college") == "Institute of Advanced Technology"


# ==============================================================================
# 3. Web Client & Registration Integration Tests
# ==============================================================================

@pytest.fixture
def auth_test_client(tmp_path):
    test_db = tmp_path / "test_auth_domains.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db(str(test_db))
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["TESTING_BYPASS_VERIFICATION"] = True
        with app.test_client() as client:
            yield client


def test_registration_allowed_when_no_domains_configured(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = ""

    # Any domain should succeed
    res = auth_test_client.post(
        "/register",
        data={
            "name": "General Student",
            "email": "general@gmail.com",
            "password": "Password123!",
            "college": "Global University",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration successful" in res.data

    user = get_user_by_email("general@gmail.com")
    assert user is not None
    prof = get_student_profile(user["id"])
    assert prof.get("college") == "Global University"


def test_registration_blocked_when_domain_disallowed(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu, polytech.ac.in"

    # Attempt registration with Gmail
    res = auth_test_client.post(
        "/register",
        data={
            "name": "Unauthorized User",
            "email": "intruder@gmail.com",
            "password": "Password123!",
            "college": "Campus College",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration is restricted to approved college email domains" in res.data
    assert b"@campus.edu" in res.data

    user = get_user_by_email("intruder@gmail.com")
    assert user is None


def test_registration_accepted_with_mixed_case_and_subdomain(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu"

    # Register with mixed case and department subdomain
    res = auth_test_client.post(
        "/register",
        data={
            "name": "Alice Subdomain",
            "email": "Alice@CS.Campus.EDU",
            "password": "StrongPassword123!",
            "college": "Campus College",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration successful" in res.data

    user = get_user_by_email("alice@cs.campus.edu")
    assert user is not None
    prof = get_student_profile(user["id"])
    assert prof.get("college") == "Campus College"


# ==============================================================================
# 4. Profile View College Storage, Update & XSS Escaping Tests
# ==============================================================================

def test_profile_college_update_and_xss_escaping(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu"
    student_id = "student_profile_test_xss"

    with auth_test_client.session_transaction() as sess:
        sess["user_id"] = student_id
        sess["user_name"] = "XSS Test Student"

    # 1. Update profile with college
    res = auth_test_client.post(
        "/profile",
        data={
            "full_name": "Test Student",
            "email": "test@campus.edu",
            "college": "State Technical University",
            "phone": "+1 555 123 4567",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Profile information updated successfully" in res.data
    assert b"State Technical University" in res.data

    # 2. Update with XSS payload in college field
    xss_payload = '<script>alert("xss")</script>'
    res2 = auth_test_client.post(
        "/profile",
        data={
            "full_name": "Test Student",
            "email": "test@campus.edu",
            "college": xss_payload,
        },
        follow_redirects=True,
    )
    assert res2.status_code == 200
    # Must NOT render unescaped raw <script> tag
    assert b"<script>alert(\"xss\")</script>" not in res2.data
    # Must render safely HTML-escaped
    assert b"&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;" in res2.data or b"&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in res2.data


def test_profile_email_change_domain_restriction(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu"
    student_id = "student_profile_email_change"

    with auth_test_client.session_transaction() as sess:
        sess["user_id"] = student_id
        sess["user_name"] = "Email Change Student"

    # Try changing email to an unapproved domain
    res = auth_test_client.post(
        "/profile",
        data={
            "full_name": "Email Change Student",
            "email": "change@personal-mail.com",
            "college": "Campus Institute",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration is restricted to approved college email domains" in res.data

    # Change email to approved subdomain
    res_ok = auth_test_client.post(
        "/profile",
        data={
            "full_name": "Email Change Student",
            "email": "student@dept.campus.edu",
            "college": "Campus Institute",
        },
        follow_redirects=True,
    )
    assert res_ok.status_code == 200
    assert b"Profile information updated successfully" in res_ok.data


# ==============================================================================
# 5. Forgot Password & Resend Verification Restrictions
# ==============================================================================

def test_forgot_password_domain_restriction(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu"

    # Disallowed email should trigger domain error
    res = auth_test_client.post(
        "/forgot-password",
        data={"email": "attacker@external.org"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration is restricted to approved college email domains" in res.data


def test_resend_verification_domain_restriction(auth_test_client):
    app.config["ALLOWED_EMAIL_DOMAINS"] = "campus.edu"

    # Disallowed email should trigger domain error
    res = auth_test_client.post(
        "/resend-verification",
        data={"email": "random@gmail.com"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Registration is restricted to approved college email domains" in res.data
