"""
utils/performance_monitor.py
Safe Performance Monitoring & Latency Breakdown Service (#task-performance-monitoring).

Provides lightweight, privacy-safe timing metrics for Flask routes and operations:
- Decomposes request latency into four critical components:
  1. Database queries (db_duration_ms & db_query_count)
  2. AI service invocations (ai_duration_ms & ai_call_count)
  3. File processing / text extraction (file_duration_ms & file_op_count)
  4. Template rendering (render_duration_ms)
- Identifies the primary bottleneck for every request:
  'database', 'ai_service', 'file_processing', 'rendering', or 'application'.
- Emits W3C Server-Timing HTTP response headers (total, db, ai, file, render)
  for transparent DevTools observability.
- Records telemetry to SQLite table `request_performance_metrics`.
- Strict Privacy Guarantee:
  Never logs or stores resume text, candidate answers, passwords, authorization tokens,
  or confidential session payloads. All URL query strings are sanitized to remove sensitive tokens.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
import csv
import datetime as dt
import io
import logging
import math
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import config

logger = logging.getLogger(__name__)

# Configurable thresholds
SLOW_THRESHOLD_MS: float = getattr(config, "SLOW_REQUEST_THRESHOLD_MS", 500.0)
PERFORMANCE_MONITORING_ENABLED: bool = getattr(config, "PERFORMANCE_MONITORING_ENABLED", True)
EXCLUDE_STATIC_PERFORMANCE: bool = getattr(config, "EXCLUDE_STATIC_PERFORMANCE", True)

# Regex patterns for path sanitization to eliminate tokens/keys
SENSITIVE_PARAM_PATTERN = re.compile(
    r"([?&](?:token|key|api_key|password|secret|code|auth)=)[^&\s]+",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Context variable for thread/async safety across request lifecycles
_current_request_perf: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "current_request_perf", default=None
)


def _get_active_tracker() -> Optional[Dict[str, Any]]:
    """Retrieves the active performance telemetry tracker for the current request."""
    # Check Flask g context first if available
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, "_perf_tracker"):
            return g._perf_tracker
    except Exception:
        pass
    return _current_request_perf.get()


def record_db_timing(duration_ms: float, query_count: int = 1) -> None:
    """Safely increments the database timing counter for the active request."""
    tracker = _get_active_tracker()
    if tracker is not None:
        tracker["db_duration_ms"] += max(0.0, float(duration_ms))
        tracker["db_query_count"] += max(0, int(query_count))


def record_ai_timing(duration_ms: float, call_count: int = 1) -> None:
    """Safely increments the AI service timing counter for the active request."""
    tracker = _get_active_tracker()
    if tracker is not None:
        tracker["ai_duration_ms"] += max(0.0, float(duration_ms))
        tracker["ai_call_count"] += max(0, int(call_count))


def record_file_timing(duration_ms: float, op_count: int = 1) -> None:
    """Safely increments the file processing timing counter for the active request."""
    tracker = _get_active_tracker()
    if tracker is not None:
        tracker["file_duration_ms"] += max(0.0, float(duration_ms))
        tracker["file_op_count"] += max(0, int(op_count))


def record_render_timing(duration_ms: float) -> None:
    """Safely increments the template rendering timing counter for the active request."""
    tracker = _get_active_tracker()
    if tracker is not None:
        tracker["render_duration_ms"] += max(0.0, float(duration_ms))


@contextmanager
def track_component(component: str):
    """
    Context manager to accurately measure execution time of a specific component:
    'database', 'ai_service', 'file_processing', or 'rendering'.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        dur_ms = (time.perf_counter() - start) * 1000.0
        comp = (component or "").strip().lower()
        if comp in ("database", "db"):
            record_db_timing(dur_ms)
        elif comp in ("ai_service", "ai", "gemini"):
            record_ai_timing(dur_ms)
        elif comp in ("file_processing", "file", "pdf", "docx"):
            record_file_timing(dur_ms)
        elif comp in ("rendering", "render", "template"):
            record_render_timing(dur_ms)


def sanitize_path(raw_path: str) -> str:
    """
    Strips sensitive query parameters (e.g. ?token=..., ?key=...) and normalizes
    UUIDs in paths to ensure privacy and prevent high-cardinality endpoint fragmentation.
    """
    if not raw_path:
        return "/"
    # Scrub sensitive query parameters
    cleaned = SENSITIVE_PARAM_PATTERN.sub(r"\g<1>[REDACTED]", raw_path)
    # If path only (no query string), normalize UUIDs for consistent endpoint reporting
    if "?" not in cleaned:
        cleaned = UUID_PATTERN.sub("<id>", cleaned)
    else:
        path_part, query_part = cleaned.split("?", 1)
        path_part = UUID_PATTERN.sub("<id>", path_part)
        cleaned = f"{path_part}?{query_part}"
    return cleaned


def calculate_primary_bottleneck(
    db_ms: float,
    ai_ms: float,
    file_ms: float,
    render_ms: float,
    total_ms: float,
) -> str:
    """
    Determines the primary component driving latency for maintainers.
    Returns: 'ai_service', 'database', 'file_processing', 'rendering', or 'application'.
    """
    components = [
        ("ai_service", ai_ms),
        ("database", db_ms),
        ("file_processing", file_ms),
        ("rendering", render_ms),
    ]
    # Find component with the highest elapsed time
    dominant_name, dominant_time = max(components, key=lambda item: item[1])

    # If the dominant component is notable (at least 20% of total or > 100ms)
    if dominant_time > 0 and (total_ms <= 0 or (dominant_time / max(1.0, total_ms)) >= 0.20 or dominant_time >= 100.0):
        return dominant_name

    # Otherwise application logic / network latency dominates
    return "application"


# ==============================================================================
# Database Schema & Persistence
# ==============================================================================

def init_performance_table(conn=None) -> None:
    """
    Initializes the request_performance_metrics table and indexes.
    Preserves existing telemetry without breaking changes.
    """
    from utils.database import get_db_connection

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_performance_metrics (
                id TEXT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                method TEXT NOT NULL,
                endpoint TEXT,
                path TEXT NOT NULL,
                status_code INTEGER DEFAULT 200,
                duration_ms REAL NOT NULL,
                db_duration_ms REAL DEFAULT 0.0,
                db_query_count INTEGER DEFAULT 0,
                ai_duration_ms REAL DEFAULT 0.0,
                ai_call_count INTEGER DEFAULT 0,
                file_duration_ms REAL DEFAULT 0.0,
                file_op_count INTEGER DEFAULT 0,
                render_duration_ms REAL DEFAULT 0.0,
                is_slow INTEGER NOT NULL DEFAULT 0,
                primary_bottleneck TEXT NOT NULL DEFAULT 'application'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_timestamp ON request_performance_metrics (timestamp DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_endpoint ON request_performance_metrics (endpoint)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_is_slow ON request_performance_metrics (is_slow)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_duration ON request_performance_metrics (duration_ms DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_bottleneck ON request_performance_metrics (primary_bottleneck)")
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing request_performance_metrics table: {e}")
    finally:
        if should_close:
            conn.close()


def record_request_metric(
    method: str,
    endpoint: str,
    path: str,
    status_code: int,
    duration_ms: float,
    db_duration_ms: float = 0.0,
    db_query_count: int = 0,
    ai_duration_ms: float = 0.0,
    ai_call_count: int = 0,
    file_duration_ms: float = 0.0,
    file_op_count: int = 0,
    render_duration_ms: float = 0.0,
    is_slow: int = 0,
    primary_bottleneck: str = "application",
    conn=None,
) -> Optional[str]:
    """
    Safely inserts exactly one performance telemetry record into SQLite.
    Never fails or throws exceptions that could disrupt user requests.
    """
    from utils.database import get_db_connection

    record_id = str(uuid.uuid4())
    should_close = False
    if conn is None:
        try:
            conn = get_db_connection()
            should_close = True
        except Exception as e:
            logger.debug(f"Unable to open database connection for performance metric: {e}")
            return None

    try:
        sanitized = sanitize_path(path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO request_performance_metrics (
                id, method, endpoint, path, status_code,
                duration_ms, db_duration_ms, db_query_count,
                ai_duration_ms, ai_call_count, file_duration_ms,
                file_op_count, render_duration_ms, is_slow,
                primary_bottleneck
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record_id,
            (method or "GET").upper(),
            endpoint or "unknown",
            sanitized,
            int(status_code),
            round(max(0.0, float(duration_ms)), 2),
            round(max(0.0, float(db_duration_ms)), 2),
            max(0, int(db_query_count)),
            round(max(0.0, float(ai_duration_ms)), 2),
            max(0, int(ai_call_count)),
            round(max(0.0, float(file_duration_ms)), 2),
            max(0, int(file_op_count)),
            round(max(0.0, float(render_duration_ms)), 2),
            int(is_slow),
            primary_bottleneck or "application",
        ))
        conn.commit()
        return record_id
    except Exception as e:
        logger.debug(f"Failed to record request performance metric: {e}")
        return None
    finally:
        if should_close:
            try:
                conn.close()
            except Exception:
                pass


# ==============================================================================
# SQLite Monitored Connection & Cursor Wrappers
# ==============================================================================

class MonitoredCursor(sqlite3.Cursor):
    """
    Cursor subclass that automatically records query execution timing into the
    active request's performance tracker without storing query text or parameters.
    """
    def execute(self, sql: str, parameters=()):
        start = time.perf_counter()
        try:
            return super().execute(sql, parameters)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_db_timing(dur_ms, query_count=1)

    def executemany(self, sql: str, seq_of_parameters):
        start = time.perf_counter()
        count = len(seq_of_parameters) if hasattr(seq_of_parameters, "__len__") else 1
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_db_timing(dur_ms, query_count=max(1, count))


class MonitoredConnection(sqlite3.Connection):
    """
    Connection subclass that returns MonitoredCursor instances and instruments
    direct connection execution calls (`conn.execute`, `conn.executemany`).
    """
    def cursor(self, *args, **kwargs):
        return super().cursor(MonitoredCursor)

    def execute(self, sql: str, *args, **kwargs):
        start = time.perf_counter()
        try:
            return super().execute(sql, *args, **kwargs)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_db_timing(dur_ms, query_count=1)

    def executemany(self, sql: str, *args, **kwargs):
        start = time.perf_counter()
        try:
            return super().executemany(sql, *args, **kwargs)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_db_timing(dur_ms, query_count=1)

    def executescript(self, sql_script: str):
        start = time.perf_counter()
        try:
            return super().executescript(sql_script)
        finally:
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_db_timing(dur_ms, query_count=1)


# ==============================================================================
# Summary Analytics & Aggregations for Maintainers
# ==============================================================================

def get_performance_summary(
    endpoint: Optional[str] = None,
    is_slow: Optional[bool] = None,
    bottleneck: Optional[str] = None,
    time_range: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    conn=None,
) -> Dict[str, Any]:
    """
    Calculates operational performance metrics and component breakdowns
    for administrative inspection and slow endpoint triage.
    """
    from utils.database import get_db_connection

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()

        # Build dynamic WHERE clause
        where_clauses: List[str] = []
        params: List[Any] = []

        if endpoint and endpoint != "all":
            where_clauses.append("endpoint = ?")
            params.append(endpoint.strip())

        if is_slow is True:
            where_clauses.append("is_slow = 1")
        elif is_slow is False:
            where_clauses.append("is_slow = 0")

        if bottleneck and bottleneck != "all":
            where_clauses.append("primary_bottleneck = ?")
            params.append(bottleneck.strip().lower())

        if time_range == "1h":
            where_clauses.append("timestamp >= datetime('now', '-1 hour')")
        elif time_range == "24h":
            where_clauses.append("timestamp >= datetime('now', '-24 hours')")
        elif time_range == "7d":
            where_clauses.append("timestamp >= datetime('now', '-7 days')")
        elif time_range == "30d":
            where_clauses.append("timestamp >= datetime('now', '-30 days')")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # 1. Overall KPIs
        kpi_query = f"""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(AVG(duration_ms), 0.0) as avg_duration,
                COALESCE(MAX(duration_ms), 0.0) as max_duration,
                COALESCE(SUM(CASE WHEN is_slow = 1 THEN 1 ELSE 0 END), 0) as slow_requests,
                COALESCE(AVG(db_duration_ms), 0.0) as avg_db,
                COALESCE(AVG(ai_duration_ms), 0.0) as avg_ai,
                COALESCE(AVG(file_duration_ms), 0.0) as avg_file,
                COALESCE(AVG(render_duration_ms), 0.0) as avg_render
            FROM request_performance_metrics
            {where_sql}
        """
        cursor.execute(kpi_query, params)
        kpi_row = cursor.fetchone()
        kpis = dict(kpi_row) if kpi_row else {}

        total_requests = kpis.get("total_requests", 0)
        slow_requests = kpis.get("slow_requests", 0)
        slow_rate_pct = round((slow_requests / total_requests * 100.0), 1) if total_requests > 0 else 0.0

        # 2. 95th Percentile (p95) Latency
        p95_duration = 0.0
        if total_requests > 0:
            p95_offset = max(0, int(math.ceil(total_requests * 0.95)) - 1)
            cursor.execute(f"""
                SELECT duration_ms FROM request_performance_metrics
                {where_sql}
                ORDER BY duration_ms ASC
                LIMIT 1 OFFSET ?
            """, params + [p95_offset])
            p95_row = cursor.fetchone()
            if p95_row:
                p95_duration = round(float(p95_row[0]), 1)

        # 3. Bottleneck Distribution Breakdown
        cursor.execute(f"""
            SELECT primary_bottleneck, COUNT(*) as count
            FROM request_performance_metrics
            {where_sql}
            GROUP BY primary_bottleneck
            ORDER BY count DESC
        """, params)
        bottleneck_dist = {row[0]: row[1] for row in cursor.fetchall()}

        # 4. Aggregated Metrics by Endpoint
        cursor.execute(f"""
            SELECT
                endpoint,
                COUNT(*) as call_count,
                ROUND(AVG(duration_ms), 1) as avg_duration_ms,
                ROUND(MAX(duration_ms), 1) as max_duration_ms,
                SUM(CASE WHEN is_slow = 1 THEN 1 ELSE 0 END) as slow_count,
                ROUND(AVG(db_duration_ms), 1) as avg_db_ms,
                ROUND(AVG(ai_duration_ms), 1) as avg_ai_ms,
                ROUND(AVG(file_duration_ms), 1) as avg_file_ms,
                ROUND(AVG(render_duration_ms), 1) as avg_render_ms
            FROM request_performance_metrics
            {where_sql}
            GROUP BY endpoint
            ORDER BY avg_duration_ms DESC
        """, params)
        endpoint_stats = []
        for r in cursor.fetchall():
            row_dict = dict(r)
            # Find dominant bottleneck for endpoint
            comp_averages = [
                ("ai_service", row_dict["avg_ai_ms"]),
                ("database", row_dict["avg_db_ms"]),
                ("file_processing", row_dict["avg_file_ms"]),
                ("rendering", row_dict["avg_render_ms"]),
            ]
            dominant = max(comp_averages, key=lambda x: x[1])
            row_dict["dominant_bottleneck"] = dominant[0] if dominant[1] > 0 else "application"
            endpoint_stats.append(row_dict)

        # 5. Distinct Endpoints for Filter Dropdown
        cursor.execute("SELECT DISTINCT endpoint FROM request_performance_metrics WHERE endpoint IS NOT NULL ORDER BY endpoint ASC")
        all_endpoints = [r[0] for r in cursor.fetchall() if r[0]]

        # 6. Detailed Recent Request Rows
        cursor.execute(f"""
            SELECT
                id, timestamp, method, endpoint, path, status_code,
                duration_ms, db_duration_ms, db_query_count,
                ai_duration_ms, ai_call_count, file_duration_ms,
                file_op_count, render_duration_ms, is_slow,
                primary_bottleneck
            FROM request_performance_metrics
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset])

        recent_requests = [dict(row) for row in cursor.fetchall()]

        return {
            "kpis": {
                "total_requests": total_requests,
                "avg_duration_ms": round(float(kpis.get("avg_duration", 0.0)), 1),
                "p95_duration_ms": p95_duration,
                "max_duration_ms": round(float(kpis.get("max_duration", 0.0)), 1),
                "slow_requests_count": slow_requests,
                "slow_rate_pct": slow_rate_pct,
                "avg_db_ms": round(float(kpis.get("avg_db", 0.0)), 1),
                "avg_ai_ms": round(float(kpis.get("avg_ai", 0.0)), 1),
                "avg_file_ms": round(float(kpis.get("avg_file", 0.0)), 1),
                "avg_render_ms": round(float(kpis.get("avg_render", 0.0)), 1),
                "slow_threshold_ms": SLOW_THRESHOLD_MS,
            },
            "bottlenecks": bottleneck_dist,
            "endpoint_stats": endpoint_stats,
            "all_endpoints": all_endpoints,
            "recent_requests": recent_requests,
            "filters": {
                "endpoint": endpoint or "all",
                "is_slow": is_slow,
                "bottleneck": bottleneck or "all",
                "time_range": time_range or "all",
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_requests,
            }
        }
    except Exception as e:
        logger.error(f"Error compiling performance summary: {e}")
        return {
            "kpis": {"total_requests": 0, "avg_duration_ms": 0.0, "p95_duration_ms": 0.0, "slow_requests_count": 0, "slow_rate_pct": 0.0},
            "bottlenecks": {},
            "endpoint_stats": [],
            "all_endpoints": [],
            "recent_requests": [],
            "filters": {},
            "pagination": {"limit": limit, "offset": offset, "total": 0},
            "error": str(e),
        }
    finally:
        if should_close:
            conn.close()


def export_performance_metrics_csv(
    endpoint: Optional[str] = None,
    is_slow: Optional[bool] = None,
    bottleneck: Optional[str] = None,
    time_range: Optional[str] = None,
    conn=None,
) -> str:
    """
    Generates a privacy-safe CSV export of performance metrics for maintainer analysis.
    Guarantees no user content, passwords, or tokens are exported.
    """
    from utils.database import get_db_connection

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.cursor()
        where_clauses: List[str] = []
        params: List[Any] = []

        if endpoint and endpoint != "all":
            where_clauses.append("endpoint = ?")
            params.append(endpoint.strip())

        if is_slow is True:
            where_clauses.append("is_slow = 1")
        elif is_slow is False:
            where_clauses.append("is_slow = 0")

        if bottleneck and bottleneck != "all":
            where_clauses.append("primary_bottleneck = ?")
            params.append(bottleneck.strip().lower())

        if time_range == "1h":
            where_clauses.append("timestamp >= datetime('now', '-1 hour')")
        elif time_range == "24h":
            where_clauses.append("timestamp >= datetime('now', '-24 hours')")
        elif time_range == "7d":
            where_clauses.append("timestamp >= datetime('now', '-7 days')")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        cursor.execute(f"""
            SELECT
                timestamp, method, endpoint, path, status_code,
                duration_ms, db_duration_ms, db_query_count,
                ai_duration_ms, ai_call_count, file_duration_ms,
                file_op_count, render_duration_ms, is_slow,
                primary_bottleneck
            FROM request_performance_metrics
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT 5000
        """, params)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "timestamp_utc",
            "method",
            "endpoint",
            "sanitized_path",
            "status_code",
            "total_duration_ms",
            "database_duration_ms",
            "database_query_count",
            "ai_service_duration_ms",
            "ai_call_count",
            "file_processing_duration_ms",
            "file_operation_count",
            "rendering_duration_ms",
            "is_slow_flag",
            "primary_bottleneck",
        ])

        for row in cursor.fetchall():
            writer.writerow(list(row))

        return output.getvalue()
    finally:
        if should_close:
            conn.close()


# ==============================================================================
# Flask Application Lifecycle Integration Middleware
# ==============================================================================

def init_performance_monitoring(app) -> None:
    """
    Attaches performance monitoring hooks to the Flask application:
    1. before_request: Initializes per-request timing tracker.
    2. before_render_template & template_rendered: Tracks template render duration.
    3. after_request: Computes component breakdown, sets W3C Server-Timing header,
       logs performance alert if slow, and saves telemetry to database.
    4. teardown_request: Cleans up context variables.
    """
    if not PERFORMANCE_MONITORING_ENABLED:
        logger.info("Performance monitoring is disabled by configuration.")
        return

    from flask import g, request, before_render_template, template_rendered

    @app.before_request
    def _perf_before_request():
        # Skip static assets if configured
        if EXCLUDE_STATIC_PERFORMANCE and (request.path.startswith("/static/") or request.endpoint == "static"):
            return

        tracker = {
            "start_time": time.perf_counter(),
            "db_duration_ms": 0.0,
            "db_query_count": 0,
            "ai_duration_ms": 0.0,
            "ai_call_count": 0,
            "file_duration_ms": 0.0,
            "file_op_count": 0,
            "render_duration_ms": 0.0,
        }
        g._perf_tracker = tracker
        _current_request_perf.set(tracker)

    # Instrument template rendering signals
    def _on_before_render(sender, template, context, **extra):
        if hasattr(g, "_perf_tracker"):
            g._render_start_time = time.perf_counter()

    def _on_template_rendered(sender, template, context, **extra):
        start = getattr(g, "_render_start_time", None)
        if start is not None and hasattr(g, "_perf_tracker"):
            dur_ms = (time.perf_counter() - start) * 1000.0
            record_render_timing(dur_ms)
            g._render_start_time = None

    try:
        before_render_template.connect(_on_before_render, app)
        template_rendered.connect(_on_template_rendered, app)
    except Exception as e:
        logger.debug(f"Unable to connect template render signals: {e}")

    @app.after_request
    def _perf_after_request(response):
        tracker = getattr(g, "_perf_tracker", None)
        if not tracker:
            return response

        total_ms = (time.perf_counter() - tracker["start_time"]) * 1000.0
        db_ms = tracker["db_duration_ms"]
        db_count = tracker["db_query_count"]
        ai_ms = tracker["ai_duration_ms"]
        ai_count = tracker["ai_call_count"]
        file_ms = tracker["file_duration_ms"]
        file_count = tracker["file_op_count"]
        render_ms = tracker["render_duration_ms"]

        # Calculate primary bottleneck
        bottleneck = calculate_primary_bottleneck(db_ms, ai_ms, file_ms, render_ms, total_ms)
        is_slow = 1 if total_ms >= SLOW_THRESHOLD_MS else 0

        # W3C Server-Timing header for browser DevTools observability
        server_timing_parts = [
            f"total;dur={total_ms:.1f}",
            f"db;dur={db_ms:.1f}",
            f"ai;dur={ai_ms:.1f}",
            f"file;dur={file_ms:.1f}",
            f"render;dur={render_ms:.1f}",
        ]
        response.headers["Server-Timing"] = ", ".join(server_timing_parts)

        # Log safe performance alert for maintainers on slow operations (NO sensitive content!)
        if is_slow:
            sanitized = sanitize_path(request.path)
            logger.warning(
                f"[PERFORMANCE WARNING] Slow request detected: {request.method} {sanitized} "
                f"took {total_ms:.1f}ms (Bottleneck: {bottleneck} | "
                f"DB: {db_ms:.1f}ms [{db_count} queries], AI: {ai_ms:.1f}ms [{ai_count} calls], "
                f"File: {file_ms:.1f}ms [{file_count} ops], Render: {render_ms:.1f}ms)"
            )

        # Persist telemetry to SQLite
        try:
            record_request_metric(
                method=request.method,
                endpoint=request.endpoint or "unknown",
                path=request.path,
                status_code=response.status_code,
                duration_ms=total_ms,
                db_duration_ms=db_ms,
                db_query_count=db_count,
                ai_duration_ms=ai_ms,
                ai_call_count=ai_count,
                file_duration_ms=file_ms,
                file_op_count=file_count,
                render_duration_ms=render_ms,
                is_slow=is_slow,
                primary_bottleneck=bottleneck,
            )
        except Exception as e:
            logger.debug(f"Could not record request performance metric: {e}")

        return response

    @app.teardown_request
    def _perf_teardown(exc=None):
        _current_request_perf.set(None)

    logger.info("Initialized safe performance monitoring middleware.")
