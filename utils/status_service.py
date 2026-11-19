"""
Public Service Status and Diagnostic Health Service (#460).
============================================================
Collects and aggregates real-time operational status for core application services:
1. Application & Web Runtime (storage write permissions, environment, uptime)
2. Database (SQLite connectivity, read query probe, latency in ms)
3. AI Integration (Google Gemini API configuration status, client readiness, demo fallback mode)

Security & Secrets Policy:
- Absolutely no API keys, secret tokens, database credentials, or sensitive server paths are exposed.
- All diagnostics provide safe, standardized health signals ("operational", "degraded", "unavailable").
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

import config
from utils.database import get_db_connection
from utils.gemini import scrub_api_key

logger = logging.getLogger(__name__)

# Track process startup timestamp for uptime calculations
_PROCESS_START_TIME = time.time()


def check_application_service() -> Dict[str, Any]:
    """
    Evaluates Application and Web Runtime service health.
    Verifies storage folder availability and writability (uploads & reports).
    """
    try:
        upload_folder = getattr(config, "UPLOAD_FOLDER", "uploads")
        report_folder = getattr(config, "REPORT_FOLDER", "reports")

        # Ensure directories exist if possible
        try:
            os.makedirs(upload_folder, exist_ok=True)
            os.makedirs(report_folder, exist_ok=True)
        except Exception:
            pass

        uploads_ok = os.path.exists(upload_folder) and os.access(upload_folder, os.W_OK)
        reports_ok = os.path.exists(report_folder) and os.access(report_folder, os.W_OK)

        storage_healthy = uploads_ok and reports_ok
        status = "operational" if storage_healthy else "degraded"

        environment = "testing" if getattr(config, "TESTING", False) else (
            "production" if os.environ.get("VERCEL") or os.environ.get("FLASK_ENV") == "production" else "development"
        )

        uptime_seconds = int(time.time() - _PROCESS_START_TIME)

        details = {
            "storage_status": "operational" if storage_healthy else "degraded",
            "uploads_writable": uploads_ok,
            "reports_writable": reports_ok,
            "environment": environment,
            "uptime_seconds": uptime_seconds,
        }

        return {
            "name": "Application & Web Runtime",
            "status": status,
            "description": "Flask web server, routing, session management, and template rendering",
            "details": details,
        }
    except Exception as exc:
        logger.error(f"Application service health probe failed: {exc}", exc_info=True)
        return {
            "name": "Application & Web Runtime",
            "status": "unavailable",
            "description": "Flask web server, routing, session management, and template rendering",
            "details": {
                "error": "Application runtime check failed",
                "storage_status": "unavailable",
            },
        }


def check_database_service() -> Dict[str, Any]:
    """
    Evaluates Database health by executing a ping probe query on SQLite.
    Measures query latency in milliseconds.
    """
    t_start = time.time()
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        finally:
            conn.close()

        latency_ms = round((time.time() - t_start) * 1000, 2)
        return {
            "name": "Database (SQLite)",
            "status": "operational",
            "description": "Primary relational database for user analyses, interviews, applications, and notes",
            "latency_ms": latency_ms,
            "details": {
                "engine": "sqlite",
                "connectivity": "connected",
            },
        }
    except Exception as exc:
        clean_err = scrub_api_key(str(exc))
        logger.error(f"Database status check failed: {clean_err}")
        latency_ms = round((time.time() - t_start) * 1000, 2)
        return {
            "name": "Database (SQLite)",
            "status": "unavailable",
            "description": "Primary relational database for user analyses, interviews, applications, and notes",
            "latency_ms": latency_ms,
            "details": {
                "engine": "sqlite",
                "connectivity": "disconnected",
                "error": "Database connectivity failed",
            },
        }


def check_ai_service(timeout: float = 2.0) -> Dict[str, Any]:
    """
    Evaluates AI Integration service health (Google Gemini).
    Verifies API key configuration and client instantiation without invoking paid tokens.
    Guarantees secrets/keys are never exposed in output.
    """
    api_key = getattr(config, "GEMINI_API_KEY", None)
    model_name = getattr(config, "GEMINI_MODEL_NAME", "gemini-1.5-flash")

    # If key is missing, empty, or default template placeholder:
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        return {
            "name": "AI Integration (Google Gemini)",
            "status": "degraded",
            "description": "Multi-agent resume analysis, STAR interview coaching, and placement guidance",
            "details": {
                "provider": "Google Gemini",
                "model": model_name,
                "configured": False,
                "mode": "demo_fallback",
                "fallback_available": True,
                "message": (
                    "Live Gemini API key is not configured. The platform is running with "
                    "deterministic scoring heuristics and synthetic demo mode."
                ),
            },
        }

    # If key is provided, test client initialization safely
    try:
        from utils.gemini import get_gemini_client
        client = get_gemini_client(timeout=timeout)
        if client is not None:
            return {
                "name": "AI Integration (Google Gemini)",
                "status": "operational",
                "description": "Multi-agent resume analysis, STAR interview coaching, and placement guidance",
                "details": {
                    "provider": "Google Gemini",
                    "model": model_name,
                    "configured": True,
                    "mode": "live",
                    "fallback_available": True,
                    "message": "AI multi-agent coordinator and evaluators ready.",
                },
            }
        else:
            return {
                "name": "AI Integration (Google Gemini)",
                "status": "degraded",
                "description": "Multi-agent resume analysis, STAR interview coaching, and placement guidance",
                "details": {
                    "provider": "Google Gemini",
                    "model": model_name,
                    "configured": True,
                    "mode": "demo_fallback",
                    "fallback_available": True,
                    "message": "Client initialized in fallback mode.",
                },
            }
    except Exception as exc:
        clean_err = scrub_api_key(str(exc))
        logger.warning(f"AI service status check failed initialization: {clean_err}")
        return {
            "name": "AI Integration (Google Gemini)",
            "status": "unavailable",
            "description": "Multi-agent resume analysis, STAR interview coaching, and placement guidance",
            "details": {
                "provider": "Google Gemini",
                "model": model_name,
                "configured": True,
                "mode": "error",
                "fallback_available": True,
                "message": "AI client initialization encountered an error.",
            },
        }


def get_system_status() -> Tuple[Dict[str, Any], int]:
    """
    Gathers health reports from all core services and computes overall status.

    Returns:
        tuple: (status_payload_dict, http_status_code)
    """
    t_start = time.time()

    app_service = check_application_service()
    db_service = check_database_service()
    ai_service = check_ai_service()

    total_time_ms = round((time.time() - t_start) * 1000, 2)
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    # Determine aggregated status
    # 1. Critical outage: Database or Application core down
    if db_service["status"] == "unavailable" or app_service["status"] == "unavailable":
        overall_status = "unavailable"
        status_message = "Major Service Outage - Primary database or application runtime is unavailable."
        http_code = 503
    # 2. Degraded: AI unconfigured/fallback mode or storage degraded
    elif (
        ai_service["status"] in ("degraded", "unavailable")
        or app_service["status"] == "degraded"
        or db_service["status"] == "degraded"
    ):
        overall_status = "degraded"
        status_message = "Some Services Degraded - Application is operational with fallback capabilities."
        http_code = 200
    # 3. All operational
    else:
        overall_status = "operational"
        status_message = "All Systems Operational - Application, database, and AI integrations are fully functional."
        http_code = 200

    payload = {
        "status": overall_status,
        "status_message": status_message,
        "timestamp": timestamp_utc,
        "response_time_ms": total_time_ms,
        "services": {
            "application": app_service,
            "database": db_service,
            "ai_integration": ai_service,
        },
    }

    return payload, http_code
