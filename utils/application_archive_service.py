"""
Application renewal and archive management service (#620).
Enables archiving old applications to declutter active trackers,
restoring archived items, and renewing applications into fresh hiring cycles
without deleting historical records.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from db.connection import get_db_connection

def init_archive_support():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE job_applications ADD COLUMN is_archived INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE job_applications ADD COLUMN cycle_number INTEGER DEFAULT 1")
        except Exception:
            pass
        conn.commit()

init_archive_support()

def archive_application(app_id: str, student_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE job_applications
            SET is_archived = 1
            WHERE id = ? AND student_id = ?
        """, (app_id, student_id))
        conn.commit()
        return cursor.rowcount > 0

def restore_application(app_id: str, student_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE job_applications
            SET is_archived = 0
            WHERE id = ? AND student_id = ?
        """, (app_id, student_id))
        conn.commit()
        return cursor.rowcount > 0

def renew_application(app_id: str, student_id: str) -> Optional[Dict[str, Any]]:
    """Renews an old application into a new application cycle while keeping old history."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM job_applications WHERE id = ? AND student_id = ?", (app_id, student_id))
        row = cursor.fetchone()
        if not row:
            return None

        import uuid
        new_id = str(uuid.uuid4())
        new_cycle = (row["cycle_number"] or 1) + 1
        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO job_applications (
                id, student_id, company_name, role_title, status, application_date,
                notes, location, job_url, is_archived, cycle_number
            )
            VALUES (?, ?, ?, ?, 'Applied', ?, ?, ?, ?, 0, ?)
        """, (
            new_id,
            student_id,
            row["company_name"],
            row["role_title"],
            now_date,
            f"Renewed from cycle {row['cycle_number'] or 1}",
            row["location"] if "location" in row.keys() else None,
            row["job_url"] if "job_url" in row.keys() else None,
            new_cycle
        ))
        conn.commit()

    return {
        "success": True,
        "new_application_id": new_id,
        "cycle_number": new_cycle,
        "company_name": row["company_name"],
        "status": "Applied"
    }
