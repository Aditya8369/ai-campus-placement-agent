"""
Playwright End-to-End Browser Integration Tests (#858)
======================================================
Tests the full student user journey through the live browser UI:
1. Register a new student account.
2. Log in with registered credentials.
3. Upload a sample resume PDF, agree to privacy consent, and submit for analysis.
4. Verify the analysis completes with mocked AI and displays the dashboard.
5. Navigate into the interactive mock interview session.
6. Log out cleanly and verify session termination.

Ensures templates, frontend JavaScript, routes, and backend agents remain integrated.
Operates fully offline with zero external network dependencies or real API keys.
"""

import json
import os
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
import pytest

# Skip gracefully if playwright is not installed in standard unit test environments
pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from werkzeug.serving import make_server

import config
from db.migrations import init_db as initialize_database
from routes import create_app
from tests.conftest import MockGeminiClient, MockGeminiResponse


@pytest.fixture
def sample_resume_pdf(tmp_path):
    """Generates a valid, readable sample resume PDF file for test uploads."""
    pdf_path = tmp_path / "jane_doe_resume.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 750, "Jane Doe - Software Engineer")
    c.drawString(100, 730, "Email: jane.doe.e2e@example.com | Phone: 123-456-7890")
    c.drawString(100, 710, "Education: Bachelor of Technology in Computer Science, GPA 8.9")
    c.drawString(100, 690, "Technical Skills: Python, Flask, SQL, PostgreSQL, REST APIs, Git, Algorithms")
    c.drawString(100, 670, "Projects: AI Placement Agent - Built full-stack web application with SQLite.")
    c.drawString(100, 650, "Experience: Software Intern - Designed microservice endpoints and automated tests.")
    c.save()
    return str(pdf_path)


@pytest.fixture
def live_server_url(monkeypatch, sample_coordinator_json):
    """
    Spins up a live, isolated Werkzeug HTTP server for Playwright browser testing.
    Uses a temporary SQLite database, mocked AI client, and disabled rate limits.
    """
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db_path = temp_db.name
    temp_db.close()

    # Configure isolated environment
    monkeypatch.setenv("DATABASE_PATH", temp_db_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key-playwright")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-playwright-secret-key-12345678901234567890")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("CAPTCHA_PROVIDER", "")
    monkeypatch.setenv("CAPTCHA_SITE_KEY", "")
    monkeypatch.setenv("CAPTCHA_SECRET_KEY", "")

    config.DATABASE_PATH = Path(temp_db_path)
    config.GEMINI_API_KEY = "fake-gemini-key-playwright"

    # Initialize schema
    initialize_database(config.DATABASE_PATH)

    # Mock Gemini client
    fake_client = MockGeminiClient(response_text=json.dumps(sample_coordinator_json))
    monkeypatch.setattr("utils.gemini.get_gemini_client", lambda *args, **kwargs: fake_client)

    # Create application instance with login enforcement active
    app = create_app()
    app.config.update({
        "TESTING": False,
        "TESTING_BYPASS_VERIFICATION": True,
        "WTF_CSRF_ENABLED": False,
        "ENFORCE_LOGIN_IN_TESTS": True,
        "SERVER_NAME": None,
    })

    # Pick an available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = make_server("127.0.0.1", port, app, threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    # Wait until live server accepts connections
    start_time = time.time()
    while time.time() - start_time < 5.0:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.05)

    try:
        yield base_url
    finally:
        server.shutdown()
        server_thread.join(timeout=3)
        try:
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)
        except OSError:
            pass


def test_playwright_complete_student_journey(live_server_url, sample_resume_pdf, page: Page):
    """
    End-to-end browser journey test verifying:
    1. Account Registration (/register)
    2. Authentication & Session Login (/login)
    3. Resume Upload & Placement Analysis with mocked AI (/)
    4. Candidate Dashboard View (/dashboard/<id>)
    5. Interactive Mock Interview Session (/interview/<id>)
    6. Session Termination (/logout)
    """
    # --------------------------------------------------------------------------
    # Step 1: Register a new student account
    # --------------------------------------------------------------------------
    page.goto(f"{live_server_url}/register")
    expect(page.locator("h2")).to_contain_text("Create Account")

    test_name = "Jane Doe"
    test_email = "jane.doe.e2e@example.com"
    test_password = "SecureStudentPass123!"

    page.fill("#regName", test_name)
    page.fill("#regEmail", test_email)
    page.fill("#regPassword", test_password)
    page.fill("#regCollege", "National Institute of Technology")
    page.click("button[type='submit']")

    # Successful registration redirects to /login
    page.wait_for_url("**/login**", timeout=10000)
    expect(page.locator("body")).to_contain_text("Registration successful")

    # --------------------------------------------------------------------------
    # Step 2: Log in with registered credentials
    # --------------------------------------------------------------------------
    page.fill("#loginEmail", test_email)
    page.fill("#loginPassword", test_password)
    page.click("button[type='submit']")

    # Successful login redirects away from /login to the home/dashboard view
    page.wait_for_url(lambda url: "/login" not in url, timeout=10000)
    expect(page.locator("body")).to_contain_text("Jane Doe")

    # --------------------------------------------------------------------------
    # Step 3: Upload sample resume & trigger placement analysis
    # --------------------------------------------------------------------------
    # Attach sample PDF file to the file input
    page.set_input_files("#resumeInput", sample_resume_pdf)

    # Target company
    page.select_option("#companySelect", "Google")

    # Agree to privacy consent checkbox
    page.check("#privacyConsentCheck")

    # Submit analysis form
    page.click("#btnSubmitAnalysis")

    # --------------------------------------------------------------------------
    # Step 4: Verify redirection to Candidate Dashboard
    # --------------------------------------------------------------------------
    dashboard_url_pattern = re.compile(r"/dashboard/[a-f0-9\-]+")
    page.wait_for_url(dashboard_url_pattern, timeout=25000)
    expect(page.locator("body")).to_contain_text("Google")
    expect(page.locator("body")).to_contain_text("ATS")

    # --------------------------------------------------------------------------
    # Step 5: Start a short interactive mock interview
    # --------------------------------------------------------------------------
    # Locate and click on the mock interview button / link
    interview_link = page.locator("a[href*='/interview/']").first
    expect(interview_link).to_be_visible()
    interview_link.click()

    interview_url_pattern = re.compile(r"/interview/[a-f0-9\-]+")
    page.wait_for_url(interview_url_pattern, timeout=15000)
    expect(page.locator("body")).to_contain_text("Interview")

    # --------------------------------------------------------------------------
    # Step 6: Log out cleanly
    # --------------------------------------------------------------------------
    page.goto(f"{live_server_url}/logout")
    page.wait_for_url(lambda url: "/login" in url or url.rstrip("/") == live_server_url or url.endswith("/dashboard"), timeout=10000)
    expect(page.locator("body")).to_contain_text("logged out")
