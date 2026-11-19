"""
Test suite for API Versioning & Backwards Compatibility Architecture (#445).

Verifies:
- URI versioning (/api/v1/...) is available across public and authenticated API endpoints.
- Legacy unversioned endpoints (/api/...) remain fully operational during the transition window.
- Standardized version and deprecation headers (API-Version, X-API-Version, Deprecation, Sunset, Link)
  are correctly injected into responses.
- Version discovery endpoint (/api/v1/version and /api/version) returns versioning metadata.
- Interactive documentation and OpenAPI specification are accessible under /api/v1/ routes.
- Future version registration (e.g. v2) operates safely without breaking existing v1 clients.
"""

import pytest
from flask import Blueprint, jsonify
from app import app
from utils.api_versioning import (
    CURRENT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    SUNSET_DATE_RFC,
    get_api_version_info,
    extract_api_version,
    to_versioned_path,
    register_api_version,
)


@pytest.fixture
def client():
    """Provides test client for versioning tests."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_version_info_structure():
    """Verify version information metadata structure and default settings."""
    info = get_api_version_info()
    assert info["status"] == "success"
    assert info["current_version"] == "v1"
    assert "v1" in info["supported_versions"]
    assert "sunset_date" in info
    assert "sunset_date_rfc" in info
    assert info["documentation_url"] == "/api/v1/docs"
    assert info["openapi_url"] == "/api/v1/openapi.json"
    assert "policy" in info
    assert "deprecation_header" in info["policy"]


def test_extract_api_version_helper():
    """Verify API version path extraction from various URI structures."""
    assert extract_api_version("/api/v1/health") == "v1"
    assert extract_api_version("/api/v1/applications") == "v1"
    assert extract_api_version("/api/v1/analysis/123/status") == "v1"
    assert extract_api_version("/api/health") == "legacy"
    assert extract_api_version("/api/applications") == "legacy"
    assert extract_api_version("/api/v2/applications") == "v2"
    assert extract_api_version("/api/v3/reports") == "v3"
    assert extract_api_version("/") is None
    assert extract_api_version("/login") is None
    assert extract_api_version("/static/css/main.css") is None


def test_to_versioned_path_helper():
    """Verify path transformation to versioned URI segments."""
    assert to_versioned_path("/api/health", "v1") == "/api/v1/health"
    assert to_versioned_path("/api/applications", "v1") == "/api/v1/applications"
    assert to_versioned_path("/api/v1/applications", "v2") == "/api/v2/applications"
    assert to_versioned_path("/non-api/path", "v1") == "/non-api/path"


def test_api_version_discovery_endpoints(client):
    """Verify GET /api/v1/version and GET /api/version deliver version discovery metadata."""
    res_v1 = client.get("/api/v1/version")
    assert res_v1.status_code == 200
    assert res_v1.is_json
    data_v1 = res_v1.get_json()
    assert data_v1["current_version"] == "v1"
    assert "v1" in data_v1["supported_versions"]
    assert res_v1.headers.get("API-Version") == "v1"
    assert res_v1.headers.get("X-API-Version") == "1.0"

    res_legacy = client.get("/api/version")
    assert res_legacy.status_code == 200
    assert res_legacy.is_json
    data_legacy = res_legacy.get_json()
    assert data_legacy["current_version"] == "v1"
    assert res_legacy.headers.get("API-Version") == "legacy"
    assert res_legacy.headers.get("Deprecation") == "true"
    assert res_legacy.headers.get("Sunset") == SUNSET_DATE_RFC
    assert "/api/v1/version" in res_legacy.headers.get("Link", "")


def test_versioned_health_and_headers(client):
    """Verify /api/v1/health emits v1 headers and /api/health emits RFC 8594 deprecation headers."""
    # Versioned endpoint
    res_v1 = client.get("/api/v1/health")
    assert res_v1.status_code == 200
    assert res_v1.is_json
    assert res_v1.headers.get("API-Version") == "v1"
    assert res_v1.headers.get("X-API-Version") == "1.0"

    # Legacy unversioned endpoint
    res_legacy = client.get("/api/health")
    assert res_legacy.status_code == 200
    assert res_legacy.is_json
    assert res_legacy.headers.get("API-Version") == "legacy"
    assert res_legacy.headers.get("Deprecation") == "true"
    assert res_legacy.headers.get("Sunset") == SUNSET_DATE_RFC
    assert 'rel="successor-version"' in res_legacy.headers.get("Link", "")
    assert "/api/v1/health" in res_legacy.headers.get("Link", "")


def test_versioned_public_endpoints_parity(client):
    """Verify public endpoints respond identically on both /api/v1/... and legacy /api/... paths."""
    # Walkthrough endpoint
    w_v1 = client.get("/api/v1/walkthrough")
    w_legacy = client.get("/api/walkthrough")
    assert w_v1.status_code == 200
    assert w_legacy.status_code == 200
    assert w_v1.get_json() == w_legacy.get_json()

    # Demo sample resume endpoint
    d_v1 = client.get("/api/v1/demo/sample-resume")
    d_legacy = client.get("/api/demo/sample-resume")
    assert d_v1.status_code == 200
    assert d_legacy.status_code == 200
    assert d_v1.get_json() == d_legacy.get_json()

    # Session status endpoint
    s_v1 = client.get("/api/v1/session/status")
    s_legacy = client.get("/api/session/status")
    assert s_v1.status_code == 200
    assert s_legacy.status_code == 200


def test_versioned_documentation_routes(client):
    """Verify Swagger UI, Redoc, and OpenAPI spec routes are served under /api/v1/."""
    # v1 OpenAPI JSON
    res_spec = client.get("/api/v1/openapi.json")
    assert res_spec.status_code == 200
    assert res_spec.is_json
    spec = res_spec.get_json()
    assert spec["openapi"] == "3.0.3"
    assert any(s["url"] == "/api/v1" for s in spec.get("servers", []))

    # v1 Swagger UI
    res_docs = client.get("/api/v1/docs")
    assert res_docs.status_code == 200
    assert b"SwaggerUIBundle" in res_docs.data
    assert b"/api/v1/openapi.json" in res_docs.data

    # v1 Redoc UI
    res_redoc = client.get("/api/v1/redoc")
    assert res_redoc.status_code == 200
    assert b"<redoc" in res_redoc.data
    assert b"/api/v1/openapi.json" in res_redoc.data


def test_future_version_registration():
    """Verify that a future API version (e.g. v2) can be registered without affecting v1."""
    from flask import Flask
    fresh_app = Flask("test_future_version_app")
    test_v2_bp = Blueprint("api_v2_test", __name__)

    @test_v2_bp.route("/ping", methods=["GET"])
    def v2_ping():
        return jsonify({"version": "v2", "message": "pong"}), 200

    register_api_version(fresh_app, version="v2", blueprint=test_v2_bp, url_prefix="/api/v2")

    assert "v2" in SUPPORTED_API_VERSIONS

    with fresh_app.test_client() as c:
        res_v2 = c.get("/api/v2/ping")
        assert res_v2.status_code == 200
        assert res_v2.get_json() == {"version": "v2", "message": "pong"}
