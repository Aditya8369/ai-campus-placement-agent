"""
Preparation Goal and Target-Date Planner Service
Enables students to define personalized placement timelines, countdown milestones,
and structured preparation goals (e.g. "Google Summer Internship - Target: July 15, 2026").

Features:
- Stores student goals in SQLite table `preparation_goals`.
- Milestones and tasks tracking: DSA problems, resume revisions, mock interviews.
- Target-date countdown calculation: days remaining, daily task pace, completion pace health.
- Non-blocking advisory disclaimer: clarifies that timelines are self-guided study goals.
- Goal status management: 'ACTIVE', 'COMPLETED', 'PAUSED', 'EXPIRED'.
"""

from datetime import datetime, timezone, date
import json
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection


class PreparationGoalPlannerService:
    """Service to create, track, and evaluate student target-date placement roadmaps."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the preparation_goals table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS preparation_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                goal_title TEXT NOT NULL,
                target_role TEXT NOT NULL,
                target_date DATE NOT NULL,
                target_coding_problems INTEGER DEFAULT 50,
                completed_coding_problems INTEGER DEFAULT 0,
                target_mock_interviews INTEGER DEFAULT 5,
                completed_mock_interviews INTEGER DEFAULT 0,
                resume_completed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_prep_goal_student_status 
            ON preparation_goals(student_id, status)
            """
        )
        conn.commit()
        conn.close()

    def create_goal(
        self,
        student_id: str,
        goal_title: str,
        target_role: str,
        target_date_str: str,
        target_coding_problems: int = 50,
        target_mock_interviews: int = 5,
        resume_completed: bool = False,
        notes: Optional[str] = None
    ) -> int:
        """
        Creates a new preparation goal with target completion date.
        """
        # Validate date format YYYY-MM-DD
        target_dt = date.fromisoformat(target_date_str)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO preparation_goals
            (student_id, goal_title, target_role, target_date, target_coding_problems, 
             completed_coding_problems, target_mock_interviews, completed_mock_interviews, 
             resume_completed, status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, 0, ?, 'ACTIVE', ?, ?)
            """,
            (
                student_id,
                goal_title,
                target_role,
                target_dt.isoformat(),
                target_coding_problems,
                target_mock_interviews,
                1 if resume_completed else 0,
                notes,
                datetime.now(timezone.utc).isoformat()
            )
        )
        goal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return goal_id

    def calculate_goal_progress(self, goal_row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates pace, percentage completion, and countdown metrics.
        """
        today = date.today()
        target_dt = date.fromisoformat(goal_row["target_date"])
        days_remaining = (target_dt - today).days

        # Progress percentage
        coding_pct = min(1.0, goal_row["completed_coding_problems"] / max(1, goal_row["target_coding_problems"]))
        interview_pct = min(1.0, goal_row["completed_mock_interviews"] / max(1, goal_row["target_mock_interviews"]))
        resume_pct = 1.0 if goal_row["resume_completed"] else 0.0

        overall_pct = round(((coding_pct * 0.5) + (interview_pct * 0.3) + (resume_pct * 0.2)) * 100, 1)

        # Pace assessment
        if days_remaining < 0:
            pace_status = "EXPIRED"
            daily_pace_advice = "The target date for this preparation plan has passed."
        elif days_remaining == 0:
            pace_status = "DUE_TODAY"
            daily_pace_advice = "Target date is today! Complete final revisions."
        else:
            remaining_coding = max(0, goal_row["target_coding_problems"] - goal_row["completed_coding_problems"])
            daily_coding = round(remaining_coding / max(1, days_remaining), 1)
            pace_status = "ON_TRACK" if overall_pct >= 50 or days_remaining > 30 else "NEEDS_ATTENTION"
            daily_pace_advice = f"Aim for ~{daily_coding} coding problems per day to stay on schedule."

        return {
            "days_remaining": days_remaining,
            "target_date": goal_row["target_date"],
            "overall_progress_percent": overall_pct,
            "coding_progress": {
                "completed": goal_row["completed_coding_problems"],
                "target": goal_row["target_coding_problems"],
                "percent": round(coding_pct * 100, 1)
            },
            "interview_progress": {
                "completed": goal_row["completed_mock_interviews"],
                "target": goal_row["target_mock_interviews"],
                "percent": round(interview_pct * 100, 1)
            },
            "resume_ready": bool(goal_row["resume_completed"]),
            "pace_status": pace_status,
            "daily_pace_advice": daily_pace_advice,
            "disclaimer": "This timeline is a personalized study guide and does not guarantee interview shortlisting."
        }

    def list_student_goals(self, student_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all goals with live progress calculations for a student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, student_id, goal_title, target_role, target_date, target_coding_problems, 
                   completed_coding_problems, target_mock_interviews, completed_mock_interviews, 
                   resume_completed, status, notes, created_at
            FROM preparation_goals
            WHERE student_id = ?
            ORDER BY id DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            row_dict = dict(r)
            progress = self.calculate_goal_progress(row_dict)
            results.append({
                **row_dict,
                "progress_metrics": progress
            })
        return results

    def update_goal_progress(
        self,
        student_id: str,
        goal_id: int,
        completed_coding: Optional[int] = None,
        completed_interviews: Optional[int] = None,
        resume_completed: Optional[bool] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Updates progress stats on an existing goal.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        updates = []
        params = []

        if completed_coding is not None:
            updates.append("completed_coding_problems = ?")
            params.append(completed_coding)
        if completed_interviews is not None:
            updates.append("completed_mock_interviews = ?")
            params.append(completed_interviews)
        if resume_completed is not None:
            updates.append("resume_completed = ?")
            params.append(1 if resume_completed else 0)
        if status is not None:
            updates.append("status = ?")
            params.append(status.upper())

        if not updates:
            conn.close()
            return False

        query = f"UPDATE preparation_goals SET {', '.join(updates)} WHERE id = ? AND student_id = ?"
        params.extend([goal_id, student_id])

        cursor.execute(query, tuple(params))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0


goal_planner_service = PreparationGoalPlannerService()
