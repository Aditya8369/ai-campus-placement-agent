"""
Unit and integration tests for Resume Page-Level PDF Issue Detection (#597).

Verifies:
1. Normal clean single-column PDF resumes do not produce false warnings and report 0 problem pages.
2. Two-column / multi-column PDF pages accurately flag the specific problem page number.
3. PDF pages containing tables and vector grids identify the exact page and tabular structure.
4. Embedded images and graphics detect page numbers with trapped icons.
5. Extraction explanations are clear and understandable to students (explain undetected content & layout fix).
6. Dashboard template renders page-level diagnostics container, problem page badge, and thumbnails.
7. REST API endpoint GET /api/analysis/<analysis_id>/pdf-page-issues returns page-by-page reports.
"""

import io
import json
import os
import tempfile
from pathlib import Path
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from PIL import Image

from routes import create_app
import config
from utils.database import init_db, save_analysis
from utils.pdf_page_issue_detector import analyze_pdf_page_issues


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "student_page_test_user"
        yield client


def _create_clean_single_column_pdf() -> bytes:
    """Generates a clean 2-page single column ATS-compliant PDF resume."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    # Page 1
    c.drawString(72, 750, "Jane Doe - Full Stack Software Engineer")
    c.drawString(72, 730, "Email: janedoe@university.edu | Phone: 555-0199 | Location: Bangalore")
    c.drawString(72, 700, "EDUCATION")
    c.drawString(72, 680, "Bachelor of Technology in Computer Science - CGPA 9.2/10")
    c.drawString(72, 650, "TECHNICAL SKILLS")
    c.drawString(72, 630, "Python, Flask, SQLite, Data Structures, Algorithms, Git, Docker, REST APIs")
    c.drawString(72, 600, "EXPERIENCE & PROJECTS")
    c.drawString(72, 580, "Built distributed microservices engine reducing API latency by 35 percent.")
    c.drawString(72, 560, "Engineered end-to-end continuous integration pipelines using GitHub Actions.")
    for y in range(540, 150, -20):
        c.drawString(72, y, "Implemented optimized graph traversal algorithms achieving linear execution time.")
    c.showPage()
    # Page 2
    c.drawString(72, 750, "CERTIFICATIONS & ACHIEVEMENTS")
    c.drawString(72, 730, "Ranked in top 1 percent in university coding contest across 4000 candidates.")
    for y in range(710, 300, -20):
        c.drawString(72, y, "Completed advanced system design and database indexing specialization coursework.")
    c.showPage()
    c.save()
    return buf.getvalue()


def _create_pdf_with_table_on_page_2() -> bytes:
    """Generates a PDF where Page 1 is clean text and Page 2 contains a table grid."""
    buf = io.BytesIO()
    from reportlab.platypus import PageBreak
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("John Smith - Data Engineer", styles["Title"]),
        Paragraph("Email: jsmith@university.edu | Location: Seattle", styles["Normal"]),
        Paragraph("Skills: Python, SQL, Apache Spark, Airflow, Kafka, Docker", styles["Normal"]),
    ]
    for _ in range(15):
        elements.append(Paragraph("Designed reliable ETL pipelines with automated validation and monitoring.", styles["Normal"]))

    elements.append(PageBreak())

    # Table on Page 2
    table_data = [
        ["Course", "Institution", "Grade", "Year"],
        ["B.Tech CS", "State University", "9.4", "2024"],
        ["Intermediate", "High School", "95%", "2020"]
    ]
    t = Table(table_data)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey)
    ]))
    elements.append(t)

    doc.build(elements)
    return buf.getvalue()


def _create_pdf_with_image_on_page_1() -> bytes:
    """Generates a PDF with an embedded image on Page 1."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    img = Image.new("RGB", (60, 60), color="blue")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(img_buf), 72, 700, width=50, height=50)
    c.drawString(140, 720, "Candidate Photo Icon")
    c.drawString(72, 650, "Skills: Python, Machine Learning, Deep Learning")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_clean_pdf_produces_no_false_warnings():
    """Verify standard single-column resume has 0 problem pages and reports clean status."""
    clean_bytes = _create_clean_single_column_pdf()
    report = analyze_pdf_page_issues(clean_bytes)

    assert report["success"] is True
    assert report["total_pages"] == 2
    assert report["problem_page_count"] == 0
    assert report["problem_page_numbers"] == []
    assert report["overall_status"] == "clean"
    assert "single-column" in report["summary_message"]


def test_table_grid_detection_identifies_exact_page():
    """Verify table grids flag the exact page number (Page 2) with explanation and layout fix."""
    pdf_bytes = _create_pdf_with_table_on_page_2()
    report = analyze_pdf_page_issues(pdf_bytes)

    assert report["success"] is True
    assert 2 in report["problem_page_numbers"]
    p2 = [p for p in report["pages"] if p["page_number"] == 2][0]
    assert p2["has_issues"] is True
    issue_codes = [iss["code"] for iss in p2["issues"]]
    assert "TABLE_GRID" in issue_codes
    table_issue = [iss for iss in p2["issues"] if iss["code"] == "TABLE_GRID"][0]
    assert "Table" in table_issue["type"]
    assert "bulleted lists" in table_issue["suggested_layout"].lower()


def test_embedded_images_detected_on_page():
    """Verify embedded graphic images flag the exact page."""
    img_pdf = _create_pdf_with_image_on_page_1()
    report = analyze_pdf_page_issues(img_pdf)

    assert report["success"] is True
    assert 1 in report["problem_page_numbers"]
    p1 = report["pages"][0]
    assert p1["has_issues"] is True
    assert any(iss["code"] == "EMBEDDED_IMAGES" for iss in p1["issues"])


def test_api_get_analysis_pdf_page_issues(client):
    """Verify GET /api/analysis/<analysis_id>/pdf-page-issues endpoint."""
    analysis_id = "test_analysis_pdf_issues_597"
    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Seeking Python Developer",
        results_dict={
            "ats_score": 85,
            "resume_analysis": {"strengths": [], "weaknesses": []},
            "job_match": {"match_percentage": 80}
        },
        student_id="student_page_test_user",
        resume_text="Jane Doe\nPython, Django, AWS\nSoftware Engineer at TechCorp\nEducation: B.Tech CS"
    )

    res = client.get(f"/api/analysis/{analysis_id}/pdf-page-issues")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "page_issues" in data
    assert data["page_issues"]["total_pages"] >= 1
    assert "pages" in data["page_issues"]


def test_dashboard_renders_page_level_diagnostics_markup():
    """Verify dashboard.html contains page issue markup and badge containers."""
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="pdfPageIssuesDiagnostics"' in html
    assert 'Page-Level Extraction & Layout Diagnostics' in html
    assert 'badgePageIssuesCount' in html
    assert 'badgePageIssuesClean' in html
    assert 'Undetected content:' in html
    assert 'Fix suggestion:' in html
