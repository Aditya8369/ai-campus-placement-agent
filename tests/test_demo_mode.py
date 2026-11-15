"""
Test suite for 'Try with a sample resume' Demo Mode (#435):
- Opens without login and without any AI calls.
- Clear visible banner marks all demo content.
- Synthetic demo results are NEVER stored in any user history or database.
- Landing page includes 'Try with a sample resume' button.
- Real user session is cleanly preserved and restored upon demo exit.
"""

import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest
from flask import json

import config
from app import app
from utils.database import (
    init_db,
    get_analyses_history,
    get_db_connection,
    save_analysis,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_demo.db"
        monkeypatch.setattr(config, "DATABASE_PATH", db_path)
        init_db()
        yield db_path


# ==============================================================================
# 1. Demo Opens Without Login
# ==============================================================================

def test_demo_opens_without_login(client, test_db):
    """The demo opens without login (Acceptance Criteria)."""
    # Ensure unauthenticated visitor
    with client.session_transaction() as sess:
        sess.clear()

    # Access /demo route
    res = client.get("/demo", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Confirms visitor landed directly on the evaluation dashboard, NOT redirected to login
    assert "login" not in res.request.path
    assert "Placement Analysis Report" in html or "Candidate Evaluation" in html or "Alex Chen" in html or "readiness" in html.lower()
    assert "demoDataBanner" in html


def test_direct_demo_dashboard_access_without_login(client, test_db):
    """Direct access to /dashboard/demo-sample-analysis works without authentication."""
    with client.session_transaction() as sess:
        sess.clear()

    res = client.get("/dashboard/demo-sample-analysis")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "demoDataBanner" in html
    assert "Demo Data" in html


# ==============================================================================
# 2. Zero AI Calls During Demo
# ==============================================================================

def test_demo_opens_without_ai_calls(client, test_db):
    """Synthetic results are pre-computed; no AI / LLM calls must be triggered (Acceptance Criteria)."""
    with patch("agents.coordinator.CoordinatorAgent.analyze", side_effect=AssertionError("AI Coordinator must NOT be called")), \
         patch("utils.gemini.generate_json_response", side_effect=AssertionError("Gemini generate_json_response must NOT be called")), \
         patch("agents.outreach_agent.OutreachGeneratorAgent.generate_outreach", side_effect=AssertionError("OutreachAgent must NOT be called")), \
         patch("agents.role_prep_agent.RolePreparationAgent.generate_role_preparation", side_effect=AssertionError("RolePrepAgent must NOT be called")):

        res = client.get("/demo", follow_redirects=True)
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "demoDataBanner" in html
        assert "Google" in html


# ==============================================================================
# 3. Visible Banner Marks All Demo Content
# ==============================================================================

def test_visible_banner_marks_demo_content(client, test_db):
    """A visible banner marks all demo content (Acceptance Criteria)."""
    res = client.get("/dashboard/demo-sample-analysis")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Banner element verification
    assert "demoDataBanner" in html
    assert "Demo Data" in html
    assert "Sample Evaluation Demonstration" in html
    assert "Viewing evaluation results generated from a synthetic sample resume and job description" in html
    assert "btnExitDemo" in html
    assert "btnUploadOwnResume" in html
    assert "navDemoBadge" in html


# ==============================================================================
# 4. Demo Results Are Never Stored in History or Database
# ==============================================================================

def test_demo_results_never_stored_in_history_or_database(client, test_db):
    """Demo results are never stored in any user's history or database (Acceptance Criteria)."""
    # 1. Run demo evaluation
    res = client.get("/demo", follow_redirects=True)
    assert res.status_code == 200

    # 2. Verify SQLite database directly contains 0 demo records
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM analyses WHERE student_id = 'demo_visitor'")
        count_visitor = cursor.fetchone()[0]
        assert count_visitor == 0

        cursor.execute("SELECT COUNT(*) FROM analyses WHERE id = 'demo-sample-analysis'")
        count_demo_id = cursor.fetchone()[0]
        assert count_demo_id == 0

        cursor.execute("SELECT COUNT(*) FROM analyses")
        total_analyses = cursor.fetchone()[0]
        assert total_analyses == 0
    finally:
        conn.close()

    # 3. Verify history page contains 0 analyses
    history_items = get_analyses_history()
    assert len(history_items) == 0

    res_history = client.get("/history")
    if res_history.status_code == 200:
        html_history = res_history.data.decode("utf-8")
        assert "Alex Chen" not in html_history
        assert "demo-sample-analysis" not in html_history


# ==============================================================================
# 5. Real User Session Isolation & Restoration
# ==============================================================================

def test_real_user_session_isolation_and_restoration(client, test_db):
    """Logged-in users can try demo mode without polluting real account history."""
    # Simulate authenticated real user
    with client.session_transaction() as sess:
        sess["user_id"] = "student_real_alice"
        sess["user_name"] = "Alice"
        sess["user_email"] = "alice@university.edu"

    # Alice visits /demo
    res_demo = client.get("/demo", follow_redirects=True)
    assert res_demo.status_code == 200
    assert "demoDataBanner" in res_demo.data.decode("utf-8")

    # While in demo mode, session is demo_visitor
    with client.session_transaction() as sess:
        assert sess.get("is_demo_mode") is True
        assert sess.get("user_id") == "demo_visitor"
        assert sess.get("pre_demo_user_id") == "student_real_alice"

    # Exit demo mode via /demo/exit
    res_exit = client.get("/demo/exit", follow_redirects=True)
    assert res_exit.status_code == 200

    # Session is cleanly restored to Alice
    with client.session_transaction() as sess:
        assert sess.get("is_demo_mode") is None
        assert sess.get("user_id") == "student_real_alice"
        assert sess.get("user_name") == "Alice"


# ==============================================================================
# 6. Landing Page Has "Try with a sample resume" Button
# ==============================================================================

def test_landing_page_has_sample_resume_button(client, test_db):
    """The landing page displays the 'Try with a sample resume' button (Proposed Solution)."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert "btnTrySampleResume" in html
    assert "Try with a sample resume" in html
    assert "/demo" in html or "demo_mode_view" in html


# ==============================================================================
# 7. Sample Resume & Job Description API Endpoints
# ==============================================================================

def test_sample_resume_and_jd_api_endpoints(client, test_db):
    """REST APIs supply bundled synthetic sample resume and job description."""
    res_resume = client.get("/api/demo/sample-resume")
    assert res_resume.status_code == 200
    data_resume = json.loads(res_resume.data.decode("utf-8"))
    assert data_resume["status"] == "success"
    assert "ALEX CHEN" in data_resume["resume_text"]
    assert data_resume["target_company"] == "Google"

    res_jd = client.get("/api/demo/sample-job-description")
    assert res_jd.status_code == 200
    data_jd = json.loads(res_jd.data.decode("utf-8"))
    assert data_jd["status"] == "success"
    assert "Google LLC" in data_jd["job_description"]
    assert "Software Development Engineer" in data_jd["target_role"]


# ==============================================================================
# 8. AJAX Request to /demo
# ==============================================================================

def test_ajax_demo_request(client, test_db):
    """AJAX request to /demo returns JSON with redirect URL."""
    res = client.get("/demo", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 200
    data = json.loads(res.data.decode("utf-8"))
    assert data["status"] == "success"
    assert data["is_demo"] is True
    assert "demo-sample-analysis" in data["redirect_url"]
