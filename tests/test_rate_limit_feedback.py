"""
Unit and integration tests for rate limit feedback, retry headers, countdown data,
and usage indicators (#652).
"""

import time
import pytest
from app import app
from utils.rate_limiter import InMemoryRateLimiter, limiter, get_rate_limit_status
from utils.i18n import get_translation


@pytest.fixture(autouse=True)
def clean_limiter():
    """Ensure in-memory rate limiter state is reset between tests."""
    limiter.reset()
    yield
    limiter.reset()


def test_in_memory_rate_limiter_get_remaining_non_mutating():
    """Verify get_remaining inspects usage without consuming quota."""
    lim = InMemoryRateLimiter()
    key = "student_test_ip"

    # Initially, remaining equals max limit
    rem, limit, reset_secs = lim.get_remaining(key, max_requests=5, window_seconds=60)
    assert rem == 5
    assert limit == 5
    assert reset_secs == 0.0

    # Repeating get_remaining does not decrease quota
    rem2, _, _ = lim.get_remaining(key, max_requests=5, window_seconds=60)
    assert rem2 == 5

    # Consume 2 requests
    allowed1, remaining1, _ = lim.is_allowed(key, max_requests=5, window_seconds=60)
    assert allowed1 is True
    assert remaining1 == 4

    allowed2, remaining2, _ = lim.is_allowed(key, max_requests=5, window_seconds=60)
    assert allowed2 is True
    assert remaining2 == 3

    # Inspect via get_remaining
    rem_after, limit_after, reset_after = lim.get_remaining(key, max_requests=5, window_seconds=60)
    assert rem_after == 3
    assert limit_after == 5
    assert reset_after > 0.0


def test_get_rate_limit_status_returns_scope_counters():
    """Verify get_rate_limit_status returns accurate dictionary counters for a scope."""
    test_ip = "198.51.100.123"
    status_initial = get_rate_limit_status("analyze", client_ip=test_ip)
    assert status_initial["scope"] == "analyze"
    assert status_initial["limit"] == 5
    assert status_initial["remaining"] == 5
    assert status_initial["reset_seconds"] == 0

    # Consume an analyze quota slot for that IP
    limiter.is_allowed(f"analyze:{test_ip}", max_requests=5, window_seconds=3600)

    status_after = get_rate_limit_status("analyze", client_ip=test_ip)
    assert status_after["remaining"] == 4
    assert status_after["limit"] == 5
    assert status_after["reset_seconds"] > 0


def test_successful_request_returns_rate_limit_headers():
    """Verify allowed requests return X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset."""
    app.config["TESTING"] = True
    test_ip = "203.0.113.55"

    with app.test_client() as client:
        res = client.post(
            "/interview/test_aid/submit",
            json={"user_answer": "STAR formatted answer with sufficient length"},
            headers={"X-Forwarded-For": test_ip},
        )
        assert res.status_code != 429
        assert "X-RateLimit-Limit" in res.headers
        assert "X-RateLimit-Remaining" in res.headers
        assert "X-RateLimit-Reset" in res.headers
        # Interview limit is 30 by default; after 1 request, remaining is 29
        assert res.headers["X-RateLimit-Remaining"] == "29"
        assert res.headers["X-RateLimit-Limit"] == "30"


def test_rate_limited_429_returns_retry_headers_and_body():
    """Verify throttled requests return Retry-After, X-RateLimit-Remaining: 0, and JSON retry_after."""
    app.config["TESTING"] = True
    test_ip = "192.0.2.77"
    aid = "rate_limit_feedback_aid"

    with app.test_client() as client:
        # Exhaust 30 interview requests
        for _ in range(30):
            res = client.post(
                f"/interview/{aid}/submit",
                json={"user_answer": "answer"},
                headers={"X-Forwarded-For": test_ip},
            )
            assert res.status_code != 429

        # 31st request triggers 429 Too Many Requests
        throttled = client.post(
            f"/interview/{aid}/submit",
            json={"user_answer": "answer"},
            headers={"X-Forwarded-For": test_ip},
        )
        assert throttled.status_code == 429
        assert "Retry-After" in throttled.headers
        assert throttled.headers["X-RateLimit-Remaining"] == "0"
        assert throttled.headers["X-RateLimit-Limit"] == "30"
        assert "X-RateLimit-Reset" in throttled.headers

        retry_after_header = int(throttled.headers["Retry-After"])
        assert retry_after_header > 0

        data = throttled.get_json()
        assert data["success"] is False
        assert data["error"] == "Too Many Requests"
        assert "retry_after" in data
        assert isinstance(data["retry_after"], int)
        assert data["retry_after"] == retry_after_header
        assert "retry_after_seconds" in data
        assert data["remaining"] == 0
        assert "try again in" in data.get("retry_after_hint", "")


def test_api_rate_limit_status_endpoint():
    """Verify /api/rate-limit/status returns live counter and rate limit headers."""
    app.config["TESTING"] = True
    test_ip = "198.51.100.200"

    with app.test_client() as client:
        # Initial check
        res = client.get(
            "/api/rate-limit/status?scope=analyze",
            headers={"X-Forwarded-For": test_ip},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["scope"] == "analyze"
        assert data["remaining"] == 5
        assert data["limit"] == 5
        assert res.headers["X-RateLimit-Remaining"] == "5"

        # Simulate 1 analysis request consumed
        limiter.is_allowed(f"analyze:{test_ip}", max_requests=5, window_seconds=3600)

        # Subsequent status check
        res_after = client.get(
            "/api/rate-limit/status?scope=analyze",
            headers={"X-Forwarded-For": test_ip},
        )
        assert res_after.status_code == 200
        data_after = res_after.get_json()
        assert data_after["remaining"] == 4
        assert res_after.headers["X-RateLimit-Remaining"] == "4"


def test_ui_429_html_response_headers_and_elements():
    """Verify non-API rate limited submission returns 429 with Retry-After and countdown elements."""
    import config

    app.config["TESTING"] = True
    test_ip = "203.0.113.199"

    original_limit = config.RATE_LIMITS.get("analyze_submission")
    config.RATE_LIMITS["analyze_submission"] = "1/hour"

    try:
        with app.test_client() as client:
            # First request
            r1 = client.post("/analyze", data={}, headers={"X-Forwarded-For": test_ip})
            assert r1.status_code != 429
            assert r1.headers.get("X-RateLimit-Remaining") == "0"

            # Second request exceeds limit
            r2 = client.post("/analyze", data={}, headers={"X-Forwarded-For": test_ip})
            assert r2.status_code == 429
            assert "Retry-After" in r2.headers
            assert r2.headers.get("X-RateLimit-Remaining") == "0"
            assert "X-RateLimit-Limit" in r2.headers

            html = r2.get_data(as_text=True)
            assert "Rate Limit Exceeded" in html
            assert "retryHintDisplay" in html
            assert "aria-live=" in html
    finally:
        config.RATE_LIMITS["analyze_submission"] = original_limit


def test_i18n_translation_with_format_kwargs():
    """Verify get_translation supports parameter interpolation across locales."""
    en_text = get_translation("rate_limit_try_again", locale="en", time="2:35")
    assert en_text == "You can try again in 2:35"

    hi_text = get_translation("rate_limit_try_again", locale="hi", time="2:35")
    assert "2:35" in hi_text

    es_text = get_translation("rate_limit_try_again", locale="es", time="2:35")
    assert "2:35" in es_text
    assert "Puedes volver a intentarlo" in es_text
