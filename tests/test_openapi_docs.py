"""
Test suite for OpenAPI 3.0.3 Documentation and Interactive Explorers (#410).

Verifies:
- GET /api/openapi.json delivers valid OpenAPI 3.0.3 specification payload.
- Important endpoint groups are documented (analysis, interview, applications, reports, account/security).
- GET /docs and GET /api/docs serve interactive Swagger UI viewer.
- GET /redoc serves Redoc reference viewer.
- Documentation routes are accessible publicly without requiring prior authentication.
"""

import pytest
from app import app
from utils.openapi_spec import get_openapi_spec, OPENAPI_SPEC


def test_openapi_spec_structure_and_metadata():
    """Verify OpenAPI 3.0.3 dictionary contains valid specification structure."""
    spec = get_openapi_spec()
    assert spec["openapi"] == "3.0.3"
    assert "info" in spec
    assert spec["info"]["title"] == "AI Campus Placement Agent API"
    assert spec["info"]["version"] == "1.0.0"
    assert "paths" in spec
    assert "components" in spec
    assert "schemas" in spec["components"]
    assert "securitySchemes" in spec["components"]


def test_openapi_spec_endpoint_coverage():
    """Ensure important core endpoints are thoroughly documented in paths."""
    spec = get_openapi_spec()
    paths = spec["paths"]

    # Analysis endpoints
    assert "/api/analysis/start" in paths
    assert "/api/analysis/status/{task_id}" in paths
    assert "/api/analysis/stream/{task_id}" in paths
    assert "/analyze" in paths
    assert "/api/analysis/{analysis_id}/skill-evidence" in paths
    assert "/api/analysis/batch-compare" in paths

    # Interview evaluation endpoints
    assert "/interview/{analysis_id}/submit" in paths
    assert "/api/interview/{analysis_id}/coding-problem" in paths
    assert "/api/interview/{analysis_id}/evaluate-code" in paths
    assert "/api/interview/evaluate-star" in paths
    assert "/api/interview/practice/topics" in paths
    assert "/api/interview-history" in paths

    # Job application tracking endpoints
    assert "/api/applications" in paths
    assert "get" in paths["/api/applications"]
    assert "post" in paths["/api/applications"]
    assert "/api/applications/{app_id}" in paths
    assert "/api/applications/{app_id}/status" in paths
    assert "/api/applications/stats" in paths
    assert "/api/applications/export" in paths

    # Reports and download endpoints
    assert "/download/{analysis_id}" in paths
    assert "/download/skills-gap/{analysis_id}" in paths
    assert "/download/interview-transcript/{analysis_id}" in paths
    assert "/download/preparation-summary" in paths

    # Preparation notes endpoints
    assert "/api/notes" in paths
    assert "/api/notes/{note_id}" in paths

    # Account and security endpoints
    assert "/login" in paths
    assert "/register" in paths
    assert "/logout" in paths
    assert "/api/session/status" in paths
    assert "/api/session/keep-alive" in paths
    assert "/api/session/logout" in paths
    assert "/api/auth/password-strength" in paths

    # System endpoints
    assert "/api/health" in paths
    assert "/api/walkthrough" in paths
    assert "/api/openapi.json" in paths


@pytest.fixture
def client():
    """Provides test client for OpenAPI endpoints."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_openapi_json_endpoint(client):
    """Verify GET /api/openapi.json returns 200 with JSON specification."""
    res = client.get("/api/openapi.json")
    assert res.status_code == 200
    assert res.is_json
    data = res.get_json()
    assert data["openapi"] == "3.0.3"
    assert data["info"]["title"] == "AI Campus Placement Agent API"
    assert len(data["paths"]) >= 25


def test_swagger_ui_endpoint(client):
    """Verify /docs and /api/docs render the interactive Swagger UI page."""
    for path in ["/docs", "/api/docs"]:
        res = client.get(path)
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "swagger-ui" in html
        assert "/api/openapi.json" in html
        assert "AI Campus Placement Agent" in html


def test_redoc_ui_endpoint(client):
    """Verify /redoc renders the Redoc API documentation viewer."""
    res = client.get("/redoc")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "<redoc" in html
    assert "/api/openapi.json" in html
