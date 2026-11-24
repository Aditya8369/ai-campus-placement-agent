"""
Unit tests for Role-based preparation difficulty estimate (#604)
"""

import pytest
from utils.prep_difficulty_service import calculate_preparation_difficulty


def test_calculate_difficulty_easy():
    # Candidate possesses all or almost all required skills
    candidate_skills = [
        "Data Structures", "Algorithms", "Python", "Java", "SQL", "Git",
        "System Design", "REST APIs", "Docker", "Linux"
    ]
    result = calculate_preparation_difficulty(
        candidate_skills=candidate_skills,
        role_id_or_profile="software_developer",
        hours_per_week=20
    )
    assert result["difficulty_tier"] == "Easy"
    assert result["estimated_weeks"] <= 3
    assert len(result["factors"]) > 0
    assert "not constitute a guarantee" in result["disclaimer"].lower()


def test_calculate_difficulty_moderate():
    # Candidate possesses some core skills, missing 2-4
    candidate_skills = ["Python", "SQL", "Git", "REST APIs", "Docker"]
    result = calculate_preparation_difficulty(
        candidate_skills=candidate_skills,
        role_id_or_profile="software_developer",
        hours_per_week=15
    )
    assert result["difficulty_tier"] == "Moderate"
    assert 3 <= result["estimated_weeks"] <= 8
    assert result["missing_required_count"] > 0
    assert len(result["factors"]) > 0


def test_calculate_difficulty_challenging():
    # Empty or zero-skill candidate
    candidate_skills = []
    result = calculate_preparation_difficulty(
        candidate_skills=candidate_skills,
        role_id_or_profile="software_developer",
        hours_per_week=10
    )
    assert result["difficulty_tier"] == "Challenging"
    assert result["estimated_weeks"] >= 6
    assert result["missing_required_count"] >= 4


def test_api_role_difficulty_estimate(client):
    resp = client.post(
        "/api/role-difficulty-estimate",
        json={
            "skills": ["Python", "Flask", "SQL"],
            "role_id": "backend_developer",
            "hours_per_week": 15
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "difficulty" in data
    assert data["difficulty"]["difficulty_tier"] in ("Easy", "Moderate", "Challenging")
    assert isinstance(data["difficulty"]["estimated_weeks"], int)
