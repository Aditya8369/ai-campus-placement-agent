"""
Company JSON Schema and Data Integrity Validator (#855).
========================================================
Validates company profile data structures against formal JSON schema rules,
detects duplicate keys or case-insensitive company names, verifies data types,
ensures non-empty arrays, and checks URL and ISO date formats.

Provides readable, actionable error messages pinpointing:
- Company name
- Field name
- Error description
- Actionable remedy
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Schema definition path
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "schemas" / "company.schema.json"

# Strict ISO 8601 YYYY-MM-DD
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_FIELDS: Dict[str, type] = {
    "overview": str,
    "hiring_process": str,
    "technical_rounds": str,
    "hr_rounds": str,
    "frequent_topics": list,
    "required_skills": list,
    "prep_tips": str,
    "eligibility": str,
    "last_updated": str,
    "source_name": str,
    "source_url": str,
}

OPTIONAL_FIELDS: Dict[str, Any] = {
    "min_cgpa": (int, float),
    "max_backlogs": int,
    "branches": list,
    "eligibility_source": str,
    "is_verified": bool,
    "verification_status": str,
    "verified_by": str,
}


class CompanyValidationError:
    """Represents a human-readable validation error for a company profile."""

    def __init__(
        self,
        company: str,
        field: str,
        error_type: str,
        message: str,
        received_value: Any = None,
        remedy: str = "",
    ):
        self.company = company
        self.field = field
        self.error_type = error_type
        self.message = message
        self.received_value = received_value
        self.remedy = remedy

    def __str__(self) -> str:
        parts = [f"[{self.company}] Field '{self.field}': {self.message}"]
        if self.remedy:
            parts.append(f"  -> Remedy: {self.remedy}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "field": self.field,
            "error_type": self.error_type,
            "message": self.message,
            "received_value": str(self.received_value) if self.received_value is not None else None,
            "remedy": self.remedy,
        }


def check_duplicate_json_keys(json_str: str) -> List[str]:
    """
    Parses JSON text and checks for duplicate keys at any dictionary level.
    Returns a list of duplicate key names found.
    """
    duplicates = []

    def dict_parser(pairs):
        seen = set()
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    json.loads(json_str, object_pairs_hook=dict_parser)
    return duplicates


def is_valid_url(url: Any) -> Tuple[bool, str]:
    """Validates that a URL has a valid http/https scheme and a hostname with domain."""
    if not isinstance(url, str):
        return False, f"Expected string for URL, got {type(url).__name__}"
    clean = url.strip()
    if not clean:
        return False, "URL cannot be empty"
    if any(c in clean for c in (" ", "\t", "\n", "\r")):
        return False, "URL contains illegal whitespace characters"

    try:
        parsed = urllib.parse.urlparse(clean)
    except Exception as exc:
        return False, f"Malformed URL syntax: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Invalid scheme '{parsed.scheme}'. URL must start with http:// or https://"

    host = parsed.netloc or parsed.hostname
    if not host:
        return False, "URL is missing a valid domain/host"

    # Host should contain a dot or be localhost
    if "." not in host and host.lower() not in ("localhost", "127.0.0.1"):
        return False, f"Domain '{host}' is missing a top-level domain"

    return True, ""


def validate_companies_data(data: Any, raw_json: Optional[str] = None) -> List[CompanyValidationError]:
    """
    Validates a loaded companies dictionary against all schema requirements.
    Detects:
    - Missing required fields
    - Invalid data types
    - Empty strings or empty lists
    - Duplicate company names (case-insensitive)
    - Duplicate JSON object keys (if raw_json is provided)
    - Invalid date formats (must be YYYY-MM-DD)
    - Invalid URLs (must be http/https with valid domain)
    - Out of range numeric fields (e.g. min_cgpa, max_backlogs)
    """
    errors: List[CompanyValidationError] = []

    # 1. Check duplicate JSON keys if raw string is provided
    if raw_json:
        try:
            dup_keys = check_duplicate_json_keys(raw_json)
            for dk in dup_keys:
                errors.append(
                    CompanyValidationError(
                        company=dk,
                        field="[key]",
                        error_type="duplicate_key",
                        message=f"Duplicate key '{dk}' found in JSON object.",
                        remedy=f"Remove or rename the duplicate '{dk}' entry.",
                    )
                )
        except Exception:
            pass

    if not isinstance(data, dict):
        errors.append(
            CompanyValidationError(
                company="[root]",
                field="[root]",
                error_type="invalid_type",
                message=f"Root of companies.json must be an object/dict, got {type(data).__name__}.",
            )
        )
        return errors

    if len(data) == 0:
        errors.append(
            CompanyValidationError(
                company="[root]",
                field="[root]",
                error_type="empty_database",
                message="companies.json contains no company entries.",
            )
        )
        return errors

    # 2. Case-insensitive duplicate company detection
    seen_names: Dict[str, str] = {}
    for company_name in data.keys():
        norm = company_name.strip().lower()
        if norm in seen_names:
            first_name = seen_names[norm]
            errors.append(
                CompanyValidationError(
                    company=company_name,
                    field="[company_name]",
                    error_type="duplicate_company",
                    message=f"Duplicate company name '{company_name}' matches existing entry '{first_name}' (case-insensitive).",
                    remedy=f"Merge '{company_name}' into '{first_name}' or rename one of them.",
                )
            )
        else:
            seen_names[norm] = company_name

    # 3. Validate each company profile
    for company_name, profile in data.items():
        if not isinstance(profile, dict):
            errors.append(
                CompanyValidationError(
                    company=company_name,
                    field="[entry]",
                    error_type="invalid_type",
                    message=f"Company profile must be a JSON object, got {type(profile).__name__}.",
                    remedy="Structure the company profile as a JSON key-value dictionary.",
                )
            )
            continue

        # Check required fields
        for field_name, expected_type in REQUIRED_FIELDS.items():
            if field_name not in profile:
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field=field_name,
                        error_type="missing_required_field",
                        message=f"Missing required field '{field_name}'.",
                        remedy=f"Add field '{field_name}' with a valid {expected_type.__name__} value.",
                    )
                )
                continue

            val = profile[field_name]

            # Check type
            if not isinstance(val, expected_type):
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field=field_name,
                        error_type="invalid_type",
                        message=f"Field '{field_name}' must be of type {expected_type.__name__}, got {type(val).__name__}.",
                        received_value=val,
                        remedy=f"Change '{field_name}' to a valid {expected_type.__name__}.",
                    )
                )
                continue

            # Check non-empty for strings
            if isinstance(val, str):
                if not val.strip():
                    errors.append(
                        CompanyValidationError(
                            company=company_name,
                            field=field_name,
                            error_type="empty_value",
                            message=f"Field '{field_name}' cannot be an empty or whitespace string.",
                            remedy=f"Provide a descriptive value for '{field_name}'.",
                        )
                    )

            # Check non-empty for lists
            if isinstance(val, list):
                if len(val) == 0:
                    errors.append(
                        CompanyValidationError(
                            company=company_name,
                            field=field_name,
                            error_type="empty_list",
                            message=f"Field '{field_name}' cannot be an empty list.",
                            remedy=f"Add at least one item to '{field_name}'.",
                        )
                    )
                else:
                    for idx, item in enumerate(val):
                        if not isinstance(item, str) or not item.strip():
                            errors.append(
                                CompanyValidationError(
                                    company=company_name,
                                    field=f"{field_name}[{idx}]",
                                    error_type="invalid_list_item",
                                    message=f"Item at index {idx} in '{field_name}' must be a non-empty string.",
                                    received_value=item,
                                    remedy="Ensure all list elements are non-empty strings.",
                                )
                            )

            # Date format validation
            if field_name == "last_updated":
                if not ISO_DATE_REGEX.match(val):
                    errors.append(
                        CompanyValidationError(
                            company=company_name,
                            field="last_updated",
                            error_type="invalid_date_format",
                            message=f"Field 'last_updated' value '{val}' is not a valid ISO 8601 date (YYYY-MM-DD).",
                            received_value=val,
                            remedy="Format the date as YYYY-MM-DD (e.g. '2026-11-20').",
                        )
                    )

            # URL validation
            if field_name == "source_url":
                is_valid, reason = is_valid_url(val)
                if not is_valid:
                    errors.append(
                        CompanyValidationError(
                            company=company_name,
                            field="source_url",
                            error_type="invalid_url",
                            message=f"Invalid URL in 'source_url': {reason}",
                            received_value=val,
                            remedy="Provide a valid HTTP or HTTPS URL (e.g. 'https://careers.company.com').",
                        )
                    )

        # Optional fields validation
        for field_name, expected_type in OPTIONAL_FIELDS.items():
            if field_name not in profile or profile[field_name] is None:
                continue

            val = profile[field_name]
            if not isinstance(val, expected_type):
                expected_name = (
                    "number" if expected_type == (int, float) else expected_type.__name__
                )
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field=field_name,
                        error_type="invalid_type",
                        message=f"Optional field '{field_name}' must be {expected_name}, got {type(val).__name__}.",
                        received_value=val,
                    )
                )
                continue

            if field_name == "min_cgpa" and not (0 <= val <= 10):
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field="min_cgpa",
                        error_type="out_of_range",
                        message=f"min_cgpa must be between 0.0 and 10.0, got {val}.",
                        received_value=val,
                    )
                )

            if field_name == "max_backlogs" and val < 0:
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field="max_backlogs",
                        error_type="out_of_range",
                        message=f"max_backlogs cannot be negative, got {val}.",
                        received_value=val,
                    )
                )

            if field_name == "branches" and isinstance(val, list):
                if len(val) == 0:
                    errors.append(
                        CompanyValidationError(
                            company=company_name,
                            field="branches",
                            error_type="empty_list",
                            message="branches cannot be an empty list when specified.",
                        )
                    )

            if field_name == "verification_status" and val not in ("verified", "pending", "unverified"):
                errors.append(
                    CompanyValidationError(
                        company=company_name,
                        field="verification_status",
                        error_type="invalid_enum",
                        message=f"verification_status must be one of ['verified', 'pending', 'unverified'], got '{val}'.",
                        received_value=val,
                    )
                )

    return errors
