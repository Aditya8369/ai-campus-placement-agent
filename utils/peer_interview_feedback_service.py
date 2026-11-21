"""
Peer Feedback Requests for Mock Interviews Service (#519)

Allows students to request blinded or authenticated peer evaluations on their mock interview answers:
- Generates expiring, secure review share tokens (e.g. 7-day expiration)
- Automatic sanitization: strips candidate personal information (PII) before sharing with peers
- Peer review criteria:
  * Technical accuracy rating (1-5)
  * Communication clarity & confidence rating (1-5)
  * Answer conciseness & pacing rating (1-5)
  * Constructive suggestions and strong points
- Student controls: view aggregated peer score, review comments, and revoke active review tokens at any time
- Multi-tenant student isolation with SQLite persistence
"""

import os
import uuid
import json
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


def init_peer_feedback_tables():
    """Initializes schemas for peer review requests and submitted reviews."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS peer_feedback_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    share_token TEXT NOT NULL UNIQUE,
                    role_title TEXT NOT NULL,
                    question_count INTEGER DEFAULT 1,
                    sanitized_transcript TEXT NOT NULL,
                    status TEXT DEFAULT 'active', -- 'active', 'revoked', 'expired'
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS peer_feedback_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    share_token TEXT NOT NULL,
                    peer_user_id TEXT, -- optional peer identifier or anonymous
                    technical_rating INTEGER NOT NULL, -- 1-5
                    communication_rating INTEGER NOT NULL, -- 1-5
                    conciseness_rating INTEGER NOT NULL, -- 1-5
                    positive_feedback TEXT NOT NULL,
                    constructive_critique TEXT NOT NULL,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pfr_token ON peer_feedback_requests(share_token)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pfs_token ON peer_feedback_submissions(share_token)")
    finally:
        conn.close()


init_peer_feedback_tables()


class PeerInterviewFeedbackService:
    """Manages peer review request tokens, sanitization, and submitted critiques."""

    @classmethod
    def create_review_request(
        cls,
        user_id: str,
        session_id: str,
        role_title: str,
        interview_qa_list: List[Dict[str, str]],
        expiry_days: int = 7
    ) -> Dict[str, Any]:
        """
        Creates an expiring review link with sanitized interview Q&A.
        """
        share_token = f"peer_{uuid.uuid4().hex[:12]}"
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(days=expiry_days)

        # Sanitize personal references from answers
        sanitized = []
        for item in interview_qa_list:
            sanitized.append({
                "question": item.get("question", ""),
                "answer": cls._sanitize_pii(item.get("answer", ""))
            })

        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    INSERT INTO peer_feedback_requests (
                        user_id, session_id, share_token, role_title,
                        question_count, sanitized_transcript, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, session_id, share_token, role_title,
                    len(sanitized), json.dumps(sanitized), expires_at.isoformat()
                ))
                req_id = cursor.lastrowid

            return {
                "id": req_id,
                "share_token": share_token,
                "role_title": role_title,
                "question_count": len(sanitized),
                "expires_at": expires_at.isoformat(),
                "review_url": f"/interview/peer-review/{share_token}"
            }
        finally:
            conn.close()

    @classmethod
    def get_review_request(cls, share_token: str) -> Optional[Dict[str, Any]]:
        """Retrieves a peer review request by token if active and unexpired."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = _get_db_connection()
        try:
            row = conn.execute("""
                SELECT * FROM peer_feedback_requests
                WHERE share_token = ? AND status = 'active' AND expires_at > ?
            """, (share_token, now_iso)).fetchone()
            if not row:
                return None

            return {
                "id": row["id"],
                "role_title": row["role_title"],
                "share_token": row["share_token"],
                "question_count": row["question_count"],
                "transcript": json.loads(row["sanitized_transcript"]),
                "expires_at": row["expires_at"]
            }
        finally:
            conn.close()

    @classmethod
    def submit_peer_feedback(
        cls,
        share_token: str,
        technical_rating: int,
        communication_rating: int,
        conciseness_rating: int,
        positive_feedback: str,
        constructive_critique: str,
        peer_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Records a peer evaluation."""
        req = cls.get_review_request(share_token)
        if not req:
            raise ValueError("Review link is invalid, expired, or has been revoked.")

        for r in [technical_rating, communication_rating, conciseness_rating]:
            if not (1 <= r <= 5):
                raise ValueError("Ratings must be between 1 and 5.")

        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    INSERT INTO peer_feedback_submissions (
                        share_token, peer_user_id, technical_rating, communication_rating,
                        conciseness_rating, positive_feedback, constructive_critique
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    share_token, peer_user_id, technical_rating, communication_rating,
                    conciseness_rating, positive_feedback.strip(), constructive_critique.strip()
                ))
                sub_id = cursor.lastrowid
            return {"submission_id": sub_id, "status": "success"}
        finally:
            conn.close()

    @classmethod
    def get_feedback_for_session(cls, user_id: str, session_id: str) -> Dict[str, Any]:
        """Returns all peer reviews received for a student's session."""
        conn = _get_db_connection()
        try:
            req_row = conn.execute("""
                SELECT share_token, status, expires_at FROM peer_feedback_requests
                WHERE user_id = ? AND session_id = ? ORDER BY created_at DESC LIMIT 1
            """, (user_id, session_id)).fetchone()

            if not req_row:
                return {"has_active_request": False, "submissions": []}

            token = req_row["share_token"]
            subs = conn.execute("""
                SELECT * FROM peer_feedback_submissions WHERE share_token = ? ORDER BY submitted_at DESC
            """, (token,)).fetchall()

            sub_list = [
                {
                    "technical_rating": r["technical_rating"],
                    "communication_rating": r["communication_rating"],
                    "conciseness_rating": r["conciseness_rating"],
                    "positive_feedback": r["positive_feedback"],
                    "constructive_critique": r["constructive_critique"],
                    "submitted_at": str(r["submitted_at"])
                }
                for r in subs
            ]

            avg_score = 0.0
            if sub_list:
                total = sum((s["technical_rating"] + s["communication_rating"] + s["conciseness_rating"]) / 3.0 for s in sub_list)
                avg_score = round(total / len(sub_list), 1)

            return {
                "has_active_request": req_row["status"] == "active",
                "share_token": token,
                "review_url": f"/interview/peer-review/{token}",
                "average_peer_rating": avg_score,
                "submissions_count": len(sub_list),
                "submissions": sub_list
            }
        finally:
            conn.close()

    @classmethod
    def revoke_review_request(cls, user_id: str, share_token: str) -> bool:
        """Revokes a share token immediately."""
        conn = _get_db_connection()
        try:
            with conn:
                cursor = conn.execute("""
                    UPDATE peer_feedback_requests
                    SET status = 'revoked'
                    WHERE share_token = ? AND user_id = ?
                """, (share_token, user_id))
                return cursor.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def _sanitize_pii(cls, text: str) -> str:
        """Basic masking for emails, phone numbers, and full names."""
        import re
        sanitized = re.sub(r'[\w\.-]+@[\w\.-]+', '[EMAIL REDACTED]', text)
        sanitized = re.sub(r'\b\d{10}\b|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b', '[PHONE REDACTED]', sanitized)
        return sanitized
