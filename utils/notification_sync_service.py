"""
Cross-device notification sync service (#632).
Stores notification read, unread, and dismissed states centrally in the database
so candidate notification badges remain synchronized across browsers and mobile devices.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List
from db.connection import get_db_connection

def init_notification_sync_table():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notification_states (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                notification_id TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                is_dismissed INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, notification_id)
            )
        """)
        conn.commit()

init_notification_sync_table()

def set_notification_state(user_id: str, notification_id: str, is_read: bool = None, is_dismissed: bool = None) -> Dict[str, Any]:
    now_str = datetime.now(timezone.utc).isoformat()
    import uuid
    state_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, is_read, is_dismissed FROM user_notification_states
            WHERE user_id = ? AND notification_id = ?
        """, (user_id, notification_id))
        row = cursor.fetchone()

        read_val = (1 if is_read else 0) if is_read is not None else (row["is_read"] if row else 0)
        dismiss_val = (1 if is_dismissed else 0) if is_dismissed is not None else (row["is_dismissed"] if row else 0)

        cursor.execute("""
            INSERT INTO user_notification_states (id, user_id, notification_id, is_read, is_dismissed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, notification_id) DO UPDATE SET
                is_read=excluded.is_read,
                is_dismissed=excluded.is_dismissed,
                updated_at=excluded.updated_at
        """, (state_id, user_id, notification_id, read_val, dismiss_val, now_str))
        conn.commit()

    return {
        "success": True,
        "notification_id": notification_id,
        "is_read": bool(read_val),
        "is_dismissed": bool(dismiss_val),
        "updated_at": now_str
    }

def get_user_notification_states(user_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT notification_id, is_read, is_dismissed, updated_at
            FROM user_notification_states
            WHERE user_id = ?
        """, (user_id,))
        rows = cursor.fetchall()

    states = {}
    for r in rows:
        states[r["notification_id"]] = {
            "is_read": bool(r["is_read"]),
            "is_dismissed": bool(r["is_dismissed"]),
            "updated_at": r["updated_at"]
        }
    return states
