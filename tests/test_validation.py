import os
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-12345")
import pytest
import config
from reportlab.pdfgen import canvas

from utils.pdf_reader import (
    validate_resume_text,
    MIN_RESUME_TEXT_CHARS,
    MIN_RESUME_WORD_COUNT,
    MAX_RESUME_TEXT_CHARS,
    MAX_PDF_PAGES,
    MIN_PDF_EXTRACTED_CHARS,
    ScannedPDFError,
    standardize_resume_sections,
    format_standardized_resume,
    extract_text_with_ocr_fallback,
    extract_text_from_pdf,
)
from app import app


def test_validate_resume_text_empty():
    is_valid, msg = validate_resume_text("")
    assert not is_valid
    assert "empty" in msg.lower()

    is_valid, msg = validate_resume_text("   \n\t  ")
    assert not is_valid


def test_validate_resume_text_too_short():
    short_text = "I am a programmer."
    is_valid, msg = validate_resume_text(short_text)
    assert not is_valid
    assert f"minimum {MIN_RESUME_TEXT_CHARS}" in msg


def test_validate_resume_text_insufficient_words():
    # Length > 50 chars but only 4 words
    text_few_words = "Supercalifragilisticexpialidocious " * 3
    is_valid, msg = validate_resume_text(text_few_words)
    assert not is_valid
    assert f"at least {MIN_RESUME_WORD_COUNT} words" in msg


def test_validate_resume_text_valid():
    valid_resume = (
        "BTech Computer Science graduate with strong foundation in Python, Java, Data Structures, "
        "and SQL. Developed multiple full-stack web applications and REST APIs using Flask and Docker."
    )
    is_valid, msg = validate_resume_text(valid_resume)
    assert is_valid
    assert msg == ""


def test_analyze_route_rejects_empty_and_short_pasted_text():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test-user-id"

        # No input
        res = client.post("/analyze", data={}, follow_redirects=True)
        assert res.status_code == 200
        assert b"Please upload a PDF resume or paste your resume text" in res.data

        # Too short pasted text
        res = client.post("/analyze", data={"resume_text": "Hi"}, follow_redirects=True)
        assert res.status_code == 200
        assert b"too short" in res.data


def test_standardize_resume_sections_identifies_canonical_sections():
    raw_resume = """
    Jane Candidate
    Email: jane@example.com | Phone: 123-456-7890

    Education
    B.Tech Computer Science, University of Technology, 2024. CGPA: 8.8

    Technical Skills
    Python, Java, Flask, SQL, Git, Docker, System Design

    Work Experience
    Software Engineering Intern at TechCorp. Built microservices in Flask.

    Projects
    AI Placement Agent: Built multi-agent resume analysis tool with Python and LLMs.

    Certifications
    AWS Certified Cloud Practitioner, 2023.
    """
    sections = standardize_resume_sections(raw_resume)
    assert "education" in sections
    assert "B.Tech Computer Science" in sections["education"]
    assert "skills" in sections
    assert "Python, Java" in sections["skills"]
    assert "experience" in sections
    assert "TechCorp" in sections["experience"]
    assert "projects" in sections
    assert "AI Placement Agent" in sections["projects"]
    assert "certifications" in sections

    formatted = format_standardized_resume(sections)
    assert "### Education & Qualifications" in formatted
    assert "### Technical Skills & Competencies" in formatted
    assert "### Work Experience & Internships" in formatted
    assert "### Key Projects & Portfolio" in formatted


def test_standardize_resume_sections_unstructured_fallback():
    unstructured_text = (
        "Dedicated software developer with 2 years of hands-on experience in full stack "
        "development, REST APIs, and database modeling without any section headers."
    )
    sections = standardize_resume_sections(unstructured_text)
    assert "summary" in sections
    assert "Dedicated software developer" in sections["summary"]


def test_ocr_fallback_triggered_on_scanned_pdf(monkeypatch, tmp_path):
    # Enable OCR fallback in config
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", True)

    # Create a dummy PDF with zero text (scanned PDF simulation)
    from PyPDF2 import PdfWriter
    pdf_path = tmp_path / "scanned_resume.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    # Mock extract_text_with_ocr_fallback to simulate OCR success
    def mock_ocr(path):
        return (
            "John Doe - Software Engineer. Education: BS in CS from State College. "
            "Skills: Python, C++, Docker, SQL. Experience: Intern at ABC Corp building APIs."
        )

    monkeypatch.setattr("utils.pdf_reader.extract_text_with_ocr_fallback", mock_ocr)

    extracted = extract_text_from_pdf(str(pdf_path))
    assert "John Doe" in extracted
    assert "Python, C++" in extracted


def test_scanned_pdf_empty_extraction_raises_scanned_pdf_error(monkeypatch, tmp_path):
    """Verify that a completely blank or image-only PDF raises ScannedPDFError when OCR is disabled."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)

    from PyPDF2 import PdfWriter
    pdf_path = tmp_path / "empty_scanned_resume.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    with pytest.raises(ScannedPDFError) as exc_info:
        extract_text_from_pdf(str(pdf_path))

    error_message = str(exc_info.value)
    assert "scanned or image-based" in error_message
    assert "upload a text-based PDF" in error_message


def test_scanned_pdf_insufficient_text_raises_scanned_pdf_error(monkeypatch, tmp_path):
    """Verify that a PDF extracting fewer than MIN_PDF_TEXT_CHARS is flagged as scanned/image-based."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    monkeypatch.setattr(config, "MIN_PDF_TEXT_CHARS", 100)

    # Create a PDF with only 18 characters (e.g. page number or watermark)
    pdf_path = tmp_path / "watermark_only.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 750, "Page 1 of 1 Resume")
    c.save()

    with pytest.raises(ScannedPDFError) as exc_info:
        extract_text_from_pdf(str(pdf_path))

    error_message = str(exc_info.value)
    assert "scanned or image-based" in error_message
    assert "upload a text-based PDF" in error_message


def test_scanned_pdf_on_analyze_route_does_not_trigger_ai_call(monkeypatch, tmp_path):
    """Verify that uploading a scanned PDF aborts the workflow and never triggers Gemini API calls."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)

    from agents.coordinator import CoordinatorAgent
    ai_called = False

    def mock_analyze(*args, **kwargs):
        nonlocal ai_called
        ai_called = True
        raise AssertionError("AI CoordinatorAgent.analyze was called on a scanned PDF!")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_analyze)

    # Create blank scanned PDF
    from PyPDF2 import PdfWriter
    pdf_path = tmp_path / "unreadable_scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test-user-id"

        with open(pdf_path, "rb") as f:
            data = {
                "resume": (f, "unreadable_scan.pdf"),
                "company": "Google",
            }
            res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)

        assert res.status_code == 200
        assert not ai_called
        assert b"scanned or image-based" in res.data
        assert b"upload a text-based PDF" in res.data


def test_scanned_pdf_on_api_start_returns_400_and_no_ai_call(monkeypatch, tmp_path):
    """Verify that /api/analysis/start returns 400 Bad Request with a clear error for scanned PDFs."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)

    from PyPDF2 import PdfWriter
    pdf_path = tmp_path / "scanned_api.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)

    app.config["TESTING"] = True
    with app.test_client() as client:
        # Establish test session
        with client.session_transaction() as sess:
            sess["user_id"] = "test-user-id"

        with open(pdf_path, "rb") as f:
            data = {
                "resume": (f, "scanned_api.pdf"),
                "company": "Amazon",
            }
            res = client.post("/api/analysis/start", data=data, content_type="multipart/form-data")

        assert res.status_code == 400
        json_data = res.get_json()
        assert json_data["success"] is False
        assert "scanned or image-based" in json_data["error"]
        assert "upload a text-based PDF" in json_data["error"]


def test_text_based_pdf_is_unaffected(tmp_path):
    """Verify that a standard text-based PDF extracts completely without false positives."""
    pdf_path = tmp_path / "valid_text_resume.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(50, 750, "Jane Doe - Full Stack Software Engineer | B.Tech Computer Science")
    c.drawString(50, 730, "Technical Skills: Python, Java, Docker, Kubernetes, SQL, Data Structures, Algorithms")
    c.drawString(50, 710, "Experience: Software Engineering Intern at Tech Innovations building scalable microservices")
    c.drawString(50, 690, "Education: National Institute of Technology, CGPA 9.2, Computer Science and Engineering")
    c.save()

    extracted = extract_text_from_pdf(str(pdf_path))
    assert len(extracted) >= 100
    assert "Jane Doe" in extracted
    assert "Technical Skills" in extracted
    assert "Python, Java" in extracted


