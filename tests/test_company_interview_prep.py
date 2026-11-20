"""
Unit and Integration Tests for Company-Specific Interview Preparation Tips (#541).

Verifies Acceptance Criteria:
1. A new company can be added by editing the data file only.
2. Every entry has a last-updated date.
3. Unknown companies fall back to general tips.
4. All guides are labeled as community-contributed.
5. REST API endpoints (/api/interview/company-prep and /api/interview/company-prep/<name>) work accurately.
6. The interview template renders the selector, community-contributed badge, and last-updated date.
7. Contribution template data/company_contribution_template.json is valid and conforms to schema.
"""

import json
from pathlib import Path
from datetime import datetime
import pytest
from unittest.mock import patch

import config
from app import app
from utils.company_interview_prep_service import (
    get_company_prep_file_path,
    load_company_prep_data,
    get_available_companies,
    get_company_prep,
    validate_company_prep_entry,
    format_last_updated_date,
    DEFAULT_GENERAL_PREP,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. Acceptance Criterion 2: Every entry has a last-updated date & valid schema
# ==============================================================================

class TestCompanyPrepDataIntegrity:
    """Tests ensuring data/company_interview_prep.json adheres to schema and date rules."""

    def test_data_file_exists_and_is_valid_json(self):
        file_path = get_company_prep_file_path()
        assert file_path.exists(), f"Data file not found at {file_path}"
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Data file root must be a JSON dictionary"
        assert len(data) >= 5, "Data file should contain at least 5 companies"
        assert "General" in data, "Data file must contain a 'General' fallback entry"

    def test_every_entry_has_last_updated_date(self):
        """Acceptance Criterion 2: Every entry has a last-updated date."""
        data = load_company_prep_data()
        for company_name, entry in data.items():
            assert "last_updated" in entry, f"'{company_name}' missing 'last_updated'"
            last_updated = entry["last_updated"]
            assert isinstance(last_updated, str) and last_updated.strip(), (
                f"'{company_name}' has invalid or empty 'last_updated'"
            )
            # Verify valid ISO date format (YYYY-MM-DD)
            try:
                dt = datetime.strptime(last_updated.strip(), "%Y-%m-%d")
                assert dt.year >= 2025, f"'{company_name}' date year seems unreasonably old ({dt.year})"
            except ValueError:
                pytest.fail(f"'{company_name}' has invalid date format: '{last_updated}'. Expected YYYY-MM-DD.")

    def test_every_entry_has_required_fields_and_valid_types(self):
        """Verifies typical_rounds, commonly_tested_topics, and preparation_tips."""
        data = load_company_prep_data()
        for company_name, entry in data.items():
            is_valid, errors = validate_company_prep_entry(entry)
            assert is_valid, f"Validation failed for '{company_name}': {', '.join(errors)}"
            assert entry.get("community_contributed") is True, (
                f"'{company_name}' should have 'community_contributed: true'"
            )

    def test_contribution_template_is_valid(self):
        """Verifies that data/company_contribution_template.json exists and is valid."""
        template_path = Path(config.BASE_DIR) / "data" / "company_contribution_template.json"
        assert template_path.exists(), f"Contribution template not found at {template_path}"
        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        is_valid, errors = validate_company_prep_entry(template)
        assert is_valid, f"Contribution template failed schema validation: {', '.join(errors)}"
        assert template.get("community_contributed") is True


# ==============================================================================
# 2. Acceptance Criterion 1: A new company can be added by editing data file only
# ==============================================================================

class TestAddCompanyByEditingDataFileOnly:
    """Acceptance Criterion 1: Verifies new company is recognized dynamically without code changes."""

    def test_new_company_in_data_file_automatically_appears(self, tmp_path):
        # Create a mock json data file
        mock_data = {
            "General": DEFAULT_GENERAL_PREP.copy(),
            "Netflix": {
                "company_name": "Netflix",
                "typical_rounds": [
                    "Round 1: Recruiter Call & Cultural Overview",
                    "Round 2: Technical Screen (Coding & System Architecture)",
                    "Round 3: Virtual Onsite 1 (Deep-dive Systems)",
                    "Round 4: Virtual Onsite 2 (Culture & Leadership Fit)"
                ],
                "commonly_tested_topics": [
                    "Distributed Systems & Scalability",
                    "Microservices Architecture",
                    "Advanced Concurrency & Multithreading",
                    "Data Structures & Optimization"
                ],
                "preparation_tips": [
                    "Read the Netflix Culture Memo thoroughly.",
                    "Be prepared to design resilient, highly available distributed systems.",
                    "Demonstrate high freedom and responsibility mindset."
                ],
                "last_updated": "2026-11-18",
                "community_contributed": True
            }
        }
        mock_file = tmp_path / "company_interview_prep.json"
        with open(mock_file, "w", encoding="utf-8") as f:
            json.dump(mock_data, f)

        # Service reads mock file without any code changes
        companies = get_available_companies(mock_file)
        assert "Netflix" in companies
        assert "General" in companies

        prep = get_company_prep("Netflix", mock_file)
        assert prep["company_name"] == "Netflix"
        assert prep["is_fallback"] is False
        assert prep["last_updated"] == "2026-11-18"
        assert prep["community_contributed"] is True
        assert len(prep["typical_rounds"]) == 4

        # Dynamically append another new company to the same file
        mock_data["Spotify"] = {
            "company_name": "Spotify",
            "typical_rounds": ["Round 1: Online Coding", "Round 2: System Design", "Round 3: Values Interview"],
            "commonly_tested_topics": ["Audio Streaming Architecture", "Graphs", "API Design"],
            "preparation_tips": ["Know agile squad dynamics.", "Explain latency trade-offs."],
            "last_updated": "2026-11-18",
            "community_contributed": True
        }
        with open(mock_file, "w", encoding="utf-8") as f:
            json.dump(mock_data, f)

        # Confirm Spotify is now immediately discovered
        updated_companies = get_available_companies(mock_file)
        assert "Spotify" in updated_companies
        spotify_prep = get_company_prep("Spotify", mock_file)
        assert spotify_prep["company_name"] == "Spotify"
        assert spotify_prep["is_fallback"] is False


# ==============================================================================
# 3. Acceptance Criterion 3: Unknown companies fall back to general tips
# ==============================================================================

class TestUnknownCompanyFallback:
    """Acceptance Criterion 3: Unknown companies fall back to general tips."""

    def test_unknown_company_falls_back_to_general_tips(self):
        prep = get_company_prep("FictionalStartupXYZ12345")
        assert prep["is_fallback"] is True
        assert prep["requested_company"] == "FictionalStartupXYZ12345"
        assert prep["community_contributed"] is True
        assert "last_updated" in prep
        assert len(prep["typical_rounds"]) >= 3
        assert len(prep["commonly_tested_topics"]) >= 3
        assert len(prep["preparation_tips"]) >= 3

    def test_none_and_empty_company_falls_back_to_general(self):
        prep_none = get_company_prep(None)
        assert prep_none["is_fallback"] is True
        assert prep_none["community_contributed"] is True

        prep_empty = get_company_prep("   ")
        assert prep_empty["is_fallback"] is True
        assert prep_empty["community_contributed"] is True

    def test_case_insensitive_matching_for_known_companies(self):
        # Google in different cases should NOT fallback
        prep_lower = get_company_prep("google")
        assert prep_lower["is_fallback"] is False
        assert prep_lower["company_name"].lower() == "google"

        prep_upper = get_company_prep("GOOGLE")
        assert prep_upper["is_fallback"] is False

        prep_mixed = get_company_prep("tCs")
        assert prep_mixed["is_fallback"] is False

        prep_accenture = get_company_prep("accenture")
        assert prep_accenture["is_fallback"] is False


# ==============================================================================
# 4. Service Utilities & Validation Helpers
# ==============================================================================

class TestCompanyPrepServiceHelpers:
    """Tests utility functions and entry validation logic."""

    def test_validate_entry_detects_missing_fields(self):
        # Missing last_updated
        bad_entry_1 = {
            "typical_rounds": ["Round 1"],
            "commonly_tested_topics": ["DSA"],
            "preparation_tips": ["Practice"]
        }
        is_valid, errors = validate_company_prep_entry(bad_entry_1)
        assert not is_valid
        assert any("last_updated" in e for e in errors)

        # Invalid date format
        bad_entry_2 = {
            "last_updated": "18-11-2026",
            "typical_rounds": ["Round 1"],
            "commonly_tested_topics": ["DSA"],
            "preparation_tips": ["Practice"]
        }
        is_valid, errors = validate_company_prep_entry(bad_entry_2)
        assert not is_valid
        assert any("format" in e for e in errors)

        # Empty lists
        bad_entry_3 = {
            "last_updated": "2026-11-18",
            "typical_rounds": [],
            "commonly_tested_topics": ["DSA"],
            "preparation_tips": ["Practice"]
        }
        is_valid, errors = validate_company_prep_entry(bad_entry_3)
        assert not is_valid
        assert any("typical_rounds" in e for e in errors)

    def test_format_last_updated_date(self):
        assert format_last_updated_date("2026-11-18") == "Nov 18, 2026"
        assert format_last_updated_date("") == "Unknown"
        assert format_last_updated_date(None) == "Unknown"
        assert format_last_updated_date("not-a-date") == "not-a-date"


# ==============================================================================
# 5. REST API Endpoints Integration
# ==============================================================================

class TestCompanyPrepApiEndpoints:
    """Tests /api/interview/company-prep and /api/interview/company-prep/<company_name>."""

    def test_api_get_company_prep_list(self, client):
        resp = client.get("/api/interview/company-prep")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert isinstance(payload["companies"], list)
        assert "General" in payload["companies"]
        assert "Google" in payload["companies"]
        assert "Amazon" in payload["companies"]
        assert payload["data"]["community_contributed"] is True

    def test_api_get_company_prep_list_with_query_param(self, client):
        resp = client.get("/api/interview/company-prep?company=Google")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert payload["selected_company"] == "Google"
        assert payload["is_fallback"] is False
        assert payload["data"]["company_name"] == "Google"

    def test_api_get_specific_known_company(self, client):
        resp = client.get("/api/interview/company-prep/Google")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert payload["company"] == "Google"
        assert payload["is_fallback"] is False
        assert payload["data"]["community_contributed"] is True
        assert len(payload["data"]["typical_rounds"]) >= 3
        assert len(payload["data"]["commonly_tested_topics"]) >= 3
        assert len(payload["data"]["preparation_tips"]) >= 3
        assert "last_updated" in payload["data"]

    def test_api_get_unknown_company_falls_back(self, client):
        """Unknown company over API falls back to general tips with is_fallback: True."""
        resp = client.get("/api/interview/company-prep/NonExistentStartupXYZ99")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert payload["company"] == "NonExistentStartupXYZ99"
        assert payload["is_fallback"] is True
        assert payload["data"]["community_contributed"] is True
        assert "last_updated" in payload["data"]
        assert len(payload["data"]["typical_rounds"]) >= 3


# ==============================================================================
# 6. Template Rendering Integration
# ==============================================================================

class TestInterviewTemplateRendering:
    """Verifies that interview.html renders the selector, community badge, and last-updated date."""

    def test_template_contains_company_prep_elements(self):
        template_path = Path(config.BASE_DIR) / "templates" / "interview.html"
        assert template_path.exists()
        content = template_path.read_text(encoding="utf-8")

        # Elements required by Issue #541
        assert "companyPrepSelector" in content, "Selector element #companyPrepSelector missing"
        assert "Community-Contributed" in content, "Community-Contributed label missing"
        assert "companyPrepLastUpdated" in content, "Last-updated element missing"
        assert "companyPrepRoundsList" in content, "Typical rounds list missing"
        assert "companyPrepTopicsList" in content, "Tested topics list missing"
        assert "companyPrepTipsList" in content, "Preparation tips list missing"
        assert "companyPrepFallbackBadge" in content, "Fallback badge missing"
        assert "companyPrepFallbackAlert" in content, "Fallback alert missing"
