"""
Unit tests for Internship Recommendation Agent (#142).
"""

from agents.internship_agent import InternshipRecommendationAgent
from app import app


def test_internship_recommendations_scoring():
    """Verify that candidate skills are matched against opportunities with appropriate rationales."""
    agent = InternshipRecommendationAgent()
    skills = ["Python", "Algorithms", "System Design", "Git"]

    res = agent.get_recommendations(candidate_skills=skills)
    assert res["success"] is True
    assert res["total_found"] > 0
    top = res["recommendations"][0]
    assert "match_percentage" in top
    assert "rationale" in top
    assert "apply_url" in top
    assert top["match_percentage"] >= 20


def test_internship_filtering_by_location():
    """Verify filtering opportunities by location."""
    agent = InternshipRecommendationAgent()
    res = agent.get_recommendations(
        candidate_skills=["Java", "SQL"],
        location="Bengaluru"
    )
    assert res["success"] is True
    for opp in res["recommendations"]:
        assert "bengaluru" in opp["location"].lower() or opp["location"] == "Remote / Hybrid"


def test_internships_web_route():
    """Verify GET and AJAX requests to /internships endpoint."""
    with app.test_client() as client:
        # Standard GET
        res = client.get("/internships?skills=Python,SQL")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Internship Recommendation Agent" in html
        assert "btnFilterInternships" in html

        # AJAX GET
        res_json = client.get("/internships?skills=Python,SQL", headers={"X-Requested-With": "XMLHttpRequest"})
        assert res_json.status_code == 200
        data = res_json.get_json()
        assert data["success"] is True
        assert len(data["recommendations"]) > 0
