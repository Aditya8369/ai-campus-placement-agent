"""
Unit and integration tests for Company Hiring Guide Source and Last Updated Information.

Verifies:
1. Every company hiring guide in companies.json contains last_updated date, source name, and source link.
2. External links open safely with target='_blank' and rel='noopener noreferrer'.
3. Verified recruitment information is clearly separated from general preparation suggestions.
4. Outdated hiring information (>12 months) is flagged with an explicit freshness warning.
5. Missing source information and missing dates are handled gracefully without breaking.
6. The /api/company/<name> endpoint returns enriched source and freshness metadata.
7. The company checklist view renders the source metadata, last updated date, and verified info banner.
"""

import json
from pathlib import Path
import pytest
from unittest.mock import patch

import config
from app import app
from utils.company_profile_manager import (
    enrich_company_hiring_guide,
    parse_last_updated_date,
    format_last_updated_display,
    is_hiring_guide_outdated,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. companies.json Source and Freshness Data Validity
# ==============================================================================

class TestCompaniesJsonSourceData:
    """Verifies that data/companies.json contains valid source and freshness attributes for all companies."""

    def test_all_companies_have_source_and_last_updated(self):
        companies_path = Path(config.BASE_DIR) / "data" / "companies.json"
        assert companies_path.exists(), "companies.json not found"

        with open(companies_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) >= 15

        for company_name, profile in data.items():
            assert "last_updated" in profile, f"Missing 'last_updated' for {company_name}"
            assert isinstance(profile["last_updated"], str) and len(profile["last_updated"]) >= 4

            assert "source_name" in profile, f"Missing 'source_name' for {company_name}"
            assert isinstance(profile["source_name"], str) and len(profile["source_name"]) > 0

            assert "source_url" in profile, f"Missing 'source_url' for {company_name}"
            assert isinstance(profile["source_url"], str)
            assert profile["source_url"].startswith("http"), f"Invalid source_url for {company_name}"

            assert "verification_status" in profile, f"Missing 'verification_status' for {company_name}"
            assert profile["verification_status"] == "verified"
            assert profile.get("is_verified") is True


# ==============================================================================
# 2. enrich_company_hiring_guide Helper Tests
# ==============================================================================

class TestEnrichCompanyHiringGuide:
    """Tests the enrich_company_hiring_guide utility with complete, missing, and outdated inputs."""

    def test_enrich_with_complete_fresh_data(self):
        raw = {
            "overview": "Leading cloud and software enterprise.",
            "last_updated": "2026-10-15",
            "source_name": "Official Careers Portal",
            "source_url": "https://careers.example.com",
            "verification_status": "verified",
            "eligibility": "60% or 6.5 CGPA",
            "hiring_process": "OA followed by 3 technical rounds",
            "technical_rounds": "DSA & System Design",
            "prep_tips": "Practice LeetCode medium problems",
            "frequent_topics": ["Binary Trees", "Graphs"],
            "required_skills": ["Python", "SQL"],
        }
        enriched = enrich_company_hiring_guide("ExampleCorp", raw)

        assert enriched["company_name"] == "ExampleCorp"
        assert enriched["source_name"] == "Official Careers Portal"
        assert enriched["source_url"] == "https://careers.example.com"
        assert enriched["source_is_default"] is False
        assert enriched["is_verified"] is True
        assert enriched["verification_badge"] == "Verified Hiring Criteria"

        # Freshness: 2026-10-15 is within 365 days
        assert enriched["is_outdated"] is False
        assert enriched["freshness_status"] == "current"
        assert enriched["outdated_warning"] is None
        assert "October 15, 2026" in enriched["last_updated_display"]

        # Verified vs General Suggestions Separation
        assert "verified_info" in enriched
        assert enriched["verified_info"]["eligibility"] == "60% or 6.5 CGPA"
        assert enriched["verified_info"]["hiring_process"] == "OA followed by 3 technical rounds"

        assert "general_suggestions" in enriched
        assert enriched["general_suggestions"]["is_general_guidance"] is True
        assert "disclaimer" in enriched["general_suggestions"]
        assert len(enriched["general_suggestions"]["frequent_topics"]) == 2

    def test_enrich_flags_outdated_guide_and_provides_warning(self):
        # A guide dated over a year ago (e.g., 2024-01-10)
        raw = {
            "last_updated": "2024-01-10",
            "source_name": "Old Placement Archive",
            "source_url": "https://old.example.com",
            "eligibility": "Old 60% requirement",
        }
        enriched = enrich_company_hiring_guide("OldCorp", raw)

        assert enriched["is_outdated"] is True
        assert enriched["freshness_status"] == "outdated"
        assert enriched["freshness_badge"] == "warning"
        assert enriched["outdated_warning"] is not None
        assert "12 months" in enriched["outdated_warning"]
        assert "January 10, 2024" in enriched["last_updated_display"]

    def test_enrich_handles_missing_source_and_missing_date_gracefully(self):
        # Missing source_name, source_url, and last_updated
        raw = {
            "overview": "A startup company without verified sources.",
            "eligibility": "Open to all branches",
        }
        enriched = enrich_company_hiring_guide("MysteryStartup", raw)

        # Must not crash
        assert enriched["source_name"] == "Campus Placement Archives (Aggregated)"
        assert enriched["source_is_default"] is True
        assert enriched["source_url"] is None  # no broken link
        assert enriched["last_updated_display"] == "Date unconfirmed"
        assert enriched["is_outdated"] is True
        assert enriched["is_verified"] is False
        assert enriched["verification_badge"] == "General Preparation Suggestions"
        assert enriched["outdated_warning"] is not None

    def test_enrich_handles_non_dict_and_empty_input(self):
        enriched_none = enrich_company_hiring_guide("EmptyCorp", None)
        assert isinstance(enriched_none, dict)
        assert enriched_none["company_name"] == "EmptyCorp"
        assert enriched_none["source_url"] is None
        assert enriched_none["last_updated_display"] == "Date unconfirmed"

        enriched_str = enrich_company_hiring_guide("StringCorp", "invalid_type")
        assert isinstance(enriched_str, dict)


# ==============================================================================
# 3. API Endpoint /api/company/<company_name> Tests
# ==============================================================================

class TestApiCompanyEndpointEnrichment:
    """Verifies that the /api/company/<name> route returns enriched source and freshness metadata."""

    def test_api_returns_source_metadata_for_google(self, client):
        response = client.get("/api/company/Google")
        assert response.status_code == 200
        payload = response.get_json()

        assert payload["success"] is True
        assert payload["company"] == "Google"
        details = payload["details"]

        assert "last_updated" in details
        assert "last_updated_display" in details
        assert "source_name" in details
        assert "source_url" in details
        assert details["source_name"] == "Google Students & University Programs"
        assert "https://careers.google.com" in details["source_url"]
        assert details["is_verified"] is True
        assert details["is_outdated"] is False

        # Verified info structure
        assert "verified_info" in details
        assert details["verified_info"]["source_name"] == "Google Students & University Programs"
        assert details["verified_info"]["is_verified"] is True

        # General suggestions structure
        assert "general_suggestions" in details
        assert details["general_suggestions"]["is_general_guidance"] is True
        assert "disclaimer" in details["general_suggestions"]

    def test_api_returns_source_metadata_for_tcs(self, client):
        response = client.get("/api/company/TCS")
        assert response.status_code == 200
        payload = response.get_json()

        details = payload["details"]
        assert details["source_name"] == "TCS NextStep & National Qualifier Test (NQT)"
        assert "nextstep.tcs.com" in details["source_url"]
        assert details["is_verified"] is True


# ==============================================================================
# 4. Company Preparation Checklist Integration Tests
# ==============================================================================

class TestCompanyChecklistSourceIntegration:
    """Verifies that the company checklist view renders source links, last updated, and external security attributes."""

    def test_checklist_renders_source_and_last_updated(self, client):
        response = client.get("/company-checklist?company=Google")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # Must display last updated date
        assert "Last Updated:" in html

        # Must display official source name
        assert "Official Source:" in html
        assert "Google Students" in html
        assert "University Programs" in html

        # Must render external link with security attributes
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html
        assert "https://careers.google.com/students/" in html

        # Must render verified information badge
        assert "Verified Hiring Guide" in html
        assert "Verified Eligibility &amp; Process" in html or "Verified Eligibility & Process" in html

        # Must render preparation suggestions disclaimer
        assert "Preparation Suggestions Notice" in html

    def test_checklist_handles_unknown_company_without_breaking(self, client):
        response = client.get("/company-checklist?company=UnknownCorpXYZ")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # Must fall back cleanly to campus archives without broken links
        assert "Campus Placement Archives" in html
        assert "UnknownCorpXYZ Placement Readiness" in html
