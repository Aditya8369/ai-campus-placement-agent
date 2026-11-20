"""
Automated Unit Tests for Sentry Error Monitoring and Personal Data Scrubbing (#562).

Validates:
1. Without SENTRY_DSN nothing is sent and nothing breaks.
2. A test event built from a request with resume text contains no resume text, cookies, or email.
3. Unhandled exceptions are reported with route and release information.
4. Exception message values, breadcrumbs, and contexts have PII and sensitive candidate fields scrubbed.
5. Events are tagged strictly and only with `release`, `route`, and `request_id`.
6. create_app() application factory initialization and Sentry configuration.
"""

import pytest
import os
from typing import Dict, Any, List
from unittest.mock import patch

from flask import Flask, request, g
from utils.sentry_integration import (
    init_sentry,
    close_sentry,
    is_sentry_enabled,
    capture_exception,
    scrub_sentry_event,
    scrub_sentry_breadcrumb,
    scrub_text,
    deep_scrub,
    SENTRY_AVAILABLE,
)
from app import create_app, app as global_app


@pytest.fixture(autouse=True)
def cleanup_sentry():
    """Ensure Sentry is closed and cleaned up before and after every test."""
    close_sentry()
    yield
    close_sentry()


class TestSentryDisabledWithoutDSN:
    """Acceptance Criterion 1: Without SENTRY_DSN nothing is sent and nothing breaks."""

    def test_init_sentry_without_dsn_returns_false(self):
        with patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False):
            result = init_sentry(dsn="")
            assert result is False
            assert not is_sentry_enabled()

    def test_capture_exception_noop_when_disabled(self):
        close_sentry()
        assert not is_sentry_enabled()
        result = capture_exception(ValueError("Simulated unhandled failure"))
        assert result is None

    def test_app_serves_requests_cleanly_when_sentry_disabled(self):
        close_sentry()
        with global_app.test_client() as client:
            resp = client.get("/healthz")
            assert resp.status_code in (200, 404, 503)  # Standard response without secondary crash


class TestSentryEventScrubbing:
    """Acceptance Criterion 2: A test event built from a request with resume text contains no resume text, cookies or email."""

    def test_scrub_event_removes_request_body_cookies_and_pii(self):
        raw_resume = (
            "Alex Chen - Software Engineer\n"
            "Email: alex.chen@stanford.edu | Phone: +1 (555) 234-5678\n"
            "Education: BS in Computer Science, Stanford University\n"
            "Experience: Built scalable microservices in Python, Flask, and PostgreSQL."
        )
        candidate_email = "alex.chen@stanford.edu"
        candidate_phone = "+1 (555) 234-5678"

        test_event: Dict[str, Any] = {
            "request": {
                "url": "http://localhost:5000/api/analyze",
                "method": "POST",
                "headers": {
                    "User-Agent": "Mozilla/5.0 TestBrowser",
                    "Authorization": "Bearer secret_jwt_token_12345",
                    "Cookie": "session=sess_abcdef9876; auth_session_token=tok_456",
                    "X-Auth-Token": "internal_secret_token",
                    "X-Request-ID": "req-fixed-id-1234",
                },
                "data": {
                    "resume": raw_resume,
                    "job_description": "We are seeking a Backend Engineer with Python experience.",
                    "student_email": candidate_email,
                },
                "cookies": {
                    "session": "sess_abcdef9876",
                    "auth_token": "secret_cookie",
                },
                "env": {
                    "HTTP_AUTHORIZATION": "Bearer secret_jwt_token_12345",
                    "HTTP_COOKIE": "session=sess_abcdef9876",
                    "SERVER_NAME": "localhost",
                },
                "query_string": f"candidate={candidate_email}&ref=portal",
            },
            "user": {
                "id": "student_999",
                "email": candidate_email,
                "phone": candidate_phone,
                "username": "alexchen",
            },
            "extra": {
                "resume_preview": raw_resume[:80],
                "student_notes": f"Candidate contact is {candidate_email} and {candidate_phone}",
                "jd_summary": "Looking for Python / Flask expertise",
                "unrelated_metric": 42,
            },
            "contexts": {
                "state": {"session_user": candidate_email},
                "runtime": {"name": "CPython", "version": "3.14.2"},
            },
            "breadcrumbs": {
                "values": [
                    {
                        "type": "http",
                        "message": f"Submitting analysis for {candidate_email}",
                        "data": {"resume_snippet": raw_resume[:40]},
                    }
                ]
            },
            "exception": {
                "values": [
                    {
                        "type": "ValueError",
                        "value": f"Failed to parse resume for {candidate_email} at +1 (555) 234-5678",
                    }
                ]
            },
            "tags": {
                "environment": "production",
                "server_name": "worker-node-1",
                "arbitrary_tag": "leak_me",
            },
            "release": "ai-campus-placement-agent@1.0.0",
        }

        # Apply the Sentry scrubbing filter
        scrubbed = scrub_sentry_event(test_event)
        assert scrubbed is not None

        # 1. Request body and form data removed
        req = scrubbed.get("request", {})
        assert "data" not in req
        assert "cookies" not in req

        # 2. Authorization and session headers removed
        req_headers = req.get("headers", {})
        assert "Authorization" not in req_headers
        assert "authorization" not in req_headers
        assert "Cookie" not in req_headers
        assert "cookie" not in req_headers
        assert "X-Auth-Token" not in req_headers
        assert "x-auth-token" not in req_headers

        # 3. Environment variables cleaned
        req_env = req.get("env", {})
        assert "HTTP_AUTHORIZATION" not in req_env
        assert "HTTP_COOKIE" not in req_env

        # 4. User context removed completely
        assert "user" not in scrubbed

        # 5. Candidate PII redacted from query string, extra, breadcrumbs, and exceptions
        assert candidate_email not in req.get("query_string", "")
        extra = scrubbed.get("extra", {})
        assert extra.get("resume_preview") == "[SCRUBBED]"
        assert candidate_email not in extra.get("student_notes", "")
        assert candidate_phone not in extra.get("student_notes", "")
        assert "[REDACTED_EMAIL]" in extra.get("student_notes", "")
        assert "[REDACTED_PHONE]" in extra.get("student_notes", "")
        assert extra.get("unrelated_metric") == 42

        # 6. Breadcrumbs cleaned
        crumbs = scrubbed.get("breadcrumbs", {}).get("values", [])
        assert len(crumbs) == 1
        assert "data" not in crumbs[0]
        assert candidate_email not in crumbs[0]["message"]
        assert "[REDACTED_EMAIL]" in crumbs[0]["message"]

        # 7. Exception value cleaned
        exc_val = scrubbed.get("exception", {}).get("values", [])[0]["value"]
        assert candidate_email not in exc_val
        assert candidate_phone not in exc_val
        assert "[REDACTED_EMAIL]" in exc_val
        assert "[REDACTED_PHONE]" in exc_val

        # 8. Event tags strictly limited to release, route, and request_id
        tags = scrubbed.get("tags", {})
        assert set(tags.keys()) == {"release", "route", "request_id"}
        assert tags["release"] == "ai-campus-placement-agent@1.0.0"
        assert tags["route"] == "unknown"  # Non-request context fallback
        assert "environment" not in tags
        assert "server_name" not in tags
        assert "arbitrary_tag" not in tags


class TestUnhandledExceptionReporting:
    """Acceptance Criterion 3: Unhandled exceptions are reported with route and release information."""

    def test_unhandled_exception_captures_route_and_release(self):
        if not SENTRY_AVAILABLE:
            pytest.skip("sentry-sdk is not installed")

        captured_events: List[Dict[str, Any]] = []

        def test_capture_callback(event: Dict[str, Any], hint: Any) -> Dict[str, Any]:
            scrubbed = scrub_sentry_event(event, hint)
            if scrubbed:
                captured_events.append(scrubbed)
            return scrubbed

        # Initialize mock Sentry with custom DSN and test capture callback
        test_release = "ai-campus-placement-agent@2.5.0-test"
        init_sentry(
            dsn="https://public_key@sentry.example.com/999",
            release=test_release,
            environment="test_env",
        )

        test_app = Flask("test_sentry_app")
        test_app.config["TESTING"] = True

        @test_app.before_request
        def before_req():
            g.request_id = "req-unhandled-trace-555"

        @test_app.route("/crash-simulation", methods=["POST"])
        def crash_route():
            resume_data = request.form.get("resume")
            raise RuntimeError(f"Processing failed for resume: {resume_data}")

        # Override before_send with our monitoring callback
        import sentry_sdk
        client = sentry_sdk.get_client()
        client.options["before_send"] = test_capture_callback

        with test_app.test_client() as client:
            try:
                client.post(
                    "/crash-simulation",
                    data={"resume": "Sensitive Resume Details", "email": "leak@college.edu"},
                    headers={"X-Request-ID": "req-unhandled-trace-555", "Cookie": "session=xyz"},
                )
            except RuntimeError:
                pass  # In testing, Flask may bubble the exception

        assert len(captured_events) >= 1
        event = captured_events[0]

        # Verify route and release tags
        assert "tags" in event
        tags = event["tags"]
        assert tags["route"] == "/crash-simulation"
        assert tags["release"] == test_release
        assert tags["request_id"] == "req-unhandled-trace-555"
        assert set(tags.keys()) == {"release", "route", "request_id"}

        # Verify request body and cookie scrubbing
        req = event.get("request", {})
        assert "data" not in req
        assert "cookies" not in req
        assert "leak@college.edu" not in str(event)


class TestAppFactoryIntegration:
    """Validates app factory create_app() with optional Sentry configuration."""

    def test_create_app_without_dsn_leaves_sentry_disabled(self):
        close_sentry()
        app_instance = create_app({"TESTING": True, "SENTRY_DSN": ""})
        assert app_instance is not None
        assert not is_sentry_enabled()

    def test_create_app_with_dsn_initializes_sentry(self):
        if not SENTRY_AVAILABLE:
            pytest.skip("sentry-sdk is not installed")

        app_instance = create_app({
            "TESTING": True,
            "SENTRY_DSN": "https://pubkey@sentry.example.com/123",
            "SENTRY_RELEASE": "ai-campus-placement-agent@test-factory",
        })
        assert app_instance is not None
        assert is_sentry_enabled()


class TestScrubbingHelpers:
    """Validates helper functions for text and breadcrumb redaction."""

    def test_scrub_text_redacts_emails_and_phone_numbers(self):
        raw = "Contact recruiter at hr@techcorp.com or student at candidate.123@nitk.edu.in, tel: +91 9876543210"
        scrubbed = scrub_text(raw)
        assert "hr@techcorp.com" not in scrubbed
        assert "candidate.123@nitk.edu.in" not in scrubbed
        assert "9876543210" not in scrubbed
        assert "[REDACTED_EMAIL]" in scrubbed
        assert "[REDACTED_PHONE]" in scrubbed

    def test_deep_scrub_nested_structures(self):
        data = {
            "resume_content": "Extracted text of resume",
            "metadata": {
                "job_description_raw": "Seeking SDE 1",
                "candidate_phone": "1234567890",
                "clean_field": "Normal value",
                "student_email": "test@gmail.com",
                "general_notes": "Contact: mentor@gmail.com",
            },
            "items": ["safe_string", "user@domain.com", {"jd_text": "Requirements"}],
        }
        cleaned = deep_scrub(data)
        assert cleaned["resume_content"] == "[SCRUBBED]"
        assert cleaned["metadata"]["job_description_raw"] == "[SCRUBBED]"
        assert cleaned["metadata"]["candidate_phone"] == "[SCRUBBED]"
        assert cleaned["metadata"]["clean_field"] == "Normal value"
        assert cleaned["metadata"]["student_email"] == "[SCRUBBED]"
        assert "[REDACTED_EMAIL]" in cleaned["metadata"]["general_notes"]
        assert cleaned["items"][1] == "[REDACTED_EMAIL]"
        assert cleaned["items"][2]["jd_text"] == "[SCRUBBED]"

    def test_scrub_sentry_breadcrumb(self):
        crumb = {
            "type": "http",
            "message": "Fetched candidate record for student@test.com",
            "data": {"resume": "binary payload", "status_code": 200},
        }
        cleaned = scrub_sentry_breadcrumb(crumb)
        assert cleaned is not None
        assert "data" not in cleaned
        assert "student@test.com" not in cleaned["message"]
        assert "[REDACTED_EMAIL]" in cleaned["message"]


class TestReadmeDocumentation:
    """Acceptance Criterion 4: The README lists exactly what is and is not sent."""

    def test_readme_lists_what_is_and_is_not_sent(self):
        readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
        assert os.path.exists(readme_path)
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check Sentry section presence
        assert "SENTRY_DSN" in content
        assert "before_send" in content

        # Check 'What is NOT Sent' documentation
        assert "Exactly What is NOT Sent" in content
        assert "Request bodies & Form Data" in content
        assert "Cookies & Session Tokens" in content
        assert "Authorization Headers" in content
        assert "Personal Identifiable Information" in content

        # Check 'What IS Sent' documentation
        assert "Exactly What IS Sent" in content
        assert "Release Version" in content
        assert "Route / URL Rule" in content
        assert "Request Correlation ID" in content
        assert "Sanitized Exception & Stack Trace" in content

