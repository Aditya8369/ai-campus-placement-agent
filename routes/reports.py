"""
Reports feature area routes & endpoints (#553).
Handles report generation, PDF exports, certificates, watermarking, and report sharing.
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

reports_bp = Blueprint("reports", __name__)

@reports_bp.route("/certificate/<analysis_id>")
def certificate(analysis_id: str):
    """
    Renders printable placement readiness completion certificate.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
            flash("The requested placement analysis report could not be found.", "error")
            return redirect(url_for("index"))

    return render_template(
        "certificate.html",
        analysis=analysis_record,
        analysis_id=analysis_id,
    )


@reports_bp.route("/certificate/<analysis_id>/download")
def download_certificate_pdf(analysis_id: str):
    """
    Generates and serves a downloadable, formal placement readiness completion certificate in PDF format.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            flash("Cannot generate certificate. Placement record not found.", "error")
            return redirect(url_for("index"))

        cert_filename = f"Placement_Certificate_{analysis_id}.pdf"
        cert_path = os.path.join(config.REPORT_FOLDER, cert_filename)

        if not os.path.exists(cert_path):
            safe_generate_report_with_recovery(
                generator_func=generate_certificate_pdf,
                data=analysis_record,
                output_path=cert_path,
                report_type="Placement Readiness Certificate"
            )

        company_clean = secure_filename(analysis_record.get("company_name", "General"))
        return send_file(
            cert_path,
            as_attachment=True,
            download_name=f"Placement_Certificate_{company_clean}.pdf",
            mimetype="application/pdf",
        )
    except Exception as exc:
        logger.error(f"Error serving certificate PDF for {analysis_id}: {exc}")
        flash("Failed to generate certificate PDF. Please try printing directly.", "error")
        return redirect(url_for("certificate", analysis_id=analysis_id))


@reports_bp.route("/download/<analysis_id>")
def download_pdf_report(analysis_id: str):
    """
    Compiles placement metrics into a ReportLab PDF and downloads the file.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            flash("Cannot generate PDF. Placement record not found.", "error")
            return redirect(url_for("index"))

        output_language, used_language_fallback = resolve_output_locale(
            get_email_notification_preferences(
                flask_session.get("user_id") or analysis_record.get("student_id")
            ).get("output_language", DEFAULT_OUTPUT_LOCALE)
        )
        if used_language_fallback:
            flash("This report is only available in English for the selected language.", "warning")

        # Check if file has already been generated
        pdf_output_name = f"Placement_Report_{analysis_id}_{output_language}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            safe_generate_report_with_recovery(
                generator_func=generate_pdf_report,
                data=analysis_record,
                output_path=pdf_full_path,
                report_type="Placement Readiness Comprehensive Report",
                language=output_language,
            )

        return send_file(
            pdf_full_path,
            as_attachment=True,
            download_name=f"Placement_Readiness_Report_{analysis_record['company_name']}_{output_language}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        logger.error(f"Failed to generate and serve PDF report: {str(e)}")
        flash(f"Error compiling report file: {str(e)}", "error")
        return redirect(url_for("dashboard", analysis_id=analysis_id))


@reports_bp.route("/download/skills-gap/<analysis_id>")
def download_skills_gap_report(analysis_id: str):
    """
    Compiles identified candidate skill gaps and upskilling roadmaps into a standalone PDF report (#136).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record:
            flash("Cannot generate Skills Gap report. Placement record not found.", "error")
            return redirect(url_for("index"))

        output_language, used_language_fallback = resolve_output_locale(
            get_email_notification_preferences(
                flask_session.get("user_id") or analysis_record.get("student_id")
            ).get("output_language", DEFAULT_OUTPUT_LOCALE)
        )
        if used_language_fallback:
            flash("This report is only available in English for the selected language.", "warning")

        pdf_output_name = f"Skills_Gap_Report_{analysis_id}_{output_language}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            safe_generate_report_with_recovery(
                generator_func=generate_skills_gap_pdf,
                data=analysis_record,
                output_path=pdf_full_path,
                report_type="Skills Gap and Upskilling Roadmap",
                language=output_language,
            )

        company = analysis_record.get("company_name", "Target_Company").replace(" ", "_")
        return send_file(
            pdf_full_path,
            as_attachment=True,
            download_name=f"Skills_Gap_Report_{company}.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        logger.error(f"Failed to generate and serve Skills Gap report: {str(e)}")
        flash(f"Error compiling skills gap report: {str(e)}", "error")
        return redirect(url_for("dashboard", analysis_id=analysis_id))


@reports_bp.route("/api/generate-outreach/<analysis_id>", methods=["POST"])
@rate_limit(scope="generate_outreach", is_api=True)
def api_generate_outreach(analysis_id: str):
    """
    Generates tailored application outreach assets (formal cover letter, LinkedIn InMail,
    cold recruiter email, subject lines, key highlights) for a given analysis ID.
    Supports tone selection ('formal', 'enthusiastic', 'concise') and custom role title.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            return jsonify({
                "success": False,
                "error": "Analysis not found."
    }), 404

        payload = request.get_json(silent=True) or {}
        tone = payload.get("tone") or request.form.get("tone", "formal")
        role_title = payload.get("role_title") or request.form.get("role_title", "")

        outreach_data = outreach_agent.generate_outreach(
            analysis_record=analysis_record,
            tone=tone,
            role_title=role_title
        )

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "tone": outreach_data.get("tone", tone),
            "role_title": outreach_data.get("role_title", role_title),
            "outreach": outreach_data
        }), 200

    except Exception as e:
        logger.error(f"Error generating outreach for {analysis_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Failed to generate outreach materials: {str(e)}"
        }), 500


@reports_bp.route("/api/outreach/download", methods=["POST"])
@reports_bp.route("/api/outreach/<analysis_id>/download", methods=["GET", "POST"])
def api_download_outreach(analysis_id: str = None):
    """
    Downloads generated application outreach assets as formatted .docx or plain .txt files.
    Can accept pre-generated outreach data in POST body or dynamically generate for an analysis_id.
    """
    try:
        payload = (request.get_json(silent=True) or {}) if request.method == "POST" else {}
        aid = analysis_id or payload.get("analysis_id") or request.args.get("analysis_id")
        file_format = (payload.get("format") or request.args.get("format") or "docx").strip().lower()
        tone = (payload.get("tone") or request.args.get("tone") or "formal").strip().lower()
        role_title = payload.get("role_title") or request.args.get("role_title", "")
        candidate_name = payload.get("candidate_name") or request.args.get("candidate_name", "Candidate")
        content_type = (payload.get("content_type") or request.args.get("type") or "all").strip().lower()
        custom_content = payload.get("content")

        analysis_record = get_analysis(aid) if aid else None
        if aid and (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "success": False,
                "error": "Analysis not found."
            }), 404
        company_name = (
            payload.get("company_name")
            or (analysis_record.get("company_name") if analysis_record else None)
            or request.args.get("company_name")
            or "Target_Company"
        )

        # If client passed complete outreach_data, use it; otherwise generate
        outreach_data = payload.get("outreach") or payload.get("outreach_data")
        if not outreach_data and analysis_record:
            outreach_data = outreach_agent.generate_outreach(
                analysis_record=analysis_record,
                tone=tone,
                role_title=role_title
            )
        elif not outreach_data and not analysis_record:
            if not custom_content:
                return jsonify({"success": False, "error": "Analysis record or outreach content required."}), 404
            outreach_data = {
                "tone": tone,
                "role_title": role_title or "Software Engineer",
                "company_name": company_name,
                "cover_letter": custom_content,
                "linkedin_inmail": custom_content,
                "cold_email": custom_content,
                "subject_lines": [],
                "key_highlights": []
            }

        safe_company = "".join(c for c in company_name if c.isalnum() or c in ("-", "_")) or "Company"
        safe_name = "".join(c for c in candidate_name if c.isalnum() or c in ("-", "_")) or "Candidate"

        if file_format == "txt":
            if custom_content and content_type != "all":
                txt_data = custom_content
                filename = f"{safe_name}_{safe_company}_{content_type}.txt"
            else:
                txt_data = outreach_agent.export_to_txt(
                    outreach_data=outreach_data,
                    candidate_name=safe_name,
                    company_name=safe_company
                )
                filename = f"{safe_name}_{safe_company}_Outreach_Portfolio.txt"

            return Response(
                txt_data,
                mimetype="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{filename}\""
                }
            )

        # Default to DOCX
        docx_bytes = outreach_agent.export_to_docx(
            outreach_data=outreach_data,
            candidate_name=safe_name,
            company_name=safe_company
        )
        filename = f"{safe_name}_{safe_company}_Outreach_Portfolio.docx"
        return send_file(
            io.BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"Error serving outreach download: {str(e)}")
        return jsonify({"success": False, "error": f"Failed to download outreach: {str(e)}"}), 500


@reports_bp.route("/report/<analysis_id>")
def view_html_report(analysis_id: str):
    """Renders an accessible, responsive HTML version of the placement report."""
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        flash("The requested placement analysis report could not be found.", "error")
        return redirect(url_for("index"))

    return render_template(
        "placement_report.html",
        report_data=sanitize_report_data(analysis_record),
    )


@reports_bp.route("/download/preparation-summary", methods=["GET"])
@reports_bp.route("/download/preparation-summary/<student_id>", methods=["GET"])
def download_student_preparation_summary_pdf(student_id: str = None):
    """
    Generates and downloads a comprehensive Placement Preparation Summary PDF report (#200).
    Ensures candidate data isolation so students only access their own report.
    """
    session_user_id = flask_session.get("user_id") or flask_session.get("user", {}).get("id") or flask_session.get("student_id")
    if not student_id:
        student_id = session_user_id or "default_student"
    elif session_user_id and session_user_id != "default_student" and student_id != session_user_id:
        # Enforce student isolation
        flash("Unauthorized access to student preparation summary.", "danger")
        return redirect(url_for("index"))

    summary_data = get_student_preparation_summary_data(student_id)
    output_language, used_language_fallback = resolve_output_locale(
        get_email_notification_preferences(student_id).get("output_language", DEFAULT_OUTPUT_LOCALE)
    )
    if used_language_fallback:
        flash("This report is only available in English for the selected language.", "warning")
    output_filename = f"Placement_Preparation_Summary_{student_id}_{output_language}.pdf"
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_pdf_path = tmp.name

    try:
        safe_generate_report_with_recovery(
            generator_func=generate_student_preparation_summary_pdf,
            data=summary_data,
            output_path=temp_pdf_path,
            report_type="Student Placement Preparation Summary",
            language=output_language,
        )
        return send_file(
            temp_pdf_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype="application/pdf"
        )
    except Exception as e:
        logger.error(f"Failed to generate student preparation summary PDF: {e}")
        flash("Could not generate preparation summary report. Please try again later.", "danger")
        return redirect(url_for("index"))


@reports_bp.route("/api/reports/share", methods=["POST"])
def api_reports_share_create():
    """
    Creates an expiring, secure read-only report sharing link (#408, #468).
    """
    from utils.shared_reports_service import create_shared_report_link
    student_id = flask_session.get("user_id") or "default_student"
    payload = request.get_json(silent=True) or request.form or {}

    analysis_id = payload.get("analysis_id")
    expiration = payload.get("expiration", "24h")

    if not analysis_id:
        return jsonify({"success": False, "error": "analysis_id is required."}), 400

    try:
        res = create_shared_report_link(analysis_id, student_id, expiration)
        return jsonify(res), 201
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except KeyError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating share link: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@reports_bp.route("/api/reports/share/<share_id>/revoke", methods=["POST"])
def api_reports_share_revoke(share_id):
    """
    Revokes an active report share link immediately (#408, #468).
    Only the owner who created the link can revoke it.
    """
    from utils.shared_reports_service import revoke_shared_link
    student_id = flask_session.get("user_id") or "default_student"
    try:
        success = revoke_shared_link(student_id, share_id)
        if success:
            return jsonify({"success": True, "message": "Share link revoked successfully."}), 200
        return jsonify({"success": False, "error": "Share link not found or already revoked."}), 404
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except Exception as e:
        logger.error(f"Error revoking share link: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@reports_bp.route("/api/reports/<analysis_id>/shares", methods=["GET"])
@reports_bp.route("/api/reports/shares", methods=["GET"])
def api_reports_share_list(analysis_id=None):
    """
    Lists share links generated by the current student for this analysis (#468).
    Includes view count and last viewed timestamp.
    """
    from utils.shared_reports_service import list_user_active_shares
    student_id = flask_session.get("user_id") or "default_student"
    try:
        shares = list_user_active_shares(student_id, analysis_id=analysis_id)
        return jsonify({"success": True, "shares": shares}), 200
    except Exception as e:
        logger.error(f"Error listing share links: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@reports_bp.route("/shared/report/<token>", methods=["GET"])
def view_shared_report(token):
    """
    Renders read-only placement report for a shared token (#408, #468).
    Sends noindex headers and requires no authentication.
    """
    from utils.shared_reports_service import get_shared_report_by_token
    valid, report, err = get_shared_report_by_token(token)
    if not valid:
        resp = make_response(render_template("shared_report_error.html", error_message=err), 404)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return resp
    resp = make_response(render_template("shared_report_view.html", report=report))
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


@reports_bp.route("/api/reports/watermark", methods=["POST"])
def api_apply_report_watermark():
    """
    Applies or previews a security watermark on reports and documents.
    Supports both HTML and plain-text report formats.
    """
    from utils.report_watermark_service import report_watermark_service

    data = request.get_json(silent=True) or request.form
    content = data.get("content", "")
    content_format = data.get("format", "html").lower()
    doc_type = data.get("document_type", "Placement Preparation Report")
    custom_notice = data.get("custom_notice")
    student_id = data.get("student_id") or flask_session.get("user_id") or "STUDENT"
    include_banner = data.get("include_banner", True)

    if not content:
        return jsonify({"success": False, "error": "content is required"}), 400

    if content_format == "html":
        watermarked = report_watermark_service.apply_watermark_to_html(
            html_content=content,
            student_id=student_id,
            document_type=doc_type,
            custom_text=custom_notice,
            include_banner=bool(include_banner)
        )
    else:
        watermarked = report_watermark_service.apply_watermark_to_plain_text(
            text_content=content,
            student_id=student_id,
            document_type=doc_type,
            custom_text=custom_notice
        )

    metadata = report_watermark_service.generate_watermark_metadata(
        student_id=student_id,
        document_type=doc_type,
        custom_text=custom_notice
    )

    return jsonify({
        "success": True,
        "format": content_format,
        "watermarked_content": watermarked,
        "metadata": metadata
    }), 200


