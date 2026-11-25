"""
utils/password_security.py
Password Strength and Security Evaluator (#290, #850).

Provides real-time password strength scoring, criteria evaluation, and actionable
suggestions for account creation during student registration, as well as server-side
enforcement against weak, common, and breached passwords (#850).

Evaluates:
- Minimum length (>= 8 characters)
- Uppercase letters (A-Z)
- Lowercase letters (a-z)
- Numbers (0-9)
- Special characters (!@#$%^&*...)
Rates passwords as Weak, Medium, or Strong.

Security Guarantees:
- The candidate password is evaluated strictly in-memory during function execution.
- It is never logged, printed, cached, or persisted to disk, database, or external services.
- Only the first 5 hexadecimal characters of the SHA-1 hash (k-anonymity prefix) are ever
  sent to the HaveIBeenPwned range API.
- If the Pwned Passwords API lookup fails or times out, the check fails open with a warning
  to ensure user registration and password updates are never blocked by third-party outages.
"""

import hashlib
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SPECIAL_CHARACTERS = set("!@#$%^&*()_+-=[]{}|;':\",./<>?~`\\^")

# Top common/easily-guessed passwords blocked at registration and reset (#850)
COMMON_PASSWORDS: frozenset[str] = frozenset({
    "12345678",
    "123456789",
    "1234567890",
    "password",
    "password1",
    "password12",
    "password123",
    "password1234",
    "passphrase",
    "qwertyuiop",
    "qwerty123",
    "qwertyui",
    "admin123",
    "administrator",
    "welcome1",
    "welcome123",
    "iloveyou",
    "changeme",
    "letmein1",
    "sunshine",
    "princess",
    "football",
    "baseball",
    "monkey123",
    "master123",
    "testing123",
    "login123",
    "default123",
    "pass1234",
    "superman",
    "trustno1",
    "shadow123",
    "dragon12",
    "hunter12",
    "mustang1",
    "michael1",
    "jessica1",
    "charlie1",
    "starwars",
    "secret12",
    "whatever",
    "freedom1",
    "computer",
    "access12",
})


def evaluate_password_strength(password: str) -> Dict[str, Any]:
    """
    Evaluates password strength across length, casing, numbers, and special characters.

    Args:
        password: The plaintext candidate password string.

    Returns:
        Dict containing score (0-5), percentage (0-100), strength label ('Weak', 'Medium', 'Strong'),
        criteria boolean status, and an array of suggestions for improvement.
        Does NOT return or store the original password.
    """
    if not password:
        return {
            "score": 0,
            "max_score": 5,
            "percentage": 0,
            "strength": "Empty",
            "criteria": {
                "length": False,
                "uppercase": False,
                "lowercase": False,
                "number": False,
                "special": False,
            },
            "suggestions": [
                "Use at least 8 characters.",
                "Include both uppercase and lowercase letters.",
                "Include at least one number (0-9).",
                "Include at least one special character (e.g. !@#$%^&*).",
            ],
        }

    has_length = len(password) >= 8
    has_uppercase = any(c.isupper() for c in password)
    has_lowercase = any(c.islower() for c in password)
    has_number = any(c.isdigit() for c in password)
    has_special = any(c in SPECIAL_CHARACTERS for c in password)

    passed_count = sum([
        has_length,
        has_uppercase,
        has_lowercase,
        has_number,
        has_special,
    ])

    suggestions: List[str] = []
    if not has_length:
        suggestions.append("Use at least 8 characters.")
    if not has_lowercase:
        suggestions.append("Add at least one lowercase letter (a-z).")
    if not has_uppercase:
        suggestions.append("Add at least one uppercase letter (A-Z).")
    if not has_number:
        suggestions.append("Add at least one number (0-9).")
    if not has_special:
        suggestions.append("Add at least one special character (e.g. !@#$%^&*).")

    # Score calculation: passwords shorter than 8 characters are capped at Weak
    score = passed_count
    if not has_length and score > 2:
        score = 2

    percentage = int((score / 5) * 100)

    if score <= 2:
        strength = "Weak"
    elif score in (3, 4):
        strength = "Medium"
    else:
        strength = "Strong"

    return {
        "score": score,
        "max_score": 5,
        "percentage": percentage,
        "strength": strength,
        "criteria": {
            "length": has_length,
            "uppercase": has_uppercase,
            "lowercase": has_lowercase,
            "number": has_number,
            "special": has_special,
        },
        "suggestions": suggestions,
    }


def check_pwned_password(password: str, timeout: float = 2.0) -> bool:
    """
    Checks if a password has appeared in known data breaches using the
    HaveIBeenPwned Pwned Passwords range API with k-anonymity (#850).

    Security & Privacy:
    - Only the first 5 characters of the SHA-1 hash (the prefix) are sent to the external API.
    - The remainder (suffix) is searched locally against the returned list of hashes.
    - Plaintext passwords and hash suffixes are never logged, printed, or sent externally.
    - If any network error, HTTP error, or timeout occurs, the function fails open (returns False)
      and logs a warning so registration/reset is not blocked.

    Args:
        password: The candidate password string to verify.
        timeout: Maximum seconds to wait for the API response (defaults to 2.0s).

    Returns:
        True if the password hash suffix is found in the returned range (breached),
        False if safe or if the API check fails (fail-open).
    """
    if not password:
        return False

    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1_hex[:5]
    suffix = sha1_hex[5:]

    api_url = f"https://api.pwnedpasswords.com/range/{prefix}"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "ai-campus-placement-agent-security-validator",
            "Add-Padding": "true",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = getattr(response, "status", getattr(response, "code", 200))
            if status_code != 200:
                logger.warning(
                    "Pwned Passwords API returned status %s; failing open.",
                    status_code,
                )
                return False
            payload = response.read().decode("utf-8", errors="ignore")

        for line in payload.splitlines():
            line_suffix = line.split(":", 1)[0].strip().upper()
            if line_suffix == suffix:
                return True

        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Pwned Passwords API lookup failed: %s; failing open.", exc)
        return False


def validate_password_security(
    password: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    check_pwned: bool = True,
    pwned_timeout: float = 2.0,
) -> Tuple[bool, Optional[str]]:
    """
    Validates candidate password against security policies:
    1. Minimum length (at least 8 characters)
    2. Contextual uniqueness (cannot match email address or user's name)
    3. Common password blocklist (rejects easily guessed common passwords)
    4. Breached password check (via k-anonymity HIBP range API)

    Args:
        password: The plaintext candidate password.
        email: Optional email address to verify against contextual matching.
        name: Optional user full name to verify against contextual matching.
        check_pwned: Whether to perform the external HIBP range check.
        pwned_timeout: Timeout in seconds for the HIBP range check.

    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str]).
        If valid, returns (True, None).
        If invalid, returns (False, descriptive_error_message).
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."

    pwd_lower = password.strip().lower()

    # Contextual check: cannot match user's name or email
    if email:
        email_clean = email.strip().lower()
        local_part = email_clean.split("@")[0] if "@" in email_clean else email_clean
        if pwd_lower == email_clean or (len(local_part) >= 3 and pwd_lower == local_part):
            return False, "Password cannot match your name or email address."

    if name:
        name_clean = name.strip().lower()
        if len(name_clean) >= 3 and pwd_lower == name_clean:
            return False, "Password cannot match your name or email address."
        name_no_spaces = "".join(name_clean.split())
        if len(name_no_spaces) >= 3 and pwd_lower == name_no_spaces:
            return False, "Password cannot match your name or email address."
        for part in re.split(r"[\s._-]+", name_clean):
            if len(part) >= 3 and pwd_lower == part:
                return False, "Password cannot match your name or email address."

    # Common passwords blocklist check
    if pwd_lower in COMMON_PASSWORDS:
        return False, "Password is too common and easily guessed. Please choose a stronger password."

    # Breached passwords check via k-anonymity range API
    if check_pwned:
        is_breached = check_pwned_password(password, timeout=pwned_timeout)
        if is_breached:
            return (
                False,
                "This password has appeared in a known data breach. Please choose a different, secure password.",
            )

    return True, None
