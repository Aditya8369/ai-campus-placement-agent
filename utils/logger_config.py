"""
Structured Logging, Correlation Tracing, and Sensitive Content Redaction System (#301).

Provides:
- Configurable log levels via LOG_LEVEL environment variable.
- Key-value, JSON, and standard text formatters with request ID correlation.
- Automatic Request ID assignment per HTTP request and response header echo.
- Sensitive data redaction filter preventing resume text, job description text,
  emails, and phone numbers from leaking into application logs, recording lengths and IDs instead.
"""

import os
import re
import sys
import json
import logging
import contextvars
from datetime import datetime, timezone
from typing import Optional, List, Any

# Context variable for request correlation tracing outside Flask request context (e.g. background tasks)
_CURRENT_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("current_request_id", default="-")
_ACTIVE_SENSITIVE_TEXTS: contextvars.ContextVar[List[str]] = contextvars.ContextVar("active_sensitive_texts", default=[])

# Regular expressions for PII detection
EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)

# Standard international, US/Canada, and Indian phone number patterns (at least 7 to 15 digits with formatting)
PHONE_REGEX = re.compile(
    r'(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b|\b(?:\+91[\s-]?)?[6-9]\d{9}\b'
)

# Labeled pattern matching for logs explicitly passing resume or job description content
RESUME_LABELED_REGEX = re.compile(
    r'(?i)\b(resume(?:_text|_content|_raw)?|resume)\s*[:=]\s*(["\']?)([\s\S]+?)\2(?=\s*,\s*\w+=|\s*$|\n|\Z)'
)

JD_LABELED_REGEX = re.compile(
    r'(?i)\b(job_description|jd(?:_text|_content)?)\s*[:=]\s*(["\']?)([\s\S]+?)\2(?=\s*,\s*\w+=|\s*$|\n|\Z)'
)

# Common resume structure header detection (Education, Experience, Skills, Projects)
RESUME_HEADER_REGEX = re.compile(
    r'(?i)\b(curriculum\s+vitae|resume\s+summary|education|work\s+experience|professional\s+experience|technical\s+skills|projects|academic\s+background)\b'
)


def get_current_request_id() -> str:
    """
    Retrieves the active request correlation ID.
    Checks Flask request context `g.request_id` or header `X-Request-ID`,
    falling back to context variable or '-' for non-HTTP contexts.
    """
    try:
        from flask import has_request_context, g, request
        if has_request_context():
            req_id = getattr(g, "request_id", None)
            if not req_id and hasattr(request, "headers"):
                req_id = request.headers.get("X-Request-ID")
            if req_id:
                return str(req_id)
    except Exception:
        pass
    return _CURRENT_REQUEST_ID.get() or "-"


def set_current_request_id(request_id: str) -> None:
    """Sets the active correlation request ID in both contextvars and Flask g."""
    clean_id = str(request_id or "-").strip()
    _CURRENT_REQUEST_ID.set(clean_id)
    try:
        from flask import has_request_context, g
        if has_request_context():
            g.request_id = clean_id
    except Exception:
        pass


def register_sensitive_text(text: Optional[str]) -> None:
    """
    Registers sensitive candidate content (such as raw resume text or job description)
    to ensure it is dynamically scrubbed if accidentally formatted into any log statement.
    """
    if not text or not isinstance(text, str):
        return
    clean = text.strip()
    if len(clean) < 15:
        return

    current_list = list(_ACTIVE_SENSITIVE_TEXTS.get() or [])
    if clean not in current_list:
        current_list.append(clean)
        _ACTIVE_SENSITIVE_TEXTS.set(current_list)

    try:
        from flask import has_request_context, g
        if has_request_context():
            if not hasattr(g, "_sensitive_texts"):
                g._sensitive_texts = []
            if clean not in g._sensitive_texts:
                g._sensitive_texts.append(clean)
    except Exception:
        pass


def clear_sensitive_texts() -> None:
    """Clears registered sensitive texts for the current execution context."""
    _ACTIVE_SENSITIVE_TEXTS.set([])
    try:
        from flask import has_request_context, g
        if has_request_context() and hasattr(g, "_sensitive_texts"):
            g._sensitive_texts = []
    except Exception:
        pass


def redact_text(text: Any) -> str:
    """
    Scrubs sensitive candidate personal details, emails, phone numbers,
    and resume/job description content from a log message string (#301).
    Replaces content with metadata markers logging lengths instead.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    # 1. Redact emails
    text = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)

    # 2. Redact phone numbers
    text = PHONE_REGEX.sub("[REDACTED_PHONE]", text)

    # 3. Redact labeled resume content (e.g. resume="...", resume_text: ...)
    def _replace_resume_label(match: re.Match) -> str:
        label = match.group(1)
        content = match.group(3)
        return f"{label}=[REDACTED_RESUME len={len(content)}]"

    text = RESUME_LABELED_REGEX.sub(_replace_resume_label, text)

    # 4. Redact labeled job description content (e.g. job_description="...")
    def _replace_jd_label(match: re.Match) -> str:
        label = match.group(1)
        content = match.group(3)
        return f"{label}=[REDACTED_JOB_DESCRIPTION len={len(content)}]"

    text = JD_LABELED_REGEX.sub(_replace_jd_label, text)

    # 5. Redact registered sensitive texts (e.g. extracted resume text for active request)
    registered_texts = list(_ACTIVE_SENSITIVE_TEXTS.get() or [])
    try:
        from flask import has_request_context, g
        if has_request_context() and hasattr(g, "_sensitive_texts"):
            registered_texts.extend(g._sensitive_texts)
    except Exception:
        pass

    for st in registered_texts:
        if st and st in text:
            text = text.replace(st, f"[REDACTED_SENSITIVE_CONTENT len={len(st)}]")
        elif st and len(st) > 80:
            # Also check long fragments (e.g. 80-char chunks)
            chunk = st[:80]
            if chunk in text:
                text = text.replace(chunk, f"[REDACTED_SENSITIVE_CHUNK len={len(chunk)}]")

    # 6. Heuristic resume block redaction for large unstructured blocks
    if len(text) > 80 and len(RESUME_HEADER_REGEX.findall(text)) >= 2:
        # Detected multiple resume section headers in the log line
        text = f"[REDACTED_RESUME_CONTENT len={len(text)}]"

    return text


class RequestIdFilter(logging.Filter):
    """
    Logging filter that extracts or generates a request ID and attaches
    it as `record.request_id` to every LogRecord for correlation tracing (#301).
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_request_id()
        return True


class SensitiveDataRedactionFilter(logging.Filter):
    """
    Logging filter that intercepts all log output and scrubs resume text,
    job description text, emails, and phone numbers before formatting (#301).
    Ensures raw candidate personal details never appear in console or file logs.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Render message with arguments safely
            raw_msg = record.getMessage()
            clean_msg = redact_text(raw_msg)
            record.msg = clean_msg
            record.args = ()

            # Also scrub exception tracebacks if present
            if record.exc_text:
                record.exc_text = redact_text(record.exc_text)
        except Exception:
            pass
        return True


class StructuredKeyValueFormatter(logging.Formatter):
    """
    Formats log records in structured key=value format (#301):
    timestamp="2026-11-10T12:00:00.000Z" level=INFO request_id="<uuid>" logger="<name>" message="<msg>"
    """
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        level = record.levelname
        req_id = getattr(record, "request_id", "-")
        logger_name = record.name
        msg = record.getMessage()

        # Sanitize double quotes for key=value format
        escaped_msg = msg.replace('"', '\\"').replace("\n", " ")
        output = f'timestamp="{timestamp}" level={level} request_id="{req_id}" logger="{logger_name}" message="{escaped_msg}"'

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            escaped_exc = record.exc_text.replace('"', '\\"').replace("\n", "\\n")
            output += f' exc_info="{escaped_exc}"'

        return output


class StructuredJsonFormatter(logging.Formatter):
    """
    Formats log records as structured, single-line JSON objects (#301).
    """
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        payload = {
            "timestamp": timestamp,
            "level": record.levelname,
            "request_id": getattr(record, "request_id", "-"),
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, ensure_ascii=False)


class StandardTextFormatter(logging.Formatter):
    """
    Human-readable text formatter carrying correlation request ID (#301):
    %(asctime)s [%(levelname)s] [req_id=%(request_id)s] %(name)s: %(message)s
    """
    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] [req_id=%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


def configure_logging(
    app: Any = None,
    log_level: Optional[str] = None,
    log_format: Optional[str] = None
) -> None:
    """
    Configures application-wide logging once with structured formatters,
    request correlation ID filters, and sensitive data redaction (#301).
    Controls log level via LOG_LEVEL environment variable or parameter.
    """
    import config

    # 1. Determine log level
    level_str = (
        log_level
        or os.getenv("LOG_LEVEL")
        or getattr(config, "LOG_LEVEL", "INFO")
    ).upper().strip()

    numeric_level = getattr(logging, level_str, logging.INFO)

    # 2. Determine formatter style
    format_style = (
        log_format
        or os.getenv("LOG_FORMAT")
        or getattr(config, "LOG_FORMAT", "key_value")
    ).lower().strip()

    if format_style in ("json", "structured_json"):
        formatter = StructuredJsonFormatter()
    elif format_style in ("text", "plain", "standard"):
        formatter = StandardTextFormatter()
    else:
        # Default: key=value structured formatter
        formatter = StructuredKeyValueFormatter()

    # 3. Setup console handler with filters
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(SensitiveDataRedactionFilter())

    # 4. Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing StreamHandlers to avoid duplicate log emissions
    for existing_h in list(root_logger.handlers):
        if isinstance(existing_h, logging.StreamHandler):
            root_logger.removeHandler(existing_h)

    root_logger.addHandler(handler)

    # 5. Configure Flask app logger if provided
    if app is not None:
        app.logger.setLevel(numeric_level)
        for h in list(app.logger.handlers):
            app.logger.removeHandler(h)
        app.logger.addHandler(handler)
