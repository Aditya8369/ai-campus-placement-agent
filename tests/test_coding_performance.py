import pytest
from utils.coding_performance_service import compare_performance

def test_performance_comparison():
    res = compare_performance("two-sum", 44.0, 17.8)
    assert res["success"] is True
    assert res["status"] == "measured"
    assert "milliseconds" in res["units"]["time"]
    assert "approximate" in res["comparison"]["disclaimer"].lower()

def test_performance_fallback():
    res = compare_performance("unknown-prob", None, None)
    assert res["success"] is True
    assert res["status"] == "fallback"

def test_performance_api(client):
    res = client.post("/api/coding/performance/compare", json={
        "problem_id": "two-sum",
        "runtime_ms": 50,
        "memory_mb": 18
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "comparison" in data["metrics"]
