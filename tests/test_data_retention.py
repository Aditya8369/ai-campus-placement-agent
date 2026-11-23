import pytest
from utils.data_retention_service import validate_retention_policy, RETENTION_POLICIES

def test_retention_policy_validation():
    p1 = validate_retention_policy("90_days")
    assert p1["valid"] is True
    assert p1["days"] == 90

    p_bad = validate_retention_policy("invalid_duration")
    assert p_bad["valid"] is False

def test_retention_api(client):
    res = client.post("/api/account/data-retention", json={
        "policy": "30_days",
        "confirmed": True
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert res.get_json()["policy"]["policy_key"] == "30_days"
