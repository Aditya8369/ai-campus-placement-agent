"""
Interview Experience Moderation Dashboard (#252)
================================================
Comprehensive moderation queue, audit logging, and administrative controls for peer
interview experience submissions.

Key Capabilities:
1. Dynamic Moderation Status:
   - status: 'pending_review', 'approved', 'rejected', 'flagged'
   - Tracks approval/rejection timestamp, moderator remarks, and action logs.
2. Moderation Audit Trail (experience_moderation_logs table).
3. Queue filtering: filter by status ('pending_review', 'flagged', 'approved', 'rejected'),
   company name, keyword, or report threshold.
4. Administrative bulk/single actions: approve, reject, reinstate, delete, or dismiss reports.
5. Integration with public interview experience listing so only 'approved' experiences
   are shown to student candidates, preserving high content quality and trust.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import uuid

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)

MODERATION_STATUSES = {"pending_review", "approved", "rejected", "flagged"}


def ensure_interview_moderation_schema(conn: sqlite3.Connection) -> None:
    """Ensures interview_experiences contains moderation columns and creates the audit log table."""
    cursor = conn.cursor()

    # Verify and add moderation columns to interview_experiences if not present
    cursor.execute("PRAGMA table_info(interview_experiences)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "moderation_status" not in existing_cols:
        cursor.execute("ALTER TABLE interview_experiences ADD COLUMN moderation_status TEXT NOT NULL DEFAULT 'approved'")
    if "moderated_by" not in existing_cols:
        cursor.execute("ALTER TABLE interview_experiences ADD COLUMN moderated_by TEXT")
    if "moderation_notes" not in existing_cols:
        cursor.execute("ALTER TABLE interview_experiences ADD COLUMN moderation_notes TEXT")
    if "moderated_at" not in existing_cols:
        cursor.execute("ALTER TABLE interview_experiences ADD COLUMN moderated_at TIMESTAMP")

    # Create audit table for all moderation actions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS experience_moderation_logs (
            id TEXT PRIMARY KEY,
            experience_id TEXT NOT NULL,
            action TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            moderator_id TEXT NOT NULL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_mod_status ON interview_experiences(moderation_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_mod_flagged ON interview_experiences(reported_flag)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mod_logs_exp ON experience_moderation_logs(experience_id)")
    conn.commit()


def get_moderation_queue(
    status_filter: Optional[str] = None,
    flagged_only: bool = False,
    company_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Fetches interview experiences requiring moderation or matching filtered criteria.
    Returns structured list along with queue summary counters.
    """
    with get_db_connection() as conn:
        ensure_interview_moderation_schema(conn)
        cursor = conn.cursor()

        # Compute counts for dashboard metrics
        cursor.execute("SELECT moderation_status, COUNT(*) as count FROM interview_experiences GROUP BY moderation_status")
        status_counts = {r["moderation_status"]: r["count"] for r in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) as count FROM interview_experiences WHERE reported_flag = 1")
        flagged_count = cursor.fetchone()["count"]

        # Build dynamic query
        query = "SELECT * FROM interview_experiences WHERE 1=1"
        params: List[Any] = []

        if status_filter and status_filter.lower() != "all":
            query += " AND LOWER(moderation_status) = LOWER(?)"
            params.append(status_filter.strip())

        if flagged_only:
            query += " AND reported_flag = 1"

        if company_filter and company_filter.strip() and company_filter.lower() != "all":
            query += " AND LOWER(company_name) = LOWER(?)"
            params.append(company_filter.strip())

        if search_query and search_query.strip():
            sq = f"%{search_query.strip().lower()}%"
            query += " AND (LOWER(company_name) LIKE ? OR LOWER(role_title) LIKE ? OR LOWER(tips_and_preparation) LIKE ?)"
            params.extend([sq, sq, sq])

        query += " ORDER BY reported_flag DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        experiences = [_format_experience_row(r) for r in rows]

        return {
            "status_counts": {
                "pending_review": status_counts.get("pending_review", 0),
                "flagged": flagged_count,
                "approved": status_counts.get("approved", 0),
                "rejected": status_counts.get("rejected", 0),
                "total": sum(status_counts.values())
            },
            "total_matches": len(experiences),
            "experiences": experiences
        }


def moderate_interview_experience(
    experience_id: str,
    action: str,
    moderator_id: str = "admin",
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a moderation decision on an interview experience:
    - approve: marks status = 'approved', clears reported_flag
    - reject: marks status = 'rejected'
    - flag: marks status = 'flagged', sets reported_flag = 1
    - dismiss_report: clears reported_flag without changing approval status

    Records audit trail in experience_moderation_logs.
    """
    valid_actions = {"approve", "reject", "flag", "dismiss_report"}
    if action not in valid_actions:
        raise ValueError(f"Invalid moderation action '{action}'. Valid: {valid_actions}")

    with get_db_connection() as conn:
        ensure_interview_moderation_schema(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM interview_experiences WHERE id = ?", (experience_id,))
        record = cursor.fetchone()
        if not record:
            raise KeyError(f"Interview experience '{experience_id}' not found.")

        current_status = record["moderation_status"]
        now = datetime.now(timezone.utc).isoformat()

        if action == "approve":
            new_status = "approved"
            cursor.execute("""
                UPDATE interview_experiences
                SET moderation_status = 'approved', reported_flag = 0,
                    moderated_by = ?, moderation_notes = ?, moderated_at = ?
                WHERE id = ?
            """, (moderator_id, reason, now, experience_id))

        elif action == "reject":
            new_status = "rejected"
            cursor.execute("""
                UPDATE interview_experiences
                SET moderation_status = 'rejected',
                    moderated_by = ?, moderation_notes = ?, moderated_at = ?
                WHERE id = ?
            """, (moderator_id, reason, now, experience_id))

        elif action == "flag":
            new_status = "flagged"
            cursor.execute("""
                UPDATE interview_experiences
                SET moderation_status = 'flagged', reported_flag = 1, report_reason = ?,
                    moderated_by = ?, moderation_notes = ?, moderated_at = ?
                WHERE id = ?
            """, (reason, moderator_id, reason, now, experience_id))

        elif action == "dismiss_report":
            new_status = current_status
            cursor.execute("""
                UPDATE interview_experiences
                SET reported_flag = 0, report_reason = NULL,
                    moderated_by = ?, moderation_notes = ?, moderated_at = ?
                WHERE id = ?
            """, (moderator_id, f"Report dismissed: {reason or 'no violation'}", now, experience_id))

        # Log audit entry
        log_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO experience_moderation_logs (
                id, experience_id, action, previous_status, new_status,
                moderator_id, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_id, experience_id, action, current_status, new_status, moderator_id, reason, now))

        conn.commit()

        # Fetch updated record
        cursor.execute("SELECT * FROM interview_experiences WHERE id = ?", (experience_id,))
        updated = cursor.fetchone()
        return _format_experience_row(updated)


def get_experience_moderation_logs(experience_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves moderation audit records."""
    with get_db_connection() as conn:
        ensure_interview_moderation_schema(conn)
        cursor = conn.cursor()
        if experience_id:
            cursor.execute("""
                SELECT * FROM experience_moderation_logs
                WHERE experience_id = ?
                ORDER BY created_at DESC
            """, (experience_id,))
        else:
            cursor.execute("""
                SELECT * FROM experience_moderation_logs
                ORDER BY created_at DESC
                LIMIT 100
            """)
        return [dict(r) for r in cursor.fetchall()]


def _format_experience_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Converts DB row to dict with parsed JSON rounds."""
    d = dict(row)
    try:
        d["rounds"] = json.loads(d.get("rounds_json") or "[]")
    except Exception:
        d["rounds"] = []
    return d
