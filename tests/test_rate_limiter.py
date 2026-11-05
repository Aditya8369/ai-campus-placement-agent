"""
Comprehensive test suite for in-memory rate limiting and request throttling.

Tests verify:
- Sliding-window timestamp eviction and boundary enforcement
- Remaining quota calculation and reset timing
- API 429 response structure with Retry-After and rate limit headers
- Non-API form submission redirect with flash messaging
- Client IP resolution from remote_addr and X-Forwarded-For reverse proxy headers
"""

import pytest
import time
from utils.rate_limiter import InMemoryRateLimiter, limiter
from app import app


@pytest.fixture(autouse=True)
def reset_limiter():
    """Ensure clean limiter state for every test."""
    limiter.reset()
    yield
    limiter.reset()


def test_in_memory_rate_limiter_allows_up_to_max():
    """Verify limiter allows exactly max_requests within window and throttles subsequent."""
    test_limiter = InMemoryRateLimiter()
    key = "test_user_ip_1"

    # Permitted calls within quota
    for i in range(5):
        allowed, remaining, reset_secs = test_limiter.is_allowed(key, max_requests=5, window_seconds=10)
        assert allowed is True
        assert remaining == 5 - (i + 1)
        assert reset_secs <= 10.0

    # 6th call should be blocked
    allowed, remaining, reset_secs = test_limiter.is_allowed(key, max_requests=5, window_seconds=10)
    assert allowed is False
    assert remaining == 0
    assert reset_secs > 0


def test_in_memory_rate_limiter_evicts_expired_timestamps():
    """Verify timestamps older than the sliding window are cleanly pruned."""
    test_limiter = InMemoryRateLimiter()
    key = "test_user_ip_sliding"

    # Fill up with window of 1 second
    for _ in range(3):
        allowed, _, _ = test_limiter.is_allowed(key, max_requests=3, window_seconds=1)
        assert allowed is True

    # Immediate next should fail
    allowed, _, _ = test_limiter.is_allowed(key, max_requests=3, window_seconds=1)
    assert allowed is False

    # Wait for window to expire
    time.sleep(1.1)

    # Now request should be allowed again
    allowed, remaining, _ = test_limiter.is_allowed(key, max_requests=3, window_seconds=1)
    assert allowed is True
    assert remaining == 2


def test_client_ip_resolution_with_forwarded_headers():
    """Verify rate limiter inspects X-Forwarded-For headers to identify genuine clients."""
    with app.test_request_context(
        "/",
        headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
    ):
        ip = limiter.get_client_ip()
        assert ip == "203.0.113.195"

    with app.test_request_context("/", headers={"X-Real-IP": "198.51.100.42"}):
        ip = limiter.get_client_ip()
        assert ip == "198.51.100.42"


def test_api_endpoint_throttling_returns_429():
    """Verify POST /interview/<aid>/submit returns HTTP 429 when throttled with Retry-After header."""
    app.config["TESTING"] = True
    aid = "test_rate_limit_aid"

    with app.test_client() as client:
        # Submit 30 allowed requests
        for _ in range(30):
            res = client.post(
                f"/interview/{aid}/submit",
                json={"user_answer": "test answer"},
                headers={"X-Forwarded-For": "192.0.2.1"}
            )
            # Route logic might return 404/500 if session doesn't exist, but won't be 429 yet
            assert res.status_code != 429

        # 31st request triggers rate limit 429
        throttled_res = client.post(
            f"/interview/{aid}/submit",
            json={"user_answer": "test answer"},
            headers={"X-Forwarded-For": "192.0.2.1"}
        )
        assert throttled_res.status_code == 429
        json_data = throttled_res.get_json()
        assert json_data["success"] is False
        assert "Too Many Requests" in json_data["error"]
        assert "retry_after_hint" in json_data
        assert "try again in" in json_data["retry_after_hint"]
        assert "Retry-After" in throttled_res.headers
        assert "X-RateLimit-Limit" in throttled_res.headers
        assert throttled_res.headers["X-RateLimit-Remaining"] == "0"


def test_parse_rate_limit_formats():
    """Verify parse_rate_limit correctly parses various limit expressions."""
    from utils.rate_limiter import parse_rate_limit

    assert parse_rate_limit("5/hour") == (5, 3600)
    assert parse_rate_limit("30/hour") == (30, 3600)
    assert parse_rate_limit("100/minute") == (100, 60)
    assert parse_rate_limit("10/day") == (10, 86400)
    assert parse_rate_limit("5/second") == (5, 1)
    assert parse_rate_limit("15/min") == (15, 60)
    assert parse_rate_limit("2/hr") == (2, 3600)
    assert parse_rate_limit((10, 120)) == (10, 120)
    assert parse_rate_limit([8, 300]) == (8, 300)
    assert parse_rate_limit(25) == (25, 60)
    # Fallback default
    assert parse_rate_limit(None) == (60, 60)


def test_format_time_hint():
    """Verify format_time_hint generates clean human-readable hints."""
    from utils.rate_limiter import format_time_hint

    assert format_time_hint(1) == "try again in 1 second"
    assert format_time_hint(45) == "try again in 45 seconds"
    assert format_time_hint(60) == "try again in 1 minute"
    assert format_time_hint(125) == "try again in 2 minutes"
    assert format_time_hint(3550) == "try again in 59 minutes"


def test_get_limit_for_scope_dynamic_config():
    """Verify limits can be retrieved and adjusted centrally without route code changes (#160)."""
    import os
    import config
    from utils.rate_limiter import get_limit_for_scope

    # Baseline limits defined in config.py
    analyze_limit = get_limit_for_scope("analyze")
    assert analyze_limit == (5, 3600)

    interview_limit = get_limit_for_scope("interview_eval")
    assert interview_limit == (30, 3600)

    # Dynamic modification in config.RATE_LIMITS dict without modifying routes
    original_analyze = config.RATE_LIMITS.get("analyze")
    try:
        config.RATE_LIMITS["analyze"] = "12/hour"
        assert get_limit_for_scope("analyze") == (12, 3600)
    finally:
        config.RATE_LIMITS["analyze"] = original_analyze

    # Environment variable override
    try:
        os.environ["RATE_LIMIT_ANALYZE"] = "7/minute"
        assert get_limit_for_scope("analyze") == (7, 60)
    finally:
        del os.environ["RATE_LIMIT_ANALYZE"]


def test_ui_request_throttling_returns_429_html():
    """Verify UI requests exceeding rate limit receive HTTP status 429 and render friendly 429 page."""
    import config

    app.config["TESTING"] = True
    test_ip = "198.51.100.99"

    # Temporarily set analyze limit to 2/hour for quick test
    original_limit = config.RATE_LIMITS.get("analyze_submission")
    config.RATE_LIMITS["analyze_submission"] = "2/hour"

    try:
        with app.test_client() as client:
            # First 2 requests should reach route logic (validation failure returns 302/redirect, but NOT 429)
            res1 = client.post("/analyze", data={}, headers={"X-Forwarded-For": test_ip})
            assert res1.status_code != 429

            res2 = client.post("/analyze", data={}, headers={"X-Forwarded-For": test_ip})
            assert res2.status_code != 429

            # 3rd request exceeds limit -> returns 429 with HTML page
            res3 = client.post("/analyze", data={}, headers={"X-Forwarded-For": test_ip})
            assert res3.status_code == 429
            html_text = res3.get_data(as_text=True)
            assert "Rate Limit Exceeded" in html_text
            assert "429" in html_text
            assert "try again in" in html_text
            assert "Retry-After" in res3.headers
    finally:
        config.RATE_LIMITS["analyze_submission"] = original_limit


def test_rate_limiting_can_be_disabled():
    """Verify that setting RATE_LIMIT_ENABLED to false bypasses throttling."""
    import os
    import config

    app.config["TESTING"] = True
    test_ip = "203.0.113.88"
    original_flag = getattr(config, "RATE_LIMIT_ENABLED", True)

    try:
        os.environ["RATE_LIMIT_ENABLED"] = "false"
        config.RATE_LIMIT_ENABLED = False

        with app.test_client() as client:
            # Send 40 requests without being blocked
            for _ in range(40):
                res = client.post(
                    "/interview/test_aid/submit",
                    json={"user_answer": "test"},
                    headers={"X-Forwarded-For": test_ip}
                )
                assert res.status_code != 429
    finally:
        if "RATE_LIMIT_ENABLED" in os.environ:
            del os.environ["RATE_LIMIT_ENABLED"]
        config.RATE_LIMIT_ENABLED = original_flag
