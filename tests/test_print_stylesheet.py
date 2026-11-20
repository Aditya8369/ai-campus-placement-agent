"""
Unit tests for Print-Friendly Stylesheet and 'Print this page' Dashboard Integration (#472).

Covers:
1. Dedicated print stylesheet (static/css/print.css) and linkage in dashboard and base templates.
2. Suppression of navigation, buttons, floating widgets, and decorative backgrounds.
3. Ink-saving high-contrast rules (black text on white, dark mode overrides).
4. Page-break prevention inside cards, panels, and table rows.
5. Repeating table headers on every page (thead display: table-header-group).
6. Automatic expansion of collapsed accordions in print.
7. Selective link URL printing (only where useful, not internal navigation).
8. Preservation and print-color-adjust for charts, gauges, canvas, and badges.
9. "Print this page" button presence and behavior on the dashboard.
"""

import os
import re
import pytest
from app import app


def test_print_stylesheet_file_exists():
    """Verify static/css/print.css exists and contains valid CSS."""
    path = os.path.join("static", "css", "print.css")
    assert os.path.isfile(path), "static/css/print.css must exist"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert len(content) > 100
    assert "@media print" in content


def test_dashboard_and_base_templates_link_print_stylesheet():
    """Templates should link print.css with media='print'."""
    for template_name in ["templates/dashboard.html", "templates/base.html"]:
        with open(template_name, "r", encoding="utf-8") as f:
            html = f.read()
        assert "css/print.css" in html, f"{template_name} must link print.css"
        assert 'media="print"' in html or "media='print'" in html, f"{template_name} must specify media='print'"


def test_dashboard_provides_print_this_page_button():
    """Dashboard must contain a 'Print this page' button invoking window.print()."""
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "btnPrintThisPage" in html
    assert "Print this page" in html
    assert "window.print()" in html


def test_navigation_and_buttons_hidden_in_print():
    """Navigation chrome and buttons must have display: none !important."""
    for css_file in ["static/css/print.css", "static/css/style.css"]:
        with open(css_file, "r", encoding="utf-8") as f:
            css = f.read()

        # Check suppression of navigation
        assert "nav.navbar" in css or ".navbar" in css
        assert "display: none !important" in css

        # Check suppression of buttons and interactive controls
        assert ".btn" in css or "button" in css
        assert ".theme-toggle-btn" in css or "button" in css


def test_floating_widgets_and_drawers_hidden_in_print():
    """Floating widgets, toasts, back-to-top buttons, and modals must be hidden."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    hidden_selectors = [
        "back-to-top-btn",
        "copy-toast-container",
        "modal",
        "chat-widget",
        "floating-widget",
        "fab",
        "progress-overlay",
    ]
    for sel in hidden_selectors:
        assert sel in css, f"Selector '{sel}' must be hidden in print stylesheet"


def test_decorative_backgrounds_and_animations_removed():
    """Decorative animated backgrounds, gradients, and box-shadows must be disabled."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "box-shadow: none !important" in css
    assert "background-image: none !important" in css
    assert "animation: none !important" in css
    assert "mesh-gradient" in css or "blob" in css or "glow" in css


def test_high_contrast_black_text_on_white():
    """Body and cards must enforce black text on white background and reset dark theme."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "color: #000000 !important" in css
    assert "background-color: #ffffff !important" in css or "background: #ffffff !important" in css
    # Ensure dark mode is specifically overridden
    assert '[data-bs-theme="dark"]' in css


def test_page_breaks_inside_cards_and_tables_avoided():
    """Cards, panels, and table rows must avoid splitting across printed pages."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "page-break-inside: avoid !important" in css or "break-inside: avoid !important" in css
    assert "tr" in css
    assert ".card" in css


def test_table_headers_repeated_on_each_page():
    """Table thead elements must repeat headers on each page with display: table-header-group."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "thead" in css
    assert "table-header-group !important" in css


def test_collapsed_accordions_expanded_in_print():
    """Collapsed accordions must automatically expand in print mode to reveal content."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".collapse" in css or ".accordion-collapse" in css
    assert "display: block !important" in css
    assert ".accordion-button::after" in css


def test_charts_and_visual_indicators_preserved_in_print():
    """Canvas elements, circular SVGs, and badges must remain visible with print-color-adjust."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "canvas" in css
    assert "svg" in css
    assert "print-color-adjust: exact !important" in css or "-webkit-print-color-adjust: exact !important" in css
    assert ".badge" in css


def test_links_show_urls_only_where_useful():
    """Internal links must not dump raw hrefs, while explicit print-url links display URL."""
    with open("static/css/print.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert 'a[href]::after' in css
    assert 'attr(href)' in css
    assert 'print-url' in css or 'article a' in css
