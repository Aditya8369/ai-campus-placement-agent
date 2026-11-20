"""
System Monitoring, Backup, Telemetry & User Feedback Repository (db/system.py)
==============================================================================
Handles database operations for online backups, integrity checks, restoration,
Gemini API cost and usage telemetry, and candidate feedback collection.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from db.connection import get_connection, transaction

logger = logging.getLogger(__name__)

COST_PER_PROMPT_TOKEN = 0.000000075
COST_PER_CANDIDATE_TOKEN = 0.00000030


def create_database_backup(
    backup_destination_path: str,
    db_path: Optional[str] = None,
) -> str:
    """Performs an online, zero-downtime hot backup of the SQLite database."""
    with get_connection(db_path) as src_conn:
        logger.info(f"Initiating online database backup to: {backup_destination_path}")
        dest_conn = sqlite3.connect(backup_destination_path)
        try:
            with dest_conn:
                src_conn.backup(dest_conn, pages=20, sleep=0.01)
            logger.info("Online database backup completed successfully.")
            return backup_destination_path
        except Exception as exc:
            logger.error(f"Failed to create database backup: {exc}")
            raise RuntimeError(f"Database backup failed: {exc}") from exc
        finally:
            dest_conn.close()


def restore_database_backup(
    backup_filepath: str,
    admin_identifier: str = "admin",
) -> Dict[str, Any]:
    """Bridge function to execute database restoration via utils.backup_restoration (#245)."""
    from utils.backup_restoration import restore_database_from_backup
    return restore_database_from_backup(backup_identifier=backup_filepath, admin_user=admin_identifier)


def verify_database_integrity(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Runs SQLite integrity PRAGMA checks and structural statistics."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            integrity_rows = [row[0] for row in cursor.fetchall()]
            is_healthy = len(integrity_rows) == 1 and integrity_rows[0].lower() == "ok"

            cursor.execute("SELECT COUNT(*) FROM analyses")
            analyses_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM interviews")
            interviews_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM cohort_benchmarks")
            cohort_count = cursor.fetchone()[0]

            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]

            return {
                "healthy": is_healthy,
                "status": "ok" if is_healthy else "corrupted",
                "messages": integrity_rows,
                "tables": {
                    "analyses_count": analyses_count,
                    "interviews_count": interviews_count,
                    "cohort_benchmarks_count": cohort_count,
                },
                "journal_mode": journal_mode,
            }
    except Exception as exc:
        logger.error(f"Error executing database integrity verification: {exc}")
        return {
            "healthy": False,
            "status": "error",
            "messages": [str(exc)],
            "tables": {},
            "journal_mode": "unknown",
        }


def calculate_gemini_call_cost(prompt_tokens: int, candidate_tokens: int) -> float:
    """Calculates estimated cost in USD based on prompt and candidate token counts (#215)."""
    prompt_cost = max(0, prompt_tokens) * COST_PER_PROMPT_TOKEN
    candidate_cost = max(0, candidate_tokens) * COST_PER_CANDIDATE_TOKEN
    return round(prompt_cost + candidate_cost, 6)


def log_gemini_api_call(
    endpoint: str,
    model_name: str,
    prompt_tokens: int = 0,
    candidate_tokens: int = 0,
    total_tokens: Optional[int] = None,
    latency_ms: int = 0,
    status: str = "success",
    error_message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Logs a single Gemini API execution call with token usage, latency, and estimated cost (#215)."""
    if total_tokens is None:
        total_tokens = prompt_tokens + candidate_tokens

    cost = calculate_gemini_call_cost(prompt_tokens, candidate_tokens)
    log_id = str(uuid.uuid4())

    try:
        with transaction(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO gemini_api_logs (
                    id, endpoint, model_name, prompt_tokens, candidate_tokens,
                    total_tokens, estimated_cost_usd, latency_ms, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    endpoint,
                    model_name,
                    prompt_tokens,
                    candidate_tokens,
                    total_tokens,
                    cost,
                    latency_ms,
                    status,
                    error_message,
                ),
            )
            return log_id
    except Exception as e:
        logger.error(f"Error logging Gemini API call: {e}")
        return ""


def get_gemini_usage_summary(
    days: int = 30,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieves aggregated Gemini API usage and cost monitoring metrics (#215)."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_calls,
                    SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_calls,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(candidate_tokens), 0) as total_candidate_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost_usd,
                    COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms
                FROM gemini_api_logs
                WHERE created_at >= datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            summary_row = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    endpoint,
                    COUNT(*) as call_count,
                    COALESCE(SUM(total_tokens), 0) as endpoint_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) as endpoint_cost,
                    COALESCE(AVG(latency_ms), 0.0) as endpoint_latency
                FROM gemini_api_logs
                WHERE created_at >= datetime('now', ?)
                GROUP BY endpoint
                ORDER BY call_count DESC
                """,
                (f"-{days} days",),
            )
            endpoints_data = [dict(r) for r in cursor.fetchall()]

            cursor.execute(
                """
                SELECT
                    model_name,
                    COUNT(*) as call_count,
                    COALESCE(SUM(total_tokens), 0) as model_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) as model_cost
                FROM gemini_api_logs
                WHERE created_at >= datetime('now', ?)
                GROUP BY model_name
                ORDER BY call_count DESC
                """,
                (f"-{days} days",),
            )
            models_data = [dict(r) for r in cursor.fetchall()]

            cursor.execute(
                """
                SELECT id, endpoint, model_name, prompt_tokens, candidate_tokens, total_tokens,
                       estimated_cost_usd, latency_ms, status, error_message, created_at
                FROM gemini_api_logs
                ORDER BY created_at DESC
                LIMIT 25
                """
            )
            recent_logs = [dict(r) for r in cursor.fetchall()]

            total_calls = summary_row["total_calls"] if summary_row else 0
            success_calls = summary_row["successful_calls"] if summary_row else 0
            success_rate = round((success_calls / total_calls * 100), 1) if total_calls > 0 else 100.0

            return {
                "timeframe_days": days,
                "total_calls": total_calls,
                "successful_calls": success_calls,
                "failed_calls": summary_row["failed_calls"] if summary_row else 0,
                "success_rate_pct": success_rate,
                "total_prompt_tokens": summary_row["total_prompt_tokens"] if summary_row else 0,
                "total_candidate_tokens": summary_row["total_candidate_tokens"] if summary_row else 0,
                "total_tokens": summary_row["total_tokens"] if summary_row else 0,
                "total_cost_usd": round(summary_row["total_cost_usd"] if summary_row else 0.0, 4),
                "avg_latency_ms": round(summary_row["avg_latency_ms"] if summary_row else 0.0, 1),
                "endpoint_breakdown": endpoints_data,
                "model_breakdown": models_data,
                "recent_logs": recent_logs,
            }
    except Exception as e:
        logger.error(f"Error retrieving Gemini usage summary: {e}")
        return {
            "timeframe_days": days,
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "success_rate_pct": 100.0,
            "total_prompt_tokens": 0,
            "total_candidate_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "endpoint_breakdown": [],
            "model_breakdown": [],
            "recent_logs": [],
        }


def submit_user_feedback(
    student_id: str,
    rating: int,
    category: str,
    comment: str,
    feedback_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Records student experience feedback with rating (1-5), category, and comments (#197)."""
    f_id = feedback_id or f"fb-{uuid.uuid4().hex[:12]}"
    normalized_student_id = (student_id or "default_student").strip()
    clamped_rating = max(1, min(5, int(rating)))
    norm_category = (category or "General Experience").strip()
    norm_comment = (comment or "").strip()

    with transaction(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO user_feedback (id, student_id, rating, category, comment, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (f_id, normalized_student_id, clamped_rating, norm_category, norm_comment),
        )

        cursor.execute("SELECT * FROM user_feedback WHERE id = ?", (f_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_user_feedback_list(
    student_id: Optional[str] = None,
    category_filter: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieves recorded user feedback entries, optionally filtered by student or category."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM user_feedback WHERE 1=1"
            params: List[Any] = []

            if student_id and student_id.strip():
                query += " AND student_id = ?"
                params.append(student_id.strip())

            if category_filter and category_filter.strip() and category_filter.strip().lower() not in ("all", "any"):
                query += " AND LOWER(category) = LOWER(?)"
                params.append(category_filter.strip())

            query += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(max(1, int(limit)))

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching user feedback: {e}")
        return []


def get_feedback_metrics_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculates aggregated satisfaction scores and category distribution (#197)."""
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_feedback,
                    COALESCE(AVG(rating), 0) as avg_rating,
                    COALESCE(SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END), 0) as five_star_count,
                    COALESCE(SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END), 0) as four_star_count,
                    COALESCE(SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END), 0) as three_star_count,
                    COALESCE(SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END), 0) as two_star_count,
                    COALESCE(SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END), 0) as one_star_count
                FROM user_feedback
                """
            )
            row = cursor.fetchone()
            stats = dict(row) if row else {}
            stats["avg_rating"] = round(float(stats.get("avg_rating", 0.0)), 2)

            cursor.execute(
                """
                SELECT category, COUNT(*) as count, AVG(rating) as category_avg
                FROM user_feedback
                GROUP BY category
                ORDER BY count DESC
                """
            )
            stats["category_breakdown"] = [
                {
                    "category": r["category"],
                    "count": r["count"],
                    "avg_rating": round(float(r["category_avg"] or 0), 1),
                }
                for r in cursor.fetchall()
            ]
            return stats
    except Exception as e:
        logger.error(f"Error computing feedback metrics summary: {e}")
        return {
            "total_feedback": 0,
            "avg_rating": 0.0,
            "five_star_count": 0,
            "four_star_count": 0,
            "three_star_count": 0,
            "two_star_count": 0,
            "one_star_count": 0,
            "category_breakdown": [],
        }
