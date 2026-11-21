"""
Coding_practice feature area routes & endpoints (#553).
Handles coding sandbox challenges, question bookmarks, folders, and evaluations.
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

coding_practice_bp = Blueprint("coding_practice", __name__)

@coding_practice_bp.route("/api/interview/<analysis_id>/coding-problem", methods=["GET"])
@coding_practice_bp.route("/api/interview/coding-problem", methods=["GET"])
def api_interview_coding_problem(analysis_id: str = None):
    """
    Returns a company-targeted DSA coding challenge with starter code and test cases.
    """
    try:
        company_name = request.args.get("company", "").strip()
        if analysis_id:
            record = get_analysis(analysis_id)

            if not record or not _is_student_authorized(record):
                 return jsonify({
                    "status": "error",
                    "message": "Analysis not found."
        }), 404

            if not company_name:
                company_name = record.get("company_name", "General")
        if not company_name:
            company_name = "General"

        difficulty = request.args.get("difficulty", "Medium").strip()
        category = request.args.get("category", None)
        if category:
            category = category.strip()

        problem = coding_assessment_agent.generate_problem(
            company_name=company_name,
            difficulty=difficulty,
            category=category,
        )

        return jsonify({
            "status": "success",
            "problem": problem
        }), 200

    except Exception as e:
        logger.error(f"Error generating coding challenge: {str(e)}")
        fallback = coding_assessment_agent.get_fallback_problem("General", "Medium")
        return jsonify({
            "status": "success",
            "problem": fallback,
            "fallback": True
        }), 200


@coding_practice_bp.route("/api/interview/<analysis_id>/evaluate-code", methods=["POST"])
@coding_practice_bp.route("/api/interview/evaluate-code", methods=["POST"])
@rate_limit(scope="interview_eval", is_api=True)
def api_evaluate_code(analysis_id: str = None):
    """
    Evaluates candidate code submission against problem statement and test cases.
    Returns correctness score, test-case pass/fail breakdown, and Big-O complexity.
    """
    try:
        payload = request.get_json() or {}
        code = payload.get("code", "")
        language = payload.get("language", "python")
        problem = payload.get("problem")

        if analysis_id:
            rec = get_analysis(analysis_id)

            if not rec or not _is_student_authorized(rec):
                 return jsonify({
                    "status": "error",
                    "message": "Analysis not found."
        }), 404

            company = rec.get("company_name", "General")
        else:
            company = "General"

        if not isinstance(problem, dict) or not problem:
            problem = coding_assessment_agent.get_fallback_problem(company)

        eval_result = coding_assessment_agent.evaluate_code(
            problem=problem,
            language=language,
            code=code
        )

        # Automatically store coding submission attempt (#194)
        student_id = payload.get("student_id") or flask_session.get("user_id") or "default_student"
        sub_id = f"sub-{uuid.uuid4().hex[:12]}"
        try:
            score_val = eval_result.get("score") or eval_result.get("correctness_score", 0)
            tests_passed_val = eval_result.get("tests_passed", 0)
            total_tests_val = eval_result.get("total_tests", 0)
            is_passed = bool(eval_result.get("passed", False)) or (int(score_val) >= 70)

            save_coding_submission(
                sub_id=sub_id,
                student_id=student_id,
                question_title=problem.get("title", "Coding Problem"),
                language=language,
                code=code,
                passed=is_passed,
                score=int(score_val),
                tests_passed=int(tests_passed_val),
                total_tests=int(total_tests_val),
                test_results=eval_result.get("test_results") or eval_result.get("test_cases", []),
                complexity_analysis=eval_result.get("complexity", ""),
                feedback=eval_result.get("feedback", ""),
                company_name=company,
                analysis_id=analysis_id
            )
            eval_result["submission_id"] = sub_id
        except Exception as sub_err:
            logger.warning(f"Failed to record coding submission: {sub_err}")

        return jsonify({
            "status": "success",
            "evaluation": eval_result,
            **eval_result
        }), 200

    except Exception as e:
        logger.error(f"Error evaluating candidate code: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Code evaluation failed: {str(e)}"
        }), 500


@coding_practice_bp.route("/coding-practice", methods=["GET", "POST"])
def coding_practice_view():
    """
    Personalized Coding Practice Recommendation View and Endpoint (#147).
    Recommends targeted LeetCode/DSA problems based on detected skill gaps, target companies, and difficulty.
    """
    target_company = request.args.get("company", "").strip()
    difficulty = request.args.get("difficulty", "All").strip()
    raw_skills = request.args.get("skills", "").strip()

    if request.method == "POST":
        target_company = request.form.get("company", "").strip()
        difficulty = request.form.get("difficulty", "All").strip()
        raw_skills = request.form.get("skills", "").strip()

    skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", raw_skills) if s.strip()]

    recommendations_data = coding_practice_agent.recommend_problems(
        skill_gaps=skill_gaps,
        target_company=target_company,
        difficulty_preference=difficulty,
        limit=8
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": recommendations_data
        }), 200

    return render_template(
        "coding_practice.html",
        data=recommendations_data,
        target_company=target_company,
        difficulty=difficulty,
        skills_input=raw_skills
    )


@coding_practice_bp.route("/api/coding-practice/recommendations")
def api_coding_practice_recommendations():
    """
    API endpoint returning tailored DSA practice problems for candidate placement prep (#147).
    """
    target_company = request.args.get("company", "").strip()
    difficulty = request.args.get("difficulty", "All").strip()
    raw_skills = request.args.get("skills", "").strip()
    skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", raw_skills) if s.strip()]

    recommendations_data = coding_practice_agent.recommend_problems(
        skill_gaps=skill_gaps,
        target_company=target_company,
        difficulty_preference=difficulty,
        limit=10
    )
    return jsonify({
        "success": True,
        "data": recommendations_data
    }), 200


@coding_practice_bp.route("/api/coding-practice/bookmarks", methods=["GET"])
def api_get_coding_bookmarks():
    """
    Returns the student's bookmarked coding questions (#234).
    """
    student_id = _get_current_student_id()
    bookmarks = get_coding_bookmarks(student_id)
    return jsonify({
        "success": True,
        "student_id": student_id,
        "count": len(bookmarks),
        "bookmarks": bookmarks
    }), 200


@coding_practice_bp.route("/api/coding-practice/bookmark", methods=["POST"])
def api_save_coding_bookmark():
    """
    Bookmarks a coding practice question for a candidate (#234).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = _get_current_student_id()
    problem_id = (payload.get("problem_id") or payload.get("id") or "").strip()

    if not problem_id:
        return jsonify({"success": False, "error": "Problem ID is required"}), 400

    problem_data = {
        "id": problem_id,
        "title": payload.get("title") or payload.get("problem_title") or "Coding Question",
        "difficulty": payload.get("difficulty") or payload.get("problem_difficulty") or "Medium",
        "topic": payload.get("topic") or payload.get("problem_topic") or "DSA",
        "platform": payload.get("platform") or payload.get("problem_platform") or "LeetCode",
        "practice_url": payload.get("practice_url") or payload.get("practice_link") or payload.get("url") or "#",
        "time_complexity": payload.get("time_complexity") or payload.get("problem_time") or "",
        "space_complexity": payload.get("space_complexity") or payload.get("problem_space") or "",
        "description": payload.get("description") or payload.get("problem_description") or "",
        "companies": payload.get("companies") or []
    }
    if isinstance(problem_data["companies"], str):
        problem_data["companies"] = [c.strip() for c in problem_data["companies"].split(",") if c.strip()]

    saved = save_coding_bookmark(student_id, problem_id, problem_data)
    return jsonify({
        "success": saved,
        "message": f"Problem '{problem_data['title']}' bookmarked successfully" if saved else "Failed to save bookmark",
        "problem": problem_data
    }), (200 if saved else 500)


@coding_practice_bp.route("/api/coding-practice/bookmark/<problem_id>", methods=["DELETE", "POST"])
def api_remove_coding_bookmark(problem_id: str):
    """
    Removes a bookmarked coding question for a candidate (#234).
    """
    student_id = _get_current_student_id()
    removed = remove_coding_bookmark(student_id, problem_id)
    return jsonify({
        "success": removed,
        "message": "Bookmark removed successfully" if removed else "Bookmark not found or already removed"
    }), 200


@coding_practice_bp.route("/api/coding-practice/bookmark/toggle", methods=["POST"])
def api_toggle_coding_bookmark():
    """
    Toggles bookmark state for a coding question (#234).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = _get_current_student_id()
    problem_id = (payload.get("problem_id") or payload.get("id") or "").strip()

    if not problem_id:
        return jsonify({"success": False, "error": "Problem ID is required"}), 400

    already_bookmarked = is_coding_bookmarked(student_id, problem_id)
    if already_bookmarked:
        remove_coding_bookmark(student_id, problem_id)
        return jsonify({
            "success": True,
            "bookmarked": False,
            "message": "Bookmark removed"
        }), 200
    else:
        problem_data = {
            "id": problem_id,
            "title": payload.get("title") or "Coding Question",
            "difficulty": payload.get("difficulty") or "Medium",
            "topic": payload.get("topic") or "DSA",
            "platform": payload.get("platform") or "LeetCode",
            "practice_url": payload.get("practice_url") or "#",
            "time_complexity": payload.get("time_complexity") or "",
            "space_complexity": payload.get("space_complexity") or "",
            "description": payload.get("description") or "",
            "companies": payload.get("companies") or []
        }
        if isinstance(problem_data["companies"], str):
            problem_data["companies"] = [c.strip() for c in problem_data["companies"].split(",") if c.strip()]
        saved = save_coding_bookmark(student_id, problem_id, problem_data)
        return jsonify({
            "success": saved,
            "bookmarked": True,
            "message": "Bookmark added"
        }), 200


@coding_practice_bp.route("/coding-submissions")
def coding_submissions_view():
    """
    Coding Assessment Submission History View (#194).
    Displays student previous attempts, question names, test results, and attempt-over-attempt improvements.
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"
    question_filter = request.args.get("question", "").strip()
    language_filter = request.args.get("language", "All").strip()
    status_filter = request.args.get("status", "All").strip()

    submissions = get_coding_submissions(
        student_id=student_id,
        question_title=question_filter or None,
        language_filter=language_filter,
        status_filter=status_filter
    )

    all_user_subs = get_coding_submissions(student_id=student_id)
    passed_count = sum(1 for s in all_user_subs if s.get("passed"))
    failed_count = len(all_user_subs) - passed_count
    avg_score = round(sum(s.get("score", 0) for s in all_user_subs) / len(all_user_subs), 1) if all_user_subs else 0.0

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "count": len(submissions),
            "submissions": submissions
        }), 200

    return render_template(
        "coding_submissions.html",
        submissions=submissions,
        student_id=student_id,
        question_filter=question_filter,
        language_filter=language_filter,
        status_filter=status_filter,
        total_count=len(all_user_subs),
        passed_count=passed_count,
        failed_count=failed_count,
        avg_score=avg_score
    )


@coding_practice_bp.route("/api/coding-submissions")
def api_coding_submissions():
    """
    API endpoint returning student coding attempts with comparison capability (#194).
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"
    question_filter = request.args.get("question", "").strip()
    submissions = get_coding_submissions(student_id=student_id, question_title=question_filter or None)

    return jsonify({
        "success": True,
        "count": len(submissions),
        "submissions": submissions
    }), 200


@coding_practice_bp.route("/api/coding-practice/bookmark-folders", methods=["GET", "POST"])
def coding_bookmark_folders_collection_endpoint():
    """
    GET: Lists all custom bookmark folders for the student, including counts and unassigned count.
    POST: Creates a new bookmark folder.
    """
    student_id = flask_session.get("user_id") or "default_student"

    if request.method == "GET":
        data = list_student_bookmark_folders(student_id)
        return jsonify({
            "status": "success",
            "data": data
        }), 200

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form.to_dict()
        folder_name = payload.get("name")
        if not folder_name or not folder_name.strip():
            return jsonify({"status": "error", "message": "Folder name is required."}), 400

        try:
            folder = create_bookmark_folder(
                student_id=student_id,
                name=folder_name,
                description=payload.get("description"),
                color_hex=payload.get("color_hex", "#3b82f6"),
                icon_name=payload.get("icon_name", "fa-folder")
            )
            return jsonify({
                "status": "success",
                "message": f"Folder '{folder_name}' created.",
                "folder": folder
            }), 201
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve)}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": f"Creation failed: {str(e)}"}), 500


@coding_practice_bp.route("/api/coding-practice/bookmark-folders/<folder_id>", methods=["GET", "PUT", "PATCH", "DELETE"])
def coding_bookmark_folder_detail_endpoint(folder_id: str):
    """
    GET: Retrieves folder metadata and bookmarked problems inside.
    PUT/PATCH: Updates folder name, description, color, or icon.
    DELETE: Deletes folder (optionally unassigns or deletes contents).
    """
    student_id = flask_session.get("user_id") or "default_student"
    folder = get_bookmark_folder_by_id(student_id, folder_id)
    if not folder:
        return jsonify({"status": "error", "message": f"Folder '{folder_id}' not found."}), 404

    if request.method == "GET":
        bookmarks = get_folder_bookmarks(student_id, folder_id)
        return jsonify({
            "status": "success",
            "folder": folder,
            "bookmarks": bookmarks,
            "count": len(bookmarks)
        }), 200

    if request.method in ("PUT", "PATCH"):
        payload = request.get_json(silent=True) or request.form.to_dict()
        try:
            updated = update_bookmark_folder(
                student_id=student_id,
                folder_id=folder_id,
                name=payload.get("name"),
                description=payload.get("description"),
                color_hex=payload.get("color_hex"),
                icon_name=payload.get("icon_name")
            )
            return jsonify({
                "status": "success",
                "message": "Folder updated successfully.",
                "folder": updated
            }), 200
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve)}), 400
        except Exception as e:
            return jsonify({"status": "error", "message": f"Update failed: {str(e)}"}), 500

    if request.method == "DELETE":
        delete_contents = request.args.get("delete_contents", "false").lower() == "true"
        deleted = delete_bookmark_folder(student_id, folder_id, delete_contents=delete_contents)
        return jsonify({
            "status": "success" if deleted else "error",
            "message": f"Folder '{folder['name']}' deleted."
        }), 200


@coding_practice_bp.route("/api/coding/bookmarks/<problem_id>/move", methods=["POST"])
def move_coding_bookmark_endpoint(problem_id: str):
    """
    Moves a bookmarked coding question to a target folder (or removes it to Uncategorized).
    """
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()
    target_folder_id = payload.get("target_folder_id") or payload.get("folder_id")

    try:
        moved = move_bookmark_to_folder(
            student_id=student_id,
            problem_id=problem_id,
            target_folder_id=target_folder_id
        )
        if not moved:
            return jsonify({"status": "error", "message": "Bookmark not found."}), 404
        return jsonify({
            "status": "success",
            "message": f"Bookmark '{problem_id}' moved successfully.",
            "target_folder_id": target_folder_id
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Move failed: {str(e)}"}), 500


# =====================================================================
# CODING SPACED REPETITION ROUTES (#509)
# =====================================================================

@coding_practice_bp.route("/coding-practice/spaced-repetition", methods=["GET"])
def coding_spaced_repetition_view():
    """Renders the student coding spaced-repetition review queue dashboard (#509)."""
    from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
    student_id = flask_session.get("user_id") or "default_student"

    due_problems = CodingSpacedRepetitionService.get_due_reviews(student_id)
    all_problems = CodingSpacedRepetitionService.get_all_enrolled(student_id)
    metrics = CodingSpacedRepetitionService.get_summary_metrics(student_id)

    return render_template(
        "coding_spaced_repetition.html",
        due_problems=due_problems,
        all_problems=all_problems,
        metrics=metrics
    )


@coding_practice_bp.route("/api/coding-practice/spaced-repetition/enroll", methods=["POST"])
def api_enroll_spaced_repetition():
    """Enrolls a coding problem into the student's spaced repetition schedule (#509)."""
    from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()

    problem_id = payload.get("problem_id")
    title = payload.get("title")
    if not problem_id or not title:
        return jsonify({"status": "error", "message": "problem_id and title are required"}), 400

    topic = payload.get("topic", "Data Structures")
    difficulty = payload.get("difficulty", "Medium")
    rating = payload.get("rating", "good")

    record = CodingSpacedRepetitionService.enroll_problem(
        user_id=student_id,
        problem_id=problem_id,
        title=title,
        topic=topic,
        difficulty=difficulty,
        initial_rating=rating
    )
    return jsonify({"status": "success", "record": record}), 201


@coding_practice_bp.route("/api/coding-practice/spaced-repetition/<problem_id>/review", methods=["POST"])
def api_record_spaced_repetition_review(problem_id):
    """Submits a performance review score for a scheduled coding problem (#509)."""
    from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form.to_dict()
    rating = payload.get("rating")
    if not rating:
        return jsonify({"status": "error", "message": "Rating is required"}), 400

    try:
        updated = CodingSpacedRepetitionService.record_review(student_id, problem_id, rating)
        return jsonify({"status": "success", "record": updated}), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@coding_practice_bp.route("/api/coding-practice/spaced-repetition/<problem_id>/pause", methods=["POST"])
def api_toggle_pause_spaced_repetition(problem_id):
    """Toggles active/paused status for an enrolled problem (#509)."""
    from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
    student_id = flask_session.get("user_id") or "default_student"
    try:
        updated = CodingSpacedRepetitionService.toggle_pause_schedule(student_id, problem_id)
        return jsonify({"status": "success", "record": updated}), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 404


@coding_practice_bp.route("/api/coding-practice/spaced-repetition/<problem_id>/reset", methods=["POST"])
def api_reset_spaced_repetition(problem_id):
    """Resets repetition level back to Day 1 interval (#509)."""
    from utils.coding_spaced_repetition_service import CodingSpacedRepetitionService
    student_id = flask_session.get("user_id") or "default_student"
    try:
        updated = CodingSpacedRepetitionService.reset_schedule(student_id, problem_id)
        return jsonify({"status": "success", "record": updated}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



