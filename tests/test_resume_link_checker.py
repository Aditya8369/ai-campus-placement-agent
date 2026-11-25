"""
Comprehensive unit tests for Resume Profile Link Checker (#845)

Acceptance Criteria:
1. Malformed links are reported without any network call.
2. Private and loopback targets are never requested (SSRF prevention).
3. Timeouts and errors show as 'could not verify', not as failures.
4. Rate limiting per user.
5. Tests mock the HTTP layer.
"""

from unittest.mock import MagicMock, patch
import pytest
import requests
from utils.resume_link_service import (
    analyze_resume_links,
    check_url_reachability,
    clear_rate_limits,
    extract_links_from_text,
    is_rate_limited,
    is_safe_public_host,
    validate_url_format,
)


def test_extract_links_from_text():
    """Extracts URLs and profile handles with and without explicit schemes."""
    text = """
    Jane Doe - Full Stack Developer
    Portfolio: https://janedoe.dev
    GitHub: github.com/janedoe/repo
    LinkedIn: https://linkedin.com/in/jane-doe-123.
    LeetCode: https://leetcode.com/janedoe/
    Email: jane@example.com (not a URL)
    Website: www.myportfolio.org/projects/
    """
    links = extract_links_from_text(text)
    assert "https://janedoe.dev" in links
    assert "https://github.com/janedoe/repo" in links
    assert "https://linkedin.com/in/jane-doe-123" in links
    assert "https://leetcode.com/janedoe" in links
    assert "https://www.myportfolio.org/projects" in links
    assert not any("jane@example.com" in l for l in links)


def test_malformed_links_reported_without_network_call():
    """Acceptance criterion: Malformed links are reported without any network call."""
    malformed_cases = [
        "https://github.com/",             # missing username
        "https://github.com/-invalid",     # invalid github username leading hyphen
        "https://linkedin.com/pub/foo",    # wrong profile path
        "https://linkedin.com/in/",        # missing handle
        "ftp://myfiles.com/resume.pdf",    # unsupported scheme
        "https://notadomain",              # host without dot
    ]

    with patch("requests.Session.head") as mock_head, patch("requests.Session.get") as mock_get:
        for malformed in malformed_cases:
            is_valid, link_type, err, fix = validate_url_format(malformed)
            assert is_valid is False
            assert err is not None
            assert fix is not None

        # Pass text with malformed links into analyze_resume_links
        resume_text = "Links: https://github.com/ and https://linkedin.com/pub/foo"
        report = analyze_resume_links(resume_text, check_reachability=True)
        assert report["malformed_count"] == 2
        assert report["has_issues"] is True
        for item in report["links"]:
            assert item["status"] == "malformed"
            assert "Malformed" in item["status_label"]

        # Ensure NO network calls were made for malformed links
        mock_head.assert_not_called()
        mock_get.assert_not_called()


def test_private_and_loopback_targets_never_requested():
    """Acceptance criterion: Private and loopback targets are never requested (SSRF protection)."""
    private_hosts = [
        "127.0.0.1",
        "localhost",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.5",
        "169.254.169.254", # AWS metadata endpoint
        "::1",
    ]

    with patch("requests.Session.head") as mock_head, patch("requests.Session.get") as mock_get:
        for host in private_hosts:
            assert is_safe_public_host(host) is False

            url = f"http://{host}/admin"
            res = check_url_reachability(url)
            assert res["status"] == "could_not_verify"
            assert "Could not verify" in res["status_label"]
            assert "non-public" in res["detail"]

        # Zero network calls initiated to prohibited hosts
        mock_head.assert_not_called()
        mock_get.assert_not_called()


def test_ssrf_redirect_into_private_ip_is_blocked():
    """Validates that a public URL redirecting to a private/loopback IP is blocked."""
    url = "https://public-service.com/redirect"

    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.url = "http://127.0.0.1/admin" # Redirected to loopback!

    with patch("utils.resume_link_service.is_safe_public_host") as mock_safe:
        # Initial host is safe, redirected host is unsafe
        mock_safe.side_effect = lambda h: h != "127.0.0.1"
        with patch("requests.Session.head", return_value=mock_resp):
            res = check_url_reachability(url)
            assert res["status"] == "could_not_verify"
            assert "Redirected to private" in res["detail"]


def test_timeouts_and_errors_show_as_could_not_verify_not_failure():
    """Acceptance criterion: Timeouts and errors show as 'could not verify', not as failures."""
    url = "https://example.com/slow-portfolio"

    with patch("utils.resume_link_service.is_safe_public_host", return_value=True):
        # 1. Timeout
        with patch("requests.Session.head", side_effect=requests.exceptions.Timeout("Timed out")):
            res = check_url_reachability(url)
            assert res["status"] == "could_not_verify"
            assert res["status_label"] == "Could not verify"
            assert "timed out" in res["detail"].lower()
            assert res["status_code"] is None

        # 2. Connection Error
        with patch("requests.Session.head", side_effect=requests.exceptions.ConnectionError("Refused")):
            res = check_url_reachability(url)
            assert res["status"] == "could_not_verify"
            assert res["status_label"] == "Could not verify"
            assert "connection failed" in res["detail"].lower()


def test_successful_and_broken_reachability_mocked():
    """Tests 200 OK working and 404 broken reachability with mocked HTTP layer."""
    with patch("utils.resume_link_service.is_safe_public_host", return_value=True):
        # 200 OK
        resp_200 = MagicMock(status_code=200, url="https://github.com/torvalds")
        with patch("requests.Session.head", return_value=resp_200):
            res = check_url_reachability("https://github.com/torvalds")
            assert res["status"] == "working"
            assert res["status_code"] == 200

        # 404 Not Found
        resp_404 = MagicMock(status_code=404, url="https://github.com/torvalds/nonexistent404")
        with patch("requests.Session.head", return_value=resp_404):
            res = check_url_reachability("https://github.com/torvalds/nonexistent404")
            assert res["status"] == "broken"
            assert res["status_code"] == 404
            assert "404 Not Found" in res["status_label"]


def test_per_user_rate_limiting():
    """Validates sliding-window rate limit per user."""
    clear_rate_limits()
    user = "student_test_rate_limit"

    # Should allow up to MAX_CHECKS_PER_MINUTE (10)
    for _ in range(10):
        assert is_rate_limited(user) is False

    # 11th request within 60s should be rate limited
    assert is_rate_limited(user) is True


def test_analyze_resume_links_full_integration_mocked():
    """Verifies end-to-end report generation with working, broken, and malformed links."""
    resume_text = """
    John Doe
    GitHub: https://github.com/gooduser
    Portfolio: https://myportfolio.com/dead
    Broken Link: https://github.com/
    LinkedIn: https://linkedin.com/in/johndoe
    """

    def mock_reachability(url, timeout=2.5, session=None):
        if "gooduser" in url or "linkedin" in url:
            return {"status": "working", "status_label": "Working", "status_code": 200, "detail": "HTTP 200 OK"}
        elif "dead" in url:
            return {"status": "broken", "status_label": "Broken (404 Not Found)", "status_code": 404, "detail": "Page returned 404"}
        return {"status": "could_not_verify", "status_label": "Could not verify", "status_code": None, "detail": "Error"}

    with patch("utils.resume_link_service.check_url_reachability", side_effect=mock_reachability):
        report = analyze_resume_links(resume_text, check_reachability=True, user_id="user_123")
        assert report["total_links"] == 4
        assert report["working_count"] == 2
        assert report["broken_count"] == 1
        assert report["malformed_count"] == 1
        assert report["has_issues"] is True


def test_api_resume_links_endpoints(client):
    """Tests the Flask endpoints for resume links."""
    # Test stateless endpoint POST /api/resume/check-links
    resp = client.post(
        "/api/resume/check-links",
        json={
            "resume_text": "GitHub: https://github.com/sampleuser LinkedIn: https://linkedin.com/in/sampleuser",
            "check_reachability": False
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "resume_links" in data
    assert data["resume_links"]["total_links"] == 2
