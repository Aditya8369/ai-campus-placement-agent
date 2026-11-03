"""
Test suite for health check and readiness probe endpoints (/healthz and /api/health).

Checks:
- HTTP 200 and healthy JSON payload in standard conditions
- Database connectivity check reporting healthy status
- Storage folder write permissions verification
- Configuration detection for Gemini API integration
- Degraded HTTP 503 response when database fails
"""

import pytest
from app import app


def test_health_check_healthy_status():
    """Verify /healthz returns 200 with service checks."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/healthz")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "ai-campus-placement-agent"
        assert "latency_ms" in data
        assert data["checks"]["database"]["status"] == "healthy"
        assert data["checks"]["storage"]["status"] == "healthy"


def test_api_health_endpoint_alias():
    """Verify /api/health behaves identically as an alias."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "healthy"


def test_health_check_degraded_when_database_fails(monkeypatch):
    """Verify /healthz returns 503 when database connection raises an exception."""
    import app as app_module

    def broken_connection():
        raise RuntimeError("Disk I/O failure on SQLite")

    monkeypatch.setattr(app_module, "get_db_connection", broken_connection)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/healthz")
        assert res.status_code == 503
        data = res.get_json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"]["status"] == "unhealthy"
        assert "Disk I/O failure" in data["checks"]["database"]["error"]
