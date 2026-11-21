"""
Daily Placement Preparation Dashboard Service (#512)

Aggregates a unified 'Today' view for students:
- Today's coding challenges and spaced-repetition due items
- Scheduled mock interviews or peer practice due today
- Approaching job application deadlines (within 3 days)
- Daily preparation streak and study goals progress
- AI placement readiness tip / daily focus recommendation
- Daily completed tasks check-off and streak tracking
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_daily_prep_table():
    """Initializes database schema for daily tasks and goal tracking."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_placement_prep_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    task_date TEXT NOT NULL, -- 'YYYY-MM-DD'
                    task_type TEXT NOT NULL, -- 'coding', 'interview', 'application', 'revision'
                    title TEXT NOT NULL,
                    target_count INTEGER DEFAULT 1,
                    completed_count INTEGER DEFAULT 0,
                    is_completed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, task_date, title)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dppt_user_date ON daily_placement_prep_tasks(user_id, task_date)")
    finally:
        conn.close()


init_daily_prep_table()


class DailyPrepDashboardService:
    """Consolidates today's action items, deadlines, streak, and focus advice."""

    DAILY_TIPS = [
        "Focus on time-boxed problem solving: spend 25 minutes solving DSA problems without looking at hints.",
        "Review your STAR stories for behavioral interviews: ensure each has a quantified result.",
        "Check your job applications due this week and follow up on submissions older than 7 days.",
        "Practice explaining technical concepts aloud to build verbal confidence.",
        "Spend 15 minutes reviewing core CS fundamentals (OS, DBMS, Computer Networks)."
    ]

    @classmethod
    def get_today_dashboard(cls, user_id: str) -> Dict[str, Any]:
        """
        Compiles the complete Daily Placement Prep agenda for the student.
        """
        today_str = datetime.date.today().isoformat()
        now_dt = datetime.datetime.now(datetime.timezone.utc)

        # 1. Initialize default daily tasks if none exist for today
        cls._ensure_default_daily_tasks(user_id, today_str)

        # 2. Fetch today's tasks
        conn = _get_db_connection()
        tasks = []
        try:
            task_rows = conn.execute(
                "SELECT * FROM daily_placement_prep_tasks WHERE user_id = ? AND task_date = ? ORDER BY id ASC",
                (user_id, today_str)
            ).fetchall()
            tasks = [
                {
                    "id": r["id"],
                    "task_type": r["task_type"],
                    "title": r["title"],
                    "target_count": r["target_count"],
                    "completed_count": r["completed_count"],
                    "is_completed": bool(r["is_completed"])
                }
                for r in task_rows
            ]

            # 3. Upcoming application deadlines (due within 3 days)
            three_days_later = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
            upcoming_deadlines = []
            try:
                deadline_rows = conn.execute("""
                    SELECT id, company_name, job_title, deadline, status
                    FROM applications
                    WHERE user_id = ? AND deadline >= ? AND deadline <= ?
                    ORDER BY deadline ASC
                """, (user_id, today_str, three_days_later)).fetchall()
                upcoming_deadlines = [
                    {
                        "id": r["id"],
                        "company": r["company_name"],
                        "role": r["job_title"],
                        "deadline": r["deadline"],
                        "status": r["status"]
                    }
                    for r in deadline_rows
                ]
            except Exception:
                upcoming_deadlines = []

            # 4. Spaced repetition coding items due today
            due_coding_problems = []
            try:
                from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
                due_coding_problems = CodingSpacedRepetitionService.get_due_reviews(user_id, limit=5)
            except Exception:
                due_coding_problems = []

        finally:
            conn.close()

        # 5. Calculate daily completion rate
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t["is_completed"])
        completion_pct = round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0.0

        # 6. Daily focus tip
        day_of_year = datetime.date.today().timetuple().tm_yday
        daily_tip = cls.DAILY_TIPS[day_of_year % len(cls.DAILY_TIPS)]

        return {
            "date": today_str,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "completion_pct": completion_pct,
            "tasks": tasks,
            "upcoming_deadlines": upcoming_deadlines,
            "due_coding_problems": due_coding_problems,
            "daily_focus_tip": daily_tip,
            "all_done": (total_tasks > 0 and completed_tasks == total_tasks)
        }

    @classmethod
    def _ensure_default_daily_tasks(cls, user_id: str, today_str: str):
        """Creates 3 baseline daily preparation habits if today is fresh."""
        conn = _get_db_connection()
        try:
            with conn:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM daily_placement_prep_tasks WHERE user_id = ? AND task_date = ?",
                    (user_id, today_str)
                ).fetchone()[0]

                if existing == 0:
                    defaults = [
                        ("coding", "Solve 2 DSA practice problems", 2),
                        ("interview", "Complete 1 mock interview session", 1),
                        ("revision", "Review 3 saved interview concepts", 3)
                    ]
                    for t_type, title, target in defaults:
                        conn.execute("""
                            INSERT OR IGNORE INTO daily_placement_prep_tasks (
                                user_id, task_date, task_type, title, target_count, completed_count, is_completed
                            ) VALUES (?, ?, ?, ?, ?, 0, 0)
                        """, (user_id, today_str, t_type, title, target))
        finally:
            conn.close()

    @classmethod
    def toggle_task(cls, user_id: str, task_id: int) -> Dict[str, Any]:
        """Toggles a daily task between completed and incomplete."""
        conn = _get_db_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT is_completed, target_count FROM daily_placement_prep_tasks WHERE id = ? AND user_id = ?",
                    (task_id, user_id)
                ).fetchone()
                if not row:
                    raise ValueError("Task not found.")

                new_state = 0 if row["is_completed"] else 1
                new_count = row["target_count"] if new_state else 0

                conn.execute("""
                    UPDATE daily_placement_prep_tasks
                    SET is_completed = ?, completed_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                """, (new_state, new_count, task_id, user_id))
            return {"task_id": task_id, "is_completed": bool(new_state)}
        finally:
            conn.close()

    @classmethod
    def add_custom_daily_task(cls, user_id: str, title: str, task_type: str = "custom") -> Dict[str, Any]:
        """Adds a custom student task for today."""
        today_str = datetime.date.today().isoformat()
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    INSERT INTO daily_placement_prep_tasks (
                        user_id, task_date, task_type, title, target_count, completed_count, is_completed
                    ) VALUES (?, ?, ?, ?, 1, 0, 0)
                """, (user_id, today_str, task_type, title.strip()))
                new_id = cursor.lastrowid
            return {
                "id": new_id,
                "task_date": today_str,
                "title": title.strip(),
                "task_type": task_type,
                "is_completed": False
            }
        finally:
            conn.close()
