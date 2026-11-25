"""
Api feature area routes & endpoints (#553).
Handles shared/utility APIs including health checks, status, translations, and walkthroughs.
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

api_bp = Blueprint("api", __name__)

@api_bp.route("/healthz", methods=["GET"], endpoint="healthz")
@api_bp.route("/health", methods=["GET"], endpoint="health")
@api_bp.route("/api/health", methods=["GET"], endpoint="api_health")
def health_check():
    """
    Production-grade Kubernetes / Cloud liveness and readiness probe endpoint.
    Performs checks on:
    - SQLite database connectivity and query response time
    - Storage directories accessibility (uploads, reports)
    - Gemini API key configuration status
    """
    start_time = time.time()
    checks = {
        "database": {"status": "unknown"},
        "storage": {"status": "unknown"},
        "gemini_config": {"status": "unknown"},
    }
    all_healthy = True

    # 1. Database check
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["database"] = {"status": "healthy", "engine": "sqlite"}
    except Exception as db_err:
        all_healthy = False
        checks["database"] = {"status": "unhealthy", "error": str(db_err)}

    # 2. Storage write permissions
    try:
        uploads_ok = os.path.exists(config.UPLOAD_FOLDER) and os.access(config.UPLOAD_FOLDER, os.W_OK)
        reports_ok = os.path.exists(config.REPORT_FOLDER) and os.access(config.REPORT_FOLDER, os.W_OK)
        if uploads_ok and reports_ok:
            checks["storage"] = {"status": "healthy", "writable": True}
        else:
            all_healthy = False
            checks["storage"] = {
                "status": "unhealthy",
                "uploads_writable": uploads_ok,
                "reports_writable": reports_ok,
            }
    except Exception as st_err:
        all_healthy = False
        checks["storage"] = {"status": "unhealthy", "error": str(st_err)}

    # 3. Gemini API key presence
    api_key = config.GEMINI_API_KEY
    if api_key and api_key != "YOUR_GEMINI_API_KEY_HERE":
        checks["gemini_config"] = {"status": "configured"}
    else:
        checks["gemini_config"] = {"status": "unconfigured_or_placeholder"}

    latency_ms = round((time.time() - start_time) * 1000, 2)
    http_status = 200 if all_healthy else 503

    return jsonify({
        "status": "healthy" if all_healthy else "degraded",
        "service": "ai-campus-placement-agent",
        "latency_ms": latency_ms,
        "checks": checks,
    }), http_status


@api_bp.route("/status", methods=["GET"], endpoint="system_status_page")
def system_status_page():
    """
    Public Status Page for Application Services (#460).
    Displays real-time operational status of Application, Database, and AI Integration
    without exposing secrets, internal credentials, or tokens.
    Returns HTML status dashboard, or JSON if requested via Accept header / ?format=json.
    """
    from utils.status_service import get_system_status
    status_data, http_code = get_system_status()

    is_json = (
        request.args.get("format") == "json"
        or "application/json" in request.headers.get("Accept", "")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if is_json:
        return jsonify(status_data), http_code

    return render_template("status.html", status_data=status_data), http_code


@api_bp.route("/api/status", methods=["GET"], endpoint="api_system_status")
@api_bp.route("/api/v1/status", methods=["GET"], endpoint="api_v1_system_status")
@csrf.exempt
def api_system_status():
    """
    Public JSON status endpoint for application services (#460).
    Reports standardized operational status ('operational', 'degraded', 'unavailable')
    for Application, Database, and AI Integration without exposing secrets or credentials.
    """
    from utils.status_service import get_system_status
    status_data, http_code = get_system_status()
    return jsonify(status_data), http_code


@api_bp.route("/set-language/<lang_code>", methods=["GET"], endpoint="set_language")
def set_language(lang_code):
    """Set the active UI locale for the current session."""
    current_locale = flask_session.get("locale") or DEFAULT_LOCALE
    normalized = (lang_code or "").strip().lower()

    if normalized in SUPPORTED_LOCALES:
        flask_session["locale"] = normalized
    elif current_locale in SUPPORTED_LOCALES:
        flask_session["locale"] = current_locale
    else:
        flask_session["locale"] = DEFAULT_LOCALE

    flash(get_translation("lang_switch_success", locale=flask_session["locale"]), "success")
    return redirect(request.referrer or url_for("index"))


@api_bp.route("/api/validate/input", methods=["POST"])
def api_validate_input():
    """
    Central input validation testing and client pre-flight check endpoint (#276).
    """
    from utils.input_validator import (
        validate_registration_payload,
        validate_job_application_payload,
        validate_interview_answer_payload,
        ValidationError
    )
    payload = request.get_json(silent=True) or request.form
    target_type = payload.get("type", "registration")
    data = payload.get("data") or {}

    try:
        if target_type == "registration":
            validated = validate_registration_payload(data)
        elif target_type == "job_application":
            validated = validate_job_application_payload(data)
        elif target_type == "interview_answer":
            validated = validate_interview_answer_payload(data)
        else:
            return jsonify({"success": False, "error": f"Unknown validation schema type '{target_type}'."}), 400

        return jsonify({"success": True, "validated": validated}), 200
    except ValidationError as ve:
        return jsonify(ve.to_dict()), 422
    except Exception as e:
        logger.error(f"Error in input validation pre-flight: {e}")
        return jsonify({"success": False, "error": "Internal validation error."}), 500


@api_bp.route("/api/translations", methods=["GET"])
@api_bp.route("/api/translations/<locale>", methods=["GET"])
def api_translations(locale=None):
    """Return the translation catalog for the current or requested locale."""
    request_locale = (locale or flask_session.get("locale") or DEFAULT_LOCALE).strip().lower()
    if request_locale not in SUPPORTED_LOCALES:
        request_locale = flask_session.get("locale") or DEFAULT_LOCALE
    if request_locale not in SUPPORTED_LOCALES:
        request_locale = DEFAULT_LOCALE

    flask_session["locale"] = request_locale
    return jsonify({
        "status": "success",
        "locale": request_locale,
        "default_locale": DEFAULT_LOCALE,
        "supported_locales": SUPPORTED_LOCALES,
        "translations": get_all_translations_for_locale(request_locale),
    })


@api_bp.route("/api/migrations/status", methods=["GET"])
def api_migrations_status():
    """Return the current migration status for the configured database."""
    migration_info = get_migration_status(db_path=config.DATABASE_PATH)
    return jsonify({
        "status": "success",
        "database_path": config.DATABASE_PATH,
        "migration_info": migration_info,
    })


@api_bp.route("/api/migrations/run", methods=["POST"])
def api_migrations_run():
    """Execute all pending migrations against the configured database."""
    try:
        result = run_database_migrations(db_path=config.DATABASE_PATH)
        return jsonify({
            "status": "success",
            "message": "Database migrations processed successfully.",
            **result,
        })
    except Exception as exc:
        logger.exception("Database migration run failed")
        return jsonify({
            "status": "error",
            "message": "Database migration execution failed.",
            "error": str(exc),
        }), 500


@api_bp.route("/api/walkthrough", methods=["GET"])
def api_walkthrough():
    """
    Returns structured walkthrough steps introducing the core application areas (#350).
    Allows first-time and returning users to learn about Resume Analysis, Interview Practice,
    Preparation Plans, and Application Tracking.
    """
    dismissed = bool(flask_session.get("walkthrough_dismissed", False))
    return jsonify({
        "success": True,
        "dismissed": dismissed,
        "recommended_next_step": {
            "feature": "resume_analysis",
            "title": "Start with Resume Analysis",
            "description": "Upload your resume in the Workspace to evaluate your ATS score and skill gaps.",
            "action_url": "/#analysisForm",
            "action_text": "Upload Resume"
        },
        "total_steps": len(WALKTHROUGH_STEPS_CATALOG),
        "steps": WALKTHROUGH_STEPS_CATALOG
    }), 200


@api_bp.route("/api/walkthrough/dismiss", methods=["POST"])
@csrf.exempt
def api_walkthrough_dismiss():
    """Marks the walkthrough as dismissed in the user session (#350)."""
    flask_session["walkthrough_dismissed"] = True
    return jsonify({
        "success": True,
        "dismissed": True,
        "message": "Walkthrough dismissed successfully."
    }), 200


@api_bp.route("/api/walkthrough/reset", methods=["POST"])
@csrf.exempt
def api_walkthrough_reset():
    """Resets the walkthrough dismissal state to re-enable it for the user (#350)."""
    flask_session["walkthrough_dismissed"] = False
    return jsonify({
        "success": True,
        "dismissed": False,
        "message": "Walkthrough reset successfully."
    }), 200


@api_bp.route("/api/openapi.json", methods=["GET"])
def openapi_json():
    """Returns the complete OpenAPI 3.0.3 specification JSON for API endpoints (#410)."""
    from utils.openapi_spec import get_openapi_spec
    return jsonify(get_openapi_spec()), 200


@api_bp.route("/docs", methods=["GET"])
@api_bp.route("/api/docs", methods=["GET"])
def api_docs_ui():
    """Renders interactive Swagger UI for API exploration and testing (#410)."""
    return render_template("swagger_ui.html")


@api_bp.route("/redoc", methods=["GET"])
def api_redoc_ui():
    """Renders Redoc three-column API documentation reference viewer (#410)."""
    return render_template("redoc.html")


@api_bp.route("/api/ai/disclaimer", methods=["GET"])
def api_get_ai_disclaimer():
    """
    Returns standardized AI disclaimer text and HTML banners for
    front-end modules (resume reviews, interview feedback, etc.).
    """
    from utils.ai_disclaimer_service import ai_disclaimer_service

    category = request.args.get("category", "general_ai")
    data = ai_disclaimer_service.get_disclaimer_data(category)
    banner_html = ai_disclaimer_service.render_banner_html(category)
    footnote_html = ai_disclaimer_service.render_footnote_html(category)

    return jsonify({
        "success": True,
        "disclaimer": data,
        "banner_html": banner_html,
        "footnote_html": footnote_html
    }), 200


# =====================================================================
# PUBLIC APPLICATION STATUS & MAINTENANCE ROUTES (#524)
# =====================================================================

@api_bp.route("/system-status", methods=["GET"])
def public_system_status_view():
    """Renders the comprehensive public system health and scheduled maintenance page (#524)."""
    from utils.system_status_service import PublicStatusService
    from flask import render_template

    status_data = PublicStatusService.get_public_system_status()
    return render_template("public_status.html", status_data=status_data)


@api_bp.route("/api/system-status/public", methods=["GET"])
def api_public_system_status_probe():
    """Public JSON status probe for uptime monitors and health checks (#524)."""
    from utils.system_status_service import PublicStatusService

    status_data = PublicStatusService.get_public_system_status()
    http_code = 200 if status_data["overall_status"] in ["operational", "maintenance"] else 503
    return jsonify(status_data), http_code



@api_bp.route("/api/admin/status/incident", methods=["POST"])
def api_admin_log_incident():
    """Logs a maintenance advisory or incident (admin gated) (#524)."""
    from utils.system_status_service import PublicStatusService
    if flask_session.get("user_role") not in ["admin", "coordinator"] and flask_session.get("is_admin") is not True:
        if flask_session.get("user_id") != "admin_user":
            return jsonify({"status": "error", "message": "Admin authorization required."}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    title = payload.get("title")
    message = payload.get("message")
    if not title or not message:
        return jsonify({"status": "error", "message": "title and message are required"}), 400

    result = PublicStatusService.log_incident(
        title=title,
        subsystem=payload.get("subsystem", "web"),
        severity=payload.get("severity", "maintenance"),
        message=message,
        scheduled_start=payload.get("scheduled_start"),
        scheduled_end=payload.get("scheduled_end")
    )
    return jsonify({"status": "success", "incident": result}), 201


@api_bp.route("/api/admin/status/incident/<int:incident_id>/resolve", methods=["POST"])
def api_admin_resolve_incident(incident_id):
    """Marks an active incident as resolved (#524)."""
    from utils.system_status_service import PublicStatusService
    if flask_session.get("user_role") not in ["admin", "coordinator"] and flask_session.get("is_admin") is not True:
        if flask_session.get("user_id") != "admin_user":
            return jsonify({"status": "error", "message": "Admin authorization required."}), 403

    resolved = PublicStatusService.resolve_incident(incident_id)
    return jsonify({"status": "success", "resolved": resolved}), 200


# ==============================================================================
# API Request Replay & Failed Operation Routes
# ==============================================================================

@api_bp.route("/api/retry-records", methods=["GET"], endpoint="api_get_retry_records")
def api_get_retry_records():
    """Returns list of active retry records for the current user."""
    from utils.api_replay_service import list_retry_records
    user_id = flask_session.get("user_id") or "default_student"
    include_expired = request.args.get("include_expired", "").lower() in ("true", "1")
    records = list_retry_records(user_id=user_id, include_expired=include_expired)
    return jsonify({"success": True, "records": records}), 200


@api_bp.route("/api/retry-records", methods=["POST"], endpoint="api_create_retry_record")
def api_create_retry_record():
    """Stores a safe retry record for a failed API operation."""
    from utils.api_replay_service import store_retry_record
    user_id = flask_session.get("user_id") or "default_student"
    data = request.get_json(silent=True) or request.form.to_dict() or {}

    operation_type = data.get("operation_type") or "api_operation"
    endpoint = data.get("endpoint")
    if not endpoint:
        return jsonify({"success": False, "error": "Missing required 'endpoint' field."}), 400

    http_method = (data.get("http_method") or "POST").upper()
    payload = data.get("payload") or {}
    error_message = data.get("error_message") or "Operation failed."
    idempotency_key = data.get("idempotency_key")
    ttl_seconds = int(data.get("ttl_seconds") or 900)

    record = store_retry_record(
        user_id=user_id,
        operation_type=operation_type,
        endpoint=endpoint,
        http_method=http_method,
        payload=payload,
        error_message=error_message,
        idempotency_key=idempotency_key,
        ttl_seconds=ttl_seconds,
    )
    return jsonify({"success": True, "record": record}), 201


@api_bp.route("/api/retry-records/<record_id>", methods=["GET"], endpoint="api_get_retry_record_item")
def api_get_retry_record_item(record_id: str):
    """Fetches details and current status of a specific retry record."""
    from utils.api_replay_service import get_retry_record
    user_id = flask_session.get("user_id") or "default_student"
    record = get_retry_record(record_id, user_id=user_id)
    if not record:
        return jsonify({"success": False, "error": "Retry record not found."}), 404
    return jsonify({"success": True, "record": record}), 200


@api_bp.route("/api/retry-records/<record_id>/replay", methods=["POST"], endpoint="api_replay_retry_record")
def api_replay_retry_record(record_id: str):
    """
    Replays a failed operation safely, preventing duplicate submissions,
    enforcing expiration, and recording the outcome.
    """
    from utils.api_replay_service import begin_replay, complete_replay, get_retry_record
    user_id = flask_session.get("user_id") or "default_student"

    can_replay, err, rec = begin_replay(record_id, user_id=user_id)
    if not can_replay:
        # Determine status code based on rejection reason
        err_str = (err or "").lower()
        if "replayed" in err_str:
            status_code = 409
        elif "expired" in err_str:
            status_code = 410
        elif "attempts" in err_str:
            status_code = 429
        else:
            status_code = 400

        current_rec = get_retry_record(record_id, user_id=user_id)
        return jsonify({
            "success": False,
            "error": err,
            "status": current_rec.get("status") if current_rec else "error",
            "record": current_rec,
        }), status_code

    endpoint = rec["endpoint"]
    method = rec["http_method"]
    payload = rec.get("payload") or {}

    try:
        with current_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user_id
                sess["user_name"] = flask_session.get("user_name") or user_id

            headers = {"Content-Type": "application/json"}
            if method == "POST":
                resp = client.post(endpoint, json=payload, headers=headers)
            elif method == "PUT":
                resp = client.put(endpoint, json=payload, headers=headers)
            elif method == "DELETE":
                resp = client.delete(endpoint, json=payload, headers=headers)
            else:
                resp = client.get(endpoint, headers=headers)

            is_ok = 200 <= resp.status_code < 300
            try:
                resp_data = resp.get_json()
            except Exception:
                resp_data = {
                    "status_code": resp.status_code,
                    "text": resp.data.decode("utf-8", errors="ignore")[:500],
                }

            if is_ok:
                updated_rec = complete_replay(record_id, success=True, result_payload=resp_data)
                return jsonify({
                    "success": True,
                    "status": "succeeded",
                    "message": "Operation successfully replayed.",
                    "result": resp_data,
                    "record": updated_rec,
                }), 200
            else:
                err_msg = "Replay execution returned error."
                if isinstance(resp_data, dict):
                    err_msg = resp_data.get("error") or resp_data.get("message") or f"HTTP {resp.status_code}"
                updated_rec = complete_replay(record_id, success=False, error_message=err_msg, result_payload=resp_data)
                return jsonify({
                    "success": False,
                    "status": updated_rec["status"],
                    "error": f"Replay failed: {err_msg}",
                    "result": resp_data,
                    "record": updated_rec,
                }), 502

    except Exception as exc:
        logger.exception(f"Exception during replay execution for record {record_id}: {exc}")
        updated_rec = complete_replay(record_id, success=False, error_message=str(exc))
        return jsonify({
            "success": False,
            "status": updated_rec["status"],
            "error": f"Internal replay execution error: {str(exc)}",
            "record": updated_rec,
        }), 500


@api_bp.route("/api/retry-records/<record_id>", methods=["DELETE"], endpoint="api_cancel_retry_record")
def api_cancel_retry_record(record_id: str):
    """Cancels/dismisses an active retry record."""
    from utils.api_replay_service import cancel_retry_record
    user_id = flask_session.get("user_id") or "default_student"
    cancelled = cancel_retry_record(record_id, user_id=user_id)
    if cancelled:
        return jsonify({"success": True, "message": "Retry record dismissed."}), 200
    return jsonify({"success": False, "error": "Record not found or not cancellable."}), 404




