"""
Job Application Activity Timeline & Audit Trail Engine (#259)
=============================================================
Maintains an immutable chronological timeline of application transitions and candidate actions.

Key Capabilities:
1. Dynamic Schema:
   - `job_application_activity_timeline` table recording each status transition, custom student note,
     timestamp, and event type.
2. Timeline Event Capture:
   - Automatically logs initial creation ('created')
   - Automatically captures status changes ('status_change' with previous_status and new_status)
   - Allows students to log custom milestones ('note_added', 'interview_scheduled', 'offer_received')
3. Chronological Reconstruction & Synthetic Fallback:
   - For legacy applications without prior activity rows, generates a baseline historical milestone
     from application_date and created_at.
4. Multi-Tenant Authorization Protection:
   - Prevents unauthorized access or timeline logging across student accounts.
"""

import sqlite3
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

STANDARD_STAGES = [
    "Bookmarked", "Applied", "Under Review", "Online Assessment",
    "Interview Scheduled", "Interviewing", "Offer Extended",
    "Offer Accepted", "Rejected", "Withdrawn"
]


def ensure_application_timeline_table(conn: sqlite3.Connection) -> None:
    """Creates the activity timeline table and indices if they do not exist."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_application_activity_timeline (
            id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'status_change',
            previous_status TEXT,
            new_status TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_app ON job_application_activity_timeline(application_id, created_at ASC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_student ON job_application_activity_timeline(student_id)")
    conn.commit()


def log_application_activity(
    application_id: str,
    student_id: str,
    new_status: str,
    previous_status: Optional[str] = None,
    event_type: str = "status_change",
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records an activity or status transition for a job application.
    Enforces student ownership of the parent application.
    """
    app_id = (application_id or "").strip()
    sid = (student_id or "").strip()

    if not app_id or not sid:
        raise ValueError("Both application_id and student_id are required.")

    now = datetime.now(timezone.utc).isoformat()
    record_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        ensure_application_timeline_table(conn)
        cursor = conn.cursor()

        # Verify application belongs to student
        cursor.execute("SELECT id, status FROM job_applications WHERE id = ? AND student_id = ?", (app_id, sid))
        parent_app = cursor.fetchone()
        if not parent_app:
            raise PermissionError(f"Job application '{app_id}' was not found or access is denied.")

        prev = previous_status if previous_status is not None else parent_app["status"]

        cursor.execute("""
            INSERT INTO job_application_activity_timeline (
                id, application_id, student_id, event_type, previous_status, new_status, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record_id, app_id, sid, event_type, prev, new_status, notes, now
        ))
        conn.commit()

    return {
        "id": record_id,
        "application_id": app_id,
        "student_id": sid,
        "event_type": event_type,
        "previous_status": prev,
        "new_status": new_status,
        "notes": notes,
        "timestamp": now
    }


def get_application_timeline(
    application_id: str,
    student_id: str
) -> Dict[str, Any]:
    """
    Retrieves the chronological timeline of events for an application.
    Synthesizes initial creation entry if legacy application has no rows.
    """
    app_id = (application_id or "").strip()
    sid = (student_id or "").strip()

    with get_db_connection() as conn:
        ensure_application_timeline_table(conn)
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute("""
            SELECT id, company_name, role_title, status, application_date, created_at
            FROM job_applications
            WHERE id = ? AND student_id = ?
        """, (app_id, sid))
        app_row = cursor.fetchone()
        if not app_row:
            raise PermissionError(f"Application '{app_id}' not found or access denied.")

        app_info = dict(app_row)

        cursor.execute("""
            SELECT id, application_id, student_id, event_type, previous_status, new_status, notes, created_at
            FROM job_application_activity_timeline
            WHERE application_id = ? AND student_id = ?
            ORDER BY created_at ASC
        """, (app_id, sid))
        rows = cursor.fetchall()
        timeline_events = [dict(r) for r in rows]

        # Handle applications without historical activity records
        if not timeline_events:
            baseline_event = {
                "id": f"initial-{app_id}",
                "application_id": app_id,
                "student_id": sid,
                "event_type": "created",
                "previous_status": None,
                "new_status": app_info.get("status", "Applied"),
                "notes": f"Application submitted on {app_info.get('application_date') or 'record creation'}.",
                "created_at": app_info.get("created_at") or app_info.get("application_date")
            }
            timeline_events = [baseline_event]

        return {
            "application_id": app_id,
            "company_name": app_info.get("company_name"),
            "role_title": app_info.get("role_title"),
            "current_status": app_info.get("status"),
            "total_activities": len(timeline_events),
            "timeline": timeline_events
        }


def transition_application_status_with_timeline(
    application_id: str,
    student_id: str,
    new_status: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomically transitions an application status and appends a chronological audit event.
    """
    app_id = (application_id or "").strip()
    sid = (student_id or "").strip()
    target_status = (new_status or "").strip()

    if not app_id or not sid or not target_status:
        raise ValueError("application_id, student_id, and new_status are required.")

    with get_db_connection() as conn:
        ensure_application_timeline_table(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT status FROM job_applications WHERE id = ? AND student_id = ?", (app_id, sid))
        row = cursor.fetchone()
        if not row:
            raise PermissionError(f"Application '{app_id}' not found or unauthorized.")

        old_status = row["status"]

        # Update application table
        cursor.execute(
            "UPDATE job_applications SET status = ? WHERE id = ? AND student_id = ?",
            (target_status, app_id, sid)
        )

        # Log timeline
        log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO job_application_activity_timeline (
                id, application_id, student_id, event_type, previous_status, new_status, notes, created_at
            ) VALUES (?, ?, ?, 'status_change', ?, ?, ?, ?)
        """, (log_id, app_id, sid, old_status, target_status, notes, now))

        conn.commit()

    return {
        "success": True,
        "application_id": app_id,
        "previous_status": old_status,
        "current_status": target_status,
        "activity_id": log_id,
        "timestamp": now
    }
