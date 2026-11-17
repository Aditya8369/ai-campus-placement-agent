"""
Resume PII Detection & Redaction Utility (#295)
==============================================
Detects and redacts personal contact details and Personally Identifiable
Information (PII) from candidate resumes before the prompt is constructed
and sent to external AI model endpoints (Gemini API).

Guarantees candidate privacy by replacing:
- Email addresses -> [EMAIL]
- Domestic & International phone numbers (including Indian formats) -> [PHONE]
- Physical / Street address lines and Postal / PIN codes -> [ADDRESS]
- Personal web links / social profiles -> [LINK]

Maintains document structure, ATS scoring integrity, and section classification.
Original resume text is preserved in the user's local stored records.
Redaction is enabled by default and can be toggled via `config.ENABLE_PII_REDACTION`.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard redaction placeholder tokens (#295)
PLACEHOLDER_EMAIL = "[EMAIL]"
PLACEHOLDER_PHONE = "[PHONE]"
PLACEHOLDER_ADDRESS = "[ADDRESS]"
PLACEHOLDER_LINK = "[LINK]"

REDACTION_PLACEHOLDERS = {
    "email": PLACEHOLDER_EMAIL,
    "phone": PLACEHOLDER_PHONE,
    "address": PLACEHOLDER_ADDRESS,
    "link": PLACEHOLDER_LINK,
}

# Regex pattern for email detection (RFC-compliant)
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# International phone numbers with leading + and country code
INTL_PHONE_PATTERN = re.compile(
    r"\+\d{1,3}(?:[ \t.-]?\(?\d{1,4}\)?){2,5}\b"
)

# Indian mobile phone formats:
# 10 digits starting with [6-9], with optional +91, 91, or 0 prefix and optional delimiters
INDIAN_PHONE_PATTERN = re.compile(
    r"(?:(?:\+91|91|0)[ \t.-]?)?(?:\([6-9]\d{2}\)|[6-9]\d{2})[ \t.-]?\d{3}[ \t.-]?\d{4}\b"
    r"|(?:(?:\+91|91|0)[ \t.-]?)?[6-9]\d{4}[ \t.-]?\d{5}\b"
    r"|(?:(?:\+91|91|0)[ \t.-]?)?[6-9]\d{9}\b"
)

# Indian landline with STD code (e.g., 011-23456789, +91 11 2345 6789)
INDIAN_LANDLINE_PATTERN = re.compile(
    r"(?:(?:\+91|91|0)[ \t.-]?)?\d{2,4}[ \t.-]?\d{6,8}\b"
)

# US / North American domestic phone format
US_PHONE_PATTERN = re.compile(
    r"(?:\(\d{3}\)|\b\d{3}\b)[ \t.-]\d{3}[ \t.-]\d{4}\b"
)

# Explicitly labeled phone numbers (e.g., "Phone: ...", "Mobile: ...")
LABELED_PHONE_PATTERN = re.compile(
    r"(?i)\b(?:phone|tel|telephone|mobile|cell|call|contact|whatsapp)[ \t]*:[ \t]*([+\d \t().-]{7,25})\b"
)

# Address labels (e.g., "Address: ...", "Permanent Address: ...")
ADDRESS_LABEL_PATTERN = re.compile(
    r"(?i)^([ \t]*(?:permanent\s+address|current\s+address|residential\s+address|postal\s+address|mailing\s+address|home\s+address|address)[ \t]*:[ \t]*)(.+)$"
)

# Address keyword indicators
ADDRESS_KEYWORD_PATTERN = re.compile(
    r"(?i)\b(?:street|st\b|road|rd\b|avenue|ave\b|boulevard|blvd\b|lane|ln\b|drive|dr\b|nagar|colony|layout|sector|block|tower|phase|cross|main|society|apartment|apartments|apt\b|flat|plot)\b"
)

# Postal / PIN codes (5-6 digits, optional US ZIP+4)
POSTAL_CODE_PATTERN = re.compile(
    r"\b\d{5,6}(?:-\d{4})?\b"
)

# Pincode / Postal code labeled lines
PINCODE_LINE_PATTERN = re.compile(
    r"(?i)\b(?:pin\s*code|postal\s*code|pincode|zip\s*code|zip)[ \t]*:[ \t]*\d{5,6}(?:-\d{4})?\b"
)

# URLs, websites, and professional profile links
LINK_PATTERN = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"]+"
    r"|\b(?:github\.com|linkedin\.com)/[^\s<>\"]+"
)


def _is_valid_phone(candidate: str) -> bool:
    """
    Validates whether a matched candidate string constitutes a genuine phone number.
    Filters out year ranges (e.g., 2019 - 2023), repeated digits, and short numerical strings.
    """
    if not candidate:
        return False
    digits = re.sub(r"\D", "", candidate)
    if not (8 <= len(digits) <= 15):
        return False
    # Exclude 8-digit graduation or employment year ranges like 2019-2023
    if len(digits) == 8 and re.match(r"^(19|20)\d{2}(19|20)\d{2}$", digits):
        return False
    # Exclude repeated single digit e.g. 0000000000 or 1111111111
    if len(set(digits)) <= 1:
        return False
    return True


def find_phone_spans(text: str) -> List[Tuple[int, int, str]]:
    """
    Finds non-overlapping character spans of phone numbers in the text.
    Returns list of (start_idx, end_idx, matched_string) sorted by start position.
    """
    if not text:
        return []

    candidates: List[Tuple[int, int, str]] = []

    # 1. Check labeled phones
    for m in LABELED_PHONE_PATTERN.finditer(text):
        val = m.group(1).strip()
        if _is_valid_phone(val):
            candidates.append((m.start(1), m.end(1), val))

    # 2. Check pattern phones
    for pat in [INTL_PHONE_PATTERN, INDIAN_PHONE_PATTERN, US_PHONE_PATTERN, INDIAN_LANDLINE_PATTERN]:
        for m in pat.finditer(text):
            val = m.group().strip()
            if _is_valid_phone(val):
                candidates.append((m.start(), m.end(), val))

    # Sort candidates by start ascending and length descending
    candidates.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    filtered: List[Tuple[int, int, str]] = []
    last_end = 0
    for s, e, val in candidates:
        if s >= last_end:
            filtered.append((s, e, val))
            last_end = e

    return filtered


def detect_pii(text: str) -> Dict[str, Any]:
    """
    Audits resume text and returns detected PII entities and categories without modifying the text.
    """
    if not text or not text.strip():
        return {
            "has_pii": False,
            "emails": [],
            "phones": [],
            "addresses": [],
            "links": [],
            "counts": {"emails": 0, "phones": 0, "addresses": 0, "links": 0},
            "total_count": 0,
        }

    emails = sorted(list(set(EMAIL_PATTERN.findall(text))))

    phone_spans = find_phone_spans(text)
    phones = sorted(list(set(p[2] for p in phone_spans)))

    links = sorted(list(set(m.group() for m in LINK_PATTERN.finditer(text))))

    addresses = []
    for line in text.split("\n"):
        label_match = ADDRESS_LABEL_PATTERN.match(line)
        if label_match:
            addresses.append(label_match.group(2).strip())
            continue
        if PINCODE_LINE_PATTERN.search(line):
            addresses.append(line.strip())
            continue
        if ADDRESS_KEYWORD_PATTERN.search(line) and POSTAL_CODE_PATTERN.search(line):
            addresses.append(line.strip())

    addresses = sorted(list(set(addresses)))

    counts = {
        "emails": len(emails),
        "phones": len(phones),
        "addresses": len(addresses),
        "links": len(links),
    }
    total_count = sum(counts.values())

    return {
        "has_pii": total_count > 0,
        "emails": emails,
        "phones": phones,
        "addresses": addresses,
        "links": links,
        "counts": counts,
        "total_count": total_count,
    }


def has_pii(text: str) -> bool:
    """Returns True if any PII entity is detected in the text."""
    return detect_pii(text)["has_pii"]


def get_pii_counts(text: str) -> Dict[str, int]:
    """Returns count of detected PII entities grouped by category."""
    return detect_pii(text)["counts"]


def redact_pii(
    text: str,
    enabled: Optional[bool] = None,
    redact_emails: bool = True,
    redact_phones: bool = True,
    redact_addresses: bool = True,
    redact_links: bool = True,
) -> str:
    """
    Sanitizes personal identifiable details from resume text before dispatching to AI.

    Args:
        text: Raw resume text extracted from upload.
        enabled: Optional boolean flag. If None, resolves to config.ENABLE_PII_REDACTION (default: True).
        redact_emails: Whether to replace email addresses with [EMAIL].
        redact_phones: Whether to replace phone numbers with [PHONE].
        redact_addresses: Whether to replace physical address lines with [ADDRESS].
        redact_links: Whether to replace profile / web URLs with [LINK].

    Returns:
        Redacted text safe for model ingestion, or original text if disabled or empty.
    """
    if not text:
        return text

    if enabled is None:
        try:
            import config
            enabled = getattr(config, "ENABLE_PII_REDACTION", True)
        except Exception:
            enabled = True

    if not enabled:
        return text

    result = text

    # 1. Redact Emails
    if redact_emails:
        emails = sorted(set(EMAIL_PATTERN.findall(result)), key=len, reverse=True)
        for email in emails:
            result = result.replace(email, PLACEHOLDER_EMAIL)

    # 2. Redact Links & URLs
    if redact_links:
        link_matches = sorted(set(m.group() for m in LINK_PATTERN.finditer(result)), key=len, reverse=True)
        for link in link_matches:
            result = result.replace(link, PLACEHOLDER_LINK)

    # 3. Redact Phone Numbers (using reverse index replacement)
    if redact_phones:
        phone_spans = find_phone_spans(result)
        for s, e, _ in reversed(phone_spans):
            result = result[:s] + PLACEHOLDER_PHONE + result[e:]

    # 4. Redact Street Addresses & PIN codes
    if redact_addresses:
        lines = result.split("\n")
        redacted_lines = []
        for line in lines:
            # Case A: Explicit address label (e.g. "Address: 123 Main St, Springfield")
            label_match = ADDRESS_LABEL_PATTERN.match(line)
            if label_match:
                prefix = label_match.group(1)
                redacted_lines.append(f"{prefix}{PLACEHOLDER_ADDRESS}")
                continue

            # Case B: Labeled pincode / postal line (e.g. "Pin Code: 560001")
            if PINCODE_LINE_PATTERN.search(line):
                line = PINCODE_LINE_PATTERN.sub(PLACEHOLDER_ADDRESS, line)
                redacted_lines.append(line)
                continue

            # Case C: Standalone line with address indicator and postal code
            if ADDRESS_KEYWORD_PATTERN.search(line) and POSTAL_CODE_PATTERN.search(line):
                leading_ws = line[:len(line) - len(line.lstrip())]
                redacted_lines.append(f"{leading_ws}{PLACEHOLDER_ADDRESS}")
                continue

            # Case D: Line with street number and street indicator
            if re.search(r"(?i)\b\d+[\w\s,.-]+(?:Street|St\b|Road|Rd\b|Avenue|Ave\b|Boulevard|Blvd\b|Lane|Ln\b|Drive|Dr\b|Nagar|Colony|Apartment|Apartments|Apt\b|Flat)\b", line):
                leading_ws = line[:len(line) - len(line.lstrip())]
                redacted_lines.append(f"{leading_ws}{PLACEHOLDER_ADDRESS}")
                continue

            redacted_lines.append(line)
        result = "\n".join(redacted_lines)

    return result
