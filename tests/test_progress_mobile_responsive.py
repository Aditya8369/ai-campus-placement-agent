"""
Tests for Issue #539:
feat(ui): add progress indicators and a responsive layout for mobile screens

Acceptance Criteria:
- Clicking twice does not send two requests (duplicate submission prevention)
- No horizontal scrolling at 360px width (mobile responsiveness & stacked sections)
- Progress always ends in a success or error state
"""

import json
import os
import pytest
from app import app
from utils.async_pipeline import (
    AnalysisTask,
    create_analysis_task,
    get_analysis_task,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_progress_overlay_markup_and_steps():
    """Verify templates/index.html includes step-by-step progress list, status icons, and retry/dismiss buttons."""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Progress overlay and landmarks
    assert 'id="progressOverlay"' in html
    assert 'role="region"' in html
    assert 'id="progressLiveAnnouncer"' in html
    assert 'aria-live="polite"' in html

    # Progress title, subtitle, and animated bar
    assert 'id="progressTitle"' in html
    assert 'id="progressSubtitle"' in html
    assert 'id="analysisProgressBar"' in html
    assert 'role="progressbar"' in html

    # Progress icons: spinner, success icon, error icon
    assert 'id="progressSpinner"' in html
    assert 'id="progressSuccessIcon"' in html
    assert 'id="progressErrorIcon"' in html

    # Progress steps: reading resume, extracting skills, generating suggestions
    assert 'id="progressStepsList"' in html or 'id="analysisProgressStepsList"' in html
    assert 'id="step1"' in html
    assert "Reading" in html and ("extracting resume" in html or "Reading resume" in html)
    assert 'id="step2"' in html
    assert "ATS formatting" in html or "Checking format" in html
    assert 'id="step3"' in html
    assert "job description match" in html or "Matching job description" in html
    assert 'id="step4"' in html
    assert "Extracting skills" in html or "Finding skill gaps" in html
    assert 'id="step5"' in html
    assert ("Generating suggestions" in html and "roadmap" in html) or "Building roadmap" in html
    assert 'id="step6"' in html
    assert "Compiling final" in html or "Preparing interview questions" in html

    # Error recovery & retry controls
    assert 'id="progressErrorAlert"' in html
    assert 'id="btnCloseProgressError"' in html
    assert 'id="btnRetryProgress"' in html or 'id="btnRetryAnalysis"' in html

    # Form action buttons
    assert 'id="btnSubmitAnalysis"' in html
    assert 'id="btnClearForm"' in html


def test_duplicate_submission_prevention_script():
    """Verify static/js/modules/analysis.js disables buttons, blocks duplicate submits, and manages progress state."""
    js_path = os.path.join("static", "js", "modules", "analysis.js")
    if not os.path.exists(js_path):
        js_path = os.path.join("static", "js", "script.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Double click prevention flag & check
    assert "isSubmitting" in js
    assert "if (isSubmitting)" in js

    # Action button disabling function
    assert "setActionButtonsProcessing" in js
    assert 'btn.setAttribute("disabled", "true")' in js or 'btn.setAttribute("disabled"' in js
    assert "btn.removeAttribute(\"disabled\")" in js

    # State attribution on progress overlay (success / error state guarantee)
    assert 'progressOverlay.setAttribute("data-state", "success")' in js
    assert 'progressOverlay.setAttribute("data-state", "error")' in js
    assert "progressSuccessIcon" in js
    assert "progressErrorIcon" in js

    # Retry and close error event listeners
    assert "btnRetryProgress" in js
    assert "btnCloseProgressError" in js


def test_mobile_360px_responsiveness_rules():
    """Verify static/css/style.css defines responsive layout, stacked sections, and 360px overflow prevention."""
    with open("static/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Prevent horizontal scrolling on mobile viewports
    assert "overflow-x: hidden" in css
    assert "max-width: 100vw" in css or "max-width: 100%" in css

    # Mobile media query (< 576px and <= 400px for 360px smartphones)
    assert "@media (max-width: 575.98px)" in css
    assert "@media (max-width: 400px)" in css

    # Stacked sections & full width action buttons
    assert "flex-direction: column !important" in css
    assert "#btnSubmitAnalysis" in css
    assert "width: 100% !important" in css

    # 360px phone layout: stack col-6 to 100% width
    assert ".col-6" in css
    assert "flex: 0 0 100% !important" in css

    # Progress overlay and panel responsiveness
    assert ".progress-overlay" in css
    assert ".progress-panel" in css
    assert "max-width: 340px !important" in css or "max-width: 320px !important" in css

    # Table and code wrapping
    assert ".table-responsive" in css
    assert "white-space: pre-wrap !important" in css
    assert "word-break: break-word !important" in css

    # Progress step error indicator styling
    assert ".progress-step.error" in css


def test_progress_lifecycle_always_ends_in_terminal_state():
    """Verify asynchronous AnalysisTask always transitions to either 'completed' or 'error'."""
    # Test 1: Successful task lifecycle reaches 'completed'
    success_task = create_analysis_task(company_name="Google", resume_filename="success_cv.pdf")
    assert success_task.status == "queued"
    success_task.emit(step="step1", agent="Parser", message="Extracting text", progress=15)
    assert success_task.status == "in_progress"
    success_task.emit(
        step="completed",
        agent="Coordinator",
        message="Finished",
        progress=100,
        status="completed",
        extra={"redirect_url": "/dashboard/test-1"}
    )
    assert success_task.status == "completed"
    assert success_task.progress == 100

    # Test 2: Failed task lifecycle reaches 'error'
    error_task = create_analysis_task(company_name="Amazon", resume_filename="error_cv.pdf")
    error_task.emit(
        step="error",
        agent="Coordinator",
        message="Model rate limited",
        progress=0,
        status="error"
    )
    assert error_task.status == "error"
    assert error_task.error_message == "Model rate limited"


def test_status_endpoint_returns_terminal_states(client):
    """Verify /api/analysis/status/<task_id> accurately reports completed and error states."""
    # 1. Completed task
    task_done = create_analysis_task(company_name="Microsoft", resume_filename="ms_cv.pdf")
    task_done.emit(
        step="completed",
        agent="Coordinator",
        message="Analysis complete",
        progress=100,
        status="completed",
        extra={"redirect_url": "/dashboard/ms-123"}
    )
    res_done = client.get(f"/api/analysis/status/{task_done.task_id}")
    assert res_done.status_code == 200
    data_done = json.loads(res_done.data.decode("utf-8"))
    assert data_done["status"] == "completed"
    assert data_done["progress"] == 100
    assert data_done["redirect_url"] == "/dashboard/ms-123"

    # 2. Error task
    task_fail = create_analysis_task(company_name="Meta", resume_filename="meta_cv.pdf")
    task_fail.emit(
        step="error",
        agent="Coordinator",
        message="AI request timeout after retries",
        progress=40,
        status="error"
    )
    res_fail = client.get(f"/api/analysis/status/{task_fail.task_id}")
    assert res_fail.status_code == 200
    data_fail = json.loads(res_fail.data.decode("utf-8"))
    assert data_fail["status"] == "error"
    assert "timeout" in data_fail["error_message"].lower()
