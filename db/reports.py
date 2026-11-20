"""
Shared Reports & Mentorship Reviews Repository (db/reports.py)
=============================================================
Handles database operations for shared placement reports, mentor sharing links,
expiration tracking, view analytics, and link revocation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import uuid
from typing import Any, Dict, List, Optional, Tuple

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)

ALLOWED_EXPIRATION_HOURS = {
    "1h": 1,
    "24h": 24,
    "7d": 168,
    "30d": 720,
}


def create_shared_report(
    analysis_id: str,
    student_id: str,
    expires_hours: int = 24,
    access_code: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates an expiring, shareable report record for mentor reviews."""
    share_id = f"shr-{uuid.uuid4().hex[:12]}"
    now_utc = dt.datetime.now(dt.timezone.utc)
    expires_at = (now_utc + dt.timedelta(hours=expires_hours)).strftime("%Y-%m-%d %H:%M:%S")

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO shared_reports (id, analysis_id, student_id, expires_at, is_active, access_code)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (share_id, analysis_id, student_id.strip() if student_id else "default_student", expires_at, access_code),
        )

    return {
        "id": share_id,
        "analysis_id": analysis_id,
        "student_id": student_id,
        "expires_at": expires_at,
        "is_active": True,
        "access_code": access_code,
    }


def get_shared_report(
    share_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves a shared report record if active and not expired."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, a.company_name, a.job_description, a.results_json
            FROM shared_reports s
            JOIN analyses a ON s.analysis_id = a.id
            WHERE s.id = ? AND s.is_active = 1
            """,
            (share_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        rec = dict(row)
        try:
            exp_time = dt.datetime.strptime(rec["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) > exp_time:
                return None
        except Exception:
            pass
        return rec


def record_shared_report_view(
    share_id: str,
    viewer_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Logs a view event for a shared report."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO shared_report_views (share_id, viewer_ip, user_agent)
                VALUES (?, ?, ?)
                """,
                (share_id, viewer_ip or "", user_agent or ""),
            )
            return True
    except Exception as e:
        logger.error(f"Error recording view for shared report {share_id}: {e}")
        return False


def get_active_shares_for_analysis(
    analysis_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns all active share links for an analysis belonging to student_id."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM shared_reports
            WHERE analysis_id = ? AND student_id = ? AND is_active = 1
            ORDER BY created_at DESC
            """,
            (analysis_id, student_id.strip() if student_id else "default_student"),
        )
        return [dict(r) for r in cursor.fetchall()]


def revoke_shared_report(
    share_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Revokes a shared report if owned by the specified student."""
    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                UPDATE shared_reports SET is_active = 0
                WHERE id = ? AND student_id = ?
                """,
                (share_id, student_id.strip() if student_id else "default_student"),
            )
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error revoking shared report {share_id}: {e}")
        return False


def get_shared_report_views(
    share_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns view log history for a report owned by student_id."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT v.* FROM shared_report_views v
            JOIN shared_reports s ON v.share_id = s.id
            WHERE s.id = ? AND s.student_id = ?
            ORDER BY v.viewed_at DESC
            """,
            (share_id, student_id.strip() if student_id else "default_student"),
        )
        return [dict(r) for r in cursor.fetchall()]


# Secure token-based shared reports (matching utils/shared_reports_service.py)

def create_secure_share_link(
    analysis_id: str,
    student_id: str,
    expiration_choice: str = "24h",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a secure token-based expiring share link for an analysis."""
    if not analysis_id or not student_id:
        raise ValueError("Analysis ID and Student ID are required.")

    hours = ALLOWED_EXPIRATION_HOURS.get(expiration_choice, 24)
    now_utc = dt.datetime.now(dt.timezone.utc)
    expires_at = now_utc + dt.timedelta(hours=hours)
    token = secrets.token_urlsafe(32)
    link_id = f"shr-{uuid.uuid4().hex[:12]}"

    with transaction(db_path) as cursor:
        cursor.execute(
            "SELECT id, student_id FROM analyses WHERE id = ?",
            (analysis_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise KeyError("Analysis not found.")
        if dict(row).get("student_id") != student_id:
            raise PermissionError("You do not have permission to share this analysis.")

        cursor.execute(
            """
            INSERT INTO secure_shared_reports (
                id, token, analysis_id, student_id, is_active, expires_at
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (link_id, token, analysis_id, student_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

    return {
        "success": True,
        "share_id": link_id,
        "token": token,
        "share_url": f"/shared/report/{token}",
        "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expiration_choice": expiration_choice,
    }


def get_secure_shared_report(
    token: str,
    db_path: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Retrieves and validates a secure shared report by its unguessable token."""
    if not token:
        return False, None, "Invalid share token."

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            SELECT s.*, a.company_name, a.job_description, a.results_json, a.created_at as analysis_date
            FROM secure_shared_reports s
            JOIN analyses a ON s.analysis_id = a.id
            WHERE s.token = ?
            """,
            (token,),
        )
        row = cursor.fetchone()
        if not row:
            return False, None, "Shared report not found."

        rec = dict(row)
        if not rec["is_active"]:
            return False, None, "This sharing link has been revoked by the owner."

        exp_str = rec["expires_at"]
        try:
            exp_time = dt.datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) > exp_time:
                return False, None, "This sharing link has expired."
        except Exception:
            pass

        now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        new_view_count = (rec.get("view_count") or 0) + 1
        cursor.execute(
            "UPDATE secure_shared_reports SET view_count = ?, last_viewed_at = ? WHERE id = ?",
            (new_view_count, now_str, rec["id"]),
        )

        return True, {
            "analysis_id": rec["analysis_id"],
            "company_name": rec.get("company_name", ""),
            "job_description": rec.get("job_description", ""),
            "results_json": rec.get("results_json", "{}"),
            "created_at": rec["analysis_date"],
            "view_count": new_view_count,
            "last_viewed_at": now_str,
            "expires_at": rec["expires_at"],
        }, None


def revoke_secure_share_link(
    student_id: str,
    share_id_or_token: str,
    db_path: Optional[str] = None,
) -> bool:
    """Revokes a secure share link after checking student ownership."""
    with transaction(db_path) as cursor:
        cursor.execute(
            """
            SELECT student_id, is_active FROM secure_shared_reports
            WHERE id = ? OR token = ?
            """,
            (share_id_or_token, share_id_or_token),
        )
        row = cursor.fetchone()
        if not row:
            return False

        if dict(row).get("student_id") != student_id:
            raise PermissionError("You do not have permission to revoke this share link.")

        cursor.execute(
            """
            UPDATE secure_shared_reports
            SET is_active = 0, revoked_at = CURRENT_TIMESTAMP
            WHERE (id = ? OR token = ?) AND student_id = ?
            """,
            (share_id_or_token, share_id_or_token, student_id),
        )
        return cursor.rowcount > 0


def list_student_secure_shares(
    student_id: str,
    analysis_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists secure share links generated by a student."""
    with get_connection(db_path) as conn:
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
                (student_id, analysis_id),
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
                (student_id,),
            )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["share_url"] = f"/shared/report/{d['token']}"
            result.append(d)
        return result
