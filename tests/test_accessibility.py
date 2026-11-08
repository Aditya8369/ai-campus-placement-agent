import pytest
import re
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_accessibility_focus_visible_styles():
    """Verify high-contrast :focus-visible outlines exist in stylesheet."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ":focus-visible" in css
    assert "outline:" in css or "outline-offset:" in css
    # Verify skip-link styling is present
    assert ".skip-link" in css
    assert "position: absolute" in css


def test_accessibility_javascript_module():
    """Verify initAccessibility registers modal focus trap, Escape key handler, and custom button listeners."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "function initAccessibility()" in js or "initAccessibility" in js
    assert "show.bs.modal" in js
    assert "hidden.bs.modal" in js
    assert "Escape" in js
    assert "role=\"button\"" in js or "role === 'button'" in js or 'role="button"' in js


def test_skip_to_content_links_in_key_templates(client):
    """Verify skip-to-content links and accessible main landmarks across pages."""
    endpoints = ["/", "/login", "/register", "/applications", "/calendar", "/leaderboard", "/history"]
    for endpoint in endpoints:
        res = client.get(endpoint)
        assert res.status_code == 200, f"Failed accessing {endpoint}"
        html = res.data.decode("utf-8")
        assert "skip-link" in html, f"Missing skip-link on {endpoint}"
        assert 'tabindex="-1"' in html or 'tabindex="0"' in html, f"Main content missing accessible tabindex on {endpoint}"


def test_modal_accessibility_attributes(client):
    """Verify modal windows have appropriate dialog roles and aria labels."""
    res = client.get("/applications")
    html = res.data.decode("utf-8")
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html

    res_cal = client.get("/calendar")
    html_cal = res_cal.data.decode("utf-8")
    assert 'role="dialog"' in html_cal
    assert 'aria-modal="true"' in html_cal


def test_form_field_explicit_labels(client):
    """Verify critical input fields have explicit labels linked via for/id attributes."""
    res_login = client.get("/login")
    html_login = res_login.data.decode("utf-8")
    assert 'for="loginEmail"' in html_login
    assert 'id="loginEmail"' in html_login
    assert 'for="loginPassword"' in html_login
    assert 'id="loginPassword"' in html_login

    res_reg = client.get("/register")
    html_reg = res_reg.data.decode("utf-8")
    assert 'for="regName"' in html_reg
    assert 'id="regName"' in html_reg
    assert 'for="regEmail"' in html_reg
    assert 'id="regEmail"' in html_reg


def test_upload_area_keyboard_accessible(client):
    """Verify the file upload drop area has button semantics, tabindex, and aria-label."""
    res = client.get("/")
    html = res.data.decode("utf-8")
    assert 'id="uploadArea"' in html
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert 'aria-label' in html

