"""
Test Suite for data/companies.json JSON Schema and Data Integrity Validation (#855).
===================================================================================
Acceptance Criteria:
1. The test validates the real data/companies.json file and passes.
2. The test fails with readable errors when a required field is missing.
3. The test fails when duplicate company names (case-insensitive) or duplicate keys exist.
4. The test fails when lists are empty or contain invalid items.
5. The test fails when URL format or ISO 8601 date format is invalid.
6. Error messages clearly state the company name and field name.
"""

import json
from pathlib import Path
import pytest

import config
from utils.company_schema_validator import (
    SCHEMA_PATH,
    CompanyValidationError,
    check_duplicate_json_keys,
    is_valid_url,
    validate_companies_data,
)


def test_schema_file_exists_and_is_valid_json():
    """Verify that the JSON schema file exists and parses as valid JSON."""
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    assert schema.get("$schema") is not None
    assert "definitions" in schema
    assert "CompanyProfile" in schema["definitions"]
    assert "required" in schema["definitions"]["CompanyProfile"]


def test_current_companies_json_file_passes_schema_validation():
    """Verify that the current data/companies.json passes all schema requirements without errors."""
    companies_file = Path(config.BASE_DIR) / "data" / "companies.json"
    assert companies_file.exists(), f"companies.json not found at {companies_file}"

    with open(companies_file, "r", encoding="utf-8") as f:
        raw_text = f.read()

    data = json.loads(raw_text)
    errors = validate_companies_data(data, raw_json=raw_text)

    # Print any errors to aid debugging if validation fails
    error_output = "\n".join(str(e) for e in errors)
    assert len(errors) == 0, f"data/companies.json failed schema validation with {len(errors)} error(s):\n{error_output}"
    assert len(data) >= 15, f"Expected at least 15 companies in companies.json, found {len(data)}"


def test_validation_fails_on_missing_required_field():
    """Verify that missing any required field fails validation and clearly reports company and field."""
    invalid_data = {
        "TestCorp": {
            # Missing "overview"
            "hiring_process": "Assessment -> Technical -> HR",
            "technical_rounds": "2 rounds DSA",
            "hr_rounds": "Behavioral",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Practice problems",
            "eligibility": "60% aggregate",
            "last_updated": "2026-11-20",
            "source_name": "TestCorp Careers",
            "source_url": "https://testcorp.com/careers",
        }
    }

    errors = validate_companies_data(invalid_data)
    assert len(errors) >= 1

    missing_errors = [e for e in errors if e.error_type == "missing_required_field"]
    assert len(missing_errors) == 1
    err = missing_errors[0]
    assert err.company == "TestCorp"
    assert err.field == "overview"
    assert "Missing required field 'overview'" in err.message
    assert "TestCorp" in str(err)
    assert "overview" in str(err)


def test_validation_fails_on_duplicate_company_names_case_insensitive():
    """Verify that duplicate company names differing only by case are caught and reported."""
    data_with_duplicates = {
        "Google": {
            "overview": "Technology company",
            "hiring_process": "Online -> Technical -> HR",
            "technical_rounds": "DSA and coding",
            "hr_rounds": "Googliness",
            "frequent_topics": ["Graphs"],
            "required_skills": ["C++"],
            "prep_tips": "Practice",
            "eligibility": "70%",
            "last_updated": "2026-11-20",
            "source_name": "Google Careers",
            "source_url": "https://careers.google.com",
        },
        "google": {
            "overview": "Duplicate entry in lower case",
            "hiring_process": "Process",
            "technical_rounds": "Tech",
            "hr_rounds": "HR",
            "frequent_topics": ["DSA"],
            "required_skills": ["Java"],
            "prep_tips": "Tips",
            "eligibility": "65%",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "https://careers.google.com",
        },
    }

    errors = validate_companies_data(data_with_duplicates)
    dup_errors = [e for e in errors if e.error_type == "duplicate_company"]
    assert len(dup_errors) == 1
    err = dup_errors[0]
    assert err.company == "google"
    assert "Google" in err.message
    assert err.field == "[company_name]"


def test_validation_fails_on_duplicate_json_keys():
    """Verify that duplicate keys within the raw JSON string are flagged."""
    raw_json = """{
        "Acme": {
            "overview": "First overview",
            "overview": "Second duplicate overview",
            "hiring_process": "Process",
            "technical_rounds": "Technical",
            "hr_rounds": "HR",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Tips",
            "eligibility": "60%",
            "last_updated": "2026-11-20",
            "source_name": "Source",
            "source_url": "https://example.com"
        }
    }"""
    data = json.loads(raw_json)
    errors = validate_companies_data(data, raw_json=raw_json)

    dup_key_errors = [e for e in errors if e.error_type == "duplicate_key"]
    assert len(dup_key_errors) == 1
    assert dup_key_errors[0].company == "overview"
    assert "Duplicate key 'overview'" in dup_key_errors[0].message


def test_validation_fails_on_empty_lists():
    """Verify that empty list fields (frequent_topics, required_skills) trigger readable errors."""
    data = {
        "EmptyListCorp": {
            "overview": "Overview text",
            "hiring_process": "Hiring process description",
            "technical_rounds": "Tech round info",
            "hr_rounds": "HR round info",
            "frequent_topics": [],  # Empty list
            "required_skills": ["Python"],
            "prep_tips": "Prep tips",
            "eligibility": "60%",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "https://example.com",
        }
    }

    errors = validate_companies_data(data)
    empty_list_errors = [e for e in errors if e.error_type == "empty_list"]
    assert len(empty_list_errors) == 1
    assert empty_list_errors[0].company == "EmptyListCorp"
    assert empty_list_errors[0].field == "frequent_topics"
    assert "cannot be an empty list" in empty_list_errors[0].message


def test_validation_fails_on_invalid_url_and_date():
    """Verify that invalid URL formats and non-ISO date formats are caught."""
    data = {
        "BadFormatCorp": {
            "overview": "Overview text",
            "hiring_process": "Hiring process description",
            "technical_rounds": "Tech round info",
            "hr_rounds": "HR round info",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Prep tips",
            "eligibility": "60%",
            "last_updated": "20-11-2026",  # DD-MM-YYYY instead of YYYY-MM-DD
            "source_name": "Careers",
            "source_url": "not-a-valid-url",  # Missing scheme and domain
        }
    }

    errors = validate_companies_data(data)
    date_errors = [e for e in errors if e.error_type == "invalid_date_format"]
    url_errors = [e for e in errors if e.error_type == "invalid_url"]

    assert len(date_errors) == 1
    assert date_errors[0].field == "last_updated"
    assert "20-11-2026" in date_errors[0].message

    assert len(url_errors) == 1
    assert url_errors[0].field == "source_url"
    assert "Invalid URL" in url_errors[0].message
