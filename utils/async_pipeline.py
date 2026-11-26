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

# Named analysis pipeline steps (#470)
STEP_NAMES: Dict[str, str] = {
    "step1": "Reading resume",
    "step2": "Checking format",
    "step3": "Matching job description",
    "step4": "Finding skill gaps",
    "step5": "Building roadmap",
    "step6": "Preparing interview questions",
}

ALL_STEPS: List[str] = ["step1", "step2", "step3", "step4", "step5", "step6"]


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
        self.current_step_name = STEP_NAMES["step1"]
        self.completed_steps: List[str] = []
        self.failed_step: Optional[str] = None
        self.analysis_id: Optional[str] = None
        self.redirect_url: Optional[str] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.milestones: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._event_queue: queue.Queue = queue.Queue()
        self.is_cancelled = False
        self.completed_sections: Dict[str, Any] = {}

    def emit_section(
        self,
        section_name: str,
        section_data: Any,
        progress: int,
        message: Optional[str] = None
    ) -> None:
        """
        Records a completed section from streaming AI generation and emits SSE event (#764).
        Allows clients to render sections incrementally as they complete.
        """
        with self._lock:
            self.completed_sections[section_name] = section_data
            completed_keys = list(self.completed_sections.keys())

        msg = message or f"Generated {section_name.replace('_', ' ').title()}"
        self.emit(
            step="section_stream",
            agent="CoordinatorAgent",
            message=msg,
            progress=progress,
            status="in_progress",
            extra={
                "event": "section_completed",
                "section": section_name,
                "section_name": section_name,
                "section_data": section_data,
                "data": section_data,
                "completed_sections": completed_keys,
            }
        )

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
            if step in STEP_NAMES:
                self.current_step_name = STEP_NAMES[step]
                step_idx = ALL_STEPS.index(step)
                self.completed_steps = [STEP_NAMES[s] for s in ALL_STEPS[:step_idx]]
            elif step == "completed":
                self.current_step_name = "Completed"
                self.completed_steps = [STEP_NAMES[s] for s in ALL_STEPS]

            self.progress = progress
            self.status = status

            if status == "completed":
                self.analysis_id = event_data.get("analysis_id")
                self.redirect_url = event_data.get("redirect_url")
                self.completed_steps = [STEP_NAMES[s] for s in ALL_STEPS]
            elif status == "error":
                self.failed_step = (extra or {}).get("failed_step") or STEP_NAMES.get(step, self.current_step_name)
                self.error_message = message
            elif status == "cancelled":
                self.error_message = message

            event_data["current_step_name"] = self.current_step_name
            event_data["completed_steps"] = list(self.completed_steps)
            if self.failed_step:
                event_data["failed_step"] = self.failed_step

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
                "current_step_name": self.current_step_name,
                "completed_steps": list(self.completed_steps),
                "failed_step": self.failed_step,
                "analysis_id": self.analysis_id,
                "redirect_url": self.redirect_url,
                "error_message": self.error_message,
                "is_cancelled": self.is_cancelled,
                "completed_sections": list(self.completed_sections.keys()),
                "has_partial_content": bool(self.completed_sections),
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
    student_id: Optional[str] = None,
    format_compatibility: Optional[Dict[str, Any]] = None,
    pdf_metadata_hygiene: Optional[Dict[str, Any]] = None,
    stored_resume_id: Optional[str] = None,
    stored_resume_label: Optional[str] = None
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
        student_id,
        format_compatibility,
        pdf_metadata_hygiene,
        stored_resume_id,
        stored_resume_label
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
    student_id: Optional[str] = None,
    format_compatibility: Optional[Dict[str, Any]] = None,
    pdf_metadata_hygiene: Optional[Dict[str, Any]] = None,
    stored_resume_id: Optional[str] = None,
    stored_resume_label: Optional[str] = None
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
            message="Reading resume text and extracting canonical sections...",
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
            message="Checking format, layout structure, and ATS score...",
            progress=30
        )

        def on_agent_progress(step: str, agent: str, message: str, progress: int) -> None:
            if task.is_cancelled:
                raise AnalysisCancelledException("Analysis cancelled by user")
            task.emit(step=step, agent=agent, message=message, progress=progress)

        # Execute coordinated multi-agent analysis via Gemini with streaming (#764)
        def on_section_complete(sec_name: str, sec_data: Any, progress_pct: int) -> None:
            if task.is_cancelled:
                raise AnalysisCancelledException("Analysis cancelled by user")
            task.emit_section(
                section_name=sec_name,
                section_data=sec_data,
                progress=progress_pct,
                message=f"Generated {sec_name.replace('_', ' ').title()} section"
            )

        try:
            from unittest.mock import Mock
            if isinstance(coordinator_agent, Mock):
                use_stream = "analyze_stream" in coordinator_agent.__dict__
            else:
                use_stream = hasattr(coordinator_agent, "analyze_stream")

            if use_stream:
                analysis_payload = coordinator_agent.analyze_stream(
                    resume_text=resume_text,
                    job_description=job_description,
                    company_name=company_name,
                    on_section=on_section_complete,
                    is_cancelled=lambda: task.is_cancelled,
                    use_fallback_on_failure=True
                )
            else:
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
            # Non-streaming fallback if on_progress or analyze_stream is unsupported
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
                message=f"Matching job description requirements for {company_name}...",
                progress=50
            )
        if "step4" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step4",
                agent="SkillGapAgent",
                message="Finding skill gaps and prioritizing missing proficiencies...",
                progress=65
            )
        if "step5" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step5",
                agent="RoadmapAgent",
                message="Building tailored 6-week progressive placement preparation roadmap...",
                progress=80
            )
        if "step6" not in existing_steps:
            if task.is_cancelled:
                _cleanup_cancelled_analysis(analysis_id)
                return
            task.emit(
                step="step6",
                agent="InterviewAgent",
                message=f"Preparing interview questions and evaluation rubrics for {company_name}...",
                progress=90
            )

        # Final pre-persistence cancellation guard
        if task.is_cancelled:
            logger.info(f"Task {task.task_id} cancelled immediately prior to DB persistence.")
            _cleanup_cancelled_analysis(analysis_id)
            return

        if isinstance(analysis_payload, dict):
            if format_compatibility and "format_compatibility" not in analysis_payload:
                analysis_payload["format_compatibility"] = format_compatibility
            if pdf_metadata_hygiene and "pdf_metadata_hygiene" not in analysis_payload:
                analysis_payload["pdf_metadata_hygiene"] = pdf_metadata_hygiene

        # Persist completed analysis to SQLite database
        try:
            save_analysis_func(
                analysis_id=analysis_id,
                resume_filename=resume_filename,
                company_name=company_name,
                job_description=job_description,
                results_dict=analysis_payload,
                student_id=student_id or "default_student",
                stored_resume_id=stored_resume_id,
                stored_resume_label=stored_resume_label
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
        from utils.gemini import format_ai_error_for_user, scrub_api_key, create_safe_fallback_analysis_payload
        clean_exc = scrub_api_key(str(exc))
        logger.error(f"Async pipeline worker failed for task {task.task_id}: {clean_exc}")
        friendly_error = format_ai_error_for_user(exc)
        current_step_name = task.current_step_name

        # Preserve any content already received and shown to the user (#764)
        has_partial = bool(task.completed_sections)
        redirect_url = f"/dashboard/{analysis_id}" if has_partial else None

        if has_partial:
            try:
                fallback_payload = create_safe_fallback_analysis_payload(company_name=company_name)
                partial_payload = {
                    "resume_analysis": task.completed_sections.get("resume_analysis", fallback_payload["resume_analysis"]),
                    "job_match": task.completed_sections.get("job_match", fallback_payload["job_match"]),
                    "skill_gap": task.completed_sections.get("skill_gap", fallback_payload["skill_gap"]),
                    "learning_roadmap": task.completed_sections.get("learning_roadmap", fallback_payload["learning_roadmap"]),
                    "interview_questions": task.completed_sections.get("interview_questions", fallback_payload["interview_questions"]),
                    "overall_recommendation_summary": task.completed_sections.get(
                        "overall_recommendation_summary", fallback_payload["overall_recommendation_summary"]
                    ),
                    "section_status": {
                        k: ("valid" if k in task.completed_sections else "unavailable")
                        for k in [
                            "resume_analysis",
                            "job_match",
                            "skill_gap",
                            "learning_roadmap",
                            "interview_questions",
                            "overall_recommendation_summary",
                        ]
                    },
                    "extracted_resume_text": resume_text,
                    "stream_error": friendly_error,
                    "is_partial": True,
                }
                save_analysis_func(
                    analysis_id=analysis_id,
                    resume_filename=resume_filename,
                    company_name=company_name,
                    job_description=job_description,
                    results_dict=partial_payload,
                    student_id=student_id or "default_student",
                )
            except Exception as save_err:
                logger.warning(f"Failed to persist partial analysis on stream error: {save_err}")
        else:
            # Produce rule-based basic analysis fallback on AI failure (#849)
            try:
                from utils.basic_analysis_fallback import generate_basic_fallback_analysis
                basic_payload = generate_basic_fallback_analysis(
                    resume_text=resume_text,
                    job_description=job_description,
                    company_name=company_name,
                    error_reason=friendly_error
                )
                basic_payload["extracted_resume_text"] = resume_text
                save_analysis_func(
                    analysis_id=analysis_id,
                    resume_filename=resume_filename,
                    company_name=company_name,
                    job_description=job_description,
                    results_dict=basic_payload,
                    student_id=student_id or "default_student",
                )
                redirect_url = f"/dashboard/{analysis_id}"
            except Exception as basic_err:
                logger.warning(f"Failed to generate basic fallback analysis on async worker failure: {basic_err}")

        task.emit(
            step=task.current_step,
            agent="CoordinatorAgent",
            message=f"Error during {current_step_name}: {friendly_error}",
            progress=task.progress,
            status="error",
            extra={
                "error_details": clean_exc,
                "failed_step": current_step_name,
                "step_name": current_step_name,
                "has_partial_content": has_partial,
                "completed_sections": list(task.completed_sections.keys()),
                "redirect_url": redirect_url,
                "analysis_id": analysis_id if has_partial else None,
            }
        )
    finally:
        if analysis_id:
            try:
                from utils.cleanup import cleanup_temporary_upload
                cleanup_temporary_upload(file_uuid=analysis_id)
            except Exception as clean_err:
                logger.warning(f"Failed to clean up temporary upload for {analysis_id}: {clean_err}")
