"""
Placement-Readiness Setup Checklist Service (#506)

Provides an onboarding & readiness checklist for newly registered and returning students.
Tracks 7 core placement preparation milestones:
1. upload_resume: Upload and analyze your primary resume
2. target_role: Set your target placement role / job profile
3. preferred_companies: Select target or preferred companies
4. job_description: Add a job description to tailor preparation
5. skill_assessment: Complete a diagnostic technical / aptitude skill assessment
6. interview_practice: Schedule or complete your first mock interview
7. application_details: Track your first campus or off-campus job application

Features:
- Dynamically checks student profile/database records for actual task completion.
- Supports manual override / task completion toggle.
- Dismissal status (dismiss temporarily for current session or permanently).
- Hides checklist automatically once 100% completed unless explicitly requested.
- REST API and template helper integration.
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection

DEFAULT_CHECKLIST_TASKS = [
    {
        "id": "upload_resume",
        "title": "Upload a Resume",
        "description": "Upload your primary resume to receive an ATS score, keyword review, and tailored feedback.",
        "action_url": "/",
        "action_label": "Upload Resume",
        "icon": "fa-file-arrow-up",
        "category": "Profile Foundation",
        "weight": 15
    },
    {
        "id": "target_role",
        "title": "Add a Target Role",
        "description": "Specify your desired placement profile (e.g., Software Development Engineer, Data Analyst).",
        "action_url": "/",
        "action_label": "Set Role",
        "icon": "fa-briefcase",
        "category": "Career Goals",
        "weight": 15
    },
    {
        "id": "preferred_companies",
        "title": "Select Preferred Companies",
        "description": "Shortlist dream and tier-1 companies to unlock company-specific interview questions.",
        "action_url": "/companies",
        "action_label": "Select Companies",
        "icon": "fa-building",
        "category": "Career Goals",
        "weight": 10
    },
    {
        "id": "job_description",
        "title": "Add a Job Description",
        "description": "Paste or upload a target job description to run precise ATS skill-gap matching.",
        "action_url": "/",
        "action_label": "Add JD",
        "icon": "fa-file-lines",
        "category": "Skill Alignment",
        "weight": 15
    },
    {
        "id": "skill_assessment",
        "title": "Complete a Skill Assessment",
        "description": "Take a diagnostic technical or subject-wise assessment to pinpoint strengths and gaps.",
        "action_url": "/skills-assessment",
        "action_label": "Start Assessment",
        "icon": "fa-chart-pie",
        "category": "Preparation Practice",
        "weight": 15
    },
    {
        "id": "interview_practice",
        "title": "Schedule First Interview Practice",
        "description": "Complete your first AI mock interview session with real-time feedback.",
        "action_url": "/interview",
        "action_label": "Practice Interview",
        "icon": "fa-microphone",
        "category": "Preparation Practice",
        "weight": 15
    },
    {
        "id": "application_details",
        "title": "Add Application Details",
        "description": "Log an active job application or campus drive to track interview stages and deadlines.",
        "action_url": "/applications",
        "action_label": "Track Application",
        "icon": "fa-list-check",
        "category": "Placement Tracking",
        "weight": 15
    }
]


class PlacementSetupChecklistService:
    """Service to evaluate and manage student placement setup checklist."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the student_setup_checklists table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_setup_checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                is_completed INTEGER DEFAULT 0,
                completed_at DATETIME,
                is_dismissed INTEGER DEFAULT 0,
                dismissed_at DATETIME,
                notes TEXT,
                UNIQUE(student_id, task_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_checklist_settings (
                student_id TEXT PRIMARY KEY,
                is_dismissed INTEGER DEFAULT 0,
                dismissed_until DATETIME,
                completed_banner_seen INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ssc_student_task 
            ON student_setup_checklists(student_id, task_id)
            """
        )
        conn.commit()
        conn.close()

    def detect_auto_completions(self, student_id: str) -> Dict[str, bool]:
        """
        Queries platform tables to automatically check if the student has completed tasks.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        completions = {task["id"]: False for task in DEFAULT_CHECKLIST_TASKS}

        # 1. Check resumes / analyses
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM analyses WHERE student_id = ? OR user_id = ?",
                (student_id, student_id)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["upload_resume"] = True
                completions["target_role"] = True
        except Exception:
            pass

        # 2. Check saved job descriptions
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM saved_job_descriptions WHERE student_id = ? OR user_id = ?",
                (student_id, student_id)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["job_description"] = True
        except Exception:
            pass

        # 3. Check mock interview sessions
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM interview_sessions WHERE student_id = ? OR user_id = ?",
                (student_id, student_id)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["interview_practice"] = True
        except Exception:
            pass

        # 4. Check applications
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM applications WHERE student_id = ? OR user_id = ?",
                (student_id, student_id)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["application_details"] = True
        except Exception:
            pass

        # 5. Check bookmarks / company interests
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM bookmarked_companies WHERE student_id = ? OR user_id = ?",
                (student_id, student_id)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["preferred_companies"] = True
        except Exception:
            pass

        # 6. Check skill assessments or coding practice
        try:
            cursor.execute(
                "SELECT COUNT(*) as count FROM student_coding_submissions WHERE student_id = ?",
                (student_id,)
            )
            row = cursor.fetchone()
            if row and row["count"] > 0:
                completions["skill_assessment"] = True
        except Exception:
            pass

        conn.close()
        return completions

    def get_student_checklist(self, student_id: str) -> Dict[str, Any]:
        """
        Retrieves the full setup checklist with completion percentages,
        task statuses, and visibility state for a student.
        """
        auto_completed = self.detect_auto_completions(student_id)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Query manual completion overrides and settings
        cursor.execute(
            "SELECT task_id, is_completed, completed_at FROM student_setup_checklists WHERE student_id = ?",
            (student_id,)
        )
        saved_rows = {r["task_id"]: dict(r) for r in cursor.fetchall()}

        cursor.execute(
            "SELECT is_dismissed, dismissed_until, completed_banner_seen FROM student_checklist_settings WHERE student_id = ?",
            (student_id,)
        )
        settings_row = cursor.fetchone()
        conn.close()

        is_dismissed = bool(settings_row["is_dismissed"]) if settings_row else False
        dismissed_until = settings_row["dismissed_until"] if settings_row else None

        # Check if dismissal period expired
        if is_dismissed and dismissed_until:
            try:
                until_dt = datetime.fromisoformat(dismissed_until)
                if datetime.now(timezone.utc) > until_dt:
                    is_dismissed = False
            except Exception:
                pass

        tasks_evaluated: List[Dict[str, Any]] = []
        completed_count = 0
        total_weight_completed = 0
        total_weight = sum(t["weight"] for t in DEFAULT_CHECKLIST_TASKS)

        for task in DEFAULT_CHECKLIST_TASKS:
            tid = task["id"]
            # A task is complete if either detected automatically or checked off manually
            manual_state = saved_rows.get(tid, {})
            is_done = bool(manual_state.get("is_completed", 0)) or auto_completed.get(tid, False)
            completed_at = manual_state.get("completed_at")

            if is_done:
                completed_count += 1
                total_weight_completed += task["weight"]

            tasks_evaluated.append({
                **task,
                "is_completed": is_done,
                "completed_at": completed_at,
                "is_auto_detected": auto_completed.get(tid, False)
            })

        progress_percent = round((total_weight_completed / total_weight) * 100) if total_weight > 0 else 0
        is_all_completed = completed_count == len(DEFAULT_CHECKLIST_TASKS)

        # Do not show checklist if all tasks are complete, unless user opens it
        should_display = not is_dismissed and not is_all_completed

        return {
            "student_id": student_id,
            "total_tasks": len(DEFAULT_CHECKLIST_TASKS),
            "completed_tasks": completed_count,
            "remaining_tasks": len(DEFAULT_CHECKLIST_TASKS) - completed_count,
            "progress_percent": progress_percent,
            "is_all_completed": is_all_completed,
            "is_dismissed": is_dismissed,
            "should_display": should_display,
            "tasks": tasks_evaluated
        }

    def update_task_status(
        self,
        student_id: str,
        task_id: str,
        is_completed: bool,
        notes: Optional[str] = None
    ) -> bool:
        """
        Manually marks a checklist task as completed or incomplete.
        """
        now_iso = datetime.now(timezone.utc).isoformat() if is_completed else None
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO student_setup_checklists
            (student_id, task_id, is_completed, completed_at, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, task_id) DO UPDATE SET
                is_completed = excluded.is_completed,
                completed_at = excluded.completed_at,
                notes = excluded.notes
            """,
            (student_id, task_id, 1 if is_completed else 0, now_iso, notes)
        )
        conn.commit()
        conn.close()
        return True

    def set_dismissal(self, student_id: str, is_dismissed: bool, hours: int = 24) -> bool:
        """
        Temporarily or permanently dismisses the setup checklist banner.
        """
        from datetime import timedelta
        until_iso = None
        if is_dismissed and hours > 0:
            until_iso = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO student_checklist_settings
            (student_id, is_dismissed, dismissed_until)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                is_dismissed = excluded.is_dismissed,
                dismissed_until = excluded.dismissed_until
            """,
            (student_id, 1 if is_dismissed else 0, until_iso)
        )
        conn.commit()
        conn.close()
        return True

    def reset_checklist(self, student_id: str) -> bool:
        """
        Resets checklist completion and dismissal for a fresh start.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM student_setup_checklists WHERE student_id = ?", (student_id,))
        cursor.execute("DELETE FROM student_checklist_settings WHERE student_id = ?", (student_id,))
        conn.commit()
        conn.close()
        return True


placement_checklist_service = PlacementSetupChecklistService()
