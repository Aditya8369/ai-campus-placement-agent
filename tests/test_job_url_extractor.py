"""
Unit and integration tests for Job Description URL Extractor (#689).
Covers:
- SSRF prevention (private, loopback, link-local, carrier-grade NAT, multicast, reserved addresses)
- DNS resolution checks and blocking domains resolving to internal IPs
- Redirect validation and preventing redirect-based SSRF
- Enforcing redirect limits
- Enforcing download size limits (Content-Length and streamed body)
- Enforcing timeouts and handling slow servers
- Rejecting non-HTML content types
- Handling bot-blocking HTTP status codes (401, 403, 429)
- Lightweight readability extraction and clutter/script/banner stripping
- REST API endpoint behavior (/api/job-description/extract-url)
"""

import io
import socket
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app
from utils.job_url_extractor import (
    DEFAULT_TIMEOUT,
    MAX_DOWNLOAD_SIZE,
    MAX_REDIRECTS,
    JobURLExtractionError,
    SSRFSecurityError,
    extract_job_description_from_url,
    extract_job_text_from_html,
    fetch_job_page_html,
    is_ip_blocked,
    validate_url_safety,
)

SAMPLE_JOB_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Senior Software Engineer - Google | Careers</title>
  <script>console.log("analytics tracker");</script>
  <style>body { font-family: sans-serif; }</style>
</head>
<body>
  <header>
    <nav>
      <a href="/">Home</a>
      <a href="/jobs">Browse Jobs</a>
      <button>Sign In</button>
    </nav>
  </header>
  <div class="cookie-banner">
    <p>We use cookies to improve your browsing experience. <button>Accept</button></p>
  </div>
  <aside class="sidebar">
    <h3>Similar Jobs</h3>
    <ul>
      <li><a href="/job/2">DevOps Engineer</a></li>
    </ul>
  </aside>
  <main>
    <div class="job-description">
      <h1>Senior Software Engineer</h1>
      <p>Google is seeking a passionate Senior Software Engineer to build scalable distributed systems.</p>
      <h2>Key Responsibilities</h2>
      <ul>
        <li>Architect high-throughput microservices using Go and Python.</li>
        <li>Lead technical design reviews and mentor junior developers.</li>
        <li>Collaborate with product and infrastructure teams.</li>
      </ul>
      <h2>Qualifications & Requirements</h2>
      <ul>
        <li>B.S. or M.S. in Computer Science or equivalent practical experience.</li>
        <li>5+ years of software development experience with distributed systems.</li>
        <li>Strong proficiency in SQL, data structures, and algorithms.</li>
      </ul>
    </div>
  </main>
  <footer>
    <p>&copy; 2026 Google LLC. All rights reserved.</p>
  </footer>
</body>
</html>
"""


def _create_mock_response(
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
    body: bytes = SAMPLE_JOB_HTML.encode("utf-8"),
    headers: Optional[Dict[str, str]] = None,
    stream_chunks: Optional[List[bytes]] = None,
) -> MagicMock:
    """Helper to generate a mock requests.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.is_redirect = status_code in (301, 302, 303, 307, 308)
    h = {"Content-Type": content_type}
    if headers:
        h.update(headers)
    mock_resp.headers = h
    mock_resp.encoding = "utf-8"

    if stream_chunks is not None:
        mock_resp.iter_content.return_value = iter(stream_chunks)
    else:
        mock_resp.iter_content.return_value = iter([body])
    return mock_resp


# ==============================================================================
# SSRF Validation Tests
# ==============================================================================

def test_blocked_private_and_loopback_ip_addresses():
    """Verify that private, loopback, and link-local IP literals are rejected."""
    blocked_urls = [
        "http://127.0.0.1:8080/job",
        "http://127.0.0.2:80/job",
        "http://localhost/job",
        "http://10.0.0.1/careers",
        "http://10.254.254.1/careers",
        "http://192.168.1.1/job",
        "http://192.168.0.254/job",
        "http://172.16.0.1/job",
        "http://172.31.255.255/job",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/job",
        "http://[::1]/job",
        "http://[fe80::1]/job",
        "http://[fc00::1]/job",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://instance-data/latest/meta-data/",
    ]
    for url in blocked_urls:
        with pytest.raises(SSRFSecurityError):
            validate_url_safety(url)


def test_blocked_integer_and_hex_ips():
    """Verify integer and hexadecimal representations of loopback/private IPs are rejected."""
    # 2130706433 is 127.0.0.1 in decimal integer
    with pytest.raises(SSRFSecurityError):
        validate_url_safety("http://2130706433/job")

    # 0x7f000001 is 127.0.0.1 in hex
    with pytest.raises(SSRFSecurityError):
        validate_url_safety("http://0x7f000001/job")


def test_disallowed_schemes():
    """Verify non-HTTP/HTTPS schemes are rejected."""
    invalid_schemes = [
        "file:///etc/passwd",
        "ftp://ftp.example.com/job.txt",
        "gopher://evil.com/1",
        "dict://evil.com:2628/",
        "javascript:alert(1)",
    ]
    for url in invalid_schemes:
        with pytest.raises(SSRFSecurityError):
            validate_url_safety(url)


def test_dangerous_ports_blocked():
    """Verify dangerous service ports (SSH, Redis, DBs) are blocked."""
    dangerous_urls = [
        "http://public-jobs.example.com:22/job",
        "http://public-jobs.example.com:6379/job",
        "http://public-jobs.example.com:3306/job",
        "http://public-jobs.example.com:25/job",
        "http://public-jobs.example.com:11211/job",
    ]
    for url in dangerous_urls:
        with pytest.raises(SSRFSecurityError):
            validate_url_safety(url)


def test_dns_resolving_to_private_address_blocked():
    """Verify that domain names resolving to internal/private IPs are rejected."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "sneaky-internal-site.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        if host == "metadata-bypass.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        if host == "lan-target.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 80))]
        if host == "ipv6-loopback.com":
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 80))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(SSRFSecurityError) as exc_info:
            validate_url_safety("http://sneaky-internal-site.com/job")
        assert "127.0.0.1" in str(exc_info.value)

        with pytest.raises(SSRFSecurityError) as exc_info2:
            validate_url_safety("http://metadata-bypass.com/meta")
        assert "169.254.169.254" in str(exc_info2.value)

        with pytest.raises(SSRFSecurityError) as exc_info3:
            validate_url_safety("http://lan-target.com/admin")
        assert "192.168.1.100" in str(exc_info3.value)

        # Allowed public domain
        validate_url_safety("https://legitimate-careers.com/job/123")


# ==============================================================================
# Redirect Validation & Limits Tests
# ==============================================================================

def test_redirect_to_private_address_blocked():
    """Verify that a public URL redirecting to a loopback/private target is blocked."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "legit-jobs.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    mock_session = MagicMock()
    # First response redirects to loopback
    redirect_resp = _create_mock_response(
        status_code=302,
        headers={"Location": "http://127.0.0.1:8000/internal-secrets"},
    )
    mock_session.get.return_value = redirect_resp

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(SSRFSecurityError):
            fetch_job_page_html("http://legit-jobs.example.com/job", session=mock_session)


def test_redirect_to_private_domain_via_dns_blocked():
    """Verify that a redirect to a domain resolving to a private IP is blocked."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "legit-jobs.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        if host == "internal-router.corp":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.1", 80))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    redirect_resp = _create_mock_response(
        status_code=301,
        headers={"Location": "http://internal-router.corp/status"},
    )
    mock_session.get.return_value = redirect_resp

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(SSRFSecurityError):
            fetch_job_page_html("http://legit-jobs.example.com/job", session=mock_session)


def test_max_redirects_exceeded():
    """Verify that redirect loops exceeding MAX_REDIRECTS are aborted."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    # Creates an infinite redirect loop
    mock_session.get.return_value = _create_mock_response(
        status_code=302,
        headers={"Location": "http://legit-jobs.example.com/redirect-again"},
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(JobURLExtractionError) as exc_info:
            fetch_job_page_html("http://legit-jobs.example.com/start", session=mock_session)
        assert "Too many redirects" in str(exc_info.value)


# ==============================================================================
# Resource Limits & Network Errors Tests
# ==============================================================================

def test_oversized_declared_content_length_rejected():
    """Verify that responses with Content-Length > 2 MB are rejected immediately."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    mock_session.get.return_value = _create_mock_response(
        status_code=200,
        headers={"Content-Length": "5242880"},  # 5 MB
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(JobURLExtractionError) as exc_info:
            fetch_job_page_html("http://legit-jobs.example.com/huge-page", session=mock_session)
        assert "too large" in str(exc_info.value).lower()


def test_oversized_streamed_chunks_rejected():
    """Verify that responses streaming data > 2 MB without Content-Length are stopped."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    # Generates 250 chunks of 10,000 bytes = 2.5 MB (> 2 MB)
    large_chunks = [b"A" * 10000] * 250
    mock_session.get.return_value = _create_mock_response(
        status_code=200,
        stream_chunks=large_chunks,
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(JobURLExtractionError) as exc_info:
            fetch_job_page_html("http://legit-jobs.example.com/stream-bomb", session=mock_session)
        assert "maximum download size" in str(exc_info.value).lower()


def test_slow_response_timeout_rejected():
    """Verify requests.Timeout raises friendly user error."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out")

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(JobURLExtractionError) as exc_info:
            fetch_job_page_html("http://legit-jobs.example.com/slow", session=mock_session)
        assert "timed out" in str(exc_info.value).lower()
        assert "manually" in str(exc_info.value).lower()


def test_non_html_response_rejected():
    """Verify that non-HTML responses (PDF, JSON, Images) are rejected."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    mock_session.get.return_value = _create_mock_response(
        status_code=200,
        content_type="application/pdf",
        body=b"%PDF-1.4 ...",
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with pytest.raises(JobURLExtractionError) as exc_info:
            fetch_job_page_html("http://legit-jobs.example.com/resume.pdf", session=mock_session)
        assert "did not return an html web page" in str(exc_info.value).lower()


def test_bot_blocked_http_status_codes():
    """Verify HTTP 401, 403, and 429 return helpful anti-bot messages."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()

    for code in (401, 403, 429):
        mock_session.get.return_value = _create_mock_response(status_code=code)
        with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
            with pytest.raises(JobURLExtractionError) as exc_info:
                fetch_job_page_html("http://legit-jobs.example.com/protected", session=mock_session)
            assert f"HTTP {code}" in str(exc_info.value)
            assert "manually" in str(exc_info.value).lower()


# ==============================================================================
# Readability & Text Extraction Tests
# ==============================================================================

def test_html_readability_extraction():
    """Verify that main job text is cleanly extracted and clutter stripped."""
    result = extract_job_text_from_html(SAMPLE_JOB_HTML)

    assert result["status"] == "success"
    text = result["job_description"]
    assert "Senior Software Engineer" in text
    assert "Google is seeking a passionate" in text
    assert "Architect high-throughput microservices using Go and Python" in text
    assert "5+ years of software development experience" in text

    # Verify bullet symbols are properly formatted
    assert "• Architect high-throughput" in text
    assert "• 5+ years of software development" in text

    # Verify clutter elements are stripped
    assert "console.log" not in text
    assert "Home" not in text
    assert "Browse Jobs" not in text
    assert "Similar Jobs" not in text
    assert "DevOps Engineer" not in text
    assert "We use cookies" not in text
    assert "&copy;" not in text

    # Verify metadata hints
    assert "Senior Software Engineer" in result["title"]
    assert "Google" in result["company"]


def test_empty_or_too_short_html_rejected():
    """Verify that pages with insufficient readable text are rejected with a helpful message."""
    empty_html = "<html><body><div id='app'></div></body></html>"
    with pytest.raises(JobURLExtractionError) as exc_info:
        extract_job_text_from_html(empty_html)
    assert "sufficient job description text" in str(exc_info.value).lower()


def test_full_successful_url_extraction_flow():
    """Verify the high-level extract_job_description_from_url pipeline."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    mock_session = MagicMock()
    mock_session.get.return_value = _create_mock_response(
        status_code=200,
        body=SAMPLE_JOB_HTML.encode("utf-8"),
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        result = extract_job_description_from_url(
            "https://careers.google.com/jobs/results/12345",
            session=mock_session,
        )

    assert result["status"] == "success"
    assert "Senior Software Engineer" in result["job_description"]
    assert result["character_count"] > 100
    assert result["url"] == "https://careers.google.com/jobs/results/12345"


# ==============================================================================
# REST API Endpoint Tests
# ==============================================================================

def test_api_extract_url_success():
    """Verify POST /api/job-description/extract-url returns 200 with extracted text."""
    client = app.test_client()

    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value = _create_mock_response(
                status_code=200,
                body=SAMPLE_JOB_HTML.encode("utf-8"),
            )
            response = client.post(
                "/api/job-description/extract-url",
                json={"url": "https://careers.google.com/jobs/123"},
            )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["status"] == "success"
    assert "Senior Software Engineer" in data["job_description"]
    assert data["character_count"] > 100


def test_api_extract_url_ssrf_blocked():
    """Verify POST /api/job-description/extract-url blocks loopback with 400."""
    client = app.test_client()

    response = client.post(
        "/api/job-description/extract-url",
        json={"url": "http://127.0.0.1:8000/private-data"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert data["error_type"] == "security_restriction"
    assert "Loopback" in data["error"] or "security reasons" in data["error"]


def test_api_extract_url_missing_param():
    """Verify POST /api/job-description/extract-url returns 400 when URL is omitted."""
    client = app.test_client()

    response = client.post(
        "/api/job-description/extract-url",
        json={},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert "valid job posting link" in data["error"].lower()


def test_api_extract_url_extraction_failure_returns_422():
    """Verify non-HTML or bot blocking returns 422 with clear message."""
    client = app.test_client()

    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value = _create_mock_response(
                status_code=403,
            )
            response = client.post(
                "/api/job-description/extract-url",
                json={"url": "https://careers.protected-site.com/job/456"},
            )

    assert response.status_code == 422
    data = response.get_json()
    assert data["success"] is False
    assert data["error_type"] == "extraction_failed"
    assert "HTTP 403" in data["error"]
    assert "manually" in data["error"].lower()
