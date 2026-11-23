import pytest
from utils.data_freshness_service import check_report_freshness

def test_report_freshness_current():
    meta = {"resume_version": "v2", "target_role": "Backend Engineer"}
    profile = {"resume_version": "v2", "target_role": "Backend Engineer"}
    res = check_report_freshness(meta, profile)
    assert res["is_fresh"] is True
    assert res["status_label"] == "Current"

def test_report_freshness_stale():
    meta = {"resume_version": "v1", "target_role": "Frontend Developer"}
    profile = {"resume_version": "v2", "target_role": "Full Stack Developer"}
    res = check_report_freshness(meta, profile)
    assert res["is_fresh"] is False
    assert res["status_label"] == "Outdated"
    assert len(res["stale_reasons"]) == 2

def test_freshness_api(client):
    res = client.post("/api/analysis/freshness-check", json={
        "report_meta": {"resume_version": "v1"},
        "current_profile": {"resume_version": "v2"}
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert res.get_json()["freshness"]["is_fresh"] is False
