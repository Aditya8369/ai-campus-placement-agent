import pytest
import json
from unittest.mock import patch
from app import app
from agents.coding_practice_agent import CodingPracticeAgent

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_coding_practice_agent_recommendations():
    agent = CodingPracticeAgent()
    
    # 1. Company matching
    res = agent.recommend_problems(
        skill_gaps=["Dynamic Programming", "Graphs"],
        target_company="Google",
        difficulty_preference="Medium",
        limit=5
    )
    assert res["target_company"] == "Google"
    assert len(res["recommendations"]) > 0
    top_problem = res["recommendations"][0]
    assert top_problem["relevance_score"] >= 40
    assert any("Google" in c for c in top_problem["companies"]) or "gap" in str(top_problem["match_reasons"])
    assert len(res["study_plan"]) == 3

def test_coding_practice_difficulty_filtering():
    agent = CodingPracticeAgent()
    res = agent.recommend_problems(
        skill_gaps=["Arrays"],
        target_company="Amazon",
        difficulty_preference="Easy",
        limit=4
    )
    assert len(res["recommendations"]) > 0
    # Easy problems get difficulty boost
    easy_probs = [p for p in res["recommendations"] if p["difficulty"] == "Easy"]
    assert len(easy_probs) >= 1

def test_coding_practice_endpoints(client):
    # GET page
    get_res = client.get("/coding-practice")
    assert get_res.status_code == 200
    assert b"Personalized Coding Practice" in get_res.data

    # POST filter
    post_res = client.post("/coding-practice", data={
        "company": "Microsoft",
        "skills": "Trees, Recursion",
        "difficulty": "Medium"
    })
    assert post_res.status_code == 200
    assert b"Microsoft" in post_res.data

    # API recommendations
    api_res = client.get("/api/coding-practice/recommendations?company=Meta&skills=Hash%20Map")
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert "recommendations" in data["data"]
    assert len(data["data"]["recommendations"]) > 0
