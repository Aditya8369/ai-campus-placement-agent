"""
Unit and integration tests for Mock Interview Answer Draft Autosave and Ctrl/Cmd+Enter Shortcut (#475).

Verifies:
1. Client-side autosave of answer text to browser storage (localStorage) keyed by session and question index.
2. Draft restoration on page load/reload, updating word counter and showing draft status indicator.
3. Ctrl/Cmd + Enter keyboard shortcut submitting only when answer is not empty.
4. Draft is never sent to the server before the student explicitly submits.
5. Draft clearing:
   - Cleared on successful answer submission for the active question.
   - Cleared for the entire session when the interview round is completed or restarted.
   - Cleared across all interview sessions when the user logs out.
6. Seamless integration with timed mode and word counter.
"""

import json
import re
import tempfile
from pathlib import Path
import pytest
from app import app
import config
from utils.database import (
    init_db,
    save_analysis,
    create_interview_session,
    get_interview_session,
)


@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with an isolated temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_interview_drafts.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Template Structure & DOM Elements
# ==============================================================================

def test_interview_template_contains_draft_and_shortcut_elements():
    """Verify interview.html template contains session/question data attributes, Ctrl/Cmd+Enter hint, and draft badge."""
    with open("templates/interview.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Form attributes for session and question identification
    assert 'id="chatForm"' in html
    assert 'data-analysis-id="{{ analysis_id }}"' in html
    assert 'data-session-id="{{ session_id or analysis_id }}"' in html
    assert 'data-question-index="{{ interview.current_question_index }}"' in html

    # Answer textarea and word counter
    assert 'id="answerInput"' in html
    assert 'id="wordCountBadge"' in html

    # Ctrl/Cmd + Enter hint and draft status badge
    assert 'id="submitShortcutHint"' in html
    assert 'Ctrl+Enter' in html or 'Ctrl' in html
    assert 'Cmd+Enter' in html or 'Cmd' in html
    assert 'id="draftStatusBadge"' in html
    assert 'aria-live="polite"' in html


# ==============================================================================
# 2. Client-Side JavaScript Logic Verification
# ==============================================================================

def _get_interview_js_content():
    p_int = Path("static/js/modules/interview.js")
    p_com = Path("static/js/modules/common.js")
    if p_int.exists() and p_com.exists():
        return p_int.read_text(encoding="utf-8") + "\n" + p_com.read_text(encoding="utf-8")
    return Path("static/js/script.js").read_text(encoding="utf-8")


def test_script_js_contains_draft_autosave_functions():
    """Verify script.js defines draft storage key generation, saving, restoring, and clearing."""
    js = _get_interview_js_content()

    assert "function getDraftStorageKey" in js
    assert "function saveCurrentDraft" in js
    assert "function restoreCurrentDraft" in js
    assert "function clearDraftForQuestion" in js
    assert "function clearAllDraftsForThisSession" in js
    assert "function clearAllInterviewDrafts" in js
    assert "interview_draft_" in js


def test_script_js_autosave_triggers_and_timing():
    """Verify autosave occurs on typing input, periodic timer (every 2.5s), and beforeunload."""
    js = _get_interview_js_content()

    # Debounced input listener
    assert "saveCurrentDraft" in js
    assert "draftDebounceTimer" in js

    # Periodic interval (2500ms / 2.5s)
    assert "setInterval(saveCurrentDraft, 2500)" in js

    # Unload event listener for sudden navigation or accidental reload
    assert 'window.addEventListener("beforeunload", saveCurrentDraft)' in js


def test_script_js_ctrl_cmd_enter_submits_only_when_non_empty():
    """Verify Ctrl/Cmd + Enter shortcut checks that answerInput is non-empty before submitting."""
    js = _get_interview_js_content()

    # Keydown listener on answerInput
    assert 'answerInput.addEventListener("keydown"' in js
    assert '(e.ctrlKey || e.metaKey) && e.key === "Enter"' in js

    # Locate the keydown block
    start_idx = js.find('answerInput.addEventListener("keydown"')
    assert start_idx != -1
    keydown_snippet = js[start_idx : start_idx + 400]

    assert "e.preventDefault()" in keydown_snippet
    assert "requestSubmit()" in keydown_snippet
    assert "trim()" in keydown_snippet
    assert "length > 0" in keydown_snippet, "Ctrl/Cmd+Enter must check length > 0 before submitting"


def test_script_js_drafts_never_sent_to_server_prematurely():
    """Verify saveCurrentDraft writes strictly to browser storage (localStorage) and never makes fetch/POST calls."""
    js = _get_interview_js_content()

    # Extract saveCurrentDraft function body
    save_match = re.search(
        r'function saveCurrentDraft\(\)\s*\{([^}]+(?:\{[^}]+\}[^}]+)*)\}',
        js,
    )
    assert save_match is not None, "saveCurrentDraft function not found"
    save_body = save_match.group(1)

    assert "localStorage.setItem" in save_body
    assert "fetch(" not in save_body, "Draft autosave must never send drafts to the server"
    assert "XMLHttpRequest" not in save_body, "Draft autosave must not use XMLHttpRequest"


def test_script_js_draft_clearing_lifecycle():
    """Verify draft is cleared on submission, session completion, restart, and user logout."""
    js = _get_interview_js_content()

    # Cleared for the active question on form submission
    assert "clearDraftForQuestion" in js

    # Cleared for session on interview completion
    assert "result.completed" in js
    assert "clearAllDraftsForThisSession" in js

    # Cleared on session reset / restart
    assert "handleResetSession" in js

    # Cleared globally on logout
    assert "clearAllInterviewDrafts" in js
    assert 'initInterviewDraftLogoutCleanup' in js


# ==============================================================================
# 3. Server-side Endpoints & Cookie-based Logout Draft Purge
# ==============================================================================

def test_logout_route_sets_drafts_cleared_cookie(test_app_client):
    """Verify /logout sets the interview_drafts_cleared cookie so client-side script sweeps localStorage."""
    response = test_app_client.get("/logout", follow_redirects=False)
    assert response.status_code == 302
    cookie_headers = response.headers.getlist("Set-Cookie")
    assert any("interview_drafts_cleared=1" in h for h in cookie_headers), (
        "Logout response must set interview_drafts_cleared cookie"
    )


def test_api_session_logout_sets_drafts_cleared_cookie(test_app_client):
    """Verify /api/session/logout also sets the interview_drafts_cleared cookie."""
    response = test_app_client.post("/api/session/logout")
    assert response.status_code == 200
    cookie_headers = response.headers.getlist("Set-Cookie")
    assert any("interview_drafts_cleared=1" in h for h in cookie_headers)


def test_interview_view_renders_form_data_attributes(test_app_client):
    """Verify /interview/<analysis_id> view sets data-analysis-id, data-session-id, and data-question-index on chatForm."""
    aid = "test_aid_draft_001"
    questions = [
        {
            "index": 0,
            "type": "Technical",
            "question": "What is the difference between optimistic and pessimistic locking?",
            "is_behavioral": False,
        },
        {
            "index": 1,
            "type": "HR",
            "question": "Describe a difficult conflict you resolved with a teammate.",
            "is_behavioral": True,
        },
    ]

    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "interview_questions": {
            "technical": ["What is the difference between optimistic and pessimistic locking?"],
            "hr": ["Describe a difficult conflict you resolved with a teammate."],
        },
    }
    save_analysis(aid, "resume.pdf", "Microsoft", "Software Engineer", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    response = test_app_client.get(f"/interview/{aid}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert f'data-analysis-id="{aid}"' in html
    assert f'data-session-id="{aid}"' in html
    assert 'data-question-index="0"' in html
    assert 'id="submitShortcutHint"' in html
    assert 'id="draftStatusBadge"' in html
    assert 'id="wordCountBadge"' in html


def test_completed_interview_does_not_render_input_form(test_app_client):
    """Verify completed interviews omit chatForm so drafts are not accepted for finalized sessions."""
    aid = "test_aid_completed_002"
    questions = [
        {
            "index": 0,
            "type": "Technical",
            "question": "Explain virtual DOM in React.",
            "is_behavioral": False,
        }
    ]
    sample_results = {"resume_analysis": {"ats_score": 80}}
    save_analysis(aid, "resume.pdf", "Amazon", "Frontend Engineer", sample_results)
    create_interview_session(interview_id=aid, analysis_id=aid, questions_list=questions)

    # Mark as completed in DB
    from utils.database import get_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE interviews SET completed = 1 WHERE id = ?", (aid,))
        conn.commit()
    finally:
        conn.close()

    session = get_interview_session(aid)
    assert session["completed"] == 1

    response = test_app_client.get(f"/interview/{aid}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Input form should not be rendered
    assert 'id="chatForm"' not in html
    assert 'id="answerInput"' not in html
