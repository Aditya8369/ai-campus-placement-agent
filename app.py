"""
Main application entry point for AI Campus Placement Agent.
Exports `app = create_app()` for WSGI servers and local development (#553).
"""

from routes import create_app
from routes.common import (
    APPLICATION_STAGES,
    WALKTHROUGH_STEPS_CATALOG,
    get_available_companies,
    coordinator_agent,
    live_interview_agent,
    save_resume_review_cache,
    get_resume_review_cache,
    _is_student_authorized,
    _extract_and_validate_resume,
    get_analysis,
    get_db_connection,
    get_valid_password_reset_token,
    extract_text_from_file,
)

app = create_app()

__all__ = [
    "app",
    "create_app",
    "APPLICATION_STAGES",
    "WALKTHROUGH_STEPS_CATALOG",
    "get_available_companies",
    "coordinator_agent",
    "live_interview_agent",
    "save_resume_review_cache",
    "get_resume_review_cache",
    "_is_student_authorized",
    "_extract_and_validate_resume",
    "get_analysis",
    "get_db_connection",
    "get_valid_password_reset_token",
    "extract_text_from_file",
]

if __name__ == "__main__":
    app.run(debug=True, port=5000)
