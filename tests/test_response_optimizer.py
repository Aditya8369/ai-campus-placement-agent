"""
tests/test_response_optimizer.py
Unit and integration tests for HTTP Response Compression and Static Asset Caching (#857).

Verifies:
1. Static asset versioning:
   - Content hash determinism and mtime cache invalidation.
   - Automatic insertion of '?v=<hash>' into url_for('static', ...).
2. Static cache header directives:
   - Versioned static assets receive 'public, max-age=31536000, immutable'.
   - Unversioned static assets receive 'public, max-age=86400'.
   - Service worker scripts retain 'no-cache, no-store'.
3. Privacy & personal data protection:
   - Authenticated pages and dynamic API routes send 'private, no-cache, no-store, must-revalidate'.
4. Gzip response compression:
   - Text, CSS, JS, and JSON responses are compressed with gzip when Accept-Encoding: gzip is provided.
   - Decompressed content matches original payload.
   - Compression is skipped when Accept-Encoding does not include gzip.
   - Compression is skipped for payloads smaller than min_size threshold.
"""

import gzip
import os
from pathlib import Path
import pytest
from flask import url_for

from utils.response_optimizer import (
    apply_cache_headers,
    clear_static_cache,
    compress_response,
    get_static_file_version,
    is_compressible_type,
)


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def test_static_file_version_deterministic():
    """Verify get_static_file_version returns consistent 8-character hex hash for static files."""
    clear_static_cache()
    ver1 = get_static_file_version("css/style.css")
    assert ver1 != ""
    assert len(ver1) == 8
    # Second call should return cached version
    ver2 = get_static_file_version("css/style.css")
    assert ver1 == ver2


def test_static_file_version_empty_for_missing_file():
    """Verify missing files return empty string without raising an exception."""
    assert get_static_file_version("nonexistent_file_12345.css") == ""


def test_static_file_version_updates_on_file_change(tmp_path):
    """Verify modifying a file and updating its mtime recomputes a different hash version."""
    test_static = tmp_path / "static"
    test_static.mkdir()
    sample_file = test_static / "sample.css"

    sample_file.write_text("body { color: blue; }", encoding="utf-8")
    v1 = get_static_file_version("sample.css", static_folder=str(test_static))
    assert len(v1) == 8

    # Modify file and change mtime
    sample_file.write_text("body { color: red; margin: 10px; }", encoding="utf-8")
    new_mtime = sample_file.stat().st_mtime + 5
    os.utime(sample_file, (new_mtime, new_mtime))

    v2 = get_static_file_version("sample.css", static_folder=str(test_static))
    assert len(v2) == 8
    assert v1 != v2, "Expected version hash to change after file content modification"


def test_url_for_static_automatically_injects_version_parameter():
    """Verify url_for('static', filename=...) automatically appends ?v=<hash>."""
    from app import app
    with app.test_request_context():
        generated_url = url_for("static", filename="css/style.css")
        assert "/static/css/style.css?v=" in generated_url
        version_param = generated_url.split("?v=")[-1]
        assert len(version_param) == 8


def test_versioned_static_asset_receives_long_lived_cache(client):
    """Verify /static/ requests containing a ?v= version query parameter receive immutable 1-year cache."""
    res = client.get("/static/css/style.css?v=abcdef12")
    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "public" in cache_control
    assert "max-age=31536000" in cache_control
    assert "immutable" in cache_control


def test_unversioned_static_asset_receives_default_cache(client):
    """Verify /static/ requests without a ?v= parameter receive default caching."""
    res = client.get("/static/css/style.css")
    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "public" in cache_control
    assert "max-age=86400" in cache_control


def test_service_worker_retains_no_cache_policy(client):
    """Verify sw.js is explicitly prevented from long-lived caching."""
    res = client.get("/static/sw.js")
    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "no-cache" in cache_control
    assert "no-store" in cache_control


def test_personal_authenticated_pages_send_no_store(client):
    """Verify pages with personal/authenticated student data send private, no-store headers."""
    with client.session_transaction() as sess:
        sess["user_id"] = "student-test-user-id"
        sess["user_role"] = "student"

    res = client.get("/")
    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "no-store" in cache_control
    assert "private" in cache_control


def test_dynamic_api_sends_no_store(client):
    """Verify dynamic API responses prevent intermediate shared caching."""
    res = client.get("/api/health")
    assert res.status_code == 200
    cache_control = res.headers.get("Cache-Control", "")
    assert "no-store" in cache_control
    assert "private" in cache_control


def test_gzip_compression_on_static_asset_with_accept_encoding(client):
    """Verify static text/css responses are compressed with gzip when client requests it."""
    res = client.get(
        "/static/css/style.css",
        headers={"Accept-Encoding": "gzip, deflate"},
    )
    assert res.status_code == 200
    assert res.headers.get("Content-Encoding") == "gzip"
    assert "Accept-Encoding" in res.headers.get("Vary", "")

    # Decompress and verify content matches raw file
    decompressed = gzip.decompress(res.data).decode("utf-8")
    raw_file = Path("static/css/style.css").read_text(encoding="utf-8")
    assert decompressed == raw_file


def test_gzip_compression_skipped_when_client_does_not_send_accept_encoding(client):
    """Verify compression is skipped if the client does not support or request gzip."""
    res = client.get(
        "/static/css/style.css",
        headers={"Accept-Encoding": "identity"},
    )
    assert res.status_code == 200
    assert res.headers.get("Content-Encoding") is None
    # Data is raw uncompressed string
    assert res.data.decode("utf-8").startswith("/*") or "{" in res.data.decode("utf-8")


def test_gzip_compression_skipped_for_small_payload():
    """Verify compress_response skips compression when payload size is below min_size threshold."""
    from flask import Response, Request
    req = Request.from_values(headers={"Accept-Encoding": "gzip"})
    tiny_res = Response("small", mimetype="text/plain")

    compressed = compress_response(tiny_res, req, min_size=500)
    assert compressed.headers.get("Content-Encoding") is None
    assert compressed.get_data() == b"small"


def test_is_compressible_type():
    """Verify detection of compressible MIME content types."""
    assert is_compressible_type("text/html") is True
    assert is_compressible_type("text/css; charset=utf-8") is True
    assert is_compressible_type("application/javascript") is True
    assert is_compressible_type("application/json") is True
    assert is_compressible_type("image/svg+xml") is True
    assert is_compressible_type("image/png") is False
    assert is_compressible_type("application/octet-stream") is False
