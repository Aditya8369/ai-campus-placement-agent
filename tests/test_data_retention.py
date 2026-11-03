"""
Unit tests for data retention policies and maintenance endpoints.
"""

import json
from app import app
from utils.cleanup import run_full_retention_policy


def test_run_full_retention_policy_dry_run():
    """Verify dry run calculates without deleting anything."""
    results = run_full_retention_policy(max_file_age_hours=24, max_db_age_days=30, dry_run=True)
    assert "files" in results
    assert "database" in results
    assert results["dry_run"] is True


def test_api_admin_retention_run_endpoint():
    """Verify admin retention execution API endpoint."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post(
            "/api/admin/retention/run",
            data=json.dumps({"max_file_age_hours": 100, "max_db_age_days": 100, "dry_run": True}),
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"
        assert data["results"]["dry_run"] is True
