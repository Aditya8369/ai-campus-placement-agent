import pytest
import uuid
from app import app
from utils.database import (
    get_db_connection,
    log_gemini_api_call,
    get_gemini_usage_summary,
    calculate_gemini_call_cost,
    COST_PER_PROMPT_TOKEN,
    COST_PER_CANDIDATE_TOKEN,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with app.app_context():
            yield client


def test_calculate_gemini_call_cost_formula():
    """Verify formula for calculating Gemini token cost in USD."""
    prompt_tokens = 1000
    candidate_tokens = 500
    expected_cost = round(
        (prompt_tokens * COST_PER_PROMPT_TOKEN) + (candidate_tokens * COST_PER_CANDIDATE_TOKEN),
        6,
    )
    actual_cost = calculate_gemini_call_cost(prompt_tokens, candidate_tokens)
    assert actual_cost == expected_cost
    assert calculate_gemini_call_cost(0, 0) == 0.0


def test_log_gemini_api_call_and_retrieve_summary():
    """Test inserting and aggregating Gemini API usage records in SQLite."""
    ep_name = f"test_endpoint_{uuid.uuid4().hex[:6]}"
    log_id_1 = log_gemini_api_call(
        endpoint=ep_name,
        model_name="gemini-2.5-flash",
        prompt_tokens=2000,
        candidate_tokens=1000,
        latency_ms=150,
        status="success",
    )
    assert log_id_1 != ""

    log_id_2 = log_gemini_api_call(
        endpoint=ep_name,
        model_name="gemini-2.5-flash",
        prompt_tokens=500,
        candidate_tokens=0,
        latency_ms=250,
        status="failed",
        error_message="Resource Exhausted: Quota exceeded",
    )
    assert log_id_2 != ""

    summary = get_gemini_usage_summary(days=1)
    assert summary["total_calls"] >= 2
    assert summary["successful_calls"] >= 1
    assert summary["failed_calls"] >= 1
    assert summary["total_prompt_tokens"] >= 2500
    assert summary["total_candidate_tokens"] >= 1000
    assert summary["total_cost_usd"] > 0.0

    # Verify endpoint breakdown contains our test endpoint
    matched_ep = next((ep for ep in summary["endpoint_breakdown"] if ep["endpoint"] == ep_name), None)
    assert matched_ep is not None
    assert matched_ep["call_count"] == 2
    assert matched_ep["endpoint_tokens"] == 3500


def test_admin_api_usage_dashboard_route(client):
    """Test GET /admin/api-usage renders HTML dashboard successfully."""
    # Seed a log entry first
    log_gemini_api_call(
        endpoint="test_render_endpoint",
        model_name="gemini-2.5-flash",
        prompt_tokens=1200,
        candidate_tokens=600,
        latency_ms=180,
        status="success",
    )

    response = client.get("/admin/api-usage?days=7")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Gemini API Usage & Cost Monitor" in html
    assert "Estimated Spend" in html
    assert "Tokens Consumed" in html
    assert "test_render_endpoint" in html


def test_api_admin_usage_stats_json_endpoint(client):
    """Test GET /api/admin/usage-stats returns structured JSON payload."""
    response = client.get("/api/admin/usage-stats?days=30")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "success"
    assert "data" in json_data
    stats = json_data["data"]
    assert "total_calls" in stats
    assert "total_cost_usd" in stats
    assert "success_rate_pct" in stats
    assert "endpoint_breakdown" in stats
    assert "recent_logs" in stats
