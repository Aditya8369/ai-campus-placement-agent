"""
Email domain validation and college suggestion utilities (#654).

Provides case-insensitive, explicit subdomain-aware validation for campus email restrictions.
When ALLOWED_EMAIL_DOMAINS is configured, only emails with matching domains or subdomains
(e.g., user@dept.college.edu when college.edu is configured) are permitted.
When ALLOWED_EMAIL_DOMAINS is empty or unset, registration is open to any domain.
"""

import os
import re
from typing import List, Optional, Union
from flask import current_app
import config


def parse_allowed_email_domains(raw: Optional[str] = None) -> List[str]:
    """
    Parses a comma-separated string of domain names into a normalized list of lowercase domains.
    Handles leading '@', leading '*.' or '.', and surrounding whitespace.
    """
    if raw is None:
        try:
            raw = current_app.config.get("ALLOWED_EMAIL_DOMAINS", "")
        except (RuntimeError, AttributeError):
            raw = getattr(config, "ALLOWED_EMAIL_DOMAINS", "") or os.getenv("ALLOWED_EMAIL_DOMAINS", "")

    if not raw or not isinstance(raw, str):
        return []

    domains: List[str] = []
    for part in raw.split(","):
        cleaned = part.strip().lower()
        cleaned = re.sub(r"^[*@.]+", "", cleaned).strip()
        if cleaned and cleaned not in domains:
            domains.append(cleaned)
    return domains


def get_allowed_email_domains() -> List[str]:
    """Retrieves the list of currently configured allowed email domains."""
    return parse_allowed_email_domains()


def extract_email_domain(email: str) -> Optional[str]:
    """
    Extracts the lowercase domain part of an email address.
    Returns None if the email format is invalid.
    """
    if not email or not isinstance(email, str):
        return None
    cleaned = email.strip().lower()
    if "@" not in cleaned:
        return None
    parts = cleaned.rsplit("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    domain = parts[1].strip().rstrip(".")
    return domain if domain else None


def is_email_domain_allowed(
    email: str,
    allowed_domains: Optional[Union[List[str], str]] = None
) -> bool:
    """
    Checks if an email's domain is allowed.

    Rules:
    1. If allowed_domains is empty/unset, any syntactically valid email domain is allowed.
    2. Comparison is case-insensitive.
    3. Explicit subdomain matching: if 'college.edu' is allowed, then:
       - 'user@college.edu' is allowed (exact match)
       - 'user@dept.college.edu' is allowed (subdomain)
       - 'user@eng.dept.college.edu' is allowed (multi-level subdomain)
       - 'user@fake-college.edu' is REJECTED (partial match not a subdomain)
       - 'user@college.edu.attacker.com' is REJECTED
    """
    if allowed_domains is None:
        domain_list = get_allowed_email_domains()
    elif isinstance(allowed_domains, str):
        domain_list = parse_allowed_email_domains(allowed_domains)
    else:
        domain_list = [d.strip().lower().lstrip("@*.") for d in allowed_domains if d and d.strip()]

    domain = extract_email_domain(email)
    if not domain:
        return False

    # If allowed_domains is not configured, registration is open to any domain
    if not domain_list:
        return True

    for allowed in domain_list:
        if domain == allowed:
            return True
        if domain.endswith("." + allowed):
            return True

    return False


def get_email_domain_error_message(
    allowed_domains: Optional[Union[List[str], str]] = None
) -> str:
    """
    Returns a user-friendly error message indicating which domains are permitted.
    """
    if allowed_domains is None:
        domain_list = get_allowed_email_domains()
    elif isinstance(allowed_domains, str):
        domain_list = parse_allowed_email_domains(allowed_domains)
    else:
        domain_list = [d.strip().lower().lstrip("@*.") for d in allowed_domains if d and d.strip()]

    if domain_list:
        formatted = ", ".join(f"@{d}" for d in domain_list)
        return (
            f"Registration is restricted to approved college email domains: {formatted}. "
            f"Please use your official college-issued email address."
        )
    return "Invalid email domain. Please enter a valid email address."


def get_suggested_colleges(
    allowed_domains: Optional[Union[List[str], str]] = None
) -> List[str]:
    """
    Returns a suggested list of college names derived from the allowed email domains.
    Used to populate HTML datalist suggestions for the profile college field.
    """
    if allowed_domains is None:
        domain_list = get_allowed_email_domains()
    elif isinstance(allowed_domains, str):
        domain_list = parse_allowed_email_domains(allowed_domains)
    else:
        domain_list = [d.strip().lower().lstrip("@*.") for d in allowed_domains if d and d.strip()]

    suggestions: List[str] = []
    known_colleges = {
        "stanford.edu": "Stanford University",
        "harvard.edu": "Harvard University",
        "mit.edu": "Massachusetts Institute of Technology (MIT)",
        "berkeley.edu": "UC Berkeley",
        "ox.ac.uk": "University of Oxford",
        "cam.ac.uk": "University of Cambridge",
        "iitb.ac.in": "IIT Bombay",
        "iitd.ac.in": "IIT Delhi",
        "iitm.ac.in": "IIT Madras",
        "cmu.edu": "Carnegie Mellon University",
        "gatech.edu": "Georgia Institute of Technology",
    }

    for d in domain_list:
        d_lower = d.lower()
        if d_lower in known_colleges:
            suggestions.append(known_colleges[d_lower])
        else:
            parts = d_lower.split(".")
            label = parts[0] if parts else d_lower
            if len(label) <= 5:
                derived = label.upper()
            else:
                derived = label.replace("-", " ").title()
            suggestions.append(f"{derived} ({d_lower})")

    seen = set()
    result = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
