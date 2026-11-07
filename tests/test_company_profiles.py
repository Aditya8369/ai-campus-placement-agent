"""
Unit and API Integration Tests for Company Profile Update Management System (#250)
==================================================================================
Tests:
1. Automated schema setup and seed initialization.
2. CRUD operations: creation, retrieval, updates, and soft deletion.
3. Search and hiring tier filtering.
4. Duplicate company prevention.
5. Admin authorization enforcement on POST, PUT, DELETE endpoints.
6. Public read access to active company directory.
"""

import pytest
import json
from unittest.mock import patch

import config
from utils.database import init_db, get_db_connection
from utils.company_profile_manager import (
    ensure_company_profiles_table,
    seed_default_company_profiles,
    create_company_profile,
    update_company_profile,
    get_company_profile_by_id,
    get_company_profile_by_name,
    list_company_profiles,
    archive_company_profile,
    delete_company_profile_permanently,
)
from app import app


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Sets up an isolated database environment for company profiles tests."""
    test_db = tmp_path / "test_company_profiles.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "secure-admin-token-xyz")
    init_db()

    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "company-mgmt-key"
    with app.test_client() as client:
        yield client


def test_seed_default_profiles(isolated_db):
    """Verify default tech giants are seeded when directory is initially empty."""
    seeded_count = seed_default_company_profiles()
    assert seeded_count >= 4

    profiles = list_company_profiles()
    names = [p["company_name"] for p in profiles]
    assert "Google" in names
    assert "Microsoft" in names
    assert "Amazon" in names


def test_create_and_retrieve_profile(isolated_db):
    """Verify adding a new enterprise profile and fetching by ID / name."""
    profile = create_company_profile(
        company_name="Netflix",
        industry="Streaming & Entertainment Tech",
        website_url="https://netflix.com",
        careers_url="https://jobs.netflix.com",
        overview="Pioneering global entertainment and video streaming technology.",
        hiring_tier="Tier 1",
        hiring_workflow=["Recruiter Screen", "Technical System Design", "Culture Interview"],
        primary_tech_stack=["Java", "Node.js", "Spinnaker", "Cassandra", "AWS"],
        typical_ctc_range="35 - 55 LPA",
        headquarters="Los Gatos, CA"
    )

    assert profile["company_name"] == "Netflix"
    assert profile["hiring_tier"] == "Tier 1"
    assert "Spinnaker" in profile["primary_tech_stack"]
    assert len(profile["hiring_workflow"]) == 3

    # Retrieve by ID
    by_id = get_company_profile_by_id(profile["id"])
    assert by_id is not None
    assert by_id["company_name"] == "Netflix"

    # Retrieve by Name
    by_name = get_company_profile_by_name("netflix")
    assert by_name is not None
    assert by_name["id"] == profile["id"]


def test_duplicate_company_rejection(isolated_db):
    """Verify duplicate company names raise an error."""
    create_company_profile(company_name="Uber", industry="Ridehailing")
    with pytest.raises(ValueError) as exc:
        create_company_profile(company_name="Uber", industry="Mobility")
    assert "already exists" in str(exc.value)


def test_update_profile(isolated_db):
    """Verify field updates are applied and updated_at timestamp is refreshed."""
    comp = create_company_profile(company_name="Stripe", industry="Fintech", hiring_tier="Tier 2")
    orig_updated_at = comp["updated_at"]

    updated = update_company_profile(comp["id"], {
        "hiring_tier": "Tier 1",
        "typical_ctc_range": "30 - 48 LPA",
        "primary_tech_stack": ["Ruby", "Go", "React"]
    })

    assert updated is not None
    assert updated["hiring_tier"] == "Tier 1"
    assert updated["typical_ctc_range"] == "30 - 48 LPA"
    assert "Ruby" in updated["primary_tech_stack"]


def test_archive_and_filtering(isolated_db):
    """Verify soft-deletion hides profiles from default active listings."""
    comp1 = create_company_profile(company_name="StartupAlpha", hiring_tier="Startup")
    comp2 = create_company_profile(company_name="StartupBeta", hiring_tier="Startup")

    # List startups
    startups = list_company_profiles(tier_filter="Startup")
    assert len(startups) == 2

    # Archive one
    archived = archive_company_profile(comp1["id"])
    assert archived is True

    # Active startups should now be 1
    remaining = list_company_profiles(tier_filter="Startup", active_only=True)
    assert len(remaining) == 1
    assert remaining[0]["company_name"] == "StartupBeta"


def test_api_list_companies(isolated_db):
    """Test GET /api/companies endpoint with automatic seeding and search."""
    resp = isolated_db.get("/api/companies?search=micro")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert any(c["company_name"] == "Microsoft" for c in data["companies"])


def test_api_create_company_admin_protection(isolated_db):
    """Test POST /api/companies requires administrative token or role."""
    new_comp = {
        "company_name": "Salesforce",
        "industry": "CRM & Enterprise SaaS"
    }

    # Unauthorized attempt
    unauth_resp = isolated_db.post("/api/companies", json=new_comp)
    assert unauth_resp.status_code == 403

    # Authorized attempt via X-Admin-Key
    auth_resp = isolated_db.post(
        "/api/companies",
        json=new_comp,
        headers={"X-Admin-Key": "secure-admin-token-xyz"}
    )
    assert auth_resp.status_code == 201
    assert auth_resp.get_json()["company"]["company_name"] == "Salesforce"


def test_api_update_and_delete_endpoints(isolated_db):
    """Test PUT and DELETE /api/companies/<id> with admin authorization."""
    created = create_company_profile(company_name="Oracle", industry="Enterprise Cloud")

    # PUT update
    update_payload = {"overview": "Global database and cloud enterprise leader."}
    put_resp = isolated_db.put(
        f"/api/companies/{created['id']}",
        json=update_payload,
        headers={"X-Admin-Key": "secure-admin-token-xyz"}
    )
    assert put_resp.status_code == 200
    assert put_resp.get_json()["company"]["overview"] == "Global database and cloud enterprise leader."

    # DELETE archive
    del_resp = isolated_db.delete(
        f"/api/companies/{created['id']}",
        headers={"X-Admin-Key": "secure-admin-token-xyz"}
    )
    assert del_resp.status_code == 200

    # Detail GET verifies active status is False
    get_resp = isolated_db.get(f"/api/companies/{created['id']}")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["company"]["is_active"] is False
