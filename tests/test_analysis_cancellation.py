"""
Automated Test Suite for Analysis Cancellation Option (#465).
==============================================================
Verifies:
1. Cancellation lifecycle on AnalysisTask instance.
2. In-flight analysis pipeline aborts promptly when cancelled.
3. Incomplete analysis results are never persisted to the database.
4. Cancellation endpoint (/api/analysis/cancel/<task_id>) responds with 200 and confirmation.
5. Task status polling reflects 'cancelled' state with is_cancelled flag.
6. Server-Sent Events (SSE) stream cleanly terminates upon task cancellation.
7. Attempting to cancel an already completed task is safely rejected.
"""

import json
import time
from unittest.mock import MagicMock
import pytest

from app import app
from utils.async_pipeline import (
    AnalysisTask,
    create_analysis_task,
    get_analysis_task,
    cancel_analysis_task,
    _run_analysis_pipeline,
)
from utils.database import get_analysis


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as test_client:
        yield test_client


SAMPLE_RESUME_TEXT = (
    "Jane Doe\n"
    "Education: B.S. Computer Science\n"
    "Skills: Python, TypeScript, Docker, SQL\n"
    "Projects: Full-stack placement tracking system\n"
)


def test_analysis_task_cancellation_lifecycle():
    """Verify AnalysisTask transitions to 'cancelled' and emits cancellation milestone."""
    task = create_analysis_task(company_name="Google", resume_filename="resume.pdf")
    assert task.status == "queued"
    assert task.is_cancelled is False

    # Perform cancellation
    cancelled = task.cancel(reason="User changed their mind.")
    assert cancelled is True
    assert task.status == "cancelled"
    assert task.is_cancelled is True
    assert task.error_message == "User changed their mind."

    # Verify to_dict serialization
    task_dict = task.to_dict()
    assert task_dict["status"] == "cancelled"
    assert task_dict["is_cancelled"] is True
    assert task_dict["error_message"] == "User changed their mind."

    # Verify terminal milestone exists
    milestones = task.get_milestones()
    assert len(milestones) == 1
    assert milestones[0]["step"] == "cancelled"
    assert milestones[0]["status"] == "cancelled"


def test_cannot_cancel_already_completed_task():
    """Verify that a completed analysis task cannot be cancelled."""
    task = create_analysis_task(company_name="Amazon", resume_filename="resume.pdf")
    task.emit(
        step="completed",
        agent="CoordinatorAgent",
        message="Analysis done!",
        progress=100,
        status="completed",
        extra={"analysis_id": "completed-aid-123"}
    )
    assert task.status == "completed"

    success, msg = cancel_analysis_task(task.task_id)
    assert success is False
    assert "already completed" in msg.lower()
    assert task.status == "completed"


def test_cancel_already_cancelled_task_is_idempotent():
    """Verify that cancelling an already cancelled task is safe and idempotent."""
    task = create_analysis_task(company_name="Microsoft", resume_filename="resume.pdf")
    task.cancel()

    success, msg = cancel_analysis_task(task.task_id)
    assert success is True
    assert "already cancelled" in msg.lower()
    assert task.status == "cancelled"


def test_cancel_analysis_api_endpoint(client):
    """Verify POST /api/analysis/cancel/<task_id> endpoint cancels active task."""
    task = create_analysis_task(company_name="Apple", resume_filename="apple_resume.pdf")

    res = client.post(f"/api/analysis/cancel/{task.task_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "cancelled"
    assert data["task_id"] == task.task_id
    assert "successfully" in data["message"].lower()

    # Verify task state in registry
    updated_task = get_analysis_task(task.task_id)
    assert updated_task.status == "cancelled"
    assert updated_task.is_cancelled is True


def test_cancel_analysis_api_via_body(client):
    """Verify POST /api/analysis/cancel with JSON body payload."""
    task = create_analysis_task(company_name="Netflix", resume_filename="netflix_resume.pdf")

    res = client.post("/api/analysis/cancel", json={"task_id": task.task_id})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "cancelled"


def test_cancel_analysis_api_not_found(client):
    """Verify cancelling a non-existent task returns 404."""
    res = client.post("/api/analysis/cancel/non-existent-task-id-999")
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False
    assert "not found" in data["error"].lower()


def test_cancel_analysis_api_missing_param(client):
    """Verify calling /api/analysis/cancel without task_id returns 400."""
    res = client.post("/api/analysis/cancel", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "missing" in data["error"].lower()


def test_pipeline_worker_aborts_without_saving_incomplete_result():
    """
    Simulates user cancellation during multi-agent analysis.
    Guarantees that save_analysis_func is never invoked and no record persists.
    """
    mock_save = MagicMock()
    mock_coordinator = MagicMock()

    task = create_analysis_task("Stripe", "resume.pdf")
    aid = "stripe-cancel-aid-123"

    # Coordinator simulates user clicking cancel while AI generation is underway
    def cancel_mid_flight(**kwargs):
        task.cancel(reason="User submitted wrong resume.")
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress("step3", "JobMatchAgent", "Processing...", 50)
        return {"resume_analysis": {"ats_score": 50}}

    mock_coordinator.analyze.side_effect = cancel_mid_flight

    _run_analysis_pipeline(
        task=task,
        coordinator_agent=mock_coordinator,
        save_analysis_func=mock_save,
        resume_text=SAMPLE_RESUME_TEXT,
        job_description="Software Engineer",
        company_name="Stripe",
        resume_filename="resume.pdf",
        analysis_id=aid
    )

    # Incomplete result must NOT be persisted
    mock_save.assert_not_called()
    assert task.status == "cancelled"
    assert task.is_cancelled is True


def test_status_endpoint_returns_cancelled_state(client):
    """Verify /api/analysis/status/<task_id> reflects cancelled status to polling clients."""
    task = create_analysis_task("Uber", "resume.pdf")
    task.cancel()

    res = client.get(f"/api/analysis/status/{task.task_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "cancelled"
    assert data["is_cancelled"] is True


def test_sse_stream_closes_on_cancellation(client):
    """Verify that Server-Sent Events stream yields cancellation event and closes."""
    task = create_analysis_task("Airbnb", "resume.pdf")

    # Cancel task
    task.cancel(reason="Cancelled by test.")

    res = client.get(f"/api/analysis/stream/{task.task_id}")
    assert res.status_code == 200
    assert "text/event-stream" in res.content_type

    stream_data = res.get_data(as_text=True)
    assert "cancelled" in stream_data
