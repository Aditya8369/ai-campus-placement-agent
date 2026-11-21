"""
Learning Resource Completion Tracker Service (#520)

Tracks student completion, bookmarking, and notes across recommended learning resources:
- Integrates with generated skill-gap roadmaps and curated tutorials
- Status states: 'not_started', 'in_progress', 'completed', 'skipped', 'needs_replacement'
- Difficulty rating, estimated duration (minutes), time spent (minutes), and completion timestamp
- Aggregated curriculum progress percentages and subject-wise completion audits
- Custom resource addition and replacement recommendations
- Multi-tenant student isolation with SQLite persistence
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


def init_learning_resources_table():
    """Initializes schema for student learning resources tracking."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS student_learning_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Core CS',
                    url TEXT,
                    estimated_minutes INTEGER DEFAULT 30,
                    time_spent_minutes INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'not_started', -- 'not_started', 'in_progress', 'completed', 'skipped', 'needs_replacement'
                    notes TEXT DEFAULT '',
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, resource_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_slr_user ON student_learning_resources(user_id, status)")
    finally:
        conn.close()


init_learning_resources_table()


class LearningResourceTrackerService:
    """Manages study material completion states, reading logs, and progress metrics."""

    DEFAULT_CURATED_RESOURCES = [
        {
            "resource_id": "res_dsa_blind75",
            "title": "Blind 75 LeetCode Essential Roadmap",
            "category": "Data Structures",
            "url": "https://leetcode.com/discuss/general-discussion/460599/blind-75-leetcode-questions",
            "estimated_minutes": 180
        },
        {
            "resource_id": "res_sys_design_primer",
            "title": "System Design Primer by Donne Martin",
            "category": "System Design",
            "url": "https://github.com/donnemartin/system-design-primer",
            "estimated_minutes": 240
        },
        {
            "resource_id": "res_os_three_easy_pieces",
            "title": "Operating Systems: Three Easy Pieces (Concurrency & Virtualization)",
            "category": "Operating Systems",
            "url": "https://pages.cs.wisc.edu/~remzi/OSTEP/",
            "estimated_minutes": 120
        },
        {
            "resource_id": "res_sql_indexing_guide",
            "title": "Use The Index, Luke: A Guide to Database Performance",
            "category": "Database Management",
            "url": "https://use-the-index-luke.com/",
            "estimated_minutes": 90
        },
        {
            "resource_id": "res_behavioral_star",
            "title": "Engineering Behavioral Interview Masterclass (STAR Technique)",
            "category": "HR & Behavioral",
            "url": "https://www.levels.fyi/blog/star-method-interview.html",
            "estimated_minutes": 60
        }
    ]

    @classmethod
    def get_or_initialize_resources(cls, user_id: str) -> List[Dict[str, Any]]:
        """Ensures default curated placement resources exist for student and returns list."""
        conn = _get_db_connection()
        try:
            with conn:
                for cur in cls.DEFAULT_CURATED_RESOURCES:
                    conn.execute("""
                        INSERT OR IGNORE INTO student_learning_resources (
                            user_id, resource_id, title, category, url, estimated_minutes, status
                        ) VALUES (?, ?, ?, ?, ?, ?, 'not_started')
                    """, (
                        user_id, cur["resource_id"], cur["title"],
                        cur["category"], cur["url"], cur["estimated_minutes"]
                    ))

            rows = conn.execute(
                "SELECT * FROM student_learning_resources WHERE user_id = ? ORDER BY id ASC",
                (user_id,)
            ).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def update_resource_status(
        cls,
        user_id: str,
        resource_id: str,
        status: str,
        time_spent_minutes: Optional[int] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Updates reading status and logs time spent."""
        valid_statuses = ["not_started", "in_progress", "completed", "skipped", "needs_replacement"]
        if status not in valid_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        completed_val = now_iso if status == "completed" else None

        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE student_learning_resources
                    SET status = ?,
                        time_spent_minutes = COALESCE(?, time_spent_minutes),
                        notes = COALESCE(?, notes),
                        completed_at = COALESCE(?, completed_at),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND resource_id = ?
                """, (status, time_spent_minutes, notes, completed_val, user_id, resource_id))

            row = conn.execute(
                "SELECT * FROM student_learning_resources WHERE user_id = ? AND resource_id = ?",
                (user_id, resource_id)
            ).fetchone()
            if not row:
                raise ValueError("Resource not found.")
            return cls._row_to_dict(row)
        finally:
            conn.close()

    @classmethod
    def add_custom_resource(
        cls,
        user_id: str,
        title: str,
        category: str = "General",
        url: Optional[str] = None,
        estimated_minutes: int = 45
    ) -> Dict[str, Any]:
        """Adds a personalized study resource."""
        import uuid
        res_id = f"custom_{uuid.uuid4().hex[:8]}"

        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO student_learning_resources (
                        user_id, resource_id, title, category, url, estimated_minutes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'not_started')
                """, (user_id, res_id, title.strip(), category.strip(), url, estimated_minutes))

            row = conn.execute(
                "SELECT * FROM student_learning_resources WHERE user_id = ? AND resource_id = ?",
                (user_id, res_id)
            ).fetchone()
            return cls._row_to_dict(row)
        finally:
            conn.close()

    @classmethod
    def get_progress_metrics(cls, user_id: str) -> Dict[str, Any]:
        """Calculates curriculum progress percentages and time invested."""
        resources = cls.get_or_initialize_resources(user_id)
        total = len(resources)
        completed = sum(1 for r in resources if r["status"] == "completed")
        in_progress = sum(1 for r in resources if r["status"] == "in_progress")
        skipped = sum(1 for r in resources if r["status"] == "skipped")
        needs_replacement = sum(1 for r in resources if r["status"] == "needs_replacement")

        total_time_spent = sum(r["time_spent_minutes"] for r in resources)
        completion_pct = round((completed / total * 100), 1) if total > 0 else 0.0

        return {
            "total_resources": total,
            "completed": completed,
            "in_progress": in_progress,
            "skipped": skipped,
            "needs_replacement": needs_replacement,
            "total_time_spent_minutes": total_time_spent,
            "completion_percentage": completion_pct,
            "resources": resources
        }

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "resource_id": row["resource_id"],
            "title": row["title"],
            "category": row["category"],
            "url": row["url"],
            "estimated_minutes": row["estimated_minutes"],
            "time_spent_minutes": row["time_spent_minutes"],
            "status": row["status"],
            "notes": row["notes"],
            "completed_at": row["completed_at"]
        }
