"""
Unit Tests for API Field and Route Deprecation Headers & Metrics (#445, #553).
==============================================================================
Tests verify:
1. Deprecated field detection in JSON request payloads.
2. Deprecated field detection in query parameters and form data.
3. Standardized RFC 8594 Sunset and Deprecation HTTP response headers.
4. X-API-Deprecated-Fields, X-API-Replacement, X-API-Removal-Date, and X-API-Deprecation-Notice.
5. Legacy unversioned route deprecation headers pointing to canonical v1 endpoints.
6. Recording of deprecated API usage in the SQLite deprecated_api_metrics table.
7. Deprecation metrics summary retrieval and /api/v1/metrics/deprecation endpoint.
8. OpenAPI 3.0.3 specification documenting deprecated fields and headers.
"""

import json
import pytest
from app import create_app
from utils.api_deprecation import (
    DEFAULT_SUNSET_DATE_ISO,
    DEFAULT_SUNSET_DATE_RFC,
    DEPRECATED_FIELDS,
    detect_deprecated_fields,
    get_deprecated_metrics_summary,
    get_field_deprecation_info,
    get_route_deprecation_info,
    reset_metrics_for_testing,
)
from utils.database import get_db_connection
from utils.openapi_spec import get_openapi_spec


@pytest.fixture
def app():
    """Creates a configured test application instance."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    """Provides a Flask test client with clean metrics state."""
    reset_metrics_for_testing()
    with app.test_client() as client:
        yield client
    reset_metrics_for_testing()


class TestFieldDeprecationCatalog:
    """Verifies the static deprecation catalog configuration."""

    def test_catalog_contains_expected_deprecated_fields(self):
        expected_fields = [
            "company",
            "role",
            "role_id",
            "selected_role",
            "input_mode",
            "cover_letter",
            "batch_companies",
            "resume_analysis_id",
            "notes",
            "tags",
        ]
        for f in expected_fields:
            assert f in DEPRECATED_FIELDS, f"Expected '{f}' to be registered in DEPRECATED_FIELDS"
            entry = DEPRECATED_FIELDS[f]
            assert "replacement" in entry
            assert "removal_date" in entry
            assert entry["removal_date"] == DEFAULT_SUNSET_DATE_ISO
            assert entry["removal_date_rfc"] == DEFAULT_SUNSET_DATE_RFC

    def test_get_field_deprecation_info_endpoint_matching(self):
        # 'company' is deprecated on /api/v1/analysis/start
        info = get_field_deprecation_info("company", "/api/v1/analysis/start")
        assert info is not None
        assert info["replacement"] == "company_name"

        # Non-deprecated field returns None
        assert get_field_deprecation_info("valid_field", "/api/v1/analysis/start") is None

    def test_detect_deprecated_fields_helper(self):
        payload = {
            "company": "Google",
            "role": "Software Engineer",
            "resume_text": "Experienced Python developer",
        }
        detected = detect_deprecated_fields("/api/v1/analysis/start", payload)
        detected_names = {d["field"] for d in detected}
        assert "company" in detected_names
        assert "role" in detected_names
        assert "resume_text" not in detected_names


class TestFieldDeprecationHeaders:
    """Verifies HTTP headers injected when deprecated fields are submitted."""

    def test_json_post_with_deprecated_field_injects_headers(self, client):
        """Calling an endpoint with deprecated field 'cover_letter' injects deprecation headers."""
        resp = client.post(
            "/api/v1/cover-letter/download",
            json={
                "cover_letter": "Dear Hiring Team,\nI am applying for SDE-1.",
                "format": "txt",
                "company_name": "Google",
            },
        )
        assert resp.status_code == 200
        headers = resp.headers

        # RFC 8594 Headers
        assert headers.get("Deprecation") == "true"
        assert headers.get("Sunset") == DEFAULT_SUNSET_DATE_RFC
        assert "Link" in headers

        # Custom Deprecation Guidance Headers
        assert "cover_letter" in headers.get("X-API-Deprecated-Fields", "")
        assert "content" in headers.get("X-API-Replacement", "")
        assert headers.get("X-API-Removal-Date") == DEFAULT_SUNSET_DATE_ISO
        assert "scheduled for removal" in headers.get("X-API-Deprecation-Notice", "")

    def test_query_args_with_deprecated_field_injects_headers(self, client):
        """Passing deprecated query parameter 'role' injects deprecation headers."""
        resp = client.get("/api/v1/version?role=SoftwareEngineer")
        assert resp.status_code == 200
        headers = resp.headers

        assert headers.get("Deprecation") == "true"
        assert headers.get("Sunset") == DEFAULT_SUNSET_DATE_RFC
        assert "role" in headers.get("X-API-Deprecated-Fields", "")
        assert "target_role" in headers.get("X-API-Replacement", "")
        assert headers.get("X-API-Removal-Date") == DEFAULT_SUNSET_DATE_ISO

    def test_clean_request_without_deprecated_fields_has_no_field_deprecation_headers(self, client):
        """A canonical v1 request with modern fields does not receive field deprecation headers."""
        resp = client.get("/api/v1/version")
        assert resp.status_code == 200
        headers = resp.headers

        # Canonical v1 route has no Deprecation header
        assert "Deprecation" not in headers
        assert "Sunset" not in headers
        assert "X-API-Deprecated-Fields" not in headers
        assert "X-API-Replacement" not in headers


class TestRouteDeprecationHeaders:
    """Verifies RFC 8594 deprecation headers on unversioned legacy routes."""

    def test_legacy_unversioned_route_injects_deprecation_and_successor_link(self, client):
        """Calling legacy /api/version returns Deprecation, Sunset, and successor-version Link."""
        resp = client.get("/api/version")
        assert resp.status_code == 200
        headers = resp.headers

        assert headers.get("API-Version") == "legacy"
        assert headers.get("Deprecation") == "true"
        assert headers.get("Sunset") == DEFAULT_SUNSET_DATE_RFC
        assert 'rel="successor-version"' in headers.get("Link", "")
        assert "/api/v1/version" in headers.get("Link", "")

    def test_route_deprecation_info_helper(self):
        route_info = get_route_deprecation_info("/api/analyze")
        assert route_info is not None
        assert route_info["replacement"] == "/api/v1/analysis/start"
        assert route_info["removal_date"] == DEFAULT_SUNSET_DATE_ISO


class TestDeprecationMetricsTracking:
    """Verifies that deprecated API invocations are safely recorded in SQLite and queryable."""

    def test_deprecated_invocation_records_in_database(self, client):
        reset_metrics_for_testing()

        # Invoke endpoint with deprecated field
        client.post(
            "/api/v1/cover-letter/download",
            json={"cover_letter": "Sample cover letter text", "format": "txt"},
        )

        conn = get_db_connection()
        try:
            rows = conn.execute("SELECT * FROM deprecated_api_metrics WHERE item_type = 'field'").fetchall()
            assert len(rows) >= 1
            row = rows[0]
            assert row["item_name"] == "cover_letter"
            assert row["replacement"] == "content"
            assert "/cover-letter/download" in row["endpoint"]
        finally:
            conn.close()

    def test_metrics_summary_endpoint(self, client):
        reset_metrics_for_testing()

        # Trigger a field deprecation and a legacy route invocation
        client.get("/api/version")
        client.post(
            "/api/v1/cover-letter/download",
            json={"cover_letter": "Test content", "format": "txt"},
        )

        resp = client.get("/api/v1/metrics/deprecation")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["status"] == "success"
        assert data["total_deprecated_invocations"] >= 2
        assert data["field_deprecated_invocations"] >= 1
        assert data["route_deprecated_invocations"] >= 1
        assert isinstance(data["fields_summary"], list)
        assert isinstance(data["routes_summary"], list)
        assert isinstance(data["recent_invocations"], list)
        assert data["sunset_date"] == DEFAULT_SUNSET_DATE_ISO

        # Legacy alias /api/metrics/deprecation also works
        resp_legacy = client.get("/api/metrics/deprecation")
        assert resp_legacy.status_code == 200
        assert resp_legacy.headers.get("Deprecation") == "true"


class TestOpenApiDeprecationDocumentation:
    """Verifies that deprecated fields and headers are properly documented in OpenAPI 3.0.3."""

    def test_openapi_spec_marks_deprecated_fields(self):
        spec = get_openapi_spec()
        schemas = spec["components"]["schemas"]

        # AnalysisStartRequest has deprecated 'company' and 'role'
        analysis_props = schemas["AnalysisStartRequest"]["properties"]
        assert analysis_props["company"].get("deprecated") is True
        assert "DEPRECATED" in analysis_props["company"]["description"]
        assert "company_name" in analysis_props

        assert analysis_props["role"].get("deprecated") is True
        assert "target_role" in analysis_props

        assert analysis_props["input_mode"].get("deprecated") is True
        assert "analysis_mode" in analysis_props

        # JobApplicationCreateRequest has deprecated 'resume_analysis_id'
        job_props = schemas["JobApplicationCreateRequest"]["properties"]
        assert job_props["resume_analysis_id"].get("deprecated") is True
        assert "DEPRECATED" in job_props["resume_analysis_id"]["description"]
        assert "analysis_id" in job_props

    def test_openapi_spec_documents_headers_and_endpoints(self):
        spec = get_openapi_spec()
        headers = spec["components"]["headers"]

        # Standard deprecation headers documented
        assert "Deprecation" in headers
        assert "Sunset" in headers
        assert "Link" in headers
        assert "X-API-Deprecated-Fields" in headers
        assert "X-API-Replacement" in headers
        assert "X-API-Removal-Date" in headers
        assert "X-API-Deprecation-Notice" in headers

        # Metrics endpoints documented in paths
        assert "/api/v1/metrics/deprecation" in spec["paths"]
        assert "/api/metrics/deprecation" in spec["paths"]
