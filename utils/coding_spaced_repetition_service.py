"""
Coding Problem Spaced-Repetition System (#509)

Provides automated spaced repetition tracking for LeetCode/DSA problems solved by students.
Algorithms inspired by Leitner & SM-2 scheduling:
- Ratings: 'forgot' (reset to day 1), 'difficult' (1 day), 'good' (3 days or next tier), 'easy' (expedite interval).
- Intervals: 1 day, 3 days, 1 week (7 days), 2 weeks (14 days), 1 month (30 days).
- Due date calculation based on last review timestamp + interval.
- Support for pausing schedule, rescheduling, and topic categorization.
- Daily review queue with problem recommendations and mastery retention score.
"""

import os
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


def init_spaced_repetition_table():
    """Initializes the database schema for coding spaced repetition."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS coding_spaced_repetition (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    topic TEXT DEFAULT 'Data Structures',
                    difficulty TEXT DEFAULT 'Medium',
                    repetition_level INTEGER DEFAULT 0,
                    interval_days INTEGER DEFAULT 1,
                    ease_factor REAL DEFAULT 2.5,
                    last_reviewed_at TIMESTAMP,
                    next_review_at TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'active', -- 'active', 'paused', 'mastered'
                    review_count INTEGER DEFAULT 0,
                    history_log TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, problem_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_csr_user_due ON coding_spaced_repetition(user_id, next_review_at, status)")
    finally:
        conn.close()


init_spaced_repetition_table()


class CodingSpacedRepetitionService:
    """Service to track, schedule, and review coding problems using spaced repetition."""

    INTERVAL_STAGES = [1, 3, 7, 14, 30]

    @classmethod
    def enroll_problem(
        cls,
        user_id: str,
        problem_id: str,
        title: str,
        topic: str = "Data Structures",
        difficulty: str = "Medium",
        initial_rating: str = "good"
    ) -> Dict[str, Any]:
        """
        Enrolls a solved or bookmarked coding problem into the spaced repetition schedule.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        rating_clean = initial_rating.lower().strip()

        interval_days = 1
        level = 0
        if rating_clean == "easy":
            interval_days = 3
            level = 1
        elif rating_clean == "difficult":
            interval_days = 1
            level = 0
        elif rating_clean == "good":
            interval_days = 2
            level = 0

        next_due = now + datetime.timedelta(days=interval_days)

        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO coding_spaced_repetition (
                        user_id, problem_id, title, topic, difficulty,
                        repetition_level, interval_days, ease_factor,
                        last_reviewed_at, next_review_at, status, review_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 2.5, ?, ?, 'active', 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, problem_id) DO UPDATE SET
                        title = excluded.title,
                        topic = excluded.topic,
                        difficulty = excluded.difficulty,
                        status = 'active',
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    user_id, problem_id, title, topic, difficulty,
                    level, interval_days, now.isoformat(), next_due.isoformat()
                ))
            return cls.get_problem_record(user_id, problem_id)
        finally:
            conn.close()

    @classmethod
    def record_review(cls, user_id: str, problem_id: str, performance_rating: str) -> Dict[str, Any]:
        """
        Records a student review attempt with ratings:
        - 'forgot': resets interval to 1 day, level to 0.
        - 'difficult': keeps interval to 1 day, decreases ease factor slightly.
        - 'good': moves to next interval stage (e.g. 1d -> 3d -> 7d -> 14d -> 30d).
        - 'easy': jumps ahead or multiplies interval by ease factor.
        """
        record = cls.get_problem_record(user_id, problem_id)
        if not record:
            raise ValueError(f"Problem '{problem_id}' is not enrolled in spaced repetition.")

        now = datetime.datetime.now(datetime.timezone.utc)
        rating = performance_rating.lower().strip()

        level = record["repetition_level"]
        interval = record["interval_days"]
        ease = record["ease_factor"]
        status = record["status"]

        if rating == "forgot":
            level = 0
            interval = 1
            ease = max(1.3, ease - 0.2)
        elif rating == "difficult":
            level = max(0, level - 1)
            interval = 1
            ease = max(1.3, ease - 0.15)
        elif rating == "good":
            level += 1
            if level < len(cls.INTERVAL_STAGES):
                interval = cls.INTERVAL_STAGES[level]
            else:
                interval = int(interval * ease)
        elif rating == "easy":
            level += 2
            if level < len(cls.INTERVAL_STAGES):
                interval = cls.INTERVAL_STAGES[level]
            else:
                interval = int(interval * ease * 1.3)
            ease = min(3.0, ease + 0.15)
        else:
            raise ValueError("Invalid rating. Must be 'forgot', 'difficult', 'good', or 'easy'.")

        if interval >= 30:
            status = "mastered"

        next_due = now + datetime.timedelta(days=interval)

        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE coding_spaced_repetition
                    SET repetition_level = ?,
                        interval_days = ?,
                        ease_factor = ?,
                        last_reviewed_at = ?,
                        next_review_at = ?,
                        status = ?,
                        review_count = review_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND problem_id = ?
                """, (
                    level, interval, ease, now.isoformat(),
                    next_due.isoformat(), status, user_id, problem_id
                ))
            return cls.get_problem_record(user_id, problem_id)
        finally:
            conn.close()

    @classmethod
    def get_due_reviews(cls, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Returns all problems due for review today or overdue.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = _get_db_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM coding_spaced_repetition
                WHERE user_id = ? AND status = 'active' AND next_review_at <= ?
                ORDER BY next_review_at ASC
                LIMIT ?
            """, (user_id, now, limit)).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def get_all_enrolled(cls, user_id: str, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns all enrolled problems with status, topic, and next review dates.
        """
        conn = _get_db_connection()
        try:
            if topic and topic.lower() != "all":
                rows = conn.execute("""
                    SELECT * FROM coding_spaced_repetition
                    WHERE user_id = ? AND topic = ?
                    ORDER BY next_review_at ASC
                """, (user_id, topic)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM coding_spaced_repetition
                    WHERE user_id = ?
                    ORDER BY next_review_at ASC
                """, (user_id,)).fetchall()
            return [cls._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def toggle_pause_schedule(cls, user_id: str, problem_id: str) -> Dict[str, Any]:
        """Toggles between active and paused status for a problem."""
        record = cls.get_problem_record(user_id, problem_id)
        if not record:
            raise ValueError("Problem record not found.")

        new_status = "active" if record["status"] == "paused" else "paused"
        conn = _get_db_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE coding_spaced_repetition SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND problem_id = ?",
                    (new_status, user_id, problem_id)
                )
            return cls.get_problem_record(user_id, problem_id)
        finally:
            conn.close()

    @classmethod
    def reset_schedule(cls, user_id: str, problem_id: str) -> Dict[str, Any]:
        """Resets the repetition progress of a problem back to Day 1."""
        now = datetime.datetime.now(datetime.timezone.utc)
        next_due = now + datetime.timedelta(days=1)
        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE coding_spaced_repetition
                    SET repetition_level = 0,
                        interval_days = 1,
                        ease_factor = 2.5,
                        status = 'active',
                        next_review_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND problem_id = ?
                """, (next_due.isoformat(), user_id, problem_id))
            return cls.get_problem_record(user_id, problem_id)
        finally:
            conn.close()

    @classmethod
    def get_summary_metrics(cls, user_id: str) -> Dict[str, Any]:
        """Computes summary statistics for the user's coding retention queue."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = _get_db_connection()
        try:
            total_count = conn.execute("SELECT COUNT(*) FROM coding_spaced_repetition WHERE user_id = ?", (user_id,)).fetchone()[0]
            due_count = conn.execute(
                "SELECT COUNT(*) FROM coding_spaced_repetition WHERE user_id = ? AND status = 'active' AND next_review_at <= ?",
                (user_id, now)
            ).fetchone()[0]
            mastered_count = conn.execute(
                "SELECT COUNT(*) FROM coding_spaced_repetition WHERE user_id = ? AND status = 'mastered'",
                (user_id,)
            ).fetchone()[0]
            paused_count = conn.execute(
                "SELECT COUNT(*) FROM coding_spaced_repetition WHERE user_id = ? AND status = 'paused'",
                (user_id,)
            ).fetchone()[0]

            retention_rate = round((mastered_count / total_count * 100), 1) if total_count > 0 else 0.0

            return {
                "total_enrolled": total_count,
                "due_today": due_count,
                "mastered": mastered_count,
                "paused": paused_count,
                "retention_rate_pct": retention_rate
            }
        finally:
            conn.close()

    @classmethod
    def get_problem_record(cls, user_id: str, problem_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single problem record."""
        conn = _get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM coding_spaced_repetition WHERE user_id = ? AND problem_id = ?",
                (user_id, problem_id)
            ).fetchone()
            return cls._row_to_dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            next_due_dt = datetime.datetime.fromisoformat(row["next_review_at"])
            is_due = (row["status"] == "active") and (next_due_dt <= now)
        except Exception:
            is_due = False

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "problem_id": row["problem_id"],
            "title": row["title"],
            "topic": row["topic"],
            "difficulty": row["difficulty"],
            "repetition_level": row["repetition_level"],
            "interval_days": row["interval_days"],
            "ease_factor": row["ease_factor"],
            "last_reviewed_at": row["last_reviewed_at"],
            "next_review_at": row["next_review_at"],
            "status": row["status"],
            "review_count": row["review_count"],
            "is_due": is_due
        }
