"""
Test suite verifying HTTP response security headers and Content Security Policy (CSP).

Checks:
- Presence and correctness of Content-Security-Policy (CSP)
- X-Content-Type-Options: nosniff
- X-Frame-Options: SAMEORIGIN
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy directives
"""

import pytest
from app import app


def test_security_headers_present_on_index_route():
    """Verify standard GET / response includes all configured defense-in-depth security headers."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200

        # Check X-Content-Type-Options
        assert res.headers.get("X-Content-Type-Options") == "nosniff"

        # Check X-Frame-Options
        assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"

        # Check Referrer-Policy
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

        # Check Permissions-Policy
        assert "microphone" in res.headers.get("Permissions-Policy", "")

        # Check CSP
        csp = res.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "style-src" in csp
        assert "font-src" in csp
        assert "frame-ancestors 'self'" in csp


def test_security_headers_present_on_api_route():
    """Verify API responses also inherit the global security headers."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/api/companies/General")
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert "default-src 'self'" in res.headers.get("Content-Security-Policy", "")
