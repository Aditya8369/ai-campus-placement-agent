"""
Optional Sentry Error Monitoring and Privacy-Preserving Scrubbing Integration (#562).

Provides:
- Optional Sentry initialization controlled by SENTRY_DSN (disabled when not set).
- Custom `before_send` hook that scrubs:
  * Request bodies, form data, and raw payloads.
  * Cookies and authorization headers.
  * Student emails, phone numbers, and PII.
  * Fields containing resume or job description content.
- Strict event tagging containing only:
  * release
  * route
  * request_id
- Custom `before_breadcrumb` hook to scrub breadcrumb metadata.
- Graceful no-op fallback when sentry-sdk is not installed or SENTRY_DSN is unset.
"""

import os
import re
import logging
from typing import Dict, Any, Optional, Union

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk import Scope
    SENTRY_AVAILABLE = True
except ImportError:
    sentry_sdk = None  # type: ignore
    FlaskIntegration = None  # type: ignore
    Scope = None  # type: ignore
    SENTRY_AVAILABLE = False

import config
from utils.logger_config import (
    redact_text,
    get_current_request_id,
)

logger = logging.getLogger(__name__)

# Sensitive header names (case-insensitive) to strip from error reports
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "proxy-authorization",
    "x-csrf-token",
    "x-csrftoken",
    "x-api-key",
}

# Substrings in dictionary keys that indicate candidate or credential sensitive data
SENSITIVE_KEY_SUBSTRINGS = (
    "resume",
    "job_description",
    "jd",
    "email",
    "phone",
    "mobile",
    "cookie",
    "authorization",
    "auth",
    "token",
    "password",
    "secret",
    "credential",
    "ssn",
    "transcript",
    "bio",
    "student_name",
    "candidate_name",
    "cv",
)

# Robust fallback PII patterns matching international/domestic variations
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
PHONE_REGEX = re.compile(
    r'(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b|\b(?:\+91[\s-]?)?[6-9]\d{9}\b'
)


def scrub_text(text: Any) -> Any:
    """
    Scrubs sensitive candidate personal details, emails, phone numbers,
    and resume/job description content from string values (#562).
    """
    if not isinstance(text, str):
        return text

    # Apply structured logging redaction filter (handles registered resume texts, labeled headers, etc.)
    cleaned = redact_text(text)

    # Secondary defense: scrub email and phone patterns explicitly
    cleaned = EMAIL_REGEX.sub("[REDACTED_EMAIL]", cleaned)
    cleaned = PHONE_REGEX.sub("[REDACTED_PHONE]", cleaned)
    return cleaned


def deep_scrub(data: Any) -> Any:
    """
    Recursively scrubs dictionary or list data structures, removing or redacting
    any keys containing resume, job description, email, phone, or credential keywords.
    """
    if isinstance(data, dict):
        scrubbed: Dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in SENSITIVE_KEY_SUBSTRINGS):
                scrubbed[k] = "[SCRUBBED]"
            else:
                scrubbed[k] = deep_scrub(v)
        return scrubbed
    elif isinstance(data, (list, tuple, set)):
        return [deep_scrub(item) for item in data]
    elif isinstance(data, str):
        return scrub_text(data)
    return data


def scrub_sentry_event(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Sentry before_send callback (#562).

    Enforces strict privacy boundaries:
    1. Removes request bodies, form data, and raw payloads completely.
    2. Removes cookies and sensitive headers (Authorization, Cookie, etc.).
    3. Removes user identities and PII (email, phone, student IDs).
    4. Deeply scrubs any extra context or breadcrumbs for resume/JD text.
    5. Scrubs exception messages for candidate contact information.
    6. Tags events strictly and only with: `release`, `route`, and `request_id`.
    """
    if not isinstance(event, dict):
        return event

    # 1. Scrub HTTP request details
    req = event.get("request")
    if isinstance(req, dict):
        # Remove request bodies and form data
        req.pop("data", None)
        # Remove cookies
        req.pop("cookies", None)

        # Remove authorization and session headers
        headers = req.get("headers")
        if isinstance(headers, dict):
            for header_name in list(headers.keys()):
                if header_name.lower() in SENSITIVE_HEADERS:
                    headers.pop(header_name, None)
        elif isinstance(headers, list):
            req["headers"] = [
                h for h in headers
                if isinstance(h, (list, tuple)) and len(h) >= 1 and str(h[0]).lower() not in SENSITIVE_HEADERS
            ]

        # Remove sensitive WSGI environment variables
        env = req.get("env")
        if isinstance(env, dict):
            for env_key in list(env.keys()):
                key_lower = env_key.lower()
                if any(sh in key_lower for sh in ("cookie", "auth", "token", "secret", "password")):
                    env.pop(env_key, None)

        # Scrub query strings
        if "query_string" in req and isinstance(req["query_string"], str):
            req["query_string"] = scrub_text(req["query_string"])

    # 2. Remove user identification object entirely
    event.pop("user", None)

    # 3. Deep-scrub extra and contexts
    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = deep_scrub(event["extra"])

    if "contexts" in event and isinstance(event["contexts"], dict):
        # Remove or scrub Flask session and request data if captured in contexts
        contexts = event["contexts"]
        if "state" in contexts:
            contexts.pop("state", None)
        event["contexts"] = deep_scrub(contexts)

    # 4. Scrub breadcrumbs
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        crumb_values = breadcrumbs.get("values", [])
        if isinstance(crumb_values, list):
            for crumb in crumb_values:
                if isinstance(crumb, dict):
                    crumb.pop("data", None)
                    if "message" in crumb and isinstance(crumb["message"], str):
                        crumb["message"] = scrub_text(crumb["message"])
    elif isinstance(breadcrumbs, list):
        for crumb in breadcrumbs:
            if isinstance(crumb, dict):
                crumb.pop("data", None)
                if "message" in crumb and isinstance(crumb["message"], str):
                    crumb["message"] = scrub_text(crumb["message"])

    # 5. Scrub exception values and messages
    exc_info = event.get("exception")
    if isinstance(exc_info, dict):
        exc_values = exc_info.get("values", [])
        if isinstance(exc_values, list):
            for exc in exc_values:
                if isinstance(exc, dict) and "value" in exc and isinstance(exc["value"], str):
                    exc["value"] = scrub_text(exc["value"])

    # 6. Scrub top-level message if present
    if "message" in event and isinstance(event["message"], str):
        event["message"] = scrub_text(event["message"])

    # 7. Extract metadata for tagging
    release = (
        event.get("release")
        or getattr(config, "SENTRY_RELEASE", None)
        or f"ai-campus-placement-agent@{config.__version__}"
    )

    route: Optional[str] = None
    request_id: str = "none"

    try:
        from flask import has_request_context, request as flask_req, g
        if has_request_context():
            if flask_req.url_rule and flask_req.url_rule.rule:
                route = flask_req.url_rule.rule
            elif getattr(flask_req, "path", None):
                route = flask_req.path

            req_id_val = getattr(g, "request_id", None) or get_current_request_id() or flask_req.headers.get("X-Request-ID")
            if req_id_val and req_id_val != "-":
                request_id = str(req_id_val)
    except Exception:
        pass

    if not route:
        route = event.get("transaction") or "unknown"

    if request_id == "none":
        context_req_id = get_current_request_id()
        if context_req_id and context_req_id != "-":
            request_id = str(context_req_id)

    # Strictly limit event tags to release, route, and request ID only
    event["tags"] = {
        "release": str(release),
        "route": str(route),
        "request_id": str(request_id),
    }
    event["release"] = str(release)

    return event


def scrub_sentry_breadcrumb(crumb: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Sentry before_breadcrumb callback (#562).
    Scrubs breadcrumb data and messages before they are recorded in memory.
    """
    if not isinstance(crumb, dict):
        return crumb

    # Remove arbitrary data payloads attached to breadcrumbs
    crumb.pop("data", None)

    if "message" in crumb and isinstance(crumb["message"], str):
        crumb["message"] = scrub_text(crumb["message"])

    return crumb


def init_sentry(
    app: Optional[Any] = None,
    dsn: Optional[str] = None,
    release: Optional[str] = None,
    environment: Optional[str] = None,
    traces_sample_rate: Optional[float] = None,
) -> bool:
    """
    Initializes Sentry error monitoring when SENTRY_DSN is configured (#562).

    Parameters:
    - app: Optional Flask application instance.
    - dsn: Optional Sentry DSN override.
    - release: Optional release name/version.
    - environment: Optional environment name (production, staging, etc.).
    - traces_sample_rate: Optional performance tracing sample rate.

    Returns:
    - True if Sentry was initialized.
    - False if Sentry is disabled or unavailable.
    """
    if not SENTRY_AVAILABLE or sentry_sdk is None:
        logger.info("sentry-sdk is not installed. Sentry monitoring is disabled.")
        return False

    # Resolve DSN
    resolved_dsn = dsn
    if not resolved_dsn and app and hasattr(app, "config"):
        resolved_dsn = app.config.get("SENTRY_DSN")
    if not resolved_dsn:
        resolved_dsn = os.getenv("SENTRY_DSN") or getattr(config, "SENTRY_DSN", "")

    if not resolved_dsn or not str(resolved_dsn).strip():
        logger.info("Sentry monitoring is disabled (SENTRY_DSN not configured).")
        return False

    resolved_dsn = str(resolved_dsn).strip()

    # Resolve release
    resolved_release = (
        release
        or (app.config.get("SENTRY_RELEASE") if app and hasattr(app, "config") else None)
        or os.getenv("SENTRY_RELEASE")
        or getattr(config, "SENTRY_RELEASE", f"ai-campus-placement-agent@{config.__version__}")
    )

    # Resolve environment
    resolved_env = (
        environment
        or (app.config.get("SENTRY_ENVIRONMENT") if app and hasattr(app, "config") else None)
        or os.getenv("SENTRY_ENVIRONMENT")
        or getattr(config, "SENTRY_ENVIRONMENT", "production")
    )

    # Resolve traces sample rate
    if traces_sample_rate is None:
        raw_traces = (
            (app.config.get("SENTRY_TRACES_SAMPLE_RATE") if app and hasattr(app, "config") else None)
            or os.getenv("SENTRY_TRACES_SAMPLE_RATE")
            or getattr(config, "SENTRY_TRACES_SAMPLE_RATE", 0.0)
        )
        try:
            traces_sample_rate = float(raw_traces)
        except (ValueError, TypeError):
            traces_sample_rate = 0.0

    integrations = []
    if FlaskIntegration is not None:
        integrations.append(FlaskIntegration(transaction_style="url"))

    try:
        sentry_sdk.init(
            dsn=resolved_dsn,
            release=str(resolved_release),
            environment=str(resolved_env),
            integrations=integrations,
            before_send=scrub_sentry_event,
            before_breadcrumb=scrub_sentry_breadcrumb,
            send_default_pii=False,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=0.0,
        )
        logger.info(
            f"Sentry error monitoring initialized (release={resolved_release}, env={resolved_env})."
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry: {e}")
        return False


def is_sentry_enabled() -> bool:
    """Returns True if Sentry is active and initialized."""
    if not SENTRY_AVAILABLE or sentry_sdk is None:
        return False
    try:
        client = sentry_sdk.get_client()
        return bool(client and client.is_active())
    except Exception:
        return False


def close_sentry() -> None:
    """Closes the current Sentry client and resets scopes (useful for cleanup and tests)."""
    if not SENTRY_AVAILABLE or sentry_sdk is None:
        return
    try:
        client = sentry_sdk.get_client()
        if client:
            client.close()
        if Scope is not None:
            Scope.get_global_scope().set_client(None)
            Scope.get_isolation_scope().set_client(None)
            Scope.get_current_scope().set_client(None)
    except Exception:
        pass


def capture_exception(error: Optional[Union[Exception, tuple]] = None, **kwargs) -> Optional[str]:
    """Safe wrapper for sentry_sdk.capture_exception that gracefully no-ops when Sentry is inactive."""
    if not is_sentry_enabled() or sentry_sdk is None:
        return None
    try:
        return sentry_sdk.capture_exception(error, **kwargs)
    except Exception:
        return None
