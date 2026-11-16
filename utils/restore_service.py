"""
Accidental Deletion Undo and Restore Service
Provides safe soft-deletion and undo recovery for critical placement entities
(resumes, job applications, interview recordings, study plans).

Features:
- Soft-deletion quarantine / recycle bin table (`soft_deleted_items`).
- Configurable retention grace period (default: 30 days before permanent purging).
- Instant undo capability via undo tokens or entity restoration endpoints.
- Preserves full original payload and schema metadata for accurate restoration.
- Permanent deletion option for students explicitly exercising data removal rights.
"""

from datetime import datetime, timezone, timedelta
import json
import sqlite3
import uuid
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection

DEFAULT_RETENTION_DAYS = 30


class AccidentalDeletionRestoreService:
    """Service to safeguard user data with soft-delete and undo restore capabilities."""

    def __init__(self, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.retention_days = retention_days
        self._ensure_recycle_bin_table()

    def _ensure_recycle_bin_table(self):
        """Ensures the soft_deleted_items table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS soft_deleted_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                undo_token TEXT UNIQUE NOT NULL,
                student_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_title TEXT NOT NULL,
                original_data JSON NOT NULL,
                deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                restored INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sdi_student_active 
            ON soft_deleted_items(student_id, restored)
            """
        )
        conn.commit()
        conn.close()

    def soft_delete_item(
        self,
        student_id: str,
        entity_type: str,
        entity_id: str,
        entity_title: str,
        original_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Quarantines an item into the recycle bin and generates an undo token.
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=self.retention_days)
        undo_token = f"undo_{uuid.uuid4().hex}"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO soft_deleted_items
            (undo_token, student_id, entity_type, entity_id, entity_title, original_data, deleted_at, expires_at, restored)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                undo_token,
                student_id,
                entity_type,
                str(entity_id),
                entity_title,
                json.dumps(original_data),
                now.isoformat(),
                expires.isoformat()
            )
        )
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "undo_token": undo_token,
            "record_id": record_id,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "entity_title": entity_title,
            "expires_at": expires.isoformat(),
            "message": f"'{entity_title}' moved to Trash. You can undo this deletion within {self.retention_days} days."
        }

    def restore_item(self, student_id: str, undo_token: str) -> Dict[str, Any]:
        """
        Restores an item from the recycle bin if it has not expired and belongs to the student.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, undo_token, entity_type, entity_id, entity_title, original_data, expires_at, restored
            FROM soft_deleted_items
            WHERE student_id = ? AND undo_token = ?
            """,
            (student_id, undo_token)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {"success": False, "error": "Item not found in Trash or invalid token."}

        if row["restored"] == 1:
            conn.close()
            return {"success": False, "error": "This item has already been restored."}

        # Check expiration
        expires_at_dt = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at_dt:
            conn.close()
            return {"success": False, "error": "Retention window has expired. Item cannot be restored."}

        # Mark as restored
        cursor.execute(
            "UPDATE soft_deleted_items SET restored = 1 WHERE id = ?",
            (row["id"],)
        )
        conn.commit()
        conn.close()

        return {
            "success": True,
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "entity_title": row["entity_title"],
            "original_data": json.loads(row["original_data"]),
            "message": f"'{row['entity_title']}' successfully restored."
        }

    def list_trash_items(self, student_id: str) -> List[Dict[str, Any]]:
        """
        Lists active (unrestored and unexpired) items in the student's trash bin.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, undo_token, entity_type, entity_id, entity_title, deleted_at, expires_at
            FROM soft_deleted_items
            WHERE student_id = ? AND restored = 0 AND expires_at > ?
            ORDER BY id DESC
            """,
            (student_id, now_iso)
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "undo_token": r["undo_token"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "entity_title": r["entity_title"],
                "deleted_at": str(r["deleted_at"]),
                "expires_at": str(r["expires_at"])
            }
            for r in rows
        ]

    def purge_expired_items(self) -> int:
        """Removes items whose retention period has elapsed."""
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM soft_deleted_items WHERE expires_at <= ?",
            (now_iso,)
        )
        purged = cursor.rowcount
        conn.commit()
        conn.close()
        return purged


restore_service = AccidentalDeletionRestoreService()
