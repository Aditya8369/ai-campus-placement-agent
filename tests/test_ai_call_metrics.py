"""
tests/test_ai_call_metrics.py
Comprehensive unit test suite for AI call telemetry, aggregation,
empty database handling, and admin authorization (#434).

Verifies all Acceptance Criteria:
1. Each AI call writes one metrics row without storing user content.
2. Only admins can open the page and the CSV.
3. Charts and tables handle an empty database gracefully.
4. Tests cover recording, aggregation, and permission checks.
"""

import io
import csv
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app import app
from utils.database import get_db_connection, init_db
from utils.ai_metrics import (
    init_ai_metrics_table,
    record_ai_call_metric,
    calculate_p95,
    get_ai_metrics_summary,
    export_ai_metrics_csv,
    set_current_ai_feature,
    get_current_ai_feature,
)
import config


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Sets up a clean, isolated SQLite test database for metrics testing."""
    db_file = tmp_path / "test_ai_metrics.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    init_db()
    init_ai_metrics_table()
    yield db_file


@pytest.fixture
def client(test_db):
    """Configures the Flask test client with login enforcement enabled."""
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. Telemetry Recording Without User Content (Acceptance Criteria 1)
# ==============================================================================

def test_record_ai_call_metric_writes_row_without_user_content(test_db):
    """Each AI call writes one telemetry row without storing prompts or resume text."""
    metric_id = record_ai_call_metric(
        feature="analysis",
        model="gemini-2.5-flash",
        latency_ms=350.5,
        token_count=210,
        prompt_tokens=150,
        candidate_tokens=60,
        success=True,
    )
    assert metric_id is not None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_call_metrics WHERE id = ?", (metric_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["feature"] == "analysis"
        assert row["model"] == "gemini-2.5-flash"
        assert row["latency_ms"] == 350.5
        assert row["token_count"] == 210
        assert row["prompt_tokens"] == 150
        assert row["candidate_tokens"] == 60
        assert row["success"] == 1
        assert row["error_type"] is None

        # Verify strict table schema: NO prompt, resume, candidate text, or response columns
        cursor.execute("PRAGMA table_info(ai_call_metrics)")
        columns = [col[1].lower() for col in cursor.fetchall()]
        forbidden_fields = {"prompt", "resume", "resume_text", "user_prompt", "content", "response_text", "email", "phone"}
        for f in forbidden_fields:
            assert f not in columns, f"Forbidden field '{f}' detected in ai_call_metrics schema"
    finally:
        conn.close()


def test_record_ai_call_metric_failure_with_error_classification(test_db):
    """Failed AI calls record error type without storing confidential text."""
    metric_id = record_ai_call_metric(
        feature="interview",
        model="gemini-2.5-flash",
        latency_ms=1250.0,
        token_count=100,
        prompt_tokens=100,
        candidate_tokens=0,
        success=False,
        error_type="AIRateLimitError",
    )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_call_metrics WHERE id = ?", (metric_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["feature"] == "interview"
        assert row["success"] == 0
        assert row["error_type"] == "AIRateLimitError"
        assert row["candidate_tokens"] == 0
    finally:
        conn.close()


def test_gemini_generate_json_response_records_metric_on_success(test_db):
    """generate_json_response logs successful invocations into ai_call_metrics."""
    from utils.gemini import generate_json_response

    mock_response = MagicMock()
    mock_response.text = '{"status": "ready", "score": 85}'
    mock_response.usage_metadata.prompt_token_count = 120
    mock_response.usage_metadata.candidates_token_count = 45
    mock_response.usage_metadata.total_token_count = 165

    with patch("utils.gemini.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        res = generate_json_response(
            system_instruction="Analyze technical resume",
            prompt="Dummy candidate content without sensitive details",
            feature="outreach"
        )
        assert res == {"status": "ready", "score": 85}

    summary = get_ai_metrics_summary()
    assert summary["total_calls"] == 1
    assert summary["successful_calls"] == 1
    assert summary["failed_calls"] == 0
    assert summary["recent_calls"][0]["feature"] == "outreach"
    assert summary["recent_calls"][0]["token_count"] == 165


def test_gemini_generate_json_response_records_metric_on_failure(test_db):
    """generate_json_response logs failures and error types into ai_call_metrics."""
    from utils.gemini import generate_json_response, AIRateLimitError
    from google.genai.errors import APIError

    with patch("utils.gemini.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        err = APIError(429, "Resource exhausted: quota exceeded")
        mock_client.models.generate_content.side_effect = err
        mock_get_client.return_value = mock_client

        with pytest.raises(AIRateLimitError):
            generate_json_response(
                system_instruction="Mock Interview System",
                prompt="Interview answer assessment",
                max_retries=0,
                feature="interview"
            )

    summary = get_ai_metrics_summary()
    assert summary["total_calls"] == 1
    assert summary["successful_calls"] == 0
    assert summary["failed_calls"] == 1
    assert summary["failure_rate_pct"] == 100.0
    assert summary["recent_calls"][0]["feature"] == "interview"
    assert summary["recent_calls"][0]["error_type"] == "AIRateLimitError"


def test_contextual_feature_tracking():
    """Verify thread-safe context variable correctly tags downstream calls."""
    assert get_current_ai_feature() is None
    token = set_current_ai_feature("interview")
    assert get_current_ai_feature() == "interview"
    set_current_ai_feature(None)
    assert get_current_ai_feature() is None


# ==============================================================================
# 2. Latency P95 & Statistics Aggregation (Acceptance Criteria 4)
# ==============================================================================

def test_calculate_p95_algorithm():
    """Validates 95th percentile latency calculations across various input sizes."""
    # Empty
    assert calculate_p95([]) == 0.0

    # Single
    assert calculate_p95([120.0]) == 120.0

    # 100 uniform items: 10, 20, 30 ... 1000
    hundred_lats = [float(i * 10) for i in range(1, 101)]
    p95 = calculate_p95(hundred_lats)
    # 95th percentile of 10..1000 is ~950.5 or 950.0
    assert 940.0 <= p95 <= 960.0


def test_get_ai_metrics_summary_aggregation(test_db):
    """Validates multi-day aggregation, p95 latency, failure rate, and error grouping."""
    # Day 1: 3 calls (2 success, 1 failure)
    record_ai_call_metric("analysis", latency_ms=100.0, token_count=50, success=True, timestamp="2026-11-10 10:00:00")
    record_ai_call_metric("analysis", latency_ms=200.0, token_count=60, success=True, timestamp="2026-11-10 11:00:00")
    record_ai_call_metric("interview", latency_ms=500.0, token_count=30, success=False, error_type="AIRateLimitError", timestamp="2026-11-10 12:00:00")

    # Day 2: 2 calls (1 success, 1 failure)
    record_ai_call_metric("outreach", latency_ms=300.0, token_count=70, success=True, timestamp="2026-11-11 09:00:00")
    record_ai_call_metric("interview", latency_ms=900.0, token_count=40, success=False, error_type="AINetworkError", timestamp="2026-11-11 14:00:00")

    # Day 3: 1 call (failure with duplicate error type to test counts)
    record_ai_call_metric("analysis", latency_ms=1000.0, token_count=50, success=False, error_type="AIRateLimitError", timestamp="2026-11-12 16:00:00")

    summary = get_ai_metrics_summary()
    assert summary["total_calls"] == 6
    assert summary["successful_calls"] == 3
    assert summary["failed_calls"] == 3
    assert summary["failure_rate_pct"] == 50.0
    assert summary["avg_latency_ms"] == round((100 + 200 + 500 + 300 + 900 + 1000) / 6, 2)
    assert summary["p95_latency_ms"] >= 900.0

    # Verify daily breakdown
    assert len(summary["daily_metrics"]) == 3
    dates = [d["date"] for d in summary["daily_metrics"]]
    assert "2026-11-10" in dates
    assert "2026-11-11" in dates
    assert "2026-11-12" in dates

    # Verify error types ranking: AIRateLimitError (2) > AINetworkError (1)
    errs = summary["common_errors"]
    assert len(errs) == 2
    assert errs[0]["error_type"] == "AIRateLimitError"
    assert errs[0]["count"] == 2
    assert errs[0]["percentage_of_errors"] == 66.7
    assert errs[1]["error_type"] == "AINetworkError"
    assert errs[1]["count"] == 1


def test_date_range_and_feature_filters(test_db):
    """Validates date range filtering and feature filtering."""
    record_ai_call_metric("analysis", latency_ms=100.0, timestamp="2026-11-01 10:00:00")
    record_ai_call_metric("interview", latency_ms=200.0, timestamp="2026-11-05 10:00:00")
    record_ai_call_metric("outreach", latency_ms=300.0, timestamp="2026-11-10 10:00:00")

    # Filter date range: Nov 4 to Nov 8 (only interview should be returned)
    filtered_date = get_ai_metrics_summary(start_date="2026-11-04", end_date="2026-11-08")
    assert filtered_date["total_calls"] == 1
    assert filtered_date["recent_calls"][0]["feature"] == "interview"

    # Filter by feature: analysis only
    filtered_feat = get_ai_metrics_summary(feature="analysis")
    assert filtered_feat["total_calls"] == 1
    assert filtered_feat["recent_calls"][0]["feature"] == "analysis"


# ==============================================================================
# 3. Handling Empty Database Gracefully (Acceptance Criteria 3)
# ==============================================================================

def test_empty_database_summary_handling(test_db):
    """Charts and tables handle an empty database without division by zero or crashing."""
    summary = get_ai_metrics_summary()
    assert summary["total_calls"] == 0
    assert summary["successful_calls"] == 0
    assert summary["failed_calls"] == 0
    assert summary["failure_rate_pct"] == 0.0
    assert summary["avg_latency_ms"] == 0.0
    assert summary["p95_latency_ms"] == 0.0
    assert summary["total_tokens"] == 0
    assert summary["daily_metrics"] == []
    assert summary["common_errors"] == []
    assert summary["feature_breakdown"] == []
    assert summary["recent_calls"] == []


def test_empty_database_csv_export(test_db):
    """CSV export returns clean headers when no telemetry records exist."""
    csv_text = export_ai_metrics_csv()
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 1  # Only header
    assert rows[0] == [
        "id", "timestamp", "feature", "model", "latency_ms",
        "token_count", "prompt_tokens", "candidate_tokens", "success", "error_type"
    ]


def test_admin_page_renders_with_empty_database(client):
    """Admin page renders clean empty banners and zeroed KPIs when database is empty."""
    with client.session_transaction() as sess:
        sess["user_id"] = "admin_user"
        sess["is_admin"] = True

    res = client.get("/admin/ai-metrics")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert "emptyMetricsChartBanner" in html
    assert "No AI calls recorded yet" in html
    assert "Zero AI Errors" in html
    assert "No AI telemetry records found" in html
    assert "0%" in html  # Failure rate


# ==============================================================================
# 4. Admin-Only Permission Checks (Acceptance Criteria 2)
# ==============================================================================

def test_admin_metrics_denied_for_unauthenticated_and_regular_students(client):
    """Only admins can open the page and CSV; regular students receive 403 Forbidden."""
    # 1. Unauthenticated visitor
    res_page = client.get("/admin/ai-metrics")
    assert res_page.status_code == 403
    assert "Unauthorized" in res_page.get_json()["error"]

    res_csv = client.get("/admin/ai-metrics/export.csv")
    assert res_csv.status_code == 403
    assert "Unauthorized" in res_csv.get_json()["error"]

    # 2. Regular logged-in student (non-admin)
    with client.session_transaction() as sess:
        sess["user_id"] = "student_alice"
        sess["is_admin"] = False
        sess["user"] = {"role": "student"}

    res_stud_page = client.get("/admin/ai-metrics")
    assert res_stud_page.status_code == 403
    assert "Unauthorized" in res_stud_page.get_json()["error"]

    res_stud_csv = client.get("/admin/ai-metrics/export.csv")
    assert res_stud_csv.status_code == 403
    assert "Unauthorized" in res_stud_csv.get_json()["error"]


def test_admin_metrics_allowed_via_admin_session(client, test_db):
    """Administrator with is_admin session flag can open page and download CSV."""
    record_ai_call_metric("analysis", latency_ms=250.0, success=True)

    with client.session_transaction() as sess:
        sess["user_id"] = "admin_alice"
        sess["is_admin"] = True

    # 1. Page view
    res_page = client.get("/admin/ai-metrics")
    assert res_page.status_code == 200
    html = res_page.data.decode("utf-8")
    assert "AI Usage, Latency & Error Telemetry" in html
    assert "btnExportAiMetricsCsv" in html
    assert "250.0" in html or "250" in html

    # 2. CSV export
    res_csv = client.get("/admin/ai-metrics/export.csv")
    assert res_csv.status_code == 200
    assert res_csv.mimetype == "text/csv"
    assert "attachment; filename=ai_call_metrics.csv" in res_csv.headers.get("Content-Disposition", "")
    csv_text = res_csv.data.decode("utf-8")
    assert "analysis" in csv_text
    assert "250" in csv_text


def test_admin_metrics_allowed_via_api_key_header_and_query_param(client, test_db):
    """Admin access granted via X-Admin-Key header or admin_key query parameter."""
    configured_key = getattr(config, "ADMIN_SECRET_KEY", "admin-default-secret-key-2026")

    # 1. Via X-Admin-Key header
    res_header = client.get("/admin/ai-metrics", headers={"X-Admin-Key": configured_key})
    assert res_header.status_code == 200

    res_csv_header = client.get("/admin/ai-metrics/export.csv", headers={"X-Admin-Key": configured_key})
    assert res_csv_header.status_code == 200

    # 2. Via admin_key query parameter
    res_param = client.get(f"/admin/ai-metrics?admin_key={configured_key}")
    assert res_param.status_code == 200

    res_csv_param = client.get(f"/admin/ai-metrics/export.csv?admin_key={configured_key}")
    assert res_csv_param.status_code == 200


def test_api_admin_ai_metrics_endpoint(client, test_db):
    """Validates the admin JSON API endpoint."""
    record_ai_call_metric("interview", latency_ms=450.0, token_count=180, success=True)

    with client.session_transaction() as sess:
        sess["user_id"] = "admin_user"
        sess["is_admin"] = True

    res = client.get("/api/admin/ai-metrics")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["data"]["total_calls"] == 1
    assert data["data"]["successful_calls"] == 1
    assert data["data"]["avg_latency_ms"] == 450.0
