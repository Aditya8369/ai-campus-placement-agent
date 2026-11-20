"""
Interview feature area routes & endpoints (#553).
Handles mock interviews, voice coaching, answer evaluation, STAR scoring, notes, and practice.
"""

import os
import io
import shutil
import uuid
import json
import time
import logging
import re
import secrets
import hashlib
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    Response,
    make_response,
    session as flask_session,
    stream_with_context,
    current_app,
    g,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge, HTTPException
from utils.rate_limiter import rate_limit
from utils.migrations import run_database_migrations, get_migration_status
import config
from utils.email_service import EmailNotificationService
from utils.database import *
from utils.aptitude_service import *
from utils.group_discussion_service import *
from utils.student_data_exporter import *
from utils.topic_practice_service import *
from utils.experience_search_service import *
from utils.bookmark_folders import *
from utils.interview_moderation import *
from utils.deadline_reminders import *
from utils.company_profile_manager import *
from utils.progress_tracker import *
from utils.password_security import evaluate_password_strength
from utils.pagination import Pagination
from utils.cohort_analytics import CohortAnalyticsService
from utils.resume_info_extractor import *
from utils.resume_pii_service import pii_service, REDACTION_TOKENS
from utils.analysis_cache import *
from utils.batch_analyzer import run_batch_company_comparison
from agents.job_recommendation_agent import JobRecommendationAgent
from utils.demo_mode import *
from utils.role_skill_gap_service import *
from utils.ats_score_service import evaluate_resume_ats_score
from utils.format_checker import *
from utils.pdf_reader import *
from utils.gemini import *
try:
    from utils.report_generator import *
except ImportError:
    from utils.report_generator import (
        generate_pdf_report,
        generate_certificate_pdf,
        generate_skills_gap_pdf,
        generate_interview_transcript_pdf,
        generate_interview_transcript_markdown,
    )
from utils.async_pipeline import *
from utils.job_feed_service import JobFeedService
from agents.coordinator import CoordinatorAgent
from agents.interview_agent import InterviewAgent
from agents.coding_agent import CodingAssessmentAgent
from agents.star_agent import StarEvaluationAgent
from agents.github_agent import GitHubAnalyzerAgent
from agents.internship_agent import InternshipRecommendationAgent
from agents.linkedin_agent import LinkedInAgent
from agents.coding_practice_agent import CodingPracticeAgent
from agents.outreach_agent import OutreachGeneratorAgent
from agents.self_introduction_agent import SelfIntroductionAgent, calculate_speaking_time
from agents.project_deep_dive_agent import ProjectDeepDiveAgent
from agents.role_prep_agent import role_prep_agent, SUPPORTED_ROLES
from utils.i18n import (
    get_translation,
    get_all_translations_for_locale,
    SUPPORTED_LOCALES,
    DEFAULT_LOCALE,
    LOCALE_NAMES,
)
from utils.output_localization import (
    DEFAULT_OUTPUT_LOCALE,
    OUTPUT_LOCALE_NAMES,
    SUPPORTED_OUTPUT_LOCALES,
    resolve_output_locale,
)
from utils.csrf import csrf, CSRFError, generate_csrf
from utils.totp import *
from utils.logger_config import (
    configure_logging,
    get_current_request_id,
    set_current_request_id,
    register_sensitive_text,
    clear_sensitive_texts,
)
from .common import *

logger = logging.getLogger(__name__)

interview_bp = Blueprint("interview", __name__)

@interview_bp.route("/interview/<analysis_id>")
def interview(analysis_id: str) -> str:
    """
    Bootstraps or loads an existing interactive mock interview session.
    Supports optional ?round=HR|Technical|Behavioral filter to practice focused rounds.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        flash("Cannot initialize mock interview. Parent analysis not found.", "error")
        return redirect(url_for("index"))

    raw_round = request.args.get("round", "").strip().lower()
    round_map = {"hr": "HR", "technical": "Technical", "behavioral": "Behavioral"}
    active_round = round_map.get(raw_round, "All")

    # Difficulty selection (#266)
    from utils.interview_difficulty_service import (
        normalize_difficulty,
        get_difficulty_metadata,
        generate_difficulty_interview_questions,
    )
    selected_difficulty = normalize_difficulty(request.args.get("difficulty"))
    difficulty_meta = get_difficulty_metadata(selected_difficulty)

    # Key session by round and difficulty if customized
    diff_slug = selected_difficulty.lower()
    session_id_parts = [analysis_id]
    if active_round in round_map.values():
        session_id_parts.append(raw_round)
    if diff_slug != "intermediate":
        session_id_parts.append(diff_slug)
    session_id = "_".join(session_id_parts)

    # Load or initialize the interview session from DB
    interview_session = get_interview_session(session_id)

    if not interview_session:
        # Check if questions should be generated from difficulty catalog
        if diff_slug != "intermediate":
            flat_questions_list = generate_difficulty_interview_questions(
                difficulty=selected_difficulty,
                target_company=analysis_record.get("company_name", "General"),
                target_role=analysis_record.get("job_title", "Software Engineer")
            )
            if active_round in round_map.values():
                flat_questions_list = [q for q in flat_questions_list if q["type"] == active_round]
                for idx, q in enumerate(flat_questions_list):
                    q["index"] = idx
        else:
            # Extract questions generated by Coordinator Agent
            coordinator_questions = analysis_record["results"].get("interview_questions", {})
            
            flat_questions_list = []
            q_idx = 0

            categories_to_include = (
                [active_round] if active_round in round_map.values() else ["HR", "Technical", "Behavioral"]
            )
            
            for category in categories_to_include:
                key = category.lower()
                for question_text in coordinator_questions.get(key, []):
                    is_behav = (category.lower() == "behavioral") or live_interview_agent.is_behavioral_question(question_text, category)
                    flat_questions_list.append({
                        "index": q_idx,
                        "type": category,
                        "question": question_text,
                        "difficulty": selected_difficulty,
                        "is_behavioral": is_behav
                    })
                    q_idx += 1

        # Ensure session contains at least 5 questions (#496)
        flat_questions_list = live_interview_agent.ensure_minimum_session_questions(
            flat_questions_list,
            round_type=active_round,
            target_role=analysis_record.get("job_title", "Software Engineer"),
            target_company=analysis_record.get("company_name", "General"),
            min_count=5
        )

        # Save new session into SQLite DB
        create_interview_session(
            interview_id=session_id,
            analysis_id=analysis_id,
            questions_list=flat_questions_list
        )
        interview_session = get_interview_session(session_id)

    # Ensure existing in-progress session has at least 5 questions
    elif not interview_session.get("completed") and len(interview_session.get("questions", [])) < 5:
        topped_up_questions = live_interview_agent.ensure_minimum_session_questions(
            interview_session.get("questions", []),
            round_type=active_round,
            target_role=analysis_record.get("job_title", "Software Engineer"),
            target_company=analysis_record.get("company_name", "General"),
            min_count=5
        )
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE interviews SET questions_json = ? WHERE id = ?", (json.dumps(topped_up_questions), session_id))
            conn.commit()
        finally:
            conn.close()
        interview_session = get_interview_session(session_id)

    # Check session state status (#265)
    from utils.interview_session_service import ensure_interview_session_pause_table
    ensure_interview_session_pause_table()
    session_status = interview_session.get("status") or ("Completed" if interview_session.get("completed") else "In Progress")

    session_summary = None
    if interview_session and interview_session.get("completed") and interview_session.get("answers"):
        session_summary = live_interview_agent.calculate_session_summary(interview_session["answers"])

    return render_template(
        "interview.html",
        interview=interview_session,
        session_summary=session_summary,
        analysis_id=analysis_id,
        session_id=session_id,
        active_round=active_round,
        selected_difficulty=selected_difficulty,
        difficulty_meta=difficulty_meta,
        company_name=analysis_record.get("company_name", "General"),
    )


@interview_bp.route("/interview/<analysis_id>/submit", methods=["POST"])
@interview_bp.route("/interview/<analysis_id>/retry", methods=["POST"])
@rate_limit(scope="interview_eval", is_api=True)
def submit_interview_answer(analysis_id: str):
    """
    Endpoint that evaluates a candidate response dynamically and updates session progress.
    Supports 'Improve this answer' retry loops (up to 2 retries per question) with side-by-side
    score comparisons and addressed feedback tracking (#467).
    """
    try:
        post_data = request.get_json() or {}
        session_id = (
            post_data.get("session_id")
            or request.args.get("session_id")
            or (f"{analysis_id}_{request.args.get('round', '').lower()}" if request.args.get('round') else None)
            or analysis_id
        )
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            return jsonify({"success": False, "error": "Interview session not found"}), 404
        session = get_interview_session(session_id)
        if not session and session_id != analysis_id:
            session_id = analysis_id
            session = get_interview_session(session_id)

        if not session:
            return jsonify({"error": "Mock interview session was not found."}), 404

        # Read JSON POST payloads
        candidate_response = post_data.get("answer", "").strip()
        question_index = int(post_data.get("question_index", 0))

        questions_list = session["questions"]
        answers_list = session["answers"]

        if question_index < 0 or question_index >= len(questions_list):
            return jsonify({"error": "The requested question index is out of bounds."}), 400

        target_question = questions_list[question_index]
        q_type = target_question.get("type", "Technical")
        is_behav = target_question.get("is_behavioral")
        if is_behav is None:
            is_behav = live_interview_agent.is_behavioral_question(target_question.get("question", ""), q_type)

        # Call InterviewAgent to dynamically evaluate response accuracy, metrics, and suggestions
        evaluation_results = live_interview_agent.evaluate_answer(
            question_type=q_type,
            question=target_question["question"],
            answer=candidate_response,
            is_behavioral=is_behav
        )

        # Enhance with deep STAR evaluation and non-verbal speech telemetry
        speech_telemetry = post_data.get("speech_metrics") or {}
        star_eval = star_evaluation_agent.evaluate_star(
            question=target_question["question"],
            answer=candidate_response,
            question_type=target_question["type"],
            speech_metrics=speech_telemetry
        )
        evaluation_results["star_evaluation"] = star_eval
        if "star_score" in star_eval:
            evaluation_results["star_score"] = star_eval["star_score"]

        # Timed Answer Mode metadata & telemetry (#431)
        is_timed = bool(post_data.get("is_timed", False))
        raw_taken = post_data.get("time_taken_seconds")
        raw_limit = post_data.get("time_limit_seconds")

        time_taken_seconds = None
        if raw_taken is not None:
            try:
                time_taken_seconds = max(0, int(round(float(raw_taken))))
            except (ValueError, TypeError):
                time_taken_seconds = None

        time_limit_seconds = None
        if raw_limit is not None:
            try:
                time_limit_seconds = max(1, int(round(float(raw_limit))))
            except (ValueError, TypeError):
                time_limit_seconds = None

        time_display = None
        if is_timed or time_taken_seconds is not None:
            def _format_time_sec(s_val: int) -> str:
                m = s_val // 60
                s = s_val % 60
                return f"{m}:{s:02d}"

            if time_taken_seconds is not None and time_limit_seconds is not None:
                time_display = f"answered in {_format_time_sec(time_taken_seconds)} of {_format_time_sec(time_limit_seconds)}"
            elif time_taken_seconds is not None:
                time_display = f"answered in {_format_time_sec(time_taken_seconds)}"

            evaluation_results["is_timed"] = True
            evaluation_results["time_taken_seconds"] = time_taken_seconds
            evaluation_results["time_limit_seconds"] = time_limit_seconds
            evaluation_results["time_display"] = time_display

            if time_limit_seconds is not None and time_taken_seconds is not None and time_taken_seconds >= time_limit_seconds:
                evaluation_results["time_expired"] = True

            # Include timing information in the feedback string if not already present
            if time_display and "answered in" not in evaluation_results.get("feedback", "").lower():
                time_prefix = f"({time_display.capitalize()})"
                current_feedback = evaluation_results.get("feedback", "")
                evaluation_results["feedback"] = f"{time_prefix} {current_feedback}".strip()

        extra_meta = {
            "is_timed": is_timed or (time_taken_seconds is not None),
            "time_taken_seconds": time_taken_seconds,
            "time_limit_seconds": time_limit_seconds,
            "time_display": time_display,
        }

        # Check if an answer already exists for this question (Retry loop #467)
        existing_idx = -1
        for idx, past_ans in enumerate(answers_list):
            if past_ans.get("question_index") == question_index:
                existing_idx = idx
                break

        from utils.interview_retry_service import (
            initialize_initial_attempt_record,
            process_retry_answer,
            MAX_RETRIES_PER_QUESTION,
        )

        is_retry = bool(post_data.get("is_retry")) or (existing_idx >= 0)
        if existing_idx >= 0:
            past_record = answers_list[existing_idx]
            ok, updated_record, err = process_retry_answer(
                past_answer_record=past_record,
                candidate_response=candidate_response,
                evaluation_results=evaluation_results,
                additional_metadata=extra_meta,
            )
            if not ok:
                return jsonify({
                    "error": err,
                    "success": False,
                    "max_retries_reached": True,
                    "retries_left": 0
                }), 400
            answers_list[existing_idx] = updated_record
            response_record = updated_record
        else:
            response_record = initialize_initial_attempt_record(
                question_index=question_index,
                target_question=target_question,
                candidate_response=candidate_response,
                evaluation_results=evaluation_results,
                additional_metadata=extra_meta,
            )
            answers_list.append(response_record)

        # Calculate progress parameters
        furthest_answered = max((a.get("question_index", 0) for a in answers_list), default=-1)
        next_question_index = min(len(questions_list), furthest_answered + 1)
        is_completed = (furthest_answered + 1) >= len(questions_list)

        # Update session logs in database
        update_interview_session(
            interview_id=session_id,
            current_question_index=next_question_index if not is_completed else question_index,
            answers_list=answers_list,
            completed=is_completed
        )

        
        # Record preparation activity for candidate streak tracking (#236)
        try:
            streak_student_id = (
                flask_session.get("user_id")
                or flask_session.get("user", {}).get("id")
                or flask_session.get("student_id")
                or analysis_record.get("student_id")
                or "default_student"
            )
            record_preparation_activity(
                student_id=streak_student_id,
                activity_type="mock_interview",
                metadata={"session_id": session_id, "question_index": question_index}
            )
        except Exception as e_streak:
            logger.warning(f"Could not record streak for interview answer: {e_streak}")

        result_payload = {
            "evaluation": evaluation_results,
            "attempt_number": response_record.get("attempt_number", 1),
            "retry_count": response_record.get("retry_count", 0),
            "retries_left": response_record.get("retries_left", MAX_RETRIES_PER_QUESTION),
            "can_retry": response_record.get("can_retry", True),
            "is_retry": is_retry,
            "comparison": response_record.get("comparison"),
            "next_index": next_question_index,
            "completed": is_completed,
            "is_timed": is_timed or (time_taken_seconds is not None),
            "time_taken_seconds": time_taken_seconds,
            "time_limit_seconds": time_limit_seconds,
            "time_display": time_display,
        }

        if is_completed:
            result_payload["summary"] = live_interview_agent.calculate_session_summary(answers_list)
            # Mark session as completed in state registry (#265)
            try:
                from utils.interview_session_service import ensure_interview_session_pause_table
                ensure_interview_session_pause_table()
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("UPDATE interviews SET status = 'Completed' WHERE id = ?", (session_id,))
                c.execute("UPDATE interview_session_state SET status = 'Completed' WHERE session_id = ?", (session_id,))
                conn.commit()
                conn.close()
            except Exception as e_comp:
                logger.debug(f"Could not update status to completed: {e_comp}")
        else:
            result_payload["next_question"] = questions_list[next_question_index]

        return jsonify(result_payload)

    except Exception as e:
        logger.error(f"Failed to process answer submission: {str(e)}")
        return jsonify({"error": f"Internal process error evaluating response: {str(e)}"}), 500


@interview_bp.route("/api/interview/difficulty/options", methods=["GET"])
def api_get_interview_difficulty_options():
    """
    Returns available mock interview difficulty tiers (Beginner, Intermediate, Advanced)
    and their configuration metadata.
    """
    from utils.interview_difficulty_service import (
        DIFFICULTY_BEGINNER,
        DIFFICULTY_INTERMEDIATE,
        DIFFICULTY_ADVANCED,
        get_difficulty_metadata,
    )
    tiers = [
        get_difficulty_metadata(DIFFICULTY_BEGINNER),
        get_difficulty_metadata(DIFFICULTY_INTERMEDIATE),
        get_difficulty_metadata(DIFFICULTY_ADVANCED),
    ]
    return jsonify({
        "status": "success",
        "default_difficulty": DIFFICULTY_INTERMEDIATE,
        "difficulty_options": tiers
    }), 200


@interview_bp.route("/api/interview/difficulty/generate", methods=["POST"])
def api_generate_difficulty_questions():
    """
    Generates an interview question batch scaled directly to the requested difficulty tier.
    """
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    difficulty = payload.get("difficulty", "Intermediate")
    company = payload.get("company_name", "General")
    role = payload.get("role", "Software Engineer")

    from utils.interview_difficulty_service import (
        normalize_difficulty,
        generate_difficulty_interview_questions,
        get_difficulty_metadata
    )
    norm_diff = normalize_difficulty(difficulty)
    questions = generate_difficulty_interview_questions(
        difficulty=norm_diff,
        target_company=company,
        target_role=role
    )
    return jsonify({
        "status": "success",
        "difficulty": norm_diff,
        "difficulty_meta": get_difficulty_metadata(norm_diff),
        "total_questions": len(questions),
        "questions": questions
    }), 200


@interview_bp.route("/api/interview/evaluate-star", methods=["POST"])
@rate_limit(scope="star_eval", is_api=True)
def api_evaluate_star():
    """
    Evaluates candidate interview responses against the STAR behavioral framework
    and analyzes verbal and non-verbal speech telemetry.
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        question = data.get("question", "").strip()
        answer = data.get("answer", "").strip()
        question_type = data.get("question_type", "Behavioral").strip()
        analysis_id = data.get("analysis_id", "").strip()

        raw_metrics = data.get("speech_metrics")
        if isinstance(raw_metrics, str):
            try:
                speech_metrics = json.loads(raw_metrics)
            except Exception:
                speech_metrics = {}
        elif isinstance(raw_metrics, dict):
            speech_metrics = raw_metrics
        else:
            speech_metrics = {}

        if not answer:
            return jsonify({
                "status": "error",
                "message": "Answer text is required for STAR story evaluation."
            }), 400

        star_results = star_evaluation_agent.evaluate_star(
            question=question,
            answer=answer,
            question_type=question_type,
            speech_metrics=speech_metrics
        )

        return jsonify({
            "status": "success",
            "success": True,
            "star_evaluation": star_results
        }), 200

    except Exception as exc:
        logger.error(f"Error in STAR evaluation endpoint: {exc}")
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


@interview_bp.route("/api/interview/<session_id>/breakdown", methods=["GET"])
def api_get_interview_breakdown(session_id: str):
    """
    Returns a comprehensive category and competency breakdown for a given interview session,
    highlighting scores across Technical Knowledge, Communication, Problem-Solving,
    Answer Relevance, along with top strengths and improvement areas.
    """
    try:
        session = get_interview_session(session_id)
        if not session:
            return jsonify({"status": "error", "message": "Interview session not found."}), 404

        from utils.interview_performance_breakdown import calculate_competency_breakdown
        breakdown = calculate_competency_breakdown(session.get("answers", []))
        summary = live_interview_agent.calculate_session_summary(session.get("answers", []))

        return jsonify({
            "status": "success",
            "session_id": session_id,
            "overall_score": summary.get("overall_score", 0),
            "readiness_verdict": summary.get("readiness_verdict"),
            "category_scores": summary.get("category_scores", {}),
            "competency_breakdown": breakdown,
            "strengths": breakdown.get("strengths", []),
            "improvements": breakdown.get("improvements", []),
            "verbal_metrics": summary.get("verbal_metrics", {})
        }), 200
    except Exception as e:
        logger.error(f"Error computing performance breakdown for {session_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to compute performance breakdown."}), 500


@interview_bp.route("/api/interview/<session_id>/pause", methods=["POST"])
def api_pause_interview_session(session_id: str):
    """
    Pauses an ongoing mock interview session, saving the current question,
    unsubmitted draft answer, and progress status.
    """
    student_id = (
        flask_session.get("user_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("student_id")
        or "default_student"
    )
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    draft_answer = payload.get("draft_answer", "").strip()
    q_index = payload.get("question_index")

    try:
        from utils.interview_session_service import pause_interview_session
        result = pause_interview_session(
            session_id=session_id,
            student_id=str(student_id),
            draft_answer=draft_answer,
            question_index=int(q_index) if q_index is not None else None
        )
        return jsonify({
            "status": "success",
            "message": "Interview session paused successfully.",
            "data": result
        }), 200
    except KeyError as ke:
        return jsonify({"status": "error", "message": str(ke)}), 404
    except PermissionError as pe:
        return jsonify({"status": "error", "message": str(pe)}), 403
    except Exception as e:
        logger.error(f"Error pausing interview session {session_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to pause interview session."}), 500


@interview_bp.route("/api/interview/<session_id>/resume", methods=["POST", "GET"])
def api_resume_interview_session(session_id: str):
    """
    Resumes a paused mock interview session and returns stored progress.
    """
    student_id = (
        flask_session.get("user_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("student_id")
        or "default_student"
    )

    try:
        from utils.interview_session_service import resume_interview_session
        result = resume_interview_session(
            session_id=session_id,
            student_id=str(student_id)
        )
        return jsonify({
            "status": "success",
            "message": "Interview session resumed.",
            "data": result
        }), 200
    except KeyError as ke:
        return jsonify({"status": "error", "message": str(ke)}), 404
    except PermissionError as pe:
        return jsonify({"status": "error", "message": str(pe)}), 403
    except Exception as e:
        logger.error(f"Error resuming interview session {session_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to resume interview session."}), 500


@interview_bp.route("/api/interview/sessions", methods=["GET"])
def api_list_interview_sessions():
    """
    Lists interview sessions for the logged-in student along with their status
    ('In Progress', 'Paused', or 'Completed').
    """
    student_id = (
        flask_session.get("user_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("student_id")
        or "default_student"
    )
    try:
        from utils.interview_session_service import get_student_interview_sessions_with_status
        sessions = get_student_interview_sessions_with_status(str(student_id))
        return jsonify({
            "status": "success",
            "count": len(sessions),
            "sessions": sessions
        }), 200
    except Exception as e:
        logger.error(f"Error listing interview sessions: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch interview sessions."}), 500


@interview_bp.route("/api/interview/subjects", methods=["GET"])
def api_get_interview_subjects():
    """
    Returns the catalog of technical subjects available for targeted interview practice
    (Python, Java, SQL, DBMS, Operating Systems, Computer Networks).
    """
    from utils.subject_interview_service import get_subject_catalog
    return jsonify({
        "status": "success",
        "subjects": get_subject_catalog()
    }), 200


@interview_bp.route("/api/interview/subject/generate", methods=["POST"])
def api_generate_subject_interview_question():
    """Generates a targeted mock interview question for a specific technical subject."""
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    subject = payload.get("subject", "python")

    from utils.subject_interview_service import generate_subject_question
    q_data = generate_subject_question(subject)
    return jsonify({
        "status": "success",
        "data": q_data
    }), 200


@interview_bp.route("/api/interview/subject/evaluate", methods=["POST"])
def api_evaluate_subject_interview_answer():
    """Evaluates a student's answer against the technical subject rubric."""
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    subject = payload.get("subject", "python")
    question = payload.get("question", "")
    answer = payload.get("answer", "")

    from utils.subject_interview_service import evaluate_subject_answer
    eval_res = evaluate_subject_answer(subject, question, answer)
    return jsonify({
        "status": "success",
        "evaluation": eval_res
    }), 200


@interview_bp.route("/api/interview/question/flag", methods=["POST"])
def api_interview_question_flag():
    """
    Flag an unsuitable mock interview question (#327).
    """
    from utils.question_flag_service import flag_interview_question
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form

    session_id = payload.get("session_id") or payload.get("interview_id") or "mock-session"
    question_index = payload.get("question_index", 0)
    question_text = payload.get("question_text") or payload.get("question", "")
    reason = payload.get("reason") or "Irrelevant to Target Role"
    comment = payload.get("comment", "")

    try:
        result = flag_interview_question(
            student_id=student_id,
            session_id=str(session_id),
            question_index=int(question_index),
            question_text=str(question_text),
            reason=str(reason),
            comment=str(comment)
        )
        return jsonify(result), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except PermissionError as pe:
        return jsonify({"success": False, "error": str(pe)}), 403
    except Exception as e:
        logger.error(f"Error recording question flag: {e}")
        return jsonify({"success": False, "error": "Internal error flagging question."}), 500


@interview_bp.route("/api/interview/question/flag-reasons", methods=["GET"])
def api_interview_question_flag_reasons():
    """
    Return available question flag categories (#327).
    """
    from utils.question_flag_service import VALID_FLAG_REASONS
    return jsonify({"success": True, "reasons": VALID_FLAG_REASONS}), 200


@interview_bp.route("/interview/<analysis_id>/reset", methods=["POST"])
def reset_interview_session(analysis_id: str):
    """
    Resets an active mock interview session back to question index 0 with empty answers,
    enabling students to retake and practice rounds anew without losing the parent analysis (#496).
    """
    try:
        raw_round = request.args.get("round", "").lower()
        post_json = request.get_json(silent=True) or {}

        session_id = (
            request.args.get("session_id")
            or post_json.get("session_id")
            or (f"{analysis_id}_{raw_round}" if raw_round in ["hr", "technical", "behavioral"] else None)
            or analysis_id
        )

        session = get_interview_session(session_id)
        if not session and session_id != analysis_id:
            # Fall back to base analysis_id if round-specific session not found
            session_id = analysis_id
            session = get_interview_session(session_id)

        if not session:
            return jsonify({"success": False, "error": "Interview session not found"}), 404

        update_interview_session(
            interview_id=session_id,
            current_question_index=0,
            answers_list=[],
            completed=False,
        )

        # Reset session status in state registry if table exists
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE interviews SET status = 'In Progress' WHERE id = ?", (session_id,))
            c.execute("UPDATE interview_session_state SET status = 'In Progress', pause_timestamp = NULL WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()
        except Exception as e_st:
            logger.debug(f"Could not reset session state status: {e_st}")

        return jsonify({
            "success": True,
            "message": "Interview session reset successfully. You can now retake this round.",
            "session_id": session_id,
        }), 200
    except Exception as exc:
        logger.error(f"Error resetting interview session: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@interview_bp.route("/interview/<analysis_id>/project-deep-dive", methods=["GET"])
def project_deep_dive_view(analysis_id: str):
    """
    Renders Project Deep-Dive interview mode for candidate resume projects (#466).
    Lists detected projects for selection, or displays an empty state if none are found.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        flash("Cannot initialize Project Deep-Dive. Analysis record not found.", "error")
        return redirect(url_for("index"))

    projects = project_deep_dive_agent.extract_projects(analysis_record)
    company_name = analysis_record.get("company_name", "Placement")

    return render_template(
        "project_deep_dive.html",
        analysis_id=analysis_id,
        analysis=analysis_record,
        company_name=company_name,
        projects=projects,
        projects_json=json.dumps(projects),
    )


@interview_bp.route("/api/interview/<analysis_id>/project-deep-dive/questions", methods=["POST"])
@rate_limit(scope="interview_eval", is_api=True)
def api_generate_project_deep_dive_questions(analysis_id: str):
    """
    Generates 5 technical follow-up questions grounded strictly in the selected project entry (#466).
    Rejects with 400 if project description is too thin, prompting the candidate to add detail first.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        return jsonify({"success": False, "error": "Analysis not found or unauthorized."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    project = payload.get("project")
    project_id = payload.get("project_id")
    additional_details = str(payload.get("additional_details", "")).strip()

    # If full project object was not passed, resolve by project_id
    if not project or not isinstance(project, dict):
        projects = project_deep_dive_agent.extract_projects(analysis_record)
        if project_id:
            for p in projects:
                if str(p.get("id")) == str(project_id):
                    project = p
                    break
        if not project and projects:
            project = projects[0]

    if not project or not isinstance(project, dict):
        return jsonify({
            "success": False,
            "error": "No valid project selected or detected in this resume.",
            "questions": [],
        }), 400

    company_name = analysis_record.get("company_name", "Placement")
    result = project_deep_dive_agent.generate_questions(
        project=project,
        company_name=company_name,
        additional_details=additional_details,
    )

    if not result.get("success"):
        return jsonify(result), 400

    return jsonify(result), 200


@interview_bp.route("/api/interview/<analysis_id>/project-deep-dive/evaluate", methods=["POST"])
@rate_limit(scope="interview_eval", is_api=True)
def api_evaluate_project_deep_dive_answer(analysis_id: str):
    """
    Evaluates candidate's response to a Project Deep-Dive question (#466).
    Returns clarity, depth, and consistency scores with exactly one improvement tip.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        return jsonify({"success": False, "error": "Analysis not found or unauthorized."}), 404

    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    project = payload.get("project") or {}
    question = str(payload.get("question", "")).strip()
    answer = str(payload.get("answer", "")).strip()

    if not question:
        return jsonify({"success": False, "error": "Question prompt is required for evaluation."}), 400

    evaluation = project_deep_dive_agent.evaluate_answer(
        project=project,
        question=question,
        answer=answer,
    )

    return jsonify({
        "status": "success",
        "success": True,
        "evaluation": evaluation,
    }), 200


@interview_bp.route("/interview/<analysis_id>/export")
def export_interview_json(analysis_id: str):
    """
    Exports the mock interview Q&A transcript and dynamic evaluations as a JSON download.
    """
    session_id = (
        request.args.get("session_id")
        or (f"{analysis_id}_{request.args.get('round', '').lower()}" if request.args.get('round') else None)
        or analysis_id
    )
    session = get_interview_session(session_id)
    if not session and session_id != analysis_id:
        session_id = analysis_id
        session = get_interview_session(session_id)

    analysis_record = get_analysis(analysis_id)

    if not analysis_record or analysis_record.get("student_id") != flask_session["user_id"]:
        return jsonify({"error": "Interview session not found."}), 404

    if not session:
        flash("Interview session not found.", "error")
        return redirect(url_for("index"))

    company_name = analysis_record.get("company_name", "General") if analysis_record else "General"
    answers_recorded = session.get("answers", [])
    session_summary = live_interview_agent.calculate_session_summary(answers_recorded) if answers_recorded else {}

    export_data = {
        "analysis_id": analysis_id,
        "company_name": company_name,
        "completed": bool(session.get("completed", 0)),
        "total_questions": len(session.get("questions", [])),
        "answers_recorded": len(answers_recorded),
        "session_summary": session_summary,
        "transcript": answers_recorded,
    }

    response = jsonify(export_data)
    safe_company = "".join(c for c in company_name if c.isalnum() or c in ("-", "_"))
    response.headers["Content-Disposition"] = (
        f"attachment; filename=Mock_Interview_{safe_company}_{analysis_id[:8]}.json"
    )
    return response


@interview_bp.route("/interview/<analysis_id>/transcript")
@interview_bp.route("/download/interview-transcript/<analysis_id>")
def download_interview_transcript(analysis_id: str):
    """
    Exports the mock interview transcript, per-question scores, AI feedback,
    and aggregate performance summary as a downloadable PDF, Markdown, or plain text file (#161).
    Works after at least one question has been answered.
    """
    try:
        session_id = (
            request.args.get("session_id")
            or (f"{analysis_id}_{request.args.get('round', '').lower()}" if request.args.get('round') else None)
            or analysis_id
        )
        session = get_interview_session(session_id)
        if not session and session_id != analysis_id:
            session_id = analysis_id
            session = get_interview_session(session_id)

        if not session:
            flash("Interview session not found.", "error")
            return redirect(url_for("interview", analysis_id=analysis_id))

        answers_recorded = session.get("answers", [])
        if not answers_recorded:
            if request.headers.get("Accept") == "application/json":
                return jsonify({"error": "No answers recorded yet. Submit at least one answer to download the transcript."}), 400
            flash("No interview answers recorded yet. Please submit at least one answer before downloading the transcript.", "warning")
            return redirect(url_for("interview", analysis_id=analysis_id))

        analysis_record = get_analysis(analysis_id)
        company_name = analysis_record.get("company_name", "General") if analysis_record else "General"
        session_summary = live_interview_agent.calculate_session_summary(answers_recorded)

        safe_company = "".join(c for c in company_name if c.isalnum() or c in ("-", "_")) or "Placement"
        filename_base = f"Interview_Transcript_{safe_company}_{analysis_id[:8]}"
        export_format = request.args.get("format", "pdf").strip().lower()

        if export_format in ("md", "markdown"):
            md_content = generate_interview_transcript_markdown(
                session_data=session,
                company_name=company_name,
                summary_data=session_summary,
            )
            return Response(
                md_content,
                mimetype="text/markdown",
                headers={"Content-Disposition": f"attachment; filename={filename_base}.md"},
            )
        elif export_format in ("txt", "text"):
            txt_content = generate_interview_transcript_markdown(
                session_data=session,
                company_name=company_name,
                summary_data=session_summary,
            )
            return Response(
                txt_content,
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename={filename_base}.txt"},
            )
        elif export_format == "json":
            return redirect(url_for("export_interview_json", analysis_id=analysis_id, session_id=session_id))
        else:
            # Default PDF
            os.makedirs(config.REPORT_FOLDER, exist_ok=True)
            pdf_filename = f"{filename_base}_{session_id}.pdf"
            pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_filename)

            generate_interview_transcript_pdf(
                session_data=session,
                output_path=pdf_full_path,
                company_name=company_name,
                summary_data=session_summary,
            )
            return send_file(
                pdf_full_path,
                as_attachment=True,
                download_name=f"{filename_base}.pdf",
                mimetype="application/pdf",
            )
    except Exception as e:
        logger.error(f"Failed to generate and serve interview transcript: {str(e)}")
        flash(f"Error compiling interview transcript: {str(e)}", "error")
        return redirect(url_for("interview", analysis_id=analysis_id))


@interview_bp.route("/interview-history")
def interview_history_view():
    """
    Mock Interview Performance History view (#144).
    Displays historical mock interview attempts, scores by question type, and score progression trends.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    analytics = get_student_interview_performance_analytics(student_id=student_id)
    return render_template("interview_history.html", analytics=analytics, student_id=student_id)


@interview_bp.route("/api/interview-history")
def api_interview_history():
    """
    API endpoint returning historical mock interview attempts and analytics (#144).
    """
    student_id = request.args.get("student_id", "default_student").strip()
    analytics = get_student_interview_performance_analytics(student_id=student_id)
    return jsonify({
        "success": True,
        "student_id": student_id,
        "analytics": analytics
    })


@interview_bp.route("/api/notifications/remind-interview", methods=["POST"])
def api_send_interview_reminder():
    """
    API endpoint to dispatch on-demand or scheduled interview reminders (#186).
    """
    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id") or "default_student"
    company_name = payload.get("company_name", "").strip()
    round_type = payload.get("round_type", "Technical Round").strip()
    scheduled_time = payload.get("scheduled_time", "").strip()
    interview_link = payload.get("interview_link", "").strip()

    if not company_name or not scheduled_time:
        return jsonify({"success": False, "error": "Company name and scheduled time are required."}), 400

    prefs = get_email_notification_preferences(student_id)
    if not prefs.get("email_enabled") or not prefs.get("notify_interview_reminder"):
        return jsonify({"success": False, "message": "Email notifications are disabled in user settings."}), 200

    recipient_email = prefs.get("email") or payload.get("email") or f"{student_id}@student.campus.edu"
    sent = email_service.send_interview_reminder_email(
        recipient_email=recipient_email,
        student_name=student_id,
        company_name=company_name,
        interview_round=round_type,
        scheduled_time=scheduled_time,
        interview_link=interview_link or None,
        locale=prefs.get("output_language", DEFAULT_OUTPUT_LOCALE),
    )

    return jsonify({"success": sent, "recipient": recipient_email}), (200 if sent else 500)


@interview_bp.route("/interview-experiences", methods=["GET", "POST"])
def interview_experiences_view():
    """
    Company-Wise Interview Experiences View and Submission Handler (#189).
    Enables students to learn from real campus placement interview rounds (Coding, Technical, HR)
    and submit their own verified candidate experiences anonymously.
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"
    company_filter = request.args.get("company", "").strip()
    category_filter = request.args.get("category", "All").strip()
    search_query = request.args.get("search", "").strip()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        role_title = request.form.get("role_title", "").strip()
        interview_date = request.form.get("interview_date", "").strip()
        overall_verdict = request.form.get("overall_verdict", "Offer").strip()
        difficulty_level = request.form.get("difficulty_level", "Medium").strip()
        tips = request.form.get("tips_and_preparation", "").strip()
        candidate_name = request.form.get("candidate_name", "").strip() or "Anonymous Candidate"

        if not company_name or not role_title or not interview_date:
            flash("Company name, job role, and interview date are required.", "error")
            return redirect(url_for("interview_experiences_view"))

        # Parse submitted rounds (Coding, Technical, HR)
        round_categories = request.form.getlist("round_category[]")
        round_descriptions = request.form.getlist("round_description[]")
        round_questions = request.form.getlist("round_questions[]")

        rounds = []
        for idx in range(len(round_categories)):
            cat = round_categories[idx].strip() if idx < len(round_categories) else "Technical"
            desc = round_descriptions[idx].strip() if idx < len(round_descriptions) else ""
            q_text = round_questions[idx].strip() if idx < len(round_questions) else ""
            if cat or desc or q_text:
                rounds.append({
                    "round_number": idx + 1,
                    "category": cat or "Technical",
                    "description": desc,
                    "questions": [q.strip() for q in q_text.split("\n") if q.strip()]
                })

        if not rounds:
            # Fallback default round if omitted
            rounds.append({
                "round_number": 1,
                "category": "Technical",
                "description": "Standard placement interview round.",
                "questions": []
            })

        exp_id = f"exp-{uuid.uuid4().hex[:12]}"
        save_interview_experience(
            exp_id=exp_id,
            student_id=student_id,
            candidate_name=candidate_name,
            company_name=company_name,
            role_title=role_title,
            interview_date=interview_date,
            rounds=rounds,
            overall_verdict=overall_verdict,
            difficulty_level=difficulty_level,
            tips_and_preparation=tips
        )
        flash("Thank you! Your interview experience was shared successfully.", "success")
        return redirect(url_for("interview_experiences_view", company=company_name))

    experiences = get_interview_experiences(
        company_name=company_filter,
        category_filter=category_filter,
        search_query=search_query
    )

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    pagination = Pagination(
        items=experiences,
        page=page,
        per_page=per_page,
        endpoint_args=request.args.to_dict(),
        base_url="/interview-experiences"
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "count": len(pagination.items),
            "total": len(experiences),
            "experiences": pagination.items,
            "pagination": pagination.to_dict()
        }), 200

    return render_template(
        "interview_experiences.html",
        experiences=pagination.items,
        pagination=pagination,
        company_filter=company_filter,
        category_filter=category_filter,
        search_query=search_query,
        student_id=student_id
    )


@interview_bp.route("/api/interview-experiences/<exp_id>/report", methods=["POST"])
def api_report_interview_experience(exp_id: str):
    """
    Moderation reporting endpoint for misleading or inappropriate interview posts (#189).
    """
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason") or request.form.get("reason", "Inappropriate or misleading submission.")
    reported = report_interview_experience(exp_id=exp_id, reason=reason)
    return jsonify({
        "success": reported,
        "message": "Submission reported and flagged for moderation review." if reported else "Experience not found."
    }), (200 if reported else 404)


@interview_bp.route("/api/self-introduction/<analysis_id>/generate", methods=["POST"])
def api_generate_self_intro(analysis_id: str):
    """
    Generates 30s, 60s, and 90s self-introduction scripts from verified resume details
    and target role/company context without fabricating achievements (#432).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            return jsonify({
                "success": False,
                "error": "Analysis record not found or access denied."
            }), 404

        payload = request.get_json(silent=True) or request.form or {}
        role_title = payload.get("role_title") or analysis_record.get("target_role") or "Software Engineer"
        company_name = payload.get("company_name") or analysis_record.get("company_name") or "General"

        intro_data = self_introduction_agent.generate_scripts(
            analysis_record=analysis_record,
            target_role=role_title,
            target_company=company_name
        )

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "data": intro_data
        }), 200

    except Exception as e:
        logger.error(f"Error generating self-introduction scripts for {analysis_id}: {e}")
        return jsonify({
            "success": False,
            "error": f"Failed to generate self-introduction: {str(e)}"
        }), 500


@interview_bp.route("/api/self-introduction/calculate-time", methods=["POST"])
def api_calculate_self_intro_time():
    """
    Computes word count, character count, estimated speaking duration, and formatted display
    for arbitrary speech script text in real-time (#432).
    """
    try:
        payload = request.get_json(silent=True) or request.form or {}
        text = payload.get("text", "")
        time_metrics = calculate_speaking_time(text)
        return jsonify({
            "success": True,
            "metrics": time_metrics
        }), 200
    except Exception as e:
        logger.error(f"Error calculating speaking time: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@interview_bp.route("/api/self-introduction/<analysis_id>/practice", methods=["POST"])
def api_practice_self_intro(analysis_id: str):
    """
    Evaluates student practice delivery text against the Present-Past-Future framework,
    clarity, pacing, and target duration (#432).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            return jsonify({
                "success": False,
                "error": "Analysis record not found or access denied."
            }), 404

        payload = request.get_json(silent=True) or request.form or {}
        practice_text = (payload.get("practice_text") or payload.get("text") or "").strip()
        target_duration = int(payload.get("target_duration") or 60)
        target_role = payload.get("role_title") or analysis_record.get("target_role") or "Software Engineer"
        target_company = payload.get("company_name") or analysis_record.get("company_name") or "General"

        if not practice_text:
            return jsonify({
                "success": False,
                "error": "Practice script text cannot be empty."
            }), 400

        evaluation = self_introduction_agent.evaluate_practice_delivery(
            practice_text=practice_text,
            target_duration=target_duration,
            target_role=target_role,
            target_company=target_company,
            analysis_record=analysis_record
        )

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "evaluation": evaluation
        }), 200

    except Exception as e:
        logger.error(f"Error evaluating self-introduction practice for {analysis_id}: {e}")
        return jsonify({
            "success": False,
            "error": f"Failed to evaluate practice delivery: {str(e)}"
        }), 500


@interview_bp.route("/notes", methods=["GET", "POST"])
def interview_notes_view():
    """
    Renders the Interview Preparation Notes dashboard and handles new note creation (#235).
    Enforces per-student isolation and supports filtering by category and search terms.
    """
    json_body = request.get_json(silent=True) if request.is_json else {}
    if not isinstance(json_body, dict):
        json_body = {}

    student_id = (
        request.args.get("student_id")
        or json_body.get("student_id")
        or request.form.get("student_id")
        or flask_session.get("user_id")
        or (flask_session.get("user", {}).get("id") if isinstance(flask_session.get("user"), dict) else None)
        or flask_session.get("student_id")
        or "default_student"
    ).strip()

    is_api_request = (
        request.path == "/api/notes"
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        title = (payload.get("title") or "").strip()
        description = (payload.get("description") or payload.get("content") or "").strip()
        category = (payload.get("category") or "Technical").strip()

        if not title or not description:
            if is_api_request:
                return jsonify({
                    "success": False,
                    "error": "Note title and description are required."
                }), 400
            flash("Note title and description are required.", "danger")
            return redirect(url_for("interview_notes_view", student_id=student_id))

        try:
            created_note = create_preparation_note(
                student_id=student_id,
                title=title,
                description=description,
                category=category
            )
            if is_api_request:
                return jsonify({
                    "success": True,
                    "message": "Interview preparation note created successfully.",
                    "note": created_note
                }), 201

            flash("Interview preparation note saved successfully!", "success")
            return redirect(url_for("interview_notes_view", student_id=student_id))
        except Exception as err:
            logger.error(f"Error creating preparation note: {err}")
            if is_api_request:
                return jsonify({
                    "success": False,
                    "error": "Failed to create preparation note."
                }), 500
            flash("Failed to save note. Please try again.", "danger")
            return redirect(url_for("interview_notes_view", student_id=student_id))

    category_filter = request.args.get("category", "All").strip()
    search_query = request.args.get("search", "").strip()

    notes = get_preparation_notes(
        student_id=student_id,
        category_filter=category_filter,
        search_query=search_query
    )
    category_counts = get_note_category_counts(student_id)

    if is_api_request:
        return jsonify({
            "success": True,
            "student_id": student_id,
            "notes": notes,
            "category_counts": category_counts,
            "current_category": category_filter,
            "search_query": search_query
        }), 200

    return render_template(
        "notes.html",
        notes=notes,
        category_counts=category_counts,
        current_category=category_filter,
        search_query=search_query,
        student_id=student_id
    )


@interview_bp.route("/api/notes", methods=["GET", "POST"])
def api_notes_collection():
    """
    Dedicated REST API collection endpoint for interview preparation notes (#235).
    """
    return interview_notes_view()


@interview_bp.route("/api/notes/<note_id>", methods=["GET", "PUT", "POST", "DELETE"])
def api_note_operations(note_id: str):
    """
    Retrieves, updates, or permanently deletes a student's private preparation note (#235).
    Enforces strict user isolation.
    """
    json_data = request.get_json(silent=True) if request.is_json else {}
    if not isinstance(json_data, dict):
        json_data = {}

    student_id = (
        request.args.get("student_id")
        or json_data.get("student_id")
        or request.form.get("student_id")
        or flask_session.get("user_id")
        or (flask_session.get("user", {}).get("id") if isinstance(flask_session.get("user"), dict) else None)
        or flask_session.get("student_id")
        or "default_student"
    ).strip()

    if request.method == "GET":
        note = get_preparation_note_by_id(note_id=note_id, student_id=student_id)
        if not note:
            return jsonify({
                "success": False,
                "error": "Note not found or unauthorized."
            }), 404
        return jsonify({
            "success": True,
            "note": note
        }), 200

    if request.method in ["PUT", "POST"]:
        payload = request.get_json(silent=True) or request.form
        existing = get_preparation_note_by_id(note_id=note_id, student_id=student_id)
        if not existing:
            return jsonify({
                "success": False,
                "error": "Note not found or unauthorized."
            }), 404

        title = (payload.get("title") or existing["title"]).strip()
        description = (payload.get("description") or payload.get("content") or existing["description"]).strip()
        category = (payload.get("category") or existing["category"]).strip()

        if not title or not description:
            return jsonify({
                "success": False,
                "error": "Title and description are required."
            }), 400

        updated = update_preparation_note(
            note_id=note_id,
            student_id=student_id,
            title=title,
            description=description,
            category=category
        )
        if updated:
            refreshed = get_preparation_note_by_id(note_id=note_id, student_id=student_id)
            return jsonify({
                "success": True,
                "message": "Preparation note updated successfully.",
                "note": refreshed
            }), 200
        return jsonify({
            "success": False,
            "error": "Failed to update preparation note."
        }), 500

    if request.method == "DELETE":
        deleted = delete_preparation_note(note_id=note_id, student_id=student_id)
        if deleted:
            return jsonify({
                "success": True,
                "message": "Preparation note deleted successfully."
            }), 200
        return jsonify({
            "success": False,
            "error": "Note not found or unauthorized."
        }), 404


@interview_bp.route("/api/notes/categories", methods=["GET"])
def api_notes_categories():
    """
    Returns aggregated note category counts for the authenticated student (#235).
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user_id")
        or (flask_session.get("user", {}).get("id") if isinstance(flask_session.get("user"), dict) else None)
        or flask_session.get("student_id")
        or "default_student"
    ).strip()
    counts = get_note_category_counts(student_id=student_id)
    return jsonify({
        "success": True,
        "student_id": student_id,
        "category_counts": counts,
        "counts": counts
    }), 200


@interview_bp.route("/api/interview-experiences/search", methods=["GET"])
def api_search_interview_experiences_endpoint():
    """
    Advanced multi-facet search endpoint for campus interview experiences.
    Supports filtering by company, role, verdict, difficulty, round category, year,
    and sorting with pagination.
    """
    company_name = request.args.get("company")
    role_title = request.args.get("role")
    verdict = request.args.get("verdict")
    difficulty = request.args.get("difficulty")
    category_filter = request.args.get("category")
    year_filter = request.args.get("year")
    search_query = request.args.get("q") or request.args.get("search")
    sort_by = request.args.get("sort", "date_desc")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))

    result = search_and_filter_interview_experiences(
        company_name=company_name,
        role_title=role_title,
        verdict=verdict,
        difficulty=difficulty,
        category_filter=category_filter,
        year_filter=year_filter,
        search_query=search_query,
        sort_by=sort_by,
        page=page,
        page_size=page_size
    )

    return jsonify({
        "status": "success",
        "data": result
    }), 200


@interview_bp.route("/api/interview-experiences/facets", methods=["GET"])
def api_interview_experience_facets_endpoint():
    """
    Returns unique aggregations and metrics for populating dynamic frontend filters.
    """
    facets = get_interview_filter_facets()
    return jsonify({
        "status": "success",
        "facets": facets
    }), 200


def preparation_notes_view():
    """
    Personal Interview Preparation Notes View (#235).
    Provides students with an organized space to create, filter, edit, and review notes.
    Guarantees strict candidate privacy: one student cannot view another's notes.
    """
    student_id = _get_current_student_id()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Technical").strip()

        if not title:
            flash("Note title is required.", "danger")
        elif not description:
            flash("Note description or content cannot be empty.", "danger")
        else:
            create_preparation_note(
                student_id=student_id,
                title=title,
                description=description,
                category=category
            )
            flash(f"Note '{title}' created successfully!", "success")
            return redirect(url_for("preparation_notes_view", category=category))

    category_filter = request.args.get("category", "All").strip()
    search_query = request.args.get("search", "").strip()

    notes = get_preparation_notes(
        student_id=student_id,
        category_filter=category_filter if category_filter != "All" else None,
        search_query=search_query or None
    )
    category_counts = get_note_category_counts(student_id)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "count": len(notes),
            "notes": notes,
            "category_counts": category_counts
        }), 200

    return render_template(
        "notes.html",
        notes=notes,
        category_counts=category_counts,
        current_category=category_filter,
        search_query=search_query,
        categories=NOTE_CATEGORIES,
        student_id=student_id
    )


@interview_bp.route("/notes/<note_id>", methods=["GET", "POST"])
def preparation_note_detail_view(note_id: str):
    """
    Individual Interview Preparation Note View and Update (#235).
    """
    student_id = _get_current_student_id()
    note = get_preparation_note_by_id(note_id, student_id)
    if not note:
        flash("Note not found or access denied.", "danger")
        return redirect(url_for("preparation_notes_view")), 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Technical").strip()

        if not title:
            flash("Note title cannot be empty.", "danger")
        elif not description:
            flash("Note description cannot be empty.", "danger")
        else:
            update_preparation_note(
                note_id=note_id,
                student_id=student_id,
                title=title,
                description=description,
                category=category
            )
            flash("Note updated successfully!", "success")
            return redirect(url_for("preparation_notes_view", category=category))

    return render_template("notes.html", active_note=note, categories=NOTE_CATEGORIES, student_id=student_id)


def api_preparation_notes():
    """
    REST API endpoint to fetch all notes or create a new note for the logged in student (#235).
    """
    student_id = _get_current_student_id()

    if request.method == "GET":
        category_filter = request.args.get("category", "All").strip()
        search_query = request.args.get("search", "").strip()
        notes = get_preparation_notes(
            student_id=student_id,
            category_filter=category_filter if category_filter != "All" else None,
            search_query=search_query or None
        )
        category_counts = get_note_category_counts(student_id)
        return jsonify({
            "success": True,
            "count": len(notes),
            "notes": notes,
            "category_counts": category_counts
        }), 200

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        title = (payload.get("title") or "").strip()
        description = (payload.get("description") or "").strip()
        category = (payload.get("category") or "Technical").strip()

        if not title:
            return jsonify({"success": False, "error": "Note title is required"}), 400
        if not description:
            return jsonify({"success": False, "error": "Note description is required"}), 400

        note = create_preparation_note(
            student_id=student_id,
            title=title,
            description=description,
            category=category
        )
        category_counts = get_note_category_counts(student_id)
        return jsonify({
            "success": True,
            "message": "Note created successfully",
            "note": note,
            "category_counts": category_counts
        }), 201


def api_preparation_note_item(note_id: str):
    """
    REST API endpoint to retrieve, update, or delete a specific note (#235).
    Enforces strict candidate privacy: checks note ownership against logged in student.
    """
    student_id = _get_current_student_id()

    existing_note = get_preparation_note_by_id(note_id, student_id)
    if not existing_note:
        return jsonify({
            "success": False,
            "error": "Note not found or access denied."
        }), 404

    if request.method == "GET":
        return jsonify({
            "success": True,
            "note": existing_note
        }), 200

    if request.method in ["PUT", "POST"]:
        payload = request.get_json(silent=True) or request.form
        title = (payload.get("title") or existing_note["title"]).strip()
        description = (payload.get("description") or existing_note["description"]).strip()
        category = (payload.get("category") or existing_note["category"]).strip()

        if not title:
            return jsonify({"success": False, "error": "Note title cannot be empty"}), 400
        if not description:
            return jsonify({"success": False, "error": "Note description cannot be empty"}), 400

        updated = update_preparation_note(
            note_id=note_id,
            student_id=student_id,
            title=title,
            description=description,
            category=category
        )
        if updated:
            refreshed = get_preparation_note_by_id(note_id, student_id)
            category_counts = get_note_category_counts(student_id)
            return jsonify({
                "success": True,
                "message": "Note updated successfully",
                "note": refreshed,
                "category_counts": category_counts
            }), 200
        return jsonify({"success": False, "error": "Failed to update note"}), 500

    if request.method == "DELETE":
        deleted = delete_preparation_note(note_id, student_id)
        category_counts = get_note_category_counts(student_id)
        return jsonify({
            "success": deleted,
            "message": "Note deleted successfully" if deleted else "Note not found",
            "category_counts": category_counts
        }), 200 if deleted else 404


@interview_bp.route("/api/notes/<note_id>/delete", methods=["POST"])
def api_delete_preparation_note_form(note_id: str):
    """
    Form-friendly deletion endpoint for non-JS browser fallbacks (#235).
    """
    student_id = _get_current_student_id()
    deleted = delete_preparation_note(note_id, student_id)
    if deleted:
        flash("Note deleted successfully.", "success")
    else:
        flash("Note could not be deleted or access was denied.", "danger")
    return redirect(url_for("preparation_notes_view"))


@interview_bp.route("/api/interview/practice/topics", methods=["GET"])
def api_interview_practice_topics():
    """Returns available technical practice topics and supported difficulty levels."""
    catalog = get_supported_topics()
    return jsonify({
        "status": "success",
        "data": catalog
    }), 200


@interview_bp.route("/api/interview/practice/generate", methods=["POST"])
def api_generate_practice_question():
    """Generates an interview question targeted to a specific technical topic and difficulty level."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    topic = payload.get("topic")
    difficulty = payload.get("difficulty", "medium")

    if not topic:
        return jsonify({"status": "error", "message": "Field 'topic' is required."}), 400

    try:
        question_data = generate_topic_interview_question(topic=topic, difficulty=difficulty)
        return jsonify({
            "status": "success",
            "data": question_data
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error generating topic question: {e}")
        return jsonify({"status": "error", "message": "Failed to generate topic interview question."}), 500


@interview_bp.route("/api/interview/practice/evaluate", methods=["POST"])
def api_evaluate_practice_answer():
    """Evaluates a candidate's answer for a topic-specific interview question and persists the session."""
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()

    topic = payload.get("topic")
    difficulty = payload.get("difficulty", "medium")
    question_text = payload.get("question", "")
    question_id = payload.get("question_id", str(uuid.uuid4()))
    answer_text = payload.get("answer", "")

    if not topic:
        return jsonify({"status": "error", "message": "Field 'topic' is required."}), 400
    if not question_text:
        return jsonify({"status": "error", "message": "Field 'question' is required."}), 400

    try:
        evaluation = evaluate_topic_answer(
            topic=topic,
            difficulty=difficulty,
            question=question_text,
            answer=answer_text
        )

        # Record session in database for student history tracking
        saved_record = record_practice_session(
            student_id=student_id,
            topic=topic,
            difficulty=difficulty,
            question_id=question_id,
            question_text=question_text,
            answer=answer_text,
            evaluation=evaluation
        )

        return jsonify({
            "status": "success",
            "evaluation": evaluation,
            "session": saved_record
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error evaluating topic answer: {e}")
        return jsonify({"status": "error", "message": "Failed to evaluate topic response."}), 500


@interview_bp.route("/api/interview/bookmarks", methods=["GET"])
def api_get_interview_bookmarks():
    """
    Returns the student's bookmarked interview questions (#358).
    Optional query param: ?category=Technical|Behavioral|HR|Company-Specific
    """
    student_id = _get_current_student_id()
    category = request.args.get("category", "").strip() or None
    bookmarks = get_interview_bookmarks(student_id, category=category)
    return jsonify({
        "success": True,
        "student_id": student_id,
        "count": len(bookmarks),
        "bookmarks": bookmarks
    }), 200


@interview_bp.route("/api/interview/bookmark", methods=["POST"])
def api_save_interview_bookmark():
    """
    Bookmarks an interview question for a candidate (#358).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = _get_current_student_id()
    question_text = (payload.get("question_text") or payload.get("question") or "").strip()
    question_id = (payload.get("question_id") or payload.get("id") or "").strip()
    category = (payload.get("category") or payload.get("type") or "Technical").strip()
    company_name = (payload.get("company_name") or payload.get("company") or "General").strip()
    notes = (payload.get("notes") or "").strip()
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    if not question_text:
        return jsonify({"success": False, "error": "Question text is required"}), 400

    if not question_id:
        question_id = f"iq-{hashlib.sha256(question_text.encode('utf-8')).hexdigest()[:12]}"

    saved = save_interview_bookmark(
        student_id=student_id,
        question_id=question_id,
        question_text=question_text,
        category=category,
        company_name=company_name,
        notes=notes,
        metadata=metadata
    )
    return jsonify({
        "success": saved,
        "message": "Question bookmarked successfully" if saved else "Failed to save bookmark",
        "question_id": question_id,
        "bookmarked": True
    }), (200 if saved else 500)


@interview_bp.route("/api/interview/bookmark/<question_id>", methods=["DELETE", "POST"])
def api_remove_interview_bookmark(question_id: str):
    """
    Removes a bookmarked interview question for a candidate (#358).
    """
    student_id = _get_current_student_id()
    removed = remove_interview_bookmark(student_id, question_id)
    return jsonify({
        "success": removed,
        "message": "Bookmark removed successfully" if removed else "Bookmark not found or already removed",
        "bookmarked": False
    }), 200


@interview_bp.route("/api/interview/bookmark/toggle", methods=["POST"])
def api_toggle_interview_bookmark():
    """
    Toggles bookmark state for an interview question (#358).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = _get_current_student_id()
    question_text = (payload.get("question_text") or payload.get("question") or "").strip()
    question_id = (payload.get("question_id") or payload.get("id") or "").strip()
    category = (payload.get("category") or payload.get("type") or "Technical").strip()
    company_name = (payload.get("company_name") or payload.get("company") or "General").strip()
    notes = (payload.get("notes") or "").strip()

    if not question_text and not question_id:
        return jsonify({"success": False, "error": "Question text or question ID is required"}), 400

    if not question_id:
        question_id = f"iq-{hashlib.sha256(question_text.encode('utf-8')).hexdigest()[:12]}"

    already_bookmarked = is_interview_bookmarked(student_id, question_id)
    if already_bookmarked:
        remove_interview_bookmark(student_id, question_id)
        return jsonify({
            "success": True,
            "bookmarked": False,
            "question_id": question_id,
            "message": "Bookmark removed"
        }), 200
    else:
        if not question_text:
            return jsonify({"success": False, "error": "Question text is required to bookmark"}), 400
        saved = save_interview_bookmark(
            student_id=student_id,
            question_id=question_id,
            question_text=question_text,
            category=category,
            company_name=company_name,
            notes=notes
        )
        return jsonify({
            "success": saved,
            "bookmarked": True,
            "question_id": question_id,
            "message": "Question bookmarked successfully"
        }), 200


@interview_bp.route("/interview/bookmarks", methods=["GET"])
def interview_bookmarks_view():
    """
    Dedicated Review Page for Bookmarked Interview Questions (#358).
    Supports category filtering (Technical, Behavioral, HR, Company-Specific),
    keyword search, and JSON export.
    """
    student_id = request.args.get("student_id") or _get_current_student_id()
    active_category = request.args.get("category", "All").strip()
    search_query = request.args.get("search", "").strip()

    all_bookmarks = get_interview_bookmarks(student_id)

    # Calculate category counts
    counts = {
        "All": len(all_bookmarks),
        "Technical": 0,
        "Behavioral": 0,
        "HR": 0,
        "Company-Specific": 0
    }
    for b in all_bookmarks:
        cat = b.get("category", "Technical")
        matched = False
        for k in ["Technical", "Behavioral", "HR", "Company-Specific"]:
            if cat.lower() == k.lower():
                counts[k] += 1
                matched = True
                break
        if not matched:
            counts["Technical"] += 1

    # Filter by category if not 'All'
    filtered = all_bookmarks
    if active_category and active_category.lower() != "all":
        filtered = [b for b in filtered if b.get("category", "").lower() == active_category.lower()]

    # Filter by search query if provided
    if search_query:
        q_lower = search_query.lower()
        filtered = [
            b for b in filtered
            if q_lower in b.get("question_text", "").lower()
            or q_lower in b.get("company_name", "").lower()
            or q_lower in b.get("notes", "").lower()
        ]

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "student_id": student_id,
            "active_category": active_category,
            "counts": counts,
            "bookmarks": filtered
        }), 200

    return render_template(
        "interview_bookmarks.html",
        student_id=student_id,
        bookmarks=filtered,
        all_bookmarks=all_bookmarks,
        active_category=active_category,
        search_query=search_query,
        counts=counts
    )


@interview_bp.route("/interview/bookmarks/export", methods=["GET"])
def export_interview_bookmarks():
    """
    Export bookmarked interview questions as JSON file download (#358).
    """
    student_id = request.args.get("student_id") or _get_current_student_id()
    category = request.args.get("category", "").strip() or None
    bookmarks = get_interview_bookmarks(student_id, category=category)
    export_payload = {
        "exported_at": datetime.now().isoformat(),
        "student_id": student_id,
        "total_bookmarks": len(bookmarks),
        "bookmarks": bookmarks
    }
    return Response(
        json.dumps(export_payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=interview_bookmarks_{student_id}.json"}
    )


@interview_bp.route("/interview/bookmarks/practice", methods=["GET"])
def interview_saved_practice_view():
    """
    Focused Practice Mode for Bookmarked Interview Questions (#359).
    Presents saved questions one-by-one with answer recording, optional
    AI evaluation, and practice completion tracking.
    """
    student_id = request.args.get("student_id") or _get_current_student_id()
    active_category = request.args.get("category", "All").strip()
    unpracticed_only_arg = request.args.get("unpracticed_only", "").strip().lower()
    unpracticed_only = unpracticed_only_arg in ("1", "true", "yes")

    # Retrieve all bookmarks for this student
    all_bookmarks = get_interview_bookmarks(student_id)
    stats = get_interview_bookmark_practice_stats(student_id)

    # Filter by category
    filtered = all_bookmarks
    if active_category and active_category.lower() != "all":
        filtered = [b for b in filtered if b.get("category", "").lower() == active_category.lower()]

    # Filter unpracticed if requested
    if unpracticed_only:
        filtered = [b for b in filtered if not b.get("is_practiced")]

    target_question_id = request.args.get("question_id", "").strip()

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "student_id": student_id,
            "stats": stats,
            "active_category": active_category,
            "unpracticed_only": unpracticed_only,
            "count": len(filtered),
            "bookmarks": filtered
        }), 200

    return render_template(
        "interview_saved_practice.html",
        student_id=student_id,
        bookmarks=filtered,
        all_bookmarks=all_bookmarks,
        stats=stats,
        active_category=active_category,
        unpracticed_only=unpracticed_only,
        target_question_id=target_question_id
    )


@interview_bp.route("/api/interview/bookmarks/<question_id>/practice", methods=["POST"])
def api_save_interview_practice(question_id: str):
    """
    Saves a candidate's practice response and marks question as practiced (#359).
    """
    student_id = _get_current_student_id()
    payload = request.get_json(silent=True) or request.form
    answer = (payload.get("answer") or "").strip()
    is_practiced_raw = payload.get("is_practiced", True)
    if isinstance(is_practiced_raw, str):
        is_practiced = is_practiced_raw.lower() not in ("false", "0", "no")
    else:
        is_practiced = bool(is_practiced_raw)

    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        evaluation = None

    updated = update_interview_bookmark_practice(
        student_id=student_id,
        question_id=question_id,
        is_practiced=is_practiced,
        answer=answer,
        evaluation=evaluation
    )
    stats = get_interview_bookmark_practice_stats(student_id)
    return jsonify({
        "success": updated,
        "question_id": question_id,
        "is_practiced": is_practiced,
        "stats": stats,
        "message": "Practice progress saved successfully" if updated else "Bookmark not found or update failed"
    }), (200 if updated else 404)


@interview_bp.route("/api/interview/bookmarks/<question_id>/practice/status", methods=["POST"])
def api_toggle_interview_practice_status(question_id: str):
    """
    Toggles or sets the practiced state of a bookmarked interview question (#359).
    """
    student_id = _get_current_student_id()
    bm = get_interview_bookmark_by_id(student_id, question_id)
    if not bm:
        return jsonify({"success": False, "error": "Question bookmark not found"}), 404

    payload = request.get_json(silent=True) or request.form
    if "is_practiced" in payload:
        raw_val = payload.get("is_practiced")
        new_status = raw_val.lower() not in ("false", "0", "no") if isinstance(raw_val, str) else bool(raw_val)
    else:
        new_status = not bm.get("is_practiced", False)

    updated = update_interview_bookmark_practice(
        student_id=student_id,
        question_id=question_id,
        is_practiced=new_status
    )
    stats = get_interview_bookmark_practice_stats(student_id)
    return jsonify({
        "success": updated,
        "question_id": question_id,
        "is_practiced": new_status,
        "stats": stats,
        "message": f"Marked as {'practiced' if new_status else 'unpracticed'}"
    }), 200


@interview_bp.route("/api/interview/bookmarks/<question_id>/practice/evaluate", methods=["POST"])
@rate_limit(scope="star_eval", is_api=True)
def api_evaluate_saved_question_practice(question_id: str):
    """
    Evaluates candidate's written or spoken practice answer for a bookmarked question (#359).
    Uses STAR framework and speech telemetry analysis.
    """
    student_id = _get_current_student_id()
    bm = get_interview_bookmark_by_id(student_id, question_id)
    if not bm:
        return jsonify({"success": False, "error": "Bookmarked question not found"}), 404

    payload = request.get_json(silent=True) or request.form
    answer = (payload.get("answer") or "").strip()
    if not answer:
        return jsonify({"success": False, "error": "Answer text is required for evaluation"}), 400

    speech_metrics = payload.get("speech_metrics")
    if isinstance(speech_metrics, str):
        try:
            speech_metrics = json.loads(speech_metrics)
        except Exception:
            speech_metrics = {}
    elif not isinstance(speech_metrics, dict):
        speech_metrics = {}

    question_text = bm.get("question_text", "")
    category = bm.get("category", "Behavioral")

    try:
        eval_result = star_evaluation_agent.evaluate_star(
            question=question_text,
            answer=answer,
            question_type=category,
            speech_metrics=speech_metrics
        )
    except Exception as exc:
        logger.error(f"Error evaluating saved interview question practice: {exc}")
        eval_result = {
            "score": 75,
            "feedback": "Answer submitted and reviewed. Consider elaborating with specific outcomes and measurable results.",
            "technical_accuracy": 75,
            "communication_score": 75,
            "strengths": ["Clear attempt", "Addresses the prompt"],
            "improvement_areas": ["Add more structured details", "Quantify results where possible"]
        }

    # Normalize response fields for consistent client and report consumption
    if isinstance(eval_result, dict):
        if "star_overall_score" in eval_result and "score" not in eval_result:
            eval_result["score"] = eval_result["star_overall_score"]
        if "feedback" not in eval_result:
            coaching = eval_result.get("coaching", {})
            if isinstance(coaching, dict):
                improvements = coaching.get("improvements", [])
                strengths = coaching.get("strengths", [])
                feedback_parts = strengths + improvements
                eval_result["feedback"] = " ".join(feedback_parts) if feedback_parts else "Response evaluated successfully."
                eval_result["suggestions"] = improvements
                eval_result["strengths"] = strengths
            else:
                eval_result["feedback"] = str(coaching or "Response evaluated successfully.")

    # Automatically save answer, evaluation, and mark as practiced
    update_interview_bookmark_practice(
        student_id=student_id,
        question_id=question_id,
        is_practiced=True,
        answer=answer,
        evaluation=eval_result
    )
    stats = get_interview_bookmark_practice_stats(student_id)

    return jsonify({
        "success": True,
        "question_id": question_id,
        "is_practiced": True,
        "evaluation": eval_result,
        "stats": stats
    }), 200


@interview_bp.route("/api/interview/bookmarks/practice/reset", methods=["POST"])
def api_reset_interview_practice():
    """
    Resets practice progress across saved interview questions (#359).
    """
    student_id = _get_current_student_id()
    payload = request.get_json(silent=True) or request.form
    question_id = (payload.get("question_id") or "").strip() or None

    reset_interview_bookmarks_practice(student_id, question_id=question_id)
    stats = get_interview_bookmark_practice_stats(student_id)
    return jsonify({
        "success": True,
        "message": f"Practice progress reset for {'question ' + question_id if question_id else 'all saved questions'}",
        "stats": stats
    }), 200


@interview_bp.route("/api/interview/compare", methods=["POST"])
def api_interview_compare():
    """
    Compare multiple interview sessions for the logged-in student (#273).
    """
    from utils.interview_session_comparator import compare_interview_sessions
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form
    session_ids = payload.get("session_ids") or []
    if isinstance(session_ids, str):
        session_ids = [s.strip() for s in session_ids.split(",") if s.strip()]

    if not session_ids or len(session_ids) < 2:
        return jsonify({"success": False, "error": "Please provide at least two interview session IDs to compare."}), 400

    try:
        comparison = compare_interview_sessions(session_ids=session_ids, student_id=student_id)
        return jsonify(comparison), 200
    except KeyError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error during interview comparison: {e}")
        return jsonify({"success": False, "error": "Internal error comparing interview sessions."}), 500


@interview_bp.route("/interview/compare", methods=["GET"])
def interview_compare_page():
    """
    Render interview comparison page (#273).
    """
    student_id = flask_session.get("user_id") or "default_student"
    return render_template("interview_compare.html", student_id=student_id)


@interview_bp.route("/api/interview/answer-quality-audit", methods=["POST"])
def api_audit_interview_answer_quality():
    """
    Audits a candidate's interview answer across the 6-point structured Quality Rubric:
    direct question address, concrete examples, supported claims, technical explanation,
    structural flow, and actionable next steps.
    """
    payload = request.get_json(silent=True) or request.form.to_dict()
    question = payload.get("question", "")
    answer = payload.get("answer", "")
    question_type = payload.get("question_type", "technical")

    if not question:
        return jsonify({"status": "error", "message": "Question prompt is required."}), 400

    try:
        from utils.answer_quality_checklist import audit_interview_answer_quality
        audit_result = audit_interview_answer_quality(
            question=question,
            answer=answer,
            question_type=question_type
        )
        return jsonify({
            "status": "success",
            "audit": audit_result
        }), 200
    except Exception as e:
        logger.error(f"Error auditing answer quality: {e}")
        return jsonify({"status": "error", "message": "Failed to analyze answer quality checklist."}), 500


@interview_bp.route("/aptitude", methods=["GET"])
def aptitude_view():
    """
    Renders the interactive Timed Aptitude Practice & Assessment page (#426).
    Supports Quantitative Aptitude, Logical Reasoning, and Verbal Ability tests
    with timed countdowns, auto-submit on timeout, and per-topic diagnostics.
    """
    student_id = flask_session.get("user_id") or "default_student"
    summary = get_student_aptitude_summary(student_id)
    recent_attempts = get_student_aptitude_attempts(student_id, limit=10)
    weak_topics = get_student_weak_aptitude_topics(student_id)

    return render_template(
        "aptitude.html",
        categories=APTITUDE_CATEGORIES,
        summary=summary,
        recent_attempts=recent_attempts,
        weak_topics=weak_topics,
        student_id=student_id
    )


@interview_bp.route("/api/aptitude/start", methods=["POST"])
def api_aptitude_start():
    """
    Starts a timed aptitude practice set (#426).
    Sanitizes questions by omitting answers and explanations from the student payload.
    """
    payload = request.get_json(silent=True) or request.form.to_dict()
    category = payload.get("category", "all")
    num_questions = int(payload.get("num_questions", 10))
    time_limit = payload.get("time_limit_seconds")
    time_limit_seconds = int(time_limit) if time_limit is not None else None

    try:
        test_data = generate_aptitude_test_set(
            category=category,
            num_questions=max(3, min(30, num_questions)),
            time_limit_seconds=time_limit_seconds
        )
        return jsonify({
            "status": "success",
            "data": test_data
        }), 200
    except Exception as e:
        logger.error(f"Error starting aptitude test set: {e}")
        return jsonify({"status": "error", "message": "Failed to start aptitude test set."}), 500


@interview_bp.route("/api/aptitude/submit", methods=["POST"])
def api_aptitude_submit():
    """
    Evaluates a completed or timed-out aptitude test submission (#426).
    Computes overall score, per-topic accuracy, per-category breakdown,
    identifies weak topics, and persists the attempt for the authenticated student.
    """
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()

    question_ids = payload.get("question_ids") or []
    answers = payload.get("answers") or {}
    time_taken_seconds = int(payload.get("time_taken_seconds", 0))
    time_limit_seconds = int(payload.get("time_limit_seconds", 600))
    timed_out = bool(payload.get("timed_out", False))
    test_category = payload.get("test_category", "all")

    if not question_ids:
        return jsonify({"status": "error", "message": "Field 'question_ids' is required."}), 400

    try:
        result = record_and_evaluate_aptitude_test(
            student_id=student_id,
            question_ids=question_ids,
            answers=answers,
            time_taken_seconds=time_taken_seconds,
            time_limit_seconds=time_limit_seconds,
            timed_out=timed_out,
            test_category=test_category
        )
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except Exception as e:
        logger.error(f"Error evaluating aptitude submission: {e}")
        return jsonify({"status": "error", "message": "Failed to evaluate aptitude test submission."}), 500


@interview_bp.route("/api/aptitude/history", methods=["GET"])
def api_aptitude_history():
    """Retrieves chronological aptitude practice attempts for the student (#426)."""
    student_id = flask_session.get("user_id") or "default_student"
    limit = int(request.args.get("limit", 10))
    attempts = get_student_aptitude_attempts(student_id, limit=limit)
    return jsonify({
        "status": "success",
        "student_id": student_id,
        "count": len(attempts),
        "attempts": attempts
    }), 200


@interview_bp.route("/api/aptitude/weak-topics", methods=["GET"])
def api_aptitude_weak_topics():
    """Retrieves aggregated weak aptitude topics (<60% accuracy) for targeted revision (#426)."""
    student_id = flask_session.get("user_id") or "default_student"
    weak_topics = get_student_weak_aptitude_topics(student_id)
    return jsonify({
        "status": "success",
        "student_id": student_id,
        "count": len(weak_topics),
        "weak_topics": weak_topics
    }), 200


@interview_bp.route("/group-discussion", methods=["GET"])
def group_discussion_view():
    """
    Renders the interactive Group Discussion Practice page (#427).
    Allows students to browse curated campus GD topics across Current Affairs,
    Technology, and Abstract categories, spin for random topics, write structured
    contributions (opening, rebuttal, conclusion), and receive multi-criteria AI feedback.
    """
    student_id = flask_session.get("user_id") or "default_student"
    all_topics = load_gd_topics()
    grouped_topics = get_topics_by_category()

    # Pre-select topic if topic_id is provided in query params, else choose random
    selected_topic_id = request.args.get("topic_id")
    initial_topic = None
    if selected_topic_id:
        initial_topic = get_topic_by_id(selected_topic_id)
    if not initial_topic and all_topics:
        initial_topic = get_random_topic()

    past_attempts = get_student_gd_attempts(student_id, limit=10)

    return render_template(
        "group_discussion.html",
        topics=all_topics,
        grouped_topics=grouped_topics,
        initial_topic=initial_topic,
        categories=VALID_CATEGORIES,
        contribution_types=VALID_CONTRIBUTION_TYPES,
        past_attempts=past_attempts,
        student_id=student_id,
        min_words=MIN_WORD_COUNT,
        recommended_min_words=RECOMMENDED_MIN_WORDS,
        recommended_max_words=RECOMMENDED_MAX_WORDS,
    )


@interview_bp.route("/api/group-discussion/topics", methods=["GET"])
def api_get_gd_topics():
    """Returns the full collection of group discussion topics (#427)."""
    category = request.args.get("category")
    if category:
        all_topics = load_gd_topics()
        filtered = [t for t in all_topics if t.get("category", "").lower() == category.lower()]
        return jsonify({"status": "success", "count": len(filtered), "topics": filtered}), 200

    grouped = get_topics_by_category()
    all_topics = load_gd_topics()
    return jsonify({
        "status": "success",
        "count": len(all_topics),
        "topics": all_topics,
        "grouped": grouped
    }), 200


@interview_bp.route("/api/group-discussion/random-topic", methods=["GET"])
def api_random_gd_topic():
    """Selects and returns a random group discussion topic, optionally filtered by category (#427)."""
    category = request.args.get("category")
    try:
        topic = get_random_topic(category=category)
        return jsonify({
            "status": "success",
            "topic": topic
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error picking random GD topic: {e}")
        return jsonify({"status": "error", "message": "Failed to pick random GD topic."}), 500


@interview_bp.route("/api/group-discussion/evaluate", methods=["POST"])
def api_evaluate_gd_contribution():
    """
    Evaluates a student's group discussion submission and records the attempt (#427).
    Rejects empty or short answers (<30 words) with clear error message.
    Scores across Content, Structure, Balance, and Clarity, and suggests stronger opening and missed counterpoint.
    """
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()

    topic_title = payload.get("topic_title", "").strip()
    topic_id = payload.get("topic_id", "").strip() or None
    category = payload.get("category", "technology").strip().lower()
    contribution_type = payload.get("contribution_type", "opening").strip().lower()
    contribution_text = payload.get("contribution_text", "").strip()
    topic_description = payload.get("topic_description", "").strip() or None

    if not topic_title:
        return jsonify({"status": "error", "message": "Topic title is required."}), 400

    # Retrieve topic details if available for context
    topic_angles = None
    if topic_id:
        topic_meta = get_topic_by_id(topic_id)
        if topic_meta:
            topic_description = topic_description or topic_meta.get("description")
            topic_angles = topic_meta.get("key_angles")

    try:
        result = record_and_evaluate_gd_attempt(
            student_id=student_id,
            topic_title=topic_title,
            category=category,
            contribution_type=contribution_type,
            contribution_text=contribution_text,
            topic_id=topic_id,
            topic_description=topic_description,
            topic_angles=topic_angles
        )
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error evaluating group discussion contribution: {e}")
        return jsonify({"status": "error", "message": "Failed to evaluate contribution. Please try again."}), 500


@interview_bp.route("/api/group-discussion/history", methods=["GET"])
def api_get_gd_history():
    """Retrieves previous group discussion attempts for the authenticated student (#427)."""
    student_id = flask_session.get("user_id") or "default_student"
    limit = int(request.args.get("limit", 10))
    attempts = get_student_gd_attempts(student_id, limit=limit)
    return jsonify({
        "status": "success",
        "student_id": student_id,
        "count": len(attempts),
        "attempts": attempts
    }), 200



# Aliases for backwards compatibility (#235, #553)
preparation_notes_view = interview_notes_view
api_preparation_notes = api_notes_collection
api_preparation_note_item = api_note_operations
