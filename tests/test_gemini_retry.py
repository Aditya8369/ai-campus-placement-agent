"""
Tests for Gemini API retry with exponential backoff and jitter on transient errors (Issue #155).

Verifies:
1. Automatic retries on transient errors (HTTP 429, 500, 503, network timeouts).
2. Fast failure without retries on permanent errors (HTTP 400, 401, 403).
3. Exponential backoff delay calculation and jitter behavior.
4. User-friendly messages when retries are exhausted (no raw tracebacks).
5. Configurable retry attempts, delays, and factor via config/parameters.
"""

import socket
import pytest
from google.genai.errors import APIError

import config
from utils.gemini import (
    calculate_backoff_delay,
    classify_gemini_error,
    format_ai_error_for_user,
    generate_json_response,
    AIAnalysisError,
    AIRateLimitError,
    AIServiceUnavailableError,
    AINetworkError,
    AIAuthError,
    AIBadRequestError,
    AIResponseFormatError,
)


class MockGenaiClient:
    """Mock Gemini client with configurable responses or sequential side-effects."""
    def __init__(self, responses_or_exceptions):
        self.queue = list(responses_or_exceptions)
        self.call_count = 0
        self.models = self

    def generate_content(self, model=None, contents=None, config=None):
        self.call_count += 1
        if not self.queue:
            raise RuntimeError("MockGenaiClient: No more responses queued")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, type) and issubclass(item, Exception):
            raise item()
        
        class MockResponse:
            def __init__(self, text):
                self.text = text
        return MockResponse(item)


# ============================================================================
# 1. Backoff & Jitter Calculation Tests
# ============================================================================

def test_calculate_backoff_delay_exponential_scaling_without_jitter():
    """Verify exponential delay increases as initial_delay * factor^(attempt - 1)."""
    # initial=1.0, factor=2.0 -> 1s, 2s, 4s, 8s
    d1 = calculate_backoff_delay(attempt=1, initial_delay=1.0, backoff_factor=2.0, max_delay=10.0, use_jitter=False)
    assert d1 == pytest.approx(1.0, rel=1e-3)

    d2 = calculate_backoff_delay(attempt=2, initial_delay=1.0, backoff_factor=2.0, max_delay=10.0, use_jitter=False)
    assert d2 == pytest.approx(2.0, rel=1e-3)

    d3 = calculate_backoff_delay(attempt=3, initial_delay=1.0, backoff_factor=2.0, max_delay=10.0, use_jitter=False)
    assert d3 == pytest.approx(4.0, rel=1e-3)

    d4 = calculate_backoff_delay(attempt=4, initial_delay=1.0, backoff_factor=2.0, max_delay=10.0, use_jitter=False)
    assert d4 == pytest.approx(8.0, rel=1e-3)


def test_calculate_backoff_delay_capped_at_max_delay():
    """Verify that delays do not exceed the configured maximum delay cap."""
    d = calculate_backoff_delay(attempt=10, initial_delay=1.0, backoff_factor=2.0, max_delay=5.0, use_jitter=False)
    assert d == pytest.approx(5.0, rel=1e-3)


def test_calculate_backoff_delay_jitter_stays_within_bounds():
    """Verify jitter adds a bounded random delta >= base_delay and <= base_delay + jitter_cap."""
    for _ in range(25):
        d = calculate_backoff_delay(attempt=2, initial_delay=2.0, backoff_factor=2.0, max_delay=20.0, use_jitter=True)
        # Base delay = 2.0 * 2^1 = 4.0. Jitter cap = min(1.0, 4.0 * 0.25) = 1.0.
        # Range should be between 4.0 and 5.0.
        assert 4.0 <= d <= 5.05


# ============================================================================
# 2. Error Classification Tests
# ============================================================================

def test_classify_gemini_error_transient_types():
    """Verify rate limits (429), server errors (500, 503), and socket timeouts are classified as retryable."""
    err_429 = APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None)
    classified_429 = classify_gemini_error(err_429)
    assert isinstance(classified_429, AIRateLimitError)
    assert classified_429.retryable is True

    err_503 = APIError(code=503, response_json={"error": {"message": "The service is overloaded"}}, response=None)
    classified_503 = classify_gemini_error(err_503)
    assert isinstance(classified_503, AIServiceUnavailableError)
    assert classified_503.retryable is True

    err_500 = APIError(code=500, response_json={"error": {"message": "Internal error"}}, response=None)
    classified_500 = classify_gemini_error(err_500)
    assert isinstance(classified_500, AIServiceUnavailableError)
    assert classified_500.retryable is True

    err_timeout = socket.timeout("Read timed out")
    classified_timeout = classify_gemini_error(err_timeout)
    assert isinstance(classified_timeout, AINetworkError)
    assert classified_timeout.retryable is True


def test_classify_gemini_error_permanent_types():
    """Verify auth errors (401, 403) and bad requests (400) are classified as non-retryable."""
    err_401 = APIError(code=401, response_json={"error": {"message": "API key not valid"}}, response=None)
    classified_401 = classify_gemini_error(err_401)
    assert isinstance(classified_401, AIAuthError)
    assert classified_401.retryable is False

    err_403 = APIError(code=403, response_json={"error": {"message": "Permission denied"}}, response=None)
    classified_403 = classify_gemini_error(err_403)
    assert isinstance(classified_403, AIAuthError)
    assert classified_403.retryable is False

    err_400 = APIError(code=400, response_json={"error": {"message": "Invalid argument supplied"}}, response=None)
    classified_400 = classify_gemini_error(err_400)
    assert isinstance(classified_400, AIBadRequestError)
    assert classified_400.retryable is False


# ============================================================================
# 3. Retry Loop Execution Tests (Mocked Client)
# ============================================================================

def test_retry_transient_429_recovers_on_second_attempt(monkeypatch):
    """Verify that a 429 rate limit triggers exponential backoff and succeeds on the 2nd attempt."""
    mock_client = MockGenaiClient([
        APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None),
        '{"status": "success", "ats_score": 85}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        jitter=False,
        _sleep_fn=lambda s: sleep_history.append(s),
    )

    assert result == {"status": "success", "ats_score": 85}
    assert mock_client.call_count == 2
    assert len(sleep_history) == 1
    assert sleep_history[0] == pytest.approx(1.0)


def test_retry_transient_503_recovers_on_third_attempt(monkeypatch):
    """Verify that two consecutive 503 errors back off exponentially (1s, 2s) and succeed on 3rd attempt."""
    mock_client = MockGenaiClient([
        APIError(code=503, response_json={"error": {"message": "Service unavailable"}}, response=None),
        APIError(code=503, response_json={"error": {"message": "Model overloaded"}}, response=None),
        '{"placement_ready": true}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        jitter=False,
        _sleep_fn=lambda s: sleep_history.append(s),
    )

    assert result == {"placement_ready": True}
    assert mock_client.call_count == 3
    assert len(sleep_history) == 2
    assert sleep_history[0] == pytest.approx(1.0)
    assert sleep_history[1] == pytest.approx(2.0)


def test_retry_transient_socket_timeout_recovers(monkeypatch):
    """Verify that network/socket timeouts trigger a retry and succeed when connectivity resumes."""
    mock_client = MockGenaiClient([
        socket.timeout("Socket read timed out"),
        '{"result": "network recovered"}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        max_retries=2,
        initial_delay=0.5,
        jitter=False,
        _sleep_fn=lambda s: sleep_history.append(s),
    )

    assert result == {"result": "network recovered"}
    assert mock_client.call_count == 2
    assert len(sleep_history) == 1
    assert sleep_history[0] == pytest.approx(0.5)


def test_repeated_transient_failures_exhausts_retries_and_raises_friendly_error(monkeypatch):
    """Verify that after exhausting all retries, a friendly error is raised without exposing raw tracebacks."""
    mock_client = MockGenaiClient([
        APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None),
        APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None),
        APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None),
        APIError(code=429, response_json={"error": {"message": "Resource exhausted"}}, response=None),
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    with pytest.raises(AIRateLimitError) as excinfo:
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=3,  # 1 initial + 3 retries = 4 total calls
            initial_delay=1.0,
            backoff_factor=2.0,
            jitter=False,
            _sleep_fn=lambda s: sleep_history.append(s),
        )

    assert mock_client.call_count == 4
    assert len(sleep_history) == 3
    assert sleep_history == [1.0, 2.0, 4.0]
    
    # User friendly message must contain the friendly guidance
    err = excinfo.value
    assert "The AI service is busy, please try again in a minute" in err.user_friendly_message
    assert "Traceback" not in err.user_friendly_message


def test_permanent_auth_error_fails_fast_without_retry(monkeypatch):
    """Verify that HTTP 401/403 fails fast on attempt 1 without any retry sleeps."""
    mock_client = MockGenaiClient([
        APIError(code=401, response_json={"error": {"message": "API key invalid"}}, response=None),
        '{"status": "should not reach"}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    with pytest.raises(AIAuthError) as excinfo:
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=3,
            _sleep_fn=lambda s: sleep_history.append(s),
        )

    assert mock_client.call_count == 1
    assert len(sleep_history) == 0
    assert "authentication failed" in excinfo.value.user_friendly_message.lower()


def test_permanent_bad_request_fails_fast_without_retry(monkeypatch):
    """Verify that HTTP 400 fails fast on attempt 1 without retrying."""
    mock_client = MockGenaiClient([
        APIError(code=400, response_json={"error": {"message": "Invalid field value"}}, response=None),
        '{"status": "should not reach"}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    with pytest.raises(AIBadRequestError):
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=3,
            _sleep_fn=lambda s: sleep_history.append(s),
        )

    assert mock_client.call_count == 1
    assert len(sleep_history) == 0


def test_format_ai_error_for_user_never_exposes_traceback():
    """Verify that format_ai_error_for_user always strips raw traceback info and returns friendly messages."""
    raw_error_with_traceback = Exception(
        "Traceback (most recent call last):\n"
        "  File 'c:/secret/path/internal.py', line 89, in connect\n"
        "ConnectionRefusedError: [Errno 111] Connection refused"
    )
    user_msg = format_ai_error_for_user(raw_error_with_traceback)

    assert "Traceback" not in user_msg
    assert "internal.py" not in user_msg
    assert "Errno 111" not in user_msg
    assert "AI analysis service is temporarily unavailable" in user_msg or "busy" in user_msg.lower()


def test_configurable_retry_settings_from_config(monkeypatch):
    """Verify that generate_json_response respects custom default values configured in config.py."""
    monkeypatch.setattr(config, "GEMINI_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(config, "GEMINI_RETRY_INITIAL_DELAY", 0.25)
    monkeypatch.setattr(config, "GEMINI_RETRY_BACKOFF_FACTOR", 3.0)
    monkeypatch.setattr(config, "GEMINI_RETRY_JITTER", False)

    mock_client = MockGenaiClient([
        APIError(code=503, response_json={"error": {"message": "Overloaded"}}, response=None),
        '{"status": "recovered"}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: mock_client)

    sleep_history = []
    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        _sleep_fn=lambda s: sleep_history.append(s),
    )

    assert result == {"status": "recovered"}
    assert mock_client.call_count == 2
    assert sleep_history == [pytest.approx(0.25)]
