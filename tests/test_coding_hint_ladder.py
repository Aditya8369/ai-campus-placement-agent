import pytest
from utils.coding_hint_ladder_service import get_hint_for_problem

def test_get_hint_ladder_progression():
    h1 = get_hint_for_problem("two-sum", 1)
    assert h1["level"] == 1
    assert "Gentle Nudge" in h1["title"]
    assert h1["has_next_hint"] is True

    h2 = get_hint_for_problem("two-sum", 2)
    assert h2["level"] == 2
    assert "Hash Map" in h2["hint"]

    h3 = get_hint_for_problem("two-sum", 3)
    assert h3["level"] == 3
    assert h3["has_next_hint"] is False

def test_coding_hint_api(client):
    res = client.post("/api/coding/hints", json={
        "problem_id": "two-sum",
        "level": 1
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["hint"]["level"] == 1
    assert data["hints_used_count"] == 1
