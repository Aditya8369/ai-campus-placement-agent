"""
Tests for Live Analysis Progress Steps, Duplicate Submission Blocking, and Retry (#470)
"""

import json
from pathlib import Path
import pytest

from app import app
from utils.async_pipeline import (
    AnalysisTask,
    create_analysis_task,
    get_analysis_task,
    STEP_NAMES,
    ALL_STEPS,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_named_steps_specification():
    """Verify all 6 required named steps are defined correctly in order."""
    expected_steps = [
        "Reading resume",
        "Checking format",
        "Matching job description",
        "Finding skill gaps",
        "Building roadmap",
        "Preparing interview questions",
    ]
    actual_steps = [STEP_NAMES[s] for s in ALL_STEPS]
    assert actual_steps == expected_steps
    assert len(STEP_NAMES) == 6


def test_status_endpoint_running(client):
    """Verify /api/analysis/status/<task_id> returns running step details and completed steps."""
    task = create_analysis_task("Google", "resume.pdf")
    task.emit(
        step="step3",
        agent="JobMatchAgent",
        message="Matching job description requirements for Google...",
        progress=50
    )

    response = client.get(f"/api/analysis/status/{task.task_id}")
    assert response.status_code == 200
    data = response.get_json()

    assert data["success"] is True
    assert data["task_id"] == task.task_id
    assert data["status"] == "in_progress"
    assert data["progress"] == 50
    assert data["current_step"] == "step3"
    assert data["current_step_name"] == "Matching job description"
    assert data["completed_steps"] == ["Reading resume", "Checking format"]
    assert data["failed_step"] is None
    assert data["error_message"] is None


def test_status_endpoint_finished(client):
    """Verify /api/analysis/status/<task_id> returns finished status, 100% progress, and all completed steps."""
    task = create_analysis_task("Microsoft", "candidate.pdf")
    task.emit(step="step1", agent="Resume Parser", message="Reading resume...", progress=15)
    task.emit(step="step2", agent="ResumeAgent", message="Checking format...", progress=30)
    task.emit(
        step="completed",
        agent="CoordinatorAgent",
        message="Complete!",
        progress=100,
        status="completed",
        extra={"analysis_id": "msft-abc", "redirect_url": "/dashboard/msft-abc"}
    )

    response = client.get(f"/api/analysis/status/{task.task_id}")
    assert response.status_code == 200
    data = response.get_json()

    assert data["success"] is True
    assert data["status"] == "completed"
    assert data["progress"] == 100
    assert data["analysis_id"] == "msft-abc"
    assert data["redirect_url"] == "/dashboard/msft-abc"
    assert data["failed_step"] is None
    assert data["completed_steps"] == [
        "Reading resume",
        "Checking format",
        "Matching job description",
        "Finding skill gaps",
        "Building roadmap",
        "Preparing interview questions",
    ]


def test_status_endpoint_failed(client):
    """Verify /api/analysis/status/<task_id> returns failed status with failed step name and error message."""
    task = create_analysis_task("Amazon", "bad_resume.pdf")
    task.emit(step="step1", agent="Resume Parser", message="Reading resume...", progress=15)
    task.emit(
        step="step2",
        agent="ResumeAgent",
        message="Checking format...",
        progress=30
    )
    # Simulate failure on step 2
    task.emit(
        step="step2",
        agent="ResumeAgent",
        message="Error during Checking format: ATS layout parsing failed",
        progress=30,
        status="error",
        extra={
            "failed_step": "Checking format",
            "error_details": "Failed to parse columns"
        }
    )

    response = client.get(f"/api/analysis/status/{task.task_id}")
    assert response.status_code == 200
    data = response.get_json()

    assert data["success"] is True
    assert data["status"] == "error"
    assert data["failed_step"] == "Checking format"
    assert "Checking format" in data["error_message"]
    assert data["completed_steps"] == ["Reading resume"]


def test_sse_stream_carries_named_steps(client):
    """Verify SSE milestones include current_step_name and completed_steps."""
    task = create_analysis_task("Netflix", "resume.pdf")
    task.emit(step="step1", agent="Resume Parser", message="Reading resume...", progress=15)
    task.emit(step="step2", agent="ResumeAgent", message="Checking format...", progress=30)
    task.emit(
        step="completed",
        agent="CoordinatorAgent",
        message="Done",
        progress=100,
        status="completed",
        extra={"analysis_id": "nflx-1", "redirect_url": "/dashboard/nflx-1"}
    )

    response = client.get(f"/api/analysis/stream/{task.task_id}")
    assert response.status_code == 200
    raw_lines = [line for line in response.data.decode("utf-8").split("\n") if line.startswith("data: ")]
    events = [json.loads(line.replace("data: ", "")) for line in raw_lines]

    assert len(events) >= 3
    assert events[0]["current_step_name"] == "Reading resume"
    assert events[0]["completed_steps"] == []
    assert events[1]["current_step_name"] == "Checking format"
    assert events[1]["completed_steps"] == ["Reading resume"]
    assert events[2]["status"] == "completed"
    assert len(events[2]["completed_steps"]) == 6


def test_template_named_steps_markup():
    """Verify templates/index.html includes all 6 named steps, retry button, and accessible announcer."""
    template_path = Path(__file__).resolve().parent.parent / "templates" / "index.html"
    content = template_path.read_text(encoding="utf-8")

    # Step list checks
    assert "Reading resume" in content
    assert "Checking format" in content
    assert "Matching job description" in content
    assert "Finding skill gaps" in content
    assert "Building roadmap" in content
    assert "Preparing interview questions" in content

    # Accessible aria-live status container
    assert 'id="progressLiveAnnouncer"' in content
    assert 'aria-live="polite"' in content
    assert 'role="status"' in content

    # Error alert and retry button
    assert 'id="progressErrorAlert"' in content
    assert 'id="progressErrorStepName"' in content
    assert 'id="btnRetryAnalysis"' in content
    assert 'id="btnCloseProgressError"' in content

    # Form submit button
    assert 'id="btnSubmitAnalysis"' in content


def test_javascript_double_submission_and_retry_wiring():
    """Verify script.js / analysis.js implements isAnalysisRunning guard and retry triggers."""
    js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "modules" / "analysis.js"
    if not js_path.exists():
        js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "script.js"
    content = js_path.read_text(encoding="utf-8")

    assert "isAnalysisRunning" in content
    assert "disableSubmitButton" in content
    assert "enableSubmitButton" in content
    assert "btnRetryAnalysis" in content
    assert "progressErrorStepName" in content
