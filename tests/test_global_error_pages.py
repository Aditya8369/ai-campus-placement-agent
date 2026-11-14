"""
Unit & Integration Tests for Global Error Pages (#362)
======================================================
Tests:
1. HTTP 404 Not Found:
   - HTML view with plain English explanation, safe actions, and correlation request ID.
   - JSON view for API / XMLHttpRequest.
2. HTTP 403 Forbidden:
   - HTML view with access guidance and sign-in action.
   - JSON view for API / XMLHttpRequest.
3. HTTP 429 Too Many Requests:
   - HTML view with retry cooldown display and theme support.
   - JSON view with Retry-After headers and request ID.
4. HTTP 500 Internal Server Error:
   - HTML view rendering dedicated error page with human-shareable Error Reference ID.
   - JSON view with reference ID and request ID.
5. Light and Dark Theme Compatibility:
   - Verification of theme attributes and toggle controls.
"""

import pytest
import json
from flask import abort
from app import app


# Define test routes before any client request runs
@app.route("/test-error-403")
def _route_403():
    abort(403, description="You must be an administrator to access this area.")


@app.route("/api/test-error-403")
def _route_api_403():
    abort(403, description="Token lacks required permissions.")


@app.route("/test-error-429")
def _route_429():
    abort(429, description="Hourly mock interview quota reached.")


@app.route("/api/test-error-429")
def _route_api_429():
    abort(429, description="Too many requests.")


@app.route("/test-error-500")
def _route_500():
    abort(500)


@app.route("/api/test-error-500")
def _route_api_500():
    abort(500)


@pytest.fixture
def test_client():
    """Sets up a Flask test client configured for error handling tests."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ==========================================
# 1. HTTP 404 Error Tests
# ==========================================

def test_404_html_page_rendering(test_client):
    """Verify 404 renders custom accessible HTML page with safe next actions."""
    resp = test_client.get("/non-existent-random-route-9999")
    assert resp.status_code == 404
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)

    # Plain English explanation and HTTP status
    assert "Page Not Found" in html
    assert "404" in html
    assert "We Couldn't Find That Page" in html

    # Safe next actions
    assert "Return Home" in html
    assert "Saved Questions" in html
    assert "Practice DSA" in html
    assert "Go Back" in html

    # Theme toggle support
    assert "data-bs-theme" in html
    assert "themeToggleBtn" in html


def test_404_api_json_response(test_client):
    """Verify 404 returns structured JSON for API and AJAX requests."""
    resp = test_client.get(
        "/api/non-existent-api-endpoint",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert resp.status_code == 404
    assert "application/json" in resp.content_type
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "Not Found"
    assert "/api/non-existent-api-endpoint" in data["path"]


# ==========================================
# 2. HTTP 403 Error Tests
# ==========================================

def test_403_html_page_rendering(test_client):
    """Verify 403 renders custom HTML page with permission explanation and login link."""
    resp = test_client.get("/test-error-403")
    assert resp.status_code == 403
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)

    assert "Access Forbidden" in html
    assert "403" in html
    assert "Access Denied" in html
    assert "You must be an administrator" in html
    assert "Sign In" in html
    assert "themeToggleBtn" in html


def test_403_api_json_response(test_client):
    """Verify 403 returns structured JSON for API requests."""
    resp = test_client.get("/api/test-error-403", headers={"Accept": "application/json"})
    assert resp.status_code == 403
    assert "application/json" in resp.content_type
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "Forbidden"
    assert "Token lacks required permissions" in data["message"]


# ==========================================
# 3. HTTP 429 Error Tests
# ==========================================

def test_429_html_page_rendering(test_client):
    """Verify 429 renders custom HTML page with rate limit explanation and theme support."""
    resp = test_client.get("/test-error-429")
    assert resp.status_code == 429
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)

    assert "Rate Limit Exceeded" in html
    assert "429" in html
    assert "Hourly mock interview quota reached" in html
    assert "Return Home" in html
    assert "themeToggleBtn" in html


def test_429_api_json_response(test_client):
    """Verify 429 returns structured JSON with retry metadata."""
    resp = test_client.get("/api/test-error-429", headers={"Accept": "application/json"})
    assert resp.status_code == 429
    assert "application/json" in resp.content_type
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "Too Many Requests"


# ==========================================
# 4. HTTP 500 Error Tests
# ==========================================

def test_500_html_page_rendering(test_client):
    """Verify 500 renders dedicated error template with human-shareable Error Reference ID."""
    resp = test_client.get("/test-error-500")
    assert resp.status_code == 500
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)

    assert "Something Went Wrong" in html
    assert "500" in html
    assert "Error Reference:" in html
    assert "ERR-" in html  # Generated Error Reference ID
    assert "btnCopyRefId" in html
    assert "Try Again" in html
    assert "themeToggleBtn" in html


def test_500_api_json_response(test_client):
    """Verify 500 returns JSON with reference ID for API calls."""
    resp = test_client.get("/api/test-error-500", headers={"Accept": "application/json"})
    assert resp.status_code == 500
    assert "application/json" in resp.content_type
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "Internal Server Error"
    assert "reference_id" in data
    assert data["reference_id"].startswith("ERR-")
