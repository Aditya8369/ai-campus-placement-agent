"""
Gemini API client, utilities, structured JSON parsing, and resilient error handling.

Provides custom exception classifications for AI API rate limits, network timeouts,
service unavailability, authentication failures, and response truncation.
Includes fallback recovery mechanisms and user-facing error message formatting.
"""

import os
import logging
import json
import re
import socket
import time
import random
from typing import Any, Dict, Optional, Tuple, Callable, Generator, Set, List
from google import genai
from google.genai import types
from google.genai.errors import APIError
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==============================================================================
# Sensitive Information & API Key Scrubbing (#497)
# ==============================================================================

GOOGLE_API_KEY_PATTERN = re.compile(r"\bAIza[0-9A-Za-z\-_]{25,}\b")
URL_API_KEY_PATTERN = re.compile(r"([?&](?:key|api_key|token)=)[^&\s'\"]+", re.IGNORECASE)
HEADER_API_KEY_PATTERN = re.compile(r"(?i)(?:x-goog-api-key|authorization|bearer)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{16,})['\"]?")
ASSIGNED_API_KEY_PATTERN = re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?")


def scrub_api_key(val: Any) -> Any:
    """
    Scans and scrubs Google Gemini API keys, query parameters, auth headers,
    and configured credentials from strings, dicts, lists, or exceptions (#497).
    Guarantees the API key never appears in logs, traces, or the UI.
    """
    if val is None:
        return ""
    if isinstance(val, Exception):
        val = str(val)
    if isinstance(val, str):
        cleaned = val
        try:
            from utils.prompt_security import redact_sensitive_information
            cleaned = redact_sensitive_information(cleaned)
        except Exception:
            pass

        cleaned = GOOGLE_API_KEY_PATTERN.sub("[REDACTED_SECRET]", cleaned)
        cleaned = URL_API_KEY_PATTERN.sub(r"\g<1>[REDACTED_SECRET]", cleaned)
        cleaned = HEADER_API_KEY_PATTERN.sub("[REDACTED_SECRET]", cleaned)
        cleaned = ASSIGNED_API_KEY_PATTERN.sub("[REDACTED_SECRET]", cleaned)

        known_secrets = [
            getattr(config, "GEMINI_API_KEY", ""),
            os.getenv("GEMINI_API_KEY", ""),
        ]
        for s in known_secrets:
            if s and len(s) >= 8 and s != "YOUR_GEMINI_API_KEY_HERE":
                cleaned = cleaned.replace(s, "[REDACTED_SECRET]")

        return cleaned
    elif isinstance(val, dict):
        return {k: scrub_api_key(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [scrub_api_key(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(scrub_api_key(item) for item in val)
    return val


class _GeminiLoggingScrubFilter(logging.Filter):
    """Logging filter ensuring logger output never exposes API keys or credentials (#497)."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = scrub_api_key(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: scrub_api_key(v) for k, v in record.args.items()}
                elif isinstance(record.args, (list, tuple)):
                    record.args = tuple(scrub_api_key(a) for a in record.args)
            if record.exc_text:
                record.exc_text = scrub_api_key(record.exc_text)
        except Exception:
            pass
        return True

logger.addFilter(_GeminiLoggingScrubFilter())


# ==============================================================================
# Custom AI Exception Hierarchy for Placement Agent (#80, #497)
# ==============================================================================

class AIAnalysisError(Exception):
    """Base exception for all AI analysis processing failures."""
    def __init__(self, message: str, user_friendly_message: Optional[str] = None, retryable: bool = False):
        clean_message = scrub_api_key(message)
        clean_user_message = scrub_api_key(user_friendly_message) if user_friendly_message else None

        super().__init__(clean_message)
        self.message = clean_message
        self.user_friendly_message = clean_user_message or (
            "We encountered an issue while communicating with the AI mentor. "
            "Please try again in a few moments."
        )
        self.retryable = retryable


class AIRateLimitError(AIAnalysisError):
    """Raised when the AI model provider returns HTTP 429 or quota exceeded."""
    def __init__(self, message: str = "Rate limit exceeded", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "The AI service is busy, please try again in a minute. "
                "Your API quota limit has been reached or the service is receiving high traffic."
            ),
            retryable=True,
        )


class AINetworkError(AIAnalysisError):
    """Raised when network connectivity, DNS, or socket connection to the AI provider fails."""
    def __init__(self, message: str = "Network connection failed", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "Unable to connect to the AI service due to a network connection issue. "
                "The AI service is busy, please try again in a minute."
            ),
            retryable=True,
        )


class AITimeoutError(AINetworkError):
    """Raised when an AI request times out or takes too long to respond (#497)."""
    def __init__(self, message: str = "AI request timed out", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "The AI service is busy and took too long to respond. "
                "Network timeout while connecting to AI service. Please check your connection and retry in a minute."
            ),
        )


class AIAuthError(AIAnalysisError):
    """Raised when GEMINI_API_KEY is invalid, missing, or unauthorized."""
    def __init__(self, message: str = "Authentication failed", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "Gemini API authentication failed. Please verify that your GEMINI_API_KEY is properly "
                "configured with valid permissions in your environment."
            ),
            retryable=False,
        )


class AIResponseFormatError(AIAnalysisError):
    """Raised when the AI output cannot be parsed into the expected structured JSON format."""
    def __init__(self, message: str = "Malformed or incomplete AI JSON response", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "The AI analysis response was incomplete or formatted unexpectedly. "
                "Our fault-tolerant recovery agent has attempted a repair. If the issue persists, "
                "please try submitting again."
            ),
            retryable=False,
        )


class AIServiceUnavailableError(AIAnalysisError):
    """Raised when Gemini returns 500, 503, or temporary backend overload errors."""
    def __init__(self, message: str = "AI service temporarily unavailable", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "The AI service is busy, please try again in a minute. "
                "The service is temporarily experiencing downtime or service maintenance."
            ),
            retryable=True,
        )


class AIBadRequestError(AIAnalysisError):
    """Raised when the AI service returns HTTP 400 Bad Request or invalid argument (permanent)."""
    def __init__(self, message: str = "Bad request sent to AI service", user_friendly_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message=user_friendly_message or (
                "The request to the AI service was invalid. Please check your inputs and try again."
            ),
            retryable=False,
        )



def format_ai_error_for_user(exc: Exception) -> str:
    """
    Translates raw exceptions into friendly, actionable user messages for flash alerts.
    Guarantees that raw exceptions, internal traces, or API keys are never exposed to the user (#497).
    """
    if isinstance(exc, AIAnalysisError):
        return scrub_api_key(exc.user_friendly_message)

    err_str = scrub_api_key(str(exc)).lower()
    if "rate limit" in err_str or "quota" in err_str or "429" in err_str or "resource_exhausted" in err_str:
        msg = (
            "The AI service is busy, please try again in a minute. "
            "API quota or rate limit exceeded. Please wait a few moments and try your analysis again."
        )
    elif "api key" in err_str or "unauthorized" in err_str or "forbidden" in err_str or "permission" in err_str:
        msg = (
            "AI Authentication issue: Invalid or missing GEMINI_API_KEY. Please verify your API key in settings."
        )
    elif "503" in err_str or "500" in err_str or "unavailable" in err_str or "overloaded" in err_str:
        msg = "The AI service is busy, please try again in a minute."
    elif "timeout" in err_str or "connection" in err_str or "timed out" in err_str or "network" in err_str or "deadline" in err_str:
        msg = (
            "The AI service is busy, please try again in a minute. "
            "Network timeout while connecting to AI service. Please check your connection and retry in a minute."
        )
    elif "json" in err_str or "parse" in err_str:
        msg = (
            "The AI generated an incomplete response. Please try submitting again with more resume details."
        )
    else:
        msg = "The AI service is busy, please try again in a minute."

    return scrub_api_key(msg)


def get_gemini_client(timeout: Optional[float] = None) -> genai.Client:
    """
    Initializes and returns the Gemini client using config settings.
    Raises AIAuthError if API Key is missing or default.
    Configures http_options with request timeout (#497).
    """
    api_key = config.GEMINI_API_KEY
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        logger.error("GEMINI_API_KEY is not configured in .env file.")
        raise AIAuthError("Missing Gemini API Key. Please set GEMINI_API_KEY in your .env file.")

    timeout_sec = timeout if timeout is not None else getattr(config, "GEMINI_REQUEST_TIMEOUT", 30.0)
    timeout_ms = int(timeout_sec * 1000) if timeout_sec else None

    try:
        http_options = types.HttpOptions(timeout=timeout_ms) if timeout_ms else None
        return genai.Client(api_key=api_key, http_options=http_options)
    except Exception as init_err:
        clean_init_err = scrub_api_key(str(init_err))
        logger.warning(
            f"Could not initialize genai.Client with http_options ({clean_init_err}); falling back to standard client init."
        )
        return genai.Client(api_key=api_key)


def _extract_json_string(text: str) -> str:
    """
    Cleans markdown code fences, strips conversational preambles/postambles,
    and returns the isolated JSON string.
    """
    if not text:
        return ""

    cleaned = text.strip().lstrip("\ufeff")

    # 1. Search for markdown code fence anywhere in the response
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(fence_pattern, cleaned, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        # Verify the candidate starts and ends with JSON structural delimiters
        if (candidate.startswith("{") and candidate.endswith("}")) or (
            candidate.startswith("[") and candidate.endswith("]")
        ):
            return candidate

    # 2. If no valid fence, extract the outermost object { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()

    # 3. Check for outermost array [ ... ]
    first_bracket = cleaned.find("[")
    last_bracket = cleaned.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        return cleaned[first_bracket : last_bracket + 1].strip()

    # 4. Fallback: Return original stripped string
    return cleaned


def create_safe_fallback_analysis_payload(company_name: str = "General", error_reason: str = "") -> Dict[str, Any]:
    """
    Generates a resilient, structured fallback payload if AI generation encounters an unrecoverable failure.
    Guarantees the dashboard view won't crash when rendering partial or fallback outcomes.
    """
    logger.info(f"Generating safe fallback analysis payload for {company_name}")
    return {
        "resume_analysis": {
            "ats_score": 65,
            "overall_feedback": (
                "Resume received and preliminary baseline computed. "
                f"Full AI deep-dive experienced a temporary service limitation ({error_reason or 'service busy'})."
            ),
            "strengths": [
                "Clean document layout and readable text formatting.",
                "Foundational technical qualifications and educational background identified."
            ],
            "areas_of_improvement": [
                "Quantify measurable engineering outcomes in project bullets (e.g. % improvement).",
                "Ensure core technologies match target role requirements closely."
            ],
            "keywords_found": ["General Computing", "Engineering", "Development"],
            "keywords_missing": ["Production CI/CD", "Cloud Architecture"]
        },
        "job_match": {
            "match_percentage": 68,
            "matched_skills": ["Programming Fundamentals", "Problem Solving", "Core CS Knowledge"],
            "missing_skills": ["Domain-Specific Frameworks", "Production Deployment Experience"],
            "hiring_criteria": "Standard campus hiring readiness benchmark.",
            "recommendation": "Strengthen technical portfolio with deployment-ready capstone projects."
        },
        "skill_gap": [
            {
                "skill": "Production Architecture & Testing",
                "priority": "High",
                "reason": "Campus recruiters seek demonstrated project lifecycle and testing experience.",
                "suggested_project": "Build an end-to-end full stack web application with unit and integration tests."
            },
            {
                "skill": "System Design Fundamentals",
                "priority": "Medium",
                "reason": "Crucial for clearing intermediate technical rounds.",
                "suggested_project": "Design and document a scalable distributed URL shortener or rate limiter."
            }
        ],
        "learning_roadmap": [
            {
                "week": 1,
                "focus": "Core Data Structures & Algorithmic Complexity",
                "tasks": ["Review Arrays, Hash Tables, and Pointers", "Solve 10 LeetCode Easy/Medium problems"]
            },
            {
                "week": 2,
                "focus": "Trees, Graphs & Dynamic Programming",
                "tasks": ["Study BFS/DFS and recursion patterns", "Implement basic DP memoization"]
            },
            {
                "week": 3,
                "focus": "System Design & Database Modeling",
                "tasks": ["Learn database normalization and indexing", "Practice API design patterns"]
            },
            {
                "week": 4,
                "focus": "Portfolio Project Modernization",
                "tasks": ["Refactor existing resume project", "Add Docker containerization and documentation"]
            },
            {
                "week": 5,
                "focus": "Company-Specific Mock Technical Rounds",
                "tasks": ["Review previous hiring questions", "Conduct timed coding practice"]
            },
            {
                "week": 6,
                "focus": "HR, Behavioral & STAR Format Preparation",
                "tasks": ["Prepare STAR stories for past accomplishments", "Practice communication and composure"]
            }
        ],
        "interview_questions": {
            "hr": [
                "Can you introduce yourself and explain what motivated your interest in this engineering role?",
                "Describe a project challenge where you had to quickly learn a new technology or tool.",
                "How do you organize your time when balancing multiple deadlines or coursework?",
                "What kind of team environment allows you to do your best work?",
                "Where do you see yourself developing technically over the next two years?"
            ],
            "technical": [
                "How do hash tables work internally, and how are collision resolutions handled?",
                "Explain the difference between synchronous and asynchronous code execution with examples.",
                "What happens under the hood when a user types a URL into a browser and presses Enter?",
                "Compare SQL vs NoSQL databases in terms of schema flexibility and ACID guarantees.",
                "How would you approach debugging a memory leak or sudden spike in CPU utilization?"
            ],
            "behavioral": [
                "Tell me about a time you had a technical disagreement with a team member and how you resolved it.",
                "Describe a situation where a project deliverable didn't go as planned. What was your takeaway?",
                "Give an example of receiving critical code review feedback and how you incorporated it.",
                "How do you handle ambiguous requirements when assigned an open-ended project task?",
                "Describe a project achievement that you are most proud of and your individual contribution."
            ]
        },
        "overall_recommendation_summary": (
            f"Baseline placement readiness profile established for {company_name}. "
            "Focus on the recommended 6-week curriculum and practice your mock interview questions."
        ),
        "conflicts": []
    }


def calculate_backoff_delay(
    attempt: int,
    initial_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    max_delay: Optional[float] = None,
    use_jitter: Optional[bool] = None,
) -> float:
    """
    Calculates exponential backoff delay with jitter for a retry attempt (1-indexed).
    Formula: min(max_delay, initial_delay * (backoff_factor ** (attempt - 1))) + jitter
    Default progression: attempt 1 -> 1s, attempt 2 -> 2s, attempt 3 -> 4s.
    """
    init_d = initial_delay if initial_delay is not None else getattr(config, "GEMINI_RETRY_INITIAL_DELAY", 1.0)
    factor = backoff_factor if backoff_factor is not None else getattr(config, "GEMINI_RETRY_BACKOFF_FACTOR", 2.0)
    max_d = max_delay if max_delay is not None else getattr(config, "GEMINI_RETRY_MAX_DELAY", 10.0)
    jitter_flag = use_jitter if use_jitter is not None else getattr(config, "GEMINI_RETRY_JITTER", True)

    exponent = max(0, attempt - 1)
    base_delay = min(max_d, init_d * (factor ** exponent))

    if jitter_flag and base_delay > 0:
        # Add random uniform jitter up to 25% of base delay (min 0.05s)
        jitter_val = random.uniform(0.0, max(0.05, 0.25 * base_delay))
        return base_delay + jitter_val
    return base_delay


def classify_gemini_error(exc: Exception) -> AIAnalysisError:
    """
    Translates raw Google GenAI APIError or system exceptions into typed AIAnalysisError subclasses.
    Differentiates transient errors (429, 500, 503, timeouts) from permanent errors (400, 401, 403).
    Ensures technical details are classified without exposing API keys (#497).
    """
    if isinstance(exc, AIAnalysisError):
        return exc

    clean_exc_str = scrub_api_key(str(exc))
    exc_type_name = type(exc).__name__.lower()
    exc_module = getattr(type(exc), "__module__", "").lower()

    # Timeouts (Transient) (#497)
    if (
        isinstance(exc, (socket.timeout, TimeoutError))
        or "timeout" in exc_type_name
        or "timeout" in exc_module
        or "deadline" in clean_exc_str.lower()
        or "timed out" in clean_exc_str.lower()
    ):
        return AITimeoutError(f"Network timeout contacting Gemini: {clean_exc_str}")

    # Network Connection Failures (Transient)
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return AINetworkError(f"Network connection failed contacting Gemini: {clean_exc_str}")

    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        msg = clean_exc_str
        msg_lower = msg.lower()

        # 504 Gateway Timeout or Deadline Exceeded (Transient) (#497)
        if (
            code == 504
            or "504" in msg
            or "deadline_exceeded" in msg_lower
            or "timed out" in msg_lower
            or "timeout" in msg_lower
        ):
            return AITimeoutError(f"Gemini API timeout: {msg}")

        # 429 Rate Limit / Quota Exhaustion (Transient)
        if code == 429 or "429" in msg or "resource_exhausted" in msg_lower or "quota" in msg_lower:
            return AIRateLimitError(f"Gemini API quota exceeded: {msg}")

        # 401 / 403 Authentication / Authorization (Permanent)
        if (
            code in (401, 403)
            or "401" in msg
            or "403" in msg
            or ("invalid_argument" in msg_lower and "key" in msg_lower)
            or "permission_denied" in msg_lower
            or "unauthenticated" in msg_lower
            or "api key not valid" in msg_lower
            or "api_key_invalid" in msg_lower
        ):
            return AIAuthError(f"Gemini authentication failed: {msg}")

        # 5xx Service Unavailable / Internal Server Error / Overloaded (Transient)
        if (
            code in (500, 502, 503)
            or any(c in msg for c in ("500", "502", "503"))
            or "unavailable" in msg_lower
            or "overloaded" in msg_lower
            or "internal error" in msg_lower
        ):
            return AIServiceUnavailableError(f"Gemini service temporarily unavailable: {msg}")

        # 400 Bad Request / Invalid Argument (Permanent)
        if code == 400 or "invalid_argument" in msg_lower or "bad request" in msg_lower:
            return AIBadRequestError(f"Gemini API Bad Request: {msg}")

        # Other API errors
        return AIAnalysisError(f"Gemini API Error: {msg}", retryable=False)

    err_str = clean_exc_str.lower()
    if "timeout" in err_str or "timed out" in err_str or "deadline" in err_str:
        return AITimeoutError(f"Network timeout contacting Gemini: {clean_exc_str}")
    if "connection" in err_str or "dns" in err_str or "network" in err_str:
        return AINetworkError(f"Network error communicating with AI provider: {clean_exc_str}")

    return AIAnalysisError(f"Unexpected AI processing error: {clean_exc_str}", retryable=False)


def is_transient_error(exc: Exception) -> bool:
    """
    Determines whether an exception is transient (429, 500, 503, timeouts)
    and should be retried automatically with exponential backoff.
    Permanent errors (400, 401, 403, invalid key) return False and fail fast.
    """
    classified = classify_gemini_error(exc)
    return bool(classified.retryable)


def generate_json_response(
    system_instruction: str,
    prompt: str,
    max_retries: Optional[int] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    max_delay: Optional[float] = None,
    jitter: Optional[bool] = None,
    request_timeout: Optional[float] = None,
    feature: Optional[str] = None,
    _sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """
    Sends a request to Gemini using the google-genai SDK, enforcing a JSON response.
    Wraps the call with exponential backoff and jitter retry logic for transient errors
    (429, 500, 503, timeouts), while failing fast on permanent errors (400, 401, 403).
    Enforces a strict request timeout on every AI call (#497).

    Configuration defaults are loaded from config.py:
    - config.GEMINI_RETRY_ATTEMPTS (default 3 retries)
    - config.GEMINI_RETRY_INITIAL_DELAY (default 1.0s)
    - config.GEMINI_RETRY_BACKOFF_FACTOR (default 2.0)
    - config.GEMINI_RETRY_MAX_DELAY (default 10.0s)
    - config.GEMINI_RETRY_JITTER (default True)
    - config.GEMINI_REQUEST_TIMEOUT (default 30.0s)
    """
    retries = max_retries if max_retries is not None else getattr(config, "GEMINI_RETRY_ATTEMPTS", 3)
    init_d = initial_delay if initial_delay is not None else getattr(config, "GEMINI_RETRY_INITIAL_DELAY", 1.0)
    factor = backoff_factor if backoff_factor is not None else getattr(config, "GEMINI_RETRY_BACKOFF_FACTOR", 2.0)
    if max_delay is not None:
        max_d = max_delay
    elif initial_delay is not None:
        max_d = max(getattr(config, "GEMINI_RETRY_MAX_DELAY", 10.0), init_d * (factor ** retries))
    else:
        max_d = getattr(config, "GEMINI_RETRY_MAX_DELAY", 10.0)
    use_jitter = jitter if jitter is not None else getattr(config, "GEMINI_RETRY_JITTER", True)

    effective_timeout = request_timeout if request_timeout is not None else getattr(config, "GEMINI_REQUEST_TIMEOUT", 30.0)
    timeout_ms = int(effective_timeout * 1000) if effective_timeout else None

    # Determine effective feature for operational telemetry (#434)
    effective_feature = (feature or "").strip().lower()
    if not effective_feature:
        try:
            from utils.ai_metrics import get_current_ai_feature
            effective_feature = get_current_ai_feature() or "analysis"
        except Exception:
            effective_feature = "analysis"

    total_attempts = max(1, retries + 1)
    try:
        client = get_gemini_client(timeout=effective_timeout)
    except TypeError:
        client = get_gemini_client()

    cfg_kwargs = {
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
        "temperature": 0.2,
    }
    if timeout_ms:
        try:
            cfg_kwargs["http_options"] = types.HttpOptions(timeout=timeout_ms)
        except Exception:
            pass
    cfg = types.GenerateContentConfig(**cfg_kwargs)

    # Defense-in-depth: Ensure outgoing model prompt contains no emails or phone numbers (#500)
    effective_prompt = prompt
    if getattr(config, "ENABLE_PII_REDACTION", True):
        try:
            from utils.pii_redactor import redact_pii
            effective_prompt = redact_pii(prompt)
        except Exception as pii_err:
            logger.warning(f"PII redaction skipped due to error: {pii_err}")

    for attempt in range(1, total_attempts + 1):
        raw_text = ""
        start_time = time.time()
        try:
            logger.info(f"Invoking Gemini model: {config.GEMINI_MODEL} (attempt {attempt}/{total_attempts})")
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=effective_prompt,
                config=cfg,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            raw_text = getattr(response, "text", "") or ""
            if not raw_text or not raw_text.strip():
                logger.error("Gemini returned an empty or null text response.")
                raise AIResponseFormatError("Gemini returned an empty response. The model may have truncated output.")

            # Extract token metadata if available from response (#215)
            prompt_tokens = 0
            candidate_tokens = 0
            total_tokens = 0
            try:
                usage_meta = getattr(response, "usage_metadata", None)
                if usage_meta:
                    prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
                    candidate_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
                    total_tokens = getattr(usage_meta, "total_token_count", 0) or (prompt_tokens + candidate_tokens)
            except Exception:
                pass

            # Estimate tokens if SDK metadata is empty (approx 4 chars per token)
            if prompt_tokens == 0:
                prompt_tokens = max(1, len(prompt) // 4)
            if candidate_tokens == 0:
                candidate_tokens = max(1, len(raw_text) // 4)
            if total_tokens == 0:
                total_tokens = prompt_tokens + candidate_tokens

            # Log API invocation to database for cost monitoring (#215)
            try:
                from utils.database import log_gemini_api_call
                log_gemini_api_call(
                    endpoint="generate_json_response",
                    model_name=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    prompt_tokens=prompt_tokens,
                    candidate_tokens=candidate_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    status="success",
                )
            except Exception as log_err:
                logger.debug(f"Non-fatal Gemini log error: {log_err}")

            # Record AI call metrics without user content (#434)
            try:
                from utils.ai_metrics import record_ai_call_metric
                record_ai_call_metric(
                    feature=effective_feature,
                    model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    latency_ms=latency_ms,
                    token_count=total_tokens,
                    prompt_tokens=prompt_tokens,
                    candidate_tokens=candidate_tokens,
                    success=True,
                    error_type=None,
                )
            except Exception as metric_err:
                logger.debug(f"Non-fatal AI metrics recording error: {metric_err}")

            logger.info("Successfully received Gemini response text. Attempting JSON parsing...")
            cleaned_json = _extract_json_string(raw_text)
            parsed_data = json.loads(cleaned_json)

            if not isinstance(parsed_data, (dict, list)):
                raise AIResponseFormatError("Parsed AI output is neither a dictionary nor a list.")

            try:
                from utils.prompt_security import redact_sensitive_information
                parsed_data = redact_sensitive_information(parsed_data)
            except Exception:
                pass

            return parsed_data

        except json.JSONDecodeError as jde:
            logger.error(f"JSON decoding failed. Content was: {raw_text[:500] if raw_text else 'None'}... Error: {jde}")
            try:
                from utils.gemini_response_validator import attempt_json_repair
                repaired = attempt_json_repair(raw_text)
                if repaired is not None and isinstance(repaired, (dict, list)):
                    logger.info("Successfully recovered truncated/malformed Gemini JSON response (#277).")
                    return repaired
            except Exception as repair_err:
                logger.debug(f"JSON repair attempt failed: {repair_err}")
            raise AIResponseFormatError(
                f"Failed to parse Gemini response as valid JSON: {str(jde)}"
            )

        except AIResponseFormatError as afe:
            # Record AI call metric failure for format error (#434)
            try:
                from utils.ai_metrics import record_ai_call_metric
                latency_ms = int((time.time() - start_time) * 1000)
                record_ai_call_metric(
                    feature=effective_feature,
                    model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    latency_ms=latency_ms,
                    token_count=max(1, len(prompt) // 4),
                    prompt_tokens=max(1, len(prompt) // 4),
                    candidate_tokens=0,
                    success=False,
                    error_type="AIResponseFormatError",
                )
            except Exception:
                pass
            # Format/truncation errors fail without exponential delay (handled by coordinator schema logic)
            raise

        except Exception as e:
            classified = classify_gemini_error(e)
            latency_ms = int((time.time() - start_time) * 1000)
            clean_err = scrub_api_key(str(e))

            # Record AI call metrics failure (#434)
            try:
                from utils.ai_metrics import record_ai_call_metric
                record_ai_call_metric(
                    feature=effective_feature,
                    model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    latency_ms=latency_ms,
                    token_count=max(1, len(prompt) // 4),
                    prompt_tokens=max(1, len(prompt) // 4),
                    candidate_tokens=0,
                    success=False,
                    error_type=classified.__class__.__name__,
                )
            except Exception as metric_err:
                logger.debug(f"Non-fatal AI metrics recording error: {metric_err}")

            # Log failure to database if attempts are exhausted or non-retryable (#215)
            try:
                from utils.database import log_gemini_api_call
                log_gemini_api_call(
                    endpoint="generate_json_response",
                    model_name=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    prompt_tokens=max(1, len(prompt) // 4),
                    candidate_tokens=0,
                    total_tokens=max(1, len(prompt) // 4),
                    latency_ms=latency_ms,
                    status="failed",
                    error_message=clean_err[:300],
                )
            except Exception:
                pass

            # Check if this error is transient and we have remaining retry attempts
            if classified.retryable and attempt < total_attempts:
                delay = calculate_backoff_delay(
                    attempt=attempt,
                    initial_delay=init_d,
                    backoff_factor=factor,
                    max_delay=max_d,
                    use_jitter=use_jitter,
                )
                logger.warning(
                    f"Gemini API transient failure on attempt {attempt}/{total_attempts} "
                    f"({classified.__class__.__name__}: {clean_err}). "
                    f"Retrying in {delay:.2f}s with exponential backoff..."
                )
                _sleep_fn(delay)
                continue

            # Permanent error (fails fast without retry)
            if not classified.retryable:
                logger.error(
                    f"Gemini API permanent failure encountered on attempt {attempt} "
                    f"({classified.__class__.__name__}: {clean_err}). Failing fast without retry."
                )
                raise classified from e
            else:
                # All transient retry attempts exhausted
                logger.error(
                    f"Gemini API request failed after {total_attempts} attempts. "
                    f"All transient retries exhausted. Real error: {clean_err}"
                )
                classified.user_friendly_message = (
                    "The AI service is busy, please try again in a minute."
                )
                raise classified from e


# ==============================================================================
# Streaming JSON Response Generator (#764)
# ==============================================================================

STANDARD_ANALYSIS_SECTIONS: List[str] = [
    "resume_analysis",
    "job_match",
    "skill_gap",
    "learning_roadmap",
    "interview_questions",
    "overall_recommendation_summary",
]


def extract_completed_sections_from_buffer(
    buffer: str,
    completed: Set[str],
    expected_sections: Optional[List[str]] = None,
) -> List[Tuple[str, Any]]:
    """
    Scans a streaming JSON buffer and extracts fully completed top-level sections
    without waiting for the entire document to close (#764).
    """
    sections = expected_sections or STANDARD_ANALYSIS_SECTIONS
    results: List[Tuple[str, Any]] = []

    for sec in sections:
        if sec in completed:
            continue

        pattern = re.compile(rf'"{re.escape(sec)}"\s*:\s*')
        m = pattern.search(buffer)
        if not m:
            continue

        start_idx = m.end()
        while start_idx < len(buffer) and buffer[start_idx] in " \t\r\n":
            start_idx += 1

        if start_idx >= len(buffer):
            continue

        open_char = buffer[start_idx]
        if open_char == "{":
            close_char = "}"
        elif open_char == "[":
            close_char = "]"
        elif open_char == '"':
            close_char = '"'
        else:
            continue

        in_string = (open_char == '"')
        escape = False
        depth = 1
        end_idx = None

        for i in range(start_idx + 1, len(buffer)):
            c = buffer[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                if open_char == '"' and not in_string:
                    end_idx = i + 1
                    break
                continue
            if not in_string:
                if c == open_char:
                    depth += 1
                elif c == close_char:
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break

        if end_idx is not None:
            snippet = buffer[start_idx:end_idx]
            try:
                val = json.loads(snippet)
                if isinstance(val, (dict, list, str)):
                    try:
                        from utils.prompt_security import redact_sensitive_information
                        val = redact_sensitive_information(val)
                    except Exception:
                        pass
                results.append((sec, val))
                completed.add(sec)
            except Exception:
                pass

    return results


def stream_json_response_sections(
    system_instruction: str,
    prompt: str,
    expected_sections: Optional[List[str]] = None,
    is_cancelled_fn: Optional[Callable[[], bool]] = None,
    request_timeout: Optional[float] = None,
    feature: Optional[str] = "analysis",
) -> Generator[Tuple[str, Any], None, None]:
    """
    Streams content from Gemini using client.models.generate_content_stream (#764).
    Yields (section_name, parsed_section_data) as each top-level section completes,
    allowing the client to render each section before the full response finishes.

    Cancellation:
        Checks is_cancelled_fn() on each streamed chunk. If True, cleanly stops consumption
        and stops the underlying request.

    Mid-stream error handling:
        If an error occurs mid-stream, captures the error and yields:
        ('_stream_error', {'error': error_msg, 'completed_sections': list(completed)})
        ensuring content already received and shown is never discarded.

    Non-streaming fallback:
        If streaming cannot be initialized or fails on the first chunk before any section
        is parsed, callers can seamlessly fall back to generate_json_response.
    """
    effective_timeout = request_timeout if request_timeout is not None else getattr(config, "GEMINI_REQUEST_TIMEOUT", 30.0)
    timeout_ms = int(effective_timeout * 1000) if effective_timeout else None
    sections_list = expected_sections or STANDARD_ANALYSIS_SECTIONS

    try:
        client = get_gemini_client(timeout=effective_timeout)
    except TypeError:
        client = get_gemini_client()

    cfg_kwargs = {
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
        "temperature": 0.2,
    }
    if timeout_ms:
        try:
            cfg_kwargs["http_options"] = types.HttpOptions(timeout=timeout_ms)
        except Exception:
            pass

    cfg = types.GenerateContentConfig(**cfg_kwargs)

    effective_prompt = prompt
    if getattr(config, "ENABLE_PII_REDACTION", True):
        try:
            from utils.pii_redactor import redact_pii
            effective_prompt = redact_pii(prompt)
        except Exception:
            pass

    completed_sections: Set[str] = set()
    buffer = ""
    start_time = time.time()

    logger.info(f"Initiating streaming Gemini response for feature={feature} model={config.GEMINI_MODEL}")

    try:
        stream = client.models.generate_content_stream(
            model=config.GEMINI_MODEL,
            contents=effective_prompt,
            config=cfg,
        )

        for chunk in stream:
            # Check cancellation between chunks (#764)
            if is_cancelled_fn and is_cancelled_fn():
                logger.info("Cancellation detected during Gemini stream iteration. Halting stream.")
                yield ("_cancelled", {"completed_sections": list(completed_sections)})
                return

            chunk_text = getattr(chunk, "text", "") or ""
            if not chunk_text:
                continue

            buffer += chunk_text

            # Extract any newly completed sections from accumulated buffer
            newly_completed = extract_completed_sections_from_buffer(
                buffer=buffer,
                completed=completed_sections,
                expected_sections=sections_list,
            )

            for sec_name, sec_data in newly_completed:
                logger.info(f"Streamed section complete: '{sec_name}'")
                yield (sec_name, sec_data)

        # End of stream: Check for any final section that might have completed with closing brace
        remaining = extract_completed_sections_from_buffer(
            buffer=buffer,
            completed=completed_sections,
            expected_sections=sections_list,
        )
        for sec_name, sec_data in remaining:
            logger.info(f"Streamed final section complete: '{sec_name}'")
            yield (sec_name, sec_data)

    except Exception as stream_err:
        clean_err = scrub_api_key(str(stream_err))
        logger.warning(
            f"Error occurred during Gemini response streaming: {clean_err}. "
            f"Completed sections: {list(completed_sections)}"
        )
        # Mid-stream error: yield error event with completed sections preserved (#764)
        yield (
            "_stream_error",
            {
                "error": format_ai_error_for_user(stream_err),
                "error_details": clean_err,
                "completed_sections": list(completed_sections),
            },
        )

