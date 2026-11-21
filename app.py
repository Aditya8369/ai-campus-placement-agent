from flask import Flask, jsonify, request
from utils.database import get_analysis_by_id, update_analysis_section
from utils.section_retry import (
    SUPPORTED_SECTIONS,
    SectionRetryError,
    regenerate_failed_section,
)


@app.route("/api/analysis/<analysis_id>/retry-section", methods=["POST"])
@limiter.limit(getattr(Config, "RATE_LIMIT_SECTION_RETRY", "15/hour"))
def retry_failed_analysis_section(analysis_id: str):
    """
    Regenerates a single failed section of an existing analysis without
    re-running the entire multi-agent pipeline or altering other sections.
    """
    body = request.get_json(silent=True) or {}
    section_key = (body.get("section") or request.form.get("section") or "").strip()

    if not section_key or section_key not in SUPPORTED_SECTIONS:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Invalid Section",
                    "message": (
                        f"Unsupported section '{section_key}'. "
                        f"Valid options: {', '.join(SUPPORTED_SECTIONS.keys())}."
                    ),
                }
            ),
            400,
        )

    analysis_record = get_analysis_by_id(analysis_id)
    if not analysis_record:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Not Found",
                    "message": "The requested placement analysis record could not be found.",
                }
            ),
            404,
        )

    try:
        db_key, regenerated_data, ai_meta = regenerate_failed_section(
            analysis_record=analysis_record,
            section_key=section_key,
        )
        updated_payload = update_analysis_section(
            analysis_id=analysis_id,
            section_db_key=db_key,
            section_payload=regenerated_data,
            section_key=section_key,
        )

        # Include rate-limit window info so the user knows when subsequent AI calls can be made
        rate_limit_info = {
            "quota": getattr(Config, "RATE_LIMIT_SECTION_RETRY", "15/hour"),
            "next_request_allowed": True,
            "cooldown_seconds": 0,
            "guidance": (
                "A new Gemini AI request was just completed. You may retry another failed "
                "section immediately within your hourly quota."
            ),
        }

        return (
            jsonify(
                {
                    "success": True,
                    "analysis_id": analysis_id,
                    "section": section_key,
                    "db_key": db_key,
                    "data": regenerated_data,
                    "failed_sections": updated_payload.get("failed_sections", {}),
                    "ai_request": ai_meta,
                    "rate_limit": rate_limit_info,
                }
            ),
            200,
        )

    except SectionRetryError as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Section Retry Failed",
                    "message": exc.message,
                    "ai_request": {
                        "ai_request_made": False,
                        "section": section_key,
                    },
                }
            ),
            exc.status_code,
        )
    except Exception as exc:
        app.logger.exception(
            "Unexpected error retrying section=%s for analysis_id=%s",
            section_key,
            analysis_id,
        )
        return (
            jsonify(
                {
                    "success": False,
                    "error": "AI Service Unavailable",
                    "message": (
                        "The AI service encountered an error while regenerating this section. "
                        "Your existing sections remain intact. Please try again in a minute."
                    ),
                    "retry_after_seconds": 60,
                    "retry_after_hint": "You may make a new AI request in 60 seconds.",
                }
            ),
            503,
        )