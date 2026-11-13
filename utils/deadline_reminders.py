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

from utils.database import (
    get_db_connection,
    get_email_notification_preferences,
    get_user_by_id
)
from utils.email_service import EmailNotificationService

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


def scan_and_generate_student_reminders(
    student_id: str,
    reference_date: Optional[datetime.date] = None
) -> List[Dict[str, Any]]:
    """
    Scans a student's active job applications and calendar deadlines,
    identifying approaching deadlines and upserting reminder records (#251, #298).
    Supports explicit reference_date for deterministic clock testing.
    """
    sid = (student_id or "").strip()
    if not sid:
        return []

    preferences = get_student_deadline_preferences(sid)
    lead_days = preferences.get("alert_lead_days", 3)

    today = reference_date or datetime.now(timezone.utc).date()
    max_scan_date = today + timedelta(days=lead_days)

    generated_reminders: List[Dict[str, Any]] = []

    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()

        # 1. Scan job applications with deadlines (notes, fields, or deadline_date)
        # Check available columns in job_applications
        cursor.execute("PRAGMA table_info(job_applications)")
        app_cols = [col[1] for col in cursor.fetchall()]
        has_deadline_col = "deadline_date" in app_cols

        query = f"""
            SELECT id, company_name, role_title, application_date, notes
            {', deadline_date' if has_deadline_col else ''}
            FROM job_applications
            WHERE student_id = ? AND LOWER(status) NOT IN ('rejected', 'offer_accepted', 'withdrawn')
        """
        cursor.execute(query, (sid,))
        apps = cursor.fetchall()

        for a in apps:
            app_id = a["id"]
            comp = a["company_name"]
            role = a["role_title"]
            app_date = a["application_date"]
            notes = a["notes"] or ""
            explicit_deadline = a["deadline_date"] if has_deadline_col and "deadline_date" in a.keys() else None

            # Priority 1: dedicated deadline_date field (#298)
            # Priority 2: deadline parsed from notes text
            # Priority 3: fallback to application_date
            parsed_deadline = _parse_iso_date(explicit_deadline) or _extract_date_from_string(notes) or _extract_date_from_string(app_date)
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


def send_upcoming_deadline_reminders(
    student_id: Optional[str] = None,
    reference_time: Optional[datetime] = None,
    days_ahead: int = 2
) -> Dict[str, Any]:
    """
    Scheduled job / CLI service function (#298):
    Finds active application & interview items due in the next `days_ahead` days (default: 2 days)
    and sends exactly one reminder email per item.

    Guarantees:
    - Reminders are sent once for each upcoming deadline (records notification_dispatched_at).
    - Students who turned email reminders off in preferences receive nothing.
    - A failed email send does not crash the scheduler loop.
    - Never logs email bodies.
    - Unit tests can mock the mail client and supply fixed reference_time clock.
    """
    ref_now = reference_time or datetime.now(timezone.utc)
    if isinstance(ref_now, datetime):
        ref_date = ref_now.date()
    else:
        ref_date = ref_now

    email_svc = EmailNotificationService()

    # Step 1: Identify candidate student IDs to scan
    candidate_ids: List[str] = []
    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        if student_id and student_id.strip():
            candidate_ids = [student_id.strip()]
        else:
            cursor.execute("""
                SELECT DISTINCT student_id FROM job_applications
                UNION
                SELECT DISTINCT student_id FROM preparation_calendar_events
                UNION
                SELECT DISTINCT student_id FROM student_deadline_preferences
            """)
            candidate_ids = [r[0] for r in cursor.fetchall() if r[0]]

    # Step 2: Ensure reminders are up-to-date for each candidate
    for sid in candidate_ids:
        try:
            scan_and_generate_student_reminders(sid, reference_date=ref_date)
        except Exception as scan_err:
            logger.warning(f"Error scanning deadlines for student {sid}: {scan_err}")

    # Step 3: Query unacknowledged, unsent reminder items
    sent_count = 0
    skipped_count = 0
    failed_count = 0
    sent_details: List[Dict[str, Any]] = []

    with get_db_connection() as conn:
        ensure_deadline_reminders_table(conn)
        cursor = conn.cursor()
        if student_id and student_id.strip():
            cursor.execute("""
                SELECT id, student_id, source_type, source_id, title, company_name,
                       deadline_date, urgency_level
                FROM application_deadline_reminders
                WHERE is_acknowledged = 0
                  AND notification_dispatched_at IS NULL
                  AND student_id = ?
                ORDER BY deadline_date ASC
            """, (student_id.strip(),))
        else:
            cursor.execute("""
                SELECT id, student_id, source_type, source_id, title, company_name,
                       deadline_date, urgency_level
                FROM application_deadline_reminders
                WHERE is_acknowledged = 0
                  AND notification_dispatched_at IS NULL
                ORDER BY deadline_date ASC
            """)
        pending_reminders = cursor.fetchall()

    for rem in pending_reminders:
        rem_id = rem["id"]
        sid = rem["student_id"]
        comp = rem["company_name"]
        title = rem["title"]
        d_str = rem["deadline_date"]

        parsed_deadline = _parse_iso_date(d_str)
        if not parsed_deadline:
            continue

        days_remaining = (parsed_deadline - ref_date).days
        # Target: items due in the next 2 days (0 <= days_remaining <= days_ahead)
        if not (0 <= days_remaining <= days_ahead):
            continue

        # Check student notification preferences
        deadline_pref = get_student_deadline_preferences(sid)
        email_pref = get_email_notification_preferences(sid)

        # Check if disabled either in student_deadline_preferences or email_notification_preferences
        if (
            not deadline_pref.get("email_alerts_enabled", 1)
            or not email_pref.get("email_enabled", True)
            or not email_pref.get("notify_deadline_reminder", True)
        ):
            logger.info(f"Skipping deadline email for student '{sid}': reminders turned off in preferences.")
            skipped_count += 1
            continue

        # Resolve destination email address and candidate name
        user_info = get_user_by_id(sid)
        recipient_email = (
            email_pref.get("email")
            or (user_info and user_info.get("email"))
            or f"{sid}@student.campus.edu"
        ).strip()

        student_name = (user_info and user_info.get("name")) or sid

        # Dispatch email
        try:
            sent = email_svc.send_deadline_reminder_email(
                recipient_email=recipient_email,
                student_name=student_name,
                title=title,
                company_name=comp,
                deadline_date=d_str,
                days_remaining=days_remaining
            )
            if sent:
                now_iso = ref_now.isoformat() if isinstance(ref_now, datetime) else datetime.now(timezone.utc).isoformat()
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute("""
                        UPDATE application_deadline_reminders
                        SET notification_dispatched_at = ?
                        WHERE id = ?
                    """, (now_iso, rem_id))
                    conn.commit()

                sent_count += 1
                sent_details.append({
                    "reminder_id": rem_id,
                    "student_id": sid,
                    "company_name": comp,
                    "title": title,
                    "deadline_date": d_str,
                    "days_remaining": days_remaining,
                    "recipient_email": recipient_email
                })
                logger.info(f"Deadline reminder sent for {comp} ({title}) to {recipient_email}")
            else:
                failed_count += 1
                logger.error(f"Email service returned failure for deadline reminder {rem_id} to {recipient_email}")
        except Exception as ex:
            # A failed email send must not crash the scheduler
            failed_count += 1
            logger.error(f"Unexpected error sending deadline reminder {rem_id} to {recipient_email}: {ex}")

    logger.info(
        f"Completed deadline reminder job: scanned_students={len(candidate_ids)}, "
        f"sent={sent_count}, skipped={skipped_count}, failed={failed_count}"
    )

    return {
        "status": "success",
        "scanned_students": len(candidate_ids),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "reminders_sent": sent_details
    }

