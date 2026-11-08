"""
tests/test_password_strength.py
Unit and integration tests for Password Strength Indicator and Security (#290).
"""

import os
import re
import pytest
from utils.password_security import evaluate_password_strength


def test_empty_password():
    """Verify empty or None passwords return initial state with suggestions."""
    result = evaluate_password_strength("")
    assert result["score"] == 0
    assert result["percentage"] == 0
    assert result["strength"] == "Empty"
    assert result["criteria"]["length"] is False
    assert result["criteria"]["uppercase"] is False
    assert result["criteria"]["lowercase"] is False
    assert result["criteria"]["number"] is False
    assert result["criteria"]["special"] is False
    assert len(result["suggestions"]) > 0
    # Ensure plaintext password is not in result
    assert "password" not in result


def test_weak_passwords():
    """Verify weak passwords across length and complexity shortages."""
    # Too short (< 8 chars)
    short = evaluate_password_strength("Ab1!")
    assert short["strength"] == "Weak"
    assert short["criteria"]["length"] is False
    assert "Use at least 8 characters." in short["suggestions"]

    # Only lowercase
    only_lower = evaluate_password_strength("alllowercasechars")
    assert only_lower["strength"] == "Weak"
    assert only_lower["criteria"]["length"] is True
    assert only_lower["criteria"]["uppercase"] is False
    assert only_lower["criteria"]["number"] is False
    assert only_lower["criteria"]["special"] is False

    # Only numbers
    only_nums = evaluate_password_strength("1234567890")
    assert only_nums["strength"] == "Weak"
    assert only_nums["criteria"]["lowercase"] is False


def test_medium_passwords():
    """Verify medium passwords that meet length and several criteria but not all."""
    # Has length, upper, lower, numbers, but missing special characters
    med1 = evaluate_password_strength("Password1234")
    assert med1["strength"] == "Medium"
    assert med1["score"] == 4
    assert med1["percentage"] == 80
    assert med1["criteria"]["special"] is False
    assert any("special character" in s for s in med1["suggestions"])

    # Has length, upper, lower, special, but missing numbers
    med2 = evaluate_password_strength("Password!@#$")
    assert med2["strength"] == "Medium"
    assert med2["score"] == 4
    assert med2["criteria"]["number"] is False
    assert any("number" in s for s in med2["suggestions"])


def test_strong_passwords():
    """Verify strong passwords meeting all 5 criteria."""
    strong = evaluate_password_strength("SuperSecureP@ssw0rd2026!")
    assert strong["strength"] == "Strong"
    assert strong["score"] == 5
    assert strong["percentage"] == 100
    assert strong["criteria"]["length"] is True
    assert strong["criteria"]["uppercase"] is True
    assert strong["criteria"]["lowercase"] is True
    assert strong["criteria"]["number"] is True
    assert strong["criteria"]["special"] is True
    assert len(strong["suggestions"]) == 0


def test_password_never_stored_in_result():
    """Ensure sensitive plaintext password is not echoed in evaluation dictionary."""
    secret = "SuperSecretPlainText123!#"
    result = evaluate_password_strength(secret)
    assert secret not in str(result)
    assert "password" not in result


def test_register_template_dom_elements():
    """Verify register.html has all required elements for password strength and show/hide toggle."""
    template_path = os.path.join("templates", "register.html")
    assert os.path.exists(template_path)

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Password input field with id and attributes
    assert 'id="regPassword"' in content
    assert 'name="password"' in content
    assert 'minlength="8"' in content
    assert 'autocomplete="new-password"' in content

    # Show/hide password button
    assert 'id="togglePasswordBtn"' in content
    assert 'id="togglePasswordIcon"' in content
    assert 'aria-label="Show password"' in content

    # Password strength container
    assert 'id="passwordStrengthContainer"' in content
    assert 'id="strengthProgressBar"' in content
    assert 'id="strengthLabel"' in content

    # Requirements checklist
    assert 'id="reqLength"' in content
    assert 'id="reqUpper"' in content
    assert 'id="reqLower"' in content
    assert 'id="reqNumber"' in content
    assert 'id="reqSpecial"' in content

    # Suggestions container
    assert 'id="passwordSuggestions"' in content
    assert 'id="suggestionsList"' in content

    # External assets
    assert "font-awesome" in content.lower()
    assert "script.js" in content


def test_script_js_security_and_toggle():
    """Verify static/js/script.js implements real-time handling and does not persist passwords."""
    js_path = os.path.join("static", "js", "script.js")
    assert os.path.exists(js_path)

    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # Function exists and called on DOMContentLoaded
    assert "initPasswordStrengthIndicator" in js_content
    assert "initPasswordStrengthIndicator()" in js_content

    # Toggle password visibility logic
    assert "togglePasswordBtn" in js_content
    assert 'passwordInput.setAttribute("type"' in js_content or "passwordInput.type =" in js_content

    # Real-time event listeners
    assert 'passwordInput.addEventListener("input"' in js_content
    assert 'passwordInput.addEventListener("keyup"' in js_content

    # Security check: ensure script does not store password in storage or cookies
    match_storage = re.findall(r'(localStorage|sessionStorage|document\.cookie)\s*\.\s*setItem\([^)]*password', js_content, re.IGNORECASE)
    assert len(match_storage) == 0, f"Detected password persistence in client storage: {match_storage}"


def test_css_styles_exist():
    """Verify static/css/style.css contains styles for strength states and toggle button."""
    css_path = os.path.join("static", "css", "style.css")
    assert os.path.exists(css_path)

    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert ".password-strength-container" in css_content
    assert ".strength-bar-weak" in css_content
    assert ".strength-bar-medium" in css_content
    assert ".strength-bar-strong" in css_content
    assert ".btn-toggle-password" in css_content
    assert ".req-met" in css_content
    assert ".req-unmet" in css_content
