"""
Gemini API client, utilities, structured JSON parsing, and resilient error handling.

Provides custom exception classifications for AI API rate limits, network timeouts,
service unavailability, authentication failures, and response truncation.
Includes fallback recovery mechanisms and user-facing error message formatting.
"""

import logging
import json
import re
import socket
import time
import random
from typing import Any, Dict, Optional, Tuple, Callable
from google import genai
from google.genai import types
from google.genai.errors import APIError
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==============================================================================
# Custom AI Exception Hierarchy for Placement Agent (#80)
# ==============================================================================

class AIAnalysisError(Exception):
    """Base exception for all AI analysis processing failures."""
    def __init__(self, message: str, user_friendly_message: Optional[str] = None, retryable: bool = False):
        try:
            from utils.prompt_security import redact_sensitive_information
            clean_message = redact_sensitive_information(message)
            clean_user_message = redact_sensitive_information(user_friendly_message) if user_friendly_message else None
        except Exception:
            clean_message = message
            clean_user_message = user_friendly_message

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
    Guarantees that raw exceptions, internal traces, or stack traces are never exposed to the user.
    """
    try:
        from utils.prompt_security import redact_sensitive_information
    except Exception:
        def redact_sensitive_information(x): return x

    if isinstance(exc, AIAnalysisError):
        return redact_sensitive_information(exc.user_friendly_message)

    err_str = str(exc).lower()
    if "rate limit" in err_str or "quota" in err_str or "429" in err_str or "resource_exhausted" in err_str:
        return (
            "The AI service is busy, please try again in a minute. "
            "API quota or rate limit exceeded. Please wait a few moments and try your analysis again."
        )
    elif "api key" in err_str or "unauthorized" in err_str or "forbidden" in err_str or "permission" in err_str:
        return (
            "AI Authentication issue: Invalid or missing GEMINI_API_KEY. Please verify your API key in settings."
        )
    elif "503" in err_str or "500" in err_str or "unavailable" in err_str or "overloaded" in err_str:
        return "The AI service is busy, please try again in a minute."
    elif "timeout" in err_str or "connection" in err_str or "timed out" in err_str or "network" in err_str:
        return (
            "The AI service is busy, please try again in a minute. "
            "Network timeout while connecting to AI service. Please check your connection and retry in a minute."
        )
    elif "json" in err_str or "parse" in err_str:
        return (
            "The AI generated an incomplete response. Please try submitting again with more resume details."
        )
    else:
        return "The AI service is busy, please try again in a minute."


def get_gemini_client() -> genai.Client:
    """
    Initializes and returns the Gemini client using config settings.
    Raises AIAuthError if API Key is missing or default.
    """
    api_key = config.GEMINI_API_KEY
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        logger.error("GEMINI_API_KEY is not configured in .env file.")
        raise AIAuthError("Missing Gemini API Key. Please set GEMINI_API_KEY in your .env file.")
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
    """
    if isinstance(exc, AIAnalysisError):
        return exc

    if isinstance(exc, (socket.timeout, TimeoutError)):
        return AINetworkError(f"Network timeout contacting Gemini: {str(exc)}")

    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return AINetworkError(f"Network connection failed contacting Gemini: {str(exc)}")

    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        msg = str(exc)
        msg_lower = msg.lower()

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
        ):
            return AIAuthError(f"Gemini authentication failed: {msg}")

        # 5xx Service Unavailable / Internal Server Error / Overloaded (Transient)
        if (
            code in (500, 502, 503, 504)
            or any(c in msg for c in ("500", "502", "503", "504"))
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

    err_str = str(exc).lower()
    if "connection" in err_str or "dns" in err_str or "network" in err_str or "timed out" in err_str:
        return AINetworkError(f"Network error communicating with AI provider: {str(exc)}")

    return AIAnalysisError(f"Unexpected AI processing error: {str(exc)}", retryable=False)


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
    _sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """
    Sends a request to Gemini using the google-genai SDK, enforcing a JSON response.
    Wraps the call with exponential backoff and jitter retry logic for transient errors
    (429, 500, 503, timeouts), while failing fast on permanent errors (400, 401, 403).

    Configuration defaults are loaded from config.py:
    - config.GEMINI_RETRY_ATTEMPTS (default 3 retries)
    - config.GEMINI_RETRY_INITIAL_DELAY (default 1.0s)
    - config.GEMINI_RETRY_BACKOFF_FACTOR (default 2.0)
    - config.GEMINI_RETRY_MAX_DELAY (default 10.0s)
    - config.GEMINI_RETRY_JITTER (default True)
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

    total_attempts = max(1, retries + 1)
    client = get_gemini_client()

    cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.2,
    )

    for attempt in range(1, total_attempts + 1):
        raw_text = ""
        start_time = time.time()
        try:
            logger.info(f"Invoking Gemini model: {config.GEMINI_MODEL} (attempt {attempt}/{total_attempts})")
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
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

        except AIResponseFormatError:
            # Format/truncation errors fail without exponential delay (handled by coordinator schema logic)
            raise

        except Exception as e:
            # Log failure to database if attempts are exhausted or non-retryable (#215)
            try:
                from utils.database import log_gemini_api_call
                from utils.prompt_security import redact_sensitive_information
                latency_ms = int((time.time() - start_time) * 1000)
                log_gemini_api_call(
                    endpoint="generate_json_response",
                    model_name=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
                    prompt_tokens=max(1, len(prompt) // 4),
                    candidate_tokens=0,
                    total_tokens=max(1, len(prompt) // 4),
                    latency_ms=latency_ms,
                    status="failed",
                    error_message=redact_sensitive_information(str(e))[:300],
                )
            except Exception:
                pass

            classified = classify_gemini_error(e)

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
                    f"({classified.__class__.__name__}: {str(e)}). "
                    f"Retrying in {delay:.2f}s with exponential backoff..."
                )
                _sleep_fn(delay)
                continue

            # Permanent error (fails fast without retry)
            if not classified.retryable:
                logger.error(
                    f"Gemini API permanent failure encountered on attempt {attempt} "
                    f"({classified.__class__.__name__}: {str(e)}). Failing fast without retry."
                )
                raise classified from e
            else:
                # All transient retry attempts exhausted
                logger.error(
                    f"Gemini API request failed after {total_attempts} attempts. "
                    f"All transient retries exhausted. Real error: {str(e)}",
                    exc_info=True,
                )
                classified.user_friendly_message = (
                    "The AI service is busy, please try again in a minute."
                )
                raise classified from e
