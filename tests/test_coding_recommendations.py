import pytest
from utils.coding_recommendation_service import recommend_problems_with_reasons

def test_recommendation_with_weak_topics():
    recs = recommend_problems_with_reasons(
        weak_topics=["stacks"],
        recent_failed_attempts=["valid-parentheses"],
        dismissed_problem_ids=["two-sum"]
    )
    assert len(recs) >= 1
    # Check dismissed problem is excluded
    assert not any(r["problem"]["id"] == "two-sum" for r in recs)

    # Check reason for valid-parentheses
    vp = next(r for r in recs if r["problem"]["id"] == "valid-parentheses")
    assert any("incorrect or unsubmitted" in reason for reason in vp["reasons"])
    assert any("stacks" in reason for reason in vp["reasons"])

def test_recommendation_api(client):
    res = client.post("/api/coding/recommendations", json={
        "weak_topics": ["hash maps"],
        "recent_failed": ["two-sum"],
        "dismissed": []
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert len(data["recommendations"]) >= 1
    assert "primary_reason" in data["recommendations"][0]
