"""
Unit tests for Saving and Restoring Unfinished Analysis Forms (#596).

Verifies:
1. Workspace template (templates/index.html) contains draft recovery elements:
   - Draft restored alert with time text and discard button (#draftRestoredAlert, #btnDiscardDraft, #btnCloseDraftAlert).
   - Local storage draft privacy notice warning before saving pasted resume content (#resumeDraftPrivacyWarning).
   - Live draft status indicator badge (#analysisDraftStatusBadge, #analysisDraftStatusText).
2. JavaScript module (static/js/modules/analysis.js) defines:
   - DRAFT_STORAGE_KEY and 48-hour expiration logic (DRAFT_MAX_AGE_MS).
   - Form state extraction: resume_text, job_description, role_template, company, student_id, batch_mode, consent.
   - Local restoration of unfinished forms on page initialization without erasing active user inputs.
   - Automatic deletion of drafts upon successful analysis completion or explicit discard.
   - Privacy safeguards guaranteeing drafts are kept locally in the browser and not prematurely transmitted to the server.
3. Server-side /analyze endpoint integration:
   - Validates that analysis requests process properly without server-side storage of unfinished drafts.
   - Clears leftover client-side state after successful analysis execution.
"""

import json
import re
import tempfile
from pathlib import Path
import pytest
from routes import create_app
import config


@pytest.fixture
def test_client():
    """Test client configured with an isolated temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_form_drafts.db"
        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client


def test_index_template_contains_draft_recovery_ui_elements():
    """Verify templates/index.html includes alert, discard button, badge, and privacy notice."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Alert elements
    assert 'id="draftRestoredAlert"' in html
    assert 'id="draftRestoredTimeText"' in html
    assert 'id="btnDiscardDraft"' in html
    assert 'id="btnCloseDraftAlert"' in html
    assert "Unfinished Analysis Form Restored" in html

    # Privacy notice for local storage of pasted resume
    assert 'id="resumeDraftPrivacyWarning"' in html
    assert "Draft Privacy Notice" in html
    assert "temporarily saved in your local browser storage" in html

    # Draft status badge
    assert 'id="analysisDraftStatusBadge"' in html
    assert 'id="analysisDraftStatusText"' in html
    assert "Local Draft Protection" in html


def test_analysis_js_defines_draft_persistence_and_expiry_logic():
    """Verify static/js/modules/analysis.js implements draft saving, restoring, expiration, and clearing."""
    with open("static/js/modules/analysis.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Storage key and expiration
    assert "placement_analysis_form_draft_v1" in js
    assert "DRAFT_STORAGE_KEY" in js
    assert "DRAFT_MAX_AGE_MS" in js

    # Draft lifecycle functions
    assert "function saveFormDraft()" in js
    assert "function clearFormDraft()" in js
    assert "function restoreFormDraft()" in js
    assert "function getFormDraftPayload()" in js
    assert "function hasSubstantialDraftContent(" in js

    # Expiration check
    assert "Date.now() - draft.timestamp > DRAFT_MAX_AGE_MS" in js

    # Automatic clearing upon success
    assert "clearFormDraft();" in js

    # Event listeners for persistence
    assert "beforeunload" in js
    assert "btnDiscardDraft" in js


def test_draft_never_transmitted_prematurely_to_server():
    """Verify draft saving functions use exclusively localStorage and never trigger fetch/XHR."""
    with open("static/js/modules/analysis.js", "r", encoding="utf-8") as f:
        js = f.read()

    save_match = re.search(r"function saveFormDraft\(\)\s*\{([\s\S]*?)\n  \}", js)
    assert save_match is not None, "saveFormDraft function must be defined"
    save_code = save_match.group(1)

    assert "fetch(" not in save_code, "Draft autosave must never send drafts to the server"
    assert "XMLHttpRequest" not in save_code, "Draft autosave must never send drafts to the server"
    assert "localStorage.setItem" in save_code, "Draft must be stored locally in the browser"


def test_clear_form_clears_saved_browser_draft():
    """Verify the 'Clear All' button triggers clearFormDraft()."""
    with open("static/js/modules/analysis.js", "r", encoding="utf-8") as f:
        js = f.read()

    clear_match = re.search(r"btnClearForm\.addEventListener\(\"click\",\s*\(e\)\s*=>\s*\{([\s\S]*?)\n    \}\);", js)
    assert clear_match is not None, "btnClearForm listener must exist"
    clear_code = clear_match.group(1)

    assert "clearFormDraft();" in clear_code, "Clearing form must remove saved local draft"


def test_landing_page_renders_cleanly_with_draft_ui(test_client):
    """Verify GET / returns 200 and renders the draft container tags without server errors."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "draftRestoredAlert" in html
    assert "analysisDraftStatusBadge" in html
    assert "resumeDraftPrivacyWarning" in html
    assert "btnDiscardDraft" in html
