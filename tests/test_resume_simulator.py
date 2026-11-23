"""
Unit tests for Resume Improvement Simulator (#600)
"""

import pytest
import uuid
from utils.database import save_analysis
from utils.resume_simulator_service import (
    get_default_what_if_suggestions,
    simulate_resume_improvements
)


def test_what_if_suggestions_default():
    suggestions = get_default_what_if_suggestions()
    assert len(suggestions) >= 4
    ids = [s["id"] for s in suggestions]
    assert "add_cloud_devops" in ids
    assert "add_system_design" in ids


def test_what_if_suggestions_tailored_gaps():
    analysis_record = {
        "id": "test_tailored_1",
        "results": {
            "skill_gap": [{"skill": "Kubernetes"}, {"skill": "Go"}]
        }
    }
    suggestions = get_default_what_if_suggestions(analysis_record)
    assert suggestions[0]["id"] == "tailored_gap_fix"
    assert "Kubernetes" in suggestions[0]["skills"]


def test_simulate_resume_improvements_logic():
    analysis_record = {
        "id": "analysis_sim_123",
        "company_name": "Google",
        "results": {
            "resume_analysis": {"ats_score": 60},
            "job_match": {"match_percentage": 50}
        }
    }
    
    # Test with suggestions and skills
    result = simulate_resume_improvements(
        analysis_record=analysis_record,
        simulated_skills=["Docker", "AWS"],
        simulated_projects=["High Scale Microservices"],
        selected_suggestion_ids=["add_cloud_devops"]
    )
    
    assert result["is_estimate"] is True
    assert result["base_metrics"]["ats_score"] == 60
    assert result["estimated_metrics"]["ats_score"] > 60
    assert result["estimated_metrics"]["match_percentage"] > 50
    assert result["deltas"]["ats_delta"] > 0
    assert result["deltas"]["match_delta"] > 0
    assert len(result["factors_applied"]) >= 2
    assert "guarantee" in result["disclaimer"].lower()

    # Verify original record remained untouched
    assert analysis_record["results"]["resume_analysis"]["ats_score"] == 60


def test_simulate_api_endpoints(client):
    analysis_id = f"test_sim_rec_{uuid.uuid4().hex[:8]}"
    results_payload = {
        "resume_analysis": {"ats_score": 70},
        "job_match": {"match_percentage": 65},
        "skill_gap": [{"skill": "Docker"}]
    }
    save_analysis(analysis_id, "resume.pdf", "Amazon", "SDE role", results_payload)

    # 1. Test GET simulation options
    resp = client.get(f"/api/analysis/{analysis_id}/simulation-options")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["suggestions"]) > 0

    # 2. Test POST simulate improvements
    sim_resp = client.post(
        f"/api/analysis/{analysis_id}/simulate-improvements",
        json={
            "simulated_skills": ["Kubernetes"],
            "simulated_projects": ["Distributed Cache"],
            "selected_suggestion_ids": ["add_cloud_devops"]
        }
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.get_json()
    assert sim_data["success"] is True
    sim = sim_data["simulation"]
    assert sim["estimated_metrics"]["ats_score"] > 70
    assert sim["base_metrics"]["ats_score"] == 70
