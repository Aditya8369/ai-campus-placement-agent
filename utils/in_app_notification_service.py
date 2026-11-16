"""
In-App Notification Center Service
Manages real-time in-app placement notifications, alerts, and reminders for students.

Features:
- Stores in-app alerts in SQLite table `in_app_notifications`.
- Tracks categories: 'interview_reminder', 'application_status', 'resume_analysis', 'system_alert'.
- Read / unread status tracking with bulk mark-all-read support.
- Unread count badge endpoint for navbar bell icon.
- Filter notifications by category, priority, and read status.
- Notification dismissal / deletion support.
"""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection


class InAppNotificationCenterService:
    """Service to deliver and manage student in-app notifications."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the in_app_notifications table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS in_app_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                category TEXT DEFAULT 'system_alert',
                priority TEXT DEFAULT 'normal',
                action_url TEXT,
                is_read INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ian_student_read 
            ON in_app_notifications(student_id, is_read)
            """
        )
        conn.commit()
        conn.close()

    def create_notification(
        self,
        student_id: str,
        title: str,
        message: str,
        category: str = "system_alert",
        priority: str = "normal",
        action_url: Optional[str] = None
    ) -> int:
        """
        Creates a new in-app notification for a student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO in_app_notifications
            (student_id, title, message, category, priority, action_url, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                student_id,
                title,
                message,
                category,
                priority,
                action_url,
                datetime.now(timezone.utc).isoformat()
            )
        )
        notification_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return notification_id

    def get_unread_count(self, student_id: str) -> int:
        """Returns the number of unread notifications for a student."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM in_app_notifications WHERE student_id = ? AND is_read = 0",
            (student_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return row["count"] if row else 0

    def list_notifications(
        self,
        student_id: str,
        is_read: Optional[bool] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Retrieves in-app notifications with optional filtering.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        query = "SELECT id, title, message, category, priority, action_url, is_read, created_at FROM in_app_notifications WHERE student_id = ?"
        params: List[Any] = [student_id]

        if is_read is not None:
            query += " AND is_read = ?"
            params.append(1 if is_read else 0)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "title": r["title"],
                "message": r["message"],
                "category": r["category"],
                "priority": r["priority"],
                "action_url": r["action_url"],
                "is_read": bool(r["is_read"]),
                "created_at": str(r["created_at"])
            }
            for r in rows
        ]

    def mark_as_read(self, student_id: str, notification_id: int) -> bool:
        """Marks a single notification as read."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE in_app_notifications SET is_read = 1 WHERE id = ? AND student_id = ?",
            (notification_id, student_id)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def mark_all_as_read(self, student_id: str) -> int:
        """Marks all notifications for a student as read."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE in_app_notifications SET is_read = 1 WHERE student_id = ? AND is_read = 0",
            (student_id,)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected

    def delete_notification(self, student_id: str, notification_id: int) -> bool:
        """Deletes a specific notification."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM in_app_notifications WHERE id = ? AND student_id = ?",
            (notification_id, student_id)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0


in_app_notification_service = InAppNotificationCenterService()
