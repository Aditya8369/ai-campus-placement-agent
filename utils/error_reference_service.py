"""
Error Reporting Reference ID Service (#263).
Provides:
- Generation of human-shareable, high-entropy unique Error Reference IDs (e.g. ERR-YYYYMMDD-XXXXXX).
- Redaction of sensitive values (API keys, passwords, bearer tokens, JWTs, emails) from logged errors.
- Persistence of error incidents in an internal SQLite registry for debugging and support triage.
- Support lookup utility for administrative staff to look up error context by reference ID.
- Global exception formatting helpers for Flask error handlers.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import secrets
import traceback
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Patterns for sanitizing sensitive credentials
REDACTION_PATTERNS = [
    (re.compile(r'(?i)(?:password|passwd|pwd|secret|auth_token|api_key|token)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)'), r'\g<0>'[:r'\g<0>'.find(':')+1] if False else r'***REDACTED***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]+'), 'Bearer ***REDACTED_TOKEN***'),
    (re.compile(r'AIza[0-9A-Za-z-_]{35}'), '***REDACTED_GOOGLE_KEY***'),
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), '***REDACTED_API_KEY***'),
    (re.compile(r'(?i)[a-z0-9_.+-]+@[a-z0-9-]+\.[a-z0-9-.]+'), '***REDACTED_EMAIL***'),
]


def sanitize_error_text(text: str) -> str:
    """Sanitize stack traces, error messages, and payload strings to prevent credential leakage."""
    if not text:
        return ""
    sanitized = str(text)
    for pattern, replacement in REDACTION_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def init_error_registry_table() -> None:
    """Initialize table storing captured application error records."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS application_error_logs (
                reference_id TEXT PRIMARY KEY,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                sanitized_traceback TEXT,
                endpoint TEXT,
                http_method TEXT,
                status_code INTEGER NOT NULL DEFAULT 500,
                user_id TEXT,
                request_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_err_ref_created ON application_error_logs(created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_err_ref_user ON application_error_logs(user_id)"
        )
        conn.commit()
    finally:
        conn.close()


def generate_error_reference_id() -> str:
    """
    Generate an ergonomic, human-shareable unique reference identifier.
    Format: ERR-YYYYMMDD-<6_CHAR_HEX>
    """
    today_str = dt.datetime.utcnow().strftime("%Y%m%d")
    random_hex = secrets.token_hex(3).upper()
    return f"ERR-{today_str}-{random_hex}"


def record_application_error(
    error: Exception,
    endpoint: Optional[str] = None,
    http_method: Optional[str] = None,
    status_code: int = 500,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Capture an uncaught or internal exception, sanitize its stack trace,
    store it in the incident registry, and return reference details for user display.
    """
    init_error_registry_table()

    ref_id = generate_error_reference_id()
    err_type = type(error).__name__
    raw_message = str(error)
    sanitized_message = sanitize_error_text(raw_message)

    raw_tb = traceback.format_exc()
    sanitized_tb = sanitize_error_text(raw_tb)

    now_str = dt.datetime.utcnow().isoformat()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO application_error_logs
                (reference_id, error_type, error_message, sanitized_traceback, endpoint, http_method, status_code, user_id, request_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref_id,
                err_type,
                sanitized_message,
                sanitized_tb,
                endpoint,
                http_method,
                status_code,
                str(user_id) if user_id else None,
                request_id,
                now_str,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.critical(f"Failed to persist error record to application_error_logs: {e}")
    finally:
        conn.close()

    logger.error(
        f"Internal Error Captured [{ref_id}] at {http_method} {endpoint}: {sanitized_message} (User: {user_id})"
    )

    return {
        "reference_id": ref_id,
        "error_type": err_type,
        "user_message": f"An unexpected system error occurred. Please quote Reference ID: {ref_id} when contacting support.",
        "status_code": status_code,
        "timestamp": now_str,
        "request_id": request_id,
    }


def lookup_error_reference(reference_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve incident log record for an error reference ID (administrator utility).
    """
    if not reference_id or not isinstance(reference_id, str):
        return None

    init_error_registry_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reference_id, error_type, error_message, sanitized_traceback,
                   endpoint, http_method, status_code, user_id, request_id, created_at
            FROM application_error_logs
            WHERE reference_id = ?
            """,
            (reference_id.strip(),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def get_recent_error_incidents(limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent error incidents for developer operations and support diagnostics.
    """
    init_error_registry_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reference_id, error_type, error_message, endpoint, http_method,
                   status_code, user_id, request_id, created_at
            FROM application_error_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
