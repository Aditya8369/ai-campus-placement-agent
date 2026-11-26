"""
Comprehensive tests for AI error handling, custom exception classifications,
rate limiting, network timeouts, authentication issues, and user-friendly error messages.
"""

import socket
import pytest
from google.genai.errors import APIError
from utils.gemini import (
    AIAnalysisError,
    AIRateLimitError,
    AINetworkError,
    AIAuthError,
    AIResponseFormatError,
    AIServiceUnavailableError,
    format_ai_error_for_user,
    create_safe_fallback_analysis_payload,
    generate_json_response,
    get_gemini_client,
)
from app import app
import config


def test_ai_exception_hierarchy():
    """Verify that all specific AI exceptions inherit from AIAnalysisError and carry user-friendly messages."""
    rate_err = AIRateLimitError("429 Too Many Requests")
    assert isinstance(rate_err, AIAnalysisError)
    assert rate_err.retryable is True
    assert "quota limit has been reached" in rate_err.user_friendly_message

    net_err = AINetworkError("Connection reset by peer")
    assert isinstance(net_err, AIAnalysisError)
    assert net_err.retryable is True
    assert "network connection issue" in net_err.user_friendly_message

    auth_err = AIAuthError("Invalid API key")
    assert isinstance(auth_err, AIAnalysisError)
    assert auth_err.retryable is False
    assert "authentication failed" in auth_err.user_friendly_message

    fmt_err = AIResponseFormatError("Truncated json")
    assert isinstance(fmt_err, AIAnalysisError)
    assert "incomplete or formatted unexpectedly" in fmt_err.user_friendly_message

    srv_err = AIServiceUnavailableError("503 Service Unavailable")
    assert isinstance(srv_err, AIAnalysisError)
    assert srv_err.retryable is True
    assert "temporarily experiencing downtime" in srv_err.user_friendly_message


def test_format_ai_error_for_user_translates_known_patterns():
    """Verify that raw exceptions are translated into clear, helpful guidance for students."""
    # Custom exception
    custom_err = AIRateLimitError("Resource Exhausted")
    assert "quota limit has been reached" in format_ai_error_for_user(custom_err)

    # Generic Exception with quota/rate limit keyword
    raw_quota = RuntimeError("Resource exhausted: rate limit 429 quota")
    msg1 = format_ai_error_for_user(raw_quota)
    assert "quota or rate limit exceeded" in msg1

    # Generic Exception with network/timeout keyword
    raw_net = socket.timeout("Timed out waiting for socket")
    msg2 = format_ai_error_for_user(raw_net)
    assert "Network timeout" in msg2

    # Generic Exception with auth keyword
    raw_auth = ValueError("Unauthorized: API key invalid")
    msg3 = format_ai_error_for_user(raw_auth)
    assert "AI Authentication issue" in msg3


def test_missing_api_key_raises_auth_error(monkeypatch):
    """Verify that a missing or placeholder API key raises AIAuthError."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(AIAuthError) as excinfo:
        get_gemini_client()
    assert "Missing Gemini API Key" in str(excinfo.value)


def test_placeholder_api_key_raises_auth_error(monkeypatch):
    """Verify that the default placeholder API key raises AIAuthError."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
    with pytest.raises(AIAuthError) as excinfo:
        get_gemini_client()
    assert "Missing Gemini API Key" in str(excinfo.value)


def test_generate_json_response_empty_text_raises_format_error(monkeypatch):
    """Verify that an empty response from Gemini raises AIResponseFormatError."""
    class FakeResponse:
        text = ""

    class FakeModels:
        def generate_content(self, *args, **kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: FakeClient())
    with pytest.raises(AIResponseFormatError) as excinfo:
        generate_json_response("instruction", "prompt")
    assert "empty response" in str(excinfo.value).lower()


def test_generate_json_response_malformed_json_raises_format_error(monkeypatch):
    """Verify that malformed unparseable output raises AIResponseFormatError."""
    class FakeResponse:
        text = "```json\n{ unquoted_key: invalid_json } \n```"

    class FakeModels:
        def generate_content(self, *args, **kwargs):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: FakeClient())
    with pytest.raises(AIResponseFormatError) as excinfo:
        generate_json_response("instruction", "prompt")
    assert "Failed to parse Gemini response" in str(excinfo.value)


def test_generate_json_response_handles_api_error_rate_limit(monkeypatch):
    """Verify that APIError with rate limit signals raises AIRateLimitError."""
    class FakeModels:
        def generate_content(self, *args, **kwargs):
            raise APIError(code=429, response_json={"error": {"message": "Resource has been exhausted quota 429"}}, response=None)

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: FakeClient())
    with pytest.raises(AIRateLimitError):
        generate_json_response("instruction", "prompt")


def test_generate_json_response_handles_api_error_service_unavailable(monkeypatch):
    """Verify that APIError with 503 unavailable raises AIServiceUnavailableError."""
    class FakeModels:
        def generate_content(self, *args, **kwargs):
            raise APIError(code=503, response_json={"error": {"message": "The model is overloaded. Unavailable"}}, response=None)

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda: FakeClient())
    with pytest.raises(AIServiceUnavailableError):
        generate_json_response("instruction", "prompt")


def test_create_safe_fallback_analysis_payload_structure():
    """Verify that create_safe_fallback_analysis_payload returns full schema matching all agents."""
    fallback = create_safe_fallback_analysis_payload(company_name="Amazon", error_reason="Rate limit")
    
    assert "resume_analysis" in fallback
    assert fallback["resume_analysis"]["ats_score"] > 0
    assert len(fallback["resume_analysis"]["strengths"]) > 0

    assert "job_match" in fallback
    assert fallback["job_match"]["match_percentage"] > 0

    assert "skill_gap" in fallback
    assert isinstance(fallback["skill_gap"], list)

    assert "learning_roadmap" in fallback
    assert len(fallback["learning_roadmap"]) == 6

    assert "interview_questions" in fallback
    assert len(fallback["interview_questions"]["hr"]) == 5
    assert len(fallback["interview_questions"]["technical"]) == 5
    assert len(fallback["interview_questions"]["behavioral"]) == 5

    assert "Amazon" in fallback["overall_recommendation_summary"]


def test_analyze_route_flashes_friendly_error_on_ai_failure(monkeypatch):
    """Verify that /analyze route catches AI exceptions and produces labelled basic analysis (#849)."""
    from agents.coordinator import CoordinatorAgent
    def mock_analyze_fail(*args, **kwargs):
        raise AIRateLimitError("Resource has been exhausted.")
    
    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_analyze_fail)

    app.config["TESTING"] = True
    with app.test_client() as client:
        valid_resume = (
            "Senior Computer Science candidate with Python, Docker, Algorithms, and System Design experience. "
            "Led placement club and developed placement platform applications."
        )
        res = client.post(
            "/analyze",
            data={"resume_text": valid_resume, "company": "Microsoft"},
            follow_redirects=True
        )
        assert res.status_code == 200
        assert b"basic analysis (ai unavailable)" in res.data.lower()
