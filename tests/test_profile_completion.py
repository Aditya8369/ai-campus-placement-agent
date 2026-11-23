import pytest
from utils.profile_completion_service import calculate_profile_completion

def test_profile_completion():
    data = {
        "target_role": "Backend Engineer",
        "graduation_year": 2026,
        "skills": ["Python", "SQL"],
        "resume_uploaded": True,
        "applications_count": 0
    }
    res = calculate_profile_completion(data)
    assert res["success"] is True
    assert res["completion_percentage"] == 90  # 25 + 20 + 25 + 20
    assert res["missing_required_count"] == 0

def test_profile_completion_api(client):
    res = client.post("/api/profile/completion-checklist", json={
        "profile": {"target_role": "SDE"}
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "completion_percentage" in data["result"]
