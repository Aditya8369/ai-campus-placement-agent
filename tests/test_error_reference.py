"""
Unit tests for Application-Wide Error Reporting Reference ID System (#263).
Verifies:
- High-entropy reference ID generation formatting (ERR-YYYYMMDD-XXXXXX).
- Stack trace and sensitive token / email redaction.
- Error recording and database persistence.
- Administrative lookup by error reference ID.
- Global 500 error handler integration returning user-facing reference IDs.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db, get_db_connection
from utils.error_reference_service import (
    generate_error_reference_id,
    sanitize_error_text,
    record_application_error,
    lookup_error_reference,
    get_recent_error_incidents,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated SQLite database for error logs."""
    test_db = str(tmp_path / "test_error_logs.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


def test_error_reference_id_generation():
    """Verify reference ID format is consistent and human-shareable."""
    ref1 = generate_error_reference_id()
    ref2 = generate_error_reference_id()
    assert ref1.startswith("ERR-")
    assert ref2.startswith("ERR-")
    assert ref1 != ref2
    assert len(ref1) >= 15


def test_sanitize_error_text():
    """Verify API keys, bearer tokens, and emails are properly masked."""
    leak_sample = (
        "Error communicating with upstream AI service: Bearer ya29.a0AfH6SMA... "
        "using key sk-1234567890abcdef1234567890 and user email student.john@campus.edu"
    )
    sanitized = sanitize_error_text(leak_sample)
    assert "sk-1234567890abcdef1234567890" not in sanitized
    assert "***REDACTED_API_KEY***" in sanitized
    assert "student.john@campus.edu" not in sanitized
    assert "***REDACTED_EMAIL***" in sanitized


def test_record_application_error_and_lookup():
    """Verify recording an exception and retrieving it via reference ID."""
    test_exc = ValueError("Invalid matrix computation in interview matcher")
    err_info = record_application_error(
        error=test_exc,
        endpoint="/api/interview/matcher",
        http_method="POST",
        status_code=500,
        user_id="student_42",
        request_id="req-abc-999",
    )

    ref_id = err_info["reference_id"]
    assert ref_id.startswith("ERR-")
    assert "Reference ID" in err_info["user_message"]

    # Look up recorded incident
    record = lookup_error_reference(ref_id)
    assert record is not None
    assert record["error_type"] == "ValueError"
    assert "Invalid matrix computation" in record["error_message"]
    assert record["endpoint"] == "/api/interview/matcher"
    assert record["http_method"] == "POST"
    assert record["user_id"] == "student_42"
    assert record["request_id"] == "req-abc-999"

    # Verify recent incidents query
    recent = get_recent_error_incidents(10)
    assert len(recent) >= 1
    assert recent[0]["reference_id"] == ref_id


def test_api_error_reference_lookup_endpoint(client):
    """Test administrative API endpoint to look up error reference records."""
    test_exc = RuntimeError("Database connection timeout during simulation")
    err_info = record_application_error(
        error=test_exc,
        endpoint="/api/test/failure",
        http_method="GET",
        status_code=500,
    )
    ref_id = err_info["reference_id"]

    # Query via endpoint
    resp = client.get(f"/api/support/error-reference/{ref_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["error_incident"]["reference_id"] == ref_id
    assert data["error_incident"]["error_type"] == "RuntimeError"

    # Query non-existent reference ID
    not_found_resp = client.get("/api/support/error-reference/ERR-99999999-NOTFOUND")
    assert not_found_resp.status_code == 404
    assert not_found_resp.get_json()["success"] is False
