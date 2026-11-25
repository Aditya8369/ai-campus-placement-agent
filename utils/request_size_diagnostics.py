"""
API Request Size Diagnostics & Enforcement Service (#784).
==========================================================
Provides comprehensive request-size limit enforcement and diagnostics for:
- JSON request bodies and individual JSON fields
- Uploaded multipart files (resumes, CSV imports, documents)
- Field-specific diagnostic error responses containing maximum allowed size
- Structured failure logging correlated with a unique Request ID
- Real-time diagnostics metrics for maintainers and observability
"""

import collections
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Request, Response, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

import config

logger = logging.getLogger(__name__)

# Ring buffer for retaining recent size failure incidents (in-memory diagnostics)
MAX_DIAGNOSTICS_RECORDS = 200
_DIAGNOSTICS_RECORDS: collections.deque = collections.deque(maxlen=MAX_DIAGNOSTICS_RECORDS)


def format_size_bytes(bytes_count: int) -> str:
    """Formats raw byte count into human-readable string (e.g., '5 MB', '250 KB')."""
    if bytes_count is None:
        return "0 B"
    b = float(bytes_count)
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024 * 1024):.1f} GB".replace(".0 GB", " GB")
    if b >= 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB".replace(".0 MB", " MB")
    if b >= 1024:
        return f"{b / 1024:.1f} KB".replace(".0 KB", " KB")
    return f"{int(b)} B"


def get_configured_limits() -> Dict[str, Any]:
    """Retrieves authoritative size limit settings from environment and config."""
    max_upload_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)
    max_resume_bytes = getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", max_upload_mb * 1024 * 1024)
    max_json_bytes = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
    max_csv_bytes = getattr(config, "MAX_CSV_FILE_SIZE_BYTES", 5 * 1024 * 1024)
    max_content_length = getattr(config, "MAX_CONTENT_LENGTH", max_resume_bytes + 2 * 1024 * 1024)

    return {
        "max_upload_size_mb": max_upload_mb,
        "max_resume_file_size_bytes": max_resume_bytes,
        "max_resume_file_size_human": format_size_bytes(max_resume_bytes),
        "max_json_payload_bytes": max_json_bytes,
        "max_json_payload_human": format_size_bytes(max_json_bytes),
        "max_csv_file_size_bytes": max_csv_bytes,
        "max_csv_file_size_human": format_size_bytes(max_csv_bytes),
        "max_content_length_bytes": max_content_length,
        "max_content_length_human": format_size_bytes(max_content_length),
    }


# Field-specific size limit catalog
# Identifies max allowed sizes for specific upload file fields and text/JSON keys.
FIELD_SIZE_LIMITS: Dict[str, Dict[str, Any]] = {
    # File uploads
    "resume": {
        "type": "file",
        "get_limit_bytes": lambda: getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 5 * 1024 * 1024),
        "description": "Resume document (PDF/Word)",
    },
    "resume_v1": {
        "type": "file",
        "get_limit_bytes": lambda: getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 5 * 1024 * 1024),
        "description": "Baseline resume document (PDF/Word)",
    },
    "resume_v2": {
        "type": "file",
        "get_limit_bytes": lambda: getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 5 * 1024 * 1024),
        "description": "Comparison resume document (PDF/Word)",
    },
    "file": {
        "type": "file",
        "get_limit_bytes": lambda: getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 5 * 1024 * 1024),
        "description": "General uploaded file or document",
    },
    "csv_file": {
        "type": "file",
        "get_limit_bytes": lambda: getattr(config, "MAX_CSV_FILE_SIZE_BYTES", 5 * 1024 * 1024),
        "description": "Job application import CSV file",
    },
    # JSON / Text input fields
    "resume_text": {
        "type": "text",
        "get_limit_bytes": lambda: 500 * 1024,  # 500 KB (~500,000 characters)
        "description": "Raw resume text string",
    },
    "extracted_text": {
        "type": "text",
        "get_limit_bytes": lambda: 500 * 1024,
        "description": "Extracted resume content string",
    },
    "job_description": {
        "type": "text",
        "get_limit_bytes": lambda: 200 * 1024,  # 200 KB
        "description": "Job description match text",
    },
    "cover_letter": {
        "type": "text",
        "get_limit_bytes": lambda: 100 * 1024,  # 100 KB
        "description": "Cover letter body text",
    },
    "content": {
        "type": "text",
        "get_limit_bytes": lambda: 200 * 1024,  # 200 KB
        "description": "Document or note content string",
    },
    "code": {
        "type": "text",
        "get_limit_bytes": lambda: 150 * 1024,  # 150 KB
        "description": "Source code solution",
    },
    "notes": {
        "type": "text",
        "get_limit_bytes": lambda: 100 * 1024,  # 100 KB
        "description": "Application or interview notes",
    },
}


class RequestSizeLimitExceeded(RequestEntityTooLarge):
    """
    Subclass of Werkzeug RequestEntityTooLarge carrying rich diagnostic metadata:
    the violating field, max allowed size, received size, and human-readable explanation.
    """

    def __init__(
        self,
        field: str,
        max_allowed_size_bytes: int,
        received_size_bytes: int,
        field_type: str = "payload",
        filename: Optional[str] = None,
        custom_message: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        self.field = field
        self.field_type = field_type
        self.max_allowed_size_bytes = max_allowed_size_bytes
        self.max_allowed_size = format_size_bytes(max_allowed_size_bytes)
        self.received_size_bytes = received_size_bytes
        self.received_size = format_size_bytes(received_size_bytes)
        self.filename = filename
        self.request_id = request_id

        if custom_message:
            self.message = custom_message
        elif field_type == "file":
            fn_suffix = f" ('{filename}')" if filename else ""
            self.message = (
                f"The uploaded file for '{field}'{fn_suffix} ({self.received_size}) "
                f"exceeds the maximum allowed size of {self.max_allowed_size}."
            )
        elif field_type == "json":
            self.message = (
                f"The JSON request payload ({self.received_size}) "
                f"exceeds the maximum allowed size of {self.max_allowed_size}."
            )
        else:
            self.message = (
                f"The field '{field}' ({self.received_size}) "
                f"exceeds the maximum allowed size of {self.max_allowed_size}."
            )

        super().__init__(description=self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Returns structured dictionary representation of the size violation."""
        return {
            "field": self.field,
            "field_type": self.field_type,
            "filename": self.filename,
            "max_allowed_size": self.max_allowed_size,
            "max_allowed_size_bytes": self.max_allowed_size_bytes,
            "received_size": self.received_size,
            "received_size_bytes": self.received_size_bytes,
            "message": self.message,
            "request_id": self.request_id,
        }


def get_field_limit(field_name: str, field_type: str = "file") -> Tuple[int, str]:
    """Retrieves the maximum allowed bytes and human-readable size for a field."""
    entry = FIELD_SIZE_LIMITS.get(field_name)
    if entry:
        limit_bytes = entry["get_limit_bytes"]()
        return limit_bytes, format_size_bytes(limit_bytes)

    if field_type == "file":
        max_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)
        limit_bytes = getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", max_mb * 1024 * 1024)
        return limit_bytes, format_size_bytes(limit_bytes)
    elif field_type == "json":
        limit_bytes = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
        return limit_bytes, format_size_bytes(limit_bytes)
    else:
        limit_bytes = 100 * 1024
        return limit_bytes, format_size_bytes(limit_bytes)


def validate_request_size(req: Request) -> Optional[Dict[str, Any]]:
    """
    Validates an incoming Flask request against configured JSON and file size limits.
    Returns None if valid, or a structured error_info dictionary if any limit is exceeded.
    """
    max_json_bytes = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
    content_length = req.content_length

    # 1. Content-Length check for JSON requests
    if req.is_json and content_length is not None and content_length > max_json_bytes:
        return {
            "field": "json_body",
            "field_type": "json",
            "filename": None,
            "max_allowed_size_bytes": max_json_bytes,
            "max_allowed_size": format_size_bytes(max_json_bytes),
            "received_size_bytes": content_length,
            "received_size": format_size_bytes(content_length),
            "message": (
                f"The JSON request payload ({format_size_bytes(content_length)}) "
                f"exceeds the maximum allowed size of {format_size_bytes(max_json_bytes)}."
            ),
        }

    # 2. Uploaded File Size Check (via req.files)
    try:
        if req.files:
            for field_name, file_storage in req.files.items():
                if file_storage and getattr(file_storage, "filename", None):
                    # Measure file size without consuming file pointer
                    file_storage.seek(0, os.SEEK_END)
                    file_size = file_storage.tell()
                    file_storage.seek(0)

                    limit_bytes, limit_human = get_field_limit(field_name, field_type="file")
                    if file_size > limit_bytes:
                        return {
                            "field": field_name,
                            "field_type": "file",
                            "filename": file_storage.filename,
                            "max_allowed_size_bytes": limit_bytes,
                            "max_allowed_size": limit_human,
                            "received_size_bytes": file_size,
                            "received_size": format_size_bytes(file_size),
                            "message": (
                                f"The uploaded file for '{field_name}' ('{file_storage.filename}', {format_size_bytes(file_size)}) "
                                f"exceeds the maximum allowed size of {limit_human}."
                            ),
                        }
    except Exception as exc:
        logger.debug(f"File size inspection bypassed due to: {exc}")

    # 3. Text field inspection for JSON payloads
    if req.is_json:
        try:
            data = req.get_json(silent=True)
            if isinstance(data, dict):
                # Check entire raw body byte size if content_length was absent
                if content_length is None:
                    try:
                        raw_len = len(req.get_data())
                        if raw_len > max_json_bytes:
                            return {
                                "field": "json_body",
                                "field_type": "json",
                                "filename": None,
                                "max_allowed_size_bytes": max_json_bytes,
                                "max_allowed_size": format_size_bytes(max_json_bytes),
                                "received_size_bytes": raw_len,
                                "received_size": format_size_bytes(raw_len),
                                "message": (
                                    f"The JSON request payload ({format_size_bytes(raw_len)}) "
                                    f"exceeds the maximum allowed size of {format_size_bytes(max_json_bytes)}."
                                ),
                            }
                    except Exception:
                        pass

                # Check individual text fields against field limits
                for field_name, val in data.items():
                    if field_name in FIELD_SIZE_LIMITS and isinstance(val, str):
                        limit_bytes, limit_human = get_field_limit(field_name, field_type="text")
                        val_bytes = len(val.encode("utf-8", errors="ignore"))
                        if val_bytes > limit_bytes:
                            return {
                                "field": field_name,
                                "field_type": "text",
                                "filename": None,
                                "max_allowed_size_bytes": limit_bytes,
                                "max_allowed_size": limit_human,
                                "received_size_bytes": val_bytes,
                                "received_size": format_size_bytes(val_bytes),
                                "message": (
                                    f"The field '{field_name}' ({format_size_bytes(val_bytes)}) "
                                    f"exceeds the maximum allowed size of {limit_human}."
                                ),
                            }
        except Exception:
            pass

    return None


def resolve_request_id(req: Optional[Request] = None, explicit_id: Optional[str] = None) -> str:
    """Extracts or assigns a consistent correlation request ID."""
    if explicit_id and explicit_id.strip() != "-":
        return explicit_id.strip()

    try:
        from utils.logger_config import get_current_request_id
        active = get_current_request_id()
        if active and active != "-":
            return active
    except Exception:
        pass

    try:
        from flask import g
        g_id = getattr(g, "request_id", None)
        if g_id and g_id != "-":
            return g_id
    except Exception:
        pass

    if req is not None:
        header_id = req.headers.get("X-Request-ID")
        if header_id:
            return header_id.strip()

    new_id = str(uuid.uuid4())
    try:
        from flask import g
        g.request_id = new_id
    except Exception:
        pass
    return new_id


def log_size_failure(
    error_info: Dict[str, Any],
    req: Optional[Request] = None,
    request_id: Optional[str] = None,
) -> str:
    """
    Logs request size violations with structured key=values and correlation Request ID (#301, #784).
    Records incident in in-memory diagnostics ring buffer.
    """
    req_id = resolve_request_id(req, request_id)
    error_info["request_id"] = req_id

    endpoint = req.path if req else "unknown"
    method = req.method if req else "POST"
    field = error_info.get("field", "payload")
    field_type = error_info.get("field_type", "payload")
    rec_bytes = error_info.get("received_size_bytes", 0)
    max_bytes = error_info.get("max_allowed_size_bytes", 0)
    rec_human = error_info.get("received_size", format_size_bytes(rec_bytes))
    max_human = error_info.get("max_allowed_size", format_size_bytes(max_bytes))
    filename = error_info.get("filename")

    client_ip = "-"
    user_id = "anonymous"
    if req:
        client_ip = req.headers.get("X-Forwarded-For", req.remote_addr) or "-"
        try:
            from flask import session as flask_session
            user_id = flask_session.get("user_id") or "anonymous"
        except Exception:
            user_id = "anonymous"

    # Structured failure log with Request ID (#301, #784)
    logger.warning(
        f"Request size limit exceeded: request_id=\"{req_id}\" endpoint=\"{endpoint}\" "
        f"method=\"{method}\" field=\"{field}\" field_type=\"{field_type}\" "
        f"received_bytes={rec_bytes} ({rec_human}) max_allowed_bytes={max_bytes} ({max_human}) "
        f"filename=\"{filename or '-'}\" client_ip=\"{client_ip}\" user_id=\"{user_id}\""
    )

    # Record in memory diagnostics ring buffer
    try:
        incident = {
            "request_id": req_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "http_method": method,
            "field": field,
            "field_type": field_type,
            "filename": filename,
            "received_size_bytes": rec_bytes,
            "received_size": rec_human,
            "max_allowed_size_bytes": max_bytes,
            "max_allowed_size": max_human,
            "client_ip": client_ip,
            "user_id": user_id,
            "message": error_info.get("message"),
        }
        _DIAGNOSTICS_RECORDS.appendleft(incident)
    except Exception:
        pass

    return req_id


def build_size_error_response(
    error_info: Dict[str, Any],
    req: Optional[Request] = None,
    status_code: int = 413,
) -> Tuple[Response, int]:
    """
    Constructs an RFC-compliant HTTP 413 JSON response containing field-specific error details,
    maximum allowed size, and Request ID headers.
    """
    req_id = log_size_failure(error_info, req)

    payload = {
        "success": False,
        "error": error_info["message"],
        "code": "REQUEST_ENTITY_TOO_LARGE",
        "error_code": "PAYLOAD_TOO_LARGE",
        "request_id": req_id,
        "field": error_info["field"],
        "field_type": error_info.get("field_type", "payload"),
        "max_allowed_size": error_info["max_allowed_size"],
        "max_allowed_size_bytes": error_info["max_allowed_size_bytes"],
        "received_size": error_info["received_size"],
        "received_size_bytes": error_info["received_size_bytes"],
        "details": {
            "field": error_info["field"],
            "field_type": error_info.get("field_type", "payload"),
            "filename": error_info.get("filename"),
            "max_allowed_size": error_info["max_allowed_size"],
            "max_allowed_size_bytes": error_info["max_allowed_size_bytes"],
            "received_size": error_info["received_size"],
            "received_size_bytes": error_info["received_size_bytes"],
            "message": error_info["message"],
        },
    }

    resp = jsonify(payload)
    resp.status_code = status_code
    resp.headers["X-Request-ID"] = req_id
    resp.headers["X-Max-Allowed-Size"] = str(error_info["max_allowed_size_bytes"])
    resp.headers["X-Request-Size-Limit"] = error_info["max_allowed_size"]
    return resp, status_code


def diagnose_413_exception(exc: Exception, req: Request) -> Dict[str, Any]:
    """
    Analyzes an unhandled 413 exception from Werkzeug, inspecting the request
    to pinpoint the specific offending field, file, or JSON body.
    """
    # 1. If exception is already a RequestSizeLimitExceeded instance
    if isinstance(exc, RequestSizeLimitExceeded):
        return exc.to_dict()

    # 2. Inspect request files if available
    try:
        if req.files:
            for field_name, file_storage in req.files.items():
                if file_storage and getattr(file_storage, "filename", None):
                    file_storage.seek(0, os.SEEK_END)
                    file_size = file_storage.tell()
                    file_storage.seek(0)
                    limit_bytes, limit_human = get_field_limit(field_name, "file")
                    if file_size > limit_bytes:
                        return {
                            "field": field_name,
                            "field_type": "file",
                            "filename": file_storage.filename,
                            "max_allowed_size_bytes": limit_bytes,
                            "max_allowed_size": limit_human,
                            "received_size_bytes": file_size,
                            "received_size": format_size_bytes(file_size),
                            "message": (
                                f"The uploaded file for '{field_name}' ('{file_storage.filename}', {format_size_bytes(file_size)}) "
                                f"exceeds the maximum allowed size of {limit_human}."
                            ),
                        }
    except Exception:
        pass

    # 3. Check JSON request body
    content_length = req.content_length or 0
    if req.is_json:
        max_json_bytes = getattr(config, "MAX_JSON_PAYLOAD_BYTES", 2 * 1024 * 1024)
        return {
            "field": "json_body",
            "field_type": "json",
            "filename": None,
            "max_allowed_size_bytes": max_json_bytes,
            "max_allowed_size": format_size_bytes(max_json_bytes),
            "received_size_bytes": content_length,
            "received_size": format_size_bytes(content_length),
            "message": (
                f"The JSON request payload ({format_size_bytes(content_length)}) "
                f"exceeds the maximum allowed size of {format_size_bytes(max_json_bytes)}."
            ),
        }

    # 4. Default: Uploaded file or general request body
    max_upload_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)
    max_upload_bytes = getattr(config, "MAX_RESUME_FILE_SIZE_BYTES", max_upload_mb * 1024 * 1024)
    return {
        "field": "resume" if "resume" in req.path or "analysis" in req.path else "payload",
        "field_type": "file" if "upload" in req.path or "resume" in req.path or req.files else "payload",
        "filename": None,
        "max_allowed_size_bytes": max_upload_bytes,
        "max_allowed_size": format_size_bytes(max_upload_bytes),
        "received_size_bytes": content_length,
        "received_size": format_size_bytes(content_length),
        "message": (
            f"The uploaded file or request payload exceeds the maximum allowed size of {format_size_bytes(max_upload_bytes)} "
            f"({max_upload_mb} MB). Please reduce file size and try again."
        ),
    }


def get_size_diagnostics_summary(limit: int = 50) -> Dict[str, Any]:
    """
    Returns an aggregated diagnostics summary of recent request size violations
    and active limits for maintainer observability.
    """
    limits = get_configured_limits()
    recent = list(_DIAGNOSTICS_RECORDS)[:limit]

    field_counts: Dict[str, int] = collections.defaultdict(int)
    type_counts: Dict[str, int] = collections.defaultdict(int)

    for item in _DIAGNOSTICS_RECORDS:
        f = item.get("field", "unknown")
        t = item.get("field_type", "unknown")
        field_counts[f] += 1
        type_counts[t] += 1

    return {
        "status": "success",
        "total_failures": len(_DIAGNOSTICS_RECORDS),
        "configured_limits": limits,
        "field_breakdown": dict(field_counts),
        "type_breakdown": dict(type_counts),
        "recent_failures": recent,
    }


def clear_diagnostics_for_testing() -> None:
    """Helper to clear in-memory ring buffer during unit test execution."""
    _DIAGNOSTICS_RECORDS.clear()
