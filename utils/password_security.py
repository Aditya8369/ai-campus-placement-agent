"""
utils/password_security.py
Password Strength and Security Evaluator (#290).

Provides real-time password strength scoring, criteria evaluation, and actionable
suggestions for account creation during student registration.
Evaluates:
- Minimum length (>= 8 characters)
- Uppercase letters (A-Z)
- Lowercase letters (a-z)
- Numbers (0-9)
- Special characters (!@#$%^&*...)
Rates passwords as Weak, Medium, or Strong.

Security Guarantee:
The password string is evaluated strictly in-memory during function execution.
It is never logged, printed, cached, or persisted to disk, database, or external services.
"""

from typing import Dict, Any, List

SPECIAL_CHARACTERS = set("!@#$%^&*()_+-=[]{}|;':\",./<>?~`\\^")


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
