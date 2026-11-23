import pytest
from utils.burnout_warning_service import evaluate_burnout_risk

def test_burnout_risk_triggered():
    heavy_schedule = [8.0, 8.5, 9.0, 7.5, 8.0, 6.0, 7.0]
    res = evaluate_burnout_risk(heavy_schedule)
    assert res["success"] is True
    assert res["warning_triggered"] is True
    assert "lighter recovery day" in res["recommendation"]
    assert "not a medical" in res["disclaimer"].lower()

def test_burnout_risk_disabled():
    res = evaluate_burnout_risk([10.0, 10.0, 10.0], reminders_enabled=False)
    assert res["warning_triggered"] is False

def test_burnout_api(client):
    res = client.post("/api/preparation/burnout-check", json={
        "daily_hours": [8.0, 8.0, 8.5]
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert res.get_json()["evaluation"]["warning_triggered"] is True
