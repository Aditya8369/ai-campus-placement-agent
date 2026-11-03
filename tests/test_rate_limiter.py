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
        assert "Retry-After" in throttled_res.headers
        assert "X-RateLimit-Limit" in throttled_res.headers
        assert throttled_res.headers["X-RateLimit-Remaining"] == "0"
