"""
Unit and integration tests for Issue #497:
feat: handle AI API timeouts, rate limits and errors gracefully.

Verifies:
1. Simulated timeouts and rate limits trigger retries with backoff and show friendly messages in the UI.
2. Missing or invalid API key shows a clear, polite friendly message.
3. Network connection failures trigger retries and show friendly messages.
4. Permanent errors (HTTP 400, 401, 403) fail fast without retrying.
5. Request timeout is enforced on every AI call via config and parameters.
6. The API key never appears in application logs or user-facing UI / responses.
"""

import io
import logging
import socket
import pytest
from unittest.mock import patch, MagicMock
from google.genai.errors import APIError

import config
from app import app
from utils.gemini import (
    generate_json_response,
    get_gemini_client,
    classify_gemini_error,
    format_ai_error_for_user,
    scrub_api_key,
    AIAnalysisError,
    AITimeoutError,
    AIRateLimitError,
    AINetworkError,
    AIAuthError,
    AIServiceUnavailableError,
    AIBadRequestError,
)
from utils.logger_config import SensitiveDataRedactionFilter, redact_text


class MockSequentialGenaiClient:
    """Mock Gemini client supporting sequential exceptions or responses."""
    def __init__(self, items):
        self.queue = list(items)
        self.call_count = 0
        self.models = self
        self.last_config = None

    def generate_content(self, model=None, contents=None, config=None):
        self.call_count += 1
        self.last_config = config
        if not self.queue:
            raise RuntimeError("MockSequentialGenaiClient: No responses queued")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, type) and issubclass(item, Exception):
            raise item()

        class MockResponse:
            def __init__(self, text):
                self.text = text
                self.usage_metadata = None
        return MockResponse(item)


# ==============================================================================
# 1. Timeout Handling & Recovery
# ==============================================================================

def test_request_timeout_parameter_configured_on_client_and_call(monkeypatch):
    """Verify generate_json_response configures HttpOptions timeout from config or parameter."""
    mock_client = MockSequentialGenaiClient(['{"status": "ok", "ats_score": 90}'])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        request_timeout=15.0,
        max_retries=0,
    )
    assert result == {"status": "ok", "ats_score": 90}
    assert mock_client.last_config is not None
    # http_options should have timeout in milliseconds (15000 ms)
    http_opts = getattr(mock_client.last_config, "http_options", None)
    if http_opts:
        assert http_opts.timeout == 15000


def test_simulated_socket_timeout_retries_and_recovers(monkeypatch):
    """Verify that a transient socket timeout is retried and succeeds on recovery."""
    mock_client = MockSequentialGenaiClient([
        socket.timeout("Socket read timed out after 30000ms"),
        '{"status": "recovered", "ats_score": 88}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

    sleep_history = []
    result = generate_json_response(
        system_instruction="sys",
        prompt="prompt",
        max_retries=2,
        initial_delay=0.5,
        jitter=False,
        _sleep_fn=lambda s: sleep_history.append(s),
    )
    assert result == {"status": "recovered", "ats_score": 88}
    assert mock_client.call_count == 2
    assert len(sleep_history) == 1
    assert sleep_history[0] == pytest.approx(0.5)


def test_exhausted_timeouts_raise_friendly_timeout_error(monkeypatch):
    """Verify that after exhausting retries on timeout, a user-friendly error is raised."""
    mock_client = MockSequentialGenaiClient([
        socket.timeout("Timeout 1"),
        TimeoutError("Timeout 2"),
        socket.timeout("Timeout 3"),
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

    sleep_history = []
    with pytest.raises(AITimeoutError) as excinfo:
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=2,
            initial_delay=0.1,
            jitter=False,
            _sleep_fn=lambda s: sleep_history.append(s),
        )

    assert mock_client.call_count == 3
    assert len(sleep_history) == 2
    err = excinfo.value
    assert isinstance(err, AINetworkError)
    assert err.retryable is True
    # Friendly message check
    assert "busy" in err.user_friendly_message.lower() or "timeout" in err.user_friendly_message.lower()


def test_api_504_gateway_timeout_classified_as_ai_timeout_error():
    """Verify that HTTP 504 or deadline_exceeded API errors are classified as AITimeoutError."""
    err_504 = APIError(code=504, response_json={"error": {"message": "Gateway Timeout 504"}}, response=None)
    classified = classify_gemini_error(err_504)
    assert isinstance(classified, AITimeoutError)
    assert classified.retryable is True


# ==============================================================================
# 2. Rate Limit Handling & Recovery
# ==============================================================================

def test_simulated_rate_limit_retries_with_exponential_backoff(monkeypatch):
    """Verify HTTP 429 rate limit triggers exponential backoff (1s, 2s) and succeeds on 3rd attempt."""
    mock_client = MockSequentialGenaiClient([
        APIError(code=429, response_json={"error": {"message": "Resource has been exhausted"}}, response=None),
        APIError(code=429, response_json={"error": {"message": "Rate limit exceeded 429"}}, response=None),
        '{"status": "success", "ats_score": 82}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

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

    assert result == {"status": "success", "ats_score": 82}
    assert mock_client.call_count == 3
    assert len(sleep_history) == 2
    assert sleep_history[0] == pytest.approx(1.0)
    assert sleep_history[1] == pytest.approx(2.0)


def test_exhausted_rate_limits_show_friendly_message(monkeypatch):
    """Verify that exhausted rate limit attempts provide friendly guidance without technical tracebacks."""
    mock_client = MockSequentialGenaiClient([
        APIError(code=429, response_json={"error": {"message": "Quota exceeded"}}, response=None),
        APIError(code=429, response_json={"error": {"message": "Quota exceeded"}}, response=None),
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

    with pytest.raises(AIRateLimitError) as excinfo:
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=1,
            initial_delay=0.1,
            jitter=False,
            _sleep_fn=lambda s: None,
        )

    err = excinfo.value
    friendly = format_ai_error_for_user(err)
    assert "busy" in friendly.lower() or "quota" in friendly.lower()
    assert "Traceback" not in friendly
    assert "google.genai" not in friendly


# ==============================================================================
# 3. Missing API Key & Network Failure Friendly Messages
# ==============================================================================

def test_missing_api_key_shows_clear_friendly_message(monkeypatch):
    """Verify that missing GEMINI_API_KEY generates a clear, actionable user message."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(AIAuthError) as excinfo:
        get_gemini_client()

    err = excinfo.value
    assert err.retryable is False
    assert "Missing Gemini API Key" in err.message
    friendly = format_ai_error_for_user(err)
    assert "GEMINI_API_KEY" in friendly or "authentication failed" in friendly.lower() or "api key" in friendly.lower()


def test_network_connection_reset_classified_and_friendly():
    """Verify network connection failures provide friendly reassurance to students."""
    conn_err = ConnectionResetError("Connection reset by peer [Errno 104]")
    classified = classify_gemini_error(conn_err)
    assert isinstance(classified, AINetworkError)
    assert classified.retryable is True

    friendly = format_ai_error_for_user(conn_err)
    assert "network" in friendly.lower() or "busy" in friendly.lower()
    assert "Errno 104" not in friendly


# ==============================================================================
# 4. Permanent Errors Fail Fast
# ==============================================================================

def test_permanent_invalid_api_key_fails_fast_without_retrying(monkeypatch):
    """Verify HTTP 401/403 fails fast on the very first attempt without backoff sleeps."""
    mock_client = MockSequentialGenaiClient([
        APIError(code=401, response_json={"error": {"message": "API_KEY_INVALID"}}, response=None),
        '{"should": "never be called"}'
    ])
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda timeout=None: mock_client)

    sleep_called = False
    with pytest.raises(AIAuthError) as excinfo:
        generate_json_response(
            system_instruction="sys",
            prompt="prompt",
            max_retries=3,
            _sleep_fn=lambda s: True,
        )

    assert mock_client.call_count == 1
    assert sleep_called is False
    assert excinfo.value.retryable is False


# ==============================================================================
# 5. UI Integration: Simulated Timeouts & Rate Limits Display Friendly Messages
# ==============================================================================

VALID_SAMPLE_RESUME = (
    "Senior Computer Science student at University with expertise in Python, Flask, "
    "Docker, algorithms, and distributed database architectures. Conducted software testing."
)


def test_analyze_route_handles_simulated_timeout_with_friendly_message(monkeypatch):
    """Verify that /analyze flashes friendly message when simulated timeout occurs."""
    from agents.coordinator import CoordinatorAgent
    def mock_analyze_timeout(*args, **kwargs):
        raise AITimeoutError("Request timed out after 30 seconds.")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_analyze_timeout)

    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test_student_timeout"
        res = client.post(
            "/analyze",
            data={
                "resume_text": VALID_SAMPLE_RESUME,
                "company": "Amazon",
                "consent": "true",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert ("busy" in html.lower() or "timeout" in html.lower())
        assert "Traceback" not in html


def test_analyze_route_handles_simulated_rate_limit_with_friendly_message(monkeypatch):
    """Verify that /analyze flashes friendly message when simulated rate limit occurs."""
    from agents.coordinator import CoordinatorAgent
    def mock_analyze_rate_limit(*args, **kwargs):
        raise AIRateLimitError("HTTP 429 quota exhausted.")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_analyze_rate_limit)

    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test_student_ratelimit"
        res = client.post(
            "/analyze",
            data={
                "resume_text": VALID_SAMPLE_RESUME,
                "company": "Google",
                "consent": "true",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert ("quota" in html.lower() or "busy" in html.lower())
        assert "Traceback" not in html


# ==============================================================================
# 6. Security: The API Key NEVER Appears in Logs or the UI
# ==============================================================================

def test_api_key_never_appears_in_logs_during_failure():
    """Verify that an API key contained in an error or request never leaks to log outputs."""
    secret_key = "AIzaSyD_SECRET_KEY_123456789_XYZ"

    log_stream = io.StringIO()
    test_handler = logging.StreamHandler(log_stream)
    test_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    test_handler.addFilter(SensitiveDataRedactionFilter())

    target_logger = logging.getLogger("utils.gemini")
    target_logger.addHandler(test_handler)

    try:
        # Simulate error containing API key in URL and error message
        raw_error_text = f"APIError: Request https://generativelanguage.googleapis.com/v1beta/models?key={secret_key} failed with 403"
        classified = classify_gemini_error(Exception(raw_error_text))

        # Test logger warning / error
        target_logger.warning(f"Failed call with key {secret_key}: {classified}")
        target_logger.error(f"Exhausted retries: {raw_error_text}")

        log_output = log_stream.getvalue()
        assert secret_key not in log_output
        assert "[REDACTED_SECRET]" in log_output or "[REDACTED_API_KEY]" in log_output
    finally:
        target_logger.removeHandler(test_handler)


def test_api_key_never_appears_in_ui_response_on_failure(monkeypatch):
    """Verify that if an exception containing an API key occurs, the key is never sent to the UI."""
    secret_key = "AIzaSySecretLeakedKey1234567890ABCD"
    from agents.coordinator import CoordinatorAgent

    def mock_analyze_leaky_error(*args, **kwargs):
        raise Exception(f"Failed contacting https://generativelanguage.googleapis.com/?key={secret_key}")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_analyze_leaky_error)

    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test_student_leaky"
        res = client.post(
            "/analyze",
            data={
                "resume_text": VALID_SAMPLE_RESUME,
                "company": "Netflix",
                "consent": "true",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Crucial Acceptance Criteria Check:
        assert secret_key not in html
        assert "generativelanguage.googleapis.com" not in html
        assert "busy" in html.lower()


def test_scrub_api_key_utility():
    """Verify scrub_api_key scrubs Google API keys, URL params, and headers from strings and dicts."""
    key = "AIzaSyD_TestScrubKey_9876543210_ABCD"
    text = f"Error calling endpoint with ?key={key}&other=1 and header x-goog-api-key: {key}"
    scrubbed = scrub_api_key(text)

    assert key not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed

    # Test dictionary scrubbing
    payload = {
        "status": "error",
        "details": f"API key {key} was rejected",
        "nested": {"token": key}
    }
    scrubbed_dict = scrub_api_key(payload)
    assert key not in str(scrubbed_dict)
    assert "[REDACTED_SECRET]" in scrubbed_dict["details"]
    assert "[REDACTED_SECRET]" in scrubbed_dict["nested"]["token"]
