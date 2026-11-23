"""
Interview session recovery service (#613).
Persists active interview state, current question index, and draft answers
so users can resume interrupted sessions without loss of progress.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from db.connection import get_db_connection

def init_session_recovery_table():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interview_recovery_sessions (
                session_key TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                analysis_id TEXT NOT NULL,
                current_question_index INTEGER DEFAULT 0,
                current_question_text TEXT,
                draft_answer TEXT,
                last_saved_at TEXT NOT NULL
            )
        """)
        conn.commit()

init_session_recovery_table()

def save_session_checkpoint(user_id: str, analysis_id: str, question_index: int, question_text: str, draft_answer: str) -> Dict[str, Any]:
    session_key = f"{user_id}_{analysis_id}"
    now_str = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO interview_recovery_sessions (session_key, user_id, analysis_id, current_question_index, current_question_text, draft_answer, last_saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                current_question_index=excluded.current_question_index,
                current_question_text=excluded.current_question_text,
                draft_answer=excluded.draft_answer,
                last_saved_at=excluded.last_saved_at
        """, (session_key, user_id, analysis_id, question_index, question_text, draft_answer, now_str))
        conn.commit()

    return {
        "success": True,
        "session_key": session_key,
        "last_saved_at": now_str
    }

def get_session_checkpoint(user_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
    session_key = f"{user_id}_{analysis_id}"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT session_key, user_id, analysis_id, current_question_index, current_question_text, draft_answer, last_saved_at
            FROM interview_recovery_sessions
            WHERE session_key = ?
        """, (session_key,))
        row = cursor.fetchone()

    if not row:
        return None
    return {
        "session_key": row["session_key"],
        "user_id": row["user_id"],
        "analysis_id": row["analysis_id"],
        "current_question_index": row["current_question_index"],
        "current_question_text": row["current_question_text"],
        "draft_answer": row["draft_answer"],
        "last_saved_at": row["last_saved_at"]
    }

def clear_session_checkpoint(user_id: str, analysis_id: str) -> bool:
    session_key = f"{user_id}_{analysis_id}"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM interview_recovery_sessions WHERE session_key = ?", (session_key,))
        conn.commit()
        return cursor.rowcount > 0
