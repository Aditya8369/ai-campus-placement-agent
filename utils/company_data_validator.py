"""
Contributor Company Data Validation Tool (#785).
================================================
Command-line and programmatic validator for contributor company JSON files.

Validates:
1. JSON syntax, UTF-8 encoding, and duplicate keys in objects.
2. Required fields for company profiles and interview preparation guides.
3. Duplicate company names within and across files (case-insensitive).
4. Date formats (ISO 8601 YYYY-MM-DD validation).
5. Broken links, URL syntax, and protocol validation (HTTP/HTTPS).
6. Unsupported field formats, invalid types, and empty values.
7. Clear, contributor-friendly error reporting pinpointing exact file and field names.

Usage:
  python utils/company_data_validator.py [paths...]
  python -m utils.company_data_validator [paths...]
  flask validate-company-data [paths...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Common default company JSON files to validate if no arguments are provided
DEFAULT_COMPANY_DATA_FILES: List[str] = [
    "data/companies.json",
    "data/company_interview_prep.json",
    "data/company_contribution_template.json",
]

# Regex for strict ISO 8601 Date: YYYY-MM-DD
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ValidationError:
    """Represents a single validation issue pinpointing exact file and field names."""
    file: str
    company: str
    field: str
    error_type: str  # 'missing_field', 'duplicate_company', 'invalid_url', 'invalid_format', 'broken_link', 'syntax_error'
    message: str
    severity: str = "error"  # 'error' or 'warning'
    received_value: Any = None
    remedy: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.received_value is not None and not isinstance(self.received_value, (str, int, float, bool, list, dict)):
            d["received_value"] = str(self.received_value)
        return d


@dataclass
class FileValidationResult:
    """Aggregated validation findings for a single company data file."""
    file_path: str
    schema_type: str
    company_count: int = 0
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(
        self,
        company: str,
        field: str,
        error_type: str,
        message: str,
        received_value: Any = None,
        remedy: str = "",
    ) -> None:
        self.errors.append(
            ValidationError(
                file=self.file_path,
                company=company,
                field=field,
                error_type=error_type,
                message=message,
                severity="error",
                received_value=received_value,
                remedy=remedy,
            )
        )

    def add_warning(
        self,
        company: str,
        field: str,
        error_type: str,
        message: str,
        received_value: Any = None,
        remedy: str = "",
    ) -> None:
        self.warnings.append(
            ValidationError(
                file=self.file_path,
                company=company,
                field=field,
                error_type=error_type,
                message=message,
                severity="warning",
                received_value=received_value,
                remedy=remedy,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "schema_type": self.schema_type,
            "company_count": self.company_count,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


# =====================================================================
# URL & Format Validation Helpers
# =====================================================================

def is_valid_url_syntax(url: Any) -> Tuple[bool, str]:
    """
    Validates URL syntax.
    Returns (True, "") if valid, or (False, reason) if malformed.
    """
    if not isinstance(url, str):
        return False, f"Expected string for URL, got {type(url).__name__}"

    url_clean = url.strip()
    if not url_clean:
        return False, "URL cannot be empty"

    if any(char in url_clean for char in (" ", "\t", "\n", "\r")):
        return False, "URL contains illegal whitespace characters"

    try:
        parsed = urllib.parse.urlparse(url_clean)
    except Exception as exc:
        return False, f"Could not parse URL: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Invalid scheme '{parsed.scheme}'. URL must start with http:// or https://"

    if not parsed.netloc:
        return False, "URL is missing a valid domain/host"

    host = parsed.netloc.split(":")[0].strip()
    if not host:
        return False, "URL contains an empty host"

    # Host must have at least one dot or be localhost
    if host.lower() != "localhost" and "." not in host:
        return False, f"Host '{host}' is missing a top-level domain (TLD)"

    # Check for invalid characters in host
    if any(c in host for c in ('"', "'", "<", ">", "\\", ";", "{", "}")):
        return False, f"Host '{host}' contains illegal characters"

    return True, ""


def check_live_url(url: str, timeout: float = 3.0) -> Tuple[bool, str]:
    """
    Optional live check to verify URL reachability via HTTP request.
    Returns (True, "") or (False, reason).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (AI-Campus-Placement-Agent-Validator/1.0)"},
        )
        # Try HEAD request first for speed
        req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status < 400:
                return True, ""
            return False, f"HTTP status {resp.status}"
    except urllib.error.HTTPError as e:
        # Some servers block HEAD or return 403 to bots, try GET with range if 403/405
        if e.code in (403, 405):
            try:
                get_req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (AI-Campus-Placement-Agent-Validator/1.0)",
                        "Range": "bytes=0-10",
                    },
                )
                with urllib.request.urlopen(get_req, timeout=timeout) as resp:
                    if resp.status < 400:
                        return True, ""
            except Exception:
                pass
        return False, f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}"
    except TimeoutError:
        return False, "Connection timed out"
    except Exception as exc:
        return False, f"Request failed: {exc}"


def is_valid_iso_date(val: Any) -> Tuple[bool, str]:
    """
    Validates that a value is a valid calendar date in ISO 8601 format (YYYY-MM-DD).
    Returns (True, "") or (False, reason).
    """
    if not isinstance(val, str):
        return False, f"Expected date string, got {type(val).__name__}"

    clean = val.strip()
    if not clean:
        return False, "Date string cannot be empty"

    if not ISO_DATE_REGEX.match(clean):
        return False, f"Date '{clean}' does not match ISO format YYYY-MM-DD"

    try:
        parsed_dt = datetime.strptime(clean, "%Y-%m-%d")
    except ValueError as exc:
        return False, f"Invalid calendar date '{clean}': {exc}"

    if parsed_dt.year < 2000 or parsed_dt.year > 2050:
        return False, f"Year {parsed_dt.year} is outside reasonable range (2000-2050)"

    return True, ""


# =====================================================================
# JSON Loading with Duplicate Key Detection
# =====================================================================

def load_json_with_duplicate_key_check(file_path: Union[str, Path]) -> Tuple[Any, List[Tuple[str, str]]]:
    """
    Parses a JSON file while detecting duplicate keys in objects.
    Standard json.load silently overwrites duplicates; this tracks them explicitly.

    Returns:
        (parsed_data, list_of_duplicate_key_tuples)
    """
    duplicates: List[Tuple[str, str]] = []

    def make_unique_pairs_hook(context_name: str = ""):
        def hook(pairs: List[Tuple[str, Any]]):
            seen: Set[str] = set()
            d: Dict[str, Any] = {}
            for k, v in pairs:
                k_clean = str(k).strip()
                if k_clean.lower() in seen:
                    duplicates.append((k, f"Key '{k}' is defined multiple times in the same JSON object."))
                seen.add(k_clean.lower())
                d[k] = v
            return d
        return hook

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    data = json.loads(content, object_pairs_hook=make_unique_pairs_hook())
    return data, duplicates


# =====================================================================
# Schema Identifiers & Field Checkers
# =====================================================================

def detect_schema_type(data: Any) -> str:
    """
    Infers the company data schema format:
      - 'hiring_guide': mapping of company name to hiring guide profile (e.g. companies.json)
      - 'interview_prep': mapping of company name to interview prep guide (e.g. company_interview_prep.json)
      - 'single_company': single dictionary representing one company
      - 'list_of_companies': list of company dictionaries
      - 'unknown': unrecognized structure
    """
    if isinstance(data, dict):
        # Check if it's a single company contribution template or profile
        if "company_name" in data and ("typical_rounds" in data or "hiring_process" in data):
            return "single_company"

        # Check values of top-level dictionary
        values = list(data.values())
        if values and isinstance(values[0], dict):
            first_val = values[0]
            if "typical_rounds" in first_val or "commonly_tested_topics" in first_val:
                return "interview_prep"
            if "hiring_process" in first_val or "technical_rounds" in first_val or "overview" in first_val:
                return "hiring_guide"

        return "hiring_guide"

    if isinstance(data, list):
        return "list_of_companies"

    return "unknown"


# Required fields for Hiring Guide profiles (e.g., data/companies.json)
HIRING_GUIDE_REQUIRED_FIELDS: Dict[str, Tuple[type, str]] = {
    "overview": (str, "Company summary paragraph"),
    "hiring_process": (str, "Overview of recruitment stages"),
    "technical_rounds": (str, "Details of technical interview rounds"),
    "hr_rounds": (str, "Details of HR and cultural rounds"),
    "frequent_topics": (list, "List of frequently tested interview topics"),
    "required_skills": (list, "List of core technical and soft skills"),
    "prep_tips": (str, "Actionable candidate preparation recommendations"),
    "eligibility": (str, "Academic and backlog eligibility criteria"),
    "last_updated": (str, "Last revision date in ISO format (YYYY-MM-DD)"),
    "source_name": (str, "Title of official source or careers portal"),
    "source_url": (str, "Canonical URL of careers portal or recruitment announcement"),
}

# Required fields for Interview Prep guides (e.g., data/company_interview_prep.json)
INTERVIEW_PREP_REQUIRED_FIELDS: Dict[str, Tuple[type, str]] = {
    "company_name": (str, "Display name of the company"),
    "typical_rounds": (list, "List of interview stages and round descriptions"),
    "commonly_tested_topics": (list, "List of topics tested during technical rounds"),
    "preparation_tips": (list, "List of company-specific preparation tips"),
    "last_updated": (str, "Last revision date in ISO format (YYYY-MM-DD)"),
}


def _validate_hiring_guide_entry(
    company_name: str,
    entry: Any,
    result: FileValidationResult,
    check_live_links: bool = False,
    strict: bool = False,
) -> None:
    """Validates an individual company entry under the hiring guide schema."""
    if not isinstance(entry, dict):
        result.add_error(
            company=company_name,
            field="[entry]",
            error_type="unsupported_format",
            message=f"Company profile for '{company_name}' must be a JSON object, got {type(entry).__name__}.",
            remedy="Structure the company profile as a key-value dictionary.",
        )
        return

    # Check required fields
    for field_name, (expected_type, desc) in HIRING_GUIDE_REQUIRED_FIELDS.items():
        if field_name not in entry:
            result.add_error(
                company=company_name,
                field=field_name,
                error_type="missing_field",
                message=f"Missing required field '{field_name}' ({desc}).",
                remedy=f"Add field '{field_name}' with a valid {expected_type.__name__} value.",
            )
            continue

        val = entry[field_name]

        # Check type
        if not isinstance(val, expected_type):
            result.add_error(
                company=company_name,
                field=field_name,
                error_type="unsupported_format",
                message=f"Field '{field_name}' has invalid type '{type(val).__name__}' (expected {expected_type.__name__}).",
                received_value=val,
                remedy=f"Change '{field_name}' to a valid {expected_type.__name__}.",
            )
            continue

        # Check non-empty for strings
        if expected_type == str:
            if not val.strip():
                result.add_error(
                    company=company_name,
                    field=field_name,
                    error_type="unsupported_format",
                    message=f"Field '{field_name}' cannot be an empty string.",
                    remedy=f"Provide meaningful content for '{field_name}'.",
                )

        # Check non-empty for lists
        if expected_type == list:
            if len(val) == 0:
                result.add_error(
                    company=company_name,
                    field=field_name,
                    error_type="unsupported_format",
                    message=f"Field '{field_name}' cannot be an empty list.",
                    remedy=f"Provide at least one non-empty string entry in '{field_name}'.",
                )
            else:
                for idx, item in enumerate(val):
                    if not isinstance(item, str) or not item.strip():
                        result.add_error(
                            company=company_name,
                            field=f"{field_name}[{idx}]",
                            error_type="unsupported_format",
                            message=f"Element at index {idx} in '{field_name}' must be a non-empty string.",
                            received_value=item,
                            remedy="Ensure all list elements are non-empty text strings.",
                        )

    # Date Validation
    if "last_updated" in entry and isinstance(entry["last_updated"], str):
        is_valid_date, date_err = is_valid_iso_date(entry["last_updated"])
        if not is_valid_date:
            result.add_error(
                company=company_name,
                field="last_updated",
                error_type="unsupported_format",
                message=f"Invalid date format in 'last_updated': {date_err}.",
                received_value=entry["last_updated"],
                remedy="Use ISO 8601 calendar date format 'YYYY-MM-DD' (e.g. '2026-11-15').",
            )

    # URL Validation
    if "source_url" in entry and isinstance(entry["source_url"], str):
        is_valid_url, url_err = is_valid_url_syntax(entry["source_url"])
        if not is_valid_url:
            result.add_error(
                company=company_name,
                field="source_url",
                error_type="invalid_url",
                message=f"Invalid URL in 'source_url': {url_err}.",
                received_value=entry["source_url"],
                remedy="Provide a valid canonical URL starting with http:// or https:// with a valid domain name.",
            )
        elif check_live_links:
            is_live, live_err = check_live_url(entry["source_url"])
            if not is_live:
                if strict:
                    result.add_error(
                        company=company_name,
                        field="source_url",
                        error_type="broken_link",
                        message=f"Broken or unreachable link: {live_err}.",
                        received_value=entry["source_url"],
                        remedy="Verify that the target careers URL is live and publicly accessible.",
                    )
                else:
                    result.add_warning(
                        company=company_name,
                        field="source_url",
                        error_type="broken_link",
                        message=f"Unreachable link warning: {live_err}.",
                        received_value=entry["source_url"],
                        remedy="Verify that the link is reachable without bot-detection or authentication blocks.",
                    )

    # Optional verification_status check
    if "verification_status" in entry:
        v_status = entry["verification_status"]
        if not isinstance(v_status, str) or v_status not in ("verified", "unverified", "general_guidance", "community"):
            result.add_warning(
                company=company_name,
                field="verification_status",
                error_type="unsupported_format",
                message=f"Unknown verification_status '{v_status}'. Recommended: 'verified', 'unverified', or 'community'.",
                received_value=v_status,
                remedy="Set verification_status to 'verified' or 'community'.",
            )


def _validate_interview_prep_entry(
    company_name: str,
    entry: Any,
    result: FileValidationResult,
    check_live_links: bool = False,
    strict: bool = False,
) -> None:
    """Validates an individual company entry under the interview preparation schema."""
    if not isinstance(entry, dict):
        result.add_error(
            company=company_name,
            field="[entry]",
            error_type="unsupported_format",
            message=f"Interview prep entry for '{company_name}' must be a JSON object, got {type(entry).__name__}.",
            remedy="Structure the entry as a key-value dictionary.",
        )
        return

    # Check required fields
    for field_name, (expected_type, desc) in INTERVIEW_PREP_REQUIRED_FIELDS.items():
        if field_name not in entry:
            result.add_error(
                company=company_name,
                field=field_name,
                error_type="missing_field",
                message=f"Missing required field '{field_name}' ({desc}).",
                remedy=f"Add field '{field_name}' with a valid {expected_type.__name__} value.",
            )
            continue

        val = entry[field_name]

        if not isinstance(val, expected_type):
            result.add_error(
                company=company_name,
                field=field_name,
                error_type="unsupported_format",
                message=f"Field '{field_name}' has invalid type '{type(val).__name__}' (expected {expected_type.__name__}).",
                received_value=val,
                remedy=f"Change '{field_name}' to a valid {expected_type.__name__}.",
            )
            continue

        if expected_type == str and not val.strip():
            result.add_error(
                company=company_name,
                field=field_name,
                error_type="unsupported_format",
                message=f"Field '{field_name}' cannot be an empty string.",
                remedy=f"Provide meaningful text for '{field_name}'.",
            )

        if expected_type == list:
            if len(val) == 0:
                result.add_error(
                    company=company_name,
                    field=field_name,
                    error_type="unsupported_format",
                    message=f"Field '{field_name}' cannot be an empty list.",
                    remedy=f"Provide at least one non-empty string entry in '{field_name}'.",
                )
            else:
                for idx, item in enumerate(val):
                    if not isinstance(item, str) or not item.strip():
                        result.add_error(
                            company=company_name,
                            field=f"{field_name}[{idx}]",
                            error_type="unsupported_format",
                            message=f"Element at index {idx} in '{field_name}' must be a non-empty string.",
                            received_value=item,
                            remedy="Ensure all list elements are non-empty text strings.",
                        )

    # Date Validation
    if "last_updated" in entry and isinstance(entry["last_updated"], str):
        is_valid_date, date_err = is_valid_iso_date(entry["last_updated"])
        if not is_valid_date:
            result.add_error(
                company=company_name,
                field="last_updated",
                error_type="unsupported_format",
                message=f"Invalid date format in 'last_updated': {date_err}.",
                received_value=entry["last_updated"],
                remedy="Use ISO 8601 calendar date format 'YYYY-MM-DD' (e.g. '2026-11-15').",
            )

    # URL Validation (optional in prep guides)
    for url_field in ("source_url", "careers_url", "url"):
        if url_field in entry and isinstance(entry[url_field], str) and entry[url_field].strip():
            is_valid_url, url_err = is_valid_url_syntax(entry[url_field])
            if not is_valid_url:
                result.add_error(
                    company=company_name,
                    field=url_field,
                    error_type="invalid_url",
                    message=f"Invalid URL in '{url_field}': {url_err}.",
                    received_value=entry[url_field],
                    remedy="Provide a valid canonical URL starting with http:// or https://.",
                )
            elif check_live_links:
                is_live, live_err = check_live_url(entry[url_field])
                if not is_live:
                    if strict:
                        result.add_error(
                            company=company_name,
                            field=url_field,
                            error_type="broken_link",
                            message=f"Broken or unreachable link: {live_err}.",
                            received_value=entry[url_field],
                            remedy="Verify that the link is live and publicly accessible.",
                        )
                    else:
                        result.add_warning(
                            company=company_name,
                            field=url_field,
                            error_type="broken_link",
                            message=f"Unreachable link warning: {live_err}.",
                            received_value=entry[url_field],
                            remedy="Verify link reachability.",
                        )


# =====================================================================
# Main File Validator
# =====================================================================

def validate_company_file(
    file_path: Union[str, Path],
    check_live_links: bool = False,
    strict: bool = False,
) -> FileValidationResult:
    """
    Validates a single company JSON file against required schemas, duplicate names,
    date formats, and broken URLs.
    """
    path = Path(file_path)
    result = FileValidationResult(file_path=str(path), schema_type="unknown")

    if not path.exists():
        result.add_error(
            company="[File]",
            field="file_path",
            error_type="missing_file",
            message=f"File not found: '{path}'.",
            remedy="Ensure the file path is correct.",
        )
        return result

    if not path.is_file():
        result.add_error(
            company="[File]",
            field="file_path",
            error_type="invalid_format",
            message=f"Target is not a file: '{path}'.",
            remedy="Specify a path to a JSON file.",
        )
        return result

    # 1. Parse JSON & Check for Duplicate Keys
    try:
        data, raw_duplicate_keys = load_json_with_duplicate_key_check(path)
    except UnicodeDecodeError as exc:
        result.add_error(
            company="[File]",
            field="encoding",
            error_type="syntax_error",
            message=f"File is not valid UTF-8: {exc}",
            remedy="Save the file with UTF-8 encoding.",
        )
        return result
    except json.JSONDecodeError as exc:
        result.add_error(
            company="[File]",
            field=f"line_{exc.lineno}",
            error_type="syntax_error",
            message=f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            remedy="Fix the JSON syntax error (check for trailing commas, quotes, or missing brackets).",
        )
        return result
    except Exception as exc:
        result.add_error(
            company="[File]",
            field="parse",
            error_type="syntax_error",
            message=f"Unexpected error loading file: {exc}",
            remedy="Inspect file contents.",
        )
        return result

    # Report any duplicate keys found at the raw parser level
    for raw_key, raw_msg in raw_duplicate_keys:
        result.add_error(
            company=str(raw_key),
            field="[duplicate_key]",
            error_type="duplicate_company",
            message=f"Duplicate key '{raw_key}' found in JSON object: {raw_msg}",
            received_value=raw_key,
            remedy=f"Remove or rename the duplicate '{raw_key}' entry so all object keys are unique.",
        )

    # 2. Determine Schema Type
    schema_type = detect_schema_type(data)
    result.schema_type = schema_type

    if schema_type == "single_company":
        result.company_count = 1
        comp_name = data.get("company_name", "[Template]")
        if "typical_rounds" in data or "commonly_tested_topics" in data:
            _validate_interview_prep_entry(comp_name, data, result, check_live_links, strict)
        else:
            _validate_hiring_guide_entry(comp_name, data, result, check_live_links, strict)
        return result

    if schema_type == "list_of_companies":
        seen_names: Dict[str, str] = {}
        result.company_count = len(data)
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                result.add_error(
                    company=f"Item[{idx}]",
                    field="[item]",
                    error_type="unsupported_format",
                    message=f"Item at index {idx} must be a dictionary, got {type(item).__name__}.",
                    remedy="Ensure each item in the array is a company dictionary.",
                )
                continue

            comp_name = item.get("company_name") or item.get("name") or f"Item[{idx}]"
            comp_norm = str(comp_name).strip().lower()
            if comp_norm in seen_names:
                result.add_error(
                    company=str(comp_name),
                    field="company_name",
                    error_type="duplicate_company",
                    message=f"Duplicate company '{comp_name}' found at index {idx} (duplicate of '{seen_names[comp_norm]}').",
                    received_value=comp_name,
                    remedy=f"Remove or rename the duplicate '{comp_name}' entry.",
                )
            else:
                seen_names[comp_norm] = str(comp_name)

            if "typical_rounds" in item or "commonly_tested_topics" in item:
                _validate_interview_prep_entry(str(comp_name), item, result, check_live_links, strict)
            else:
                _validate_hiring_guide_entry(str(comp_name), item, result, check_live_links, strict)
        return result

    if schema_type in ("hiring_guide", "interview_prep"):
        if not isinstance(data, dict):
            result.add_error(
                company="[Root]",
                field="[root]",
                error_type="unsupported_format",
                message=f"Expected top-level dictionary mapping company names to profiles, got {type(data).__name__}.",
                remedy="Structure the root JSON as an object mapping company names to profiles.",
            )
            return result

        result.company_count = len(data)
        seen_names: Dict[str, str] = {}

        for company_name, profile in data.items():
            # Check for empty or whitespace company names
            if not str(company_name).strip():
                result.add_error(
                    company="[EmptyName]",
                    field="[company_key]",
                    error_type="unsupported_format",
                    message="Company name key cannot be empty or whitespace.",
                    remedy="Provide a valid, non-empty company name for every key.",
                )
                continue

            # Check case-insensitive duplicates
            norm_name = str(company_name).strip().lower()
            if norm_name in seen_names:
                existing = seen_names[norm_name]
                result.add_error(
                    company=company_name,
                    field="[company_key]",
                    error_type="duplicate_company",
                    message=f"Duplicate company '{company_name}' (case-insensitive duplicate of '{existing}').",
                    received_value=company_name,
                    remedy=f"Merge '{company_name}' into '{existing}' or rename one of the entries.",
                )
            else:
                seen_names[norm_name] = company_name

            # Validate entry schema
            if schema_type == "interview_prep":
                _validate_interview_prep_entry(company_name, profile, result, check_live_links, strict)
            else:
                _validate_hiring_guide_entry(company_name, profile, result, check_live_links, strict)

        return result

    # Unknown structure
    result.add_error(
        company="[File]",
        field="[structure]",
        error_type="unsupported_format",
        message=f"Unrecognized company JSON structure in '{path}'.",
        remedy="Use the format in 'data/company_contribution_template.json' or 'data/companies.json'.",
    )
    return result


def validate_paths(
    paths: Optional[List[Union[str, Path]]] = None,
    check_live_links: bool = False,
    strict: bool = False,
) -> List[FileValidationResult]:
    """
    Validates a list of file or directory paths.
    If no paths provided, validates standard company files in data/.
    """
    targets: List[Path] = []

    if not paths:
        for p_str in DEFAULT_COMPANY_DATA_FILES:
            p = Path(p_str)
            if p.exists():
                targets.append(p)
    else:
        for p_raw in paths:
            p = Path(p_raw)
            if p.is_dir():
                # Scan directory for all JSON files
                for item in sorted(p.glob("**/*.json")):
                    # Skip package.json and config files
                    if item.name not in ("package.json", "package-lock.json", "tsconfig.json", "vercel.json"):
                        targets.append(item)
            elif p.exists():
                targets.append(p)
            else:
                # Still record missing file so caller sees error
                targets.append(p)

    results: List[FileValidationResult] = []
    for t in targets:
        res = validate_company_file(t, check_live_links=check_live_links, strict=strict)
        results.append(res)

    return results


# =====================================================================
# Output Presentation & CLI Runner
# =====================================================================

def format_terminal_report(
    results: List[FileValidationResult],
    quiet: bool = False,
) -> str:
    """Formats validation results for terminal printing with clear file, company, and field names."""
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("  AI Campus Placement Agent - Contributor Company Data Validator")
    lines.append("=" * 72)

    total_files = len(results)
    total_companies = sum(r.company_count for r in results)
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)

    lines.append(f"Scanned {total_files} file(s) containing {total_companies} company definition(s).")
    lines.append("-" * 72)

    has_failures = False

    for r in results:
        if r.is_valid and len(r.warnings) == 0:
            if not quiet:
                lines.append(f"[PASS] {r.file_path} ({r.company_count} company/companies, 0 errors, 0 warnings)")
        else:
            status_tag = "[FAIL]" if not r.is_valid else "[WARN]"
            if not r.is_valid:
                has_failures = True

            lines.append(f"\n{status_tag} {r.file_path} (Errors: {len(r.errors)}, Warnings: {len(r.warnings)}):")

            # Print errors with clear file, company, and field identifiers
            for idx, err in enumerate(r.errors, 1):
                lines.append(f"  {idx}. File   : {err.file}")
                lines.append(f"     Company: [{err.company}]")
                lines.append(f"     Field  : '{err.field}'")
                lines.append(f"     Type   : {err.error_type}")
                lines.append(f"     Issue  : {err.message}")
                if err.received_value is not None:
                    lines.append(f"     Value  : {repr(err.received_value)}")
                if err.remedy:
                    lines.append(f"     Remedy : {err.remedy}")
                lines.append("")

            # Print warnings
            for idx, warn in enumerate(r.warnings, 1):
                lines.append(f"  (Warning {idx}) File   : {warn.file}")
                lines.append(f"                 Company: [{warn.company}]")
                lines.append(f"                 Field  : '{warn.field}'")
                lines.append(f"                 Issue  : {warn.message}")
                if warn.remedy:
                    lines.append(f"                 Remedy : {warn.remedy}")
                lines.append("")

    lines.append("-" * 72)
    if has_failures:
        lines.append(f"[FAILED] Found {total_errors} validation error(s) across {total_files} file(s).")
        lines.append("Please correct the field-specific issues listed above before opening a Pull Request.")
    else:
        lines.append(f"[SUCCESS] All company data files are valid! ({total_companies} companies verified, 0 errors).")
    lines.append("=" * 72)

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI runner for company JSON validation."""
    parser = argparse.ArgumentParser(
        description="Validate contributor company JSON files for required fields, duplicate names, and link validity."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="One or more company JSON files or directories to validate (defaults to standard files in data/).",
    )
    parser.add_argument(
        "--live",
        "--check-live-links",
        dest="check_live_links",
        action="store_true",
        help="Perform optional live HTTP requests to verify external URLs are reachable.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (useful for strict CI checks).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output validation results in structured JSON format.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output error details when failures occur.",
    )

    args = parser.parse_args(argv)

    results = validate_paths(
        paths=args.paths if args.paths else None,
        check_live_links=args.check_live_links,
        strict=args.strict,
    )

    if args.json:
        payload = {
            "all_valid": all(r.is_valid for r in results),
            "total_files": len(results),
            "total_companies": sum(r.company_count for r in results),
            "total_errors": sum(len(r.errors) for r in results),
            "total_warnings": sum(len(r.warnings) for r in results),
            "files": [r.to_dict() for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        report_text = format_terminal_report(results, quiet=args.quiet)
        print(report_text)

    is_success = all(r.is_valid for r in results)
    if args.strict and any(len(r.warnings) > 0 for r in results):
        is_success = False

    return 0 if is_success else 1


if __name__ == "__main__":
    sys.exit(main())
