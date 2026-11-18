"""
Unit and Integration Tests for ATS Resume Format Compatibility Checker (#474).
==============================================================================
Tests:
1. Single-column PDF resume passes all 5 format checks.
2. Two-column PDF resume detects multi-column layout and warns with one-line fix.
3. PDF with table grid detects tabular layout and warns with one-line fix.
4. PDF with embedded images detects raster graphics and warns with one-line fix.
5. PDF with >2 pages warns on page count.
6. PDF with 1 or 2 pages passes page count check.
7. Low-density or garbled text extraction triggers warning.
8. Rule-based format check is strictly non-blocking: analysis workflow completes normally.
9. GET /api/analysis/<analysis_id>/format-compatibility returns evaluation JSON.
10. POST /api/resume/format-compatibility evaluates uploaded files or raw text.
11. Dashboard renders format compatibility card with pass/warn badges and fixes.
12. Demo mode includes format compatibility in synthetic data.
"""

import io
import json
import os
import uuid
import pytest
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from app import app
from utils.database import init_db, save_analysis
from utils.format_checker import (
    check_embedded_images,
    check_multi_column_layout,
    check_page_count,
    check_pdf_format_compatibility,
    check_resume_format_compatibility,
    check_tables_and_grids,
    check_text_legibility,
    get_or_compute_format_compatibility,
)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure database is initialized before running tests."""
    init_db()


@pytest.fixture
def client():
    """Provides a Flask test client with testing and debug configs."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test_user_format_check"
            sess["user_email"] = "format_checker@test.com"
            sess["user_name"] = "Format Checker Test User"
        yield client


def make_single_column_pdf(pages: int = 1) -> bytes:
    """Creates a standard single-column PDF resume."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for p in range(pages):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(54, 750, f"Alex Chen - Page {p+1}")
        c.setFont("Helvetica", 10)
        c.drawString(54, 730, "alex.chen@berkeley.edu | (555) 019-2834 | San Francisco, CA")
        c.drawString(54, 705, "PROFESSIONAL SUMMARY")
        c.drawString(
            54, 690,
            "Software engineer with strong experience in Python, distributed task queues, and APIs."
        )
        c.drawString(54, 665, "EDUCATION")
        c.drawString(54, 650, "B.S. in Computer Science - University of California, Berkeley (2020 - 2024)")
        c.drawString(54, 625, "TECHNICAL SKILLS")
        c.drawString(54, 610, "Python, Java, C++, Docker, Kubernetes, AWS, PostgreSQL, Redis, REST APIs, Git")
        c.drawString(54, 585, "WORK EXPERIENCE")
        c.drawString(54, 570, "Software Engineering Intern - CloudTech Solutions (June 2023 - August 2023)")
        c.drawString(
            54, 555,
            "Architected RESTful microservices in Python, improving reporting pipeline throughput by 25%."
        )
        c.drawString(54, 530, "PROJECTS")
        c.drawString(54, 515, "Distributed Task Queue - Python, Redis, Docker")
        c.drawString(
            54, 500,
            "Engineered distributed background workers processing 5,000+ jobs per minute with priority scheduling."
        )
        if p < pages - 1:
            c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def make_two_column_pdf() -> bytes:
    """Creates a two-column PDF resume with side-by-side text blocks."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(54, 750, "Devon Vance")
    c.setFont("Helvetica", 10)
    c.drawString(54, 730, "devon.vance@example.com | +1 555-890-1234 | Austin, TX")

    # Draw left and right columns across multiple vertical lines
    for i in range(8):
        y = 680 - (i * 24)
        c.drawString(54, y, f"Left column education and skills description paragraph line {i+1} with detailed content.")
        c.drawString(330, y, f"Right column work experience and project description line {i+1} with detailed text.")
    c.save()
    buf.seek(0)
    return buf.getvalue()


def make_table_pdf() -> bytes:
    """Creates a PDF containing an explicit table grid."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    data = [
        ["Degree", "Institution", "Graduation Year", "Cumulative GPA"],
        ["B.Tech CS", "Midwest State University", "2020 - 2024", "3.9 / 4.0"],
        ["High School Diploma", "Central High School", "2018 - 2020", "4.0 / 4.0"],
        ["Certifications", "AWS Certified Developer", "2023", "Pass with Merit"],
    ]
    t = Table(data)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ]))
    doc.build([
        Paragraph("Elena Rostova", styles["Heading1"]),
        Paragraph("elena.rostova@example.com | Full Stack Developer", styles["Normal"]),
        t,
        Paragraph("Technical Skills: Python, Java, C++, TypeScript, React, Docker, Kubernetes, SQL", styles["Normal"]),
        Paragraph("Work Experience: Backend Intern at DataFlow Tech developing ETL pipelines", styles["Normal"]),
    ])
    buf.seek(0)
    return buf.getvalue()


def make_image_pdf() -> bytes:
    """Creates a PDF with an embedded raster image."""
    img_buf = io.BytesIO()
    img = Image.new("RGB", (120, 120), color=(50, 120, 200))
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    reader = ImageReader(img_buf)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(54, 750, "Marcus Sterling")
    c.setFont("Helvetica", 10)
    c.drawString(54, 730, "marcus.sterling@example.com | Portfolio with Photo")
    c.drawImage(reader, 54, 600, width=90, height=90)
    c.drawString(54, 560, "PROFESSIONAL SUMMARY")
    c.drawString(54, 540, "Software developer with focus on frontend and graphic design systems.")
    c.drawString(54, 515, "TECHNICAL SKILLS")
    c.drawString(54, 495, "Python, JavaScript, React, CSS, Docker, Git, SQL, Figma, REST APIs")
    c.drawString(54, 470, "EXPERIENCE")
    c.drawString(54, 450, "Frontend Engineer Intern at PixelCorp developing interactive component libraries.")
    c.save()
    buf.seek(0)
    return buf.getvalue()


# ==============================================================================
# UNIT TESTS FOR FORMAT CHECKER RULES
# ==============================================================================

def test_single_column_pdf_passes_all_checks():
    """A standard single-column text resume must pass all 5 layout checks cleanly."""
    pdf_bytes = make_single_column_pdf(pages=1)
    result = check_pdf_format_compatibility(pdf_bytes)

    assert result["overall_status"] == "pass"
    assert result["warn_count"] == 0
    assert result["passed_count"] == 5
    assert result["total_checks"] == 5
    assert result["score_percentage"] == 100

    check_map = {c["id"]: c for c in result["checks"]}
    assert "page_count" in check_map
    assert "multi_column" in check_map
    assert "tables" in check_map
    assert "images" in check_map
    assert "text_extraction" in check_map

    for c in result["checks"]:
        assert c["status"] == "pass"
        assert len(c["explanation"]) > 0
        assert len(c["fix"]) > 0


def test_two_column_pdf_warns_on_multi_column():
    """Two-column resumes should trigger a multi_column warning with an actionable fix."""
    pdf_bytes = make_two_column_pdf()
    result = check_pdf_format_compatibility(pdf_bytes)

    assert result["overall_status"] == "warn"
    check_map = {c["id"]: c for c in result["checks"]}
    col_check = check_map["multi_column"]

    assert col_check["status"] == "warn"
    assert "multi-column" in col_check["explanation"].lower() or "parallel" in col_check["explanation"].lower()
    assert "single-column" in col_check["fix"].lower()


def test_table_pdf_warns_on_tables():
    """Resumes with table grids must report a warning and suggest bullet points."""
    pdf_bytes = make_table_pdf()
    result = check_pdf_format_compatibility(pdf_bytes)

    check_map = {c["id"]: c for c in result["checks"]}
    table_check = check_map["tables"]

    assert table_check["status"] == "warn"
    assert "table" in table_check["explanation"].lower()
    assert "bullet" in table_check["fix"].lower()


def test_image_pdf_warns_on_embedded_images():
    """Resumes with embedded raster graphics must report a warning and recommend plain text."""
    pdf_bytes = make_image_pdf()
    result = check_pdf_format_compatibility(pdf_bytes)

    check_map = {c["id"]: c for c in result["checks"]}
    img_check = check_map["images"]

    assert img_check["status"] == "warn"
    assert "image" in img_check["explanation"].lower() or "icon" in img_check["explanation"].lower()
    assert "text" in img_check["fix"].lower()


def test_page_count_rule_bounds():
    """Resumes of 1-2 pages pass; >2 pages warn."""
    # 1 page passes
    one_page_pdf = make_single_column_pdf(pages=1)
    res_1 = check_pdf_format_compatibility(one_page_pdf)
    c1 = next(c for c in res_1["checks"] if c["id"] == "page_count")
    assert c1["status"] == "pass"
    assert c1["value"] == 1

    # 2 pages pass
    two_page_pdf = make_single_column_pdf(pages=2)
    res_2 = check_pdf_format_compatibility(two_page_pdf)
    c2 = next(c for c in res_2["checks"] if c["id"] == "page_count")
    assert c2["status"] == "pass"
    assert c2["value"] == 2

    # 3 pages warn
    three_page_pdf = make_single_column_pdf(pages=3)
    res_3 = check_pdf_format_compatibility(three_page_pdf)
    c3 = next(c for c in res_3["checks"] if c["id"] == "page_count")
    assert c3["status"] == "warn"
    assert c3["value"] == 3
    assert "1-2" in c3["fix"]


def test_text_legibility_rule():
    """Low text density or corrupt encodings trigger text_extraction warning."""
    # Low word count (< 30 words)
    low_text = check_text_legibility("John Doe\nDeveloper", page_count=1)
    assert low_text["status"] == "warn"
    assert "Low text density" in low_text["explanation"]

    # High garbled character ratio
    garbled = "Valid start\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\ufffd\ufffd\ufffd" * 5
    garbled_check = check_text_legibility(garbled, page_count=1)
    assert garbled_check["status"] == "warn"

    # Clean text passes
    clean = "This is a clean resume text. " * 50
    clean_check = check_text_legibility(clean, page_count=1)
    assert clean_check["status"] == "pass"


# ==============================================================================
# INTEGRATION & API TESTS
# ==============================================================================

def test_format_warnings_never_stop_analysis(client, monkeypatch):
    """
    Format warnings must never stop or fail the placement analysis workflow.
    Even with multi-column, table, and image warnings, the analysis completes normally.
    """
    from agents.coordinator import CoordinatorAgent

    dummy_payload = {
        "resume_analysis": {"ats_score": 75, "summary": "Good profile."},
        "job_match": {"match_percentage": 78},
        "skill_gap": [],
    }
    monkeypatch.setattr(CoordinatorAgent, "analyze", lambda self, *args, **kwargs: dummy_payload)

    two_col_pdf = make_two_column_pdf()
    response = client.post(
        "/analyze",
        data={
            "resume": (io.BytesIO(two_col_pdf), "two_col_resume.pdf"),
            "company": "Google",
            "job_description": "Software engineer with Python experience.",
            "privacy_consent": "true",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    # Should succeed and redirect to dashboard
    assert response.status_code == 200
    assert b"Format Compatibility Check" in response.data or b"Format compatibility" in response.data or b"formatCompatibilityCard" in response.data


def test_api_get_format_compatibility(client):
    """GET /api/analysis/<analysis_id>/format-compatibility returns evaluation JSON."""
    analysis_id = str(uuid.uuid4())
    save_analysis(
        analysis_id=analysis_id,
        resume_filename="sample_resume.pdf",
        company_name="Google",
        job_description="Software Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 80},
        },
        student_id="test_user_format_check",
    )

    resp = client.get(f"/api/analysis/{analysis_id}/format-compatibility")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "format_compatibility" in data
    fc = data["format_compatibility"]
    assert "overall_status" in fc
    assert "checks" in fc
    assert len(fc["checks"]) == 5


def test_api_post_format_compatibility_with_pdf(client):
    """POST /api/resume/format-compatibility evaluates uploaded PDF files directly."""
    single_col_pdf = make_single_column_pdf(pages=1)
    resp = client.post(
        "/api/resume/format-compatibility",
        data={"resume": (io.BytesIO(single_col_pdf), "single_column.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    fc = data["format_compatibility"]
    assert fc["overall_status"] == "pass"
    assert fc["passed_count"] == 5


def test_api_post_format_compatibility_with_text(client):
    """POST /api/resume/format-compatibility handles raw JSON text."""
    resp = client.post(
        "/api/resume/format-compatibility",
        json={"resume_text": "Alex Chen\nSoftware Engineer with experience in Python and Docker.\n" * 20},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "format_compatibility" in data


def test_dashboard_renders_format_compatibility_card(client):
    """Dashboard HTML renders format compatibility card with pass/warn badges and fixes."""
    analysis_id = str(uuid.uuid4())
    save_analysis(
        analysis_id=analysis_id,
        resume_filename="single_col.pdf",
        company_name="Google",
        job_description="Software Engineer",
        results_dict={
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 82},
            "format_compatibility": {
                "overall_status": "warn",
                "passed_count": 4,
                "warn_count": 1,
                "total_checks": 5,
                "score_percentage": 80,
                "checks": [
                    {
                        "id": "page_count",
                        "name": "Page Count",
                        "status": "pass",
                        "explanation": "1 page detected.",
                        "fix": "Keep within 1-2 pages.",
                        "value": 1,
                    },
                    {
                        "id": "multi_column",
                        "name": "Single-Column Layout",
                        "status": "warn",
                        "explanation": "Multi-column layout detected.",
                        "fix": "Maintain a linear single-column layout.",
                        "value": True,
                    },
                    {
                        "id": "tables",
                        "name": "Tables & Grids",
                        "status": "pass",
                        "explanation": "No tables detected.",
                        "fix": "Avoid tables.",
                        "value": False,
                    },
                    {
                        "id": "images",
                        "name": "Embedded Images",
                        "status": "pass",
                        "explanation": "No images detected.",
                        "fix": "Avoid images.",
                        "value": 0,
                    },
                    {
                        "id": "text_extraction",
                        "name": "Text Extraction & Encoding",
                        "status": "pass",
                        "explanation": "Clean text extracted.",
                        "fix": "Maintain standard fonts.",
                        "value": {"word_count": 350},
                    },
                ],
            },
        },
        student_id="test_user_format_check",
    )

    resp = client.get(f"/dashboard/{analysis_id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    assert 'id="formatCompatibilityCard"' in html
    assert "Format Compatibility Check" in html
    assert "Layout Warnings Detected" in html
    assert "Maintain a linear single-column layout." in html
    assert 'data-check-id="multi_column"' in html


def test_demo_mode_includes_format_compatibility(client):
    """Demo mode includes format compatibility in synthetic data and displays cleanly."""
    resp = client.get("/dashboard/demo-sample-analysis")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    assert 'id="formatCompatibilityCard"' in html
    assert "Format Compatibility Check" in html
    assert "ATS-Friendly Layout" in html
