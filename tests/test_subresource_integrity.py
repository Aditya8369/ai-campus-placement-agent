"""
Unit and Integration Tests for Subresource Integrity (SRI) (#648)
==================================================================
Validates:
1. Every external <script> and <link rel="stylesheet"> tag in templates/ has:
   - An exact pinned version.
   - A valid cryptographic integrity hash (sha384-...).
   - A crossorigin="anonymous" attribute.
2. The validator detects and fails on unprotected resources (missing integrity, missing crossorigin, unpinned version).
3. The site continues to work with the configured Content Security Policy (CSP).
"""

from pathlib import Path
import pytest
from app import app
from utils.sri_validator import (
    scan_templates_directory,
    scan_template_content,
    check_tag_sri,
    is_version_pinned,
)


def test_every_external_script_and_stylesheet_has_sri_and_crossorigin():
    """
    Acceptance Criteria: Every external script and stylesheet has a pinned version
    and an integrity hash, along with crossorigin='anonymous'.
    """
    violations, stats = scan_templates_directory("templates")
    assert stats["scanned_files"] > 0, "Templates directory must contain HTML files."
    assert stats["external_tags"] > 0, "External tags must be discovered and audited."

    if violations:
        violation_details = "\n".join(
            f"[{v['file']}] {v['type']} {v['url']}: {', '.join(v['errors'])}"
            for v in violations
        )
        pytest.fail(f"Found {len(violations)} template SRI violation(s):\n{violation_details}")

    assert len(violations) == 0


def test_all_external_urls_pinned_to_exact_versions():
    """Verify that all external resource URLs in templates avoid floating/unpinned tags like 'latest'."""
    dir_path = Path("templates")
    for html_file in dir_path.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8", errors="ignore")
        violations = scan_template_content(content, filename=html_file.name)
        unpinned = [v for v in violations if any("Unpinned" in e for e in v["errors"])]
        assert len(unpinned) == 0, f"Unpinned resources found in {html_file.name}: {unpinned}"


def test_sri_check_fails_on_unprotected_external_script():
    """Acceptance Criteria: The test fails when an unprotected external script is added."""
    unprotected_template = """
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body>
      <script src="https://cdn.example.com/unprotected/library.js"></script>
    </body>
    </html>
    """
    violations = scan_template_content(unprotected_template, filename="unprotected_script.html")
    assert len(violations) >= 1
    v = violations[0]
    assert v["type"] == "script"
    assert "https://cdn.example.com/unprotected/library.js" in v["url"]
    assert any("integrity" in err.lower() for err in v["errors"])
    assert any("crossorigin" in err.lower() for err in v["errors"])


def test_sri_check_fails_on_unprotected_external_stylesheet():
    """Acceptance Criteria: The test fails when an unprotected external stylesheet is added."""
    unprotected_template = """
    <!DOCTYPE html>
    <html>
    <head>
      <link rel="stylesheet" href="https://cdn.example.com/styles.css">
    </head>
    <body></body>
    </html>
    """
    violations = scan_template_content(unprotected_template, filename="unprotected_stylesheet.html")
    assert len(violations) >= 1
    v = violations[0]
    assert v["type"] == "stylesheet"
    assert "https://cdn.example.com/styles.css" in v["url"]
    assert any("integrity" in err.lower() for err in v["errors"])
    assert any("crossorigin" in err.lower() for err in v["errors"])


def test_sri_check_fails_on_missing_crossorigin():
    """Verify that specifying an integrity hash without crossorigin='anonymous' is rejected."""
    missing_crossorigin = """
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
            integrity="sha384-geWF76RCwLtnZ8qwWowPQNguL3RmwHVBC9FhGdlKrxdiJJigb/j/68SIy3Te4Bkz">
    </script>
    """
    violations = scan_template_content(missing_crossorigin, filename="missing_crossorigin.html")
    assert len(violations) == 1
    assert any("crossorigin" in err.lower() for err in violations[0]["errors"])


def test_sri_check_fails_on_unpinned_floating_version():
    """Verify that using 'latest' or unversioned URLs is rejected even if integrity is present."""
    floating_version = """
    <script src="https://cdn.example.com/chart.js/latest/chart.min.js"
            integrity="sha384-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            crossorigin="anonymous">
    </script>
    """
    violations = scan_template_content(floating_version, filename="floating_version.html")
    assert len(violations) == 1
    assert any("Unpinned resource version" in err for err in violations[0]["errors"])


def test_site_works_with_current_csp():
    """
    Acceptance Criteria: The site still works with the current CSP.
    Verifies HTTP 200 responses on public routes and confirms CSP permits CDN origins.
    """
    app.config["TESTING"] = True
    with app.test_client() as client:
        # 1. Landing page
        res = client.get("/")
        assert res.status_code == 200
        csp = res.headers.get("Content-Security-Policy", "")
        assert "https://cdn.jsdelivr.net" in csp
        assert "https://cdnjs.cloudflare.com" in csp

        # 2. Login page
        res_login = client.get("/login")
        assert res_login.status_code == 200

        # 3. Status page
        res_status = client.get("/status")
        assert res_status.status_code == 200

        # 4. Interactive Swagger UI
        res_docs = client.get("/docs")
        assert res_docs.status_code == 200
