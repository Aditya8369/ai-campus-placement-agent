"""
utils/response_optimizer.py
HTTP Response Compression, Static Asset Versioning, and Cache Policy Enforcement (#857).

Key Capabilities:
1. Static Asset Versioning:
   - Computes deterministic SHA-256 hash suffixes for static assets.
   - Automatically injects '?v=<hash>' into url_for('static', ...) via @app.url_defaults.
   - Automatically updates version tags whenever static file contents or mtime change.
2. Long-Lived Static Asset Caching:
   - Versioned static assets (?v=...) receive 'public, max-age=31536000, immutable'.
   - Unversioned static assets receive 'public, max-age=86400'.
   - Service worker scripts (/sw.js) explicitly retain 'no-cache, no-store, must-revalidate'.
3. Privacy & Personal Data Cache Protection:
   - Authenticated sessions, HTML views, and user data routes receive 'private, no-cache, no-store, must-revalidate'
     to ensure private personal data is never cached by shared intermediate proxies or CDN caches.
4. Gzip Response Compression:
   - Text, CSS, JavaScript, JSON, SVG, and XML responses are dynamically compressed using gzip
     when the client sends Accept-Encoding: gzip.
   - Minimum size threshold (default 500 bytes) avoids compression overhead on tiny payloads.
   - Sets 'Content-Encoding: gzip' and properly adds 'Vary: Accept-Encoding'.
"""

import gzip
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

COMPRESSIBLE_MIMETYPES = frozenset({
    "text/html",
    "text/css",
    "text/plain",
    "text/xml",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "application/json",
    "application/xml",
    "application/ld+json",
    "image/svg+xml",
})

_STATIC_HASH_CACHE: Dict[str, Tuple[float, str]] = {}


def get_static_file_version(filename: str, static_folder: Optional[str] = None) -> str:
    """
    Computes a content hash version for a static file based on its mtime and content.
    Returns an 8-character hex string. Caches in-memory to prevent repeated disk I/O.
    If the file is modified on disk, mtime changes and the hash is automatically recomputed.
    """
    if not filename:
        return ""
    folder = Path(static_folder) if static_folder else Path("static")
    file_path = folder / filename.lstrip("/\\")

    try:
        stat_result = file_path.stat()
        mtime = stat_result.st_mtime
    except (OSError, FileNotFoundError):
        return ""

    cached = _STATIC_HASH_CACHE.get(filename)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with open(file_path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:8]
        _STATIC_HASH_CACHE[filename] = (mtime, digest)
        return digest
    except (OSError, PermissionError):
        return ""


def clear_static_cache() -> None:
    """Clears the in-memory static file version cache (useful in tests or asset updates)."""
    _STATIC_HASH_CACHE.clear()


def is_compressible_type(content_type: str) -> bool:
    """Checks whether the given MIME content type is eligible for gzip compression."""
    if not content_type:
        return False
    base_type = content_type.split(";")[0].strip().lower()
    return base_type in COMPRESSIBLE_MIMETYPES or base_type.startswith("text/")


def compress_response(
    response: Any,
    request: Any,
    min_size: int = 500,
    enabled: bool = True,
) -> Any:
    """
    Gzip compresses HTTP response payload if supported by client and eligible.
    """
    if not enabled:
        return response

    # Skip event streams
    if response.mimetype == "text/event-stream":
        return response

    # Werkzeug send_file responses set direct_passthrough; disable to read bytes for compression
    if getattr(response, "direct_passthrough", False):
        response.direct_passthrough = False

    # Only compress successful 2xx responses
    status_code = getattr(response, "status_code", 200)
    if not (200 <= status_code < 300):
        return response

    # Skip already-compressed responses
    if "Content-Encoding" in response.headers:
        return response

    # Check client Accept-Encoding
    accept_encoding = request.headers.get("Accept-Encoding", "").lower() if request else ""
    if "gzip" not in accept_encoding:
        return response

    # Check Content-Type eligibility
    content_type = response.headers.get("Content-Type", "")
    if not is_compressible_type(content_type):
        return response

    # Check size threshold
    try:
        data = response.get_data()
    except Exception:
        return response

    if not data or len(data) < min_size:
        return response

    # Perform gzip compression
    try:
        compressed = gzip.compress(data, compresslevel=6)
    except Exception as exc:
        logger.warning("Gzip compression failed: %s; serving uncompressed response.", exc)
        return response

    if len(compressed) < len(data):
        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))

    # Add Vary header for cache correctness
    vary = response.headers.get("Vary")
    if not vary:
        response.headers["Vary"] = "Accept-Encoding"
    elif "Accept-Encoding" not in vary:
        response.headers["Vary"] = f"{vary}, Accept-Encoding"

    return response


def apply_cache_headers(
    response: Any,
    request: Any,
    is_authenticated: bool = False,
    max_age_versioned: int = 31536000,
    max_age_default: int = 86400,
) -> Any:
    """
    Applies caching directives:
    - Long-lived immutable caching for versioned static assets.
    - Default caching for unversioned static assets.
    - Explicit 'no-cache, no-store' for service worker scripts.
    - Strict 'private, no-cache, no-store' for authenticated sessions and personal/dynamic pages.
    """
    path = request.path if request else ""

    # Service worker scripts and web manifests must never be cached long-term
    if path.endswith("sw.js") or path == "/manifest.json":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    # Static assets
    if path.startswith("/static/"):
        if request and "v" in request.args:
            response.headers["Cache-Control"] = f"public, max-age={max_age_versioned}, immutable"
        else:
            response.headers["Cache-Control"] = f"public, max-age={max_age_default}"
        return response

    # Personal data, authenticated sessions, or dynamic HTML/API pages
    content_type = response.headers.get("Content-Type", "")
    if is_authenticated or "text/html" in content_type or path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response
