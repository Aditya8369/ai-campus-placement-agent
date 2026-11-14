"""
Unsuitable Mock-Interview Question Reporting and Flagging Service (#327).

Allows students to flag questions generated during mock interviews that are:
- Irrelevant to the target job description or company profile.
- Unclear or grammatically ambiguous.
- Duplicate / repeated within the same session.
- Outdated or incorrect technical assertions.

Privacy & Governance:
- Reports store question text, reason category, and optional student comments.
- Aggregates reports by question similarity/hash without exposing private student answers or personal transcripts to reviewers.
- Enables quality assurance audits to prevent poor questions from recurring.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

VALID_FLAG_REASONS = [
    "Irrelevant to Target Role",
    "Unclear or Ambiguous",
    "Duplicate Question",
    "Factually Incorrect",
    "Too Easy or Too Hard",
    "Other"
]


def init_question_flags_table():
    """Initializes the question flags store if missing."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS unsuitable_question_flags (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                question_index INTEGER NOT NULL,
                question_hash TEXT NOT NULL,
                question_text TEXT NOT NULL,
                reason TEXT NOT NULL,
                comment TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def compute_question_hash(question_text: str) -> str:
    """Computes a canonical SHA-256 hash for deduplication and grouping."""
    norm = "".join(ch.lower() for ch in str(question_text) if ch.isalnum())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def flag_interview_question(
    student_id: str,
    session_id: str,
    question_index: int,
    question_text: str,
    reason: str,
    comment: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records an unsuitable question report from a student.
    """
    if not student_id:
        raise PermissionError("Authentication required to flag an interview question.")

    if not question_text or not question_text.strip():
        raise ValueError("Question text is required.")

    valid_reasons_lower = [r.lower() for r in VALID_FLAG_REASONS]
    if reason.lower() not in valid_reasons_lower:
        raise ValueError(f"Invalid reason '{reason}'. Valid: {', '.join(VALID_FLAG_REASONS)}")

    init_question_flags_table()

    report_id = f"flag-{uuid.uuid4().hex[:12]}"
    q_hash = compute_question_hash(question_text)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO unsuitable_question_flags (
                id, student_id, session_id, question_index, question_hash, question_text, reason, comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                student_id,
                session_id,
                int(question_index),
                q_hash,
                question_text.strip(),
                reason,
                (comment or "").strip()
            )
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "report_id": report_id,
        "message": "Thank you! Your feedback has been recorded and will help improve future question generation."
    }


def get_flagged_questions_summary(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retrieves grouped statistics on flagged questions without exposing private student answers.
    """
    init_question_flags_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                question_hash,
                question_text,
                COUNT(*) as flag_count,
                GROUP_CONCAT(DISTINCT reason) as reasons,
                MAX(created_at) as latest_report
            FROM unsuitable_question_flags
            GROUP BY question_hash
            ORDER BY flag_count DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        summary = []
        for r in rows:
            summary.append({
                "question_hash": r["question_hash"],
                "question_text": r["question_text"],
                "flag_count": r["flag_count"],
                "reasons": (r["reasons"] or "").split(","),
                "latest_report": r["latest_report"]
            })
        return summary
    finally:
        conn.close()


def resolve_flagged_question(question_hash: str, resolution_status: str = "Resolved") -> bool:
    """
    Allows moderators or automated workflows to mark flagged questions as resolved or suppressed.
    """
    init_question_flags_table()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE unsuitable_question_flags
            SET status = ?
            WHERE question_hash = ?
            """,
            (resolution_status, question_hash)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def is_question_suppressed(question_text: str, flag_threshold: int = 3) -> bool:
    """
    Checks if a question has exceeded the rejection threshold to prevent it from being generated.
    """
    init_question_flags_table()
    q_hash = compute_question_hash(question_text)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) as flag_count
            FROM unsuitable_question_flags
            WHERE question_hash = ?
            """,
            (q_hash,)
        )
        row = cursor.fetchone()
        count = row["flag_count"] if row else 0
        return count >= flag_threshold
    finally:
        conn.close()

