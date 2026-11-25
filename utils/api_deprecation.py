"""
API Field and Route Deprecation Management Service (#445, #553).
===============================================================
Provides standard RFC 8594 Sunset & Deprecation HTTP response headers,
deprecated field detection in requests (JSON, form, query args) and responses,
successor/replacement mapping, removal schedules, and SQLite metrics tracking.

Standard HTTP Headers Injected:
  - Deprecation: true (RFC 8594)
  - Sunset: Wed, 01 Jan 2030 00:00:00 GMT (RFC 8594 / RFC 1123)
  - Link: <url>; rel="successor-version" or rel="deprecation" (RFC 8288)
  - X-API-Deprecated-Fields: <field1>, <field2>
  - X-API-Replacement: <replacement_mapping>
  - X-API-Removal-Date: 2030-01-01 (ISO 8601)
  - X-API-Deprecation-Notice: Human-readable guidance
"""

import copy
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from flask import Request, Response

logger = logging.getLogger(__name__)

# Standard Deprecation & Sunset Configuration
DEFAULT_SUNSET_DATE_RFC: str = "Wed, 01 Jan 2030 00:00:00 GMT"
DEFAULT_SUNSET_DATE_ISO: str = "2030-01-01"
MIGRATION_DOCS_URL: str = "/docs/api-versioning"

# Structured Deprecated Fields Catalog
# Maps legacy field names to their replacement, scheduled removal date, and applicable routes.
DEPRECATED_FIELDS: Dict[str, Dict[str, Any]] = {
    "cover_letter": {
        "field": "cover_letter",
        "replacement": "content",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/cover-letter/download",
            "/api/v1/cover-letter/download",
        ],
        "description": "Cover letter text. Use 'content' instead.",
    },
    "company": {
        "field": "company",
        "replacement": "company_name",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/analysis/start",
            "/api/v1/analysis/start",
            "/api/role-prep/generate",
            "/api/v1/role-prep/generate",
            "/api/analyze",
            "/api/v1/analyze",
        ],
        "description": "Target company name. Use 'company_name' instead.",
    },
    "role": {
        "field": "role",
        "replacement": "target_role",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/role-prep/generate",
            "/api/v1/role-prep/generate",
            "/api/analysis/start",
            "/api/v1/analysis/start",
            "/api/analyze",
            "/api/v1/analyze",
        ],
        "description": "Target job role name. Use 'target_role' instead.",
    },
    "role_id": {
        "field": "role_id",
        "replacement": "target_role",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/analyze",
            "/api/v1/analyze",
            "/api/analysis/start",
            "/api/v1/analysis/start",
        ],
        "description": "Role template ID. Use 'target_role' instead.",
    },
    "selected_role": {
        "field": "selected_role",
        "replacement": "target_role",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/analyze",
            "/api/v1/analyze",
            "/api/analysis/start",
            "/api/v1/analysis/start",
        ],
        "description": "Role selection. Use 'target_role' instead.",
    },
    "input_mode": {
        "field": "input_mode",
        "replacement": "analysis_mode",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/analyze",
            "/api/v1/analyze",
        ],
        "description": "Input mode ('upload' | 'text'). Use 'analysis_mode' instead.",
    },
    "batch_companies": {
        "field": "batch_companies",
        "replacement": "companies",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/batch-compare",
            "/api/v1/batch-compare",
            "/api/analysis/batch-compare",
            "/api/v1/analysis/batch-compare",
        ],
        "description": "List of companies for batch comparison. Use 'companies' instead.",
    },
    "resume_analysis_id": {
        "field": "resume_analysis_id",
        "replacement": "analysis_id",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/applications",
            "/api/v1/applications",
            "/api/applications/create",
            "/api/v1/applications/create",
        ],
        "description": "Linked resume analysis id. Use 'analysis_id' instead.",
    },
    "tags": {
        "field": "tags",
        "replacement": "competencies",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/interview/experience",
            "/api/v1/interview/experience",
        ],
        "description": "Experience tags list. Use 'competencies' instead.",
    },
    "notes": {
        "field": "notes",
        "replacement": "change_notes",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "endpoints": [
            "/api/analysis/resume/label",
            "/api/v1/analysis/resume/label",
        ],
        "description": "Resume label notes. Use 'change_notes' instead.",
    },
}

# Structured Deprecated Routes Catalog
DEPRECATED_ROUTES: Dict[str, Dict[str, Any]] = {
    "/api/analyze": {
        "replacement": "/api/v1/analysis/start",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "description": "Legacy synchronous analyze route. Use '/api/v1/analysis/start' instead.",
    },
    "/api/applications/create": {
        "replacement": "/api/v1/applications",
        "removal_date": DEFAULT_SUNSET_DATE_ISO,
        "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "description": "Legacy application create route. Use POST '/api/v1/applications' instead.",
    },
}

# In-memory fast counters for metrics aggregation
_METRICS_COUNTER: Dict[str, Any] = {
    "total": 0,
    "fields": {},
    "routes": {},
}


def _normalize_path(path: str) -> str:
    """Normalizes a URL path for endpoint matching (strips trailing slash)."""
    if not path:
        return "/"
    p = path.rstrip("/")
    return p if p else "/"


def _endpoint_matches(target_endpoint: str, candidate_path: str) -> bool:
    """
    Checks if a candidate path matches a target endpoint pattern.
    Handles exact match, /api/v1 vs /api equivalents, and wildcard matching.
    """
    if target_endpoint == "*":
        return True

    norm_target = _normalize_path(target_endpoint)
    norm_candidate = _normalize_path(candidate_path)

    if norm_target == norm_candidate:
        return True

    # Check unversioned <-> v1 equivalence
    if norm_target.startswith("/api/v1/"):
        unversioned_target = "/api/" + norm_target[len("/api/v1/"):]
        if unversioned_target == norm_candidate:
            return True
    elif norm_target.startswith("/api/"):
        v1_target = "/api/v1/" + norm_target[len("/api/"):]
        if v1_target == norm_candidate:
            return True

    # Prefix match (e.g. dynamic parameters in path)
    if norm_candidate.startswith(norm_target + "/"):
        return True

    return False


def get_field_deprecation_info(field_name: str, endpoint_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Looks up deprecation metadata for a given field name and endpoint path.
    Returns metadata dict if deprecated for the route, or None if valid.
    """
    info = DEPRECATED_FIELDS.get(field_name)
    if not info:
        return None

    if not endpoint_path:
        return copy.deepcopy(info)

    allowed_endpoints = info.get("endpoints", ["*"])
    if "*" in allowed_endpoints:
        return copy.deepcopy(info)

    for ep in allowed_endpoints:
        if _endpoint_matches(ep, endpoint_path):
            return copy.deepcopy(info)

    return None


def get_route_deprecation_info(endpoint_path: str) -> Optional[Dict[str, Any]]:
    """
    Looks up deprecation metadata for a route.
    Checks explicitly registered deprecated routes as well as unversioned legacy /api/ routes.
    """
    norm_path = _normalize_path(endpoint_path)

    # 1. Explicitly mapped route deprecations
    if norm_path in DEPRECATED_ROUTES:
        return copy.deepcopy(DEPRECATED_ROUTES[norm_path])

    # 2. Check unversioned /api/... legacy route
    if norm_path.startswith("/api/") and not norm_path.startswith("/api/v1/") and norm_path != "/api/v1":
        # Unversioned legacy route: successor is /api/v1/...
        subpath = norm_path[len("/api/"):]
        if not subpath.startswith("v") or not subpath[1:].split("/")[0].isdigit():
            successor = f"/api/v1/{subpath}"
            return {
                "replacement": successor,
                "removal_date": DEFAULT_SUNSET_DATE_ISO,
                "removal_date_rfc": DEFAULT_SUNSET_DATE_RFC,
                "description": f"Legacy unversioned endpoint. Migrated to '{successor}'.",
            }

    return None


def detect_deprecated_fields(
    endpoint_path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Inspects a dictionary payload (from JSON body, form data, or query args)
    and returns a list of detected deprecated field descriptors.
    """
    if not payload or not isinstance(payload, dict):
        return []

    detected: List[Dict[str, Any]] = []
    seen_fields: Set[str] = set()

    for key in payload.keys():
        if key in seen_fields:
            continue
        dep_info = get_field_deprecation_info(key, endpoint_path)
        if dep_info:
            seen_fields.add(key)
            detected.append(dep_info)

    return detected


def detect_request_deprecations(
    req: Request,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Inspects an incoming Flask request for route deprecation and deprecated field usage.
    Checks request JSON, form data, and query args.

    Returns:
        (route_deprecation_info_or_None, list_of_detected_field_infos)
    """
    path = req.path
    route_info = get_route_deprecation_info(path)

    detected_fields_map: Dict[str, Dict[str, Any]] = {}

    # 1. Check Query Parameters
    try:
        if req.args:
            for k in req.args.keys():
                dep = get_field_deprecation_info(k, path)
                if dep:
                    detected_fields_map[k] = dep
    except Exception:
        pass

    # 2. Check JSON payload (safe cached retrieval)
    try:
        if req.is_json:
            json_body = req.get_json(silent=True)
            if isinstance(json_body, dict):
                for k in json_body.keys():
                    dep = get_field_deprecation_info(k, path)
                    if dep:
                        detected_fields_map[k] = dep
    except Exception:
        pass

    # 3. Check Form Data
    try:
        if req.form:
            for k in req.form.keys():
                dep = get_field_deprecation_info(k, path)
                if dep:
                    detected_fields_map[k] = dep
    except Exception:
        pass

    return route_info, list(detected_fields_map.values())


def inject_deprecation_headers(
    response: Response,
    detected_fields: Optional[List[Dict[str, Any]]] = None,
    route_info: Optional[Dict[str, Any]] = None,
    endpoint_path: Optional[str] = None,
) -> Response:
    """
    Applies RFC 8594 Sunset & Deprecation headers along with detailed
    X-API-Deprecated-Fields, X-API-Replacement, X-API-Removal-Date, and
    X-API-Deprecation-Notice headers to a Flask response object.
    """
    if not detected_fields and not route_info:
        return response

    # 1. Base Deprecation & Sunset headers (RFC 8594)
    response.headers["Deprecation"] = "true"

    sunset_rfc = DEFAULT_SUNSET_DATE_RFC
    removal_iso = DEFAULT_SUNSET_DATE_ISO

    if route_info:
        sunset_rfc = route_info.get("removal_date_rfc", DEFAULT_SUNSET_DATE_RFC)
        removal_iso = route_info.get("removal_date", DEFAULT_SUNSET_DATE_ISO)
    elif detected_fields:
        sunset_rfc = detected_fields[0].get("removal_date_rfc", DEFAULT_SUNSET_DATE_RFC)
        removal_iso = detected_fields[0].get("removal_date", DEFAULT_SUNSET_DATE_ISO)

    response.headers["Sunset"] = sunset_rfc
    response.headers["X-API-Removal-Date"] = removal_iso

    # 2. Link Header (RFC 8288)
    if route_info and "replacement" in route_info:
        replacement_route = route_info["replacement"]
        response.headers["Link"] = f'<{replacement_route}>; rel="successor-version"'
    elif "Link" not in response.headers:
        response.headers["Link"] = f'<{MIGRATION_DOCS_URL}>; rel="deprecation"'

    # 3. Field-specific deprecation headers
    if detected_fields:
        field_names = [f["field"] for f in detected_fields]
        replacements = [f"{f['field']} -> {f['replacement']}" for f in detected_fields]

        response.headers["X-API-Deprecated-Fields"] = ", ".join(field_names)
        response.headers["X-API-Replacement"] = ", ".join(replacements)

        notices = [
            f"Field '{f['field']}' is deprecated and scheduled for removal on {f['removal_date']}. Please migrate to '{f['replacement']}'."
            for f in detected_fields
        ]
        response.headers["X-API-Deprecation-Notice"] = " ".join(notices)
    elif route_info:
        # Route deprecation notice
        rep = route_info.get("replacement", "the canonical v1 endpoint")
        response.headers["X-API-Replacement"] = rep
        response.headers["X-API-Deprecation-Notice"] = (
            f"Route '{endpoint_path or ''}' is deprecated and scheduled for removal on {removal_iso}. "
            f"Please use '{rep}' instead."
        )

    return response


# =====================================================================
# Database Metrics Tracking & Reporting
# =====================================================================

def record_deprecated_usage(
    item_type: str,
    item_name: str,
    replacement: Optional[str],
    endpoint: str,
    http_method: str = "GET",
    user_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Safely records an invocation of a deprecated field or route into SQLite
    and increments in-memory aggregate counters. Never raises exceptions to
    prevent disrupting user requests.
    """
    # 1. Update in-memory counters
    try:
        _METRICS_COUNTER["total"] += 1
        if item_type == "field":
            _METRICS_COUNTER["fields"][item_name] = _METRICS_COUNTER["fields"].get(item_name, 0) + 1
        elif item_type == "route":
            _METRICS_COUNTER["routes"][item_name] = _METRICS_COUNTER["routes"].get(item_name, 0) + 1
    except Exception:
        pass

    # 2. Persist to SQLite table: deprecated_api_metrics
    try:
        from utils.database import get_db_connection
        conn = get_db_connection()
        try:
            metric_id = f"dep-{uuid.uuid4().hex[:12]}"
            effective_user = user_id or "anonymous"
            conn.execute(
                """
                INSERT INTO deprecated_api_metrics (
                    id, item_type, item_name, replacement, endpoint,
                    http_method, user_id, client_ip, user_agent, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    metric_id,
                    item_type,
                    item_name,
                    replacement or "",
                    endpoint,
                    http_method.upper(),
                    effective_user,
                    client_ip or "",
                    (user_agent or "")[:250],
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"Failed to record deprecated API metric ({item_type}:{item_name}): {exc}")


def get_deprecated_metrics_summary(limit: int = 100) -> Dict[str, Any]:
    """
    Queries database and returns an authoritative summary of deprecated API usage:
      - Total invocation count
      - Count by field name and route
      - Scheduled removal dates and recommended replacements
      - Most recent invocations log
    """
    total_count = 0
    field_count = 0
    route_count = 0
    fields_summary: List[Dict[str, Any]] = []
    routes_summary: List[Dict[str, Any]] = []
    recent_events: List[Dict[str, Any]] = []

    try:
        from utils.database import get_db_connection
        conn = get_db_connection()
        try:
            # 1. Aggregate totals
            row = conn.execute("SELECT COUNT(*) FROM deprecated_api_metrics").fetchone()
            total_count = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM deprecated_api_metrics WHERE item_type = 'field'").fetchone()
            field_count = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM deprecated_api_metrics WHERE item_type = 'route'").fetchone()
            route_count = row[0] if row else 0

            # 2. Breakdown by field
            field_rows = conn.execute(
                """
                SELECT item_name, replacement, COUNT(*) as call_count, MAX(timestamp) as last_used
                FROM deprecated_api_metrics
                WHERE item_type = 'field'
                GROUP BY item_name, replacement
                ORDER BY call_count DESC
                """
            ).fetchall()

            for r in field_rows:
                f_name = r["item_name"]
                meta = DEPRECATED_FIELDS.get(f_name, {})
                fields_summary.append({
                    "field": f_name,
                    "replacement": r["replacement"] or meta.get("replacement", ""),
                    "removal_date": meta.get("removal_date", DEFAULT_SUNSET_DATE_ISO),
                    "call_count": r["call_count"],
                    "last_used_at": r["last_used"],
                })

            # Also include configured fields that have 0 calls so maintainers see full picture
            observed_fields = {f["field"] for f in fields_summary}
            for k, meta in DEPRECATED_FIELDS.items():
                if k not in observed_fields:
                    fields_summary.append({
                        "field": k,
                        "replacement": meta.get("replacement", ""),
                        "removal_date": meta.get("removal_date", DEFAULT_SUNSET_DATE_ISO),
                        "call_count": 0,
                        "last_used_at": None,
                    })

            # 3. Breakdown by route
            route_rows = conn.execute(
                """
                SELECT item_name, replacement, COUNT(*) as call_count, MAX(timestamp) as last_used
                FROM deprecated_api_metrics
                WHERE item_type = 'route'
                GROUP BY item_name, replacement
                ORDER BY call_count DESC
                """
            ).fetchall()

            for r in route_rows:
                r_name = r["item_name"]
                meta = DEPRECATED_ROUTES.get(r_name, {})
                routes_summary.append({
                    "route": r_name,
                    "replacement": r["replacement"] or meta.get("replacement", ""),
                    "removal_date": meta.get("removal_date", DEFAULT_SUNSET_DATE_ISO),
                    "call_count": r["call_count"],
                    "last_used_at": r["last_used"],
                })

            # 4. Recent invocation events
            recent_rows = conn.execute(
                """
                SELECT id, item_type, item_name, replacement, endpoint, http_method, user_id, timestamp
                FROM deprecated_api_metrics
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()

            for r in recent_rows:
                recent_events.append({
                    "id": r["id"],
                    "item_type": r["item_type"],
                    "item_name": r["item_name"],
                    "replacement": r["replacement"],
                    "endpoint": r["endpoint"],
                    "http_method": r["http_method"],
                    "user_id": r["user_id"],
                    "timestamp": r["timestamp"],
                })

        finally:
            conn.close()

    except Exception as exc:
        logger.warning(f"Error querying deprecated_api_metrics: {exc}")
        # Return in-memory fallback if DB table not yet populated
        total_count = _METRICS_COUNTER["total"]
        field_count = sum(_METRICS_COUNTER["fields"].values())
        route_count = sum(_METRICS_COUNTER["routes"].values())

    return {
        "status": "success",
        "total_deprecated_invocations": total_count,
        "field_deprecated_invocations": field_count,
        "route_deprecated_invocations": route_count,
        "fields_summary": fields_summary,
        "routes_summary": routes_summary,
        "recent_invocations": recent_events,
        "sunset_date": DEFAULT_SUNSET_DATE_ISO,
        "sunset_date_rfc": DEFAULT_SUNSET_DATE_RFC,
        "migration_guide": MIGRATION_DOCS_URL,
    }


def reset_metrics_for_testing() -> None:
    """Helper to clear metrics table and in-memory counters during test execution."""
    _METRICS_COUNTER["total"] = 0
    _METRICS_COUNTER["fields"].clear()
    _METRICS_COUNTER["routes"].clear()

    try:
        from utils.database import get_db_connection
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM deprecated_api_metrics")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
