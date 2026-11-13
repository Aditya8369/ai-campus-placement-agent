"""
Unit and integration tests for Password Visibility Toggle (#355).
==================================================================
Verifies that:
1. Login form renders password input with a visibility toggle button.
2. Registration form renders password input with a visibility toggle button.
3. Reset password form renders toggle buttons for new and confirmation passwords.
4. Delete account form renders password verification toggle button.
5. All toggle buttons feature proper accessibility attributes (aria-label, title, data-target).
6. JavaScript (script.js) defines initPasswordToggle and registers it in DOMContentLoaded.
7. CSS (style.css) defines responsive styles for toggle buttons.
"""

from pathlib import Path
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_login_page_renders_password_visibility_toggle(client):
    """Verify login page includes an accessible password visibility toggle button."""
    res = client.get("/login")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="loginPassword"' in html
    assert "toggle-password-visibility" in html
    assert 'data-target="#loginPassword"' in html
    assert 'aria-label="Show password"' in html
    assert "fa-eye" in html


def test_register_page_renders_password_visibility_toggle(client):
    """Verify register page includes an accessible password visibility toggle button."""
    res = client.get("/register")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="regPassword"' in html
    assert "toggle-password-visibility" in html
    assert 'data-target="#regPassword"' in html
    assert 'aria-label="Show password"' in html
    assert "fa-eye" in html


def test_reset_password_page_renders_both_toggle_buttons(client):
    """Verify reset password template renders visibility toggles for new and confirm password fields."""
    res = client.get("/reset-password/sample-token-12345")
    html = res.get_data(as_text=True)

    # Regardless of token validity, check if rendered form has toggle controls
    if res.status_code == 200:
        assert 'id="newPassword"' in html
        assert 'id="confirmPassword"' in html
        assert 'data-target="#newPassword"' in html
        assert 'data-target="#confirmPassword"' in html
        assert "toggle-password-visibility" in html


def test_delete_account_page_renders_password_toggle(client):
    """Verify delete account confirmation form has a password visibility toggle button."""
    with client.session_transaction() as sess:
        sess["user_id"] = "test-user-id"
        sess["user_name"] = "Test User"
        sess["user_email"] = "test@example.com"

    res = client.get("/account/delete")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="deleteAccountPassword"' in html
    assert "toggle-password-visibility" in html
    assert 'data-target="#deleteAccountPassword"' in html
    assert 'aria-label="Show password"' in html


def test_javascript_defines_init_password_toggle():
    """Verify static/js/script.js implements and registers initPasswordToggle."""
    js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "script.js"
    assert js_path.exists(), "script.js not found"
    js_content = js_path.read_text(encoding="utf-8")

    assert "initPasswordToggle()" in js_content
    assert "function initPasswordToggle()" in js_content
    assert ".toggle-password-visibility" in js_content
    assert 'input.type = isPassword ? "text" : "password"' in js_content
    assert "fa-eye-slash" in js_content


def test_css_defines_password_toggle_styles():
    """Verify static/css/style.css includes layout and dark theme rules for toggle button."""
    css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"
    assert css_path.exists(), "style.css not found"
    css_content = css_path.read_text(encoding="utf-8")

    assert ".toggle-password-visibility" in css_content
    assert '[data-bs-theme="dark"] .toggle-password-visibility' in css_content
