"""
Unit tests for empty states across dashboard, recent analyses drawer, and tables (#130).
"""

from app import app


def test_dashboard_empty_states_rendered():
    """Verify that dashboard template includes empty state containers and action buttons."""
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "skillGapNoItemsInitial" in html
    assert "No Skill Gaps Identified" in html
    assert "skillGapEmptyState" in html
    assert "No Matching Skills Found" in html
    assert "Clear Filters" in html


def test_script_js_recent_analyses_empty_state():
    """Verify script.js renders a styled empty state card when no past analyses exist."""
    with open("static/js/script.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "initRecentAnalysesDrawer" in js
    assert "No Analysis History" in js
    assert "Start First Analysis" in js
    assert "Service Unavailable" in js
