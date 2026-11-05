"""
Unit tests for print-friendly report button and CSS media print rules (#138).
"""

from app import app


def test_dashboard_template_contains_print_button():
    """Verify that dashboard template provides a Print Report button."""
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "btn-print-report" in html
    assert "window.print()" in html
    assert "Print" in html


def test_css_contains_print_media_rules():
    """Verify style.css declares @media print rules suppressing nav, buttons, and configuring page-break."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "@media print" in css
    assert "nav.navbar" in css
    assert "page-break-inside: avoid" in css
    assert "break-inside: avoid" in css
    assert "display: none !important" in css
    assert "table-header-group" in css
