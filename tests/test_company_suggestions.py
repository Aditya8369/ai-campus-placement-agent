"""
Unit and Integration Tests for Company Profile Suggestions & Review System (#450).
==================================================================================
Tests:
1. Users can suggest a new company profile.
2. Users can request an update to an existing company profile.
3. Suggestions start as 'pending' and are not publicly visible in active directory.
4. Web and API submission endpoints (/companies/suggest, /api/company-suggestions).
5. Maintainers can view and distinguish unverified suggestions from approved profiles.
6. Maintainer approval workflow publishes new company or applies updates.
7. Maintainer rejection workflow records rejection with audit notes.
"""

import pytest
import config
from utils.database import init_db, get_db_connection
from utils.company_profile_manager import (
    ensure_company_profiles_table,
    ensure_company_profile_suggestions_table,
    seed_default_company_profiles,
    create_company_profile,
    get_company_profile_by_name,
    list_company_profiles,
    create_company_suggestion,
    get_company_suggestion_by_id,
    list_company_suggestions,
    approve_company_suggestion,
    reject_company_suggestion,
    get_suggestion_stats,
)
from app import app


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Sets up an isolated database environment for company suggestion tests."""
    test_db = tmp_path / "test_company_suggestions.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-admin-secret-xyz")
    init_db()

    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)
        ensure_company_profile_suggestions_table(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-suggestions-secret-key"
    with app.test_client() as client:
        yield client


def test_suggest_new_company_creation(isolated_db):
    """Verify users can suggest a new company profile, saved as pending and unverified."""
    suggestion = create_company_suggestion(
        company_name="Razorpay",
        suggestion_type="new",
        industry="Fintech / Payment Gateway",
        website_url="https://razorpay.com",
        careers_url="https://razorpay.com/jobs",
        hiring_tier="Startup",
        hiring_workflow=["Online Assessment", "Machine Coding Round", "System Design", "Culture Fit"],
        primary_tech_stack=["Go", "Python", "PHP", "AWS", "Kafka"],
        typical_ctc_range="18 - 30 LPA",
        headquarters="Bengaluru, India",
        overview="Leading fintech unicorn powering digital payments in India.",
        notes="Visiting campus for 2026 Batch",
        submitter_name="John Doe",
        submitter_email="john@college.edu"
    )

    assert suggestion is not None
    assert suggestion["id"] is not None
    assert suggestion["company_name"] == "Razorpay"
    assert suggestion["status"] == "pending"
    assert suggestion["suggestion_type"] == "new"
    assert len(suggestion["hiring_workflow"]) == 4
    assert len(suggestion["primary_tech_stack"]) == 5

    # Crucial distinction: Razorpay must NOT be visible in public active company directory
    public_profiles = list_company_profiles(search_query="Razorpay", active_only=True)
    assert len(public_profiles) == 0


def test_suggest_update_to_existing_company(isolated_db):
    """Verify users can request an update to an existing company profile."""
    # First create an existing verified profile
    existing = create_company_profile(
        company_name="Atlassian",
        industry="Product Software",
        hiring_tier="Tier 1",
        typical_ctc_range="40 - 65 LPA",
        headquarters="Sydney, Australia"
    )

    # User submits an update suggestion
    suggestion = create_company_suggestion(
        company_name="Atlassian",
        suggestion_type="update",
        target_company_id=existing["id"],
        typical_ctc_range="50 - 75 LPA",
        hiring_workflow=["HackerRank OA", "System Design", "Values Interview"],
        notes="Updated CTC bracket for 2026 graduate hires"
    )

    assert suggestion["suggestion_type"] == "update"
    assert suggestion["target_company_id"] == existing["id"]
    assert suggestion["status"] == "pending"

    # Detail check includes current verified profile for maintainer comparison
    sugg_detail = get_company_suggestion_by_id(suggestion["id"])
    assert sugg_detail["current_verified_profile"] is not None
    assert sugg_detail["current_verified_profile"]["typical_ctc_range"] == "40 - 65 LPA"


def test_web_and_api_submission(isolated_db):
    """Verify GET /companies/suggest form rendering and POST /api/company-suggestions API."""
    # 1. GET form page
    res_get = isolated_db.get("/companies/suggest?company_name=Stripe")
    assert res_get.status_code == 200
    html = res_get.get_data(as_text=True)
    assert "Suggest a Company or Profile Update" in html
    assert "Stripe" in html

    # 2. POST API JSON submission
    payload = {
        "company_name": "Stripe",
        "suggestion_type": "new",
        "industry": "Fintech / Global Infrastructure",
        "website_url": "https://stripe.com",
        "typical_ctc_range": "35 - 55 LPA",
        "notes": "Remote-first campus recruiting"
    }
    res_post = isolated_db.post("/api/company-suggestions", json=payload)
    assert res_post.status_code == 201
    data = res_post.get_json()
    assert data["status"] == "success"
    assert data["suggestion"]["company_name"] == "Stripe"
    assert data["suggestion"]["status"] == "pending"


def test_validation_empty_company_name(isolated_db):
    """Verify validation rejects empty company names."""
    res = isolated_db.post("/api/company-suggestions", json={"company_name": "  "})
    assert res.status_code == 400
    assert "Company name is required" in res.get_json()["message"]


def test_maintainer_review_and_approval_workflow(isolated_db):
    """Verify maintainer can review unverified suggestions and approve them into the directory."""
    # 1. Submit suggestion
    sugg = create_company_suggestion(
        company_name="Databricks",
        suggestion_type="new",
        industry="Data & AI Infrastructure",
        hiring_tier="Tier 1",
        typical_ctc_range="35 - 60 LPA",
        hiring_workflow=["Codesignal OA", "Algo Round", "Systems Round", "Cultural Fit"]
    )
    sugg_id = sugg["id"]

    # 2. Maintainer inspects queue
    stats_before = get_suggestion_stats()
    assert stats_before["pending"] >= 1

    pending_list = list_company_suggestions(status="pending")
    assert any(s["id"] == sugg_id for s in pending_list)

    # 3. Maintainer approves via API with audit notes
    res_approve = isolated_db.post(
        f"/api/admin/company-suggestions/{sugg_id}/approve",
        headers={"X-Admin-Key": "test-admin-secret-xyz"},
        json={"moderator_notes": "Verified against 2026 hiring rubric"}
    )
    assert res_approve.status_code == 200
    approved_sugg = res_approve.get_json()["suggestion"]
    assert approved_sugg["status"] == "approved"
    assert approved_sugg["moderated_by"] == "admin"

    # 4. Now Databricks MUST be published and discoverable in company_profiles
    published = get_company_profile_by_name("Databricks")
    assert published is not None
    assert published["company_name"] == "Databricks"
    assert published["industry"] == "Data & AI Infrastructure"
    assert published["is_active"] == 1


def test_maintainer_rejection_workflow(isolated_db):
    """Verify maintainer can reject invalid or spam company suggestions."""
    sugg = create_company_suggestion(
        company_name="Spam Fake Corp 123",
        suggestion_type="new",
        overview="Unverified placeholder"
    )
    sugg_id = sugg["id"]

    res_reject = isolated_db.post(
        f"/api/admin/company-suggestions/{sugg_id}/reject",
        headers={"X-Admin-Key": "test-admin-secret-xyz"},
        json={"moderator_notes": "Duplicate / invalid organization"}
    )
    assert res_reject.status_code == 200
    rejected_sugg = res_reject.get_json()["suggestion"]
    assert rejected_sugg["status"] == "rejected"

    # Ensure profile was NEVER added to company_profiles
    assert get_company_profile_by_name("Spam Fake Corp 123") is None


def test_maintainer_web_portal_rendering(isolated_db):
    """Verify maintainer review dashboard renders with side-by-side comparison."""
    # Seed a verified company
    comp = create_company_profile(company_name="Nvidia", industry="Semiconductors", typical_ctc_range="25 - 45 LPA")
    # Add an update suggestion
    create_company_suggestion(
        company_name="Nvidia",
        suggestion_type="update",
        target_company_id=comp["id"],
        typical_ctc_range="35 - 55 LPA"
    )

    res = isolated_db.get(
        "/admin/company-suggestions?status=pending",
        headers={"X-Admin-Key": "test-admin-secret-xyz"}
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Company Profile Suggestions Review" in html
    assert "Pending Review" in html
    assert "Nvidia" in html
    assert "Field Comparison" in html
