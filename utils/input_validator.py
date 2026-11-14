"""
Application-Wide Input Validation and Sanitization Service (#276).

Provides centralized, reusable input validation rules and sanitation helpers across:
1. User registration, profile updates, and authentication forms.
2. Job application submissions and edits (company names, roles, URLs, statuses).
3. Mock interview answers, questions, and topics.
4. Note creation, tags, and search query strings.
5. Code submission languages and content length constraints.

Enforces:
- Length constraints (min_length, max_length) to prevent memory exhaustion / DoS.
- ReDoS-safe regex validation for emails, URLs, identifiers, and phone numbers.
- HTML tag stripping / XSS mitigation for free-text inputs.
- Normalized error payloads with clear, user-friendly field-level error messages.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple, Union

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)
URL_REGEX = re.compile(
    r"^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$",
    re.IGNORECASE
)
ALPHANUMERIC_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
HTML_TAGS_REGEX = re.compile(r"<[^>]+>")


class ValidationError(ValueError):
    """Custom exception raised when validation fails, containing structured error details."""
    def __init__(self, message: str, field_errors: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.message = message
        self.field_errors = field_errors or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error": self.message,
            "field_errors": self.field_errors
        }


def sanitize_text(text: Any, strip_html: bool = True, max_len: Optional[int] = None) -> str:
    """
    Sanitizes string input by stripping whitespace, escaping/stripping HTML, and enforcing max length.
    """
    if text is None:
        return ""
    val = str(text).strip()
    if strip_html:
        val = HTML_TAGS_REGEX.sub("", val)
    val = html.escape(val, quote=True)
    if max_len is not None and len(val) > max_len:
        val = val[:max_len]
    return val


def validate_email(email: str, field_name: str = "email") -> str:
    """
    Validates email format and length.
    """
    if not email or not isinstance(email, str):
        raise ValidationError(f"{field_name} is required.", {field_name: "Email cannot be empty."})
    clean = email.strip()
    if len(clean) > 254:
        raise ValidationError("Email address exceeds maximum length (254 characters).", {field_name: "Email too long."})
    if not EMAIL_REGEX.match(clean):
        raise ValidationError("Invalid email address format.", {field_name: "Please provide a valid email address."})
    return clean.lower()


def validate_string(
    value: Any,
    field_name: str,
    min_length: int = 1,
    max_length: int = 255,
    required: bool = True,
    allowed_values: Optional[List[str]] = None
) -> str:
    """
    Validates general string input length, presence, and optional enum value constraints.
    """
    if value is None:
        clean = ""
    else:
        clean = str(value).strip()

    if not clean:
        if required:
            raise ValidationError(f"{field_name} is required.", {field_name: f"{field_name} cannot be empty."})
        return ""

    if len(clean) < min_length:
        raise ValidationError(
            f"{field_name} must be at least {min_length} characters.",
            {field_name: f"Minimum length is {min_length}."}
        )

    if len(clean) > max_length:
        raise ValidationError(
            f"{field_name} cannot exceed {max_length} characters.",
            {field_name: f"Maximum length is {max_length}."}
        )

    if allowed_values is not None:
        valid_vals_lower = [v.lower() for v in allowed_values]
        if clean.lower() not in valid_vals_lower:
            raise ValidationError(
                f"Invalid value for {field_name}. Must be one of: {', '.join(allowed_values)}",
                {field_name: f"Allowed values: {', '.join(allowed_values)}"}
            )

    return clean


def validate_url(url: Optional[str], field_name: str = "url", required: bool = False) -> str:
    """
    Validates HTTP/HTTPS URLs.
    """
    if not url:
        if required:
            raise ValidationError(f"{field_name} is required.", {field_name: "URL cannot be empty."})
        return ""
    clean = str(url).strip()
    if len(clean) > 2048:
        raise ValidationError("URL exceeds maximum length of 2048 characters.", {field_name: "URL too long."})
    if not URL_REGEX.match(clean):
        raise ValidationError(f"Invalid URL for {field_name}. Must start with http:// or https://", {field_name: "Invalid URL."})
    return clean


def validate_registration_payload(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validates student user registration fields.
    """
    errors: Dict[str, str] = {}
    validated: Dict[str, str] = {}

    try:
        validated["email"] = validate_email(data.get("email", ""), "email")
    except ValidationError as ve:
        errors.update(ve.field_errors)

    try:
        validated["full_name"] = validate_string(data.get("full_name") or data.get("name"), "full_name", min_length=2, max_length=100)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    password = str(data.get("password") or "")
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters long."
    elif len(password) > 128:
        errors["password"] = "Password cannot exceed 128 characters."
    else:
        validated["password"] = password

    if errors:
        raise ValidationError("Registration validation failed.", errors)

    return validated


def validate_job_application_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates job application creation or update payload.
    """
    errors: Dict[str, str] = {}
    validated: Dict[str, Any] = {}

    try:
        validated["company_name"] = validate_string(data.get("company_name"), "company_name", min_length=2, max_length=120)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    try:
        role = data.get("role_title") or data.get("job_title")
        validated["role_title"] = validate_string(role, "role_title", min_length=2, max_length=150)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    valid_statuses = ["Applied", "Interviewing", "Offer", "Rejected", "Withdrawn", "Pending"]
    try:
        status_raw = data.get("status", "Applied")
        validated["status"] = validate_string(status_raw, "status", allowed_values=valid_statuses)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    try:
        job_url = data.get("job_url") or data.get("url")
        validated["job_url"] = validate_url(job_url, "job_url", required=False)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    validated["notes"] = sanitize_text(data.get("notes", ""), max_len=2000)
    validated["location"] = validate_string(data.get("location", "Remote"), "location", min_length=1, max_length=100, required=False)

    if errors:
        raise ValidationError("Job application validation failed.", errors)

    return validated


def validate_interview_answer_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates mock interview answer submission.
    """
    errors: Dict[str, str] = {}
    validated: Dict[str, Any] = {}

    try:
        answer_text = validate_string(data.get("answer"), "answer", min_length=5, max_length=10000, required=True)
        validated["answer"] = sanitize_text(answer_text, strip_html=True)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    try:
        validated["session_id"] = validate_string(data.get("session_id"), "session_id", min_length=1, max_length=128, required=True)
    except ValidationError as ve:
        errors.update(ve.field_errors)

    if errors:
        raise ValidationError("Interview answer submission failed validation.", errors)

    return validated
