"""
Tests for Contributor Company Data Validation Tool (#785).
==========================================================
Validates:
1. Default project company JSON data files pass schema validation without errors.
2. Duplicate company names within and across files are detected (including case-insensitive matches).
3. Missing required fields are flagged with exact file and field names.
4. Broken links and invalid URL formats (scheme, domain, spaces) are caught.
5. Invalid date formats (non-ISO 8601) are flagged.
6. Unsupported field formats, invalid types, and empty values are detected.
7. Terminal report and JSON output accurately present file, company, and field labels.
8. CLI exit codes properly signal success (0) and failure (1).
"""

import json
from pathlib import Path
from click.testing import CliRunner

from app import app
from utils.company_data_validator import (
    DEFAULT_COMPANY_DATA_FILES,
    FileValidationResult,
    ValidationError,
    detect_schema_type,
    format_terminal_report,
    is_valid_iso_date,
    is_valid_url_syntax,
    load_json_with_duplicate_key_check,
    main as validator_main,
    validate_company_file,
    validate_paths,
)


def test_default_company_files_exist_and_pass_validation():
    """Verify that all default company data files in data/ exist and pass validation with 0 errors."""
    for file_path in DEFAULT_COMPANY_DATA_FILES:
        path = Path(file_path)
        assert path.exists(), f"Default company data file '{file_path}' must exist."
        result = validate_company_file(path)
        assert result.is_valid, f"File '{file_path}' failed validation with errors: {result.errors}"
        assert result.company_count > 0, f"File '{file_path}' must contain at least 1 company entry."
        assert len(result.errors) == 0


def test_duplicate_keys_in_json_object_detected(tmp_path):
    """Verify that duplicate keys inside the same JSON object are detected and reported."""
    bad_json = """{
        "Acme Corp": {
            "overview": "Overview 1",
            "hiring_process": "Process 1",
            "technical_rounds": "Rounds 1",
            "hr_rounds": "HR 1",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Tips 1",
            "eligibility": "70%",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "https://example.com/careers"
        },
        "Acme Corp": {
            "overview": "Overview 2",
            "hiring_process": "Process 2",
            "technical_rounds": "Rounds 2",
            "hr_rounds": "HR 2",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Tips 2",
            "eligibility": "70%",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "https://example.com/careers"
        }
    }"""
    file_path = tmp_path / "dup_company.json"
    file_path.write_text(bad_json, encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    dup_errors = [e for e in result.errors if e.error_type == "duplicate_company"]
    assert len(dup_errors) >= 1
    assert "Acme Corp" in dup_errors[0].company
    assert dup_errors[0].field == "[duplicate_key]"


def test_case_insensitive_duplicate_company_names_detected(tmp_path):
    """Verify that case-insensitive duplicate company names are reported."""
    data = {
        "Microsoft": {
            "overview": "Tech giant",
            "hiring_process": "Online -> Technical -> HR",
            "technical_rounds": "2 rounds DSA",
            "hr_rounds": "1 round behavioral",
            "frequent_topics": ["Trees", "Graphs"],
            "required_skills": ["C++", "Java"],
            "prep_tips": "Practice LeetCode medium",
            "eligibility": "60% aggregate",
            "last_updated": "2026-11-20",
            "source_name": "Microsoft Careers",
            "source_url": "https://careers.microsoft.com",
        },
        "microsoft": {
            "overview": "Duplicate entry lowercase",
            "hiring_process": "Process",
            "technical_rounds": "Tech",
            "hr_rounds": "HR",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Tips",
            "eligibility": "60%",
            "last_updated": "2026-11-20",
            "source_name": "Source",
            "source_url": "https://careers.microsoft.com",
        },
    }
    file_path = tmp_path / "case_dup.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    dup_errors = [e for e in result.errors if e.error_type == "duplicate_company"]
    assert len(dup_errors) == 1
    assert dup_errors[0].company == "microsoft"
    assert "case-insensitive duplicate" in dup_errors[0].message


def test_missing_required_fields_reported_with_field_and_company_names(tmp_path):
    """Verify that every missing required field is reported with the exact company and field name."""
    incomplete_company = {
        "IncompleteTech": {
            "overview": "Incomplete profile missing several required keys",
            # missing hiring_process
            # missing technical_rounds
            "hr_rounds": "1 HR round",
            "frequent_topics": ["Python"],
            # missing required_skills
            "prep_tips": "Study well",
            "eligibility": "7.0 CGPA",
            "last_updated": "2026-11-20",
            "source_name": "Official Careers",
            # missing source_url
        }
    }
    file_path = tmp_path / "missing_fields.json"
    file_path.write_text(json.dumps(incomplete_company), encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    missing_fields = {e.field for e in result.errors if e.error_type == "missing_field"}
    assert "hiring_process" in missing_fields
    assert "technical_rounds" in missing_fields
    assert "required_skills" in missing_fields
    assert "source_url" in missing_fields

    for err in result.errors:
        assert err.company == "IncompleteTech"
        assert err.file == str(file_path)
        assert err.field != ""
        assert err.remedy != ""


def test_invalid_url_syntax_detection():
    """Verify url syntax validation catches missing schemes, illegal whitespace, and missing domains."""
    valid_urls = [
        "https://google.com/careers",
        "http://careers.microsoft.com/jobs",
        "https://amazon.jobs/en/",
        "http://localhost:5000/careers",
    ]
    for url in valid_urls:
        is_valid, msg = is_valid_url_syntax(url)
        assert is_valid, f"Expected '{url}' to be valid, got: {msg}"

    invalid_urls = [
        ("", "URL cannot be empty"),
        ("ftp://example.com", "Invalid scheme"),
        ("https://careers example.com", "whitespace characters"),
        ("careers.google.com", "Invalid scheme"),
        ("https://", "empty host"),
        ("https://invalid_host_no_tld", "missing a top-level domain"),
        ("javascript:alert(1)", "Invalid scheme"),
        (None, "Expected string"),
    ]
    for bad_url, expected_substr in invalid_urls:
        is_valid, msg = is_valid_url_syntax(bad_url)
        assert not is_valid, f"Expected '{bad_url}' to fail validation"
        assert expected_substr.lower() in msg.lower()


def test_broken_urls_in_company_data_reported_with_field_name(tmp_path):
    """Verify that an invalid source_url in a company file is flagged with field 'source_url'."""
    data = {
        "BadUrlCorp": {
            "overview": "Valid overview",
            "hiring_process": "Valid process",
            "technical_rounds": "Valid rounds",
            "hr_rounds": "Valid HR",
            "frequent_topics": ["DSA"],
            "required_skills": ["Python"],
            "prep_tips": "Valid tips",
            "eligibility": "60%",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "ftp://not-http-url.com",  # Bad scheme
        }
    }
    file_path = tmp_path / "bad_url.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    url_errs = [e for e in result.errors if e.field == "source_url"]
    assert len(url_errs) == 1
    assert url_errs[0].company == "BadUrlCorp"
    assert url_errs[0].error_type == "invalid_url"
    assert "Invalid scheme 'ftp'" in url_errs[0].message


def test_iso_date_validation():
    """Verify ISO 8601 date validator accepts valid calendar dates and rejects invalid formats."""
    valid_dates = ["2026-11-20", "2025-01-01", "2024-02-29"]  # 2024 is leap year
    for dt in valid_dates:
        is_valid, msg = is_valid_iso_date(dt)
        assert is_valid, f"Expected '{dt}' to be valid: {msg}"

    invalid_dates = [
        ("2026/11/20", "does not match ISO format"),
        ("20-11-2026", "does not match ISO format"),
        ("2026-02-30", "Invalid calendar date"),  # Feb 30 never exists
        ("not-a-date", "does not match ISO format"),
        ("1980-01-01", "outside reasonable range"),
        ("", "cannot be empty"),
    ]
    for bad_dt, expected_substr in invalid_dates:
        is_valid, msg = is_valid_iso_date(bad_dt)
        assert not is_valid, f"Expected '{bad_dt}' to fail"
        assert expected_substr.lower() in msg.lower()


def test_unsupported_format_empty_strings_and_empty_lists(tmp_path):
    """Verify that empty strings or empty lists for required fields are caught."""
    data = {
        "EmptyFieldCorp": {
            "overview": "   ",  # whitespace string
            "hiring_process": "Valid",
            "technical_rounds": "Valid",
            "hr_rounds": "Valid",
            "frequent_topics": [],  # empty list
            "required_skills": [""],  # list with empty string element
            "prep_tips": "Valid",
            "eligibility": "Valid",
            "last_updated": "2026-11-20",
            "source_name": "Careers",
            "source_url": "https://example.com/careers",
        }
    }
    file_path = tmp_path / "empty_fields.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    err_fields = {e.field for e in result.errors}
    assert "overview" in err_fields
    assert "frequent_topics" in err_fields
    assert "required_skills[0]" in err_fields


def test_json_syntax_error_reported(tmp_path):
    """Verify that broken JSON syntax reports line and column information."""
    broken_json = '{\n  "Company": {\n    "overview": "missing closing quote\n  }\n}'
    file_path = tmp_path / "syntax_error.json"
    file_path.write_text(broken_json, encoding="utf-8")

    result = validate_company_file(file_path)
    assert not result.is_valid
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.error_type == "syntax_error"
    assert "JSON syntax error" in err.message
    assert err.file == str(file_path)


def test_terminal_report_formatting():
    """Verify that format_terminal_report prints structured output with file, company, and field labels."""
    result = FileValidationResult(file_path="data/test_companies.json", schema_type="hiring_guide", company_count=1)
    result.add_error(
        company="TestCorp",
        field="source_url",
        error_type="invalid_url",
        message="Invalid URL in 'source_url'",
        received_value="bad-url",
        remedy="Provide http or https URL",
    )
    report = format_terminal_report([result])
    assert "data/test_companies.json" in report
    assert "Company: [TestCorp]" in report
    assert "Field  : 'source_url'" in report
    assert "Type   : invalid_url" in report
    assert "Remedy : Provide http or https URL" in report
    assert "[FAIL]" in report


def test_cli_runner_and_json_output(tmp_path, capsys):
    """Verify the CLI runner works with file arguments and returns valid exit codes and JSON output."""
    valid_data = {
        "ValidCorp": {
            "overview": "Leading tech innovator",
            "hiring_process": "Online test followed by technical interview",
            "technical_rounds": "Data structures and algorithm questions",
            "hr_rounds": "Culture fit conversation",
            "frequent_topics": ["Dynamic Programming", "Trees"],
            "required_skills": ["Python", "Problem Solving"],
            "prep_tips": "Review placement preparation notes",
            "eligibility": "60% aggregate without standing backlogs",
            "last_updated": "2026-11-20",
            "source_name": "ValidCorp Careers",
            "source_url": "https://validcorp.example.com/careers",
        }
    }
    file_path = tmp_path / "valid_company.json"
    file_path.write_text(json.dumps(valid_data), encoding="utf-8")

    # Run CLI in JSON mode
    exit_code = validator_main([str(file_path), "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["all_valid"] is True
    assert payload["total_files"] == 1
    assert payload["total_companies"] == 1
    assert payload["total_errors"] == 0


def test_flask_cli_validate_company_data_command():
    """Verify that the Flask CLI 'flask validate-company-data' command executes properly."""
    runner = app.test_cli_runner()
    # Test on default data files
    cli_result = runner.invoke(args=["validate-company-data"])
    assert cli_result.exit_code == 0
    assert "Contributor Company Data Validator" in cli_result.output
    assert "[SUCCESS] All company data files are valid!" in cli_result.output
