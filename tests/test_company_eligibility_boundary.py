"""
Comprehensive tests for Company Eligibility Checker (#844)

Acceptance Criteria:
1. Eligibility results are correct for sample profiles including boundary values.
2. Missing criteria show 'unknown', never 'eligible'.
3. Profile values are private and validated.
4. Tests cover boundaries and missing data.
5. 'only companies I am eligible for' filter in search / companies view.
6. Clear drive variation disclaimer included in results.
"""

import pytest
from utils.company_eligibility_service import (
    calculate_company_eligibility,
    load_company_data,
)


def test_eligibility_sample_profiles_met():
    """Eligible when candidate meets or exceeds all criteria."""
    company_data = {
        "min_cgpa": 7.0,
        "max_backlogs": 0,
        "branches": ["CS", "IT", "ECE"],
        "eligibility_source": "Test Careers Portal"
    }

    # Case 1: Exceeds CGPA, 0 backlogs, exact branch match
    profile_1 = {"cgpa": 8.5, "backlogs": 0, "branch": "Computer Science"}
    res_1 = calculate_company_eligibility("TechCorp", profile_1, company_data=company_data)
    assert res_1["eligible"] is True
    assert res_1["overall_status"] == "Eligible"
    assert res_1["status"] == "eligible"
    assert "Meets all" in res_1["reason"]
    assert "Criteria vary by drive" in res_1["drive_disclaimer"]


def test_eligibility_boundary_cgpa_exact_match():
    """Boundary test: exactly on the minimum CGPA boundary."""
    company_data = {
        "min_cgpa": 6.5,
        "max_backlogs": 1,
        "branches": ["All"],
        "eligibility_source": "Test Drive Circular"
    }

    # Exactly 6.5 CGPA -> Should be eligible
    profile_exact = {"cgpa": 6.5, "backlogs": 1, "branch": "Mechanical Engineering"}
    res_exact = calculate_company_eligibility("BoundaryCorp", profile_exact, company_data=company_data)
    assert res_exact["eligible"] is True
    assert res_exact["overall_status"] == "Eligible"

    # Just below: 6.49 CGPA -> Should NOT be eligible
    profile_below = {"cgpa": 6.49, "backlogs": 1, "branch": "Mechanical Engineering"}
    res_below = calculate_company_eligibility("BoundaryCorp", profile_below, company_data=company_data)
    assert res_below["eligible"] is False
    assert res_below["overall_status"] == "Not Eligible"
    assert "below required minimum" in res_below["reason"]

    # Just above: 6.51 CGPA -> Should be eligible
    profile_above = {"cgpa": 6.51, "backlogs": 1, "branch": "Mechanical Engineering"}
    res_above = calculate_company_eligibility("BoundaryCorp", profile_above, company_data=company_data)
    assert res_above["eligible"] is True


def test_eligibility_boundary_backlogs():
    """Boundary test: backlogs limit boundary."""
    company_data = {
        "min_cgpa": 6.0,
        "max_backlogs": 0,
        "branches": ["All"],
        "eligibility_source": "Recruiter FAQ"
    }

    # 0 backlogs allowed, student has 0 -> eligible
    res_0 = calculate_company_eligibility("ZeroBacklogCorp", {"cgpa": 7.0, "backlogs": 0, "branch": "CS"}, company_data=company_data)
    assert res_0["eligible"] is True

    # 0 backlogs allowed, student has 1 -> not eligible
    res_1 = calculate_company_eligibility("ZeroBacklogCorp", {"cgpa": 7.0, "backlogs": 1, "branch": "CS"}, company_data=company_data)
    assert res_1["eligible"] is False
    assert res_1["overall_status"] == "Not Eligible"
    assert "exceeds allowed limit" in res_1["reason"]


def test_eligibility_missing_criteria_shows_unknown_never_eligible():
    """Acceptance criterion: Missing criteria show 'unknown', never 'eligible'."""
    # Scenario A: Company data has no criteria specified at all
    empty_company = {
        "source_name": "Test Portal"
    }
    profile = {"cgpa": 9.5, "backlogs": 0, "branch": "Computer Science"}
    res_a = calculate_company_eligibility("UnknownCorp", profile, company_data=empty_company)
    assert res_a["overall_status"] == "Unknown"
    assert res_a["eligible"] is False
    assert "unknown" in res_a["status"]

    # Scenario B: Company has min_cgpa but backlog/branch rules are missing/unspecified
    partial_company = {
        "min_cgpa": 7.0,
        "eligibility_source": "Partial Circular"
    }
    res_b = calculate_company_eligibility("PartialCorp", profile, company_data=partial_company)
    assert res_b["overall_status"] == "Unknown"
    assert res_b["eligible"] is False

    # Scenario C: Candidate has missing CGPA in profile
    strict_company = {
        "min_cgpa": 7.0,
        "max_backlogs": 0,
        "branches": ["CS"],
        "eligibility_source": "Strict Circular"
    }
    missing_cgpa_profile = {"backlogs": 0, "branch": "CS"}
    res_c = calculate_company_eligibility("StrictCorp", missing_cgpa_profile, company_data=strict_company)
    assert res_c["overall_status"] == "Unknown"
    assert res_c["eligible"] is False
    assert "CGPA not provided" in res_c["reason"]

    # Scenario D: Candidate has missing branch in profile
    missing_branch_profile = {"cgpa": 8.0, "backlogs": 0}
    res_d = calculate_company_eligibility("StrictCorp", missing_branch_profile, company_data=strict_company)
    assert res_d["overall_status"] == "Unknown"
    assert res_d["eligible"] is False
    assert "Branch not provided" in res_d["reason"]


def test_eligibility_disallowed_branch():
    """Candidate has good CGPA and 0 backlogs but non-circuital branch."""
    company_data = {
        "min_cgpa": 6.5,
        "max_backlogs": 0,
        "branches": ["CS", "IT", "ECE"],
        "eligibility_source": "Circuital Drive"
    }
    civil_profile = {"cgpa": 8.8, "backlogs": 0, "branch": "Civil Engineering"}
    res = calculate_company_eligibility("TechCorp", civil_profile, company_data=company_data)
    assert res["eligible"] is False
    assert res["overall_status"] == "Not Eligible"
    assert "not in allowed branches" in res["reason"]


def test_open_to_all_branches():
    """When branches list includes 'All', any branch is accepted."""
    company_data = {
        "min_cgpa": 6.0,
        "max_backlogs": 0,
        "branches": ["All"],
        "eligibility_source": "Mass Hiring Drive"
    }
    mech_profile = {"cgpa": 7.2, "backlogs": 0, "branch": "Mechanical Engineering"}
    res = calculate_company_eligibility("MassCorp", mech_profile, company_data=company_data)
    assert res["eligible"] is True
    assert res["overall_status"] == "Eligible"


def test_api_company_eligibility_endpoint_full(client):
    """Verifies POST /api/company/<name>/eligibility endpoint."""
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
    assert data["eligibility"]["overall_status"] == "Eligible"
    assert data["eligibility"]["eligible"] is True
    assert "drive_disclaimer" in data["eligibility"]


def test_companies_view_eligible_only_filter(client):
    """Verifies the 'only companies I am eligible for' filter in /companies."""
    # First, test regular view (all companies returned)
    resp_all = client.get("/companies")
    assert resp_all.status_code == 200

    # With eligible_only=true
    resp_filtered = client.get("/companies?eligible_only=true")
    assert resp_filtered.status_code == 200
    assert "Only companies I am eligible for" in resp_filtered.get_data(as_text=True)
    assert "Criteria vary by drive" in resp_filtered.get_data(as_text=True)


def test_student_profile_validation(client):
    """Verifies that student profile validates CGPA and backlog boundaries."""
    # Valid submission
    resp_valid = client.post(
        "/profile",
        data={
            "full_name": "Test Student",
            "department": "Computer Science",
            "grad_year": "2026",
            "cgpa": "8.5",
            "backlogs": "0"
        },
        follow_redirects=True
    )
    assert resp_valid.status_code == 200

    # Invalid CGPA: > 10.0
    resp_invalid_cgpa = client.post(
        "/profile",
        data={
            "full_name": "Test Student",
            "department": "Computer Science",
            "grad_year": "2026",
            "cgpa": "11.5",
            "backlogs": "0"
        },
        follow_redirects=True
    )
    assert "CGPA must be between 0.0 and 10.0" in resp_invalid_cgpa.get_data(as_text=True)

    # Invalid Backlogs: < 0
    resp_invalid_backlogs = client.post(
        "/profile",
        data={
            "full_name": "Test Student",
            "department": "Computer Science",
            "grad_year": "2026",
            "cgpa": "8.0",
            "backlogs": "-2"
        },
        follow_redirects=True
    )
    assert "Active backlogs cannot be negative" in resp_invalid_backlogs.get_data(as_text=True)
