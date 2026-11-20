"""
Asynchronous Multi-Agent Pipeline & Real-Time Progress Streaming

Coordinates background execution of multi-agent placement analysis using
ThreadPoolExecutor, tracking incremental agent milestones and emitting real-time
Server-Sent Events (SSE) to connected frontend clients.
"""

import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Global thread pool for background agent analysis execution
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AgentWorker")

# In-memory registry for active analysis tasks
_active_tasks: Dict[str, "AnalysisTask"] = {}
_registry_lock = threading.Lock()


class AnalysisCancelledException(Exception):
    """Raised when an ongoing analysis pipeline task has been cancelled by the user."""
    pass


class AnalysisTask:
    """
    Represents an asynchronous multi-agent analysis background job.
    Maintains milestone history, thread synchronization, and event queue for SSE streaming.
    """

    def __init__(
        self,
        task_id: str,
        company_name: str,
        resume_filename: str,
        student_id: Optional[str] = None
    ) -> None:
        self.task_id = task_id
        self.company_name = company_name
        self.resume_filename = resume_filename
        self.student_id = student_id
        self.status = "queued"  # queued, in_progress, completed, error, cancelled
        self.progress = 0
        self.current_step = "step1"
        self.analysis_id: Optional[str] = None
        self.redirect_url: Optional[str] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.milestones: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._event_queue: queue.Queue = queue.Queue()
        self.is_cancelled = False

    def emit(
        self,
        step: str,
        agent: str,
        message: str,
        progress: int,
        status: str = "in_progress",
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Records a milestone, notifies any SSE stream listeners, and pushes to queue.
        """
        event_data = {
            "task_id": self.task_id,
            "step": step,
            "agent": agent,
            "message": message,
            "progress": progress,
            "status": status,
            "timestamp": time.time(),
        }

        if extra:
            event_data["extra"] = extra
            event_data.update(extra)

        with self._lock:
            # If already cancelled, ignore subsequent progress updates unless it is the cancelled milestone
            if self.is_cancelled and status not in ("cancelled",):
                return

            self.current_step = step
            self.progress = progress
            self.status = status

            if status == "completed":
                self.analysis_id = event_data.get("analysis_id")
                self.redirect_url = event_data.get("redirect_url")
            elif status == "error":
                self.error_message = message
            elif status == "cancelled":
                self.error_message = message

            self.milestones.append(event_data)
            self._condition.notify_all()

        self._event_queue.put(event_data)
        logger.info(f"Task [{self.task_id[:8]}] - [{agent}] {step} ({progress}%): {message}")

    def cancel(self, reason: str = "Analysis cancelled by user.") -> bool:
        """
        Marks task as cancelled and emits a terminal cancellation milestone.
        Returns True if transitioned to cancelled.
        """
        with self._lock:
            if self.status == "completed":
                return False
            if self.status == "cancelled":
                return True
            self.is_cancelled = True
            self.status = "cancelled"
            self.error_message = reason

        self.emit(
            step="cancelled",
            agent="CoordinatorAgent",
            message=reason,
            progress=0,
            status="cancelled",
            extra={"cancelled": True, "analysis_id": self.analysis_id}
        )
        return True

    def get_milestones(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.milestones)

    def get_events_since(self, index: int, timeout: float = 20.0) -> List[Dict[str, Any]]:
        """
        Retrieves all milestones added at or after the given index.
        Blocks for up to timeout seconds if no new events are available.
        """
        with self._lock:
            if index < len(self.milestones):
                return list(self.milestones[index:])
            if self.status in ("completed", "error", "cancelled") or self.is_cancelled:
                return []
            self._condition.wait(timeout=timeout)
            return list(self.milestones[index:])

    def get_next_event(self, timeout: float = 25.0) -> Optional[Dict[str, Any]]:
        """
        Pulls the next event from the internal queue (legacy/polling support).
        """
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "task_id": self.task_id,
                "company_name": self.company_name,
                "resume_filename": self.resume_filename,
                "status": self.status,
                "progress": self.progress,
                "current_step": self.current_step,
                "analysis_id": self.analysis_id,
                "redirect_url": self.redirect_url,
                "error_message": self.error_message,
                "is_cancelled": self.is_cancelled,
                "milestones": list(self.milestones),
                "created_at": self.created_at
            }


def create_analysis_task(
    company_name: str,
    resume_filename: str,
    student_id: Optional[str] = None
) -> AnalysisTask:
    """
    Initializes a new background task and registers it in the global tasks dictionary.
    """
    task_id = str(uuid.uuid4())
    task = AnalysisTask(task_id, company_name, resume_filename, student_id=student_id)

    with _registry_lock:
        _active_tasks[task_id] = task

        # Cleanup old completed tasks if registry grows large (keep last 100)
        if len(_active_tasks) > 100:
            now = time.time()
            expired = [tid for tid, t in _active_tasks.items() if now - t.created_at > 3600]
            for tid in expired:
                _active_tasks.pop(tid, None)

    return task


def get_analysis_task(task_id: str) -> Optional[AnalysisTask]:
    """
    Retrieves an active or completed task by task_id.
    """
    with _registry_lock:
        return _active_tasks.get(task_id)


def _cleanup_cancelled_analysis(analysis_id: Optional[str]) -> None:
    """Removes any temporary upload or partial database/cache record for a cancelled analysis."""
    if not analysis_id:
        return
    try:
        from utils.cleanup import cleanup_temporary_upload
        cleanup_temporary_upload(file_uuid=analysis_id)
    except Exception as e:
        logger.warning(f"Error cleaning up temporary file for cancelled analysis {analysis_id}: {e}")
    try:
        from utils.database import delete_analysis
        delete_analysis(analysis_id)
    except Exception as e:
        logger.warning(f"Error deleting cancelled analysis record {analysis_id}: {e}")


def cancel_analysis_task(task_id: str, student_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Cancels an active or queued background analysis task (#465).
    Stops background execution, terminates event emission, and cleans up
    any partial database or filesystem data.
    """
    task = get_analysis_task(task_id)
    if not task:
        return False, f"Analysis task '{task_id}' not found."

    with task._lock:
        if task.status == "completed":
            return False, "Analysis has already completed and cannot be cancelled."
        if task.status == "cancelled":
            return True, "Analysis task is already cancelled."

    success = task.cancel(reason="Analysis was cancelled by user.")
    if success:
        _cleanup_cancelled_analysis(task.analysis_id)
        return True, "Analysis task cancelled successfully."
    return False, "Could not cancel analysis task."


def start_async_analysis(
    task: AnalysisTask,
    coordinator_agent: Any,
    save_analysis_func: Any,
    resume_text: str,
    job_description: str,
    company_name: str,
    resume_filename: str,
    analysis_id: str,
    student_id: Optional[str] = None
) -> None:
    """
    Dispatches the multi-agent analysis to the background ThreadPoolExecutor.
    Emits real-time SSE progress milestones through each agent's execution phase.
    """
    task.analysis_id = analysis_id
    if student_id:
        task.student_id = student_id

    _executor.submit(
        _run_analysis_pipeline,
        task,
        coordinator_agent,
        save_analysis_func,
        resume_text,
        job_description,
        company_name,
        resume_filename,
        analysis_id,
        student_id
    )


def _run_analysis_pipeline(
    task: AnalysisTask,
    coordinator_agent: Any,
    save_analysis_func: Any,
    resume_text: str,
    job_description: str,
    company_name: str,
    resume_filename: str,
    analysis_id: str,
    student_id: Optional[str] = None
) -> None:
    """
    Worker thread routine running the sequential multi-agent analysis pipeline.
    """
    try:
        # Pre-execution cancellation check
        if task.is_cancelled:
            logger.info(f"Task {task.task_id} aborted before Step 1 due to user cancellation.")
            _cleanup_cancelled_analysis(analysis_id)
            return

        # Step 1: Document extraction and section standardization
        task.emit(
            step="step1",
            agent="Resume Parser",
            message="Resume document parsed and standardized into canonical sections.",
            progress=15
        )
        time.sleep(0.1)

        if task.is_cancelled:
            logger.info(f"Task {task.task_id} aborted before Step 2 due to user cancellation.")
            _cleanup_cancelled_analysis(analysis_id)
            return

        # Step 2: Resume Agent analysis
        task.emit(
            step="step2",
            agent="ResumeAgent",
            message="Evaluating resume formatting, bullet points, and ATS compatibility...",
            progress=30
        )

        def on_agent_progress(step: str, agent: str, message: str, progress: int) -> None:
            if task.is_cancelled:
                raise AnalysisCancelledException("Analysis cancelled by user")
            task.emit(step=step, agent=agent, message=message, progress=progress)

        # Execute coordinated multi-agent analysis via Gemini
        try:
            analysis_payload = coordinator_agent.analyze(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company_name,
                on_progress=on_agent_progress
            )
        except TypeError:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            # Fallback if coordinator_agent.analyze does not accept on_progress
            analysis_payload = coordinator_agent.analyze(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company_name
            )

        # Post-analysis cancellation check: ensure incomplete results are not saved
        if task.is_cancelled:
            logger.info(f"Task {task.task_id} aborted after coordinator call due to cancellation.")
            _cleanup_cancelled_analysis(analysis_id)
            return

        # Ensure intermediate milestones were emitted if coordinator didn't call callback
        existing_steps = {m["step"] for m in task.get_milestones()}
        if "step3" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step3",
                agent="JobMatchAgent",
                message=f"Benchmarking technical capabilities against {company_name} hiring criteria...",
                progress=50
            )
        if "step4" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step4",
                agent="SkillGapAgent",
                message="Detecting critical skill deficiencies and recommending portfolio projects...",
                progress=65
            )
        if "step5" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step5",
                agent="RoadmapAgent",
                message="Constructing tailored 6-week progressive placement preparation roadmap...",
                progress=80
            )
        if "step6" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step6",
                agent="InterviewAgent",
                message=f"Synthesizing customized Technical, HR, and Behavioral questions for {company_name}...",
                progress=90
            )

        # Final pre-persistence cancellation guard
        if task.is_cancelled:
            logger.info(f"Task {task.task_id} cancelled immediately prior to DB persistence.")
            _cleanup_cancelled_analysis(analysis_id)
            return

        # Persist completed analysis to SQLite database
        try:
            save_analysis_func(
                analysis_id=analysis_id,
                resume_filename=resume_filename,
                company_name=company_name,
                job_description=job_description,
                results_dict=analysis_payload,
                student_id=student_id or "default_student"
            )
        except TypeError:
            save_analysis_func(
                analysis_id=analysis_id,
                resume_filename=resume_filename,
                company_name=company_name,
                job_description=job_description,
                results_dict=analysis_payload
            )

        # Cache completed analysis result by input hash (#296)
        try:
            from utils.analysis_cache import compute_analysis_hash, set_cached_analysis
            input_hash = compute_analysis_hash(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company_name
            )
            set_cached_analysis(
                input_hash=input_hash,
                analysis_id=analysis_id,
                student_id=student_id or "default_student"
            )
        except Exception as cache_err:
            logger.warning(f"Failed to record async analysis in cache: {cache_err}")

        redirect_url = f"/dashboard/{analysis_id}"

        # Emit completion milestone with target redirect URL
        task.emit(
            step="completed",
            agent="CoordinatorAgent",
            message="Multi-agent placement analysis complete! Redirecting to dashboard...",
            progress=100,
            status="completed",
            extra={
                "analysis_id": analysis_id,
                "redirect_url": redirect_url,
                "company_name": company_name
            }
        )

    except AnalysisCancelledException:
        logger.info(f"Task {task.task_id} worker terminated cleanly upon user cancellation.")
        _cleanup_cancelled_analysis(analysis_id)
        return
    except Exception as exc:
        if task.is_cancelled:
            logger.info(f"Task {task.task_id} was cancelled; suppressing downstream error: {exc}")
            _cleanup_cancelled_analysis(analysis_id)
            return
        from utils.gemini import format_ai_error_for_user, scrub_api_key
        clean_exc = scrub_api_key(str(exc))
        logger.error(f"Async pipeline worker failed for task {task.task_id}: {clean_exc}")
        friendly_error = format_ai_error_for_user(exc)
        task.emit(
            step="error",
            agent="CoordinatorAgent",
            message=friendly_error,
            progress=0,
            status="error",
            extra={"error_details": clean_exc}
        )
    finally:
        if analysis_id:
            try:
                from utils.cleanup import cleanup_temporary_upload
                cleanup_temporary_upload(file_uuid=analysis_id)
            except Exception as clean_err:
                logger.warning(f"Failed to clean up temporary upload for {analysis_id}: {clean_err}")
