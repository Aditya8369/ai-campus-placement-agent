import json
from pathlib import Path
import pytest

import config
from app import app, get_available_companies
from agents.coordinator import CoordinatorAgent
from agents.job_match_agent import determine_company_tier


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


NEW_COMPANIES = [
    "Cognizant",
    "Zoho",
    "HCLTech",
    "Tech Mahindra",
    "Deloitte",
    "Flipkart",
    "Adobe",
]

EXISTING_COMPANIES = [
    "Google",
    "Microsoft",
    "Amazon",
    "TCS",
    "Infosys",
    "Accenture",
    "Capgemini",
    "Wipro",
]

REQUIRED_KEYS = [
    "overview",
    "hiring_process",
    "technical_rounds",
    "hr_rounds",
    "frequent_topics",
    "required_skills",
    "prep_tips",
    "eligibility",
]


def test_companies_json_validity_and_structure():
    """Validates that data/companies.json exists, parses cleanly, and contains all expected profiles and keys."""
    companies_path = Path(config.BASE_DIR) / "data" / "companies.json"
    assert companies_path.exists(), f"companies.json not found at {companies_path}"

    with open(companies_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict)
    assert len(data) >= 15

    # Check that all new companies are present
    for company in NEW_COMPANIES:
        assert company in data, f"Expected company '{company}' not found in companies.json"

    # Check that all existing companies are still present
    for company in EXISTING_COMPANIES:
        assert company in data, f"Original company '{company}' missing from companies.json"

    # Validate that every company entry satisfies the required schema
    for name, profile in data.items():
        for key in REQUIRED_KEYS:
            assert key in profile, f"Missing key '{key}' in profile for '{name}'"

        assert isinstance(profile["overview"], str) and len(profile["overview"]) > 0
        assert isinstance(profile["hiring_process"], str) and len(profile["hiring_process"]) > 0
        assert isinstance(profile["technical_rounds"], str) and len(profile["technical_rounds"]) > 0
        assert isinstance(profile["hr_rounds"], str) and len(profile["hr_rounds"]) > 0
        assert isinstance(profile["frequent_topics"], list) and len(profile["frequent_topics"]) > 0
        assert isinstance(profile["required_skills"], list) and len(profile["required_skills"]) > 0
        assert isinstance(profile["prep_tips"], str) and len(profile["prep_tips"]) > 0
        assert isinstance(profile["eligibility"], str) and len(profile["eligibility"]) > 0


def test_get_available_companies():
    """Verifies get_available_companies loads dynamic list and falls back gracefully."""
    companies = get_available_companies()
    assert isinstance(companies, list)
    assert len(companies) >= 15
    for c in NEW_COMPANIES + EXISTING_COMPANIES:
        assert c in companies

    # Test fallback behavior when file does not exist
    orig_base = config.BASE_DIR
    try:
        config.BASE_DIR = Path("/nonexistent/directory/path")
        fallback = get_available_companies()
        assert isinstance(fallback, list)
        assert len(fallback) >= 8
        for c in NEW_COMPANIES:
            assert c in fallback
    finally:
        config.BASE_DIR = orig_base


def test_api_company_endpoints(client):
    """Verifies /api/company/<company_name> returns 200 with details for all new companies."""
    for company in NEW_COMPANIES:
        response = client.get(f"/api/company/{company}")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        assert payload["company"] == company
        details = payload["details"]
        for key in REQUIRED_KEYS:
            assert key in details, f"Missing '{key}' in API details for '{company}'"

    # Non-existent company should return 404
    resp_404 = client.get("/api/company/NonExistentCorp123")
    assert resp_404.status_code == 404
    payload_404 = resp_404.get_json()
    assert payload_404["success"] is False


def test_ui_company_selector_renders_new_companies(client):
    """Verifies that the index page renders all new companies in both the dropdown and pill selector."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    for company in NEW_COMPANIES:
        # Check select option
        assert f'<option value="{company}">{company}</option>' in html
        # Check batch mode pill badge
        assert f'data-company="{company}"' in html


def test_coordinator_loads_new_companies():
    """Verifies CoordinatorAgent._load_company_data fetches profiles for new companies."""
    coord = CoordinatorAgent()
    for company in NEW_COMPANIES:
        profile = coord._load_company_data(company)
        assert isinstance(profile, dict) and profile
        assert "hiring_process" in profile
        assert "eligibility" in profile


def test_company_recruitment_tiers():
    """Verifies recruitment tier classification for new companies in JobMatchAgent."""
    # Adobe -> Tier 1
    t1 = determine_company_tier("Adobe")
    assert "Tier 1" in t1["tier"]

    # Flipkart, Zoho -> Tier 2
    t2_flipkart = determine_company_tier("Flipkart")
    assert "Tier 2" in t2_flipkart["tier"]
    t2_zoho = determine_company_tier("Zoho")
    assert "Tier 2" in t2_zoho["tier"]

    # Cognizant, Deloitte, HCLTech, Tech Mahindra -> Tier 3
    for comp in ["Cognizant", "Deloitte", "HCLTech", "Tech Mahindra"]:
        t3 = determine_company_tier(comp)
        assert "Tier 3" in t3["tier"], f"Expected {comp} to be in Tier 3, got {t3['tier']}"
