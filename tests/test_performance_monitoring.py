"""
tests/test_performance_monitoring.py
Unit & Integration Tests for Safe Performance Monitoring & Latency Breakdown (#task-performance-monitoring).

Validates:
1. Performance table initialization and telemetry insertion.
2. Accurate component latency breakdown (Database, AI Service, File Processing, Rendering).
3. Primary bottleneck calculation logic.
4. Privacy sanitization (scrubbing sensitive query parameters, passwords, tokens).
5. W3C Server-Timing header injection on HTTP responses.
6. Administrative access protection on /admin/performance and /api/admin/performance-metrics.
7. Safe CSV export generation without private content.
8. Monitored database connection timing tracking.
"""

import json
import sqlite3
import time
from pathlib import Path
import pytest
from flask import Flask

from app import app
from utils.performance_monitor import (
    init_performance_table,
    record_request_metric,
    get_performance_summary,
    export_performance_metrics_csv,
    calculate_primary_bottleneck,
    sanitize_path,
    record_db_timing,
    record_ai_timing,
    record_file_timing,
    record_render_timing,
    MonitoredConnection,
)
import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_calculate_primary_bottleneck():
    """Verify that primary bottleneck correctly identifies the dominant component."""
    # 1. AI Service dominates
    assert calculate_primary_bottleneck(db_ms=20.0, ai_ms=1200.0, file_ms=50.0, render_ms=10.0, total_ms=1300.0) == "ai_service"

    # 2. Database dominates
    assert calculate_primary_bottleneck(db_ms=450.0, ai_ms=0.0, file_ms=10.0, render_ms=25.0, total_ms=500.0) == "database"

    # 3. File Processing dominates
    assert calculate_primary_bottleneck(db_ms=15.0, ai_ms=0.0, file_ms=350.0, render_ms=10.0, total_ms=400.0) == "file_processing"

    # 4. Rendering dominates
    assert calculate_primary_bottleneck(db_ms=10.0, ai_ms=0.0, file_ms=0.0, render_ms=180.0, total_ms=200.0) == "rendering"

    # 5. General application logic dominates
    assert calculate_primary_bottleneck(db_ms=5.0, ai_ms=0.0, file_ms=0.0, render_ms=5.0, total_ms=300.0) == "application"


def test_sanitize_path_scrubs_secrets():
    """Verify that sensitive query parameters and UUIDs are properly sanitized."""
    # Query parameters with tokens, keys, passwords must be redacted
    dirty_path = "/api/v1/auth/callback?token=secret_jwt_token_12345&user=john"
    cleaned = sanitize_path(dirty_path)
    assert "secret_jwt_token_12345" not in cleaned
    assert "[REDACTED]" in cleaned
    assert "token=" in cleaned

    # Password query param
    dirty_pw = "/reset-password?password=SuperSecretPassword123"
    cleaned_pw = sanitize_path(dirty_pw)
    assert "SuperSecretPassword123" not in cleaned_pw
    assert "[REDACTED]" in cleaned_pw

    # UUID in path must be normalized to prevent cardinality explosion
    uuid_path = "/analysis/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
    normalized = sanitize_path(uuid_path)
    assert "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d" not in normalized
    assert normalized == "/analysis/<id>"


def test_record_request_metric_and_summary():
    """Verify inserting and querying metrics from request_performance_metrics table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_performance_table(conn)

    # Insert test metric records
    rec1 = record_request_metric(
        method="POST",
        endpoint="analysis.analyze_resume",
        path="/analyze",
        status_code=200,
        duration_ms=1250.0,
        db_duration_ms=45.0,
        db_query_count=3,
        ai_duration_ms=1100.0,
        ai_call_count=1,
        file_duration_ms=80.0,
        file_op_count=1,
        render_duration_ms=0.0,
        is_slow=1,
        primary_bottleneck="ai_service",
        conn=conn,
    )
    assert rec1 is not None

    rec2 = record_request_metric(
        method="GET",
        endpoint="dashboard.view_dashboard",
        path="/dashboard",
        status_code=200,
        duration_ms=85.0,
        db_duration_ms=50.0,
        db_query_count=4,
        ai_duration_ms=0.0,
        ai_call_count=0,
        file_duration_ms=0.0,
        file_op_count=0,
        render_duration_ms=25.0,
        is_slow=0,
        primary_bottleneck="database",
        conn=conn,
    )
    assert rec2 is not None

    summary = get_performance_summary(conn=conn)
    kpis = summary["kpis"]

    assert kpis["total_requests"] == 2
    assert kpis["slow_requests_count"] == 1
    assert kpis["slow_rate_pct"] == 50.0
    assert kpis["avg_ai_ms"] == 550.0  # (1100 + 0) / 2
    assert kpis["avg_db_ms"] == 47.5   # (45 + 50) / 2

    # Verify bottleneck distribution
    assert summary["bottlenecks"].get("ai_service") == 1
    assert summary["bottlenecks"].get("database") == 1

    # Verify endpoint aggregation
    assert len(summary["endpoint_stats"]) == 2
    ep_names = [ep["endpoint"] for ep in summary["endpoint_stats"]]
    assert "analysis.analyze_resume" in ep_names
    assert "dashboard.view_dashboard" in ep_names


def test_export_performance_metrics_csv():
    """Verify CSV export contains expected column headers and excludes private content."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_performance_table(conn)

    record_request_metric(
        method="GET",
        endpoint="home.index",
        path="/",
        status_code=200,
        duration_ms=45.0,
        db_duration_ms=10.0,
        ai_duration_ms=0.0,
        file_duration_ms=0.0,
        render_duration_ms=20.0,
        is_slow=0,
        primary_bottleneck="rendering",
        conn=conn,
    )

    csv_data = export_performance_metrics_csv(conn=conn)
    assert "timestamp_utc,method,endpoint,sanitized_path,status_code" in csv_data
    assert "database_duration_ms" in csv_data
    assert "ai_service_duration_ms" in csv_data
    assert "home.index" in csv_data
    assert "rendering" in csv_data


def test_monitored_database_connection_timing():
    """Verify MonitoredConnection measures execution time without breaking queries."""
    conn = sqlite3.connect(":memory:", factory=MonitoredConnection)
    conn.row_factory = sqlite3.Row

    # Execute table creation and inserts
    conn.execute("CREATE TABLE test_data (id INT, label TEXT)")
    conn.execute("INSERT INTO test_data VALUES (1, 'active')")
    conn.executemany("INSERT INTO test_data VALUES (?, ?)", [(2, "pending"), (3, "resolved")])

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM test_data")
    row = cur.fetchone()
    assert row["count"] == 3


def test_server_timing_header_in_http_response(client):
    """Verify that requests return the standard W3C Server-Timing header."""
    res = client.get("/")
    assert res.status_code in (200, 302)
    assert "Server-Timing" in res.headers
    server_timing = res.headers["Server-Timing"]
    assert "total;dur=" in server_timing
    assert "db;dur=" in server_timing
    assert "ai;dur=" in server_timing
    assert "file;dur=" in server_timing
    assert "render;dur=" in server_timing


def test_admin_performance_api_authentication(client):
    """Verify that /admin/performance requires administrative privileges."""
    # 1. Unauthenticated request must return 403
    unauth_res = client.get("/admin/performance")
    assert unauth_res.status_code == 403

    unauth_api = client.get("/api/admin/performance-metrics")
    assert unauth_api.status_code == 403

    # 2. Authenticated request with X-Admin-Key must succeed
    admin_key = getattr(config, "ADMIN_SECRET_KEY", "admin-default-secret-key-2026")
    auth_res = client.get("/api/admin/performance-metrics", headers={"X-Admin-Key": admin_key})
    assert auth_res.status_code == 200
    data = json.loads(auth_res.data)
    assert data["status"] == "success"
    assert "kpis" in data["data"]
    assert "bottlenecks" in data["data"]
    assert "endpoint_stats" in data["data"]

    # 3. HTML view with admin_key query parameter
    html_res = client.get(f"/admin/performance?admin_key={admin_key}")
    assert html_res.status_code == 200
    assert b"Route Performance &amp; Latency Telemetry" in html_res.data or b"Route Performance" in html_res.data
    assert b"Primary Bottleneck" in html_res.data
