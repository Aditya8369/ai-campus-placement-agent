"""
Unit and integration tests for Light/Dark theme switching, CSS variables,
system preference detection, and UI component readability in dark mode (#158).

Tests verify:
- CSS variables defined for both light and dark themes in static/css/style.css.
- Theme toggle button present in the navbar across templates.
- System preference (prefers-color-scheme) detection and localStorage persistence in script.js.
- High contrast and readability rules for dashboard cards, interview chat, tables, and accordions.
- Mobile responsiveness of the theme toggle button.
"""

import os
from pathlib import Path
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_css_variables_defined_for_light_and_dark_themes():
    """Verify that style.css declares CSS variables in :root and [data-bs-theme='dark']."""
    css_path = Path("static/css/style.css")
    assert css_path.exists()
    content = css_path.read_text(encoding="utf-8")

    # Light / :root variables
    assert ":root" in content
    assert "--primary-blue:" in content
    assert "--bg-color:" in content
    assert "--card-bg:" in content
    assert "--border-color:" in content
    assert "--text-dark:" in content
    assert "--accordion-bg:" in content
    assert "--table-bg:" in content
    assert "--chat-bubble-agent-bg:" in content

    # Dark mode overrides
    assert '[data-bs-theme="dark"]' in content
    assert "--bg-color: #0d1117;" in content
    assert "--card-solid-bg: #161b22;" in content
    assert "--text-dark: #e6edf3;" in content
    assert "--border-color: #30363d;" in content


def test_all_primary_templates_contain_theme_toggle_button():
    """Verify every primary page template contains the .theme-toggle-btn in its navbar."""
    templates_to_check = [
        "index.html",
        "dashboard.html",
        "interview.html",
        "applications.html",
        "batch_compare.html",
        "coding_practice.html",
        "github_analyzer.html",
        "internships.html",
        "interview_history.html",
        "leaderboard.html",
        "linkedin_analyzer.html",
        "my_reports.html",
        "resume_compare.html",
    ]

    for tpl_name in templates_to_check:
        tpl_path = Path("templates") / tpl_name
        assert tpl_path.exists(), f"Template {tpl_name} does not exist"
        html = tpl_path.read_text(encoding="utf-8")
        assert "theme-toggle-btn" in html, f"Template {tpl_name} missing .theme-toggle-btn in navbar"


def test_script_js_theme_toggle_and_persistence_logic():
    """Verify script.js checks localStorage, prefers-color-scheme, and sets data-bs-theme."""
    js_path = Path("static/js/script.js")
    assert js_path.exists()
    js = js_path.read_text(encoding="utf-8")

    assert "initThemeToggle" in js
    assert "getPreferredTheme" in js
    assert "prefers-color-scheme: dark" in js
    assert "localStorage.getItem" in js
    assert "localStorage.setItem" in js
    assert 'setAttribute("data-bs-theme"' in js
    assert "fa-sun" in js
    assert "fa-moon" in js


def test_dark_mode_component_readability_rules_in_css():
    """Ensure dashboard, tables, accordions, and interview chat have explicit dark mode rules."""
    css = Path("static/css/style.css").read_text(encoding="utf-8")

    # Accordions
    assert '[data-bs-theme="dark"] .accordion-item' in css
    assert '[data-bs-theme="dark"] .accordion-button' in css
    assert '[data-bs-theme="dark"] .accordion-body' in css

    # Tables
    assert '[data-bs-theme="dark"] .table' in css
    assert '[data-bs-theme="dark"] thead.table-light th' in css

    # Interview Chat
    assert '[data-bs-theme="dark"] .chat-window' in css
    assert ".chat-bubble-agent" in css
    assert ".chat-bubble-question" in css
    assert ".chat-bubble-evaluation" in css

    # Forms & Dialogs
    assert '[data-bs-theme="dark"] .form-control' in css
    assert '[data-bs-theme="dark"] .modal-content' in css
    assert '[data-bs-theme="dark"] .card' in css


def test_theme_toggle_button_mobile_responsiveness():
    """Verify theme toggle button includes mobile styling and touch sizing."""
    css = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".theme-toggle-btn" in css
    assert "@media (max-width: 575.98px)" in css

