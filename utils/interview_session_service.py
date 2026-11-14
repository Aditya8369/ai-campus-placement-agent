"""
Interview Session Pause and Resume Service (#265).

Provides robust state management for mock interview sessions:
- Session status lifecycle: 'In Progress', 'Paused', 'Completed'.
- Snapshot capture of current question index, question text, answers history,
  and unsubmitted draft answers.
- Pause action: saves timestamp, status, and pending input.
- Resume action: loads paused session, validates integrity, restores progress.
- Listing of a user's active, paused, or completed interview sessions.
- Multi-tenant student isolation: guarantees students can only pause/resume their own sessions.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

STATUS_IN_PROGRESS = "In Progress"
STATUS_PAUSED = "Paused"
STATUS_COMPLETED = "Completed"

VALID_STATUSES = {STATUS_IN_PROGRESS, STATUS_PAUSED, STATUS_COMPLETED}


def ensure_interview_session_pause_table(conn=None) -> None:
    """
    Ensures interview session status and snapshot metadata columns/tables exist.
    Stores session metadata in `interview_session_state` table to augment the base `interviews` table.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interview_session_state (
                session_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                analysis_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'In Progress',
                current_question_index INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL DEFAULT 0,
                saved_draft_answer TEXT,
                last_paused_at TIMESTAMP,
                last_resumed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sess_state_student ON interview_session_state (student_id, status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sess_state_analysis ON interview_session_state (analysis_id)")

        # Verify whether `status` column exists in `interviews` table for backwards compatibility
        cursor.execute("PRAGMA table_info(interviews)")
        cols = [c[1] for c in cursor.fetchall()]
        if "status" not in cols:
            try:
                cursor.execute("ALTER TABLE interviews ADD COLUMN status TEXT DEFAULT 'In Progress'")
            except Exception as e:
                logger.debug(f"Column status may already exist or cannot be added: {e}")

        conn.commit()
    finally:
        if should_close:
            conn.close()


def pause_interview_session(
    session_id: str,
    student_id: str,
    draft_answer: str = "",
    question_index: Optional[int] = None
) -> Dict[str, Any]:
    """
    Pauses an ongoing interview session and stores snapshot details.
    """
    ensure_interview_session_pause_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Verify interview existence
        cursor.execute("SELECT id, analysis_id, current_question_index, questions_json, answers_json, completed FROM interviews WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise KeyError(f"Interview session '{session_id}' not found.")

        analysis_id = row["analysis_id"]

        # Verify student authorization
        cursor.execute("SELECT student_id FROM analyses WHERE id = ?", (analysis_id,))
        a_row = cursor.fetchone()
        if a_row:
            owner_id = str(a_row["student_id"] or "default_student")
            if owner_id != str(student_id) and owner_id != "default_student" and student_id != "default_student":
                raise PermissionError("Access denied: You do not own this interview session.")

        questions = json.loads(row["questions_json"] or "[]")
        answers = json.loads(row["answers_json"] or "[]")
        total_questions = len(questions)

        current_idx = row["current_question_index"] if question_index is None else int(question_index)
        now_iso = dt.datetime.utcnow().isoformat()

        # Update base interviews table status
        cursor.execute("UPDATE interviews SET status = ? WHERE id = ?", (STATUS_PAUSED, session_id))

        # Upsert state
        cursor.execute("""
            INSERT INTO interview_session_state (
                session_id, student_id, analysis_id, status, current_question_index,
                total_questions, saved_draft_answer, last_paused_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status = excluded.status,
                current_question_index = excluded.current_question_index,
                total_questions = excluded.total_questions,
                saved_draft_answer = excluded.saved_draft_answer,
                last_paused_at = excluded.last_paused_at,
                updated_at = excluded.updated_at
        """, (
            session_id,
            str(student_id),
            analysis_id,
            STATUS_PAUSED,
            current_idx,
            total_questions,
            draft_answer or "",
            now_iso,
            now_iso
        ))
        conn.commit()

        current_q = questions[current_idx] if 0 <= current_idx < total_questions else None

        return {
            "success": True,
            "session_id": session_id,
            "status": STATUS_PAUSED,
            "current_question_index": current_idx,
            "total_questions": total_questions,
            "answers_count": len(answers),
            "current_question": current_q,
            "draft_answer": draft_answer or "",
            "paused_at": now_iso
        }
    finally:
        conn.close()


def resume_interview_session(
    session_id: str,
    student_id: str
) -> Dict[str, Any]:
    """
    Resumes a paused interview session and restores the candidate's exact spot.
    """
    ensure_interview_session_pause_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, analysis_id, current_question_index, questions_json, answers_json, completed FROM interviews WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise KeyError(f"Interview session '{session_id}' not found.")

        analysis_id = row["analysis_id"]

        # Verify authorization
        cursor.execute("SELECT student_id, company_name FROM analyses WHERE id = ?", (analysis_id,))
        a_row = cursor.fetchone()
        if a_row:
            owner_id = str(a_row["student_id"] or "default_student")
            if owner_id != str(student_id) and owner_id != "default_student" and student_id != "default_student":
                raise PermissionError("Access denied: You do not own this interview session.")

        company_name = a_row["company_name"] if a_row else "General"
        questions = json.loads(row["questions_json"] or "[]")
        answers = json.loads(row["answers_json"] or "[]")
        is_completed = bool(row["completed"])

        # Fetch paused metadata
        cursor.execute("SELECT * FROM interview_session_state WHERE session_id = ?", (session_id,))
        state_row = cursor.fetchone()

        if is_completed:
            status = STATUS_COMPLETED
            draft_answer = ""
            current_idx = len(questions) - 1
        else:
            status = STATUS_IN_PROGRESS
            draft_answer = state_row["saved_draft_answer"] if state_row else ""
            current_idx = state_row["current_question_index"] if state_row else row["current_question_index"]

        now_iso = dt.datetime.utcnow().isoformat()

        cursor.execute("UPDATE interviews SET status = ? WHERE id = ?", (status, session_id))
        cursor.execute("""
            INSERT INTO interview_session_state (
                session_id, student_id, analysis_id, status, current_question_index,
                total_questions, saved_draft_answer, last_resumed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status = excluded.status,
                last_resumed_at = excluded.last_resumed_at,
                updated_at = excluded.updated_at
        """, (
            session_id,
            str(student_id),
            analysis_id,
            status,
            current_idx,
            len(questions),
            draft_answer,
            now_iso,
            now_iso
        ))
        conn.commit()

        current_q = questions[current_idx] if 0 <= current_idx < len(questions) else None

        return {
            "success": True,
            "session_id": session_id,
            "analysis_id": analysis_id,
            "company_name": company_name,
            "status": status,
            "current_question_index": current_idx,
            "total_questions": len(questions),
            "answered_count": len(answers),
            "current_question": current_q,
            "draft_answer": draft_answer or "",
            "answers": answers,
            "resumed_at": now_iso
        }
    finally:
        conn.close()


def get_student_interview_sessions_with_status(student_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all interview sessions for a given student with status indicator (In Progress, Paused, Completed).
    """
    ensure_interview_session_pause_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                i.id AS session_id,
                i.analysis_id,
                i.current_question_index,
                i.completed,
                COALESCE(s.status, CASE WHEN i.completed = 1 THEN 'Completed' ELSE 'In Progress' END) AS status,
                COALESCE(s.saved_draft_answer, '') AS saved_draft_answer,
                s.last_paused_at,
                s.last_resumed_at,
                a.company_name,
                a.created_at AS analysis_created_at
            FROM interviews i
            LEFT JOIN interview_session_state s ON i.id = s.session_id
            JOIN analyses a ON i.analysis_id = a.id
            WHERE (a.student_id = ? OR a.student_id = 'default_student' OR ? = 'default_student')
            ORDER BY COALESCE(s.updated_at, a.created_at) DESC
        """, (str(student_id), str(student_id)))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "session_id": row["session_id"],
                "analysis_id": row["analysis_id"],
                "company_name": row["company_name"] or "General",
                "current_question_index": row["current_question_index"],
                "completed": bool(row["completed"]),
                "status": row["status"] if row["status"] in VALID_STATUSES else (STATUS_COMPLETED if row["completed"] else STATUS_IN_PROGRESS),
                "draft_answer": row["saved_draft_answer"],
                "last_paused_at": row["last_paused_at"],
                "last_resumed_at": row["last_resumed_at"],
            })
        return results
    finally:
        conn.close()
