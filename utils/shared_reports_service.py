"""
Secure Report-Sharing Link with Expiration, Revocation, and Redaction Service (#408, #468).

Enables students to generate safe, read-only public sharing links for mentors,
seniors, or placement officers:
- Cryptographically secure unguessable tokens (secrets.token_urlsafe).
- Configurable expiration periods (24 hours, 7 days, etc.).
- Immediate manual revocation capability by the owner.
- Deep PII redaction: automatically redacts candidate email, phone, physical address,
  and personal profile links from the shared view.
- Tracks views (view count and last viewed timestamp).
- Read-only shared view: strictly renders the placement report and hides account controls,
  other private analyses, resumes, personal identity credentials, and edit/delete/download actions.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import uuid
from typing import Any, Dict, List, Optional, Tuple

from utils.database import get_db_connection
from utils.pii_redactor import redact_pii

logger = logging.getLogger(__name__)

class SharePermissionError(KeyError, PermissionError):
    """Raised when a user lacks permission to access, create, or revoke a shared report."""
    pass


ALLOWED_EXPIRATION_HOURS = {
    "1h": 1,
    "24h": 24,
    "7d": 168,
    "30d": 720
}


def _deep_redact_pii(data: Any) -> Any:
    """
    Recursively redacts PII (emails, phone numbers, addresses, personal links)
    and removes student account identifiers from arbitrary nested structures.
    """
    if isinstance(data, str):
        return redact_pii(data, enabled=True)
    elif isinstance(data, dict):
        sensitive_keys = {
            "student_id", "user_id", "email", "phone", "contact",
            "personal_info", "account", "password", "auth_session_id",
            "candidate_email", "candidate_phone", "candidate_address",
            "pdf_metadata_hygiene", "metadata_hygiene"
        }
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in sensitive_keys:
                continue
            sanitized[k] = _deep_redact_pii(v)
        return sanitized
    elif isinstance(data, list):
        return [_deep_redact_pii(item) for item in data]
    else:
        return data


def init_shared_links_table():
    """Initializes the secure report sharing table if missing and ensures schema migrations."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS secure_shared_reports (
                id TEXT PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                analysis_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                view_count INTEGER DEFAULT 0,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revoked_at TIMESTAMP,
                last_viewed_at TIMESTAMP
            )
            """
        )
        # Migrate table schema if last_viewed_at is missing from an existing database
        cursor.execute("PRAGMA table_info(secure_shared_reports)")
        columns = [col[1] for col in cursor.fetchall()]
        if "last_viewed_at" not in columns:
            cursor.execute("ALTER TABLE secure_shared_reports ADD COLUMN last_viewed_at TIMESTAMP")
        conn.commit()
    finally:
        conn.close()


def create_shared_report_link(
    analysis_id: str,
    student_id: str,
    expiration_choice: str = "24h"
) -> Dict[str, Any]:
    """
    Creates an expiring, revocable share link for a specific analysis owned by student_id.
    Enforces analysis ownership: only the owner can create a share link.
    """
    if not analysis_id or not student_id:
        raise ValueError("Analysis ID and Student ID are required.")

    hours = ALLOWED_EXPIRATION_HOURS.get(expiration_choice, 24)
    now_utc = dt.datetime.now(dt.timezone.utc)
    expires_at = now_utc + dt.timedelta(hours=hours)
    token = secrets.token_urlsafe(32)
    link_id = f"shr-{uuid.uuid4().hex[:12]}"

    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Verify ownership
        cursor.execute(
            "SELECT id, student_id, company_name, resume_filename FROM analyses WHERE id = ?",
            (analysis_id,)
        )
        analysis_row = cursor.fetchone()
        if not analysis_row:
            raise KeyError("Analysis not found.")
        
        row_dict = dict(analysis_row)
        if row_dict.get("student_id") != student_id:
            raise SharePermissionError("You do not have permission to share this analysis.")

        cursor.execute(
            """
            INSERT INTO secure_shared_reports (
                id, token, analysis_id, student_id, is_active, expires_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (link_id, token, analysis_id, student_id, expires_at.strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "share_id": link_id,
        "token": token,
        "share_url": f"/shared/report/{token}",
        "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expiration_choice": expiration_choice
    }


def get_shared_report_by_token(token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates share token and returns the analysis data for read-only view.
    Checks revocation status and expiration timestamp.
    Applies deep PII redaction and updates view count & last_viewed_at.
    """
    if not token:
        return False, None, "Invalid share token."

    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, a.company_name, a.job_description, a.results_json, a.created_at as analysis_date
            FROM secure_shared_reports s
            JOIN analyses a ON s.analysis_id = a.id
            WHERE s.token = ?
            """,
            (token,)
        )
        row = cursor.fetchone()
        if not row:
            return False, None, "Shared report not found."

        rec = dict(row)
        if not rec["is_active"]:
            return False, None, "This sharing link has been revoked by the owner."

        # Expiration check
        exp_str = rec["expires_at"]
        try:
            exp_time = dt.datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            now_utc = dt.datetime.now(dt.timezone.utc)
            if now_utc > exp_time:
                return False, None, "This sharing link has expired."
        except Exception:
            pass

        # Record view: increment count and update last_viewed_at
        now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_view_count = (rec.get("view_count") or 0) + 1
        cursor.execute(
            "UPDATE secure_shared_reports SET view_count = ?, last_viewed_at = ? WHERE id = ?",
            (new_view_count, now_str, rec["id"])
        )
        conn.commit()

        # Sanitize data for read-only mentor view
        results = {}
        try:
            results = json.loads(rec["results_json"] or "{}")
        except Exception:
            pass

        # Apply deep PII redaction to company name, job description, and nested results
        redacted_company = redact_pii(rec.get("company_name") or "", enabled=True)
        redacted_jd = redact_pii(rec.get("job_description") or "", enabled=True)
        redacted_results = _deep_redact_pii(results)

        sanitized_report = {
            "analysis_id": rec["analysis_id"],
            "company_name": redacted_company,
            "job_description": redacted_jd,
            "results": redacted_results,
            "created_at": rec["analysis_date"],
            "view_count": new_view_count,
            "last_viewed_at": now_str,
            "expires_at": rec["expires_at"]
        }
        return True, sanitized_report, None
    finally:
        conn.close()


def revoke_shared_link(student_id: str, share_id_or_token: str) -> bool:
    """
    Allows the owner to immediately revoke a sharing link.
    Enforces ownership: only the student who created the link can revoke it.
    """
    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT student_id, is_active FROM secure_shared_reports
            WHERE id = ? OR token = ?
            """,
            (share_id_or_token, share_id_or_token)
        )
        row = cursor.fetchone()
        if not row:
            return False

        row_dict = dict(row)
        if row_dict.get("student_id") != student_id:
            raise SharePermissionError("You do not have permission to revoke this share link.")

        cursor.execute(
            """
            UPDATE secure_shared_reports
            SET is_active = 0, revoked_at = CURRENT_TIMESTAMP
            WHERE (id = ? OR token = ?) AND student_id = ?
            """,
            (share_id_or_token, share_id_or_token, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_user_active_shares(student_id: str, analysis_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists share links generated by a student, optionally filtered by analysis_id."""
    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if analysis_id:
            cursor.execute(
                """
                SELECT s.*, a.company_name
                FROM secure_shared_reports s
                JOIN analyses a ON s.analysis_id = a.id
                WHERE s.student_id = ? AND s.analysis_id = ?
                ORDER BY s.created_at DESC
                """,
                (student_id, analysis_id)
            )
        else:
            cursor.execute(
                """
                SELECT s.*, a.company_name
                FROM secure_shared_reports s
                JOIN analyses a ON s.analysis_id = a.id
                WHERE s.student_id = ?
                ORDER BY s.created_at DESC
                """,
                (student_id,)
            )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["share_url"] = f"/shared/report/{d['token']}"
            result.append(d)
        return result
    finally:
        conn.close()
