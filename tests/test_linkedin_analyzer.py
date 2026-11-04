import pytest
import json
from unittest.mock import patch
from app import app
from agents.linkedin_agent import LinkedInAgent

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_linkedin_agent_scoring():
    agent = LinkedInAgent()
    analysis = agent.analyze_profile(
        headline="Software Engineer Intern | Python, React, Docker | Open to Placements",
        about="I am a CS student passionate about building scalable microservices and distributed databases. Engineered backend systems handling 10k requests.",
        experience="Built an e-commerce platform that reduced checkout latency by 35%. Refactored REST APIs using Python and PostgreSQL.",
        skills="Python, React, Docker, SQL, Git, REST APIs, Microservices, Data Structures, Algorithms",
        target_role="Software Engineer"
    )

    assert analysis["overall_score"] > 60
    assert analysis["headline_score"] >= 70
    assert analysis["about_score"] >= 60
    assert analysis["experience_score"] >= 70
    assert analysis["skills_score"] >= 50
    assert len(analysis["headline_rewrites"]) >= 1
    assert len(analysis["ai_suggestions"]) >= 1
    assert "Python" in analysis["matched_keywords"]

def test_linkedin_agent_empty_profile():
    agent = LinkedInAgent()
    analysis = agent.analyze_profile(
        headline="",
        about="",
        experience="",
        skills="",
        target_role="Frontend Developer"
    )

    assert analysis["overall_score"] <= 30
    assert len(analysis["headline_feedback"]) >= 1
    assert len(analysis["missing_keywords"]) > 0

def test_linkedin_analyzer_endpoints(client):
    # GET view
    get_res = client.get("/linkedin-analyzer")
    assert get_res.status_code == 200
    assert b"LinkedIn Profile Analyzer" in get_res.data

    # POST view
    post_res = client.post("/linkedin-analyzer", data={
        "target_role": "Backend Developer",
        "headline": "Backend Engineer | Go & Python",
        "about": "Passionate backend engineer with experience in Docker and Redis.",
        "experience": "Architected microservices handling high traffic.",
        "skills": "Go, Python, Docker, Redis"
    })
    assert post_res.status_code == 200
    assert b"Profile Optimization Score" in post_res.data
    assert b"AI-Powered Headline Rewrites" in post_res.data

    # API JSON request
    api_res = client.post("/linkedin-analyzer", json={
        "target_role": "Data Scientist",
        "headline": "Data Scientist | Python, ML, SQL",
        "about": "Developed deep learning models for classification.",
        "experience": "Trained CNN models with 92% accuracy.",
        "skills": "Python, Machine Learning, SQL, PyTorch"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert data["analysis"]["overall_score"] > 50
