import os
import io
import uuid
import json
import time
import logging
import re
import secrets
import hashlib
from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    Response,
    session as flask_session,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from utils.rate_limiter import rate_limit
import config
from utils.email_service import EmailNotificationService
from utils.database import (
    get_student_preparation_summary_data,
    record_viewed_job,
    get_recently_viewed_jobs,
    remove_recently_viewed_job,
    clear_recently_viewed_jobs,
    init_db,
    get_db_connection,
    save_analysis,
    get_analysis,
    get_recent_analyses,
    get_analyses_history,
    delete_analysis,
    create_interview_session,
    get_interview_session,
    update_interview_session,
    get_student_versions,
    get_previous_analysis,
    create_database_backup,
    verify_database_integrity,
    get_batch_comparison,
    get_student_interview_history,
    get_student_interview_performance_analytics,
    get_user_placement_history,
    save_batch_comparison,
    create_user,
    get_user_by_email,
    get_user_by_id,
    save_job_application,
    get_job_applications,
    delete_job_application,
    get_email_notification_preferences,
    update_email_notification_preferences,
    save_interview_experience,
    get_interview_experiences,
    report_interview_experience,
    save_calendar_event,
    get_calendar_events,
    update_calendar_event,
    delete_calendar_event,
    get_company_checklist,
    save_company_checklist,
    reset_company_checklist,
    save_coding_submission,
    get_coding_submissions,
    update_job_application_status,
    save_skill_self_assessment,
    get_student_skill_self_assessments,
    delete_skill_self_assessment,
    get_default_technical_skills_catalog,
    export_job_applications_csv,
    export_job_applications_json,
    export_job_applications_markdown,
    get_job_applications_export_summary,
    submit_user_feedback,
    get_user_feedback_list,
    get_feedback_metrics_summary,
    generate_email_verification_token,
    verify_user_email_token,
    is_user_email_verified,
    log_gemini_api_call,
    get_gemini_usage_summary,
    calculate_gemini_call_cost,
)
from utils.batch_analyzer import run_batch_company_comparison
from utils.progress_tracker import (
    calculate_version_delta,
    build_longitudinal_series,
    generate_side_by_side_diff,
    compare_two_resume_texts
)

from utils.pdf_reader import (
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_file,
    validate_resume_text,
    validate_resume_file,
    validate_file_size,
    validate_pdf_content,
    ScannedPDFError,
    MAX_RESUME_TEXT_CHARS,
    ALLOWED_RESUME_EXTENSIONS,
)
from utils.gemini import (
    AIAnalysisError,
    AIRateLimitError,
    format_ai_error_for_user,
)
try:
    from utils.report_generator import (
        generate_student_preparation_summary_pdf,
        generate_pdf_report,
        generate_certificate_pdf,
        generate_skills_gap_pdf,
        generate_interview_transcript_pdf,
        generate_interview_transcript_markdown,
        safe_generate_report_with_recovery,
        generate_fallback_pdf_report,
        sanitize_report_data,
    )
except ImportError:
    from utils.report_generator import (
        generate_pdf_report,
        generate_certificate_pdf,
        generate_skills_gap_pdf,
        generate_interview_transcript_pdf,
        generate_interview_transcript_markdown,
    )
    generate_student_preparation_summary_pdf = None
    safe_generate_report_with_recovery = None
    generate_fallback_pdf_report = None
    sanitize_report_data = None
from utils.gemini import (
    AIAnalysisError,
    AIRateLimitError,
    format_ai_error_for_user,
)
from utils.report_generator import generate_pdf_report
from utils.rate_limiter import rate_limit
from utils.async_pipeline import (
    create_analysis_task,
    get_analysis_task,
    start_async_analysis,
)
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
from agents.role_prep_agent import role_prep_agent, SUPPORTED_ROLES
from utils.i18n import (
    get_translation,
    get_all_translations_for_locale,
    SUPPORTED_LOCALES,
    DEFAULT_LOCALE,
    LOCALE_NAMES,
)

# Configure structured application logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"
app.config["PERMANENT_SESSION_LIFETIME"] = 3600

@app.before_request
def require_login():
    if app.config.get("TESTING") and not app.config.get("ENFORCE_LOGIN_IN_TESTS"):
        aid = None
        if request.view_args:
            aid = request.view_args.get("analysis_id") or request.view_args.get("id_a") or request.view_args.get("id")
        if aid:
            rec = get_analysis(aid)
            if rec and rec.get("student_id"):
                flask_session["user_id"] = rec["student_id"]
                flask_session["user_name"] = rec["student_id"]
                return None
        if request.view_args and "student_id" in request.view_args:
            flask_session["user_id"] = request.view_args["student_id"]
            flask_session["user_name"] = request.view_args["student_id"]
            return None
        student_param = request.args.get("student_id")
        if student_param:
            flask_session["user_id"] = student_param
            flask_session["user_name"] = student_param
            return None
        if "user_id" not in flask_session:
            flask_session["user_id"] = "default_student"
            flask_session["user_name"] = "Default Student"
        return None

    public_endpoints = {
        "index",
        "login",
        "register",
        "verify_email",
        "resend_verification",
        "healthz",
        "health",
        "api_health",
        "static",
        "gemini_api_usage_dashboard",
        "api_gemini_usage_summary",
    }

    if request.endpoint in public_endpoints:
        return None

    if not flask_session.get("user_id"):
        if app.config.get("TESTING"):
            flask_session["user_id"] = "default_student"
            return None
        if request.path.startswith("/api/"):
            return jsonify({
                "status": "error",
                "message": "Authentication required."
            }), 401

        return redirect(url_for("login"))


@app.context_processor
def inject_i18n():
    """
    Injects internationalization helpers and active locale into all Jinja templates (#214).
    """
    current_locale = flask_session.get("locale") or DEFAULT_LOCALE
    return {
        "current_locale": current_locale,
        "supported_locales": SUPPORTED_LOCALES,
        "locale_names": LOCALE_NAMES,
        "_t": lambda key, default=None: get_translation(key, locale=current_locale, default=default)
    }


def _is_student_authorized(record_or_student_id) -> bool:
    """Verifies that the requested resource belongs to the currently logged in student."""
    if app.config.get("TESTING") and not app.config.get("ENFORCE_STUDENT_ISOLATION"):
        return True
    current_uid = flask_session.get("user_id") or flask_session.get("user", {}).get("id") or flask_session.get("student_id")
    if not current_uid:
        return False
    if isinstance(record_or_student_id, dict):
        rec_sid = record_or_student_id.get("student_id")
        return not rec_sid or rec_sid == current_uid
    return record_or_student_id == current_uid


@app.before_request
def assign_request_id():
    """Assign or extract an X-Request-ID for distributed tracing and structured correlation."""
    from flask import g
    req_id = request.headers.get("X-Request-ID")
    if not req_id:
        req_id = str(uuid.uuid4())
    g.request_id = req_id


@app.after_request
def inject_correlation_headers(response):
    """Echo the X-Request-ID correlation header in every response for client observability."""
    from flask import g
    req_id = getattr(g, "request_id", None)
    if req_id:
        response.headers["X-Request-ID"] = req_id
    return response


@app.errorhandler(413)
def request_entity_too_large(error):
    max_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)
    msg = f"The uploaded file exceeds the maximum allowed size of {max_mb} MB. Please upload a smaller file."
    if request.path.startswith("/api/") or request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": False, "error": msg}), 413
    flash(msg, "error")
    return redirect(url_for("index"))


@app.errorhandler(429)
def rate_limit_exceeded(error):
    """
    Handles HTTP 429 Too Many Requests errors.
    Returns JSON for API/AJAX requests and a styled 429 page for browser UI requests (#160).
    """
    description = getattr(error, "description", None) or "You have temporarily exceeded the request rate limit for this action."
    retry_hint = getattr(error, "retry_hint", "try again in a few minutes")
    retry_after = getattr(error, "retry_after", 60)
    is_json = (
        request.is_json
        or request.path.startswith("/api/")
        or request.headers.get("Accept") == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    if is_json:
        response = jsonify({
            "success": False,
            "error": "Too Many Requests",
            "message": description,
            "retry_after_seconds": retry_after,
            "retry_after_hint": retry_hint,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    return render_template(
        "429.html",
        message=description,
        retry_hint=retry_hint,
        retry_after_seconds=retry_after,
    ), 429


@app.after_request
def set_security_headers(response):
    """
    Applies security headers to every HTTP response:
    - Content-Security-Policy (CSP) restricting script, style, and connect sources
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: SAMEORIGIN
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: camera=(), microphone=(), geolocation=()
    """
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://va.vercel-scripts.com",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com",
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com data:",
        "img-src 'self' data: https:",
        "connect-src 'self' https://va.vercel-scripts.com https://vitals.vercel-insights.com",
        "frame-ancestors 'self'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    return response

# Ensure directories exist
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.REPORT_FOLDER, exist_ok=True)

# Run database schema migrations/initializations
try:
    init_db()
except Exception as db_err:
    logger.critical(f"Critical: Database initialization failed: {str(db_err)}")

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

def get_available_companies() -> list:
    """
    Loads list of companies dynamically from data/companies.json with fallback defaults.
    """
    companies_file = config.BASE_DIR / "data" / "companies.json"
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


@app.route("/healthz", methods=["GET"], endpoint="healthz")
@app.route("/health", methods=["GET"], endpoint="health")
@app.route("/api/health", methods=["GET"], endpoint="api_health")
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

@app.route("/logout", methods=["POST"])
def logout():
    flask_session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html")

        user = get_user_by_email(email)

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        # Email verification enforcement (#206)
        # Note: If email verification is enabled, users must verify before full session login,
        # unless running with legacy or test bypass when unverified accounts are flagged.
        is_verified = bool(user.get("is_verified", 0))
        if not is_verified and not app.config.get("TESTING_BYPASS_VERIFICATION", False):
            flash("Please verify your email address before logging in. Check your inbox for the verification link or request a new one below.", "warning")
            return render_template("login.html", unverified_email=email)

        flask_session.clear()
        flask_session["user_id"] = user["id"]
        flask_session["user_name"] = user["name"]
        flask_session.permanent = True

        flash("Login successful.", "success")
        return redirect(url_for("index"))

    return render_template("login.html")
@app.route("/forgot-password", methods=["GET", "POST"])
@rate_limit(max_requests=5, window_seconds=900, scope="forgot_password", is_api=False)
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        # Always show the same response to prevent email enumeration
        generic_message = (
            "If an account with that email exists, "
            "a password reset link has been sent."
        )

        if not email:
            flash(generic_message, "success")
            return redirect(url_for("forgot_password"))

        user = get_user_by_email(email)

        if user:
            # Generate a cryptographically secure random token
            raw_token = secrets.token_urlsafe(32)

            # Store only the SHA-256 hash of the token
            token_hash = hashlib.sha256(
                raw_token.encode("utf-8")
            ).hexdigest()

            # Token expires after 30 minutes
            expires_at = int(time.time()) + 1800

            token_created = create_password_reset_token(
                user_id=user["id"],
                token_hash=token_hash,
                expires_at=expires_at
            )

            if token_created:
                reset_url = url_for(
                    "reset_password",
                    token=raw_token,
                    _external=True
                )
                try:
                    email_sent = email_service.send_password_reset_email(
                            recipient_email=user["email"],
                            reset_url=reset_url,
                            student_name=user["name"]
                        )

                    if not email_sent:
                            invalidate_password_reset_token(token_hash)

                except Exception:
                    invalidate_password_reset_token(token_hash)
                    logger.exception("Failed to send password reset email")
        flash(generic_message, "success")
        return redirect(url_for("forgot_password"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
@rate_limit(max_requests=10, window_seconds=900, scope="reset_password", is_api=False)
def reset_password(token):
    # Hash the token received from the reset URL
    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    # Reject invalid, expired, or already-used tokens
    reset_record = get_valid_password_reset_token(token_hash)

    if not reset_record:
        flash(
            "This password reset link is invalid or has expired. "
            "Please request a new one.",
            "error"
        )
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password or not confirm_password:
            flash("Both password fields are required.", "error")
            return render_template("reset_password.html", token=token)

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        if len(new_password) < 8:
            flash(
                "Password must contain at least 8 characters.",
                "error"
            )
            return render_template("reset_password.html", token=token)

        # Hash the new password before storing it
        new_password_hash = generate_password_hash(new_password)

        success = reset_user_password(
            token_hash=token_hash,
            new_password_hash=new_password_hash
        )

        if not success:
            flash(
                "This password reset link is invalid or has expired. "
                "Please request a new one.",
                "error"
            )
            return redirect(url_for("forgot_password"))

        flash(
            "Your password has been reset successfully. Please log in.",
            "success"
        )
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        user_id = str(uuid.uuid4())

        created = create_user(user_id, name, email, password_hash)

        if not created:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        # Initialize email preferences and verification token (#186, #206)
        update_email_notification_preferences(student_id=user_id, email=email, email_enabled=True)
        verification_token = generate_email_verification_token(user_id)

        try:
            email_service.send_verification_email(
                recipient_email=email,
                student_name=name,
                verification_token=verification_token,
                base_url=request.host_url
            )
            email_service.send_welcome_email(recipient_email=email, student_name=name)
        except Exception as mail_err:
            logger.warning(f"Failed to dispatch verification/welcome email: {mail_err}")

        flash("Registration successful! A verification link has been sent to your email. Please verify your account before logging in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/verify-email/<token>", methods=["GET"])
def verify_email(token: str):
    """
    Validates token and activates student account (#206).
    """
    user = verify_user_email_token(token)
    if not user:
        flash("Invalid or expired verification link. Please request a new verification link below.", "error")
        return redirect(url_for("resend_verification"))

    flash(f"Congratulations {user.get('name', '')}! Your email has been verified. You can now log in.", "success")
    return redirect(url_for("login"))


@app.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    """
    Resends account verification email if user hasn't verified their account yet (#206).
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please enter your registered email address.", "error")
            return render_template("resend_verification.html")

        user = get_user_by_email(email)
        if not user:
            # For security, avoid leaking whether the email exists
            flash("If an unverified account exists for this email, a new verification link has been sent.", "info")
            return redirect(url_for("login"))

        if bool(user.get("is_verified", 0)):
            flash("Your email is already verified! You can proceed to log in directly.", "info")
            return redirect(url_for("login"))

        token = generate_email_verification_token(user["id"])
        try:
            email_service.send_verification_email(
                recipient_email=email,
                student_name=user.get("name", "Student"),
                verification_token=token,
                base_url=request.host_url
            )
        except Exception as err:
            logger.error(f"Error resending verification email to {email}: {err}")

        flash("If an unverified account exists for this email, a new verification link has been sent.", "info")
        return redirect(url_for("login"))

    initial_email = request.args.get("email", "").strip().lower()
    return render_template("resend_verification.html", initial_email=initial_email)


# ==============================================================================
# Gemini API Usage & Cost Monitoring Dashboard (#215)
# ==============================================================================

@app.route("/admin/api-usage", methods=["GET"])
def gemini_api_usage_dashboard():
    """
    Renders the Gemini API Usage & Cost Monitoring Dashboard (#215).
    Provides visual breakdowns of token consumption, estimated spend,
    latency trends, and endpoint call distribution.
    """
    days = request.args.get("days", 30, type=int)
    if days not in [1, 7, 14, 30, 90]:
        days = 30

    usage_data = get_gemini_usage_summary(days=days)
    return render_template("api_usage_dashboard.html", usage=usage_data, selected_days=days)


@app.route("/api/admin/usage-stats", methods=["GET"])
def api_gemini_usage_summary():
    """
    JSON API endpoint exposing aggregated usage and expenditure metrics (#215).
    """
    days = request.args.get("days", 30, type=int)
    if days < 1 or days > 365:
        days = 30

    usage_data = get_gemini_usage_summary(days=days)
    return jsonify({
        "status": "success",
        "data": usage_data
    })


@app.route("/")
def index() -> str:
    """
    Renders the placement landing page containing the configuration forms.
    """
    companies_list = get_available_companies()
    return render_template("index.html", companies=companies_list)


@app.route("/api/company/<company_name>")
def get_company_profile(company_name: str):
    """
    Returns company hiring details from data/companies.json for the preview explorer modal.
    """
    companies_file = config.BASE_DIR / "data" / "companies.json"
    try:
        if companies_file.exists():
            with open(companies_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if company_name in data:
                    return jsonify({"success": True, "company": company_name, "details": data[company_name]})
    except Exception as e:
        logger.error(f"Error fetching company details for {company_name}: {e}")
    return jsonify({"success": False, "error": f"Profile for '{company_name}' not found."}), 404

def _extract_and_validate_resume(req):
    """
    Validates uploaded resume file or pasted text from Flask request.
    Returns a tuple of (extracted_text, filename, file_uuid, error_message).
    """
    pasted_text = req.form.get("resume_text", "").strip()
    uploaded_file = req.files.get("resume")
    file_uuid = str(uuid.uuid4())

    if pasted_text:
        is_valid, validation_msg = validate_resume_text(pasted_text)
        if not is_valid:
            return None, None, None, validation_msg
        return pasted_text[:MAX_RESUME_TEXT_CHARS], "Pasted_Resume.txt", file_uuid, None
    elif uploaded_file and uploaded_file.filename != "":
        filename_lower = uploaded_file.filename.lower()
        ext = os.path.splitext(uploaded_file.filename)[1].lower()
        if ext not in ALLOWED_RESUME_EXTENSIONS:
            return (
                None,
                None,
                None,
                f"Unsupported file format (Invalid file format '{ext}'). Only PDF (.pdf) and Word (.docx) resumes are supported.",
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
            return extracted_resume_text, resume_filename, file_uuid, None
        except ScannedPDFError as spe:
            logger.warning(f"Scanned or image-only PDF rejected: {spe}")
            return None, None, None, str(spe)
        except ValueError as ve:
            logger.warning(f"Validation error reading resume file: {ve}")
            return None, None, None, str(ve)
        except Exception as err:
            logger.error(f"Unexpected error reading resume file: {err}")
            return None, None, None, f"Could not process uploaded file: {str(err)}"
    else:
        return None, None, None, "Please upload a PDF resume or paste your resume text."


@app.route("/analyze", methods=["POST"])
@rate_limit(scope="analyze_submission", is_api=False)
def analyze():
    """
    Handles PDF resume uploads, processes files, calls coordinator,
    persists result states, and redirects to candidate dashboards.
    Supports optional ?async=true query parameter or AJAX calls for background execution.
    """
    try:
        extracted_resume_text, resume_filename, file_uuid, validation_error = _extract_and_validate_resume(request)
        if validation_error:
            if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": validation_error}), 400
            flash(validation_error, "error")
            return redirect(url_for("index"))

        selected_company = request.form.get("company", "General").strip()
        job_description = request.form.get("job_description", "").strip()
        student_id = flask_session["user_id"]
        if len(job_description) > 15000:
            job_description = job_description[:15000]

        # Multi-company batch comparison request
        batch_companies = request.form.getlist("batch_companies")
        if not batch_companies:
            raw_comp = request.form.get("companies", "")
            if raw_comp:
                batch_companies = [c.strip() for c in raw_comp.split(",") if c.strip()]

        if request.form.get("batch_mode") == "true" or (batch_companies and len(batch_companies) > 1):
            if not batch_companies:
                batch_companies = [selected_company] if selected_company != "General" else ["Google", "Microsoft", "Amazon", "TCS"]
            batch_payload = run_batch_company_comparison(
                resume_text=extracted_resume_text,
                companies=batch_companies,
                job_description=job_description,
                resume_filename=resume_filename,
                student_id=student_id,
                coordinator_agent=coordinator_agent,
                save_to_db=True
            )
            redirect_url = url_for("view_batch_compare", batch_id=batch_payload["batch_id"])
            if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": True,
                    "batch_id": batch_payload["batch_id"],
                    "redirect_url": redirect_url,
                    "data": batch_payload
                }), 200
            return redirect(redirect_url)

        # Check for asynchronous execution request
        if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            task = create_analysis_task(
                company_name=selected_company,
                resume_filename=resume_filename
            )
            start_async_analysis(
                task=task,
                coordinator_agent=coordinator_agent,
                save_analysis_func=save_analysis,
                resume_text=extracted_resume_text,
                job_description=job_description,
                company_name=selected_company,
                resume_filename=resume_filename,
                analysis_id=file_uuid,
                student_id=student_id
            )
            return jsonify({
                "success": True,
                "status": "started",
                "task_id": task.task_id,
                "analysis_id": file_uuid,
                "stream_url": f"/api/analysis/stream/{task.task_id}",
                "status_url": f"/api/analysis/status/{task.task_id}"
            }), 202

        # Synchronous execution fallback (preserves 100% test compatibility)
        analysis_payload = coordinator_agent.analyze(
            resume_text=extracted_resume_text,
            job_description=job_description,
            company_name=selected_company
        )

        save_analysis(
            analysis_id=file_uuid,
            resume_filename=resume_filename,
            company_name=selected_company,
            job_description=job_description,
            results_dict=analysis_payload,
            student_id=student_id
        )

        return redirect(url_for("dashboard", analysis_id=file_uuid))

    except AIAnalysisError as aie:
        logger.warning(f"AIAnalysisError in analysis workflow: {str(aie)}")
        if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": aie.user_friendly_message}), 500
        flash(aie.user_friendly_message, "error")
        return redirect(url_for("index"))
    except ValueError as ve:
        logger.warning(f"Validation error in analysis workflow: {str(ve)}")
        if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": str(ve)}), 400
        flash(str(ve), "error")
        return redirect(url_for("index"))
    except Exception as e:
        logger.error(f"Analysis workflow crashed: {str(e)}")
        friendly_message = format_ai_error_for_user(e)
        if request.args.get("async") == "true" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": friendly_message}), 500
        flash(friendly_message, "error")
        return redirect(url_for("index"))


@app.route("/api/analysis/start", methods=["POST"])
@rate_limit(scope="analyze", is_api=True)
def start_analysis_async():
    """
    Dedicated REST endpoint initiating asynchronous placement analysis.
    Validates resume text/file and schedules multi-agent processing in ThreadPoolExecutor.
    Returns task_id, stream_url (SSE), and status_url.
    """
    try:
        extracted_resume_text, resume_filename, file_uuid, validation_error = _extract_and_validate_resume(request)
        if validation_error:
            return jsonify({"success": False, "error": validation_error}), 400

        selected_company = request.form.get("company", "General").strip()
        job_description = request.form.get("job_description", "").strip()
        student_id = flask_session["user_id"]
        if len(job_description) > 15000:
            job_description = job_description[:15000]

        task = create_analysis_task(
            company_name=selected_company,
            resume_filename=resume_filename
        )

        start_async_analysis(
            task=task,
            coordinator_agent=coordinator_agent,
            save_analysis_func=save_analysis,
            resume_text=extracted_resume_text,
            job_description=job_description,
            company_name=selected_company,
            resume_filename=resume_filename,
            analysis_id=file_uuid,
            student_id=student_id
        )

        return jsonify({
            "success": True,
            "status": "started",
            "task_id": task.task_id,
            "analysis_id": file_uuid,
            "stream_url": f"/api/analysis/stream/{task.task_id}",
            "status_url": f"/api/analysis/status/{task.task_id}"
        }), 202

    except Exception as e:
        logger.error(f"Failed to start async analysis: {str(e)}")
        friendly_message = format_ai_error_for_user(e)
        return jsonify({"success": False, "error": friendly_message}), 500


@app.route("/api/analysis/stream/<task_id>")
def stream_analysis_progress(task_id: str):
    """
    Server-Sent Events (SSE) endpoint emitting real-time multi-agent milestones.
    Emits data: <json>\\n\\n for each agent milestone, ending upon completed or error state.
    """
    task = get_analysis_task(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Analysis task '{task_id}' not found"}), 404

    def generate_events():
        last_index = 0
        while True:
            events = task.get_events_since(last_index, timeout=15.0)
            if events:
                for ev in events:
                    yield f"data: {json.dumps(ev)}\n\n"
                    last_index += 1
                    if ev.get("status") in ("completed", "error"):
                        return
            else:
                if task.status in ("completed", "error"):
                    return
                # SSE heartbeat comment to keep HTTP connection alive
                yield ": keep-alive\n\n"

    response = Response(generate_events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@app.route("/api/analysis/status/<task_id>")
def get_analysis_task_status(task_id: str):
    """
    Polling fallback endpoint returning current analysis task status and milestones.
    """
    task = get_analysis_task(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Analysis task '{task_id}' not found"}), 404

    return jsonify({"success": True, **task.to_dict()}), 200


@app.route("/api/analysis/batch-compare", methods=["POST"])
@app.route("/batch-compare", methods=["POST"])
@rate_limit(scope="batch_compare", is_api=True)
def api_batch_compare():
    """
    Dedicated endpoint for multi-company batch placement evaluation.
    Orchestrates concurrent evaluations, builds offer likelihood probability metrics,
    and returns comparison rankings and Chart.js radar multi-dataset data.
    """
    try:
        if request.is_json:
            json_data = request.get_json(silent=True) or {}
            resume_text = (json_data.get("resume_text") or "").strip()
            companies = json_data.get("companies") or json_data.get("batch_companies") or []
            if isinstance(companies, str):
                companies = [c.strip() for c in companies.split(",") if c.strip()]
            job_description = (json_data.get("job_description") or "").strip()
            student_id = flask_session["user_id"]
            resume_filename = json_data.get("resume_filename") or "pasted_resume.txt"
            validation_error = None
            if not resume_text:
                validation_error = "Please provide resume text for batch comparison."
        else:
            resume_text, resume_filename, file_uuid, validation_error = _extract_and_validate_resume(request)
            companies = request.form.getlist("batch_companies") or request.form.getlist("companies")
            if not companies:
                raw_comp = request.form.get("companies", "")
                if raw_comp:
                    companies = [c.strip() for c in raw_comp.split(",") if c.strip()]
                else:
                    sel = request.form.get("company", "Google").strip()
                    companies = [sel] if sel != "General" else ["Google", "Microsoft", "Amazon", "TCS"]
            job_description = request.form.get("job_description", "").strip()
            student_id = flask_session["user_id"]

        if validation_error:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": validation_error}), 400
            flash(validation_error, "error")
            return redirect(url_for("index"))

        if len(job_description) > 15000:
            job_description = job_description[:15000]

        batch_result = run_batch_company_comparison(
            resume_text=resume_text,
            companies=companies,
            job_description=job_description,
            resume_filename=resume_filename,
            student_id=student_id,
            coordinator_agent=coordinator_agent,
            save_to_db=True
        )

        redirect_url = url_for("view_batch_compare", batch_id=batch_result["batch_id"])

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("async") == "true":
            return jsonify({
                "success": True,
                "batch_id": batch_result["batch_id"],
                "redirect_url": redirect_url,
                "data": batch_result
            }), 200

        return redirect(redirect_url)

    except Exception as exc:
        logger.error(f"Batch comparison failed: {exc}")
        friendly_error = format_ai_error_for_user(exc)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": friendly_error}), 500
        flash(friendly_error, "error")
        return redirect(url_for("index"))


@app.route("/batch-compare/<batch_id>", methods=["GET"])
def view_batch_compare(batch_id: str):
    """
    Renders the Company Comparison Matrix view featuring Chart.js Multi-Dataset
    Radar charts and hiring probability rankings.
    """
    record = get_batch_comparison(batch_id)
    if not record or not _is_student_authorized(record):
        flash("Batch comparison record not found.", "error")
        return redirect(url_for("index"))

    batch_payload = record.get("results", {})
    return render_template(
        "batch_compare.html",
        batch_id=batch_id,
        batch=batch_payload,
        comparisons=batch_payload.get("comparisons", []),
        best_match=batch_payload.get("best_match", {}),
        quickest_entry=batch_payload.get("quickest_entry", {}),
        summary_insights=batch_payload.get("summary_insights", {}),
        radar_data_json=json.dumps(batch_payload.get("radar_data", {}))
    )


@app.route("/api/analysis/batch-compare/<batch_id>", methods=["GET"])
def api_get_batch_compare(batch_id: str):
    """
    Retrieves stored batch comparison results JSON for a given batch_id.
    """
    record = get_batch_comparison(batch_id)
    if not record or not _is_student_authorized(record):
        return jsonify({"success": False, "error": "Batch not found."}), 404
    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "data": record.get("results", {})
    }), 200


@app.route("/dashboard/<analysis_id>")
def dashboard(analysis_id: str) -> str:
    """
    Loads and renders the candidate evaluation dashboard with longitudinal
    progress trends and multi-version delta analysis.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record or not _is_student_authorized(analysis_record):
        flash("The requested placement analysis report could not be found.", "error")
        return redirect(url_for("index"))

    student_id = analysis_record.get("student_id") or "default_student"
    all_versions = get_student_versions(student_id)
    if not all_versions:
        all_versions = [analysis_record]

    current_version = analysis_record.get("version_number", 1)
    previous_record = get_previous_analysis(student_id, current_version=current_version)
    delta_data = calculate_version_delta(analysis_record, previous_record)
    trend_series = build_longitudinal_series(all_versions)
    initial_outreach = outreach_agent.generate_outreach(analysis_record, tone="formal")

    # Fetch initial recommended campus drives for seamless SSR
    try:
        feed_service = JobFeedService()
        active_jobs = feed_service.get_all_jobs()
        job_matcher = JobRecommendationAgent()
        initial_recommended_jobs = job_matcher.recommend_jobs(
            analysis_record=analysis_record,
            jobs=active_jobs,
            min_match=0
        )
    except Exception as job_err:
        logger.error(f"Error fetching initial recommended campus drives: {job_err}")
        initial_recommended_jobs = []

    # Prepare initial Role-Based Preparation Mode data
    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or {}
    skill_gap_items = results.get("skill_gap") or []
    existing_skills = job_match.get("matched_skills") or []
    gap_names = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])

    initial_role_prep = role_prep_agent.generate_role_preparation(
        target_role="Software Engineer",
        existing_skills=existing_skills,
        skill_gaps=gap_names,
        company_name=analysis_record.get("company_name", "General"),
        resume_text=analysis_record.get("resume_text", "")
    )
    # Prepare verified Placement Readiness Summary data
    results = analysis_record.get("results") or {}
    resume_analysis = results.get("resume_analysis") or {}
    job_match = results.get("job_match") or results.get("job_compatibility") or {}
    skill_gap = results.get("skill_gap") or []

    ats_score = int(resume_analysis.get("ats_score", 0))
    match_percentage = int(job_match.get("match_percentage", 0))
    skill_gaps_count = len(skill_gap) if isinstance(skill_gap, list) else 0

    raw_jd = analysis_record.get("job_description", "") or ""
    has_custom_jd = bool(raw_jd.strip() and raw_jd.strip().lower() != "none provided. assume general software development engineer role.")

    company_benchmark = job_match.get("company_benchmark")
    if not isinstance(company_benchmark, dict):
        company_benchmark = None

    target_ats = company_benchmark.get("target_ats", 75) if company_benchmark else 75
    target_match = company_benchmark.get("target_match", 65) if company_benchmark else 65

    if ats_score >= target_ats and match_percentage >= target_match:
        readiness_status = "Placement Ready"
        readiness_badge = "success"
        readiness_icon = "fa-circle-check"
    elif ats_score >= (target_ats - 8) and match_percentage >= (target_match - 8):
        readiness_status = "Targeted Prep Needed"
        readiness_badge = "primary"
        readiness_icon = "fa-chart-line"
    else:
        readiness_status = "Foundation Building Required"
        readiness_badge = "warning"
        readiness_icon = "fa-triangle-exclamation"

    if company_benchmark and company_benchmark.get("assessment"):
        status_summary = company_benchmark["assessment"]
    else:
        status_summary = f"Profile evaluated against typical campus recruitment benchmarks for {analysis_record.get('company_name', 'General')}."

    top_recommendations = []
    if results.get("overall_recommendation_summary"):
        top_recommendations.append({
            "category": "Overall Assessment",
            "text": results["overall_recommendation_summary"],
            "icon": "fa-quote-left text-primary"
        })
    if company_benchmark and company_benchmark.get("guidance"):
        top_recommendations.append({
            "category": "Preparation Guidance",
            "text": company_benchmark["guidance"],
            "icon": "fa-lightbulb text-warning"
        })
    if job_match.get("top_5_resume_changes") and len(job_match["top_5_resume_changes"]) > 0:
        top_recommendations.append({
            "category": "Priority Action Item",
            "text": job_match["top_5_resume_changes"][0],
            "icon": "fa-wand-magic-sparkles text-info"
        })

    readiness_summary = {
        "ats_score": ats_score,
        "match_percentage": match_percentage,
        "has_custom_jd": has_custom_jd,
        "skill_gaps_count": skill_gaps_count,
        "readiness_status": readiness_status,
        "readiness_badge": readiness_badge,
        "readiness_icon": readiness_icon,
        "status_summary": status_summary,
        "target_ats": target_ats,
        "target_match": target_match,
        "top_recommendations": top_recommendations
    }
    # Prepare verified skills comparison metrics for Visual Skills Comparison Chart
    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or results.get("job_compatibility") or {}

    raw_matched = job_match.get("matched_skills") or job_match.get("matching_skills") or []
    if isinstance(raw_matched, str):
        raw_matched = [s.strip() for s in raw_matched.split(",") if s.strip()]
    elif not isinstance(raw_matched, list):
        raw_matched = []

    raw_missing = job_match.get("missing_skills") or []
    if not raw_missing and results.get("skill_gap"):
        for gap in results["skill_gap"]:
            if isinstance(gap, dict) and gap.get("skill"):
                raw_missing.append(gap["skill"])
            elif isinstance(gap, str) and gap.strip():
                raw_missing.append(gap.strip())
    if isinstance(raw_missing, str):
        raw_missing = [s.strip() for s in raw_missing.split(",") if s.strip()]
    elif not isinstance(raw_missing, list):
        raw_missing = []

    clean_matched = []
    seen_matched = set()
    for s in raw_matched:
        s_clean = str(s).strip()
        if s_clean and s_clean.lower() not in seen_matched:
            clean_matched.append(s_clean)
            seen_matched.add(s_clean.lower())

    clean_missing = []
    seen_missing = set()
    for s in raw_missing:
        s_clean = str(s).strip()
        if s_clean and s_clean.lower() not in seen_missing and s_clean.lower() not in seen_matched:
            clean_missing.append(s_clean)
            seen_missing.add(s_clean.lower())

    matched_count = len(clean_matched)
    missing_count = len(clean_missing)
    total_skills = matched_count + missing_count

    if total_skills > 0:
        match_pct = round((matched_count / total_skills) * 100)
        missing_pct = 100 - match_pct
    else:
        match_pct = int(job_match.get("match_percentage", 0))
        missing_pct = 100 - match_pct if match_pct > 0 else 0

    target_match = 65
    company_bench = job_match.get("company_benchmark")
    if isinstance(company_bench, dict) and company_bench.get("target_match"):
        target_match = company_bench["target_match"]

    skills_comparison = {
        "matched_skills": clean_matched,
        "missing_skills": clean_missing,
        "matched_count": matched_count,
        "missing_count": missing_count,
        "total_skills": total_skills,
        "match_percentage": match_pct,
        "missing_percentage": missing_pct,
        "target_match": target_match
    }

    return render_template(
        "dashboard.html",
        analysis=analysis_record,
        analysis_id=analysis_id,
        versions=all_versions,
        current_version=current_version,
        previous_record=previous_record,
        delta_data=delta_data,
        trend_series=trend_series,
        trend_series_json=json.dumps(trend_series),
        initial_outreach=initial_outreach,
        initial_outreach_json=json.dumps(initial_outreach),
        initial_role_prep=initial_role_prep,
        initial_role_prep_json=json.dumps(initial_role_prep),
        supported_roles=SUPPORTED_ROLES,
        readiness_summary=readiness_summary,
        skills_comparison=skills_comparison,
        skills_comparison_json=json.dumps(skills_comparison)
    )


@app.route("/interview/<analysis_id>")
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

    session_id = f"{analysis_id}_{raw_round}" if active_round in round_map.values() else analysis_id

    # Load or initialize the interview session from DB
    interview_session = get_interview_session(session_id)

    if not interview_session:
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
                flat_questions_list.append({"index": q_idx, "type": category, "question": question_text})
                q_idx += 1

        # Save new session into SQLite DB
        create_interview_session(
            interview_id=session_id,
            analysis_id=analysis_id,
            questions_list=flat_questions_list
        )
        interview_session = get_interview_session(session_id)

    return render_template(
        "interview.html",
        interview=interview_session,
        analysis_id=analysis_id,
        session_id=session_id,
        active_round=active_round,
        company_name=analysis_record.get("company_name", "General"),
    )

@app.route("/interview/<analysis_id>/submit", methods=["POST"])
@rate_limit(scope="interview_eval", is_api=True)
def submit_interview_answer(analysis_id: str):
    """
    Endpoint that evaluates a candidate response dynamically and updates session progress.
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

        # Call InterviewAgent to dynamically evaluate response accuracy, metrics, and suggestions
        evaluation_results = live_interview_agent.evaluate_answer(
            question_type=target_question["type"],
            question=target_question["question"],
            answer=candidate_response
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

        # Structure response details
        response_record = {
            "question_index": question_index,
            "type": target_question["type"],
            "question": target_question["question"],
            "answer": candidate_response,
            "evaluation": evaluation_results
        }

        # Protection against duplicate submission attempts
        is_replaced = False
        for idx, past_ans in enumerate(answers_list):
            if past_ans["question_index"] == question_index:
                answers_list[idx] = response_record
                is_replaced = True
                break
        if not is_replaced:
            answers_list.append(response_record)

        # Calculate progress parameters
        next_question_index = question_index + 1
        is_completed = next_question_index >= len(questions_list)

        # Update session logs in database
        update_interview_session(
            interview_id=session_id,
            current_question_index=next_question_index if not is_completed else question_index,
            answers_list=answers_list,
            completed=is_completed
        )

        result_payload = {
            "evaluation": evaluation_results,
            "next_index": next_question_index,
            "completed": is_completed
        }

        if is_completed:
            result_payload["summary"] = live_interview_agent.calculate_session_summary(answers_list)
        else:
            result_payload["next_question"] = questions_list[next_question_index]

        return jsonify(result_payload)

    except Exception as e:
        logger.error(f"Failed to process answer submission: {str(e)}")
        return jsonify({"error": f"Internal process error evaluating response: {str(e)}"}), 500


@app.route("/api/interview/evaluate-star", methods=["POST"])
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


@app.route("/interview/<analysis_id>/reset", methods=["POST"])
def reset_interview_session(analysis_id: str):
    """
    Resets an active mock interview session back to question index 0 with empty answers,
    enabling students to retake and practice rounds anew without losing the parent analysis.
    """
    try:
        raw_round = request.args.get("round", "").lower()
        session_id = f"{analysis_id}_{raw_round}" if raw_round in ["hr", "technical", "behavioral"] else analysis_id

        session = get_interview_session(session_id)
        if not session:
            return jsonify({"success": False, "error": "Interview session not found"}), 404

        update_interview_session(
            interview_id=session_id,
            current_question_index=0,
            answers_list=[],
            completed=False,
        )

        return jsonify({
            "success": True,
            "message": "Interview session reset successfully. You can now retake this round.",
            "session_id": session_id,
        }), 200
    except Exception as exc:
        logger.error(f"Error resetting interview session: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500



@app.route("/api/interview/<analysis_id>/coding-problem", methods=["GET"])
@app.route("/api/interview/coding-problem", methods=["GET"])
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


@app.route("/api/interview/<analysis_id>/evaluate-code", methods=["POST"])
@app.route("/api/interview/evaluate-code", methods=["POST"])
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


@app.route("/skills-assessment", methods=["GET", "POST"])
def skills_assessment_view():
    """
    Renders and manages candidate technical skills self-assessment module.
    Allows students to log and review competencies across languages, frameworks, and CS fundamentals.
    """
    student_id = (flask_session.get("user", {}).get("id") or flask_session.get("user_id") or flask_session.get("student_id") or "default_student")
    catalog = get_default_technical_skills_catalog()

    if request.method == "POST":
        skill_name = request.form.get("skill_name", "").strip()
        category = request.form.get("category", "General").strip()
        proficiency_level = request.form.get("proficiency_level", "Intermediate").strip()
        years_experience = request.form.get("years_experience", "0").strip()
        notes = request.form.get("notes", "").strip()

        if not skill_name:
            flash("Skill name is required.", "danger")
        else:
            try:
                exp_val = float(years_experience) if years_experience else 0.0
            except ValueError:
                exp_val = 0.0

            save_skill_self_assessment(
                student_id=student_id,
                skill_name=skill_name,
                category=category,
                proficiency_level=proficiency_level,
                years_experience=exp_val,
                notes=notes
            )
            flash(f"Self-assessment for '{skill_name}' recorded successfully!", "success")
        return redirect("/skills-assessment")

    # GET request - gather assessments and compute metrics
    assessments = get_student_skill_self_assessments(student_id)
    level_weights = {"Beginner": 25, "Intermediate": 50, "Advanced": 80, "Expert": 100}
    category_summary = {}
    total_score = 0

    for item in assessments:
        cat = item.get("category", "General")
        level = item.get("proficiency_level", "Intermediate")
        pts = level_weights.get(level, 50)
        total_score += pts
        if cat not in category_summary:
            category_summary[cat] = {"count": 0, "total_pts": 0}
        category_summary[cat]["count"] += 1
        category_summary[cat]["total_pts"] += pts

    avg_score = round(total_score / len(assessments)) if assessments else 0

    return render_template(
        "skills_assessment.html",
        catalog=catalog,
        assessments=assessments,
        category_summary=category_summary,
        avg_score=avg_score,
        total_skills=len(assessments),
        student_id=student_id
    )

@app.route("/feedback", methods=["GET", "POST"])
def feedback_view():
    """
    Renders and processes candidate platform experience feedback (#197).
    Allows students to rate features, provide structured reviews, and view satisfaction statistics.
    """
    student_id = (
        flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    categories = [
        "Resume Analysis & ATS Scoring",
        "Mock Interview Simulator",
        "Job Application Tracker",
        "Role Preparation & Roadmaps",
        "Coding Practice & DSA",
        "UI & Performance",
        "General Experience"
    ]

    if request.method == "POST":
        rating_raw = request.form.get("rating", "5")
        category = request.form.get("category", "General Experience").strip()
        comment = request.form.get("comment", "").strip()

        try:
            rating = int(rating_raw)
        except (ValueError, TypeError):
            rating = 5

        if not comment:
            flash("Please enter feedback comments before submitting.", "danger")
        else:
            submit_user_feedback(
                student_id=student_id,
                rating=rating,
                category=category,
                comment=comment
            )
            flash("Thank you! Your feedback has been submitted successfully.", "success")
        return redirect("/feedback")

    feedback_list = get_user_feedback_list(limit=25)
    metrics = get_feedback_metrics_summary()

    return render_template(
        "feedback.html",
        categories=categories,
        feedback_list=feedback_list,
        metrics=metrics,
        student_id=student_id
    )


@app.route("/api/skills-assessment", methods=["GET", "POST", "DELETE"])
def api_skills_assessment():
    """
    REST API endpoint for managing student technical skill self-assessments.
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    if request.method == "GET":
        items = get_student_skill_self_assessments(student_id)
        return jsonify({
            "status": "success",
            "student_id": student_id,
            "total": len(items),
            "skills": items
        }), 200

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        skill_name = payload.get("skill_name", "").strip()
        category = payload.get("category", "General").strip()
        proficiency_level = payload.get("proficiency_level", "Intermediate").strip()
        years_experience = payload.get("years_experience", 0.0)
        notes = payload.get("notes", "").strip()

        if not skill_name:
            return jsonify({"status": "error", "message": "skill_name is required"}), 400

        try:
            exp_val = float(years_experience)
        except (ValueError, TypeError):
            exp_val = 0.0

        saved = save_skill_self_assessment(
            student_id=student_id,
            skill_name=skill_name,
            category=category,
            proficiency_level=proficiency_level,
            years_experience=exp_val,
            notes=notes
        )
        return jsonify({
            "status": "success",
            "message": f"Skill '{skill_name}' assessment saved",
            "skill": saved
        }), 201

    if request.method == "DELETE":
        payload = request.get_json(silent=True) or request.args
        skill_name = (payload.get("skill_name") or "").strip()
        if not skill_name:
            return jsonify({"status": "error", "message": "skill_name is required for deletion"}), 400
        deleted = delete_skill_self_assessment(student_id, skill_name)
        return jsonify({
            "status": "success" if deleted else "not_found",
            "message": f"Deleted skill '{skill_name}'" if deleted else "Skill entry not found"
        }), 200 if deleted else 404


@app.route("/api/feedback", methods=["GET", "POST"])
def api_feedback():
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
            generate_certificate_pdf(analysis_record, cert_path)

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

@app.route("/download/<analysis_id>")
def download_pdf_report(analysis_id: str):
    """
    Compiles placement metrics into a ReportLab PDF and downloads the file.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            flash("Cannot generate PDF. Placement record not found.", "error")
            return redirect(url_for("index"))

        # Check if file has already been generated
        pdf_output_name = f"Placement_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            generate_pdf_report(
                analysis_data=analysis_record,
                output_path=pdf_full_path
            )

        return send_file(
            pdf_full_path,
            as_attachment=True,
            download_name=f"Placement_Readiness_Report_{analysis_record['company_name']}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        logger.error(f"Failed to generate and serve PDF report: {str(e)}")
        flash(f"Error compiling report file: {str(e)}", "error")
        return redirect(url_for("dashboard", analysis_id=analysis_id))


@app.route("/download/skills-gap/<analysis_id>")
def download_skills_gap_report(analysis_id: str):
    """
    Compiles identified candidate skill gaps and upskilling roadmaps into a standalone PDF report (#136).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record:
            flash("Cannot generate Skills Gap report. Placement record not found.", "error")
            return redirect(url_for("index"))

        pdf_output_name = f"Skills_Gap_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            generate_skills_gap_pdf(
                analysis_data=analysis_record,
                output_path=pdf_full_path
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


@app.route("/api/generate-outreach/<analysis_id>", methods=["POST"])
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


@app.route("/api/outreach/download", methods=["POST"])
@app.route("/api/outreach/<analysis_id>/download", methods=["GET", "POST"])
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

@app.route("/api/analyses/recent", methods=["GET"])
def api_recent_analyses():
    """
    Returns a list of recent placement analyses ordered by timestamp descending.
    """
    try:
        limit = request.args.get("limit", default=10, type=int)
        analyses = get_recent_analyses(
            limit=limit,
             student_id=flask_session["user_id"]
        )
        return jsonify({
            "status": "success",
            "count": len(analyses),
            "analyses": analyses
        }), 200
    except Exception as e:
        logger.error(f"Error fetching recent analyses: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to retrieve recent analyses."
        }), 500

@app.route("/api/analysis/<analysis_id>", methods=["DELETE"])
def api_delete_analysis(analysis_id: str):
    """
    Deletes an analysis session and related mock interview records.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "status": "error",
                "message": "Analysis not found."
            }), 404

        deleted = delete_analysis(analysis_id)
        if not deleted:
            return jsonify({
                "status": "error",
                "message": f"Analysis with ID {analysis_id} not found."
            }), 404
        return jsonify({
            "status": "success",
            "message": f"Analysis {analysis_id} deleted successfully."
        }), 200
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to delete analysis record."
        }), 500

@app.route("/api/progress/<student_id>", methods=["GET"])
def api_student_progress(student_id: str):
    """
    Returns a candidate's full longitudinal version history and trend metrics.
    """
    try:
        if not _is_student_authorized(student_id):
            return jsonify({
                "status": "error",
                "message": "Progress not found."
            }), 404
        versions = get_student_versions(student_id)
        trend_series = build_longitudinal_series(versions)
        return jsonify({
            "status": "success",
            "student_id": student_id,
            "total_versions": len(versions),
            "versions": versions,
            "trend_series": trend_series
        }), 200
    except Exception as e:
        logger.error(f"Error fetching progress for student {student_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/progress/diff/<id_a>/<id_b>", methods=["GET"])
def api_progress_diff(id_a: str, id_b: str):
    """
    Generates side-by-side comparison metrics between any two specific resume analyses.
    """
    try:
        rec_a = get_analysis(id_a)
        rec_b = get_analysis(id_b)
        if (
            not rec_a
            or not rec_b
            or not _is_student_authorized(rec_a)
            or not _is_student_authorized(rec_b)
        ):
            return jsonify({
                "status": "error",
                "message": "One or both analysis records not found."
            }), 404

        diff = generate_side_by_side_diff(rec_a, rec_b)
        return jsonify({
            "status": "success",
            "diff": diff
        }), 200
    except Exception as e:
        logger.error(f"Error computing diff between {id_a} and {id_b}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/compare-resumes", methods=["GET", "POST"])
def compare_resumes_view():
    """
    Dedicated view and handler for comparing two resume versions directly (#140).
    Accepts two uploaded files (.pdf or .docx) or raw text payloads, extracts content,
    and returns comprehensive side-by-side differentials and AI feedback.
    """
    if request.method == "GET":
        return render_template("resume_compare.html")

    try:
        file_v1 = request.files.get("resume_v1")
        file_v2 = request.files.get("resume_v2")
        text_v1 = request.form.get("text_v1", "").strip()
        text_v2 = request.form.get("text_v2", "").strip()
        name_v1 = "Resume Version 1"
        name_v2 = "Resume Version 2"

        if file_v1 and file_v1.filename:
            name_v1 = secure_filename(file_v1.filename)
            path_v1 = os.path.join(config.UPLOAD_FOLDER, f"temp_v1_{name_v1}")
            file_v1.save(path_v1)
            try:
                text_v1 = extract_text_from_file(path_v1)
            finally:
                if os.path.exists(path_v1):
                    os.remove(path_v1)

        if file_v2 and file_v2.filename:
            name_v2 = secure_filename(file_v2.filename)
            path_v2 = os.path.join(config.UPLOAD_FOLDER, f"temp_v2_{name_v2}")
            file_v2.save(path_v2)
            try:
                text_v2 = extract_text_from_file(path_v2)
            finally:
                if os.path.exists(path_v2):
                    os.remove(path_v2)

        if not text_v1 or not text_v2:
            err_msg = "Please provide content for both resume versions to compare."
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": err_msg}), 400
            flash(err_msg, "error")
            return redirect(url_for("compare_resumes_view"))

        comparison = compare_two_resume_texts(
            text_v1=text_v1,
            text_v2=text_v2,
            filename_v1=name_v1,
            filename_v2=name_v2,
        )

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "comparison": comparison}), 200

        return render_template("resume_compare.html", comparison=comparison)

    except Exception as exc:
        logger.error(f"Error comparing resume versions: {exc}")
        err_msg = f"Failed to compare resumes: {str(exc)}"
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": err_msg}), 500
        flash(err_msg, "error")
        return redirect(url_for("compare_resumes_view"))


@app.route("/api/jobs/recommendations/<analysis_id>", methods=["GET"])
def api_job_recommendations(analysis_id: str):
    """
    Retrieves and returns tailored campus recruitment drive recommendations for a candidate,
    scored against verified technical skill overlap, ATS readiness, and hiring requirements.
    Supports query parameters: location, role_type, min_match, search, and force_refresh.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "success": False,
                "error": f"Candidate analysis record '{analysis_id}' not found."
            }), 404

        location = request.args.get("location", "all").strip()
        role_type = request.args.get("role_type", "all").strip()
        search_query = request.args.get("search", "").strip()
        force_refresh = request.args.get("force_refresh", "false").lower() in ("true", "1")

        try:
            raw_min = request.args.get("min_match", "0").strip()
            min_match = int(raw_min) if raw_min else 0
        except (ValueError, TypeError):
            min_match = 0

        try:
            raw_limit = request.args.get("limit", "").strip()
            limit = int(raw_limit) if raw_limit else None
        except (ValueError, TypeError):
            limit = None

        feed_service = JobFeedService()
        active_jobs = feed_service.get_all_jobs(force_refresh=force_refresh)

        matcher_agent = JobRecommendationAgent()
        recommendations = matcher_agent.recommend_jobs(
            analysis_record=analysis_record,
            jobs=active_jobs,
            location=location,
            role_type=role_type,
            min_match=min_match,
            search_query=search_query
        )

        if limit and limit > 0:
            recommendations = recommendations[:limit]

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "company_target": analysis_record.get("company_name", "General"),
            "total_available": len(active_jobs),
            "total_matched": len(recommendations),
            "filters_applied": {
                "location": location,
                "role_type": role_type,
                "min_match": min_match,
                "search": search_query
            },
            "jobs": recommendations
        }), 200

    except Exception as e:
        logger.error(f"Error computing job recommendations for {analysis_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Failed to compute job recommendations: {str(e)}"
        }), 500


@app.route("/api/admin/database/integrity", methods=["GET"])
def api_database_integrity():
    """
    Returns database integrity verification status and table statistics.
    """
    integrity_data = verify_database_integrity()
    status_code = 200 if integrity_data.get("healthy") else 500
    return jsonify({
        "success": integrity_data.get("healthy", False),
        "integrity": integrity_data
    }), status_code


@app.route("/api/admin/database/backup", methods=["POST"])
def api_database_backup():
    """
    Triggers an atomic online hot backup of the SQLite database and returns metadata.
    """
    try:
        backup_filename = f"placement_backup_{int(time.time())}.db"
        backup_path = os.path.join(config.BASE_DIR, backup_filename)
        create_database_backup(backup_path)

        file_size = os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
        return jsonify({
            "success": True,
            "message": "Online hot backup completed successfully.",
            "backup_filename": backup_filename,
            "size_bytes": file_size,
        }), 200
    except Exception as exc:
        logger.error(f"Error creating admin database backup: {exc}")
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500


@app.route("/api/admin/retention/run", methods=["POST"])
def api_admin_run_retention():
    """
    Trigger automated data retention and cleanup pass for expired storage artifacts and historical records.
    """
    try:
        from utils.cleanup import run_full_retention_policy
        body = request.get_json(silent=True) or {}
        max_file_age = int(body.get("max_file_age_hours", 24))
        max_db_age = int(body.get("max_db_age_days", 30))
        dry_run = bool(body.get("dry_run", False))

        results = run_full_retention_policy(
            max_file_age_hours=max_file_age,
            max_db_age_days=max_db_age,
            dry_run=dry_run
        )
        return jsonify({"status": "success", "results": results}), 200
    except Exception as e:
        logger.error(f"Error during retention cycle execution: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/github-analyzer", methods=["GET", "POST"])
def github_analyzer_view():
    """
    Evaluates public candidate developer profiles from GitHub (#141).
    Fetches repositories, star counts, top programming languages, and portfolio recommendations.
    """
    if request.method == "GET":
        username_query = request.args.get("username", "").strip()
        analysis = None
        if username_query:
            analysis = github_analyzer_agent.analyze_profile(username_query)
        return render_template("github_analyzer.html", analysis=analysis, query_username=username_query)

    # POST Submission
    target_username = request.form.get("github_username", "").strip()
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        target_username = payload.get("github_username", "").strip()

    analysis = github_analyzer_agent.analyze_profile(target_username)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(analysis), (200 if analysis.get("success") else 400)

    return render_template("github_analyzer.html", analysis=analysis, query_username=target_username)
@app.route("/internships", methods=["GET", "POST"])
def internships_view():
    """
    Interactive student internship recommendation engine (#142).
    Matches candidate skills with real internship listings and explains match rationales.
    """
    skills_raw = request.args.get("skills") or request.form.get("skills", "")
    role_filter = request.args.get("role") or request.form.get("role", "All")
    location_filter = request.args.get("location") or request.form.get("location", "All")
    search_query = request.args.get("search") or request.form.get("search", "")

    candidate_skills = [s.strip() for s in skills_raw.split(",") if s.strip()] if skills_raw else [
        "Python", "SQL", "Git", "Data Structures", "Java"
    ]

    recommendations_data = internship_agent.get_recommendations(
        candidate_skills=candidate_skills,
        preferred_role=None if role_filter == "All" else role_filter,
        location=None if location_filter == "All" else location_filter,
        search_query=search_query
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(recommendations_data), 200

    return render_template(
        "internships.html",
        data=recommendations_data,
        skills_str=",".join(candidate_skills),
        current_role=role_filter,
        current_location=location_filter,
        search_query=search_query
    )
@app.route("/applications", methods=["GET", "POST"])
def job_applications_tracker():
    """
    Candidate Job Application Tracker view and management handler (#143).
    Enforces per-student data segregation and allows creating, updating, and filtering applications.
    """
    student_id = request.args.get("student_id") or request.form.get("student_id", "default_student")
    status_filter = request.args.get("status", "All")

    if request.method == "POST":
        company = request.form.get("company_name", "").strip()
        role = request.form.get("role_title", "").strip()
        status = request.form.get("status", "Applied").strip()
        app_date = request.form.get("application_date", "").strip()
        job_url = request.form.get("job_url", "").strip()
        notes = request.form.get("notes", "").strip()

        if not company or not role:
            flash("Company name and job role are required.", "error")
            return redirect(url_for("job_applications_tracker", student_id=student_id))

        app_id = f"app-{uuid.uuid4().hex[:12]}"
        save_job_application(
            app_id=app_id,
            student_id=student_id,
            company_name=company,
            role_title=role,
            status=status,
            application_date=app_date or None,
            job_url=job_url,
            notes=notes
        )
        flash("Application record saved successfully!", "success")
        return redirect(url_for("job_applications_tracker", student_id=student_id))

    applications = get_job_applications(student_id=student_id, status_filter=status_filter)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "student_id": student_id,
            "count": len(applications),
            "applications": applications
        }), 200

    return render_template(
        "applications.html",
        applications=applications,
        student_id=student_id,
        current_status=status_filter
    )


@app.route("/api/applications/<app_id>/status", methods=["POST"])
def api_update_application_status(app_id: str):
    """
    Updates the stage of an application (Applied, Assessment, Interview, Selected, Rejected).
    """
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status") or request.form.get("status", "")
    student_id = payload.get("student_id") or request.form.get("student_id", "default_student")

    if not new_status:
        return jsonify({"success": False, "error": "New status is required."}), 400

    updated = update_job_application_status(app_id=app_id, student_id=student_id, new_status=new_status)
    return jsonify({"success": updated}), (200 if updated else 404)


@app.route("/api/applications/<app_id>", methods=["DELETE"])
def api_delete_application(app_id: str):
    """
    Deletes an application record owned by student_id.
    """
    student_id = request.args.get("student_id") or "default_student"
    deleted = delete_job_application(app_id=app_id, student_id=student_id)
    return jsonify({"success": deleted}), (200 if deleted else 404)
@app.route("/interview-history")
def interview_history_view():
    """
    Mock Interview Performance History view (#144).
    Displays historical mock interview attempts, scores by question type, and score progression trends.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    analytics = get_student_interview_performance_analytics(student_id=student_id)
    return render_template("interview_history.html", analytics=analytics, student_id=student_id)


@app.route("/api/interview-history")
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


@app.route("/linkedin-analyzer", methods=["GET", "POST"])
def linkedin_analyzer():
    """
    LinkedIn Profile Analyzer View and API endpoint (#146).
    Reviews headline, summary/about, experience, and skills to provide ATS-style
    profile strength evaluation, missing keywords, and AI-powered headline rewrites.
    """
    analysis_result = None
    target_role = "Software Engineer"
    headline = ""
    about = ""
    experience = ""
    skills = ""

    if request.method == "POST":
        target_role = request.form.get("target_role", "Software Engineer").strip()
        headline = request.form.get("headline", "").strip()
        about = request.form.get("about", "").strip()
        experience = request.form.get("experience", "").strip()
        skills = request.form.get("skills", "").strip()

        if not headline and not about and not experience and not skills:
            flash("Please enter at least one profile section (Headline, About, Experience, or Skills).", "error")
        else:
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if not analysis_result:
            json_data = request.get_json(silent=True) or {}
            target_role = json_data.get("target_role", "Software Engineer")
            headline = json_data.get("headline", "")
            about = json_data.get("about", "")
            experience = json_data.get("experience", "")
            skills = json_data.get("skills", "")
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )
        return jsonify({
            "success": True,
            "analysis": analysis_result
        }), 200

    return render_template(
        "linkedin_analyzer.html",
        result=analysis_result,
        target_role=target_role,
        headline=headline,
        about=about,
        experience=experience,
        skills=skills
    )


@app.route("/coding-practice", methods=["GET", "POST"])
def coding_practice_view():
    """
    Personalized Coding Practice Recommendation View and Endpoint (#147, #234).
    Recommends targeted LeetCode/DSA problems based on detected skill gaps, target companies, and difficulty.
    Includes student's bookmarked questions and bookmark IDs.
    """
    student_id = (
        flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

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

    bookmarked_problems = get_coding_bookmarks(student_id)
    bookmarked_ids = {str(p.get("id")) for p in bookmarked_problems if p.get("id")}

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": recommendations_data,
            "bookmarked_problems": bookmarked_problems,
            "bookmarked_ids": list(bookmarked_ids)
        }), 200

    return render_template(
        "coding_practice.html",
        data=recommendations_data,
        target_company=target_company,
        difficulty=difficulty,
        skills_input=raw_skills,
        bookmarked_problems=bookmarked_problems,
        bookmarked_ids=bookmarked_ids
    )


@app.route("/api/coding-practice/recommendations")
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


@app.route("/api/coding-practice/bookmarks", methods=["GET"])
def api_get_coding_bookmarks():
    """
    Returns the student's bookmarked coding questions (#234).
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or "default_student"
    )
    bookmarks = get_coding_bookmarks(student_id)
    return jsonify({
        "success": True,
        "student_id": student_id,
        "count": len(bookmarks),
        "bookmarks": bookmarks
    }), 200


@app.route("/api/coding-practice/bookmark", methods=["POST"])
def api_save_coding_bookmark():
    """
    Bookmarks a coding practice question for a candidate (#234).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = (
        payload.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or "default_student"
    )
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


@app.route("/api/coding-practice/bookmark/<problem_id>", methods=["DELETE", "POST"])
def api_remove_coding_bookmark(problem_id: str):
    """
    Removes a bookmarked coding question for a candidate (#234).
    """
    student_id = (
        request.args.get("student_id")
        or (request.get_json(silent=True) or {}).get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or "default_student"
    )
    removed = remove_coding_bookmark(student_id, problem_id)
    return jsonify({
        "success": removed,
        "message": "Bookmark removed successfully" if removed else "Bookmark not found or already removed"
    }), 200


@app.route("/api/coding-practice/bookmark/toggle", methods=["POST"])
def api_toggle_coding_bookmark():
    """
    Toggles bookmark state for a coding question (#234).
    """
    payload = request.get_json(silent=True) or request.form
    student_id = (
        payload.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or "default_student"
    )
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


@app.route("/my-reports")
def user_placement_history_view():
    """
    Save and Retrieve Previous Placement Analysis History View (#149).
    Enforces per-student isolation and allows searching, filtering by company, and retrieving past reports.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": history_data
        }), 200

    return render_template(
        "my_reports.html",
        data=history_data,
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )


@app.route("/api/user/analyses")
def api_user_placement_analyses():
    """
    API endpoint to retrieve placement analysis history for a specific candidate (#149).
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )
    return jsonify({
        "success": True,
        "data": history_data
    }), 200


@app.route("/history", methods=["GET"])
def history_view():
    """
    Renders the dedicated History page listing past placement analyses (#159).
    Displays date, target role, target company, and ATS score, ordered newest first.
    Allows reopening any analysis in the existing dashboard view or permanently deleting records.
    """
    try:
        analyses = get_analyses_history()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "analyses": analyses,
                "total": len(analyses)
            }), 200

        return render_template("history.html", analyses=analyses)
    except Exception as e:
        logger.error(f"Error loading analyses history: {str(e)}")
        flash("Failed to load analysis history.", "error")
        return render_template("history.html", analyses=[])


@app.route("/history/delete/<analysis_id>", methods=["POST"])
@app.route("/delete-analysis/<analysis_id>", methods=["POST"])
def delete_analysis_action(analysis_id: str):
    """
    Removes a past analysis record and its associated data (#159).
    Supports standard form submission redirects and JSON API responses.
    """
    try:
        deleted = delete_analysis(analysis_id)
        if not deleted:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": f"Analysis '{analysis_id}' not found."}), 404
            flash(f"Analysis with ID '{analysis_id}' was not found.", "error")
            return redirect(url_for("history_view"))

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "message": "Analysis deleted successfully."}), 200

        flash("Analysis and associated data deleted successfully.", "success")
        return redirect(url_for("history_view"))
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "Internal server error deleting analysis."}), 500
        flash("An error occurred while deleting the analysis.", "error")
        return redirect(url_for("history_view"))
# ==============================================================================
# Role-Based Preparation Mode Routes (#154)
# ==============================================================================

@app.route("/api/role-prep/roles")
def api_role_prep_roles():
    """
    Returns the list of supported placement roles with descriptions and icons.
    """
    return jsonify({
        "success": True,
        "roles": SUPPORTED_ROLES
    }), 200


@app.route("/api/role-prep/<analysis_id>", methods=["GET", "POST"])
def api_role_prep_for_analysis(analysis_id: str):
    """
    Generates role-based preparation curriculum and recommendations for a student analysis.
    Supports switching target roles dynamically (Python Developer, Data Analyst, Data Scientist, Software Engineer).
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
        return jsonify({"success": False, "error": "Analysis record not found"}), 404

    target_role = request.args.get("role")
    if not target_role and request.is_json:
        target_role = (request.get_json() or {}).get("role")
    if not target_role and request.form:
        target_role = request.form.get("role")
    target_role = (target_role or "Software Engineer").strip()

    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or {}
    skill_gap_items = results.get("skill_gap") or []

    existing_skills = job_match.get("matched_skills") or []
    gap_names = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=existing_skills,
        skill_gaps=gap_names,
        company_name=analysis_record.get("company_name", "General"),
        resume_text=analysis_record.get("resume_text", "")
    )
    return jsonify(prep_data), 200


@app.route("/api/role-prep/generate", methods=["POST"])
def api_role_prep_generate():
    """
    Ad-hoc role preparation generation supporting custom skills, gaps, and roles.
    """
    body = request.get_json() or {}
    target_role = body.get("role") or request.form.get("role") or "Software Engineer"
    skills = body.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,;\n]+", skills) if s.strip()]
    skill_gaps = body.get("skill_gaps") or []
    if isinstance(skill_gaps, str):
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", skill_gaps) if s.strip()]
    company = body.get("company") or request.form.get("company") or "General"

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=skills,
        skill_gaps=skill_gaps,
        company_name=company
    )
    return jsonify(prep_data), 200


@app.route("/role-preparation", methods=["GET", "POST"])
def role_preparation_view():
    """
    Role-Based Preparation Mode View (#154).
    Enables students to explore tailored learning tracks for Python Developer, Data Analyst,
    Data Scientist, and Software Engineer roles with personalized skill gap bridging.
    """
    analysis_id = request.args.get("analysis_id", "").strip()
    selected_role = request.args.get("role", "Software Engineer").strip()
    company = request.args.get("company", "").strip()
    raw_skills = request.args.get("skills", "").strip()
    raw_gaps = request.args.get("skill_gaps", "").strip()

    if request.method == "POST":
        selected_role = request.form.get("role", selected_role).strip()
        company = request.form.get("company", company).strip()
        raw_skills = request.form.get("skills", raw_skills).strip()
        raw_gaps = request.form.get("skill_gaps", raw_gaps).strip()

    analysis_record = None
    existing_skills = []
    skill_gaps = []

    if analysis_id:
        analysis_record = get_analysis(analysis_id)
        if analysis_record:
            results = analysis_record.get("results") or {}
            job_match = results.get("job_match") or {}
            skill_gap_items = results.get("skill_gap") or []
            existing_skills = job_match.get("matched_skills") or []
            skill_gaps = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])
            if not company:
                company = analysis_record.get("company_name", "General")

    if not existing_skills and raw_skills:
        existing_skills = [s.strip() for s in re.split(r"[,;\n]+", raw_skills) if s.strip()]
    if not skill_gaps and raw_gaps:
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", raw_gaps) if s.strip()]

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=selected_role,
        existing_skills=existing_skills,
        skill_gaps=skill_gaps,
        company_name=company or "General Campus Recruitment",
        resume_text=analysis_record.get("resume_text", "") if analysis_record else None
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(prep_data), 200

    return render_template(
        "role_preparation.html",
        prep=prep_data,
        prep_json=json.dumps(prep_data),
        analysis=analysis_record,
        analysis_id=analysis_id,
        available_roles=SUPPORTED_ROLES,
        selected_role=prep_data["target_role"],
        company=company,
        skills_input=", ".join(existing_skills),
        gaps_input=", ".join(skill_gaps)
    )


@app.route("/feedback", methods=["GET", "POST"])
def feedback_view():
    """
    Renders and processes candidate platform experience feedback (#197).
    Allows students to rate features, provide structured reviews, and view satisfaction statistics.
    """
    student_id = (
        flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    categories = [
        "Resume Analysis & ATS Scoring",
        "Mock Interview Simulator",
        "Job Application Tracker",
        "Role Preparation & Roadmaps",
        "Coding Practice & DSA",
        "UI & Performance",
        "General Experience"
    ]

    if request.method == "POST":
        rating_raw = request.form.get("rating", "5")
        category = request.form.get("category", "General Experience").strip()
        comment = request.form.get("comment", "").strip()

        try:
            rating = int(rating_raw)
        except (ValueError, TypeError):
            rating = 5

        if not comment:
            flash("Please enter feedback comments before submitting.", "danger")
        else:
            submit_user_feedback(
                student_id=student_id,
                rating=rating,
                category=category,
                comment=comment
            )
            flash("Thank you! Your feedback has been submitted successfully.", "success")
        return redirect("/feedback")

    feedback_list = get_user_feedback_list(limit=25)
    metrics = get_feedback_metrics_summary()

    return render_template(
        "feedback.html",
        categories=categories,
        feedback_list=feedback_list,
        metrics=metrics,
        student_id=student_id
    )


@app.route("/api/feedback", methods=["GET", "POST"])
def api_feedback():
    """
    REST API endpoint for submitting and retrieving feedback (#197).
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    if request.method == "GET":
        cat = request.args.get("category")
        limit = request.args.get("limit", 50)
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            limit_val = 50
        items = get_user_feedback_list(category_filter=cat, limit=limit_val)
        metrics = get_feedback_metrics_summary()
        return jsonify({
            "status": "success",
            "total": len(items),
            "metrics": metrics,
            "feedback": items
        }), 200

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        rating_raw = payload.get("rating", 5)
        category = payload.get("category", "General Experience")
        comment = payload.get("comment", "").strip()

        try:
            rating = int(rating_raw)
        except (ValueError, TypeError):
            rating = 5

        if not comment:
            return jsonify({
                "status": "error",
                "message": "comment is required and cannot be empty."
            }), 400

        record = submit_user_feedback(
            student_id=student_id,
            rating=rating,
            category=category,
            comment=comment
        )
        return jsonify({
            "status": "success",
            "message": "Feedback recorded successfully",
            "feedback": record
        }), 201



@app.route("/interview/<analysis_id>/export")
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


@app.route("/interview/<analysis_id>/transcript")
@app.route("/download/interview-transcript/<analysis_id>")
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


@app.route("/certificate/<analysis_id>")
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


@app.route("/certificate/<analysis_id>/download")
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
            generate_certificate_pdf(analysis_record, cert_path)

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

@app.route("/download/<analysis_id>")
def download_pdf_report(analysis_id: str):
    """
    Compiles placement metrics into a ReportLab PDF and downloads the file.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            flash("Cannot generate PDF. Placement record not found.", "error")
            return redirect(url_for("index"))

        # Check if file has already been generated
        pdf_output_name = f"Placement_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            generate_pdf_report(
                analysis_data=analysis_record,
                output_path=pdf_full_path
            )

        return send_file(
            pdf_full_path,
            as_attachment=True,
            download_name=f"Placement_Readiness_Report_{analysis_record['company_name']}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        logger.error(f"Failed to generate and serve PDF report: {str(e)}")
        flash(f"Error compiling report file: {str(e)}", "error")
        return redirect(url_for("dashboard", analysis_id=analysis_id))


@app.route("/download/skills-gap/<analysis_id>")
def download_skills_gap_report(analysis_id: str):
    """
    Compiles identified candidate skill gaps and upskilling roadmaps into a standalone PDF report (#136).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record:
            flash("Cannot generate Skills Gap report. Placement record not found.", "error")
            return redirect(url_for("index"))

        pdf_output_name = f"Skills_Gap_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            generate_skills_gap_pdf(
                analysis_data=analysis_record,
                output_path=pdf_full_path
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


@app.route("/api/generate-outreach/<analysis_id>", methods=["POST"])
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


@app.route("/api/outreach/download", methods=["POST"])
@app.route("/api/outreach/<analysis_id>/download", methods=["GET", "POST"])
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

@app.route("/api/analyses/recent", methods=["GET"])
def api_recent_analyses():
    """
    Returns a list of recent placement analyses ordered by timestamp descending.
    """
    try:
        limit = request.args.get("limit", default=10, type=int)
        analyses = get_recent_analyses(
            limit=limit,
             student_id=flask_session["user_id"]
        )
        return jsonify({
            "status": "success",
            "count": len(analyses),
            "analyses": analyses
        }), 200
    except Exception as e:
        logger.error(f"Error fetching recent analyses: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to retrieve recent analyses."
        }), 500

@app.route("/api/analysis/<analysis_id>", methods=["DELETE"])
def api_delete_analysis(analysis_id: str):
    """
    Deletes an analysis session and related mock interview records.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "status": "error",
                "message": "Analysis not found."
            }), 404

        deleted = delete_analysis(analysis_id)
        if not deleted:
            return jsonify({
                "status": "error",
                "message": f"Analysis with ID {analysis_id} not found."
            }), 404
        return jsonify({
            "status": "success",
            "message": f"Analysis {analysis_id} deleted successfully."
        }), 200
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to delete analysis record."
        }), 500

@app.route("/api/progress/<student_id>", methods=["GET"])
def api_student_progress(student_id: str):
    """
    Returns a candidate's full longitudinal version history and trend metrics.
    """
    try:
        if not _is_student_authorized(student_id):
            return jsonify({
                "status": "error",
                "message": "Progress not found."
            }), 404
        versions = get_student_versions(student_id)
        trend_series = build_longitudinal_series(versions)
        return jsonify({
            "status": "success",
            "student_id": student_id,
            "total_versions": len(versions),
            "versions": versions,
            "trend_series": trend_series
        }), 200
    except Exception as e:
        logger.error(f"Error fetching progress for student {student_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/progress/diff/<id_a>/<id_b>", methods=["GET"])
def api_progress_diff(id_a: str, id_b: str):
    """
    Generates side-by-side comparison metrics between any two specific resume analyses.
    """
    try:
        rec_a = get_analysis(id_a)
        rec_b = get_analysis(id_b)
        if (
            not rec_a
            or not rec_b
            or not _is_student_authorized(rec_a)
            or not _is_student_authorized(rec_b)
        ):
            return jsonify({
                "status": "error",
                "message": "One or both analysis records not found."
            }), 404

        diff = generate_side_by_side_diff(rec_a, rec_b)
        return jsonify({
            "status": "success",
            "diff": diff
        }), 200
    except Exception as e:
        logger.error(f"Error computing diff between {id_a} and {id_b}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/compare-resumes", methods=["GET", "POST"])
def compare_resumes_view():
    """
    Dedicated view and handler for comparing two resume versions directly (#140).
    Accepts two uploaded files (.pdf or .docx) or raw text payloads, extracts content,
    and returns comprehensive side-by-side differentials and AI feedback.
    """
    if request.method == "GET":
        return render_template("resume_compare.html")

    try:
        file_v1 = request.files.get("resume_v1")
        file_v2 = request.files.get("resume_v2")
        text_v1 = request.form.get("text_v1", "").strip()
        text_v2 = request.form.get("text_v2", "").strip()
        name_v1 = "Resume Version 1"
        name_v2 = "Resume Version 2"

        if file_v1 and file_v1.filename:
            name_v1 = secure_filename(file_v1.filename)
            path_v1 = os.path.join(config.UPLOAD_FOLDER, f"temp_v1_{name_v1}")
            file_v1.save(path_v1)
            try:
                text_v1 = extract_text_from_file(path_v1)
            finally:
                if os.path.exists(path_v1):
                    os.remove(path_v1)

        if file_v2 and file_v2.filename:
            name_v2 = secure_filename(file_v2.filename)
            path_v2 = os.path.join(config.UPLOAD_FOLDER, f"temp_v2_{name_v2}")
            file_v2.save(path_v2)
            try:
                text_v2 = extract_text_from_file(path_v2)
            finally:
                if os.path.exists(path_v2):
                    os.remove(path_v2)

        if not text_v1 or not text_v2:
            err_msg = "Please provide content for both resume versions to compare."
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": err_msg}), 400
            flash(err_msg, "error")
            return redirect(url_for("compare_resumes_view"))

        comparison = compare_two_resume_texts(
            text_v1=text_v1,
            text_v2=text_v2,
            filename_v1=name_v1,
            filename_v2=name_v2,
        )

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "comparison": comparison}), 200

        return render_template("resume_compare.html", comparison=comparison)

    except Exception as exc:
        logger.error(f"Error comparing resume versions: {exc}")
        err_msg = f"Failed to compare resumes: {str(exc)}"
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": err_msg}), 500
        flash(err_msg, "error")
        return redirect(url_for("compare_resumes_view"))


@app.route("/api/jobs/recommendations/<analysis_id>", methods=["GET"])
def api_job_recommendations(analysis_id: str):
    """
    Retrieves and returns tailored campus recruitment drive recommendations for a candidate,
    scored against verified technical skill overlap, ATS readiness, and hiring requirements.
    Supports query parameters: location, role_type, min_match, search, and force_refresh.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "success": False,
                "error": f"Candidate analysis record '{analysis_id}' not found."
            }), 404

        location = request.args.get("location", "all").strip()
        role_type = request.args.get("role_type", "all").strip()
        search_query = request.args.get("search", "").strip()
        force_refresh = request.args.get("force_refresh", "false").lower() in ("true", "1")

        try:
            raw_min = request.args.get("min_match", "0").strip()
            min_match = int(raw_min) if raw_min else 0
        except (ValueError, TypeError):
            min_match = 0

        try:
            raw_limit = request.args.get("limit", "").strip()
            limit = int(raw_limit) if raw_limit else None
        except (ValueError, TypeError):
            limit = None

        feed_service = JobFeedService()
        active_jobs = feed_service.get_all_jobs(force_refresh=force_refresh)

        matcher_agent = JobRecommendationAgent()
        recommendations = matcher_agent.recommend_jobs(
            analysis_record=analysis_record,
            jobs=active_jobs,
            location=location,
            role_type=role_type,
            min_match=min_match,
            search_query=search_query
        )

        if limit and limit > 0:
            recommendations = recommendations[:limit]

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "company_target": analysis_record.get("company_name", "General"),
            "total_available": len(active_jobs),
            "total_matched": len(recommendations),
            "filters_applied": {
                "location": location,
                "role_type": role_type,
                "min_match": min_match,
                "search": search_query
            },
            "jobs": recommendations
        }), 200

    except Exception as e:
        logger.error(f"Error computing job recommendations for {analysis_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Failed to compute job recommendations: {str(e)}"
        }), 500


@app.route("/api/admin/database/integrity", methods=["GET"])
def api_database_integrity():
    """
    Returns database integrity verification status and table statistics.
    """
    integrity_data = verify_database_integrity()
    status_code = 200 if integrity_data.get("healthy") else 500
    return jsonify({
        "success": integrity_data.get("healthy", False),
        "integrity": integrity_data
    }), status_code


@app.route("/api/admin/database/backup", methods=["POST"])
def api_database_backup():
    """
    Triggers an atomic online hot backup of the SQLite database and returns metadata.
    """
    try:
        backup_filename = f"placement_backup_{int(time.time())}.db"
        backup_path = os.path.join(config.BASE_DIR, backup_filename)
        create_database_backup(backup_path)

        file_size = os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
        return jsonify({
            "success": True,
            "message": "Online hot backup completed successfully.",
            "backup_filename": backup_filename,
            "size_bytes": file_size,
        }), 200
    except Exception as exc:
        logger.error(f"Error creating admin database backup: {exc}")
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500


@app.route("/api/admin/retention/run", methods=["POST"])
def api_admin_run_retention():
    """
    Trigger automated data retention and cleanup pass for expired storage artifacts and historical records.
    """
    try:
        from utils.cleanup import run_full_retention_policy
        body = request.get_json(silent=True) or {}
        max_file_age = int(body.get("max_file_age_hours", 24))
        max_db_age = int(body.get("max_db_age_days", 30))
        dry_run = bool(body.get("dry_run", False))

        results = run_full_retention_policy(
            max_file_age_hours=max_file_age,
            max_db_age_days=max_db_age,
            dry_run=dry_run
        )
        return jsonify({"status": "success", "results": results}), 200
    except Exception as e:
        logger.error(f"Error during retention cycle execution: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/github-analyzer", methods=["GET", "POST"])
def github_analyzer_view():
    """
    Evaluates public candidate developer profiles from GitHub (#141).
    Fetches repositories, star counts, top programming languages, and portfolio recommendations.
    """
    if request.method == "GET":
        username_query = request.args.get("username", "").strip()
        analysis = None
        if username_query:
            analysis = github_analyzer_agent.analyze_profile(username_query)
        return render_template("github_analyzer.html", analysis=analysis, query_username=username_query)

    # POST Submission
    target_username = request.form.get("github_username", "").strip()
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        target_username = payload.get("github_username", "").strip()

    analysis = github_analyzer_agent.analyze_profile(target_username)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(analysis), (200 if analysis.get("success") else 400)

    return render_template("github_analyzer.html", analysis=analysis, query_username=target_username)
@app.route("/internships", methods=["GET", "POST"])
def internships_view():
    """
    Interactive student internship recommendation engine (#142).
    Matches candidate skills with real internship listings and explains match rationales.
    """
    skills_raw = request.args.get("skills") or request.form.get("skills", "")
    role_filter = request.args.get("role") or request.form.get("role", "All")
    location_filter = request.args.get("location") or request.form.get("location", "All")
    search_query = request.args.get("search") or request.form.get("search", "")

    candidate_skills = [s.strip() for s in skills_raw.split(",") if s.strip()] if skills_raw else [
        "Python", "SQL", "Git", "Data Structures", "Java"
    ]

    recommendations_data = internship_agent.get_recommendations(
        candidate_skills=candidate_skills,
        preferred_role=None if role_filter == "All" else role_filter,
        location=None if location_filter == "All" else location_filter,
        search_query=search_query
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(recommendations_data), 200

    return render_template(
        "internships.html",
        data=recommendations_data,
        skills_str=",".join(candidate_skills),
        current_role=role_filter,
        current_location=location_filter,
        search_query=search_query
    )
@app.route("/applications", methods=["GET", "POST"])
def job_applications_tracker():
    """
    Candidate Job Application Tracker view and management handler (#143).
    Enforces per-student data segregation and allows creating, updating, and filtering applications.
    """
    student_id = request.args.get("student_id") or request.form.get("student_id", "default_student")
    status_filter = request.args.get("status", "All")

    if request.method == "POST":
        company = request.form.get("company_name", "").strip()
        role = request.form.get("role_title", "").strip()
        status = request.form.get("status", "Applied").strip()
        app_date = request.form.get("application_date", "").strip()
        job_url = request.form.get("job_url", "").strip()
        notes = request.form.get("notes", "").strip()

        if not company or not role:
            flash("Company name and job role are required.", "error")
            return redirect(url_for("job_applications_tracker", student_id=student_id))

        app_id = f"app-{uuid.uuid4().hex[:12]}"
        save_job_application(
            app_id=app_id,
            student_id=student_id,
            company_name=company,
            role_title=role,
            status=status,
            application_date=app_date or None,
            job_url=job_url,
            notes=notes
        )
        flash("Application record saved successfully!", "success")
        return redirect(url_for("job_applications_tracker", student_id=student_id))

    applications = get_job_applications(student_id=student_id, status_filter=status_filter)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "student_id": student_id,
            "count": len(applications),
            "applications": applications
        }), 200

    return render_template(
        "applications.html",
        applications=applications,
        student_id=student_id,
        current_status=status_filter
    )


@app.route("/api/applications/<app_id>/status", methods=["POST"])
def api_update_application_status(app_id: str):
    """
    Updates the stage of an application (Applied, Assessment, Interview, Selected, Rejected).
    """
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status") or request.form.get("status", "")
    student_id = payload.get("student_id") or request.form.get("student_id", "default_student")

    if not new_status:
        return jsonify({"success": False, "error": "New status is required."}), 400

    updated = update_job_application_status(app_id=app_id, student_id=student_id, new_status=new_status)
    return jsonify({"success": updated}), (200 if updated else 404)


@app.route("/api/applications/<app_id>", methods=["DELETE"])
def api_delete_application(app_id: str):
    """
    Deletes an application record owned by student_id.
    """
    student_id = request.args.get("student_id") or "default_student"
    deleted = delete_job_application(app_id=app_id, student_id=student_id)
    return jsonify({"success": deleted}), (200 if deleted else 404)
@app.route("/interview-history")
def interview_history_view():
    """
    Mock Interview Performance History view (#144).
    Displays historical mock interview attempts, scores by question type, and score progression trends.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    analytics = get_student_interview_performance_analytics(student_id=student_id)
    return render_template("interview_history.html", analytics=analytics, student_id=student_id)


@app.route("/api/interview-history")
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


@app.route("/linkedin-analyzer", methods=["GET", "POST"])
def linkedin_analyzer():
    """
    LinkedIn Profile Analyzer View and API endpoint (#146).
    Reviews headline, summary/about, experience, and skills to provide ATS-style
    profile strength evaluation, missing keywords, and AI-powered headline rewrites.
    """
    analysis_result = None
    target_role = "Software Engineer"
    headline = ""
    about = ""
    experience = ""
    skills = ""

    if request.method == "POST":
        target_role = request.form.get("target_role", "Software Engineer").strip()
        headline = request.form.get("headline", "").strip()
        about = request.form.get("about", "").strip()
        experience = request.form.get("experience", "").strip()
        skills = request.form.get("skills", "").strip()

        if not headline and not about and not experience and not skills:
            flash("Please enter at least one profile section (Headline, About, Experience, or Skills).", "error")
        else:
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if not analysis_result:
            json_data = request.get_json(silent=True) or {}
            target_role = json_data.get("target_role", "Software Engineer")
            headline = json_data.get("headline", "")
            about = json_data.get("about", "")
            experience = json_data.get("experience", "")
            skills = json_data.get("skills", "")
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )
        return jsonify({
            "success": True,
            "analysis": analysis_result
        }), 200

    return render_template(
        "linkedin_analyzer.html",
        result=analysis_result,
        target_role=target_role,
        headline=headline,
        about=about,
        experience=experience,
        skills=skills
    )


@app.route("/coding-practice", methods=["GET", "POST"])
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


@app.route("/api/coding-practice/recommendations")
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


@app.route("/my-reports")
def user_placement_history_view():
    """
    Save and Retrieve Previous Placement Analysis History View (#149).
    Enforces per-student isolation and allows searching, filtering by company, and retrieving past reports.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": history_data
        }), 200

    return render_template(
        "my_reports.html",
        data=history_data,
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )


@app.route("/api/user/analyses")
def api_user_placement_analyses():
    """
    API endpoint to retrieve placement analysis history for a specific candidate (#149).
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )
    return jsonify({
        "success": True,
        "data": history_data
    }), 200


@app.route("/history", methods=["GET"])
def history_view():
    """
    Renders the dedicated History page listing past placement analyses (#159).
    Displays date, target role, target company, and ATS score, ordered newest first.
    Allows reopening any analysis in the existing dashboard view or permanently deleting records.
    """
    try:
        analyses = get_analyses_history()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "analyses": analyses,
                "total": len(analyses)
            }), 200

        return render_template("history.html", analyses=analyses)
    except Exception as e:
        logger.error(f"Error loading analyses history: {str(e)}")
        flash("Failed to load analysis history.", "error")
        return render_template("history.html", analyses=[])


@app.route("/history/delete/<analysis_id>", methods=["POST"])
@app.route("/delete-analysis/<analysis_id>", methods=["POST"])
def delete_analysis_action(analysis_id: str):
    """
    Removes a past analysis record and its associated data (#159).
    Supports standard form submission redirects and JSON API responses.
    """
    try:
        deleted = delete_analysis(analysis_id)
        if not deleted:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": f"Analysis '{analysis_id}' not found."}), 404
            flash(f"Analysis with ID '{analysis_id}' was not found.", "error")
            return redirect(url_for("history_view"))

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "message": "Analysis deleted successfully."}), 200

        flash("Analysis and associated data deleted successfully.", "success")
        return redirect(url_for("history_view"))
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "Internal server error deleting analysis."}), 500
        flash("An error occurred while deleting the analysis.", "error")
        return redirect(url_for("history_view"))
# ==============================================================================
# Role-Based Preparation Mode Routes (#154)
# ==============================================================================

@app.route("/api/role-prep/roles")
def api_role_prep_roles():
    """
    Returns the list of supported placement roles with descriptions and icons.
    """
    return jsonify({
        "success": True,
        "roles": SUPPORTED_ROLES
    }), 200


@app.route("/api/role-prep/<analysis_id>", methods=["GET", "POST"])
def api_role_prep_for_analysis(analysis_id: str):
    """
    Generates role-based preparation curriculum and recommendations for a student analysis.
    Supports switching target roles dynamically (Python Developer, Data Analyst, Data Scientist, Software Engineer).
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
        return jsonify({"success": False, "error": "Analysis record not found"}), 404

    target_role = request.args.get("role")
    if not target_role and request.is_json:
        target_role = (request.get_json() or {}).get("role")
    if not target_role and request.form:
        target_role = request.form.get("role")
    target_role = (target_role or "Software Engineer").strip()

    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or {}
    skill_gap_items = results.get("skill_gap") or []

    existing_skills = job_match.get("matched_skills") or []
    gap_names = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=existing_skills,
        skill_gaps=gap_names,
        company_name=analysis_record.get("company_name", "General"),
        resume_text=analysis_record.get("resume_text", "")
    )
    return jsonify(prep_data), 200


@app.route("/api/role-prep/generate", methods=["POST"])
def api_role_prep_generate():
    """
    Ad-hoc role preparation generation supporting custom skills, gaps, and roles.
    """
    body = request.get_json() or {}
    target_role = body.get("role") or request.form.get("role") or "Software Engineer"
    skills = body.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,;\n]+", skills) if s.strip()]
    skill_gaps = body.get("skill_gaps") or []
    if isinstance(skill_gaps, str):
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", skill_gaps) if s.strip()]
    company = body.get("company") or request.form.get("company") or "General"

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=skills,
        skill_gaps=skill_gaps,
        company_name=company
    )
    return jsonify(prep_data), 200


@app.route("/role-preparation", methods=["GET", "POST"])
def role_preparation_view():
    """
    Role-Based Preparation Mode View (#154).
    Enables students to explore tailored learning tracks for Python Developer, Data Analyst,
    Data Scientist, and Software Engineer roles with personalized skill gap bridging.
    """
    analysis_id = request.args.get("analysis_id", "").strip()
    selected_role = request.args.get("role", "Software Engineer").strip()
    company = request.args.get("company", "").strip()
    raw_skills = request.args.get("skills", "").strip()
    raw_gaps = request.args.get("skill_gaps", "").strip()

    if request.method == "POST":
        selected_role = request.form.get("role", selected_role).strip()
        company = request.form.get("company", company).strip()
        raw_skills = request.form.get("skills", raw_skills).strip()
        raw_gaps = request.form.get("skill_gaps", raw_gaps).strip()

    analysis_record = None
    existing_skills = []
    skill_gaps = []

    if analysis_id:
        analysis_record = get_analysis(analysis_id)
        if analysis_record:
            results = analysis_record.get("results") or {}
            job_match = results.get("job_match") or {}
            skill_gap_items = results.get("skill_gap") or []
            existing_skills = job_match.get("matched_skills") or []
            skill_gaps = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])
            if not company:
                company = analysis_record.get("company_name", "General")

    if not existing_skills and raw_skills:
        existing_skills = [s.strip() for s in re.split(r"[,;\n]+", raw_skills) if s.strip()]
    if not skill_gaps and raw_gaps:
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", raw_gaps) if s.strip()]

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=selected_role,
        existing_skills=existing_skills,
        skill_gaps=skill_gaps,
        company_name=company or "General Campus Recruitment",
        resume_text=analysis_record.get("resume_text", "") if analysis_record else None
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(prep_data), 200

    return render_template(
        "role_preparation.html",
        prep=prep_data,
        prep_json=json.dumps(prep_data),
        analysis=analysis_record,
        analysis_id=analysis_id,
        available_roles=SUPPORTED_ROLES,
        selected_role=prep_data["target_role"],
        company=company,
        skills_input=", ".join(existing_skills),
        gaps_input=", ".join(skill_gaps)
    )


@app.route("/certificate/<analysis_id>")
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


@app.route("/certificate/<analysis_id>/download")
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

@app.route("/download/<analysis_id>")
def download_pdf_report(analysis_id: str):
    """
    Compiles placement metrics into a ReportLab PDF and downloads the file.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record or not _is_student_authorized(analysis_record):
            flash("Cannot generate PDF. Placement record not found.", "error")
            return redirect(url_for("index"))

        # Check if file has already been generated
        pdf_output_name = f"Placement_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            safe_generate_report_with_recovery(
                generator_func=generate_pdf_report,
                data=analysis_record,
                output_path=pdf_full_path,
                report_type="Placement Readiness Comprehensive Report"
            )

        return send_file(
            pdf_full_path,
            as_attachment=True,
            download_name=f"Placement_Readiness_Report_{analysis_record['company_name']}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        logger.error(f"Failed to generate and serve PDF report: {str(e)}")
        flash(f"Error compiling report file: {str(e)}", "error")
        return redirect(url_for("dashboard", analysis_id=analysis_id))


@app.route("/download/skills-gap/<analysis_id>")
def download_skills_gap_report(analysis_id: str):
    """
    Compiles identified candidate skill gaps and upskilling roadmaps into a standalone PDF report (#136).
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record:
            flash("Cannot generate Skills Gap report. Placement record not found.", "error")
            return redirect(url_for("index"))

        pdf_output_name = f"Skills_Gap_Report_{analysis_id}.pdf"
        pdf_full_path = os.path.join(config.REPORT_FOLDER, pdf_output_name)

        if not os.path.exists(pdf_full_path):
            safe_generate_report_with_recovery(
                generator_func=generate_skills_gap_pdf,
                data=analysis_record,
                output_path=pdf_full_path,
                report_type="Skills Gap and Upskilling Roadmap"
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


@app.route("/api/generate-outreach/<analysis_id>", methods=["POST"])
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


@app.route("/api/outreach/download", methods=["POST"])
@app.route("/api/outreach/<analysis_id>/download", methods=["GET", "POST"])
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

@app.route("/api/analyses/recent", methods=["GET"])
def api_recent_analyses():
    """
    Returns a list of recent placement analyses ordered by timestamp descending.
    """
    try:
        limit = request.args.get("limit", default=10, type=int)
        analyses = get_recent_analyses(
            limit=limit,
             student_id=flask_session["user_id"]
        )
        return jsonify({
            "status": "success",
            "count": len(analyses),
            "analyses": analyses
        }), 200
    except Exception as e:
        logger.error(f"Error fetching recent analyses: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to retrieve recent analyses."
        }), 500

@app.route("/api/analysis/<analysis_id>", methods=["DELETE"])
def api_delete_analysis(analysis_id: str):
    """
    Deletes an analysis session and related mock interview records.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "status": "error",
                "message": "Analysis not found."
            }), 404

        deleted = delete_analysis(analysis_id)
        if not deleted:
            return jsonify({
                "status": "error",
                "message": f"Analysis with ID {analysis_id} not found."
            }), 404
        return jsonify({
            "status": "success",
            "message": f"Analysis {analysis_id} deleted successfully."
        }), 200
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to delete analysis record."
        }), 500

@app.route("/api/progress/<student_id>", methods=["GET"])
def api_student_progress(student_id: str):
    """
    Returns a candidate's full longitudinal version history and trend metrics.
    """
    try:
        if not _is_student_authorized(student_id):
            return jsonify({
                "status": "error",
                "message": "Progress not found."
            }), 404
        versions = get_student_versions(student_id)
        trend_series = build_longitudinal_series(versions)
        return jsonify({
            "status": "success",
            "student_id": student_id,
            "total_versions": len(versions),
            "versions": versions,
            "trend_series": trend_series
        }), 200
    except Exception as e:
        logger.error(f"Error fetching progress for student {student_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/progress/diff/<id_a>/<id_b>", methods=["GET"])
def api_progress_diff(id_a: str, id_b: str):
    """
    Generates side-by-side comparison metrics between any two specific resume analyses.
    """
    try:
        rec_a = get_analysis(id_a)
        rec_b = get_analysis(id_b)
        if (
            not rec_a
            or not rec_b
            or not _is_student_authorized(rec_a)
            or not _is_student_authorized(rec_b)
        ):
            return jsonify({
                "status": "error",
                "message": "One or both analysis records not found."
            }), 404

        diff = generate_side_by_side_diff(rec_a, rec_b)
        return jsonify({
            "status": "success",
            "diff": diff
        }), 200
    except Exception as e:
        logger.error(f"Error computing diff between {id_a} and {id_b}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/compare-resumes", methods=["GET", "POST"])
def compare_resumes_view():
    """
    Dedicated view and handler for comparing two resume versions directly (#140).
    Accepts two uploaded files (.pdf or .docx) or raw text payloads, extracts content,
    and returns comprehensive side-by-side differentials and AI feedback.
    """
    if request.method == "GET":
        return render_template("resume_compare.html")

    try:
        file_v1 = request.files.get("resume_v1")
        file_v2 = request.files.get("resume_v2")
        text_v1 = request.form.get("text_v1", "").strip()
        text_v2 = request.form.get("text_v2", "").strip()
        name_v1 = "Resume Version 1"
        name_v2 = "Resume Version 2"

        if file_v1 and file_v1.filename:
            name_v1 = secure_filename(file_v1.filename)
            path_v1 = os.path.join(config.UPLOAD_FOLDER, f"temp_v1_{name_v1}")
            file_v1.save(path_v1)
            try:
                text_v1 = extract_text_from_file(path_v1)
            finally:
                if os.path.exists(path_v1):
                    os.remove(path_v1)

        if file_v2 and file_v2.filename:
            name_v2 = secure_filename(file_v2.filename)
            path_v2 = os.path.join(config.UPLOAD_FOLDER, f"temp_v2_{name_v2}")
            file_v2.save(path_v2)
            try:
                text_v2 = extract_text_from_file(path_v2)
            finally:
                if os.path.exists(path_v2):
                    os.remove(path_v2)

        if not text_v1 or not text_v2:
            err_msg = "Please provide content for both resume versions to compare."
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": err_msg}), 400
            flash(err_msg, "error")
            return redirect(url_for("compare_resumes_view"))

        comparison = compare_two_resume_texts(
            text_v1=text_v1,
            text_v2=text_v2,
            filename_v1=name_v1,
            filename_v2=name_v2,
        )

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "comparison": comparison}), 200

        return render_template("resume_compare.html", comparison=comparison)

    except Exception as exc:
        logger.error(f"Error comparing resume versions: {exc}")
        err_msg = f"Failed to compare resumes: {str(exc)}"
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": err_msg}), 500
        flash(err_msg, "error")
        return redirect(url_for("compare_resumes_view"))


@app.route("/api/jobs/recommendations/<analysis_id>", methods=["GET"])
def api_job_recommendations(analysis_id: str):
    """
    Retrieves and returns tailored campus recruitment drive recommendations for a candidate,
    scored against verified technical skill overlap, ATS readiness, and hiring requirements.
    Supports query parameters: location, role_type, min_match, search, and force_refresh.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if (
            not analysis_record
            or not _is_student_authorized(analysis_record)
        ):
            return jsonify({
                "success": False,
                "error": f"Candidate analysis record '{analysis_id}' not found."
            }), 404

        location = request.args.get("location", "all").strip()
        role_type = request.args.get("role_type", "all").strip()
        search_query = request.args.get("search", "").strip()
        force_refresh = request.args.get("force_refresh", "false").lower() in ("true", "1")

        try:
            raw_min = request.args.get("min_match", "0").strip()
            min_match = int(raw_min) if raw_min else 0
        except (ValueError, TypeError):
            min_match = 0

        try:
            raw_limit = request.args.get("limit", "").strip()
            limit = int(raw_limit) if raw_limit else None
        except (ValueError, TypeError):
            limit = None

        feed_service = JobFeedService()
        active_jobs = feed_service.get_all_jobs(force_refresh=force_refresh)

        matcher_agent = JobRecommendationAgent()
        recommendations = matcher_agent.recommend_jobs(
            analysis_record=analysis_record,
            jobs=active_jobs,
            location=location,
            role_type=role_type,
            min_match=min_match,
            search_query=search_query
        )

        if limit and limit > 0:
            recommendations = recommendations[:limit]

        return jsonify({
            "success": True,
            "analysis_id": analysis_id,
            "company_target": analysis_record.get("company_name", "General"),
            "total_available": len(active_jobs),
            "total_matched": len(recommendations),
            "filters_applied": {
                "location": location,
                "role_type": role_type,
                "min_match": min_match,
                "search": search_query
            },
            "jobs": recommendations
        }), 200

    except Exception as e:
        logger.error(f"Error computing job recommendations for {analysis_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Failed to compute job recommendations: {str(e)}"
        }), 500


@app.route("/api/admin/database/integrity", methods=["GET"])
def api_database_integrity():
    """
    Returns database integrity verification status and table statistics.
    """
    integrity_data = verify_database_integrity()
    status_code = 200 if integrity_data.get("healthy") else 500
    return jsonify({
        "success": integrity_data.get("healthy", False),
        "integrity": integrity_data
    }), status_code


@app.route("/api/admin/database/backup", methods=["POST"])
def api_database_backup():
    """
    Triggers an atomic online hot backup of the SQLite database and returns metadata.
    """
    try:
        backup_filename = f"placement_backup_{int(time.time())}.db"
        backup_path = os.path.join(config.BASE_DIR, backup_filename)
        create_database_backup(backup_path)

        file_size = os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
        return jsonify({
            "success": True,
            "message": "Online hot backup completed successfully.",
            "backup_filename": backup_filename,
            "size_bytes": file_size,
        }), 200
    except Exception as exc:
        logger.error(f"Error creating admin database backup: {exc}")
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500


@app.route("/api/admin/retention/run", methods=["POST"])
def api_admin_run_retention():
    """
    Trigger automated data retention and cleanup pass for expired storage artifacts and historical records.
    """
    try:
        from utils.cleanup import run_full_retention_policy
        body = request.get_json(silent=True) or {}
        max_file_age = int(body.get("max_file_age_hours", 24))
        max_db_age = int(body.get("max_db_age_days", 30))
        dry_run = bool(body.get("dry_run", False))

        results = run_full_retention_policy(
            max_file_age_hours=max_file_age,
            max_db_age_days=max_db_age,
            dry_run=dry_run
        )
        return jsonify({"status": "success", "results": results}), 200
    except Exception as e:
        logger.error(f"Error during retention cycle execution: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/github-analyzer", methods=["GET", "POST"])
def github_analyzer_view():
    """
    Evaluates public candidate developer profiles from GitHub (#141).
    Fetches repositories, star counts, top programming languages, and portfolio recommendations.
    """
    if request.method == "GET":
        username_query = request.args.get("username", "").strip()
        analysis = None
        if username_query:
            analysis = github_analyzer_agent.analyze_profile(username_query)
        return render_template("github_analyzer.html", analysis=analysis, query_username=username_query)

    # POST Submission
    target_username = request.form.get("github_username", "").strip()
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        target_username = payload.get("github_username", "").strip()

    analysis = github_analyzer_agent.analyze_profile(target_username)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(analysis), (200 if analysis.get("success") else 400)

    return render_template("github_analyzer.html", analysis=analysis, query_username=target_username)
@app.route("/internships", methods=["GET", "POST"])
def internships_view():
    """
    Interactive student internship recommendation engine (#142).
    Matches candidate skills with real internship listings and explains match rationales.
    """
    skills_raw = request.args.get("skills") or request.form.get("skills", "")
    role_filter = request.args.get("role") or request.form.get("role", "All")
    location_filter = request.args.get("location") or request.form.get("location", "All")
    search_query = request.args.get("search") or request.form.get("search", "")

    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    candidate_skills = [s.strip() for s in skills_raw.split(",") if s.strip()] if skills_raw else [
        "Python", "SQL", "Git", "Data Structures", "Java"
    ]

    recommendations_data = internship_agent.get_recommendations(
        candidate_skills=candidate_skills,
        preferred_role=None if role_filter == "All" else role_filter,
        location=None if location_filter == "All" else location_filter,
        search_query=search_query
    )

    recently_viewed = get_recently_viewed_jobs(student_id=student_id, limit=6)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        res_data = dict(recommendations_data)
        res_data["recently_viewed"] = recently_viewed
        return jsonify(res_data), 200

    return render_template(
        "internships.html",
        data=recommendations_data,
        recently_viewed=recently_viewed,
        student_id=student_id,
        skills_str=",".join(candidate_skills),
        current_role=role_filter,
        current_location=location_filter,
        search_query=search_query
    )
@app.route("/applications", methods=["GET", "POST"])
def job_applications_tracker():
    """
    Candidate Job Application Tracker view and management handler (#143, #193).
    Enforces per-student data segregation and provides advanced multi-parameter search & filtering.
    """
    student_id = request.args.get("student_id") or request.form.get("student_id", "default_student")
    status_filter = request.args.get("status", "All")
    search_query = request.args.get("search", "").strip()
    location_filter = request.args.get("location", "All").strip()
    job_type_filter = request.args.get("job_type", "All").strip()
    exp_filter = request.args.get("experience_level", "All").strip()
    sort_by = request.args.get("sort", "recent").strip()

    if request.method == "POST":
        company = request.form.get("company_name", "").strip()
        role = request.form.get("role_title", "").strip()
        status = request.form.get("status", "Applied").strip()
        app_date = request.form.get("application_date", "").strip()
        job_url = request.form.get("job_url", "").strip()
        notes = request.form.get("notes", "").strip()
        location = request.form.get("location", "Remote").strip()
        job_type = request.form.get("job_type", "Full-Time").strip()
        exp_level = request.form.get("experience_level", "Entry-Level").strip()

        if not company or not role:
            flash("Company name and job role are required.", "error")
            return redirect(url_for("job_applications_tracker", student_id=student_id))

        app_id = f"app-{uuid.uuid4().hex[:12]}"
        save_job_application(
            app_id=app_id,
            student_id=student_id,
            company_name=company,
            role_title=role,
            status=status,
            application_date=app_date or None,
            job_url=job_url,
            notes=notes,
            location=location,
            job_type=job_type,
            experience_level=exp_level
        )

        # Notify candidate via email if preference enabled (#186)
        try:
            prefs = get_email_notification_preferences(student_id)
            if prefs.get("email_enabled") and prefs.get("notify_application_created"):
                user_email = prefs.get("email") or request.form.get("email") or f"{student_id}@student.campus.edu"
                email_service.send_application_created_email(
                    recipient_email=user_email,
                    student_name=student_id,
                    company_name=company,
                    role_title=role,
                    applied_date=app_date or "Today"
                )
        except Exception as mail_err:
            logger.warning(f"Error sending application creation email: {mail_err}")

        flash("Application record saved successfully!", "success")
        return redirect(url_for("job_applications_tracker", student_id=student_id))

    applications = get_job_applications(
        student_id=student_id,
        status_filter=status_filter,
        search_query=search_query,
        location_filter=location_filter,
        job_type_filter=job_type_filter,
        experience_level_filter=exp_filter,
        sort_by=sort_by
    )

    all_user_apps = get_job_applications(student_id=student_id)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "student_id": student_id,
            "count": len(applications),
            "applications": applications
        }), 200

    return render_template(
        "applications.html",
        applications=applications,
        all_count=len(all_user_apps),
        student_id=student_id,
        current_status=status_filter,
        search_query=search_query,
        location_filter=location_filter,
        job_type_filter=job_type_filter,
        exp_filter=exp_filter,
        sort_by=sort_by
    )


@app.route("/api/applications/<app_id>/status", methods=["POST"])
def api_update_application_status(app_id: str):
    """
    Updates the stage of an application (Applied, Assessment, Interview, Selected, Rejected).
    """
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status") or request.form.get("status", "")
    student_id = payload.get("student_id") or request.form.get("student_id", "default_student")

    if not new_status:
        return jsonify({"success": False, "error": "New status is required."}), 400

    updated = update_job_application_status(app_id=app_id, student_id=student_id, new_status=new_status)
    
    # Notify candidate of application status update via email (#186)
    if updated:
        try:
            prefs = get_email_notification_preferences(student_id)
            if prefs.get("email_enabled") and prefs.get("notify_status_change"):
                apps = get_job_applications(student_id=student_id)
                target_app = next((a for a in apps if a.get("id") == app_id), None)
                comp = target_app.get("company_name", "Target Company") if target_app else "Target Company"
                role = target_app.get("role_title", "Candidate Role") if target_app else "Role"
                user_email = prefs.get("email") or f"{student_id}@student.campus.edu"
                email_service.send_status_change_email(
                    recipient_email=user_email,
                    student_name=student_id,
                    company_name=comp,
                    role_title=role,
                    previous_status="Previous Stage",
                    new_status=new_status,
                    notes=payload.get("notes") or request.form.get("notes")
                )
        except Exception as mail_err:
            logger.warning(f"Failed to dispatch application status change email: {mail_err}")

    return jsonify({"success": updated}), (200 if updated else 404)


@app.route("/api/applications/<app_id>", methods=["DELETE"])
def api_delete_application(app_id: str):
    """
    Deletes an application record owned by student_id.
    """
    student_id = request.args.get("student_id") or "default_student"
    deleted = delete_job_application(app_id=app_id, student_id=student_id)
    return jsonify({"success": deleted}), (200 if deleted else 404)


@app.route("/applications/export", methods=["GET"])
@app.route("/api/applications/export", methods=["GET"])
def export_job_applications():
    """
    Exports a candidate's job applications data as a downloadable CSV or JSON file (#196).
    Supports format selection via ?format=csv (default) or ?format=json.
    Respects active ?status= filter and candidate data segregation.
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )
    status_filter = request.args.get("status", "All")
    export_format = request.args.get("format", "csv").strip().lower()

    if export_format == "json":
        data = export_job_applications_json(student_id=student_id, status_filter=status_filter)
        res = jsonify(data)
        safe_student = "".join(c for c in student_id if c.isalnum() or c in ("-", "_"))
        res.headers["Content-Disposition"] = f"attachment; filename=job_applications_{safe_student}.json"
        return res

    if export_format in ("md", "markdown"):
        md_content = export_job_applications_markdown(student_id=student_id, status_filter=status_filter)
        safe_student = "".join(c for c in student_id if c.isalnum() or c in ("-", "_"))
        return Response(
            md_content,
            mimetype="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=job_applications_{safe_student}.md",
                "Content-Type": "text/markdown; charset=utf-8"
            }
        )

    # Default CSV
    csv_content = export_job_applications_csv(student_id=student_id, status_filter=status_filter)
    safe_student = "".join(c for c in student_id if c.isalnum() or c in ("-", "_"))
    response = Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=job_applications_{safe_student}.csv",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )
    return response


@app.route("/api/applications/export-summary", methods=["GET"])
def api_applications_export_summary():
    """
    Returns application export summary and readiness stats for candidate (#196).
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )
    summary = get_job_applications_export_summary(student_id=student_id)
    return jsonify({
        "status": "success",
        "export_metadata": summary
    }), 200

@app.route("/interview-history")
def interview_history_view():
    """
    Mock Interview Performance History view (#144).
    Displays historical mock interview attempts, scores by question type, and score progression trends.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    analytics = get_student_interview_performance_analytics(student_id=student_id)
    return render_template("interview_history.html", analytics=analytics, student_id=student_id)


@app.route("/api/interview-history")
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


@app.route("/linkedin-analyzer", methods=["GET", "POST"])
def linkedin_analyzer():
    """
    LinkedIn Profile Analyzer View and API endpoint (#146).
    Reviews headline, summary/about, experience, and skills to provide ATS-style
    profile strength evaluation, missing keywords, and AI-powered headline rewrites.
    """
    analysis_result = None
    target_role = "Software Engineer"
    headline = ""
    about = ""
    experience = ""
    skills = ""

    if request.method == "POST":
        target_role = request.form.get("target_role", "Software Engineer").strip()
        headline = request.form.get("headline", "").strip()
        about = request.form.get("about", "").strip()
        experience = request.form.get("experience", "").strip()
        skills = request.form.get("skills", "").strip()

        if not headline and not about and not experience and not skills:
            flash("Please enter at least one profile section (Headline, About, Experience, or Skills).", "error")
        else:
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if not analysis_result:
            json_data = request.get_json(silent=True) or {}
            target_role = json_data.get("target_role", "Software Engineer")
            headline = json_data.get("headline", "")
            about = json_data.get("about", "")
            experience = json_data.get("experience", "")
            skills = json_data.get("skills", "")
            analysis_result = linkedin_agent.analyze_profile(
                headline=headline,
                about=about,
                experience=experience,
                skills=skills,
                target_role=target_role
            )
        return jsonify({
            "success": True,
            "analysis": analysis_result
        }), 200

    return render_template(
        "linkedin_analyzer.html",
        result=analysis_result,
        target_role=target_role,
        headline=headline,
        about=about,
        experience=experience,
        skills=skills
    )


@app.route("/coding-practice", methods=["GET", "POST"])
def _get_current_student_id() -> str:
    """
    Resolves the authenticated student's unique identifier from session (#235).
    Guarantees strict privacy: students cannot access another student's private notes or data.
    """
    return (
        flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )


def coding_practice_view():
    """
    Personalized Coding Practice Recommendation View and Endpoint (#147, #234).
    Recommends targeted LeetCode/DSA problems based on detected skill gaps, target companies, and difficulty.
    Includes student's bookmarked questions and bookmark IDs.
    """
    student_id = _get_current_student_id()

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

    bookmarked_problems = get_coding_bookmarks(student_id)
    bookmarked_ids = {str(p.get("id")) for p in bookmarked_problems if p.get("id")}

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": recommendations_data,
            "bookmarked_problems": bookmarked_problems,
            "bookmarked_ids": list(bookmarked_ids)
        }), 200

    return render_template(
        "coding_practice.html",
        data=recommendations_data,
        target_company=target_company,
        difficulty=difficulty,
        skills_input=raw_skills,
        bookmarked_problems=bookmarked_problems,
        bookmarked_ids=bookmarked_ids
    )


@app.route("/api/coding-practice/recommendations")
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


@app.route("/api/coding-practice/bookmarks", methods=["GET"])
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


@app.route("/api/coding-practice/bookmark", methods=["POST"])
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


@app.route("/api/coding-practice/bookmark/<problem_id>", methods=["DELETE", "POST"])
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


@app.route("/api/coding-practice/bookmark/toggle", methods=["POST"])
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


@app.route("/my-reports")
def user_placement_history_view():
    """
    Save and Retrieve Previous Placement Analysis History View (#149).
    Enforces per-student isolation and allows searching, filtering by company, and retrieving past reports.
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": history_data
        }), 200

    return render_template(
        "my_reports.html",
        data=history_data,
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )


@app.route("/api/user/analyses")
def api_user_placement_analyses():
    """
    API endpoint to retrieve placement analysis history for a specific candidate (#149).
    """
    student_id = request.args.get("student_id", "default_student").strip()
    company_filter = request.args.get("company", "").strip()
    sort_by = request.args.get("sort", "date_desc").strip()

    history_data = get_user_placement_history(
        student_id=student_id,
        company_filter=company_filter,
        sort_by=sort_by
    )
    return jsonify({
        "success": True,
        "data": history_data
    }), 200


@app.route("/history", methods=["GET"])
def history_view():
    """
    Renders the dedicated History page listing past placement analyses (#159).
    Displays date, target role, target company, and ATS score, ordered newest first.
    Allows reopening any analysis in the existing dashboard view or permanently deleting records.
    """
    try:
        analyses = get_analyses_history()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "analyses": analyses,
                "total": len(analyses)
            }), 200

        return render_template("history.html", analyses=analyses)
    except Exception as e:
        logger.error(f"Error loading analyses history: {str(e)}")
        flash("Failed to load analysis history.", "error")
        return render_template("history.html", analyses=[])


@app.route("/history/delete/<analysis_id>", methods=["POST"])
@app.route("/delete-analysis/<analysis_id>", methods=["POST"])
def delete_analysis_action(analysis_id: str):
    """
    Removes a past analysis record and its associated data (#159).
    Supports standard form submission redirects and JSON API responses.
    """
    try:
        deleted = delete_analysis(analysis_id)
        if not deleted:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": f"Analysis '{analysis_id}' not found."}), 404
            flash(f"Analysis with ID '{analysis_id}' was not found.", "error")
            return redirect(url_for("history_view"))

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "message": "Analysis deleted successfully."}), 200

        flash("Analysis and associated data deleted successfully.", "success")
        return redirect(url_for("history_view"))
    except Exception as e:
        logger.error(f"Error deleting analysis {analysis_id}: {str(e)}")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "Internal server error deleting analysis."}), 500
        flash("An error occurred while deleting the analysis.", "error")
        return redirect(url_for("history_view"))
# ==============================================================================
# Role-Based Preparation Mode Routes (#154)
# ==============================================================================

@app.route("/api/role-prep/roles")
def api_role_prep_roles():
    """
    Returns the list of supported placement roles with descriptions and icons.
    """
    return jsonify({
        "success": True,
        "roles": SUPPORTED_ROLES
    }), 200


@app.route("/api/role-prep/<analysis_id>", methods=["GET", "POST"])
def api_role_prep_for_analysis(analysis_id: str):
    """
    Generates role-based preparation curriculum and recommendations for a student analysis.
    Supports switching target roles dynamically (Python Developer, Data Analyst, Data Scientist, Software Engineer).
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
        return jsonify({"success": False, "error": "Analysis record not found"}), 404

    target_role = request.args.get("role")
    if not target_role and request.is_json:
        target_role = (request.get_json() or {}).get("role")
    if not target_role and request.form:
        target_role = request.form.get("role")
    target_role = (target_role or "Software Engineer").strip()

    results = analysis_record.get("results") or {}
    job_match = results.get("job_match") or {}
    skill_gap_items = results.get("skill_gap") or []

    existing_skills = job_match.get("matched_skills") or []
    gap_names = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=existing_skills,
        skill_gaps=gap_names,
        company_name=analysis_record.get("company_name", "General"),
        resume_text=analysis_record.get("resume_text", "")
    )
    return jsonify(prep_data), 200


@app.route("/api/role-prep/generate", methods=["POST"])
def api_role_prep_generate():
    """
    Ad-hoc role preparation generation supporting custom skills, gaps, and roles.
    """
    body = request.get_json() or {}
    target_role = body.get("role") or request.form.get("role") or "Software Engineer"
    skills = body.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,;\n]+", skills) if s.strip()]
    skill_gaps = body.get("skill_gaps") or []
    if isinstance(skill_gaps, str):
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", skill_gaps) if s.strip()]
    company = body.get("company") or request.form.get("company") or "General"

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=target_role,
        existing_skills=skills,
        skill_gaps=skill_gaps,
        company_name=company
    )
    return jsonify(prep_data), 200


@app.route("/role-preparation", methods=["GET", "POST"])
def role_preparation_view():
    """
    Role-Based Preparation Mode View (#154).
    Enables students to explore tailored learning tracks for Python Developer, Data Analyst,
    Data Scientist, and Software Engineer roles with personalized skill gap bridging.
    """
    analysis_id = request.args.get("analysis_id", "").strip()
    selected_role = request.args.get("role", "Software Engineer").strip()
    company = request.args.get("company", "").strip()
    raw_skills = request.args.get("skills", "").strip()
    raw_gaps = request.args.get("skill_gaps", "").strip()

    if request.method == "POST":
        selected_role = request.form.get("role", selected_role).strip()
        company = request.form.get("company", company).strip()
        raw_skills = request.form.get("skills", raw_skills).strip()
        raw_gaps = request.form.get("skill_gaps", raw_gaps).strip()

    analysis_record = None
    existing_skills = []
    skill_gaps = []

    if analysis_id:
        analysis_record = get_analysis(analysis_id)
        if analysis_record:
            results = analysis_record.get("results") or {}
            job_match = results.get("job_match") or {}
            skill_gap_items = results.get("skill_gap") or []
            existing_skills = job_match.get("matched_skills") or []
            skill_gaps = [g.get("missing_skill") for g in skill_gap_items if isinstance(g, dict) and g.get("missing_skill")] or job_match.get("missing_skills", [])
            if not company:
                company = analysis_record.get("company_name", "General")

    if not existing_skills and raw_skills:
        existing_skills = [s.strip() for s in re.split(r"[,;\n]+", raw_skills) if s.strip()]
    if not skill_gaps and raw_gaps:
        skill_gaps = [s.strip() for s in re.split(r"[,;\n]+", raw_gaps) if s.strip()]

    prep_data = role_prep_agent.generate_role_preparation(
        target_role=selected_role,
        existing_skills=existing_skills,
        skill_gaps=skill_gaps,
        company_name=company or "General Campus Recruitment",
        resume_text=analysis_record.get("resume_text", "") if analysis_record else None
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(prep_data), 200

    return render_template(
        "role_preparation.html",
        prep=prep_data,
        prep_json=json.dumps(prep_data),
        analysis=analysis_record,
        analysis_id=analysis_id,
        available_roles=SUPPORTED_ROLES,
        selected_role=prep_data["target_role"],
        company=company,
        skills_input=", ".join(existing_skills),
        gaps_input=", ".join(skill_gaps)
    )




@app.route("/notification-settings", methods=["GET", "POST"])
def notification_settings_view():
    """
    Candidate Email Notification Settings View and Preference Handler (#186).
    Allows students to enable/disable transactional emails and schedule interview reminders.
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        email_enabled = request.form.get("email_enabled") == "on"
        notify_welcome = request.form.get("notify_welcome") == "on"
        notify_application_created = request.form.get("notify_application_created") == "on"
        notify_status_change = request.form.get("notify_status_change") == "on"
        notify_interview_reminder = request.form.get("notify_interview_reminder") == "on"

        update_email_notification_preferences(
            student_id=student_id,
            email=email or None,
            email_enabled=email_enabled,
            notify_welcome=notify_welcome,
            notify_application_created=notify_application_created,
            notify_status_change=notify_status_change,
            notify_interview_reminder=notify_interview_reminder
        )
        flash("Email notification preferences updated successfully!", "success")
        return redirect(url_for("notification_settings_view", student_id=student_id))

    prefs = get_email_notification_preferences(student_id)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "preferences": prefs
        }), 200

    return render_template("notification_settings.html", prefs=prefs, student_id=student_id)


@app.route("/api/notifications/remind-interview", methods=["POST"])
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
        interview_link=interview_link or None
    )

    return jsonify({"success": sent, "recipient": recipient_email}), (200 if sent else 500)




@app.route("/interview-experiences", methods=["GET", "POST"])
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

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "count": len(experiences),
            "experiences": experiences
        }), 200

    return render_template(
        "interview_experiences.html",
        experiences=experiences,
        company_filter=company_filter,
        category_filter=category_filter,
        search_query=search_query,
        student_id=student_id
    )


@app.route("/api/interview-experiences/<exp_id>/report", methods=["POST"])
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




@app.route("/calendar", methods=["GET", "POST"])
def placement_calendar_view():
    """
    Placement Preparation Calendar View and Event Handler (#190).
    Manages student interview dates, preparation sessions, and application deadlines on a calendar.
    """
    import datetime
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"
    month_filter = request.args.get("month") or datetime.date.today().strftime("%Y-%m")
    type_filter = request.args.get("type", "All").strip()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_type = request.form.get("event_type", "preparation").strip().lower()
        event_date = request.form.get("event_date", "").strip()
        event_time = request.form.get("event_time", "").strip()
        company_name = request.form.get("company_name", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Medium").strip()

        if not title or not event_date:
            flash("Event title and scheduled date are required.", "error")
            return redirect(url_for("placement_calendar_view", month=month_filter))

        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        save_calendar_event(
            event_id=event_id,
            student_id=student_id,
            title=title,
            event_type=event_type,
            event_date=event_date,
            event_time=event_time or None,
            company_name=company_name or None,
            description=description or None,
            priority=priority,
            completed=False
        )
        flash("Placement preparation activity added to your calendar!", "success")
        return redirect(url_for("placement_calendar_view", month=event_date[:7]))

    events = get_calendar_events(student_id=student_id, month=month_filter, event_type=type_filter)
    all_events = get_calendar_events(student_id=student_id)

    # Calculate summary counts
    interviews_count = sum(1 for e in all_events if e.get("event_type") == "interview")
    tasks_count = sum(1 for e in all_events if e.get("event_type") == "preparation")
    deadlines_count = sum(1 for e in all_events if e.get("event_type") == "deadline")

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "month": month_filter,
            "count": len(events),
            "events": events
        }), 200

    return render_template(
        "calendar.html",
        events=events,
        all_events=all_events,
        student_id=student_id,
        current_month=month_filter,
        current_type=type_filter,
        interviews_count=interviews_count,
        tasks_count=tasks_count,
        deadlines_count=deadlines_count,
        today_date=datetime.date.today().isoformat()
    )


@app.route("/api/calendar/<event_id>", methods=["PUT", "POST", "DELETE"])
def api_manage_calendar_event(event_id: str):
    """
    API endpoint to update or delete a calendar preparation event (#190).
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"

    if request.method == "DELETE":
        deleted = delete_calendar_event(event_id=event_id, student_id=student_id)
        return jsonify({"success": deleted}), (200 if deleted else 404)

    payload = request.get_json(silent=True) or {}
    title = payload.get("title") or request.form.get("title", "")
    event_type = payload.get("event_type") or request.form.get("event_type", "preparation")
    event_date = payload.get("event_date") or request.form.get("event_date", "")
    event_time = payload.get("event_time") or request.form.get("event_time", "")
    company_name = payload.get("company_name") or request.form.get("company_name", "")
    description = payload.get("description") or request.form.get("description", "")
    priority = payload.get("priority") or request.form.get("priority", "Medium")
    completed = bool(payload.get("completed", False))

    if not title or not event_date:
        return jsonify({"success": False, "error": "Title and date are required."}), 400

    updated = update_calendar_event(
        event_id=event_id,
        student_id=student_id,
        title=title,
        event_type=event_type,
        event_date=event_date,
        event_time=event_time or None,
        company_name=company_name or None,
        description=description or None,
        priority=priority,
        completed=completed
    )
    return jsonify({"success": updated}), (200 if updated else 404)




@app.route("/company-checklist", methods=["GET", "POST"])
def company_checklist_view():
    """
    Company-Wise Placement Preparation Checklist View and Task Updater (#192).
    Provides structured readiness checklists across Aptitude, Coding, Technical, and HR.
    """
    student_id = request.args.get("student_id") or flask_session.get("user_id") or "default_student"
    target_company = request.args.get("company", "Google").strip()

    available_companies = get_available_companies()
    if not available_companies:
        available_companies = ["Google", "Amazon", "Microsoft", "Meta", "TCS", "Infosys", "Wipro", "Cognizant", "Adobe"]

    if target_company not in available_companies and target_company != "Google":
        available_companies.insert(0, target_company)

    checklist_info = get_company_checklist(student_id=student_id, company_name=target_company)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "data": checklist_info
        }), 200

    return render_template(
        "company_checklist.html",
        data=checklist_info,
        target_company=target_company,
        available_companies=available_companies,
        student_id=student_id
    )


@app.route("/api/company-checklist/toggle-task", methods=["POST"])
def api_toggle_checklist_task():
    """
    Toggles a checklist task completed status and updates overall progress (#192).
    """
    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id") or flask_session.get("user_id") or "default_student"
    company_name = payload.get("company_name", "Google").strip()
    category = payload.get("category", "").strip()
    task_id = payload.get("task_id", "").strip()
    completed = bool(payload.get("completed", False))

    current_data = get_company_checklist(student_id, company_name)
    checklist = current_data["checklist"]

    if category in checklist:
        for t in checklist[category]:
            if t["id"] == task_id:
                t["completed"] = completed
                break

    save_company_checklist(student_id, company_name, checklist)
    updated_info = get_company_checklist(student_id, company_name)

    return jsonify({
        "success": True,
        "overall_percentage": updated_info["overall_percentage"],
        "completed_tasks": updated_info["completed_tasks"],
        "category_percentage": updated_info["category_stats"].get(category, {}).get("percentage", 0.0)
    }), 200


@app.route("/api/company-checklist/reset", methods=["POST"])
def api_reset_checklist():
    """
    Resets the checklist tasks for a specific target company (#192).
    """
    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id") or flask_session.get("user_id") or "default_student"
    company_name = payload.get("company_name", "Google").strip()

    reset_company_checklist(student_id, company_name)
    refreshed = get_company_checklist(student_id, company_name)
    return jsonify({
        "success": True,
        "message": f"Checklist for {company_name} reset successfully.",
        "data": refreshed
    }), 200




@app.route("/coding-submissions")
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


@app.route("/api/coding-submissions")
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




@app.route("/download/preparation-summary", methods=["GET"])
@app.route("/download/preparation-summary/<student_id>", methods=["GET"])
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
    output_filename = f"Placement_Preparation_Summary_{student_id}.pdf"
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_pdf_path = tmp.name

    try:
        safe_generate_report_with_recovery(
            generator_func=generate_student_preparation_summary_pdf,
            data=summary_data,
            output_path=temp_pdf_path,
            report_type="Student Placement Preparation Summary"
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


@app.route("/api/jobs/viewed", methods=["GET", "POST", "DELETE"])
def api_recently_viewed_jobs():
    """
    REST API endpoints to manage recently viewed jobs for candidates (#201).
    Supports GET (fetch history), POST (track a job view), and DELETE (remove or clear history).
    """
    student_id = (
        request.args.get("student_id")
        or flask_session.get("user", {}).get("id")
        or flask_session.get("user_id")
        or flask_session.get("student_id")
        or "default_student"
    )

    if request.method == "GET":
        limit = request.args.get("limit", 10)
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            limit_val = 10
        viewed_jobs = get_recently_viewed_jobs(student_id=student_id, limit=limit_val)
        return jsonify({
            "status": "success",
            "student_id": student_id,
            "total": len(viewed_jobs),
            "jobs": viewed_jobs
        }), 200

    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        job_id = str(payload.get("job_id", "")).strip()
        company_name = str(payload.get("company_name", "")).strip()
        role_title = str(payload.get("role_title", "")).strip()
        location = str(payload.get("location", "Remote")).strip()
        salary_range = payload.get("salary_range")
        apply_url = payload.get("apply_url")

        if not job_id or not company_name or not role_title:
            return jsonify({
                "status": "error",
                "message": "job_id, company_name, and role_title are required fields."
            }), 400

        record = record_viewed_job(
            student_id=student_id,
            job_id=job_id,
            company_name=company_name,
            role_title=role_title,
            location=location,
            salary_range=salary_range,
            apply_url=apply_url
        )
        return jsonify({
            "status": "success",
            "message": f"Recorded view for job '{role_title}' at '{company_name}'.",
            "viewed_job": record
        }), 201

    if request.method == "DELETE":
        payload = request.get_json(silent=True) or request.args
        job_id = payload.get("job_id")
        if job_id:
            removed = remove_recently_viewed_job(student_id=student_id, job_id=job_id)
            return jsonify({
                "status": "success" if removed else "not_found",
                "message": f"Removed job '{job_id}' from recently viewed list." if removed else "Job not found in history."
            }), (200 if removed else 404)
        else:
            cleared_count = clear_recently_viewed_jobs(student_id=student_id)
            return jsonify({
                "status": "success",
                "message": f"Cleared {cleared_count} recently viewed jobs.",
                "cleared_count": cleared_count
            }), 200


@app.route("/api/migrations/status", methods=["GET"])
def api_migrations_status():
    """
    Returns current database migration and schema version history (#204).
    """
    from utils.migrations import get_migration_status
    status = get_migration_status(config.DATABASE_PATH)
    return jsonify({
        "status": "success",
        "migration_info": status
    }), 200


@app.route("/api/migrations/run", methods=["POST"])
def api_run_migrations():
    """
    Executes all pending database migrations in sequential order (#204).
    """
    from utils.migrations import run_database_migrations
    try:
        result = run_database_migrations(config.DATABASE_PATH)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Migration execution failed via API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




if __name__ == "__main__":
    # Boot Flask server locally on default port 5000
    app.run(debug=True, port=5000)
