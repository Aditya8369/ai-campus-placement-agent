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
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Global thread pool for background agent analysis execution
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AgentWorker")

# In-memory registry for active analysis tasks
_active_tasks: Dict[str, "AnalysisTask"] = {}
_registry_lock = threading.Lock()


class AnalysisTask:
    """
    Represents an asynchronous multi-agent analysis background job.
    Maintains milestone history, thread synchronization, and event queue for SSE streaming.
    """

    def __init__(self, task_id: str, company_name: str, resume_filename: str) -> None:
        self.task_id = task_id
        self.company_name = company_name
        self.resume_filename = resume_filename
        self.status = "queued"  # queued, in_progress, completed, error
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
            self.current_step = step
            self.progress = progress
            self.status = status

            if status == "completed":
                self.analysis_id = event_data.get("analysis_id")
                self.redirect_url = event_data.get("redirect_url")
            elif status == "error":
                self.error_message = message

            self.milestones.append(event_data)
            self._condition.notify_all()

        self._event_queue.put(event_data)
        logger.info(f"Task [{self.task_id[:8]}] - [{agent}] {step} ({progress}%): {message}")

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
            if self.status in ("completed", "error"):
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
                "milestones": list(self.milestones),
                "created_at": self.created_at
            }


def create_analysis_task(company_name: str, resume_filename: str) -> AnalysisTask:
    """
    Initializes a new background task and registers it in the global tasks dictionary.
    """
    task_id = str(uuid.uuid4())
    task = AnalysisTask(task_id, company_name, resume_filename)

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
        # Step 1: Document extraction and section standardization
        task.emit(
            step="step1",
            agent="Resume Parser",
            message="Resume document parsed and standardized into canonical sections.",
            progress=15
        )
        time.sleep(0.1)

        # Step 2: Resume Agent analysis
        task.emit(
            step="step2",
            agent="ResumeAgent",
            message="Evaluating resume formatting, bullet points, and ATS compatibility...",
            progress=30
        )

        def on_agent_progress(step: str, agent: str, message: str, progress: int) -> None:
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
            # Fallback if coordinator_agent.analyze does not accept on_progress
            analysis_payload = coordinator_agent.analyze(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company_name
            )

        # Ensure intermediate milestones were emitted if coordinator didn't call callback
        existing_steps = {m["step"] for m in task.get_milestones()}
        if "step3" not in existing_steps:
            task.emit(
                step="step3",
                agent="JobMatchAgent",
                message=f"Benchmarking technical capabilities against {company_name} hiring criteria...",
                progress=50
            )
        if "step4" not in existing_steps:
            task.emit(
                step="step4",
                agent="SkillGapAgent",
                message="Detecting critical skill deficiencies and recommending portfolio projects...",
                progress=65
            )
        if "step5" not in existing_steps:
            task.emit(
                step="step5",
                agent="RoadmapAgent",
                message="Constructing tailored 6-week progressive placement preparation roadmap...",
                progress=80
            )
        if "step6" not in existing_steps:
            task.emit(
                step="step6",
                agent="InterviewAgent",
                message=f"Synthesizing customized Technical, HR, and Behavioral questions for {company_name}...",
                progress=90
            )

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

    except Exception as exc:
        logger.error(f"Async pipeline worker failed for task {task.task_id}: {str(exc)}")
        from utils.gemini import format_ai_error_for_user
        friendly_error = format_ai_error_for_user(exc)
        task.emit(
            step="error",
            agent="CoordinatorAgent",
            message=friendly_error,
            progress=0,
            status="error",
            extra={"error_details": str(exc)}
        )
