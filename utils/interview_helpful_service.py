"""
Interview Experience Helpful Voting & Ranking Service (utils/interview_helpful_service.py)
===========================================================================================
Manages helpful votes, rate-limited voting enforcement, contributor impact tracking,
and 'most helpful' ranking across peer interview experiences (#693).

Key Capabilities:
1. One Vote Per User Per Experience (Idempotent Toggle):
   - Users can vote an approved experience as helpful or withdraw their vote.
2. Self-Voting Prevention:
   - Contributors cannot vote on their own submitted interview experiences.
3. Strict Privacy:
   - Voter identities are never exposed in public queries or API responses;
     only aggregate counts and the requesting user's own vote state are returned.
4. Contributor Impact Metric:
   - Tracks the total number of students helped by a contributor's shared experiences.
5. Rate Limiting:
   - Throttles voting actions per client/student to prevent spam or manipulation.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.database import get_db_connection
from utils.rate_limiter import limiter

logger = logging.getLogger(__name__)

# Default rate limits for voting actions
VOTE_RATE_LIMIT_MAX = 20
VOTE_RATE_LIMIT_WINDOW = 60  # seconds


def ensure_helpful_votes_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Ensures that the helpful_count column and interview_experience_helpful_votes table exist.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()

        # Check helpful_count column on interview_experiences
        cursor.execute("PRAGMA table_info(interview_experiences)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        if "helpful_count" not in existing_cols:
            cursor.execute("ALTER TABLE interview_experiences ADD COLUMN helpful_count INTEGER NOT NULL DEFAULT 0")

        # Create votes table with unique constraint on (experience_id, student_id)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interview_experience_helpful_votes (
                id TEXT PRIMARY KEY,
                experience_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(experience_id, student_id)
            )
        """)

        # Performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_helpful_votes_exp ON interview_experience_helpful_votes (experience_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_helpful_votes_student ON interview_experience_helpful_votes (student_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_experiences_helpful ON interview_experiences (helpful_count DESC, interview_date DESC)")

        conn.commit()
    except Exception as e:
        logger.error(f"Error ensuring helpful votes schema: {e}")
    finally:
        if should_close:
            conn.close()


def toggle_helpful_vote(
    experience_id: str,
    student_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Toggles a helpful vote for a student on an interview experience:
    - If already voted: removes the vote (decrements helpful_count).
    - If not voted: adds the vote (increments helpful_count).
    - Rejects votes on one's own submitted experience (HTTP 403).
    - Rejects votes on reported or rejected experiences (HTTP 400).
    - Returns updated aggregate count and user vote state. Voter identities are never returned.
    """
    clean_exp_id = (experience_id or "").strip()
    clean_student_id = (student_id or "").strip()

    if not clean_exp_id or not clean_student_id:
        return {
            "success": False,
            "error": "Experience ID and Student ID are required.",
            "code": 400,
        }

    with get_db_connection() as conn:
        ensure_helpful_votes_schema(conn)
        cursor = conn.cursor()

        # 1. Fetch experience to verify existence, moderation, and authorship
        cursor.execute(
            "SELECT id, student_id, reported_flag, helpful_count FROM interview_experiences WHERE id = ?",
            (clean_exp_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {
                "success": False,
                "error": f"Interview experience '{clean_exp_id}' not found.",
                "code": 404,
            }

        exp_data = dict(row)

        # Disallow voting on reported content
        if bool(exp_data.get("reported_flag")):
            return {
                "success": False,
                "error": "Cannot vote on an interview experience that has been reported.",
                "code": 400,
            }

        # Check moderation status if column exists
        cursor.execute("PRAGMA table_info(interview_experiences)")
        cols = {r["name"] for r in cursor.fetchall()}
        if "moderation_status" in cols:
            cursor.execute("SELECT moderation_status FROM interview_experiences WHERE id = ?", (clean_exp_id,))
            mod_row = cursor.fetchone()
            if mod_row and str(mod_row["moderation_status"]).strip().lower() == "rejected":
                return {
                    "success": False,
                    "error": "Cannot vote on an interview experience that was rejected by moderation.",
                    "code": 400,
                }

        # Prevent voting on own post
        author_id = str(exp_data.get("student_id") or "").strip()
        if author_id and author_id.lower() == clean_student_id.lower():
            return {
                "success": False,
                "error": "You cannot vote on your own interview experience.",
                "code": 403,
            }

        # 2. Check if the user has already voted
        cursor.execute(
            "SELECT id FROM interview_experience_helpful_votes WHERE experience_id = ? AND student_id = ?",
            (clean_exp_id, clean_student_id),
        )
        existing_vote = cursor.fetchone()

        if existing_vote:
            # Withdraw / remove vote
            cursor.execute(
                "DELETE FROM interview_experience_helpful_votes WHERE experience_id = ? AND student_id = ?",
                (clean_exp_id, clean_student_id),
            )
            voted = False
            action = "removed"
        else:
            # Cast new vote
            vote_id = f"vote-{uuid.uuid4().hex[:12]}"
            cursor.execute(
                "INSERT INTO interview_experience_helpful_votes (id, experience_id, student_id) VALUES (?, ?, ?)",
                (vote_id, clean_exp_id, clean_student_id),
            )
            voted = True
            action = "added"

        # 3. Synchronize aggregate helpful_count
        cursor.execute(
            "SELECT COUNT(*) as count FROM interview_experience_helpful_votes WHERE experience_id = ?",
            (clean_exp_id,),
        )
        count_row = cursor.fetchone()
        new_count = count_row["count"] if count_row else 0

        cursor.execute(
            "UPDATE interview_experiences SET helpful_count = ? WHERE id = ?",
            (new_count, clean_exp_id),
        )
        conn.commit()

        return {
            "success": True,
            "voted": voted,
            "action": action,
            "helpful_count": new_count,
            "experience_id": clean_exp_id,
            "message": "Marked as helpful" if voted else "Helpful vote removed",
            "code": 200,
        }


def get_user_helpful_votes(
    student_id: str,
    experience_ids: Optional[List[str]] = None,
) -> Set[str]:
    """
    Returns the set of experience IDs that the student has marked as helpful.
    Used to highlight the 'Helpful' button state for the active user.
    """
    clean_student_id = (student_id or "").strip()
    if not clean_student_id:
        return set()

    with get_db_connection() as conn:
        ensure_helpful_votes_schema(conn)
        cursor = conn.cursor()

        if experience_ids:
            placeholders = ",".join("?" for _ in experience_ids)
            query = f"""
                SELECT experience_id FROM interview_experience_helpful_votes
                WHERE student_id = ? AND experience_id IN ({placeholders})
            """
            params = [clean_student_id] + list(experience_ids)
            cursor.execute(query, params)
        else:
            cursor.execute(
                "SELECT experience_id FROM interview_experience_helpful_votes WHERE student_id = ?",
                (clean_student_id,),
            )

        rows = cursor.fetchall()
        return {row["experience_id"] for row in rows}


def get_contributor_helped_students_count(student_id: str) -> int:
    """
    Calculates the total number of students helped by this contributor.
    Counts the total helpful votes received across all approved, non-reported
    interview experiences submitted by this student.
    """
    clean_student_id = (student_id or "").strip()
    if not clean_student_id:
        return 0

    with get_db_connection() as conn:
        ensure_helpful_votes_schema(conn)
        cursor = conn.cursor()

        # Count total distinct votes received by this author's approved posts
        cursor.execute(
            """
            SELECT COUNT(v.id) as helped_count
            FROM interview_experience_helpful_votes v
            INNER JOIN interview_experiences e ON v.experience_id = e.id
            WHERE LOWER(e.student_id) = LOWER(?)
              AND e.reported_flag = 0
            """,
            (clean_student_id,),
        )
        row = cursor.fetchone()
        return row["helped_count"] if row and row["helped_count"] else 0


def check_voting_rate_limit(
    student_id: str,
    client_ip: Optional[str] = None,
    max_requests: int = VOTE_RATE_LIMIT_MAX,
    window_seconds: int = VOTE_RATE_LIMIT_WINDOW,
) -> Tuple[bool, int, float]:
    """
    Checks whether a user or IP has exceeded the allowed rate of helpful votes.
    Returns: (is_allowed, remaining_requests, reset_seconds)
    """
    identifier = student_id.strip() if student_id else (client_ip or "127.0.0.1")
    bucket_key = f"helpful_vote:{identifier}"
    return limiter.is_allowed(bucket_key, max_requests=max_requests, window_seconds=window_seconds)
