"""
Unit Tests for API Request Replay, Idempotency, and Expiration (#Task).
=======================================================================
Tests cover:
1. Safe payload sanitization (stripping passwords, tokens, secrets, long binaries).
2. Deterministic idempotency key calculation and duplicate submission prevention.
3. Retry record creation, status tracking, and attempt limits.
4. Short-period record expiration (TTL window and expired rejection).
5. Atomic replay claim (blocking concurrent/duplicate replay submissions).
6. Replay completion and outcome recording.
7. User record cancellation / dismissal.
8. REST API endpoints integration for retry records.
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app import app
from config import Config
from utils.api_replay_service import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_RECORD_TTL_SECONDS,
    begin_replay,
    cancel_retry_record,
    cleanup_expired_retries,
    complete_replay,
    generate_idempotency_key,
    get_retry_record,
    list_retry_records,
    sanitize_operation_payload,
    store_retry_record,
)


@pytest.fixture
def isolated_db(monkeypatch):
    """Provides an isolated temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_api_replay.db"
        monkeypatch.setattr(Config, "DATABASE_PATH", str(db_path))

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_retry_records (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default_student',
                operation_type TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                http_method TEXT NOT NULL DEFAULT 'POST',
                payload_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'failed',
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                last_response_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        yield str(db_path)


class TestSafePayloadSanitization:
    """Verifies that sensitive data and tokens are completely stripped from stored payloads."""

    def test_strip_passwords_and_tokens(self):
        unsafe_payload = {
            "username": "candidate_1",
            "password": "MySuperSecretPassword123!",
            "confirm_password": "MySuperSecretPassword123!",
            "csrf_token": "csrf-secret-9999",
            "auth_token": "bearer-jwt-token-xyz",
            "target_role": "Backend Engineer",
            "company": "Google",
        }
        cleaned = sanitize_operation_payload(unsafe_payload)
        assert cleaned["username"] == "candidate_1"
        assert cleaned["password"] == "[REDACTED]"
        assert cleaned["confirm_password"] == "[REDACTED]"
        assert cleaned["csrf_token"] == "[REDACTED]"
        assert cleaned["auth_token"] == "[REDACTED]"
        assert cleaned["target_role"] == "Backend Engineer"
        assert cleaned["company"] == "Google"

    def test_truncate_oversized_binary_strings(self):
        huge_base64 = "data:application/pdf;base64," + ("A" * 6000)
        payload = {"filename": "resume.pdf", "file_data": huge_base64}
        cleaned = sanitize_operation_payload(payload)
        assert cleaned["filename"] == "resume.pdf"
        assert "[TRUNCATED_PAYLOAD_" in cleaned["file_data"]


class TestIdempotencyKey:
    """Verifies deterministic idempotency calculation."""

    def test_deterministic_hash_for_same_operation(self):
        key1 = generate_idempotency_key("user_1", "/api/test", "POST", {"a": 1, "b": 2})
        key2 = generate_idempotency_key("user_1", "/api/test", "POST", {"b": 2, "a": 1})
        assert key1 == key2

    def test_different_hash_for_different_user_or_payload(self):
        key1 = generate_idempotency_key("user_1", "/api/test", "POST", {"a": 1})
        key2 = generate_idempotency_key("user_2", "/api/test", "POST", {"a": 1})
        key3 = generate_idempotency_key("user_1", "/api/test", "POST", {"a": 2})
        assert key1 != key2
        assert key1 != key3

    def test_explicit_key_precedence(self):
        custom_key = "client-unique-idem-key-12345"
        key = generate_idempotency_key("user_1", "/api/test", "POST", {}, explicit_key=custom_key)
        assert key == custom_key


class TestRetryRecordLifecycle:
    """Verifies record creation, status, and atomic replay claim."""

    def test_store_and_get_retry_record(self, isolated_db):
        rec = store_retry_record(
            user_id="student_123",
            operation_type="section_retry",
            endpoint="/api/analysis/101/retry-section",
            http_method="POST",
            payload={"section": "roadmap"},
            error_message="Gemini AI timeout",
            ttl_seconds=900,
            db_path=isolated_db,
        )

        assert rec["id"].startswith("retry_")
        assert rec["status"] == "failed"
        assert rec["can_replay"] is True
        assert rec["retry_count"] == 0

        fetched = get_retry_record(rec["id"], user_id="student_123", db_path=isolated_db)
        assert fetched is not None
        assert fetched["endpoint"] == "/api/analysis/101/retry-section"
        assert fetched["payload"]["section"] == "roadmap"
        assert fetched["is_expired"] is False
        assert fetched["seconds_until_expiry"] > 0

    def test_prevent_duplicate_submissions_while_replaying(self, isolated_db):
        rec = store_retry_record(
            user_id="student_123",
            operation_type="analysis_run",
            endpoint="/api/analysis/start",
            payload={"company": "Amazon"},
            db_path=isolated_db,
        )

        # First replay claim must succeed
        can_replay, err, claim1 = begin_replay(rec["id"], user_id="student_123", db_path=isolated_db)
        assert can_replay is True
        assert err is None
        assert claim1["status"] == "replaying"
        assert claim1["retry_count"] == 1

        # Second concurrent replay claim must be rejected
        can_replay_2, err_2, claim2 = begin_replay(rec["id"], user_id="student_123", db_path=isolated_db)
        assert can_replay_2 is False
        assert "currently being replayed" in err_2
        assert claim2 is None

    def test_prevent_resubmission_after_success(self, isolated_db):
        rec = store_retry_record(
            user_id="student_123",
            operation_type="analysis_run",
            endpoint="/api/analysis/start",
            db_path=isolated_db,
        )

        begin_replay(rec["id"], db_path=isolated_db)
        complete_replay(rec["id"], success=True, result_payload={"analysis_id": "aid_999"}, db_path=isolated_db)

        # Attempting to replay a succeeded record must be rejected
        can_replay, err, _ = begin_replay(rec["id"], db_path=isolated_db)
        assert can_replay is False
        assert "already succeeded" in err

    def test_exhaust_max_retries(self, isolated_db):
        rec = store_retry_record(
            user_id="student_123",
            operation_type="interview_eval",
            endpoint="/api/interview/submit",
            max_retries=2,
            db_path=isolated_db,
        )

        # Attempt 1
        begin_replay(rec["id"], db_path=isolated_db)
        complete_replay(rec["id"], success=False, error_message="Fail 1", db_path=isolated_db)

        # Attempt 2
        begin_replay(rec["id"], db_path=isolated_db)
        complete_replay(rec["id"], success=False, error_message="Fail 2", db_path=isolated_db)

        # Attempt 3: rejected because max retries reached
        can_replay, err, _ = begin_replay(rec["id"], db_path=isolated_db)
        assert can_replay is False
        assert "Maximum retry attempts" in err


class TestShortPeriodExpiration:
    """Verifies that retry records strictly expire after a short period."""

    def test_expired_record_rejection(self, isolated_db):
        # Store a record with 1 second TTL
        rec = store_retry_record(
            user_id="student_123",
            operation_type="section_retry",
            endpoint="/api/test",
            ttl_seconds=1,
            db_path=isolated_db,
        )

        # Manually force expiration in DB to simulate passage of time
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        conn = sqlite3.connect(isolated_db)
        conn.execute("UPDATE api_retry_records SET expires_at = ? WHERE id = ?", (past_iso, rec["id"]))
        conn.commit()
        conn.close()

        # Check get_retry_record reflects expiration
        fetched = get_retry_record(rec["id"], db_path=isolated_db)
        assert fetched["status"] == "expired"
        assert fetched["is_expired"] is True
        assert fetched["can_replay"] is False

        # Attempt to replay must be rejected
        can_replay, err, _ = begin_replay(rec["id"], db_path=isolated_db)
        assert can_replay is False
        assert "expired" in err

    def test_cleanup_expired_retries_utility(self, isolated_db):
        rec = store_retry_record(user_id="student_123", operation_type="test", endpoint="/api/test", db_path=isolated_db)
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

        conn = sqlite3.connect(isolated_db)
        conn.execute("UPDATE api_retry_records SET expires_at = ? WHERE id = ?", (past_iso, rec["id"]))
        conn.commit()
        conn.close()

        updated_count = cleanup_expired_retries(db_path=isolated_db)
        assert updated_count >= 1

        fetched = get_retry_record(rec["id"], db_path=isolated_db)
        assert fetched["status"] == "expired"


class TestCancellation:
    """Verifies user can dismiss or cancel retry records."""

    def test_cancel_active_retry_record(self, isolated_db):
        rec = store_retry_record(user_id="student_123", operation_type="test", endpoint="/api/test", db_path=isolated_db)
        cancelled = cancel_retry_record(rec["id"], user_id="student_123", db_path=isolated_db)
        assert cancelled is True

        fetched = get_retry_record(rec["id"], db_path=isolated_db)
        assert fetched["status"] == "cancelled"
        assert fetched["can_replay"] is False


class TestApiEndpointsIntegration:
    """Verifies Flask REST endpoints for retry records."""

    @pytest.fixture
    def client(self, isolated_db):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            yield c

    def test_create_and_list_retry_records_endpoint(self, client):
        # Create record via POST /api/retry-records
        resp = client.post("/api/retry-records", json={
            "operation_type": "section_retry",
            "endpoint": "/api/analysis/test-id/retry-section",
            "http_method": "POST",
            "payload": {"section": "roadmap"},
            "error_message": "Network dropped during AI call",
            "ttl_seconds": 600,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["success"] is True
        rec_id = data["record"]["id"]

        # List records via GET /api/retry-records
        list_resp = client.get("/api/retry-records")
        assert list_resp.status_code == 200
        list_data = list_resp.get_json()
        assert list_data["success"] is True
        assert any(r["id"] == rec_id for r in list_data["records"])

        # Fetch detail via GET /api/retry-records/<id>
        detail_resp = client.get(f"/api/retry-records/{rec_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.get_json()
        assert detail_data["record"]["id"] == rec_id
        assert detail_data["record"]["status"] == "failed"

        # Dismiss via DELETE /api/retry-records/<id>
        del_resp = client.delete(f"/api/retry-records/{rec_id}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["success"] is True
