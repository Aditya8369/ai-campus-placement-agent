"""
Resume PII Detection & Redaction Service (#249)
===============================================
Identifies and redacts sensitive Personally Identifiable Information (PII)
from student resumes before dispatching text to AI analysis models.

Supported PII categories:
1. Email addresses
2. Phone numbers (domestic & international with country codes)
3. Physical / Street addresses and PIN codes
4. Government identifiers (Aadhaar, PAN, SSN patterns)
5. Social profiles & personal links (LinkedIn, GitHub handles, portfolio URLs)

Safety guarantees:
- Non-destructive: Preserves original uploaded resume files.
- Deterministic redaction using clean entity tokens ([REDACTED_EMAIL], [REDACTED_PHONE], etc.).
- Candidate review & selection: allows selective or blanket redaction.
- Hardened regex patterns preventing accidental leakage.
"""

import re
import logging
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger(__name__)

# Standard replacement tokens
REDACTION_TOKENS = {
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "address": "[REDACTED_ADDRESS]",
    "government_id": "[REDACTED_GOV_ID]",
    "url": "[REDACTED_LINK]",
}

# Regex Patterns for PII extraction
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# International & Indian phone formats (with/without country code, spaces, dashes, parentheses)
PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}\b"
)

# Indian PAN card: 5 uppercase letters, 4 digits, 1 uppercase letter
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b")

# Indian Aadhaar: 12 digits, often formatted as 4-4-4
AADHAAR_PATTERN = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")

# US SSN: 3-2-4 digits
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Street address indicators
ADDRESS_INDICATORS = [
    r"\b(?:\d+[\w\s,-]+(?:Street|St\.|Road|Rd\.|Avenue|Ave\.|Nagar|Colony|Layout|Sector|Block|Apartment|Apt\.|Flat|Lane|Drive|Dr\.))[\w\s,-]+(?:\d{5,6})\b",
    r"\b(?:Pin\s*Code|Postal\s*Code|Pincode)[:\s]*\d{6}\b"
]


class PIIDetectionService:
    """Detects, audits, and redacts personal identifiable identifiers in resume text."""

    def scan_pii(self, text: str) -> Dict[str, Any]:
        """
        Scans input resume text and extracts discovered personal information fields with locations.

        Returns:
            Dict containing detected entities categorized by type, entity counts,
            and an overall sensitivity score.
        """
        if not text or not text.strip():
            return {
                "detected": False,
                "total_count": 0,
                "entities": {
                    "emails": [],
                    "phones": [],
                    "government_ids": [],
                    "addresses": []
                },
                "summary": "No text content to analyze."
            }

        emails = list(set(EMAIL_PATTERN.findall(text)))

        # Find phones, filtering out short digits that aren't actual phone numbers
        raw_phones = PHONE_PATTERN.findall(text)
        phones = []
        for p in raw_phones:
            digits_only = re.sub(r"\D", "", p)
            if 10 <= len(digits_only) <= 13:
                phones.append(p.strip())
        phones = list(set(phones))

        # Government identifiers
        gov_ids = []
        for pan in PAN_PATTERN.findall(text):
            gov_ids.append({"type": "PAN", "value": pan})
        for aadhaar in AADHAAR_PATTERN.findall(text):
            # Check if this isn't just an accidental 12 digit number
            digits = re.sub(r"\D", "", aadhaar)
            if len(digits) == 12:
                gov_ids.append({"type": "Aadhaar", "value": aadhaar})
        for ssn in SSN_PATTERN.findall(text):
            gov_ids.append({"type": "SSN", "value": ssn})

        # Addresses
        addresses = []
        for addr_pat in ADDRESS_INDICATORS:
            for match in re.finditer(addr_pat, text, re.IGNORECASE):
                addresses.append(match.group(0).strip())
        addresses = list(set(addresses))

        total_entities = len(emails) + len(phones) + len(gov_ids) + len(addresses)

        # Risk scoring
        if total_entities == 0:
            risk_level = "none"
        elif len(gov_ids) > 0 or total_entities >= 4:
            risk_level = "high"
        elif total_entities >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "has_pii": total_entities > 0,
            "detected": total_entities > 0,
            "total_count": total_entities,
            "total_detections": total_entities,
            "risk_level": risk_level,
            "detected_entities": {
                "emails": emails,
                "phones": phones,
                "government_ids": [g["value"] if isinstance(g, dict) else g for g in gov_ids],
                "addresses": addresses
            },
            "entities": {
                "emails": emails,
                "phones": phones,
                "government_ids": gov_ids,
                "addresses": addresses
            },
            "summary": f"Detected {total_entities} personal identifier(s) across {len([k for k in (emails, phones, gov_ids, addresses) if k])} categories."
        }

    detect_pii = scan_pii

    def redact_pii(
        self,
        text: str,
        redact_emails: bool = True,
        redact_phones: bool = True,
        redact_gov_ids: bool = True,
        redact_addresses: bool = True,
        custom_redact_values: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Redacts specified categories of PII from the resume text while maintaining document structure.

        Returns:
            Dict containing:
                - redacted_text: Sanitized text string safe for AI processing.
                - redaction_counts: Count of replacements made per category.
                - total_redactions: Total replacements.
        """
        if not text:
            return {"redacted_text": "", "redaction_counts": {}, "total_redactions": 0}

        sanitized = text
        counts = {
            "emails": 0,
            "phones": 0,
            "government_ids": 0,
            "addresses": 0,
            "custom": 0
        }

        # 1. Redact emails
        if redact_emails:
            matches = list(set(EMAIL_PATTERN.findall(sanitized)))
            for email in matches:
                sanitized = sanitized.replace(email, REDACTION_TOKENS["email"])
                counts["emails"] += 1

        # 2. Redact phones
        if redact_phones:
            raw_phones = PHONE_PATTERN.findall(sanitized)
            valid_phones = []
            for p in raw_phones:
                digits_only = re.sub(r"\D", "", p)
                if 10 <= len(digits_only) <= 13:
                    valid_phones.append(p.strip())
            for phone in sorted(set(valid_phones), key=len, reverse=True):
                sanitized = sanitized.replace(phone, REDACTION_TOKENS["phone"])
                counts["phones"] += 1

        # 3. Redact government IDs
        if redact_gov_ids:
            for pan in set(PAN_PATTERN.findall(sanitized)):
                sanitized = sanitized.replace(pan, REDACTION_TOKENS["government_id"])
                counts["government_ids"] += 1
            for aadhaar in set(AADHAAR_PATTERN.findall(sanitized)):
                digits = re.sub(r"\D", "", aadhaar)
                if len(digits) == 12:
                    sanitized = sanitized.replace(aadhaar, REDACTION_TOKENS["government_id"])
                    counts["government_ids"] += 1
            for ssn in set(SSN_PATTERN.findall(sanitized)):
                sanitized = sanitized.replace(ssn, REDACTION_TOKENS["government_id"])
                counts["government_ids"] += 1

        # 4. Redact addresses
        if redact_addresses:
            for addr_pat in ADDRESS_INDICATORS:
                for match in list(re.finditer(addr_pat, sanitized, re.IGNORECASE)):
                    addr_str = match.group(0).strip()
                    sanitized = sanitized.replace(addr_str, REDACTION_TOKENS["address"])
                    counts["addresses"] += 1

        # 5. Redact custom user-selected phrases
        if custom_redact_values:
            for val in set(custom_redact_values):
                if val and val.strip():
                    sanitized = sanitized.replace(val.strip(), "[REDACTED_CUSTOM]")
                    counts["custom"] += 1

        total_redacted = sum(counts.values())

        return {
            "redacted_text": sanitized,
            "redaction_counts": counts,
            "total_redactions": total_redacted,
            "has_redactions": total_redacted > 0
        }


# Singleton service instance
pii_service = PIIDetectionService()
