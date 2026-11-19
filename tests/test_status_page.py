"""
Automated Test Suite for Public System Status Page & Health Diagnostic API (#460).
===================================================================================
Verifies:
1. Overall system status computation ('operational', 'degraded', 'unavailable').
2. Application & Web Runtime health (storage writability, environment, uptime).
3. Database (SQLite) connectivity probe and query latency.
4. AI Integration (Google Gemini) configuration, client status, and demo fallback mode.
5. Strict secrets protection: zero exposure of API keys, tokens, or credentials.
6. Public availability of /status (HTML dashboard) and /api/status (JSON API).
7. Content negotiation: /status returning JSON when requested via Accept header or ?format=json.
8. Proper HTTP status codes (200 on operational/degraded, 503 on major service outage).
"""

import json
import pytest
from app import app
import config
from utils.status_service import (
    check_application_service,
    check_database_service,
    check_ai_service,
    get_system_status,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as test_client:
        yield test_client


def test_system_status_operational_when_all_services_healthy(monkeypatch):
    """Verify system status is 'operational' (HTTP 200) when all services are healthy."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "mock-valid-gemini-key-123456789")

    # Mock get_gemini_client to return a mock client object
    import utils.gemini as gemini_module
    class DummyClient:
        pass

    monkeypatch.setattr(gemini_module, "get_gemini_client", lambda timeout=None: DummyClient())

    payload, status_code = get_system_status()
    assert status_code == 200
    assert payload["status"] == "operational"
    assert "All Systems Operational" in payload["status_message"]
    assert "timestamp" in payload
    assert "response_time_ms" in payload

    services = payload["services"]
    assert "application" in services
    assert "database" in services
    assert "ai_integration" in services

    assert services["application"]["status"] == "operational"
    assert services["database"]["status"] == "operational"
    assert services["ai_integration"]["status"] == "operational"
    assert services["ai_integration"]["details"]["configured"] is True


def test_system_status_degraded_when_ai_key_unconfigured(monkeypatch):
    """Verify system status is 'degraded' (HTTP 200) with safe demo fallback when AI key is missing."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    payload, status_code = get_system_status()
    assert status_code == 200
    assert payload["status"] == "degraded"
    assert "Degraded" in payload["status_message"]

    ai_svc = payload["services"]["ai_integration"]
    assert ai_svc["status"] == "degraded"
    assert ai_svc["details"]["configured"] is False
    assert ai_svc["details"]["mode"] == "demo_fallback"
    assert ai_svc["details"]["fallback_available"] is True


def test_system_status_unavailable_when_database_fails(monkeypatch):
    """Verify system status is 'unavailable' (HTTP 503) when database connection fails."""
    import utils.status_service as status_service_module

    def broken_db_conn():
        raise RuntimeError("SQLite database file is locked or unavailable")

    monkeypatch.setattr(status_service_module, "get_db_connection", broken_db_conn)

    payload, status_code = get_system_status()
    assert status_code == 503
    assert payload["status"] == "unavailable"
    assert "Major Service Outage" in payload["status_message"]

    db_svc = payload["services"]["database"]
    assert db_svc["status"] == "unavailable"
    assert db_svc["details"]["connectivity"] == "disconnected"


def test_zero_secrets_exposure_in_status_response(monkeypatch):
    """Guarantees that sensitive API keys, secret credentials, and tokens are never leaked."""
    secret_key = "AIzaSySecretInternalProductionKey998877"
    monkeypatch.setattr(config, "GEMINI_API_KEY", secret_key)
    monkeypatch.setitem(app.config, "SECRET_KEY", "super-secret-session-signing-token")

    payload, _ = get_system_status()
    payload_str = json.dumps(payload)

    # Neither the raw key nor sensitive keywords should be exposed in the payload
    assert secret_key not in payload_str
    assert "super-secret-session-signing-token" not in payload_str
    assert "GEMINI_API_KEY" not in payload_str


def test_public_status_page_html_rendering(client):
    """Verify /status delivers an accessible, public HTML status dashboard with required sections."""
    res = client.get("/status")
    assert res.status_code in (200, 503)
    html = res.get_data(as_text=True)

    assert "System Status" in html
    assert "Core Application Services" in html
    assert "Application & Web Runtime" in html
    assert "Database (SQLite)" in html
    assert "AI Integration" in html
    assert "Refresh Status" in html
    assert "Zero Credentials Exposed" in html


def test_api_status_json_endpoint(client):
    """Verify GET /api/status returns valid JSON structure with standardized service statuses."""
    res = client.get("/api/status")
    assert res.status_code in (200, 503)
    assert res.is_json

    data = res.get_json()
    assert "status" in data
    assert data["status"] in ("operational", "degraded", "unavailable")
    assert "status_message" in data
    assert "timestamp" in data
    assert "response_time_ms" in data

    services = data.get("services", {})
    for svc_key in ("application", "database", "ai_integration"):
        assert svc_key in services
        assert "name" in services[svc_key]
        assert "status" in services[svc_key]
        assert services[svc_key]["status"] in ("operational", "degraded", "unavailable")
        assert "description" in services[svc_key]
        assert "details" in services[svc_key]


def test_status_page_content_negotiation(client):
    """Verify /status responds with JSON when requested via Accept header or ?format=json."""
    # Via Accept header
    res_header = client.get("/status", headers={"Accept": "application/json"})
    assert res_header.status_code in (200, 503)
    assert res_header.is_json
    data_header = res_header.get_json()
    assert "services" in data_header

    # Via ?format=json query param
    res_query = client.get("/status?format=json")
    assert res_query.status_code in (200, 503)
    assert res_query.is_json
    data_query = res_query.get_json()
    assert "services" in data_query


def test_api_v1_status_endpoint_alias(client):
    """Verify /api/v1/status acts as a versioned alias for /api/status."""
    res = client.get("/api/v1/status")
    assert res.status_code in (200, 503)
    assert res.is_json
    data = res.get_json()
    assert "services" in data
    assert "application" in data["services"]
    assert "database" in data["services"]
    assert "ai_integration" in data["services"]


def test_status_endpoints_accessible_without_authentication():
    """Ensure public access: users can check status without any user session or cookie."""
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = True
    with app.test_client() as unauth_client:
        res_html = unauth_client.get("/status")
        assert res_html.status_code in (200, 503)
        assert res_html.status_code != 401
        assert res_html.status_code != 302

        res_api = unauth_client.get("/api/status")
        assert res_api.status_code in (200, 503)
        assert res_api.status_code != 401
        assert res_api.status_code != 302
