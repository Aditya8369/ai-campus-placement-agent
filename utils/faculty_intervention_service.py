"""
Faculty Intervention Queue Service (#786).
==========================================
Identifies students at risk of placement failure or disengagement:
1. Students who have not logged in for >= 14 days (Inactivity).
2. Students with missed application deadlines without milestone progression (Missed Deadlines).
3. Students who have stopped daily preparation drills and practice (Stopped Preparation).
4. Students who received repeated low mock interview scores (< 60%) (Repeated Low Scores).

Each intervention item includes:
- A privacy-preserving explanation that summarizes duration, counts, and timelines
  WITHOUT logging or exposing sensitive resume contents, interview answers, or private notes.
- A concrete, actionable suggested follow-up action for placement coordinators and faculty mentors.
- Coordinator workflow states: Pending, In Progress, Resolved, Snoozed, and Dismissed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import config
from db.connection import create_connection, get_connection, transaction
from db.interviews import get_student_interview_history

logger = logging.getLogger(__name__)

# Intervention Categories
CATEGORY_INACTIVITY = "inactivity"
CATEGORY_MISSED_DEADLINES = "missed_deadlines"
CATEGORY_STOPPED_PREP = "stopped_preparation"
CATEGORY_REPEATED_LOW_SCORES = "repeated_low_scores"

ALL_CATEGORIES = [
    CATEGORY_INACTIVITY,
    CATEGORY_MISSED_DEADLINES,
    CATEGORY_STOPPED_PREP,
    CATEGORY_REPEATED_LOW_SCORES,
]

# Urgency Levels
URGENCY_HIGH = "high"
URGENCY_MEDIUM = "medium"
URGENCY_LOW = "low"

# Intervention Statuses
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUS_DISMISSED = "dismissed"
STATUS_SNOOZED = "snoozed"

CATEGORY_METADATA = {
    CATEGORY_INACTIVITY: {
        "label": "Inactive Account",
        "badge_class": "bg-secondary-subtle text-secondary border border-secondary-subtle",
        "icon": "fa-solid fa-user-clock",
        "color": "#6c757d",
    },
    CATEGORY_MISSED_DEADLINES: {
        "label": "Missed Deadlines",
        "badge_class": "bg-danger-subtle text-danger border border-danger-subtle",
        "icon": "fa-solid fa-calendar-xmark",
        "color": "#dc3545",
    },
    CATEGORY_STOPPED_PREP: {
        "label": "Stalled Preparation",
        "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        "icon": "fa-solid fa-person-circle-exclamation",
        "color": "#ffc107",
    },
    CATEGORY_REPEATED_LOW_SCORES: {
        "label": "Low Interview Scores",
        "badge_class": "bg-info-subtle text-info-emphasis border border-info-subtle",
        "icon": "fa-solid fa-chart-line-down",
        "color": "#0dcaf0",
    },
}


def init_intervention_tables(db_path: Optional[str] = None) -> None:
    """Ensures faculty_interventions table and performance indexes exist."""
    with transaction(db_path) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty_interventions (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                student_name TEXT,
                student_email TEXT,
                department TEXT NOT NULL DEFAULT 'Computer Science',
                graduation_year INTEGER NOT NULL DEFAULT 2026,
                category TEXT NOT NULL,
                urgency_level TEXT NOT NULL DEFAULT 'medium',
                explanation TEXT NOT NULL,
                explanation_detail TEXT,
                suggested_action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                snoozed_until TEXT,
                action_notes TEXT,
                resolved_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fac_int_status ON faculty_interventions(status, urgency_level)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fac_int_student ON faculty_interventions(student_id, category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fac_int_category ON faculty_interventions(category)")


class FacultyInterventionService:
    """Comprehensive engine for faculty and placement coordinator intervention management."""

    @classmethod
    def scan_students_for_interventions(cls, db_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Scans all student accounts across login sessions, applications, preparation logs,
        and interview evaluations to identify students needing faculty intervention.
        """
        init_intervention_tables(db_path)
        now_dt = datetime.now(timezone.utc)
        today_str = now_dt.strftime("%Y-%m-%d")

        stats = {
            "scanned_students": 0,
            "created_interventions": 0,
            "updated_interventions": 0,
            "reopened_snoozed": 0,
            "by_category": {cat: 0 for cat in ALL_CATEGORIES},
        }

        with transaction(db_path) as cursor:
            # 1. Wake up any snoozed interventions whose snooze date has elapsed
            cursor.execute("""
                UPDATE faculty_interventions
                SET status = 'pending', snoozed_until = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE status = 'snoozed' AND snoozed_until IS NOT NULL AND snoozed_until <= ?
            """, (today_str,))
            stats["reopened_snoozed"] = cursor.rowcount

            # 2. Gather student roster
            # Union of users, student_batch_profiles, and student_profiles
            cursor.execute("""
                SELECT DISTINCT
                    COALESCE(u.id, sbp.user_id, sp.student_id, a.student_id) AS student_id,
                    COALESCE(u.name, sbp.user_id, sp.student_id) AS student_name,
                    COALESCE(u.email, '') AS student_email,
                    COALESCE(sbp.department, sp.department, 'Computer Science') AS department,
                    COALESCE(sbp.graduation_year, sp.graduation_year, 2026) AS graduation_year,
                    u.created_at AS user_created_at
                FROM (
                    SELECT id, name, email, created_at FROM users
                    UNION
                    SELECT user_id AS id, user_id AS name, '' AS email, created_at FROM student_batch_profiles
                    UNION
                    SELECT student_id AS id, student_id AS name, '' AS email, created_at FROM student_profiles
                    UNION
                    SELECT student_id AS id, student_id AS name, '' AS email, created_at FROM analyses WHERE student_id IS NOT NULL
                ) u
                LEFT JOIN student_batch_profiles sbp ON u.id = sbp.user_id
                LEFT JOIN student_profiles sp ON u.id = sp.student_id
                LEFT JOIN analyses a ON u.id = a.student_id
                WHERE u.id IS NOT NULL AND u.id NOT IN ('admin', 'coordinator', 'admin_user')
            """)
            students = [dict(r) for r in cursor.fetchall()]
            stats["scanned_students"] = len(students)

            for s in students:
                sid = s["student_id"]
                sname = s.get("student_name") or sid
                semail = s.get("student_email") or f"{sid}@campus.edu"
                dept = s.get("department") or "Computer Science"
                grad_year = s.get("graduation_year") or 2026

                # -------------------------------------------------------------
                # Trigger A: Inactivity (Have not logged in for >= 14 days)
                # -------------------------------------------------------------
                cursor.execute("""
                    SELECT MAX(last_seen_at) FROM auth_sessions WHERE user_id = ?
                """, (sid,))
                row = cursor.fetchone()
                last_seen_epoch = row[0] if row and row[0] is not None else None

                days_inactive = None
                last_active_date_str = "Never"

                if last_seen_epoch:
                    try:
                        last_seen_dt = datetime.fromtimestamp(last_seen_epoch, tz=timezone.utc)
                        days_inactive = (now_dt - last_seen_dt).days
                        last_active_date_str = last_seen_dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass
                elif s.get("user_created_at"):
                    try:
                        created_dt = datetime.fromisoformat(str(s["user_created_at"]).replace("Z", "+00:00"))
                        if created_dt.tzinfo is None:
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        days_inactive = (now_dt - created_dt).days
                        last_active_date_str = created_dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                if days_inactive is not None and days_inactive >= 14:
                    urgency = URGENCY_HIGH if days_inactive >= 30 or last_active_date_str == "Never" else URGENCY_MEDIUM
                    explanation = (
                        f"No login activity recorded for {days_inactive} days (last active: {last_active_date_str}). "
                        f"Student may be disengaged or facing portal access barriers."
                    )
                    explanation_detail = (
                        f"Lapsed portal access beyond the 14-day threshold. "
                        f"Personal credentials and account notes remain strictly confidential."
                    )
                    suggested_action = (
                        "Send an automated placement check-in email and verify whether the student intends "
                        "to participate in upcoming campus recruitment drives."
                    )
                    cls._upsert_intervention(
                        cursor=cursor,
                        student_id=sid,
                        student_name=sname,
                        student_email=semail,
                        department=dept,
                        graduation_year=grad_year,
                        category=CATEGORY_INACTIVITY,
                        urgency_level=urgency,
                        explanation=explanation,
                        explanation_detail=explanation_detail,
                        suggested_action=suggested_action,
                        stats=stats,
                    )

                # -------------------------------------------------------------
                # Trigger B: Missed Deadlines (Expired application deadlines)
                # -------------------------------------------------------------
                cursor.execute("""
                    SELECT id, deadline_date, status, company_name
                    FROM job_applications
                    WHERE student_id = ?
                      AND deadline_date IS NOT NULL
                      AND deadline_date != ''
                      AND deadline_date < ?
                      AND status NOT IN ('Offer', 'Accepted', 'Rejected', 'Withdrawn', 'Archived')
                    ORDER BY deadline_date ASC
                """, (sid, today_str))
                missed_apps = [dict(r) for r in cursor.fetchall()]

                if missed_apps:
                    missed_count = len(missed_apps)
                    oldest_deadline = missed_apps[0]["deadline_date"]
                    days_overdue = 0
                    try:
                        d_dt = datetime.strptime(oldest_deadline[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        days_overdue = max(0, (now_dt - d_dt).days)
                    except Exception:
                        pass

                    urgency = URGENCY_HIGH if (missed_count >= 2 or days_overdue >= 7) else URGENCY_MEDIUM
                    explanation = (
                        f"{missed_count} job application deadline(s) passed without status progression "
                        f"(oldest deadline expired {days_overdue} days ago on {oldest_deadline[:10]})."
                    )
                    explanation_detail = (
                        f"Tracked applications passed their cutoff dates while still in pending states. "
                        f"Company identities and candidate application notes are redacted to preserve confidentiality."
                    )
                    suggested_action = (
                        "Schedule an advisory check-in with the student to verify submission status, "
                        "resolve application hurdles, and provide deadline guidance for active drives."
                    )
                    cls._upsert_intervention(
                        cursor=cursor,
                        student_id=sid,
                        student_name=sname,
                        student_email=semail,
                        department=dept,
                        graduation_year=grad_year,
                        category=CATEGORY_MISSED_DEADLINES,
                        urgency_level=urgency,
                        explanation=explanation,
                        explanation_detail=explanation_detail,
                        suggested_action=suggested_action,
                        stats=stats,
                    )

                # -------------------------------------------------------------
                # Trigger C: Stopped Preparation (No activity for >= 14 days)
                # -------------------------------------------------------------
                cursor.execute("""
                    SELECT last_activity_date, total_active_days
                    FROM student_streaks
                    WHERE student_id = ?
                """, (sid,))
                streak_row = cursor.fetchone()

                cursor.execute("""
                    SELECT MAX(activity_date) FROM preparation_activity_log WHERE student_id = ?
                """, (sid,))
                prep_max_row = cursor.fetchone()

                last_prep_date = None
                if streak_row and streak_row[0]:
                    last_prep_date = streak_row[0]
                elif prep_max_row and prep_max_row[0]:
                    last_prep_date = prep_max_row[0]

                if last_prep_date:
                    try:
                        last_prep_dt = datetime.strptime(last_prep_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        days_since_prep = (now_dt - last_prep_dt).days
                    except Exception:
                        days_since_prep = 0

                    if days_since_prep >= 14:
                        urgency = URGENCY_HIGH if days_since_prep >= 28 else URGENCY_MEDIUM
                        explanation = (
                            f"Preparation halted: 0 practice drills, coding submissions, or mock interviews "
                            f"recorded over the past {days_since_prep} days (last drill: {last_prep_date[:10]})."
                        )
                        explanation_detail = (
                            f"Daily preparation cadence has halted after previous active involvement. "
                            f"Practice question answers and personal notes remain confidential."
                        )
                        suggested_action = (
                            "Assign foundational aptitude and DSA practice modules; schedule a faculty mentor "
                            "check-in to restore preparation momentum."
                        )
                        cls._upsert_intervention(
                            cursor=cursor,
                            student_id=sid,
                            student_name=sname,
                            student_email=semail,
                            department=dept,
                            graduation_year=grad_year,
                            category=CATEGORY_STOPPED_PREP,
                            urgency_level=urgency,
                            explanation=explanation,
                            explanation_detail=explanation_detail,
                            suggested_action=suggested_action,
                            stats=stats,
                        )

                # -------------------------------------------------------------
                # Trigger D: Repeated Low Interview Scores (< 60% on >= 2 sessions)
                # -------------------------------------------------------------
                try:
                    history = get_student_interview_history(student_id=sid, db_path=db_path)
                    if history:
                        # Sessions with recorded scores
                        scored_sessions = [h for h in history if h.get("average_score", 0) > 0 and h.get("answered_questions", 0) > 0]
                        # Filter sessions where average score < 60
                        low_sessions = [s for s in scored_sessions if s["average_score"] < 60.0]

                        if len(low_sessions) >= 2:
                            low_count = len(low_sessions)
                            latest_score = low_sessions[0]["average_score"]
                            avg_low = round(sum(s["average_score"] for s in low_sessions) / low_count, 1)

                            urgency = URGENCY_HIGH if avg_low < 50.0 else URGENCY_MEDIUM
                            explanation = (
                                f"Multiple low mock interview evaluations: scored below 60% on {low_count} sessions "
                                f"(average low score: {avg_low}%, latest: {latest_score}%)."
                            )
                            explanation_detail = (
                                f"Identified persistent difficulties in technical depth, communication clarity, or STAR structure. "
                                f"Full interview transcripts and question answers remain confidential."
                            )
                            suggested_action = (
                                "Arrange a 1-on-1 faculty coaching session and assign STAR-method behavioral response "
                                "and fundamental problem-solving practice."
                            )
                            cls._upsert_intervention(
                                cursor=cursor,
                                student_id=sid,
                                student_name=sname,
                                student_email=semail,
                                department=dept,
                                graduation_year=grad_year,
                                category=CATEGORY_REPEATED_LOW_SCORES,
                                urgency_level=urgency,
                                explanation=explanation,
                                explanation_detail=explanation_detail,
                                suggested_action=suggested_action,
                                stats=stats,
                            )
                except Exception as exc:
                    logger.debug(f"Error checking interview scores for {sid}: {exc}")

        return stats

    @classmethod
    def _upsert_intervention(
        cls,
        cursor: sqlite3.Cursor,
        student_id: str,
        student_name: str,
        student_email: str,
        department: str,
        graduation_year: int,
        category: str,
        urgency_level: str,
        explanation: str,
        explanation_detail: str,
        suggested_action: str,
        stats: Dict[str, Any],
    ) -> None:
        """Inserts a new intervention or updates an existing pending/in_progress one."""
        cursor.execute("""
            SELECT id, status FROM faculty_interventions
            WHERE student_id = ? AND category = ? AND status IN ('pending', 'in_progress', 'snoozed')
            ORDER BY created_at DESC LIMIT 1
        """, (student_id, category))
        existing = cursor.fetchone()

        if existing:
            # Update explanation, urgency, and timestamp while preserving coordinator notes
            cursor.execute("""
                UPDATE faculty_interventions
                SET urgency_level = ?,
                    explanation = ?,
                    explanation_detail = ?,
                    suggested_action = ?,
                    student_name = ?,
                    student_email = ?,
                    department = ?,
                    graduation_year = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                urgency_level,
                explanation,
                explanation_detail,
                suggested_action,
                student_name,
                student_email,
                department,
                graduation_year,
                existing[0],
            ))
            stats["updated_interventions"] += 1
        else:
            # Check if resolved recently (within last 3 days) to avoid immediate re-alerting
            cursor.execute("""
                SELECT id FROM faculty_interventions
                WHERE student_id = ? AND category = ? AND status = 'resolved'
                  AND updated_at >= datetime('now', '-3 days')
            """, (student_id, category))
            if cursor.fetchone():
                return

            new_id = uuid.uuid4().hex
            cursor.execute("""
                INSERT INTO faculty_interventions (
                    id, student_id, student_name, student_email, department, graduation_year,
                    category, urgency_level, explanation, explanation_detail, suggested_action,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                new_id,
                student_id,
                student_name,
                student_email,
                department,
                graduation_year,
                category,
                urgency_level,
                explanation,
                explanation_detail,
                suggested_action,
            ))
            stats["created_interventions"] += 1
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

    @classmethod
    def get_intervention_queue(
        cls,
        category: Optional[str] = None,
        status: Optional[str] = "pending",
        urgency: Optional[str] = None,
        search: Optional[str] = None,
        department: Optional[str] = None,
        limit: int = 100,
        db_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves filtered intervention queue items with enriched presentation metadata.
        """
        init_intervention_tables(db_path)

        query = "SELECT * FROM faculty_interventions WHERE 1=1"
        params: List[Any] = []

        if status and status.lower() != "all":
            query += " AND status = ?"
            params.append(status.lower())

        if category and category.lower() != "all":
            query += " AND category = ?"
            params.append(category.lower())

        if urgency and urgency.lower() != "all":
            query += " AND urgency_level = ?"
            params.append(urgency.lower())

        if department and department.lower() != "all":
            query += " AND department = ?"
            params.append(department)

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            query += " AND (LOWER(student_name) LIKE ? OR LOWER(student_email) LIKE ? OR LOWER(student_id) LIKE ? OR LOWER(department) LIKE ?)"
            params.extend([term, term, term, term])

        # Priority ordering: high urgency first, then pending before in_progress, then newest
        query += """
            ORDER BY 
                CASE urgency_level WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END ASC,
                CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'snoozed' THEN 3 ELSE 4 END ASC,
                created_at DESC
            LIMIT ?
        """
        params.append(limit)

        with get_connection(db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                cat = item.get("category", CATEGORY_INACTIVITY)
                meta = CATEGORY_METADATA.get(cat, CATEGORY_METADATA[CATEGORY_INACTIVITY])
                item["category_label"] = meta["label"]
                item["category_badge_class"] = meta["badge_class"]
                item["category_icon"] = meta["icon"]
                item["category_color"] = meta["color"]

                # Urgency badge classes
                urg = item.get("urgency_level", URGENCY_MEDIUM)
                if urg == URGENCY_HIGH:
                    item["urgency_badge_class"] = "bg-danger text-white"
                elif urg == URGENCY_MEDIUM:
                    item["urgency_badge_class"] = "bg-warning text-dark"
                else:
                    item["urgency_badge_class"] = "bg-secondary text-white"

                results.append(item)
            return results

    @classmethod
    def get_intervention_summary_metrics(cls, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Calculates aggregated intervention queue metrics for dashboard overview badges."""
        init_intervention_tables(db_path)

        with get_connection(db_path) as conn:
            # Active items (pending or in_progress)
            active_row = conn.execute("""
                SELECT 
                    COUNT(*) as total_active,
                    SUM(CASE WHEN urgency_level = 'high' THEN 1 ELSE 0 END) as high_urgency,
                    SUM(CASE WHEN category = 'inactivity' THEN 1 ELSE 0 END) as inactivity,
                    SUM(CASE WHEN category = 'missed_deadlines' THEN 1 ELSE 0 END) as missed_deadlines,
                    SUM(CASE WHEN category = 'stopped_preparation' THEN 1 ELSE 0 END) as stopped_prep,
                    SUM(CASE WHEN category = 'repeated_low_scores' THEN 1 ELSE 0 END) as repeated_low_scores
                FROM faculty_interventions
                WHERE status IN ('pending', 'in_progress')
            """).fetchone()

            resolved_row = conn.execute("""
                SELECT COUNT(*) FROM faculty_interventions WHERE status = 'resolved'
            """).fetchone()

            departments_rows = conn.execute("""
                SELECT DISTINCT department FROM faculty_interventions WHERE department IS NOT NULL AND department != '' ORDER BY department ASC
            """).fetchall()

            return {
                "total_active": active_row["total_active"] if active_row else 0,
                "high_urgency": active_row["high_urgency"] or 0 if active_row else 0,
                "inactivity_count": active_row["inactivity"] or 0 if active_row else 0,
                "missed_deadlines_count": active_row["missed_deadlines"] or 0 if active_row else 0,
                "stopped_prep_count": active_row["stopped_prep"] or 0 if active_row else 0,
                "repeated_low_scores_count": active_row["repeated_low_scores"] or 0 if active_row else 0,
                "resolved_count": resolved_row[0] if resolved_row else 0,
                "departments": [r[0] for r in departments_rows] if departments_rows else ["Computer Science", "Information Technology", "Electronics"],
            }

    @classmethod
    def record_faculty_action(
        cls,
        intervention_id: str,
        new_status: str,
        notes: Optional[str] = None,
        resolved_by: Optional[str] = None,
        snooze_days: int = 7,
        db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Updates an intervention's workflow status and logs coordinator follow-up notes.
        Supported statuses: 'in_progress', 'resolved', 'dismissed', 'snoozed', 'pending'.
        """
        init_intervention_tables(db_path)

        valid_statuses = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_DISMISSED, STATUS_SNOOZED)
        clean_status = new_status.strip().lower()
        if clean_status not in valid_statuses:
            return {"success": False, "error": f"Invalid status '{new_status}'. Allowed: {', '.join(valid_statuses)}"}

        now_dt = datetime.now(timezone.utc)
        snoozed_until_str = None
        if clean_status == STATUS_SNOOZED:
            snooze_days = max(1, min(snooze_days, 60))
            snoozed_until_str = (now_dt + timedelta(days=snooze_days)).strftime("%Y-%m-%d")

        with transaction(db_path) as cursor:
            cursor.execute("SELECT id, action_notes FROM faculty_interventions WHERE id = ?", (intervention_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": f"Intervention '{intervention_id}' not found."}

            existing_notes = row[1] or ""
            updated_notes = existing_notes
            if notes and notes.strip():
                timestamp = now_dt.strftime("%Y-%m-%d %H:%M UTC")
                actor = resolved_by or "Coordinator"
                entry = f"[{timestamp} by {actor}] {notes.strip()}"
                updated_notes = f"{existing_notes}\n{entry}".strip() if existing_notes else entry

            cursor.execute("""
                UPDATE faculty_interventions
                SET status = ?,
                    snoozed_until = ?,
                    action_notes = ?,
                    resolved_by = COALESCE(?, resolved_by),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                clean_status,
                snoozed_until_str,
                updated_notes,
                resolved_by,
                intervention_id,
            ))

        return {
            "success": True,
            "intervention_id": intervention_id,
            "new_status": clean_status,
            "snoozed_until": snoozed_until_str,
            "message": f"Intervention status updated to '{clean_status}'.",
        }

    @classmethod
    def create_manual_intervention(
        cls,
        student_id: str,
        category: str,
        explanation: str,
        suggested_action: str,
        urgency_level: str = URGENCY_MEDIUM,
        student_name: Optional[str] = None,
        student_email: Optional[str] = None,
        department: str = "Computer Science",
        graduation_year: int = 2026,
        explanation_detail: Optional[str] = None,
        created_by: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Allows faculty coordinators to manually raise an intervention item."""
        init_intervention_tables(db_path)
        new_id = uuid.uuid4().hex

        with transaction(db_path) as cursor:
            cursor.execute("""
                INSERT INTO faculty_interventions (
                    id, student_id, student_name, student_email, department, graduation_year,
                    category, urgency_level, explanation, explanation_detail, suggested_action,
                    status, resolved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                new_id,
                student_id,
                student_name or student_id,
                student_email or f"{student_id}@campus.edu",
                department,
                graduation_year,
                category,
                urgency_level,
                explanation,
                explanation_detail or "Manually flagged by faculty placement coordinator.",
                suggested_action,
                created_by,
            ))

        return {"success": True, "id": new_id, "message": "Manual intervention created successfully."}

    @classmethod
    def get_intervention_by_id(cls, intervention_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a single intervention by ID."""
        init_intervention_tables(db_path)
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT * FROM faculty_interventions WHERE id = ?", (intervention_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            cat = item.get("category", CATEGORY_INACTIVITY)
            meta = CATEGORY_METADATA.get(cat, CATEGORY_METADATA[CATEGORY_INACTIVITY])
            item["category_label"] = meta["label"]
            item["category_badge_class"] = meta["badge_class"]
            item["category_icon"] = meta["icon"]
            item["category_color"] = meta["color"]
            return item
