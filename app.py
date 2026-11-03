import os
import uuid
import json
import time
import logging
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
)
from werkzeug.utils import secure_filename


import config
from utils.database import (
    init_db,
    get_db_connection,
    save_analysis,
    get_analysis,
    get_recent_analyses,
    delete_analysis,
    create_interview_session,
    get_interview_session,
    update_interview_session,
    get_student_versions,
    get_previous_analysis
)
from utils.progress_tracker import (
    calculate_version_delta,
    build_longitudinal_series,
    generate_side_by_side_diff
)
from utils.pdf_reader import (
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_file,
    validate_resume_text,
    MAX_RESUME_TEXT_CHARS,
    ALLOWED_RESUME_EXTENSIONS,
)
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
from agents.coordinator import CoordinatorAgent
from agents.interview_agent import InterviewAgent
from agents.coding_agent import CodingAssessmentAgent

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
    flash("Uploaded file exceeds the 16MB size limit. Please upload a smaller PDF.", "error")
    return redirect(url_for("index"))

# Ensure directories exist
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.REPORT_FOLDER, exist_ok=True)

# Run database schema migrations/initializations
try:
    init_db()
except Exception as db_err:
    logger.critical(f"Critical: Database initialization failed: {str(db_err)}")

# Instantiate coordination and specialized interview agents
coordinator_agent = CoordinatorAgent()
live_interview_agent = InterviewAgent()
coding_assessment_agent = CodingAssessmentAgent()

def get_available_companies() -> list:
    """
    Loads list of companies dynamically from data/companies.json with fallback defaults.
    """
    companies_file = config.BASE_DIR / "data" / "companies.json"
    default_companies = ["Google", "Microsoft", "Amazon", "TCS", "Infosys", "Accenture", "Capgemini", "Wipro"]
    try:
        if companies_file.exists():
            with open(companies_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return sorted(list(data.keys()))
    except Exception as e:
        logger.warning(f"Could not load dynamic companies from {companies_file}: {e}")
    return default_companies


@app.route("/api/health")
@app.route("/health")
def health_check():
    """
    Health check endpoint verifying application uptime and database connectivity.
    """
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_status = "connected"
    except Exception as db_err:
        logger.error(f"Healthcheck database error: {str(db_err)}")
        db_status = f"unhealthy: {str(db_err)}"

    status_code = 200 if db_status == "connected" else 503
    return (
        jsonify(
            {
                "status": "healthy" if status_code == 200 else "degraded",
                "version": config.__version__,
                "database": db_status,
            }
        ),
        status_code,
    )

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
        if not any(filename_lower.endswith(ext) for ext in ALLOWED_RESUME_EXTENSIONS):
            return (
                None,
                None,
                None,
                "Invalid file format. Only PDF (.pdf) and Word (.docx) resumes are supported.",
            )
        resume_filename = uploaded_file.filename
        safe_name = secure_filename(f"{file_uuid}_{uploaded_file.filename}")
        saved_file_path = os.path.join(config.UPLOAD_FOLDER, safe_name)
        uploaded_file.save(saved_file_path)
        logger.info(f"Uploaded resume saved locally at: {saved_file_path}")
        extracted_resume_text = extract_text_from_file(saved_file_path)
        return extracted_resume_text, resume_filename, file_uuid, None
    else:
        return None, None, None, "Please upload a PDF resume or paste your resume text."


@app.route("/analyze", methods=["POST"])
@rate_limit(max_requests=15, window_seconds=60, scope="analyze_submission", is_api=False)
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
        student_id = request.form.get("student_id", "default_student").strip()
        if len(job_description) > 15000:
            job_description = job_description[:15000]

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
            student_id=candidate_student_id
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
        student_id = request.form.get("student_id", "default_student").strip()
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

@app.route("/dashboard/<analysis_id>")
def dashboard(analysis_id: str) -> str:
    """
    Loads and renders the candidate evaluation dashboard with longitudinal
    progress trends and multi-version delta analysis.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
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

    return render_template(
        "dashboard.html",
        analysis=analysis_record,
        analysis_id=analysis_id,
        versions=all_versions,
        current_version=current_version,
        previous_record=previous_record,
        delta_data=delta_data,
        trend_series=trend_series,
        trend_series_json=json.dumps(trend_series)
    )

@app.route("/interview/<analysis_id>")
def interview(analysis_id: str) -> str:
    """
    Bootstraps or loads an existing interactive mock interview session.
    Supports optional ?round=HR|Technical|Behavioral filter to practice focused rounds.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
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
@rate_limit(max_requests=30, window_seconds=60, scope="interview_eval", is_api=True)
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
        if not company_name and analysis_id:
            record = get_analysis(analysis_id)
            if record:
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

        if not isinstance(problem, dict) or not problem:
            company = "General"
            if analysis_id:
                rec = get_analysis(analysis_id)
                if rec:
                    company = rec.get("company_name", "General")
            problem = coding_assessment_agent.get_fallback_problem(company)

        eval_result = coding_assessment_agent.evaluate_code(
            problem=problem,
            language=language,
            code=code
        )

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


@app.route("/certificate/<analysis_id>")
def certificate(analysis_id: str):
    """
    Renders printable placement readiness completion certificate.
    """
    analysis_record = get_analysis(analysis_id)
    if not analysis_record:
        flash("The requested placement analysis report could not be found.", "error")
        return redirect(url_for("index"))

    return render_template(
        "certificate.html",
        analysis=analysis_record,
        analysis_id=analysis_id,
    )

@app.route("/download/<analysis_id>")
def download_pdf_report(analysis_id: str):
    """
    Compiles placement metrics into a ReportLab PDF and downloads the file.
    """
    try:
        analysis_record = get_analysis(analysis_id)
        if not analysis_record:
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

@app.route("/api/analyses/recent", methods=["GET"])
def api_recent_analyses():
    """
    Returns a list of recent placement analyses ordered by timestamp descending.
    """
    try:
        limit = request.args.get("limit", default=10, type=int)
        analyses = get_recent_analyses(limit=limit)
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
        if not rec_a or not rec_b:
            return jsonify({"status": "error", "message": "One or both analysis records not found."}), 404

        diff = generate_side_by_side_diff(rec_a, rec_b)
        return jsonify({
            "status": "success",
            "diff": diff
        }), 200
    except Exception as e:
        logger.error(f"Error computing diff between {id_a} and {id_b}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/healthz", methods=["GET"], endpoint="healthz")
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


if __name__ == "__main__":
    # Boot Flask server locally on default port 5000
    app.run(debug=True, port=5000)
