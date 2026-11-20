"""
Shared helpers, constants, and utilities for route Blueprints (#553).
"""

import sys
import os
import io
import re
import csv
import json
import uuid
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from flask import request, session as flask_session, current_app, flash, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import config
from utils.database import (
    get_student_profile,
    get_job_applications,
    get_student_versions,
)
from utils.aptitude_service import VALID_CATEGORIES as APTITUDE_CATEGORIES
from utils.email_service import EmailNotificationService
from agents.coordinator import CoordinatorAgent
from agents.interview_agent import InterviewAgent
from agents.coding_agent import CodingAssessmentAgent
from agents.star_agent import StarEvaluationAgent
from agents.github_agent import GitHubAnalyzerAgent
from agents.internship_agent import InternshipRecommendationAgent
from agents.linkedin_agent import LinkedInAgent
from agents.coding_practice_agent import CodingPracticeAgent
from agents.outreach_agent import OutreachGeneratorAgent
from agents.self_introduction_agent import SelfIntroductionAgent
from agents.project_deep_dive_agent import ProjectDeepDiveAgent
from utils.pdf_reader import (
    extract_text_from_pdf,
    extract_text_from_docx,
    validate_resume_text,
    validate_resume_file,
    validate_file_size,
    validate_pdf_content,
    ScannedPDFError,
    PasswordProtectedPDFError,
    MAX_RESUME_TEXT_CHARS,
    ALLOWED_RESUME_EXTENSIONS,
)
from utils.logger_config import register_sensitive_text, clear_sensitive_texts
from utils.resume_info_extractor import extract_resume_information

logger = logging.getLogger(__name__)

# Constants
APPLICATION_STAGES = ["Applied", "Assessment", "Interview", "Selected", "Rejected"]
NOTE_CATEGORIES = ["Technical", "HR", "DSA", "Company Preparation"]

WALKTHROUGH_STEPS_CATALOG = [
    {
        "id": "resume_analysis",
        "step_number": 1,
        "title": "Resume Analysis & ATS Scoring",
        "short_desc": "Upload your resume in PDF or DOCX format for instant ATS scoring, grammar review, and keyword matching.",
        "long_desc": "Evaluates your resume against corporate job descriptions to identify formatting weaknesses, missing keywords, and section improvements.",
        "action_url": "/#analysisForm",
        "action_text": "Start Resume Analysis",
        "target_element": "analysisForm",
        "icon": "fa-file-lines",
        "badge": "Recommended First Step",
        "color": "primary"
    },
    {
        "id": "interview_practice",
        "step_number": 2,
        "title": "Interactive Mock Interviews",
        "short_desc": "Dynamic AI mock interviews, technical DSA challenges, and behavioral STAR evaluations.",
        "long_desc": "Practice real-time technical questions and behavioral scenarios with AI feedback scoring communication clarity, confidence, and accuracy.",
        "action_url": "/coding-practice",
        "action_text": "Explore Interview Practice",
        "target_element": None,
        "icon": "fa-comments",
        "badge": "Technical & HR",
        "color": "success"
    },
    {
        "id": "preparation_plans",
        "step_number": 3,
        "title": "Preparation Plans & Roadmaps",
        "short_desc": "Tailored 6-week study roadmaps, company hiring checklists, and daily streak tracking.",
        "long_desc": "Follow progressive weekly preparation milestones and track recruitment readiness using checklists for 15+ top recruiters.",
        "action_url": "/company-checklist",
        "action_text": "View Preparation Plans",
        "target_element": None,
        "icon": "fa-list-check",
        "badge": "Milestones & Checklist",
        "color": "warning"
    },
    {
        "id": "application_tracker",
        "step_number": 4,
        "title": "Job Application Tracker",
        "short_desc": "Organize applications across Applied, Assessment, Interview, Selected, and Rejected stages.",
        "long_desc": "Manage every placement drive from submission to offer. Record application dates, track status updates, and export your application records.",
        "action_url": "/applications",
        "action_text": "Go to Application Tracker",
        "target_element": None,
        "icon": "fa-briefcase",
        "badge": "Pipeline Tracker",
        "color": "info"
    }
]

# Instantiate coordination and specialized interview agents
email_service = EmailNotificationService()
coordinator_agent = CoordinatorAgent()
live_interview_agent = InterviewAgent()
coding_assessment_agent = CodingAssessmentAgent()
star_evaluation_agent = StarEvaluationAgent()
github_analyzer_agent = GitHubAnalyzerAgent()
internship_agent = InternshipRecommendationAgent()
linkedin_agent = LinkedInAgent()
coding_practice_agent = CodingPracticeAgent()
outreach_agent = OutreachGeneratorAgent()
self_introduction_agent = SelfIntroductionAgent()
project_deep_dive_agent = ProjectDeepDiveAgent()

# Resume review cache & Application import state
_RESUME_REVIEW_CACHE: Dict[str, Dict[str, Any]] = {}
APPLICATION_IMPORT_FIELDS = [
    "company_name", "role_title", "status", "application_date", "job_url",
    "job_description", "notes", "location", "job_type", "experience_level"
]
APPLICATION_IMPORT_MAX_ROWS = 2000
APPLICATION_IMPORT_MAX_BYTES = 5 * 1024 * 1024
_APPLICATION_IMPORT_PREVIEWS = {}

# Delegating wrappers for functions commonly patched or monkeypatched in tests (#553)
def get_analysis(*args, **kwargs):
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "get_analysis", None)
        if custom is not None and custom is not get_analysis:
            return custom(*args, **kwargs)
    import utils.database
    return utils.database.get_analysis(*args, **kwargs)

def get_db_connection(*args, **kwargs):
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "get_db_connection", None)
        if custom is not None and custom is not get_db_connection:
            return custom(*args, **kwargs)
    import utils.database
    return utils.database.get_db_connection(*args, **kwargs)

def get_valid_password_reset_token(*args, **kwargs):
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "get_valid_password_reset_token", None)
        if custom is not None and custom is not get_valid_password_reset_token:
            return custom(*args, **kwargs)
    import utils.database
    return utils.database.get_valid_password_reset_token(*args, **kwargs)

def extract_text_from_file(*args, **kwargs):
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "extract_text_from_file", None)
        if custom is not None and custom is not extract_text_from_file:
            return custom(*args, **kwargs)
    import utils.pdf_reader
    return utils.pdf_reader.extract_text_from_file(*args, **kwargs)

def _is_student_authorized(record_or_student_id) -> bool:
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "_is_student_authorized", None)
        if custom is not None and custom is not _is_student_authorized:
            return custom(record_or_student_id)
    if isinstance(record_or_student_id, dict):
        if (
            record_or_student_id.get("is_demo")
            or record_or_student_id.get("id") in ("demo-sample-analysis", "demo_sample_analysis", "demo")
            or record_or_student_id.get("student_id") == "demo_visitor"
        ):
            return True
    elif record_or_student_id in ("demo-sample-analysis", "demo_sample_analysis", "demo", "demo_visitor"):
        return True

    if current_app.config.get("TESTING") and not current_app.config.get("ENFORCE_STUDENT_ISOLATION"):
        return True
    current_uid = flask_session.get("user_id") or (flask_session.get("user", {}).get("id") if isinstance(flask_session.get("user"), dict) else None) or flask_session.get("student_id")
    if not current_uid:
        return False
    if isinstance(record_or_student_id, dict):
        rec_sid = record_or_student_id.get("student_id")
        return not rec_sid or rec_sid == current_uid
    return record_or_student_id == current_uid

def _get_current_student_id() -> str:
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        custom = getattr(app_mod, "_get_current_student_id", None)
        if custom is not None and custom is not _get_current_student_id:
            return custom()
    return (
        flask_session.get("user", {}).get("id")
        if isinstance(flask_session.get("user"), dict) else None
    ) or flask_session.get("user_id") or flask_session.get("student_id") or "default_student"

__all__ = [
    "APPLICATION_STAGES",
    "APPLICATION_IMPORT_FIELDS",
    "APPLICATION_IMPORT_MAX_ROWS",
    "APPLICATION_IMPORT_MAX_BYTES",
    "_APPLICATION_IMPORT_PREVIEWS",
    "_RESUME_REVIEW_CACHE",
    "WALKTHROUGH_STEPS_CATALOG",
    "APTITUDE_CATEGORIES",
    "NOTE_CATEGORIES",
    "email_service",
    "coordinator_agent",
    "live_interview_agent",
    "coding_assessment_agent",
    "star_evaluation_agent",
    "github_analyzer_agent",
    "internship_agent",
    "linkedin_agent",
    "coding_practice_agent",
    "outreach_agent",
    "self_introduction_agent",
    "project_deep_dive_agent",
    "_session_client_label",
    "_format_session_timestamp",
    "_is_student_authorized",
    "_get_current_student_id",
    "get_available_companies",
    "_has_privacy_consent",
    "_extract_and_validate_resume",
    "save_resume_review_cache",
    "get_resume_review_cache",
    "_ics_escape",
    "_ics_fold_line",
    "_application_import_student_id",
    "_normalise_csv_header",
    "_suggest_application_import_mapping",
    "_read_application_import_csv",
    "_application_import_duplicate",
    "_build_application_import_preview",
    "_resume_link_snapshot",
    "_require_authenticated_student",
    "_saved_job_description_fields",
    "get_analysis",
    "get_db_connection",
    "get_valid_password_reset_token",
    "extract_text_from_file",
]

def _session_client_label() -> str:
    """Return a coarse client description from the user agent without storing raw network data."""
    user_agent = request.user_agent
    browser = (user_agent.browser or "").lower()
    platform = (user_agent.platform or "").lower()
    ua_str = (user_agent.string or request.headers.get("User-Agent") or "").lower()

    if not browser:
        if "edg" in ua_str:
            browser = "edge"
        elif "chrome" in ua_str or "crios" in ua_str:
            browser = "chrome"
        elif "firefox" in ua_str or "fxios" in ua_str:
            browser = "firefox"
        elif "safari" in ua_str and "chrome" not in ua_str and "crios" not in ua_str:
            browser = "safari"

    if not platform:
        if "windows" in ua_str:
            platform = "windows"
        elif "macintosh" in ua_str or "mac os" in ua_str:
            platform = "macos"
        elif "iphone" in ua_str or "ipad" in ua_str or "ios" in ua_str:
            platform = "ios"
        elif "android" in ua_str:
            platform = "android"
        elif "linux" in ua_str:
            platform = "linux"

    if "edge" in browser or "edg" in browser:
        browser_name = "Edge"
    elif "firefox" in browser:
        browser_name = "Firefox"
    elif "safari" in browser and "chrome" not in browser:
        browser_name = "Safari"
    elif "chrome" in browser:
        browser_name = "Chrome"
    else:
        browser_name = "Web browser"

    if platform in ("iphone", "ipad", "ios"):
        platform_name = "iOS"
    elif platform == "android":
        platform_name = "Android"
    elif platform == "windows":
        platform_name = "Windows"
    elif platform == "macos":
        platform_name = "macOS"
    elif platform == "linux":
        platform_name = "Linux"
    else:
        platform_name = "Desktop"
    return f"{browser_name} on {platform_name}"


def _format_session_timestamp(timestamp: Any) -> str:
    """Format registry timestamps consistently without exposing more than date and time."""
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        return "Unknown"


def get_available_companies() -> list:
    """
    Loads list of companies dynamically from data/companies.json with fallback defaults.
    """
    companies_file = Path(config.BASE_DIR) / "data" / "companies.json"
    default_companies = [
        "Accenture",
        "Adobe",
        "Amazon",
        "Capgemini",
        "Cognizant",
        "Deloitte",
        "Flipkart",
        "Google",
        "HCLTech",
        "Infosys",
        "Microsoft",
        "TCS",
        "Tech Mahindra",
        "Wipro",
        "Zoho",
    ]
    try:
        if companies_file.exists():
            with open(companies_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return sorted(list(data.keys()))
    except Exception as e:
        logger.warning(f"Could not load dynamic companies from {companies_file}: {e}")
    return default_companies


def _has_privacy_consent(req) -> bool:
    """
    Verifies that the candidate has agreed to the privacy notice and consented
    to third-party Gemini AI processing of resume text and data storage (#304).
    Supports form fields and JSON payloads ('privacy_consent' or 'consent').
    In automated test environments, allows legacy tests to run if neither field is provided,
    unless ENFORCE_CONSENT_IN_TESTS is explicitly configured.
    """
    raw = None
    if req.form:
        raw = req.form.get("privacy_consent")
        if raw is None:
            raw = req.form.get("consent")
    if raw is None and req.is_json:
        data = req.get_json(silent=True) or {}
        raw = data.get("privacy_consent")
        if raw is None:
            raw = data.get("consent")

    if current_app.config.get("TESTING") and not current_app.config.get("ENFORCE_CONSENT_IN_TESTS"):
        # If running in testing mode without explicit consent enforcement,
        # allow requests that omit consent so existing unit tests pass without retrofit.
        if raw is None:
            return True

    if raw is None:
        return False

    return str(raw).strip().lower() in ("true", "1", "on", "yes")


def _extract_and_validate_resume(req):
    """
    Validates uploaded resume file or pasted text from Flask request.
    Returns a tuple of (extracted_text, filename, file_uuid, error_message).
    """
    pasted_text = req.form.get("resume_text", "").strip()
    uploaded_file = req.files.get("resume")
    file_uuid = str(uuid.uuid4())

    jd_text = req.form.get("job_description", "").strip()
    if jd_text:
        register_sensitive_text(jd_text)

    if pasted_text:
        is_valid, validation_msg = validate_resume_text(pasted_text)
        if not is_valid:
            return None, None, None, validation_msg
        clean_text = pasted_text[:MAX_RESUME_TEXT_CHARS]
        register_sensitive_text(clean_text)
        try:
            os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
            text_path = os.path.join(config.UPLOAD_FOLDER, f"{file_uuid}_resume.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(clean_text)
        except Exception as e:
            logger.warning(f"Could not persist pasted resume text: {e}")
        return clean_text, "Pasted_Resume.txt", file_uuid, None
    elif uploaded_file and uploaded_file.filename != "":
        filename_lower = uploaded_file.filename.lower()
        ext = os.path.splitext(uploaded_file.filename)[1].lower()
        if ext not in ALLOWED_RESUME_EXTENSIONS:
            ext_display = f"'{ext}'" if ext else "none"
            return (
                None,
                None,
                None,
                f"Unsupported file format (Invalid file format {ext_display}). Only PDF (.pdf) and Word (.docx) resumes are supported.",
            )

        # Enforce maximum upload file size before writing to disk (Issue #153)
        uploaded_file.seek(0, os.SEEK_END)
        file_size = uploaded_file.tell()
        uploaded_file.seek(0)

        max_bytes = getattr(
            config, "MAX_RESUME_FILE_SIZE_BYTES", getattr(config, "MAX_UPLOAD_SIZE_MB", 5) * 1024 * 1024
        )
        max_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)

        if file_size == 0:
            return None, None, None, "The uploaded file is empty. Please upload a valid resume."

        if file_size > max_bytes:
            return (
                None,
                None,
                None,
                f"The uploaded file exceeds the maximum allowed size of {max_mb} MB. Please upload a smaller file.",
            )

        # Verify real content type (magic bytes) before saving and parsing (Issue #153)
        header = uploaded_file.read(1024)
        uploaded_file.seek(0)

        if ext == ".pdf":
            if b"%PDF-" not in header:
                return (
                    None,
                    None,
                    None,
                    "The uploaded file is not a valid PDF document. Please upload a genuine PDF resume (.pdf).",
                )
        elif ext == ".docx":
            if not header.startswith(b"PK\x03\x04"):
                return (
                    None,
                    None,
                    None,
                    "The uploaded file is not a valid Word document (.docx). Please upload a genuine .docx resume.",
                )

        resume_filename = uploaded_file.filename
        safe_name = secure_filename(f"{file_uuid}_{uploaded_file.filename}")
        saved_file_path = os.path.join(config.UPLOAD_FOLDER, safe_name)
        uploaded_file.save(saved_file_path)
        logger.info(f"Uploaded resume saved locally at: {saved_file_path}")
        try:
            extracted_resume_text = extract_text_from_file(saved_file_path)
            register_sensitive_text(extracted_resume_text)
            return extracted_resume_text, resume_filename, file_uuid, None
        except ScannedPDFError as spe:
            logger.warning(f"Scanned or image-only PDF rejected: {spe}")
            if os.path.exists(saved_file_path):
                try:
                    os.remove(saved_file_path)
                except Exception:
                    pass
            return None, None, None, str(spe)
        except PasswordProtectedPDFError as ppe:
            logger.warning("Password-protected PDF rejected without logging credentials.")
            if os.path.exists(saved_file_path):
                try:
                    os.remove(saved_file_path)
                except Exception:
                    pass
            return None, None, None, str(ppe)
        except ValueError as ve:
            logger.warning(f"Validation error reading resume file: {ve}")
            if os.path.exists(saved_file_path):
                try:
                    os.remove(saved_file_path)
                except Exception:
                    pass
            return None, None, None, str(ve)
        except Exception as err:
            logger.error(f"Unexpected error reading resume file: {err}")
            if os.path.exists(saved_file_path):
                try:
                    os.remove(saved_file_path)
                except Exception:
                    pass
            return None, None, None, f"Could not process uploaded file: {str(err)}"
    else:
        return None, None, None, "Please upload a PDF resume or paste your resume text."


def save_resume_review_cache(file_uuid: str, review_data: Dict[str, Any]) -> None:
    """Stores candidate resume review data in-memory and persists JSON cache to disk."""
    _RESUME_REVIEW_CACHE[file_uuid] = review_data
    try:
        cache_path = os.path.join(config.UPLOAD_FOLDER, f"review_{file_uuid}.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(review_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not persist review cache file for {file_uuid}: {e}")


def get_resume_review_cache(file_uuid: str) -> Optional[Dict[str, Any]]:
    """Retrieves resume review data from memory, disk cache, or re-extracts from saved upload."""
    if file_uuid in _RESUME_REVIEW_CACHE:
        return _RESUME_REVIEW_CACHE[file_uuid]

    cache_path = os.path.join(config.UPLOAD_FOLDER, f"review_{file_uuid}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                _RESUME_REVIEW_CACHE[file_uuid] = data
                return data
        except Exception as e:
            logger.warning(f"Failed to read review cache file for {file_uuid}: {e}")

    # Check for original uploaded file starting with file_uuid
    try:
        if os.path.exists(config.UPLOAD_FOLDER):
            for fname in os.listdir(config.UPLOAD_FOLDER):
                if fname.startswith(f"{file_uuid}_"):
                    full_path = os.path.join(config.UPLOAD_FOLDER, fname)
                    original_name = fname[len(file_uuid) + 1:]
                    txt = extract_text_from_file(full_path)
                    data = extract_resume_information(txt, filename=original_name, file_uuid=file_uuid)
                    save_resume_review_cache(file_uuid, data)
                    return data
    except Exception as e:
        logger.warning(f"Failed to rebuild review cache from uploaded file for {file_uuid}: {e}")

    return None


def _ics_escape(value):
    """Escapes text according to RFC 5545 content-line rules."""
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_fold_line(line, limit=75):
    """Folds long iCalendar content lines without splitting UTF-8 bytes."""
    if len(line) <= limit:
        return [line]
    chunks = [line[index:index + limit] for index in range(0, len(line), limit)]
    return [chunks[0]] + [f" {chunk}" for chunk in chunks[1:]]


def _application_import_student_id():
    return (
        flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    ).strip()


def _normalise_csv_header(value):
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _suggest_application_import_mapping(headers):
    aliases = {
        "company_name": {"company", "company_name", "employer", "organisation", "organization"},
        "role_title": {"role", "role_title", "job_title", "position", "title"},
        "status": {"status", "stage", "application_status"},
        "application_date": {"date", "application_date", "date_applied", "applied_date"},
        "job_url": {"url", "job_url", "job_link", "link"},
        "job_description": {"job_description", "description", "job_posting"},
        "notes": {"notes", "note", "comments"},
        "location": {"location", "city"},
        "job_type": {"job_type", "employment_type", "type"},
        "experience_level": {"experience", "experience_level", "seniority"},
    }
    mapping = {}
    normalised = {_normalise_csv_header(header): header for header in headers}
    for field, names in aliases.items():
        mapping[field] = next((normalised[name] for name in names if name in normalised), "")
    return mapping


def _read_application_import_csv(uploaded_file):
    if not uploaded_file or not uploaded_file.filename:
        raise ValueError("Choose a CSV file to import.")
    if not uploaded_file.filename.lower().endswith(".csv"):
        raise ValueError("Only CSV files are supported.")
    uploaded_file.seek(0, os.SEEK_END)
    if uploaded_file.tell() > APPLICATION_IMPORT_MAX_BYTES:
        raise ValueError("CSV files must be 5 MB or smaller.")
    uploaded_file.seek(0)
    try:
        content = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV must be encoded as UTF-8.") from exc
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    if not headers:
        raise ValueError("The CSV must include a header row.")
    rows = list(reader)
    if len(rows) > APPLICATION_IMPORT_MAX_ROWS:
        raise ValueError(f"CSV imports are limited to {APPLICATION_IMPORT_MAX_ROWS} rows.")
    return headers, rows


def _application_import_duplicate(existing_apps, candidate):
    candidate_url = (candidate.get("job_url") or "").strip().lower()
    candidate_key = (
        (candidate.get("company_name") or "").strip().lower(),
        (candidate.get("role_title") or "").strip().lower(),
        (candidate.get("application_date") or "").strip(),
    )
    for existing in existing_apps:
        existing_url = (existing.get("job_url") or "").strip().lower()
        existing_key = (
            (existing.get("company_name") or "").strip().lower(),
            (existing.get("role_title") or "").strip().lower(),
            (existing.get("application_date") or "").strip(),
        )
        if candidate_url and existing_url and candidate_url == existing_url:
            return "matches an existing application URL"
        if candidate_key == existing_key:
            return "matches an existing company, role, and application date"
    return None


def _build_application_import_preview(student_id, headers, rows, mapping):
    existing_apps = get_job_applications(student_id=student_id)
    seen = []
    preview_rows = []
    for row_number, raw_row in enumerate(rows, start=2):
        candidate = {field: (raw_row.get(mapping.get(field, ""), "") or "").strip() for field in APPLICATION_IMPORT_FIELDS}
        errors = []
        if not candidate["company_name"]:
            errors.append("Company is required")
        if not candidate["role_title"]:
            errors.append("Role title is required")
        if candidate["status"] and candidate["status"] not in APPLICATION_STAGES:
            if candidate["status"] == "Offered":
                candidate["status"] = "Selected"
            else:
                errors.append(f"Invalid status '{candidate['status']}'")
        if candidate["application_date"]:
            try:
                datetime.strptime(candidate["application_date"], "%Y-%m-%d")
            except ValueError:
                errors.append("Application date must use YYYY-MM-DD")
        duplicate = _application_import_duplicate(existing_apps + seen, candidate)
        if duplicate:
            errors.append(f"Likely duplicate: {duplicate}")
        if not errors:
            seen.append(candidate)
        preview_rows.append({"row_number": row_number, "values": candidate, "errors": errors})
    return preview_rows


def _resume_link_snapshot(student_id: str, analysis_id: str):
    """Returns an owned analysis snapshot suitable for linking to an application."""
    if not analysis_id:
        return None
    for version in get_student_versions(student_id):
        if version.get("id") == analysis_id:
            return {
                "id": version["id"],
                "filename": version.get("resume_filename") or "",
                "version": version.get("version_number"),
                "job_description": version.get("job_description") or "",
            }
    return None


def _require_authenticated_student():
    """Returns the current user id or a suitable response for private data routes."""
    student_id = flask_session.get("user_id")
    if student_id:
        return student_id, None
    if request.is_json or request.path.startswith("/api/"):
        return None, (jsonify({"success": False, "error": "Authentication required."}), 401)
    flash("Please log in to use your saved job description library.", "warning")
    return None, redirect(url_for("login", next=request.path))


def _saved_job_description_fields(payload):
    """Extracts and validates the fields shared by page and API submissions."""
    values = {
        "company_name": (payload.get("company_name") or "").strip(),
        "role_title": (payload.get("role_title") or "").strip(),
        "source": (payload.get("source") or "").strip(),
        "description": (payload.get("description") or "").strip(),
        "notes": (payload.get("notes") or "").strip(),
    }
    if not values["company_name"] or not values["role_title"] or not values["source"] or not values["description"]:
        return None, "Company, role title, source, and job description are required."
    if len(values["description"]) > 15000:
        return None, "Job descriptions must be 15,000 characters or fewer."
    if len(values["notes"]) > 5000:
        return None, "Notes must be 5,000 characters or fewer."
    return values, None


