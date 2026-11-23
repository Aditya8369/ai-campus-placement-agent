"""
Coding solution explanation feedback service (#616).
Collects feedback (Helpful, Confusing, Incorrect, Too Long) on solution explanations.
Guarantees duplicate prevention per user/explanation and escapes comments.
"""

import html
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from db.connection import get_db_connection

VALID_FEEDBACK_TYPES = {"helpful", "confusing", "incorrect", "too_long"}

def init_feedback_table():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS explanation_feedback (
                user_id TEXT NOT NULL,
                explanation_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                comment TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, explanation_id)
            )
        """)
        conn.commit()

init_feedback_table()

def submit_feedback(user_id: str, explanation_id: str, feedback_type: str, comment: str = "") -> Dict[str, Any]:
    if not user_id or not explanation_id:
        return {"success": False, "error": "user_id and explanation_id are required"}

    clean_type = (feedback_type or "").lower().strip()
    if clean_type not in VALID_FEEDBACK_TYPES:
        return {"success": False, "error": f"Invalid feedback type: {clean_type}. Must be one of {list(VALID_FEEDBACK_TYPES)}"}

    safe_comment = html.escape(comment.strip()) if comment else ""
    now_str = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO explanation_feedback (user_id, explanation_id, feedback_type, comment, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, explanation_id) DO UPDATE SET
                feedback_type=excluded.feedback_type,
                comment=excluded.comment,
                updated_at=excluded.updated_at
        """, (user_id, explanation_id, clean_type, safe_comment, now_str))
        conn.commit()

    return {
        "success": True,
        "explanation_id": explanation_id,
        "feedback_type": clean_type,
        "comment": safe_comment,
        "updated_at": now_str
    }

def get_feedback_summary(explanation_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT feedback_type, COUNT(*) as count
            FROM explanation_feedback
            WHERE explanation_id = ?
            GROUP BY feedback_type
        """, (explanation_id,))
        rows = cursor.fetchall()

    summary = {t: 0 for t in VALID_FEEDBACK_TYPES}
    total = 0
    for r in rows:
        summary[r["feedback_type"]] = r["count"]
        total += r["count"]

    return {
        "explanation_id": explanation_id,
        "total_feedback": total,
        "breakdown": summary
    }

def remove_feedback(user_id: str, explanation_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM explanation_feedback WHERE user_id = ? AND explanation_id = ?", (user_id, explanation_id))
        conn.commit()
        return cursor.rowcount > 0
