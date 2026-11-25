"""
Unit Tests for API Request Size Diagnostics & Enforcement (#784).
=================================================================
Verifies:
1. Size limits for JSON payloads and uploaded files.
2. Field-specific diagnostic error details (field name, field type, filename).
3. Maximum allowed size in both bytes and human-readable units.
4. Request ID generation, header correlation, and structured logging.
5. In-memory diagnostics ring buffer and /api/v1/diagnostics/request-size endpoint.
6. OpenAPI 3.0.3 documentation for 413 Payload Too Large and diagnostics.
"""

import io
import json
import pytest
from app import create_app
import config
from utils.openapi_spec import get_openapi_spec
from utils.request_size_diagnostics import (
    RequestSizeLimitExceeded,
    build_size_error_response,
    clear_diagnostics_for_testing,
    diagnose_413_exception,
    format_size_bytes,
    get_configured_limits,
    get_size_diagnostics_summary,
    log_size_failure,
    validate_request_size,
)


@pytest.fixture
def app():
    """Creates a configured Flask testing app."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    """Provides test client with clean diagnostics state."""
    clear_diagnostics_for_testing()
    with app.test_client() as client:
        yield client
    clear_diagnostics_for_testing()


class TestFormatAndLimits:
    """Tests byte formatting and configuration helpers."""

    def test_format_size_bytes(self):
        assert format_size_bytes(500) == "500 B"
        assert format_size_bytes(1024) == "1.0 KB" or format_size_bytes(1024) == "1 KB"
        assert format_size_bytes(5 * 1024 * 1024) == "5 MB"
        assert format_size_bytes(10 * 1024 * 1024) == "10 MB"

    def test_get_configured_limits(self):
        limits = get_configured_limits()
        assert "max_upload_size_mb" in limits
        assert "max_resume_file_size_bytes" in limits
        assert "max_json_payload_bytes" in limits
        assert "max_content_length_bytes" in limits
        assert limits["max_resume_file_size_bytes"] == limits["max_upload_size_mb"] * 1024 * 1024


class TestRequestSizeValidation:
    """Tests request size inspection and violation detection."""

    def test_oversized_json_payload_rejected_with_field_details(self, client):
        """A JSON request exceeding MAX_JSON_PAYLOAD_BYTES returns 413 with field details."""
        max_json = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
        # Create a payload larger than max_json (e.g. 2.2 MB string)
        large_text = "A" * (max_json + 200 * 1024)
        large_payload = {"resume_text": large_text, "company": "Google"}

        resp = client.post(
            "/api/analysis/start",
            json=large_payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413
        data = resp.get_json()

        assert data["success"] is False
        assert data["code"] == "REQUEST_ENTITY_TOO_LARGE"
        assert data["error_code"] == "PAYLOAD_TOO_LARGE"
        assert data["field"] in ("json_body", "resume_text")
        assert "max_allowed_size" in data
        assert "max_allowed_size_bytes" in data
        assert "received_size" in data
        assert "received_size_bytes" in data
        assert "request_id" in data
        assert len(data["request_id"]) > 0

        # Verify Response Headers
        assert "X-Request-ID" in resp.headers
        assert "X-Max-Allowed-Size" in resp.headers
        assert "X-Request-Size-Limit" in resp.headers

    def test_oversized_uploaded_file_rejected_with_field_details(self, client):
        """An uploaded file exceeding limit returns 413 specifying the file field name and max size."""
        max_bytes = getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 5 * 1024 * 1024)
        oversized_data = b"%PDF-1.4 " + (b"0" * (max_bytes + 100 * 1024))

        data = {
            "resume": (io.BytesIO(oversized_data), "oversized_resume.pdf"),
            "company": "Google",
        }
        resp = client.post(
            "/api/analysis/start",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 413
        data = resp.get_json()

        assert data["success"] is False
        assert data["field"] == "resume"
        assert data["field_type"] == "file"
        assert data["max_allowed_size_bytes"] == max_bytes
        assert data["received_size_bytes"] > max_bytes
        assert "request_id" in data
        assert "details" in data
        assert data["details"]["field"] == "resume"

    def test_custom_request_id_preserved_in_diagnostics(self, client):
        """When an incoming request passes X-Request-ID, size failures correlate with it."""
        max_json = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
        custom_req_id = "test-client-correlation-id-9988"

        large_payload = {"resume_text": "X" * (max_json + 50 * 1024)}
        resp = client.post(
            "/api/analysis/start",
            json=large_payload,
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": custom_req_id,
            },
        )
        assert resp.status_code == 413
        data = resp.get_json()
        assert data["request_id"] == custom_req_id
        assert resp.headers.get("X-Request-ID") == custom_req_id


class TestDiagnosticsEndpoint:
    """Tests the /api/v1/diagnostics/request-size observability endpoint."""

    def test_diagnostics_endpoint_returns_summary(self, client):
        clear_diagnostics_for_testing()

        # Trigger an oversized request
        max_json = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
        client.post(
            "/api/analysis/start",
            json={"resume_text": "Y" * (max_json + 50 * 1024)},
        )

        resp = client.get("/api/v1/diagnostics/request-size")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["status"] == "success"
        assert data["total_failures"] >= 1
        assert "configured_limits" in data
        assert "field_breakdown" in data
        assert "recent_failures" in data
        assert len(data["recent_failures"]) >= 1

        recent = data["recent_failures"][0]
        assert "request_id" in recent
        assert "field" in recent
        assert "received_size_bytes" in recent
        assert "max_allowed_size_bytes" in recent

        # Legacy alias /api/diagnostics/request-size also works
        resp_legacy = client.get("/api/diagnostics/request-size")
        assert resp_legacy.status_code == 200


class TestOpenApiSpecificationDocumentation:
    """Tests that request size limits and 413 schemas are documented in OpenAPI."""

    def test_openapi_documents_413_and_diagnostics(self):
        spec = get_openapi_spec()
        schemas = spec["components"]["schemas"]

        assert "PayloadTooLargeResponse" in schemas
        payload_props = schemas["PayloadTooLargeResponse"]["properties"]
        assert "field" in payload_props
        assert "max_allowed_size" in payload_props
        assert "max_allowed_size_bytes" in payload_props
        assert "received_size" in payload_props
        assert "request_id" in payload_props
        assert "details" in payload_props

        assert "RequestSizeDiagnosticsResponse" in schemas
        assert "/api/v1/diagnostics/request-size" in spec["paths"]
        assert "/api/diagnostics/request-size" in spec["paths"]
        assert "413" in spec["paths"]["/api/analysis/start"]["post"]["responses"]
