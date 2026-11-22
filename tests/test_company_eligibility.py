"""
Unit tests for Company eligibility calculator (#603)
"""

import pytest
from utils.company_eligibility_service import calculate_company_eligibility


def test_company_eligibility_calculator_eligible():
    company_data = {
        "eligibility": "Minimum 6.5 CGPA in current degree, no active backlogs, all branches eligible.",
        "source_name": "Test Portal",
        "last_updated": "2026-10-01"
    }
    profile = {
        "cgpa": 7.8,
        "backlogs": 0,
        "branch": "Computer Science"
    }
    result = calculate_company_eligibility("TechCorp", profile, company_data=company_data)
    assert result["overall_status"] == "Eligible"
    assert len(result["evaluations"]) >= 3
    cgpa_eval = next(e for e in result["evaluations"] if "CGPA" in e["criteria"])
    assert cgpa_eval["status"] == "Met"
    backlog_eval = next(e for e in result["evaluations"] if "Backlogs" in e["criteria"])
    assert backlog_eval["status"] == "Met"


def test_company_eligibility_calculator_unmet():
    company_data = {
        "eligibility": "Minimum 7.0 CGPA, no active backlogs.",
        "source_name": "Test Portal"
    }
    profile = {
        "cgpa": 6.2,
        "backlogs": 2,
        "branch": "Mechanical"
    }
    result = calculate_company_eligibility("TopTierCorp", profile, company_data=company_data)
    assert result["overall_status"] == "Not Eligible"
    unmet = [e for e in result["evaluations"] if e["status"] == "Unmet"]
    assert len(unmet) >= 2


def test_company_eligibility_calculator_uncertain_defaults():
    company_data = {
        "eligibility": "Minimum 6.5 CGPA.",
        "source_name": "Test Portal"
    }
    # User provides no fields
    profile = {}
    result = calculate_company_eligibility("AmbiguousCorp", profile, company_data=company_data)
    assert result["overall_status"] == "Needs Profile Information"
    assert any(e["status"] == "Uncertain" for e in result["evaluations"])


def test_api_company_eligibility_endpoint(client):
    resp = client.post(
        "/api/company/Google/eligibility",
        json={
            "cgpa": 8.5,
            "backlogs": 0,
            "branch": "Computer Science"
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "eligibility" in data
    assert data["eligibility"]["overall_status"] in ("Eligible", "Conditionally Eligible")
