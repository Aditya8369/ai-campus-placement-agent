"""
utils/ai_metrics.py
AI Call Metrics & Performance Tracking Service (#434).

Records per-call telemetry for Gemini API invocations across analysis,
interview, and outreach features:
- Timestamp, feature, model, latency (ms), token counts, success flag, error type.
- Never stores prompts, candidate responses, or resume text.
- Aggregates daily volume, average latency, 95th percentile (p95) latency,
  failure rate, and common error distributions.
- Supports date range filtering and administrative CSV export.
"""

import csv
import io
import logging
import math
import uuid
import contextvars
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Valid features supported by placement agent platform
VALID_FEATURES = {"analysis", "interview", "outreach", "coding", "general"}

# Thread/async-safe contextual feature tracking
_current_ai_feature: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_ai_feature", default=None
)


def set_current_ai_feature(feature: Optional[str]) -> Any:
    """Sets the active feature context for downstream AI calls."""
    clean = (feature or "").strip().lower()
    val = clean if clean in VALID_FEATURES else None
    return _current_ai_feature.set(val)


def get_current_ai_feature() -> Optional[str]:
    """Retrieves the active feature context if set."""
    return _current_ai_feature.get()


def init_ai_metrics_table(conn=None) -> None:
    """
    Initializes the ai_call_metrics SQLite table and indexes if they do not exist (#434).
    """
    from utils.database import get_db_connection

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_call_metrics (
                id TEXT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                feature TEXT NOT NULL DEFAULT 'analysis',
                model TEXT NOT NULL,
                latency_ms REAL NOT NULL DEFAULT 0.0,
                token_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                candidate_tokens INTEGER DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 1,
                error_type TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_metrics_timestamp ON ai_call_metrics (timestamp DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_metrics_feature ON ai_call_metrics (feature)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_metrics_success ON ai_call_metrics (success)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_metrics_error ON ai_call_metrics (error_type)")
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing ai_call_metrics table: {e}")
    finally:
        if should_close:
            conn.close()


def record_ai_call_metric(
    feature: str = "analysis",
    model: str = "gemini-2.5-flash",
    latency_ms: float = 0.0,
    token_count: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    candidate_tokens: Optional[int] = None,
    success: bool = True,
    error_type: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """
    Records exactly one telemetry row for an AI invocation (#434).

    Strict Privacy Assurance:
    Prompts, candidate responses, resume text, and PII are never received
    or stored in this table. Only operational telemetry is recorded.
    """
    from utils.database import get_db_connection

    clean_feature = (feature or "analysis").strip().lower()
    if clean_feature not in VALID_FEATURES:
        clean_feature = "analysis"

    p_tokens = max(0, int(prompt_tokens or 0))
    c_tokens = max(0, int(candidate_tokens or 0))
    t_tokens = int(token_count) if token_count is not None else (p_tokens + c_tokens)

    clean_latency = max(0.0, round(float(latency_ms), 2))
    success_int = 1 if success else 0
    clean_error_type = (error_type.strip() if error_type else None) if not success else None

    # Track AI latency in active request performance tracker (#task-performance-monitoring)
    try:
        from utils.performance_monitor import record_ai_timing
        record_ai_timing(clean_latency, call_count=1)
    except Exception:
        pass

    metric_id = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        init_ai_metrics_table(conn)
        cursor = conn.cursor()

        if timestamp:
            cursor.execute("""
                INSERT INTO ai_call_metrics (
                    id, timestamp, feature, model, latency_ms,
                    token_count, prompt_tokens, candidate_tokens,
                    success, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric_id,
                timestamp,
                clean_feature,
                str(model or "gemini-2.5-flash"),
                clean_latency,
                t_tokens,
                p_tokens,
                c_tokens,
                success_int,
                clean_error_type,
            ))
        else:
            cursor.execute("""
                INSERT INTO ai_call_metrics (
                    id, feature, model, latency_ms,
                    token_count, prompt_tokens, candidate_tokens,
                    success, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric_id,
                clean_feature,
                str(model or "gemini-2.5-flash"),
                clean_latency,
                t_tokens,
                p_tokens,
                c_tokens,
                success_int,
                clean_error_type,
            ))
        conn.commit()
        return metric_id
    except Exception as e:
        logger.error(f"Failed to record AI call metric: {e}")
        return metric_id
    finally:
        conn.close()


def calculate_p95(latencies: List[float]) -> float:
    """
    Computes the 95th percentile latency from a list of latencies.
    Returns 0.0 if list is empty.
    Uses nearest rank / percentile formula.
    """
    if not latencies:
        return 0.0
    sorted_lats = sorted(latencies)
    n = len(sorted_lats)
    if n == 1:
        return round(sorted_lats[0], 2)
    # 95th percentile index (0-based)
    k = (n - 1) * 0.95
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_lats[int(k)], 2)
    d0 = sorted_lats[f] * (c - k)
    d1 = sorted_lats[c] * (k - f)
    return round(d0 + d1, 2)


def get_ai_metrics_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    feature: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aggregates operational metrics across AI calls (#434):
    - Daily call counts
    - Average and 95th percentile (p95) latency
    - Failure rate percentage
    - Table of most common error types
    - Feature and model breakdowns
    - Gracefully handles an empty database.
    """
    from utils.database import get_db_connection

    conn = get_db_connection()
    try:
        init_ai_metrics_table(conn)
        cursor = conn.cursor()

        # Build parameterized where clause for date range and feature
        where_clauses = []
        params: List[Any] = []

        if start_date:
            clean_start = str(start_date).strip()
            # If start_date has format YYYY-MM-DD
            if len(clean_start) == 10:
                where_clauses.append("date(timestamp) >= date(?)")
                params.append(clean_start)
            else:
                where_clauses.append("timestamp >= ?")
                params.append(clean_start)

        if end_date:
            clean_end = str(end_date).strip()
            if len(clean_end) == 10:
                where_clauses.append("date(timestamp) <= date(?)")
                params.append(clean_end)
            else:
                where_clauses.append("timestamp <= ?")
                params.append(clean_end)

        # Feature filter
        if feature and feature.strip().lower() != "all":
            where_clauses.append("LOWER(feature) = LOWER(?)")
            params.append(feature.strip().lower())

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # 1. Overall Aggregates (total, success, failure, avg latency, tokens)
        cursor.execute(f"""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls,
                COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms,
                COALESCE(SUM(token_count), 0) as total_tokens,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(candidate_tokens), 0) as total_candidate_tokens
            FROM ai_call_metrics
            {where_sql}
        """, params)
        overview_row = cursor.fetchone()

        total_calls = overview_row["total_calls"] if overview_row and overview_row["total_calls"] else 0
        successful_calls = overview_row["successful_calls"] if overview_row and overview_row["successful_calls"] else 0
        failed_calls = overview_row["failed_calls"] if overview_row and overview_row["failed_calls"] else 0
        avg_latency = round(float(overview_row["avg_latency_ms"]), 2) if overview_row and overview_row["avg_latency_ms"] else 0.0
        failure_rate = round((failed_calls / total_calls) * 100, 2) if total_calls > 0 else 0.0

        # 2. Extract latencies to compute overall 95th percentile
        cursor.execute(f"""
            SELECT latency_ms
            FROM ai_call_metrics
            {where_sql}
            ORDER BY latency_ms ASC
        """, params)
        all_latencies = [float(r["latency_ms"]) for r in cursor.fetchall() if r["latency_ms"] is not None]
        p95_latency = calculate_p95(all_latencies)

        # 3. Daily Call Counts and Daily Latencies
        cursor.execute(f"""
            SELECT
                date(timestamp) as call_date,
                COUNT(*) as daily_total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as daily_success,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as daily_failed,
                COALESCE(AVG(latency_ms), 0.0) as daily_avg_latency,
                COALESCE(SUM(token_count), 0) as daily_tokens
            FROM ai_call_metrics
            {where_sql}
            GROUP BY date(timestamp)
            ORDER BY call_date DESC
        """, params)
        daily_rows = cursor.fetchall()

        # Query latencies grouped by day for accurate daily p95
        daily_metrics = []
        for d in daily_rows:
            d_date = d["call_date"]
            d_total = d["daily_total"]
            d_failed = d["daily_failed"]
            d_rate = round((d_failed / d_total) * 100, 2) if d_total > 0 else 0.0

            # Daily p95
            daily_where_clause = "WHERE date(timestamp) = date(?)"
            daily_params: List[Any] = [d_date]
            if feature and feature.strip().lower() != "all":
                daily_where_clause += " AND LOWER(feature) = LOWER(?)"
                daily_params.append(feature.strip().lower())

            cursor.execute(f"""
                SELECT latency_ms
                FROM ai_call_metrics
                {daily_where_clause}
                ORDER BY latency_ms ASC
            """, daily_params)
            d_lats = [float(r["latency_ms"]) for r in cursor.fetchall() if r["latency_ms"] is not None]
            d_p95 = calculate_p95(d_lats)

            daily_metrics.append({
                "date": d_date,
                "total_calls": d_total,
                "successful_calls": d["daily_success"],
                "failed_calls": d_failed,
                "failure_rate_pct": d_rate,
                "avg_latency_ms": round(float(d["daily_avg_latency"]), 2),
                "p95_latency_ms": d_p95,
                "total_tokens": d["daily_tokens"],
            })

        # 4. Most Common Error Types Table
        error_where_sql = "WHERE success = 0 AND error_type IS NOT NULL AND error_type != ''"
        if where_clauses:
            error_where_sql += " AND " + " AND ".join(where_clauses)
        cursor.execute(f"""
            SELECT
                error_type,
                COUNT(*) as count,
                MAX(timestamp) as last_occurred
            FROM ai_call_metrics
            {error_where_sql}
            GROUP BY error_type
            ORDER BY count DESC
        """, params)
        error_rows = cursor.fetchall()

        common_errors = []
        for err in error_rows:
            err_count = err["count"]
            err_pct = round((err_count / failed_calls) * 100, 1) if failed_calls > 0 else 0.0
            common_errors.append({
                "error_type": err["error_type"],
                "count": err_count,
                "percentage_of_errors": err_pct,
                "last_occurred": err["last_occurred"],
            })

        # 5. Feature Breakdown Table (analysis, interview, outreach)
        cursor.execute(f"""
            SELECT
                feature,
                COUNT(*) as call_count,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
                COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms,
                COALESCE(SUM(token_count), 0) as total_tokens
            FROM ai_call_metrics
            {where_sql}
            GROUP BY feature
            ORDER BY call_count DESC
        """, params)
        feature_rows = cursor.fetchall()

        feature_breakdown = []
        for feat in feature_rows:
            f_count = feat["call_count"]
            f_fail = feat["failure_count"]
            f_rate = round((f_fail / f_count) * 100, 1) if f_count > 0 else 0.0
            feature_breakdown.append({
                "feature": feat["feature"],
                "call_count": f_count,
                "success_count": feat["success_count"],
                "failure_count": f_fail,
                "failure_rate_pct": f_rate,
                "avg_latency_ms": round(float(feat["avg_latency_ms"]), 2),
                "total_tokens": feat["total_tokens"],
            })

        # 6. Model Breakdown Table
        cursor.execute(f"""
            SELECT
                model,
                COUNT(*) as call_count,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
                COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms,
                COALESCE(SUM(token_count), 0) as total_tokens
            FROM ai_call_metrics
            {where_sql}
            GROUP BY model
            ORDER BY call_count DESC
        """, params)
        model_rows = cursor.fetchall()

        model_breakdown = []
        for mod in model_rows:
            m_count = mod["call_count"]
            m_fail = mod["failure_count"]
            m_rate = round((m_fail / m_count) * 100, 1) if m_count > 0 else 0.0
            model_breakdown.append({
                "model": mod["model"],
                "call_count": m_count,
                "success_count": mod["success_count"],
                "failure_count": m_fail,
                "failure_rate_pct": m_rate,
                "avg_latency_ms": round(float(mod["avg_latency_ms"]), 2),
                "total_tokens": mod["total_tokens"],
            })

        # 7. Recent Invocations (sanitized metadata, last 25)
        cursor.execute(f"""
            SELECT id, timestamp, feature, model, latency_ms, token_count,
                   prompt_tokens, candidate_tokens, success, error_type
            FROM ai_call_metrics
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT 50
        """, params)
        recent_calls = [dict(r) for r in cursor.fetchall()]

        return {
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "failure_rate_pct": failure_rate,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "total_tokens": overview_row["total_tokens"] if overview_row else 0,
            "total_prompt_tokens": overview_row["total_prompt_tokens"] if overview_row else 0,
            "total_candidate_tokens": overview_row["total_candidate_tokens"] if overview_row else 0,
            "daily_metrics": daily_metrics,
            "common_errors": common_errors,
            "feature_breakdown": feature_breakdown,
            "model_breakdown": model_breakdown,
            "recent_calls": recent_calls,
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "feature": feature or "all",
            }
        }
    except Exception as e:
        logger.error(f"Error computing AI metrics summary: {e}")
        return {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "failure_rate_pct": 0.0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_candidate_tokens": 0,
            "daily_metrics": [],
            "common_errors": [],
            "feature_breakdown": [],
            "model_breakdown": [],
            "recent_calls": [],
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "feature": feature or "all",
            }
        }
    finally:
        conn.close()


def export_ai_metrics_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    feature: Optional[str] = None,
) -> str:
    """
    Exports filtered AI call metrics to a CSV formatted string (#434).
    Guarantees no prompts or candidate data are ever included.
    Handles an empty database gracefully by outputting the header row.
    """
    from utils.database import get_db_connection

    conn = get_db_connection()
    try:
        init_ai_metrics_table(conn)
        cursor = conn.cursor()

        where_clauses = []
        params: List[Any] = []

        if start_date:
            clean_start = str(start_date).strip()
            if len(clean_start) == 10:
                where_clauses.append("date(timestamp) >= date(?)")
                params.append(clean_start)
            else:
                where_clauses.append("timestamp >= ?")
                params.append(clean_start)

        if end_date:
            clean_end = str(end_date).strip()
            if len(clean_end) == 10:
                where_clauses.append("date(timestamp) <= date(?)")
                params.append(clean_end)
            else:
                where_clauses.append("timestamp <= ?")
                params.append(clean_end)

        # Feature filter
        if feature and feature.strip().lower() != "all":
            where_clauses.append("LOWER(feature) = LOWER(?)")
            params.append(feature.strip().lower())

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cursor.execute(f"""
            SELECT
                id,
                timestamp,
                feature,
                model,
                latency_ms,
                token_count,
                prompt_tokens,
                candidate_tokens,
                success,
                COALESCE(error_type, '') as error_type
            FROM ai_call_metrics
            {where_sql}
            ORDER BY timestamp DESC
        """, params)
        rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "id",
            "timestamp",
            "feature",
            "model",
            "latency_ms",
            "token_count",
            "prompt_tokens",
            "candidate_tokens",
            "success",
            "error_type"
        ])

        for r in rows:
            writer.writerow([
                r["id"],
                r["timestamp"],
                r["feature"],
                r["model"],
                r["latency_ms"],
                r["token_count"],
                r["prompt_tokens"],
                r["candidate_tokens"],
                r["success"],
                r["error_type"],
            ])

        return output.getvalue()
    except Exception as e:
        logger.error(f"Error exporting AI metrics to CSV: {e}")
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "id",
            "timestamp",
            "feature",
            "model",
            "latency_ms",
            "token_count",
            "prompt_tokens",
            "candidate_tokens",
            "success",
            "error_type"
        ])
        return output.getvalue()
    finally:
        conn.close()
