import pytest
from utils.company_timeline_service import get_company_process_timeline

def test_company_process_timeline():
    timeline = get_company_process_timeline("Google")
    assert timeline["success"] is True
    assert timeline["company_name"] == "Google"
    assert len(timeline["stages"]) == 6
    assert any(s["type"] == "official" for s in timeline["stages"])
    assert any(s["type"] == "community_reported" for s in timeline["stages"])

def test_company_process_timeline_api(client):
    res = client.get("/api/company/Google/process-timeline")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["timeline"]["estimated_total_days"] > 0
