"""
Recommendation Dismissal Service
Allows students to dismiss recommendations marked as "not relevant".

Features:
- Dismisses recommendations with a student-selected reason:
  - "Already know this skill / topic"
  - "Not interested in this technology / domain"
  - "Irrelevant to my target career track"
  - "Too basic or too advanced for my current level"
  - "Other (custom note)"
- Persists dismissals per-student in SQLite table `recommendation_dismissals`.
- Excludes dismissed items from future recommendation feeds and suggestions.
- Allows students to review and un-dismiss (restore) previously hidden recommendations.
- Aggregates student feedback breakdown metrics for curriculum analytics.
"""

from datetime import datetime, timezone
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection

STANDARD_DISMISSAL_REASONS = [
    "Already know this skill / topic",
    "Not interested in this technology / domain",
    "Irrelevant to my target career track",
    "Too basic or too advanced for my current level",
    "Other"
]


class RecommendationDismissalService:
    """Service to handle dismissing and un-dismissing AI recommendations."""

    def __init__(self):
        self.standard_reasons = STANDARD_DISMISSAL_REASONS
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the recommendation_dismissals table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_dismissals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                recommendation_id TEXT NOT NULL,
                recommendation_type TEXT NOT NULL,
                recommendation_title TEXT NOT NULL,
                reason TEXT NOT NULL,
                custom_notes TEXT,
                dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, recommendation_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rec_dismiss_student 
            ON recommendation_dismissals(student_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rec_dismiss_type 
            ON recommendation_dismissals(recommendation_type)
            """
        )
        conn.commit()
        conn.close()

    def dismiss_recommendation(
        self,
        student_id: str,
        recommendation_id: str,
        recommendation_title: str,
        recommendation_type: str = "skill_recommendation",
        reason: str = "Not interested in this technology / domain",
        custom_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Marks a recommendation as not relevant for the student.
        """
        clean_reason = reason.strip() if reason and reason.strip() in self.standard_reasons else "Other"
        timestamp = datetime.now(timezone.utc).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO recommendation_dismissals
            (student_id, recommendation_id, recommendation_type, recommendation_title, reason, custom_notes, dismissed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, recommendation_id) DO UPDATE SET
                reason = excluded.reason,
                custom_notes = excluded.custom_notes,
                dismissed_at = excluded.dismissed_at
            """,
            (student_id, recommendation_id, recommendation_type, recommendation_title, clean_reason, custom_notes, timestamp)
        )
        conn.commit()
        conn.close()

        return {
            "success": True,
            "student_id": student_id,
            "recommendation_id": recommendation_id,
            "recommendation_title": recommendation_title,
            "reason": clean_reason,
            "dismissed_at": timestamp,
            "message": f"Recommendation '{recommendation_title}' marked as not relevant."
        }

    def undismiss_recommendation(
        self,
        student_id: str,
        recommendation_id: str
    ) -> bool:
        """
        Removes a dismissal, restoring the recommendation to the student's feed.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM recommendation_dismissals
            WHERE student_id = ? AND recommendation_id = ?
            """,
            (student_id, recommendation_id)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def get_dismissed_recommendation_ids(self, student_id: str) -> List[str]:
        """
        Returns list of recommendation IDs dismissed by the student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT recommendation_id FROM recommendation_dismissals
            WHERE student_id = ?
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [r["recommendation_id"] for r in rows]

    def list_dismissed_recommendations(self, student_id: str) -> List[Dict[str, Any]]:
        """
        Returns full list of dismissed recommendations with reason and timestamp.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, recommendation_id, recommendation_type, recommendation_title, reason, custom_notes, dismissed_at
            FROM recommendation_dismissals
            WHERE student_id = ?
            ORDER BY id DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "recommendation_id": r["recommendation_id"],
                "recommendation_type": r["recommendation_type"],
                "recommendation_title": r["recommendation_title"],
                "reason": r["reason"],
                "custom_notes": r["custom_notes"],
                "dismissed_at": str(r["dismissed_at"])
            }
            for r in rows
        ]

    def get_dismissal_analytics(self, student_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Summarizes reasons and categories of dismissals to understand learner preferences.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        if student_id:
            cursor.execute(
                """
                SELECT reason, COUNT(*) as count 
                FROM recommendation_dismissals 
                WHERE student_id = ? 
                GROUP BY reason
                """,
                (student_id,)
            )
        else:
            cursor.execute(
                """
                SELECT reason, COUNT(*) as count 
                FROM recommendation_dismissals 
                GROUP BY reason
                """
            )
        rows = cursor.fetchall()
        conn.close()

        reason_counts = {r["reason"]: r["count"] for r in rows}
        total_dismissals = sum(reason_counts.values())

        return {
            "total_dismissed": total_dismissals,
            "reasons_breakdown": reason_counts,
            "student_id": student_id or "global"
        }

    def filter_active_recommendations(
        self,
        student_id: str,
        recommendations: List[Dict[str, Any]],
        id_key: str = "id"
    ) -> List[Dict[str, Any]]:
        """
        Filters out dismissed items from any list of recommendation dictionaries.
        """
        dismissed_set = set(self.get_dismissed_recommendation_ids(student_id))
        return [r for r in recommendations if str(r.get(id_key, "")) not in dismissed_set]


recommendation_dismissal_service = RecommendationDismissalService()
