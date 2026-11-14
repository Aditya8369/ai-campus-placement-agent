"""
Unit tests for Application-Wide Input Validation and Sanitization (#276).
"""

import pytest
from app import app
from utils.input_validator import (
    sanitize_text,
    validate_email,
    validate_string,
    validate_url,
    validate_registration_payload,
    validate_job_application_payload,
    validate_interview_answer_payload,
    ValidationError
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_sanitize_text():
    raw_html = "<script>alert('xss')</script><b>Hello World</b>"
    cleaned = sanitize_text(raw_html, strip_html=True)
    assert "<script>" not in cleaned
    assert "Hello World" in cleaned

    truncated = sanitize_text("abcdefghij", max_len=5)
    assert len(truncated) == 5
    assert truncated == "abcde"


def test_validate_email_valid():
    assert validate_email("student@university.edu") == "student@university.edu"
    assert validate_email("  Test.User+1@Domain.Co  ") == "test.user+1@domain.co"


def test_validate_email_invalid():
    with pytest.raises(ValidationError) as exc:
        validate_email("plainaddress")
    assert "Invalid email address format." in str(exc.value)

    with pytest.raises(ValidationError):
        validate_email("")

    with pytest.raises(ValidationError):
        validate_email("a" * 250 + "@domain.com")


def test_validate_string_length_and_enum():
    res = validate_string("Software Engineer", "role", min_length=2, max_length=50)
    assert res == "Software Engineer"

    with pytest.raises(ValidationError) as exc:
        validate_string("a", "role", min_length=2)
    assert "at least 2 characters" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        validate_string("Too long", "status", allowed_values=["Applied", "Interviewing"])
    assert "Must be one of" in str(exc.value)


def test_validate_url():
    assert validate_url("https://careers.google.com/jobs/123") == "https://careers.google.com/jobs/123"
    with pytest.raises(ValidationError):
        validate_url("javascript:alert(1)", field_name="job_url")
    with pytest.raises(ValidationError):
        validate_url("ftp://fileserver/job.pdf", field_name="job_url")


def test_validate_registration_payload():
    valid_data = {
        "email": "student@college.edu",
        "full_name": "Jane Doe",
        "password": "SecurePassword123!"
    }
    validated = validate_registration_payload(valid_data)
    assert validated["email"] == "student@college.edu"
    assert validated["full_name"] == "Jane Doe"

    invalid_data = {
        "email": "not-an-email",
        "full_name": "",
        "password": "short"
    }
    with pytest.raises(ValidationError) as exc:
        validate_registration_payload(invalid_data)
    field_errors = exc.value.field_errors
    assert "email" in field_errors
    assert "full_name" in field_errors
    assert "password" in field_errors


def test_validate_job_application_payload():
    valid_app = {
        "company_name": "Microsoft",
        "role_title": "Frontend Engineer",
        "status": "Applied",
        "job_url": "https://careers.microsoft.com/123",
        "notes": "Referred by alum."
    }
    validated = validate_job_application_payload(valid_app)
    assert validated["company_name"] == "Microsoft"
    assert validated["status"] == "Applied"

    invalid_app = {
        "company_name": "",
        "role_title": "A",
        "status": "NonExistentStatus",
        "job_url": "invalid-url"
    }
    with pytest.raises(ValidationError) as exc:
        validate_job_application_payload(invalid_app)
    errs = exc.value.field_errors
    assert "company_name" in errs
    assert "role_title" in errs
    assert "status" in errs
    assert "job_url" in errs


def test_api_validate_input_endpoint(client):
    res = client.post(
        "/api/validate/input",
        json={
            "type": "registration",
            "data": {
                "email": "bob@university.edu",
                "full_name": "Bob Smith",
                "password": "StrongPassword99$"
            }
        }
    )
    assert res.status_code == 200
    assert res.get_json()["success"] is True

    # Test rejection endpoint
    res_err = client.post(
        "/api/validate/input",
        json={
            "type": "registration",
            "data": {"email": "invalid", "password": "123"}
        }
    )
    assert res_err.status_code == 422
    data_err = res_err.get_json()
    assert data_err["success"] is False
    assert "field_errors" in data_err
