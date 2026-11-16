"""
Secure Report-Sharing Link with Expiration and Revocation Service (#408).

Enables students to generate safe, read-only public sharing links for mentors
or career counselors:
- Cryptographically secure unguessable tokens (secrets.token_urlsafe).
- Configurable expiration periods (e.g. 1 hour, 24 hours, 7 days, 30 days).
- Immediate manual revocation capability by the owner.
- Read-only shared view: strictly renders the placement report and hides account controls,
  other private analyses, resumes, and personal identity credentials.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import uuid
from typing import Any, Dict, List, Optional, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

ALLOWED_EXPIRATION_HOURS = {
    "1h": 1,
    "24h": 24,
    "7d": 168,
    "30d": 720
}


def init_shared_links_table():
    """Initializes the secure report sharing table if missing."""
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
                revoked_at TIMESTAMP
            )
            """
        )
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
    """
    if not analysis_id or not student_id:
        raise ValueError("Analysis ID and Student ID are required.")

    hours = ALLOWED_EXPIRATION_HOURS.get(expiration_choice, 24)
    expires_at = dt.datetime.utcnow() + dt.timedelta(hours=hours)
    token = secrets.token_urlsafe(32)
    link_id = f"shr-{uuid.uuid4().hex[:12]}"

    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Verify ownership
        cursor.execute(
            "SELECT id, company_name, resume_filename FROM analyses WHERE id = ? AND student_id = ?",
            (analysis_id, student_id)
        )
        analysis_row = cursor.fetchone()
        if not analysis_row:
            raise KeyError("Analysis not found or you do not have permission to share it.")

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
            exp_time = dt.datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
            if dt.datetime.utcnow() > exp_time:
                return False, None, "This sharing link has expired."
        except Exception:
            pass

        # Increment view count
        cursor.execute(
            "UPDATE secure_shared_reports SET view_count = view_count + 1 WHERE id = ?",
            (rec["id"],)
        )
        conn.commit()

        # Sanitize data for read-only mentor view
        import json
        results = {}
        try:
            results = json.loads(rec["results_json"] or "{}")
        except Exception:
            pass

        sanitized_report = {
            "analysis_id": rec["analysis_id"],
            "company_name": rec["company_name"],
            "job_description": rec["job_description"],
            "results": results,
            "created_at": rec["analysis_date"],
            "view_count": rec["view_count"] + 1,
            "expires_at": rec["expires_at"]
        }
        return True, sanitized_report, None
    finally:
        conn.close()


def revoke_shared_link(student_id: str, share_id_or_token: str) -> bool:
    """
    Allows the owner to immediately revoke a sharing link.
    """
    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
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


def list_user_active_shares(student_id: str) -> List[Dict[str, Any]]:
    """Lists all active share links generated by a student."""
    init_shared_links_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
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
        return [dict(r) for r in rows]
    finally:
        conn.close()
