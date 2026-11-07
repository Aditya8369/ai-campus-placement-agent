"""
Job Application Deadline Reminder System (#251)
================================================
Monitors student job application deadlines, upcoming interviews, and preparation milestones,
generating prioritized reminder schedules and alerts.

Key Capabilities:
1. Multi-source deadline ingestion:
   - Tracks application deadlines directly from job_applications.
   - Evaluates deadline events from calendar_events.
2. Deadline Proximity Evaluation:
   - Urgent / Immediate: Due within 24 hours (1 day).
   - Upcoming: Due within 3 days.
   - Approaching: Due within 7 days.
   - Overdue: Passed deadlines.
3. Notification state tracking (prevents spam and duplicate alert dispatches).
4. Configurable student notification preferences (frequency, days in advance).
5. Comprehensive API endpoints for dashboard widgets and proactive alert feeds.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import uuid

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def ensure_deadline_reminders_table(conn: sqlite3.Connection) -> None:
    """Creates the application_deadline_reminders and reminder_preferences tables."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_deadline_reminders (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'job_application',
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            company_name TEXT NOT NULL,
            deadline_date TEXT NOT NULL,
            urgency_level TEXT NOT NULL DEFAULT 'upcoming',
            is_acknowledged INTEGER NOT NULL DEFAULT 0,
            notification_dispatched_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, source_id, deadline_date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_deadline_preferences (
            student_id TEXT PRIMARY KEY,
            alert_lead_days INTEGER NOT NULL DEFAULT 3,
            email_alerts_enabled INTEGER NOT NULL DEFAULT 1,
            dashboard_alerts_enabled INTEGER NOT NULL DEFAULT 1,
            urgency_threshold_hours INTEGER NOT NULL DEFAULT 24,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_student ON application_deadline_reminders(student_id, is_acknowledged)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_date ON application_deadline_reminders(deadline_date)")
    conn.commit()


def get_student_deadline_preferences(student_id: str) -> Dict[str, Any]:
    """Retrieves or creates default reminder preferences for a student."""
    sid = (student_id or "").strip()
    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM student_deadline_preferences WHERE student_id = ?", (sid,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        
        # Default configuration
        default_pref = {
            "student_id": sid,
            "alert_lead_days": 3,
            "email_alerts_enabled": 1,
            "dashboard_alerts_enabled": 1,
            "urgency_threshold_hours": 24,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        cursor.execute("""
            INSERT INTO student_deadline_preferences (
                student_id, alert_lead_days, email_alerts_enabled,
                dashboard_alerts_enabled, urgency_threshold_hours, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            sid,
            default_pref["alert_lead_days"],
            default_pref["email_alerts_enabled"],
            default_pref["dashboard_alerts_enabled"],
            default_pref["urgency_threshold_hours"],
            default_pref["updated_at"]
        ))
        conn.commit()
        return default_pref


def update_student_deadline_preferences(
    student_id: str,
    alert_lead_days: Optional[int] = None,
    email_alerts_enabled: Optional[bool] = None,
    dashboard_alerts_enabled: Optional[bool] = None,
    urgency_threshold_hours: Optional[int] = None
) -> Dict[str, Any]:
    """Updates deadline alert settings for a student."""
    current = get_student_deadline_preferences(student_id)
    new_lead_days = alert_lead_days if alert_lead_days is not None else current["alert_lead_days"]
    new_email = int(email_alerts_enabled) if email_alerts_enabled is not None else current["email_alerts_enabled"]
    new_dash = int(dashboard_alerts_enabled) if dashboard_alerts_enabled is not None else current["dashboard_alerts_enabled"]
    new_thresh = urgency_threshold_hours if urgency_threshold_hours is not None else current["urgency_threshold_hours"]
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE student_deadline_preferences
            SET alert_lead_days = ?, email_alerts_enabled = ?,
                dashboard_alerts_enabled = ?, urgency_threshold_hours = ?, updated_at = ?
            WHERE student_id = ?
        """, (new_lead_days, new_email, new_dash, new_thresh, now, student_id))
        conn.commit()

    return get_student_deadline_preferences(student_id)


def scan_and_generate_student_reminders(student_id: str) -> List[Dict[str, Any]]:
    """
    Scans a student's active job applications and calendar deadlines,
    identifying approaching deadlines and upserting reminder records.
    """
    sid = (student_id or "").strip()
    if not sid:
        return []

    preferences = get_student_deadline_preferences(sid)
    lead_days = preferences.get("alert_lead_days", 3)

    today = datetime.now(timezone.utc).date()
    max_scan_date = today + timedelta(days=lead_days)

    generated_reminders: List[Dict[str, Any]] = []

    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()

        # 1. Scan job applications with deadlines (notes or fields)
        cursor.execute("""
            SELECT id, company_name, role_title, application_date, notes
            FROM job_applications
            WHERE student_id = ? AND LOWER(status) NOT IN ('rejected', 'offer_accepted', 'withdrawn')
        """, (sid,))
        apps = cursor.fetchall()

        for a in apps:
            app_id, comp, role, app_date, notes = a["id"], a["company_name"], a["role_title"], a["application_date"], a["notes"] or ""
            # Inspect if notes or metadata contain a deadline date format
            parsed_deadline = _extract_date_from_string(notes) or _extract_date_from_string(app_date)
            if parsed_deadline:
                rem = _process_candidate_deadline(
                    conn, sid, "job_application", app_id,
                    f"Application Deadline: {role}", comp, parsed_deadline, today
                )
                if rem:
                    generated_reminders.append(rem)

        # 2. Scan calendar events categorized as 'deadline'
        cursor.execute("""
            SELECT id, title, company_name, event_date
            FROM preparation_calendar_events
            WHERE student_id = ? AND LOWER(event_type) = 'deadline'
        """, (sid,))
        cal_events = cursor.fetchall()

        for c in cal_events:
            c_id, title, comp, e_date = c["id"], c["title"], c["company_name"] or "Company", c["event_date"]
            parsed_date = _parse_iso_date(e_date)
            if parsed_date:
                rem = _process_candidate_deadline(
                    conn, sid, "calendar_event", c_id,
                    title, comp, parsed_date, today
                )
                if rem:
                    generated_reminders.append(rem)

        conn.commit()

    return list_student_reminders(sid)


def list_student_reminders(
    student_id: str,
    include_acknowledged: bool = False,
    urgency_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Lists saved reminder items for a candidate."""
    sid = (student_id or "").strip()
    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        query = "SELECT * FROM application_deadline_reminders WHERE student_id = ?"
        params: List[Any] = [sid]

        if not include_acknowledged:
            query += " AND is_acknowledged = 0"

        if urgency_filter and urgency_filter.lower() != "all":
            query += " AND urgency_level = ?"
            params.append(urgency_filter.lower())

        query += " ORDER BY deadline_date ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def acknowledge_deadline_reminder(student_id: str, reminder_id: str) -> bool:
    """Marks a reminder as acknowledged / dismissed by the student."""
    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE application_deadline_reminders
            SET is_acknowledged = 1
            WHERE id = ? AND student_id = ?
        """, (reminder_id, student_id))
        conn.commit()
        return cursor.rowcount > 0


def _process_candidate_deadline(
    conn: sqlite3.Connection,
    student_id: str,
    source_type: str,
    source_id: str,
    title: str,
    company_name: str,
    deadline_date: datetime.date,
    today: datetime.date
) -> Optional[Dict[str, Any]]:
    """Helper to categorize and upsert deadline reminder record."""
    delta_days = (deadline_date - today).days

    if delta_days < 0:
        urgency = "overdue"
    elif delta_days <= 1:
        urgency = "critical"
    elif delta_days <= 3:
        urgency = "upcoming"
    else:
        urgency = "approaching"

    deadline_str = deadline_date.isoformat()
    rem_id = str(uuid.uuid4())

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO application_deadline_reminders (
            id, student_id, source_type, source_id, title, company_name,
            deadline_date, urgency_level, is_acknowledged
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(student_id, source_id, deadline_date) DO UPDATE SET
            urgency_level = excluded.urgency_level,
            title = excluded.title
    """, (
        rem_id, student_id, source_type, source_id, title, company_name,
        deadline_str, urgency
    ))

    return {
        "student_id": student_id,
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "company_name": company_name,
        "deadline_date": deadline_str,
        "urgency_level": urgency
    }


def _parse_iso_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Attempts to parse YYYY-MM-DD or full ISO strings into a date object."""
    if not date_str:
        return None
    try:
        clean = date_str.split("T")[0].split(" ")[0].strip()
        return datetime.strptime(clean, "%Y-%m-%d").date()
    except Exception:
        return None


def _extract_date_from_string(text: Optional[str]) -> Optional[datetime.date]:
    """Finds date patterns like 2026-11-28 or Nov 28, 2026 within free text."""
    if not text:
        return None
    import re
    # Try YYYY-MM-DD
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        return _parse_iso_date(match.group(1))

    # Try Month DD, YYYY
    match_str = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b", text, re.IGNORECASE)
    if match_str:
        month_str, day_str, year_str = match_str.groups()
        try:
            return datetime.strptime(f"{month_str[:3]} {day_str} {year_str}", "%b %d %Y").date()
        except Exception:
            return None
    return None
