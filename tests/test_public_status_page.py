"""
Unit tests for Public Application Status and Maintenance Page (#524).
"""

import json
import pytest
from app import create_app
from utils.system_status_service import PublicStatusService


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_public_status_service_probes():
    status = PublicStatusService.get_public_system_status()
    assert "overall_status" in status
    assert len(status["subsystems"]) == 5
    assert status["uptime_30d_pct"] > 99.0

    # Log maintenance incident
    inc = PublicStatusService.log_incident(
        title="Scheduled Database Reindexing",
        subsystem="database",
        severity="maintenance",
        message="Running automated index optimization."
    )
    assert inc["status"] == "created"

    # Status reflects maintenance
    updated_status = PublicStatusService.get_public_system_status()
    assert len(updated_status["active_incidents"]) >= 1

    # Resolve incident
    res_ok = PublicStatusService.resolve_incident(inc["incident_id"])
    assert res_ok is True


def test_public_status_api_and_view(client):
    # 1. HTML View (Public without login)
    view_res = client.get("/system-status")
    assert view_res.status_code == 200
    assert b"Platform Health & Status" in view_res.data or b"Platform Health &amp; Status" in view_res.data

    # 2. JSON API endpoint
    api_res = client.get("/api/system-status/public")
    assert api_res.status_code in [200, 503]
    data = json.loads(api_res.data)
    assert "subsystems" in data
    assert any(s["key"] == "web" for s in data["subsystems"])

    # 3. Admin incident creation
    with client.session_transaction() as s:
        s["user_id"] = "admin_user"
        s["user_role"] = "admin"

    inc_res = client.post("/api/admin/status/incident", json={
        "title": "ATS Engine Upgrade",
        "subsystem": "resume_parser",
        "severity": "maintenance",
        "message": "Deploying enhanced OCR models."
    })
    assert inc_res.status_code == 201
    i_data = json.loads(inc_res.data)
    inc_id = i_data["incident"]["incident_id"]

    # 4. Admin resolve
    resolve_res = client.post(f"/api/admin/status/incident/{inc_id}/resolve")
    assert resolve_res.status_code == 200
    r_data = json.loads(resolve_res.data)
    assert r_data["resolved"] is True
