"""
API Versioning & Deprecation Management Service (#445).

Provides URL-based versioning (/api/v1/...), backwards-compatible aliasing
for legacy unversioned routes (/api/...), standardized HTTP headers
(API-Version, X-API-Version, Deprecation, Sunset, Link), version discovery,
and an extensible architecture for introducing future API versions (e.g. v2).
"""

import logging
from typing import Any, Dict, List, Optional
from flask import Blueprint, Flask, jsonify, render_template, request

logger = logging.getLogger(__name__)

# Canonical Version Configuration
CURRENT_API_VERSION: str = "v1"
DEFAULT_API_VERSION: str = "v1"
SUPPORTED_API_VERSIONS: List[str] = ["v1"]
DEPRECATED_API_VERSIONS: List[str] = ["legacy (unversioned /api/...)"]
SUNSET_DATE_RFC: str = "Wed, 01 Jan 2030 00:00:00 GMT"
SUNSET_DATE_ISO: str = "2030-01-01"
MIGRATION_DOCS_PATH: str = "/docs/api-versioning"


def get_api_version_info() -> Dict[str, Any]:
    """
    Returns API versioning metadata, active and supported versions,
    deprecation schedule, and documentation links.
    """
    return {
        "status": "success",
        "current_version": CURRENT_API_VERSION,
        "default_version": DEFAULT_API_VERSION,
        "supported_versions": list(SUPPORTED_API_VERSIONS),
        "deprecated_versions": list(DEPRECATED_API_VERSIONS),
        "sunset_date": SUNSET_DATE_ISO,
        "sunset_date_rfc": SUNSET_DATE_RFC,
        "documentation_url": "/api/v1/docs",
        "openapi_url": "/api/v1/openapi.json",
        "migration_guide": MIGRATION_DOCS_PATH,
        "policy": {
            "strategy": "URI path prefixing (/api/v1/...) with legacy alias support",
            "backwards_compatibility": "Guaranteed during deprecation transition window",
            "deprecation_header": "Deprecation: true",
            "sunset_header": f"Sunset: {SUNSET_DATE_RFC}",
            "link_header_rel": "successor-version",
        },
    }


def extract_api_version(path: str) -> Optional[str]:
    """
    Extracts the API version identifier from a request URL path.

    Returns:
        - 'v1' for paths starting with '/api/v1/'
        - 'v2' (or higher) for future versioned paths
        - 'legacy' for paths starting with '/api/' without a version segment
        - None for non-API routes (e.g. '/', '/login', '/static/...')
    """
    if not path or not path.startswith("/api/"):
        return None

    subpath = path[len("/api/"):]
    if subpath.startswith("v1/") or subpath == "v1":
        return "v1"

    # Future versions support: checks for /api/v<N>/...
    parts = subpath.split("/", 1)
    if parts[0].startswith("v") and parts[0][1:].isdigit():
        return parts[0]

    return "legacy"


def to_versioned_path(path: str, version: str = "v1") -> str:
    """
    Converts an unversioned /api/... path to its versioned counterpart /api/v<N>/...
    If the path is already versioned, updates or retains the version segment.
    """
    if not path or not path.startswith("/api/"):
        return path

    subpath = path[len("/api/"):]
    # Check if path already starts with v<N>
    parts = subpath.split("/", 1)
    if parts[0].startswith("v") and parts[0][1:].isdigit():
        remainder = parts[1] if len(parts) > 1 else ""
        return f"/api/{version}/{remainder}".rstrip("/") if remainder else f"/api/{version}"

    return f"/api/{version}/{subpath}"


def register_api_version(
    app: Flask,
    version: str,
    blueprint: Optional[Blueprint] = None,
    url_prefix: Optional[str] = None
) -> None:
    """
    Registers a new API version (e.g., 'v2') with the Flask application.
    Enables future version introduction without breaking existing v1 or legacy clients.
    """
    v_norm = version.lower().strip()
    if not v_norm.startswith("v"):
        v_norm = f"v{v_norm}"

    if v_norm not in SUPPORTED_API_VERSIONS:
        SUPPORTED_API_VERSIONS.append(v_norm)

    if blueprint is not None:
        prefix = url_prefix or f"/api/{v_norm}"
        app.register_blueprint(blueprint, url_prefix=prefix)
        logger.info(f"Registered new API version blueprint '{blueprint.name}' under {prefix}")


def register_api_versioning(app: Flask) -> None:
    """
    Initializes the API versioning strategy on the Flask application:
    1. Registers version discovery endpoints (/api/version and /api/v1/version).
    2. Registers v1 documentation endpoints (/api/v1/openapi.json, /api/v1/docs, /api/v1/redoc).
    3. Traverses existing /api/... routes and registers matching /api/v1/... aliases.
    4. Attaches after_request hooks for standardized HTTP response headers
       (API-Version, X-API-Version, Deprecation, Sunset, Link).
    """

    # 1. Version discovery endpoints
    @app.route("/api/version", methods=["GET"], endpoint="api_version_info_legacy")
    @app.route("/api/v1/version", methods=["GET"], endpoint="api_version_info_v1")
    def api_version_endpoint():
        """Returns API versioning metadata, supported versions, and deprecation details (#445)."""
        return jsonify(get_api_version_info()), 200

    # 2. Documentation endpoints under /api/v1/
    @app.route("/api/v1/openapi.json", methods=["GET"], endpoint="api_v1_openapi_json")
    def api_v1_openapi_json():
        """Delivers OpenAPI 3.0.3 specification JSON for v1 endpoints (#445)."""
        from utils.openapi_spec import get_openapi_spec
        return jsonify(get_openapi_spec()), 200

    @app.route("/api/v1/docs", methods=["GET"], endpoint="api_v1_docs")
    def api_v1_docs():
        """Renders interactive Swagger UI explorer for v1 endpoints (#445)."""
        return render_template("swagger_ui.html", spec_url="/api/v1/openapi.json")

    @app.route("/api/v1/redoc", methods=["GET"], endpoint="api_v1_redoc")
    def api_v1_redoc():
        """Renders Redoc reference documentation for v1 endpoints (#445)."""
        return render_template("redoc.html", spec_url="/api/v1/openapi.json")

    # 3. Mirror all unversioned /api/... rules under /api/v1/...
    existing_rules = list(app.url_map.iter_rules())
    existing_patterns = {r.rule for r in existing_rules}
    alias_count = 0

    for rule in existing_rules:
        # Match only unversioned /api/... rules, skip already versioned ones
        if rule.rule.startswith("/api/") and extract_api_version(rule.rule) == "legacy":
            v1_pattern = "/api/v1" + rule.rule[len("/api"):]
            if v1_pattern not in existing_patterns:
                try:
                    app.add_url_rule(
                        v1_pattern,
                        endpoint=rule.endpoint,
                        methods=rule.methods,
                        strict_slashes=rule.strict_slashes,
                        defaults=rule.defaults,
                    )
                    existing_patterns.add(v1_pattern)
                    alias_count += 1
                except Exception as exc:
                    logger.warning(
                        f"Failed to register v1 alias for {rule.rule} -> {v1_pattern}: {exc}"
                    )

    logger.info(f"API Versioning initialized: registered {alias_count} v1 route aliases.")

    # 4. Standardized Response Headers Injection (RFC 8594 Sunset & Deprecation)
    @app.after_request
    def inject_api_version_headers(response):
        path = request.path
        version = extract_api_version(path)
        if version == "v1":
            response.headers["API-Version"] = "v1"
            response.headers["X-API-Version"] = "1.0"
        elif version == "legacy":
            # Unversioned legacy endpoint: return deprecation headers pointing to v1
            response.headers["API-Version"] = "legacy"
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = SUNSET_DATE_RFC
            v1_url = to_versioned_path(path, "v1")
            response.headers["Link"] = f'<{v1_url}>; rel="successor-version"'
        elif version is not None:
            # Future version (e.g. v2, v3)
            response.headers["API-Version"] = version

        return response
