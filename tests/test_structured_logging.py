"""
Unit and integration tests for Structured Logging, Request Tracing, and Sensitive Content Redaction (#301).

Verifies:
1. Every log line emitted during a request carries the exact request ID.
2. Resume content, job description content, email addresses, and phone numbers never leak into logs.
3. Log levels are configurable via parameter and LOG_LEVEL environment variable.
4. Redaction filter handles emails, phone numbers, labeled resume/JD text, and registered texts.
5. Structured Key-Value, JSON, and standard text formatters format records with correlation request ID.
6. End-to-end resume upload test asserts zero sensitive details appear in captured logs.
"""

import io
import json
import logging
import pytest
from unittest.mock import patch

from app import app
import config
from utils.logger_config import (
    RequestIdFilter,
    SensitiveDataRedactionFilter,
    StructuredKeyValueFormatter,
    StructuredJsonFormatter,
    StandardTextFormatter,
    configure_logging,
    get_current_request_id,
    set_current_request_id,
    register_sensitive_text,
    clear_sensitive_texts,
    redact_text,
)


# ==============================================================================
# 1. Request ID Correlation Tracing
# ==============================================================================

def test_request_id_attached_to_every_log_line():
    """Verify that every log line emitted during an HTTP request carries the matching request ID."""
    custom_trace_id = "trace-uuid-abcdef-12345"

    log_stream = io.StringIO()
    test_handler = logging.StreamHandler(log_stream)
    test_handler.setFormatter(StructuredKeyValueFormatter())
    test_handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.addHandler(test_handler)

    try:
        with app.test_client() as client:
            res = client.get("/", headers={"X-Request-ID": custom_trace_id})
            assert res.status_code == 200
            assert res.headers.get("X-Request-ID") == custom_trace_id

            # Emit log messages during the request
            test_logger = logging.getLogger("test_request_tracer")
            test_logger.info("Processing home request trace step 1")
            test_logger.info("Processing home request trace step 2")

            output = log_stream.getvalue()
            lines = [l for l in output.strip().split("\n") if "test_request_tracer" in l]
            assert len(lines) >= 2
            for line in lines:
                assert f'request_id="{custom_trace_id}"' in line
    finally:
        root_logger.removeHandler(test_handler)


def test_request_id_generated_automatically_when_absent():
    """Verify a unique request ID is generated when not supplied by client and attached to logs."""
    log_stream = io.StringIO()
    test_handler = logging.StreamHandler(log_stream)
    test_handler.setFormatter(StructuredKeyValueFormatter())
    test_handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.addHandler(test_handler)

    try:
        with app.test_client() as client:
            res = client.get("/")
            assert res.status_code == 200
            generated_id = res.headers.get("X-Request-ID")
            assert generated_id is not None
            assert len(generated_id) >= 10

            test_logger = logging.getLogger("test_auto_tracer")
            test_logger.info("Automatic ID message test")

            output = log_stream.getvalue()
            assert f'request_id="{generated_id}"' in output
    finally:
        root_logger.removeHandler(test_handler)


# ==============================================================================
# 2. Sensitive Data Redaction Filter
# ==============================================================================

def test_redaction_filter_scrubs_emails():
    """Verify email addresses are scrubbed and replaced with [REDACTED_EMAIL]."""
    text_with_emails = "Candidate contact: student.john_2026@university.edu and alt: hiring@techcorp.io."
    clean = redact_text(text_with_emails)
    assert "student.john_2026@university.edu" not in clean
    assert "hiring@techcorp.io" not in clean
    assert "[REDACTED_EMAIL]" in clean


def test_redaction_filter_scrubs_phone_numbers():
    """Verify phone numbers are scrubbed and replaced with [REDACTED_PHONE]."""
    test_phones = [
        "Call candidate at +1-555-123-4567 for interview.",
        "Mobile contact: (555) 234-5678 or 555-890-1234.",
        "Overseas phone: +91 9876543210 immediately.",
    ]
    for raw in test_phones:
        clean = redact_text(raw)
        assert "[REDACTED_PHONE]" in clean
        assert "555-123-4567" not in clean
        assert "9876543210" not in clean


def test_redaction_filter_scrubs_labeled_resume_and_jd():
    """Verify logs passing labeled resume or job description content are redacted with length recorded."""
    sample_content = "John Doe, Software Engineer with 4 years Python and AWS expertise."
    log_line = f'Analyzing candidate resume_text="{sample_content}"'

    clean = redact_text(log_line)
    assert sample_content not in clean
    assert "[REDACTED_RESUME" in clean
    assert f"len={len(sample_content)}" in clean

    sample_jd = "Looking for Senior Backend Developer with FastAPI and Postgres."
    jd_line = f"Matching against job_description='{sample_jd}'"
    clean_jd = redact_text(jd_line)
    assert sample_jd not in clean_jd
    assert "[REDACTED_JOB_DESCRIPTION" in clean_jd
    assert f"len={len(sample_jd)}" in clean_jd


def test_redaction_filter_scrubs_registered_sensitive_texts():
    """Verify dynamically registered sensitive texts (e.g. extracted resume text) are scrubbed from logs."""
    sample_resume = (
        "ALICE SMITH - Full Stack Developer\n"
        "Education: Bachelor of Science in Computer Science, GPA: 3.95\n"
        "Experience: Architected high-throughput microservices using Golang and Kafka.\n"
        "Projects: Built distributed cache with consistent hashing."
    )

    register_sensitive_text(sample_resume)
    try:
        log_msg = f"Coordinator received: {sample_resume} from file parser."
        clean = redact_text(log_msg)
        assert sample_resume not in clean
        assert "[REDACTED_SENSITIVE_CONTENT" in clean or "[REDACTED_RESUME" in clean
        assert "ALICE SMITH" not in clean
        assert "GPA: 3.95" not in clean
    finally:
        clear_sensitive_texts()


def test_redaction_filter_heuristic_resume_detection():
    """Verify unstructured multi-section resume text is detected by heuristics and redacted."""
    raw_resume_block = (
        "Curriculum Vitae\n"
        "Education: B.Tech in Computer Engineering\n"
        "Work Experience: Intern at GlobalTech, developed REST APIs in Flask\n"
        "Technical Skills: Python, Docker, PostgreSQL\n"
        "Projects: Placement readiness assistant"
    )

    clean = redact_text(raw_resume_block)
    assert "GlobalTech" not in clean
    assert "B.Tech in Computer Engineering" not in clean
    assert "[REDACTED_RESUME" in clean


# ==============================================================================
# 3. End-to-End Resume Upload Redaction Assertion
# ==============================================================================

def test_resume_upload_and_analysis_never_leaks_sensitive_content_to_logs(mock_gemini_client, sample_coordinator_json):
    """
    Acceptance Criteria: Test with a sample resume to assert that resume text,
    job description text, emails, and phone numbers never appear in log output.
    """
    mock_gemini_client(payload=sample_coordinator_json)

    sample_resume_text = (
        "Robert Johnson\n"
        "Email: robert.johnson_test99@example.edu\n"
        "Phone: +1-555-876-5432\n"
        "Education: Master of Science in Artificial Intelligence, Stanford University, GPA 3.9\n"
        "Professional Experience: Senior Cloud Architect at SiliconTech Solutions\n"
        "Technical Skills: Python, PyTorch, Kubernetes, GCP Cloud Spanner"
    )

    sample_jd_text = (
        "Seeking Principal Software Engineer specializing in low-latency distributed storage."
    )

    log_stream = io.StringIO()
    test_handler = logging.StreamHandler(log_stream)
    test_handler.setFormatter(StructuredKeyValueFormatter())
    test_handler.addFilter(RequestIdFilter())
    test_handler.addFilter(SensitiveDataRedactionFilter())

    root_logger = logging.getLogger()
    root_logger.addHandler(test_handler)

    try:
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "test_logging_student"

            res = client.post(
                "/analyze",
                data={
                    "resume_text": sample_resume_text,
                    "company": "Google",
                    "job_description": sample_jd_text,
                },
                headers={"X-Request-ID": "upload-trace-id-999"},
                follow_redirects=True,
            )
            assert res.status_code == 200

            # Inspect all captured logs
            captured_logs = log_stream.getvalue()

            # 1. Request ID must be present on logs
            assert 'request_id="upload-trace-id-999"' in captured_logs

            # 2. Candidate sensitive PII must NOT appear in raw form
            assert "robert.johnson_test99@example.edu" not in captured_logs
            assert "555-876-5432" not in captured_logs
            assert "SiliconTech Solutions" not in captured_logs
            assert "Stanford University, GPA 3.9" not in captured_logs

            # 3. Job description content must NOT appear in raw form
            assert "low-latency distributed storage" not in captured_logs
    finally:
        root_logger.removeHandler(test_handler)


# ==============================================================================
# 4. Configurable Log Levels
# ==============================================================================

def test_configurable_log_levels(monkeypatch):
    """Verify log levels are configurable via parameter and LOG_LEVEL environment variable."""
    # 1. Test DEBUG level
    configure_logging(log_level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG

    # 2. Test ERROR level
    configure_logging(log_level="ERROR")
    assert logging.getLogger().level == logging.ERROR

    # 3. Test WARNING level
    configure_logging(log_level="WARNING")
    assert logging.getLogger().level == logging.WARNING

    # 4. Test environment variable fallback
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    assert logging.getLogger().level == logging.DEBUG

    # Reset back to INFO
    configure_logging(log_level="INFO")
    assert logging.getLogger().level == logging.INFO


# ==============================================================================
# 5. Structured Formatters
# ==============================================================================

def test_structured_key_value_formatter():
    """Verify Key-Value formatter outputs timestamp, level, request_id, logger, and message."""
    formatter = StructuredKeyValueFormatter()
    record = logging.LogRecord(
        name="auth_service",
        level=logging.INFO,
        pathname="auth.py",
        lineno=42,
        msg="User authenticated successfully.",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-test-key-value"

    formatted = formatter.format(record)
    assert 'level=INFO' in formatted
    assert 'request_id="req-test-key-value"' in formatted
    assert 'logger="auth_service"' in formatted
    assert 'message="User authenticated successfully."' in formatted
    assert 'timestamp="' in formatted


def test_structured_json_formatter():
    """Verify JSON formatter outputs valid single-line JSON with all correlation keys."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="payment_service",
        level=logging.WARNING,
        pathname="pay.py",
        lineno=108,
        msg="Payment gateway latency high: 1200ms",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-test-json-uuid"

    formatted = formatter.format(record)
    data = json.loads(formatted)
    assert data["level"] == "WARNING"
    assert data["request_id"] == "req-test-json-uuid"
    assert data["logger"] == "payment_service"
    assert data["message"] == "Payment gateway latency high: 1200ms"
    assert "timestamp" in data


def test_standard_text_formatter():
    """Verify Standard text formatter carries [req_id=...] in log format."""
    formatter = StandardTextFormatter()
    record = logging.LogRecord(
        name="db_pool",
        level=logging.INFO,
        pathname="db.py",
        lineno=15,
        msg="Connection pool healthy.",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-text-trace-555"

    formatted = formatter.format(record)
    assert "[req_id=req-text-trace-555]" in formatted
    assert "[INFO]" in formatted
    assert "db_pool: Connection pool healthy." in formatted
