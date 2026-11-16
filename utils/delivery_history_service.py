"""
Notification Delivery History Service
Maintains an auditable, privacy-conscious delivery log for outbound notifications
(emails, interview reminders, placement alerts) without logging confidential message bodies.

Features:
- Stores delivery status (DELIVERED, PENDING, FAILED, BOUNCED) in table `notification_delivery_logs`.
- Logs safe delivery metadata: channel ('email', 'sms', 'in_app'), recipient mask (e.g. 'j***e@domain.com'),
  subject/template_name, error_summary (if failed), and dispatch latency.
- Never stores unencrypted resume text, passwords, or personal credentials.
- Filterable by student, delivery channel, status, and date range.
- Supports retry status updates when failed dispatches succeed upon retry.
"""

from datetime import datetime, timezone
import re
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection


class NotificationDeliveryHistoryService:
    """Service to record, track, and query notification dispatches."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the notification_delivery_logs table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_delivery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                masked_recipient TEXT NOT NULL,
                template_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                error_summary TEXT,
                dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                latency_ms INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ndl_student_status 
            ON notification_delivery_logs(student_id, status)
            """
        )
        conn.commit()
        conn.close()

    def mask_recipient(self, recipient: str) -> str:
        """
        Masks email addresses or phone numbers to prevent storing plain PII.
        Example: john.doe@example.com -> j***e@example.com
        """
        if not recipient:
            return "N/A"
        clean = recipient.strip()
        if "@" in clean:
            user, domain = clean.split("@", 1)
            if len(user) <= 2:
                masked_user = user[0] + "***" if user else "***"
            else:
                masked_user = f"{user[0]}***{user[-1]}"
            return f"{masked_user}@{domain}"
        # Phone numbers
        digits = re.sub(r"\D", "", clean)
        if len(digits) >= 4:
            return f"***-***-{digits[-4:]}"
        return "***"

    def log_delivery(
        self,
        student_id: str,
        channel: str,
        recipient: str,
        template_name: str,
        subject: str,
        status: str = "DELIVERED",
        error_summary: Optional[str] = None,
        latency_ms: int = 0
    ) -> int:
        """
        Records a notification dispatch attempt safely.
        """
        masked = self.mask_recipient(recipient)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO notification_delivery_logs
            (student_id, channel, masked_recipient, template_name, subject, status, error_summary, dispatched_at, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                channel.lower(),
                masked,
                template_name,
                subject,
                status.upper(),
                error_summary,
                datetime.now(timezone.utc).isoformat(),
                max(0, latency_ms)
            )
        )
        log_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return log_id

    def list_delivery_history(
        self,
        student_id: str,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Retrieves notification delivery records for a student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT id, student_id, channel, masked_recipient, template_name, 
                   subject, status, error_summary, dispatched_at, latency_ms
            FROM notification_delivery_logs
            WHERE student_id = ?
        """
        params: List[Any] = [student_id]

        if channel:
            query += " AND channel = ?"
            params.append(channel.lower())

        if status:
            query += " AND status = ?"
            params.append(status.upper())

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "student_id": r["student_id"],
                "channel": r["channel"],
                "masked_recipient": r["masked_recipient"],
                "template_name": r["template_name"],
                "subject": r["subject"],
                "status": r["status"],
                "error_summary": r["error_summary"],
                "dispatched_at": str(r["dispatched_at"]),
                "latency_ms": r["latency_ms"]
            }
            for r in rows
        ]

    def get_delivery_metrics(self, student_id: str) -> Dict[str, Any]:
        """
        Calculates delivery rate and channel distribution for student auditing.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT status, COUNT(*) as count 
            FROM notification_delivery_logs 
            WHERE student_id = ? 
            GROUP BY status
            """,
            (student_id,)
        )
        status_rows = cursor.fetchall()
        conn.close()

        status_counts = {r["status"]: r["count"] for r in status_rows}
        total = sum(status_counts.values())
        delivered = status_counts.get("DELIVERED", 0)
        success_rate = round((delivered / total * 100), 1) if total > 0 else 100.0

        return {
            "total_sent": total,
            "delivered": delivered,
            "failed": status_counts.get("FAILED", 0),
            "pending": status_counts.get("PENDING", 0),
            "success_rate_percent": success_rate,
            "status_breakdown": status_counts
        }


delivery_history_service = NotificationDeliveryHistoryService()
