"""
API Request Replay & Failed Operation Service.
==============================================
Provides safe storage, idempotency, duplicate submission prevention,
and replay capabilities for failed operations and API requests:

1. Safe Retry Record Storage:
   - Sanitizes and strips sensitive authentication tokens, passwords, and secrets.
   - Persists operation details with endpoints, methods, and safe payloads.

2. Duplicate Submission Prevention:
   - Uses unique idempotency keys to deduplicate concurrent or repeated requests.
   - Enforces atomic state transitions (preventing double replay when 'replaying').

3. Short-Period Expiration:
   - Attaches strict TTL expiration timestamps (default: 15 minutes / 900s).
   - Dynamically expires stale retry records and rejects expired re-submissions.

4. UI Retry Status Visibility:
   - Exposes status indicators ('failed', 'replaying', 'succeeded', 'expired', 'exhausted').
   - Tracks attempt counts and time remaining before record expiry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from config import Config
from db.connection import get_connection

logger = logging.getLogger(__name__)

# Default time-to-live for a retry record (15 minutes)
DEFAULT_RETRY_RECORD_TTL_SECONDS = 900
DEFAULT_MAX_RETRIES = 3

# Field names that must be scrubbed from stored payloads for privacy & security
SENSITIVE_FIELD_NAMES = frozenset({
    "password",
    "confirm_password",
    "current_password",
    "new_password",
    "token",
    "auth_token",
    "csrf_token",
    "secret",
    "secret_key",
    "api_key",
    "session",
    "session_token",
    "authorization",
    "cookie",
    "credit_card",
    "cvv",
})


def sanitize_operation_payload(data: Any, max_string_len: int = 1000) -> Any:
    """
    Recursively strips sensitive authentication parameters and truncates
    enormous binary payloads (e.g. raw file base64 data) for safe persistence.

    Args:
        data: Arbitrary Python structure (dict, list, primitive).
        max_string_len: Threshold above which long string values are summarized.

    Returns:
        Scrubbed, safe data structure.
    """
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for key, val in data.items():
            key_lower = str(key).lower()
            if key_lower in SENSITIVE_FIELD_NAMES or any(s in key_lower for s in ("password", "csrf", "secret")):
                cleaned[key] = "[REDACTED]"
            elif isinstance(val, (dict, list)):
                cleaned[key] = sanitize_operation_payload(val, max_string_len)
            elif isinstance(val, str) and len(val) > max_string_len and ("base64" in val[:50] or len(val) > 5000):
                cleaned[key] = f"[TRUNCATED_PAYLOAD_{len(val)}_BYTES]"
            else:
                cleaned[key] = val
        return cleaned

    if isinstance(data, list):
        return [sanitize_operation_payload(item, max_string_len) for item in data]

    return data


def generate_idempotency_key(
    user_id: str,
    endpoint: str,
    method: str,
    payload: Any,
    explicit_key: Optional[str] = None,
) -> str:
    """
    Computes a deterministic idempotency key for an operation to prevent duplicate submissions.

    Args:
        user_id: Identifier of the student/user.
        endpoint: API route endpoint.
        method: HTTP method (e.g. POST).
        payload: Request payload dictionary or string.
        explicit_key: Optional client-provided idempotency key.

    Returns:
        Hex-encoded SHA256 idempotency key string.
    """
    if explicit_key and str(explicit_key).strip():
        return str(explicit_key).strip()

    serialized_payload = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)
    raw_hash_input = f"{user_id.strip()}:{method.strip().upper()}:{endpoint.strip()}:{serialized_payload}"
    return hashlib.sha256(raw_hash_input.encode("utf-8")).hexdigest()


def _ensure_tables_exist(cursor: sqlite3.Cursor) -> None:
    """Ensures api_retry_records table exists even in dynamic test temp databases."""
    cursor.execute("""
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_retry_records_user ON api_retry_records (user_id, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_retry_records_expires ON api_retry_records (expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_retry_records_idempotency ON api_retry_records (idempotency_key)")


def _format_iso(dt_val: datetime) -> str:
    """Formats a datetime as UTC ISO 8601 string."""
    if dt_val.tzinfo is None:
        dt_val = dt_val.replace(tzinfo=timezone.utc)
    return dt_val.astimezone(timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """Safely parses an ISO or SQLite timestamp into a UTC datetime."""
    try:
        # Replace space with T if SQLite CURRENT_TIMESTAMP format
        cleaned = iso_str.replace(" ", "T")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def store_retry_record(
    user_id: str,
    operation_type: str,
    endpoint: str,
    http_method: str = "POST",
    payload: Optional[Dict[str, Any]] = None,
    error_message: str = "",
    idempotency_key: Optional[str] = None,
    ttl_seconds: int = DEFAULT_RETRY_RECORD_TTL_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stores a sanitized retry record for a failed API operation.
    If an active, unexpired record with the exact same idempotency key already exists:
    - If status is 'failed' or 'pending', refreshes error message and expiration.
    - If status is 'replaying', returns the existing record (preventing duplicate submission).

    Args:
        user_id: Student/User ID.
        operation_type: Human-readable category (e.g. 'section_retry', 'analysis_run').
        endpoint: API endpoint URL.
        http_method: HTTP verb.
        payload: Operation parameters / body.
        error_message: Summary of the error encountered.
        idempotency_key: Optional unique key; generated if omitted.
        ttl_seconds: Seconds until expiration (default: 900s / 15m).
        max_retries: Maximum permitted replay attempts (default: 3).
        db_path: Optional database path override.

    Returns:
        Dictionary representing the persisted retry record.
    """
    safe_user_id = (user_id or "default_student").strip()
    safe_payload = sanitize_operation_payload(payload or {})
    idem_key = generate_idempotency_key(safe_user_id, endpoint, http_method, safe_payload, idempotency_key)
    now_utc = datetime.now(timezone.utc)
    expires_at_utc = now_utc + timedelta(seconds=max(ttl_seconds, 60))

    payload_json = json.dumps(safe_payload, ensure_ascii=False)
    now_iso = _format_iso(now_utc)
    expires_iso = _format_iso(expires_at_utc)

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        # Check for an existing record with the same idempotency key
        cursor.execute(
            "SELECT * FROM api_retry_records WHERE idempotency_key = ?",
            (idem_key,)
        )
        existing = cursor.fetchone()

        if existing:
            rec = dict(existing)
            rec_expires = _parse_iso(rec["expires_at"])
            # If expired, we can reset and reuse the slot
            if now_utc > rec_expires and rec["status"] != "succeeded":
                cursor.execute("""
                    UPDATE api_retry_records
                    SET status = 'failed',
                        error_message = ?,
                        retry_count = 0,
                        updated_at = ?,
                        expires_at = ?
                    WHERE id = ?
                """, (error_message, now_iso, expires_iso, rec["id"]))
                conn.commit()
                rec["status"] = "failed"
                rec["error_message"] = error_message
                rec["expires_at"] = expires_iso
                rec["retry_count"] = 0
                return rec

            # If currently replaying, return immediately to block duplicate submission
            if rec["status"] == "replaying":
                return rec

            # If previously failed/pending, update error message and refresh expires_at
            if rec["status"] in ("failed", "pending"):
                cursor.execute("""
                    UPDATE api_retry_records
                    SET error_message = ?,
                        updated_at = ?,
                        expires_at = ?
                    WHERE id = ?
                """, (error_message, now_iso, expires_iso, rec["id"]))
                conn.commit()
                rec["error_message"] = error_message
                rec["expires_at"] = expires_iso
                rec["updated_at"] = now_iso
                return rec

            # If already succeeded, return existing record
            return rec

        # Create new retry record
        record_id = f"retry_{uuid.uuid4().hex[:12]}"
        cursor.execute("""
            INSERT INTO api_retry_records (
                id, user_id, operation_type, endpoint, http_method,
                payload_json, idempotency_key, status, error_message,
                retry_count, max_retries, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?, 0, ?, ?, ?, ?)
        """, (
            record_id, safe_user_id, operation_type, endpoint, http_method.upper(),
            payload_json, idem_key, error_message, max_retries,
            now_iso, now_iso, expires_iso
        ))
        conn.commit()

        return {
            "id": record_id,
            "user_id": safe_user_id,
            "operation_type": operation_type,
            "endpoint": endpoint,
            "http_method": http_method.upper(),
            "payload": safe_payload,
            "idempotency_key": idem_key,
            "status": "failed",
            "error_message": error_message,
            "retry_count": 0,
            "max_retries": max_retries,
            "created_at": now_iso,
            "updated_at": now_iso,
            "expires_at": expires_iso,
            "seconds_until_expiry": int((expires_at_utc - now_utc).total_seconds()),
            "can_replay": True,
        }
    finally:
        conn.close()


def get_retry_record(
    record_id: str,
    user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetches a retry record by ID, dynamically evaluating expiration.

    Args:
        record_id: Unique record ID.
        user_id: Optional student/user authorization verification.
        db_path: Optional database path override.

    Returns:
        Enriched record dictionary or None if not found or unauthorized.
    """
    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        cursor.execute("SELECT * FROM api_retry_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return None

        rec = dict(row)

        # Authorization check if user_id supplied
        if user_id and rec["user_id"] != user_id and rec["user_id"] != "default_student":
            return None

        # Parse JSON fields safely
        try:
            rec["payload"] = json.loads(rec.get("payload_json") or "{}")
        except Exception:
            rec["payload"] = {}

        try:
            rec["last_response"] = json.loads(rec.get("last_response_json") or "{}") if rec.get("last_response_json") else None
        except Exception:
            rec["last_response"] = None

        now_utc = datetime.now(timezone.utc)
        expires_at_utc = _parse_iso(rec["expires_at"])
        is_expired = now_utc > expires_at_utc
        seconds_left = max(0, int((expires_at_utc - now_utc).total_seconds()))

        # Update status if expired while pending or failed
        if is_expired and rec["status"] in ("failed", "pending"):
            cursor.execute(
                "UPDATE api_retry_records SET status = 'expired', updated_at = ? WHERE id = ?",
                (_format_iso(now_utc), record_id)
            )
            conn.commit()
            rec["status"] = "expired"

        retries_left = max(0, rec["max_retries"] - rec["retry_count"])
        rec["is_expired"] = is_expired
        rec["seconds_until_expiry"] = seconds_left
        rec["retries_left"] = retries_left
        rec["can_replay"] = (
            rec["status"] in ("failed", "pending")
            and not is_expired
            and retries_left > 0
        )

        return rec
    finally:
        conn.close()


def list_retry_records(
    user_id: str,
    include_expired: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lists retry records for a student/user, sorted by created_at DESC.

    Args:
        user_id: Student identifier.
        include_expired: Whether to include expired/succeeded/cancelled records.
        db_path: Optional database path override.

    Returns:
        List of enriched retry record dictionaries.
    """
    cleanup_expired_retries(db_path)

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        if include_expired:
            cursor.execute("""
                SELECT * FROM api_retry_records
                WHERE user_id = ? OR user_id = 'default_student'
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT * FROM api_retry_records
                WHERE (user_id = ? OR user_id = 'default_student')
                  AND status IN ('failed', 'pending', 'replaying')
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))

        rows = cursor.fetchall()
        records: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        for row in rows:
            rec = dict(row)
            try:
                rec["payload"] = json.loads(rec.get("payload_json") or "{}")
            except Exception:
                rec["payload"] = {}

            expires_at_utc = _parse_iso(rec["expires_at"])
            is_expired = now_utc > expires_at_utc
            seconds_left = max(0, int((expires_at_utc - now_utc).total_seconds()))

            if is_expired and rec["status"] in ("failed", "pending"):
                rec["status"] = "expired"

            retries_left = max(0, rec["max_retries"] - rec["retry_count"])
            rec["is_expired"] = is_expired
            rec["seconds_until_expiry"] = seconds_left
            rec["retries_left"] = retries_left
            rec["can_replay"] = (
                rec["status"] in ("failed", "pending")
                and not is_expired
                and retries_left > 0
            )

            if include_expired or rec["status"] in ("failed", "pending", "replaying"):
                records.append(rec)

        return records
    finally:
        conn.close()


def begin_replay(
    record_id: str,
    user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Atomically checks preconditions and transitions record status to 'replaying'.
    Guarantees that only ONE thread or request can execute a replay for this record,
    preventing duplicate submissions.

    Args:
        record_id: ID of the retry record.
        user_id: Optional student identifier for permission check.
        db_path: Optional database path override.

    Returns:
        (True, None, record_dict) if replay successfully claimed.
        (False, error_message, None) if replay rejected.
    """
    now_utc = datetime.now(timezone.utc)
    now_iso = _format_iso(now_utc)

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        cursor.execute("SELECT * FROM api_retry_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return False, "Retry record not found.", None

        rec = dict(row)

        if user_id and rec["user_id"] != user_id and rec["user_id"] != "default_student":
            return False, "Unauthorized to replay this operation.", None

        expires_at_utc = _parse_iso(rec["expires_at"])
        if now_utc > expires_at_utc:
            cursor.execute("UPDATE api_retry_records SET status = 'expired', updated_at = ? WHERE id = ?", (now_iso, record_id))
            conn.commit()
            return False, "Retry record has expired. Please initiate a new request.", None

        if rec["status"] == "succeeded":
            return False, "Operation has already succeeded and cannot be resubmitted.", None

        if rec["status"] == "replaying":
            return False, "Operation is currently being replayed. Please wait.", None

        if rec["retry_count"] >= rec["max_retries"]:
            cursor.execute("UPDATE api_retry_records SET status = 'exhausted', updated_at = ? WHERE id = ?", (now_iso, record_id))
            conn.commit()
            return False, f"Maximum retry attempts ({rec['max_retries']}) reached for this operation.", None

        # Atomic transition to 'replaying'
        cursor.execute("""
            UPDATE api_retry_records
            SET status = 'replaying',
                retry_count = retry_count + 1,
                updated_at = ?
            WHERE id = ?
              AND status IN ('failed', 'pending')
              AND datetime(expires_at) > datetime('now')
        """, (now_iso, record_id))
        conn.commit()

        if cursor.rowcount == 0:
            return False, "Concurrent replay or operation state changed.", None

        # Fetch fresh record
        cursor.execute("SELECT * FROM api_retry_records WHERE id = ?", (record_id,))
        fresh_row = cursor.fetchone()
        fresh_rec = dict(fresh_row)
        try:
            fresh_rec["payload"] = json.loads(fresh_rec.get("payload_json") or "{}")
        except Exception:
            fresh_rec["payload"] = {}

        return True, None, fresh_rec
    finally:
        conn.close()


def complete_replay(
    record_id: str,
    success: bool,
    result_payload: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Finalizes a replay attempt with its success or failure outcome.

    Args:
        record_id: ID of the retry record.
        success: Whether the replayed operation succeeded.
        result_payload: Optional response payload.
        error_message: Optional error message on failure.
        db_path: Optional database path override.

    Returns:
        Updated record dictionary.
    """
    now_utc = datetime.now(timezone.utc)
    now_iso = _format_iso(now_utc)
    resp_json = json.dumps(result_payload or {}, ensure_ascii=False) if result_payload else None

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        cursor.execute("SELECT * FROM api_retry_records WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Retry record {record_id} not found.")

        rec = dict(row)

        if success:
            cursor.execute("""
                UPDATE api_retry_records
                SET status = 'succeeded',
                    last_response_json = ?,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ?
            """, (resp_json, now_iso, record_id))
            conn.commit()
            rec["status"] = "succeeded"
            rec["last_response_json"] = resp_json
            rec["error_message"] = None
        else:
            new_status = "exhausted" if rec["retry_count"] >= rec["max_retries"] else "failed"
            cursor.execute("""
                UPDATE api_retry_records
                SET status = ?,
                    error_message = ?,
                    last_response_json = ?,
                    updated_at = ?
                WHERE id = ?
            """, (new_status, error_message or "Replay attempt failed.", resp_json, now_iso, record_id))
            conn.commit()
            rec["status"] = new_status
            rec["error_message"] = error_message
            rec["last_response_json"] = resp_json

        rec["updated_at"] = now_iso
        return rec
    finally:
        conn.close()


def cancel_retry_record(
    record_id: str,
    user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    Cancels or dismisses an active retry record.

    Args:
        record_id: ID of the retry record.
        user_id: Optional student identifier verification.
        db_path: Optional database path override.

    Returns:
        True if record was cancelled, False otherwise.
    """
    now_iso = _format_iso(datetime.now(timezone.utc))

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        if user_id:
            cursor.execute("""
                UPDATE api_retry_records
                SET status = 'cancelled', updated_at = ?
                WHERE id = ? AND (user_id = ? OR user_id = 'default_student')
            """, (now_iso, record_id, user_id))
        else:
            cursor.execute("""
                UPDATE api_retry_records
                SET status = 'cancelled', updated_at = ?
                WHERE id = ?
            """, (now_iso, record_id))

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def cleanup_expired_retries(
    db_path: Optional[str] = None,
    purge_after_hours: int = 24,
) -> int:
    """
    Transitions stale records beyond their expires_at date to 'expired',
    and purges very old records (> 24 hours) to keep storage bounded.

    Args:
        db_path: Optional database path override.
        purge_after_hours: Hours after which expired/cancelled records are deleted.

    Returns:
        Count of updated expired records.
    """
    now_utc = datetime.now(timezone.utc)
    now_iso = _format_iso(now_utc)
    purge_cutoff_iso = _format_iso(now_utc - timedelta(hours=purge_after_hours))

    conn = get_connection(db_path or Config.DATABASE_PATH)
    try:
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)

        cursor.execute("""
            UPDATE api_retry_records
            SET status = 'expired', updated_at = ?
            WHERE status IN ('failed', 'pending')
              AND datetime(expires_at) <= datetime('now')
        """, (now_iso,))
        updated = cursor.rowcount

        # Purge very old completed/cancelled/expired records
        cursor.execute("""
            DELETE FROM api_retry_records
            WHERE status IN ('succeeded', 'cancelled', 'expired', 'exhausted')
              AND datetime(updated_at) < datetime(?)
        """, (purge_cutoff_iso,))

        conn.commit()
        return updated
    finally:
        conn.close()
