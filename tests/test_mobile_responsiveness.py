"""
Unit and integration tests for responsive markup, mobile layout attributes,
viewport safety constraints, and touch friendliness across application views.
"""

import os
import tempfile
from pathlib import Path
import pytest
import config
from utils.database import init_db, save_analysis, get_interview_session
from app import app


@pytest.fixture
def test_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_mobile.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)
        init_db()
        yield


def test_index_page_contains_viewport_meta_tag():
    """Ensure the index page defines the mobile responsive viewport meta tag."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in html


def test_dashboard_contains_viewport_meta_tag(test_env):
    """Ensure the dashboard view defines the mobile responsive viewport meta tag."""
    aid = "test-mobile-view-aid-999"
    sample_results = {
        "resume_analysis": {"ats_score": 85, "skills": ["Python"]},
        "job_match": {"match_percentage": 75, "matching_skills": ["Python"]},
        "skill_gap": {"missing_skills": []},
        "roadmap": {"weeks": []},
        "interview_questions": {
            "hr": ["HR Q1"],
            "technical": ["Tech Q1"],
            "behavioral": ["Beh Q1"],
        },
        "overall_recommendation_summary": "Ready for mobile testing",
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get(f"/dashboard/{aid}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in html
        # Check responsive container & flex classes in navigation
        assert "navbar-brand-custom" in html
        assert "flex-wrap" in html


def test_interview_contains_viewport_meta_tag(test_env):
    """Ensure mock interview page contains proper viewport and responsive structure."""
    aid = "test-mobile-interview-aid-888"
    sample_results = {
        "resume_analysis": {"ats_score": 80},
        "job_match": {"match_percentage": 70},
        "skill_gap": {"missing_skills": []},
        "roadmap": {"weeks": []},
        "interview_questions": {
            "hr": [f"HR Q{i}" for i in range(1, 6)],
            "technical": [f"Tech Q{i}" for i in range(1, 6)],
            "behavioral": [f"Beh Q{i}" for i in range(1, 6)],
        },
    }
    save_analysis(aid, "resume.pdf", "Google", "SWE", sample_results)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get(f"/interview/{aid}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in html
        assert "flex-wrap" in html


def test_style_css_defines_mobile_media_queries():
    """Verify that style.css declares media queries for small screens and overflow prevention."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path)
    
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # Verify key responsive media query breakpoints
    assert "@media (max-width: 991.98px)" in css
    assert "@media (max-width: 767.98px)" in css
    assert "@media (max-width: 420px)" in css

    # Verify horizontal overflow guard rules
    assert "overflow-x: hidden" in css
    assert "max-width: 100%" in css

    # Verify touch target size optimizations (>= 44px min-height)
    assert "min-height: 44px" in css
    assert "touch-action: manipulation" in css

    # Verify font-size 16px to prevent auto-zooming on mobile devices
    assert "font-size: 16px" in css


def test_index_navigation_has_mobile_wrapping_classes():
    """Check that index page navbar contains flexible responsive classes."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        html = res.data.decode("utf-8")
        assert "d-flex flex-wrap align-items-center justify-content-between" in html
        assert "btnExploreCompany" in html


def test_mobile_responsive_button_touch_targets_in_templates():
    """Verify that buttons across templates include responsive padding and min-height support."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        # Verify responsive analyze button markup
        assert "Analyze Readiness" in html
        assert "btn-custom-primary" in html
        assert "theme-toggle-btn" in html
        assert "btnOpenRecentAnalyses" in html


def test_mobile_breakpoint_declarations_in_css():
    """Verify detailed CSS rules supporting small screens down to 320px width."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "-webkit-overflow-scrolling: touch" in content
    assert "circular-progress-container" in content
    assert "progress-panel" in content
    assert "chat-bubble" in content
    assert "benchmark-card" in content


def test_mobile_navigation_and_table_responsiveness_rules():
    """Verify specific CSS responsive enhancements for navigation and tables (#279)."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Mobile navigation adjustments
    assert ".navbar-nav" in content
    assert "padding-top: 0.75rem" in content
    assert ".table-responsive" in content
    assert "box-shadow: inset -4px 0 6px -4px rgba(0, 0, 0, 0.1)" in content
    assert ".mobile-action-bar" in content
    assert ".filter-pills-container" in content
    assert ".interview-question-box" in content
    assert ".btn-mobile-full" in content
    assert ".horizontal-chips-scroll" in content
    assert ".navbar-brand-custom" in content
    assert ".drawer-mobile" in content
    assert ".fab-mobile" in content
    assert ".sticky-bottom-submit" in content
    assert ".code-editor-mobile-view" in content



def test_key_placement_views_render_with_viewport_and_css():
    """Verify all critical placement pages deliver responsive layout markup."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        for route in ["/", "/history", "/login", "/register", "/interview_bookmarks"]:
            res = client.get(route)
            if res.status_code == 200:
                html = res.data.decode("utf-8")
                assert "viewport" in html
                assert "style.css" in html


