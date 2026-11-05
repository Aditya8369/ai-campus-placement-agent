import io
import os
import pytest
from reportlab.pdfgen import canvas
import config
import os
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-12345")
import pytest
import config
from reportlab.pdfgen import canvas

from utils.pdf_reader import (
    validate_resume_text,
    validate_pdf_content,
    validate_docx_content,
    validate_file_size,
    validate_resume_file,
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
    extract_text_from_file,
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


def test_validate_pdf_content_genuine_and_fake():
    """Verify that validate_pdf_content accurately identifies real vs fake PDF byte streams."""
    # Genuine PDF starts with %PDF-
    genuine_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    is_valid, msg = validate_pdf_content(genuine_pdf)
    assert is_valid is True
    assert msg == ""

    # Renamed plain text
    fake_text_pdf = b"This is just a plain text document renamed to resume.pdf"
    is_valid, msg = validate_pdf_content(fake_text_pdf)
    assert is_valid is False
    assert "not a valid PDF document" in msg

    # Renamed PNG image
    fake_png_pdf = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
    is_valid, msg = validate_pdf_content(fake_png_pdf)
    assert is_valid is False
    assert "not a valid PDF document" in msg

    # Renamed Windows Executable
    fake_exe_pdf = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
    is_valid, msg = validate_pdf_content(fake_exe_pdf)
    assert is_valid is False
    assert "not a valid PDF document" in msg


def test_validate_file_size_empty_and_oversized():
    """Verify file size validation for empty, normal, and oversized files."""
    # Empty file (0 bytes)
    is_valid, msg = validate_file_size(b"")
    assert is_valid is False
    assert "empty" in msg

    # Normal 50 KB content
    normal_content = b"%PDF-" + b"0" * (50 * 1024)
    is_valid, msg = validate_file_size(normal_content, max_bytes=5 * 1024 * 1024)
    assert is_valid is True
    assert msg == ""

    # Oversized content (6 MB with 5 MB limit)
    oversized_content = b"%PDF-" + b"0" * (6 * 1024 * 1024)
    is_valid, msg = validate_file_size(oversized_content, max_bytes=5 * 1024 * 1024)
    assert is_valid is False
    assert "exceeds the maximum allowed size of 5 MB" in msg


def test_validate_resume_file_comprehensive(tmp_path):
    """Verify validate_resume_file combines extension, size, and content signature checks."""
    # 1. Non-allowed extension
    txt_file = tmp_path / "resume.txt"
    txt_file.write_bytes(b"Software Engineer resume details")
    is_valid, msg = validate_resume_file(str(txt_file), filename="resume.txt")
    assert is_valid is False
    assert "Unsupported file format" in msg

    # 2. Renamed fake PDF file
    fake_pdf = tmp_path / "fake_resume.pdf"
    fake_pdf.write_bytes(b"This is not a real PDF file despite the extension")
    is_valid, msg = validate_resume_file(str(fake_pdf), filename="fake_resume.pdf")
    assert is_valid is False
    assert "not a valid PDF document" in msg

    # 3. Oversized PDF file
    oversized_pdf = tmp_path / "huge_resume.pdf"
    oversized_pdf.write_bytes(b"%PDF-" + b"x" * (6 * 1024 * 1024))
    is_valid, msg = validate_resume_file(str(oversized_pdf), filename="huge_resume.pdf", max_bytes=5 * 1024 * 1024)
    assert is_valid is False
    assert "exceeds the maximum allowed size" in msg

    # 4. Valid PDF file
    valid_pdf = tmp_path / "valid.pdf"
    c = canvas.Canvas(str(valid_pdf))
    c.drawString(100, 750, "Jane Doe - Full Stack Developer")
    c.save()
    is_valid, msg = validate_resume_file(str(valid_pdf), filename="valid.pdf")
    assert is_valid is True
    assert msg == ""


def test_extract_text_from_pdf_rejects_fake_and_oversized_files(tmp_path):
    """Verify extract_text_from_pdf halts early on fake PDF signatures and oversized files."""
    # Fake PDF
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"Plain text masquerading as a PDF")
    with pytest.raises(ValueError) as excinfo:
        extract_text_from_pdf(str(fake_pdf))
    assert "not a valid PDF document" in str(excinfo.value)

    # Oversized PDF (mock 1 MB limit)
    oversized_pdf = tmp_path / "oversized.pdf"
    oversized_pdf.write_bytes(b"%PDF-1.4\n" + b"A" * (2 * 1024 * 1024))
    try:
        old_bytes = config.MAX_RESUME_FILE_SIZE_BYTES
        old_mb = config.MAX_UPLOAD_SIZE_MB
        config.MAX_RESUME_FILE_SIZE_BYTES = 1 * 1024 * 1024
        config.MAX_UPLOAD_SIZE_MB = 1

        with pytest.raises(ValueError) as excinfo:
            extract_text_from_pdf(str(oversized_pdf))
        assert "exceeds the maximum allowed size" in str(excinfo.value)
    finally:
        config.MAX_RESUME_FILE_SIZE_BYTES = old_bytes
        config.MAX_UPLOAD_SIZE_MB = old_mb


def test_extract_text_from_pdf_corrupted_file_handling(tmp_path):
    """Verify corrupted PDF files yield a clear user-friendly error instead of an internal crash."""
    corrupt_pdf = tmp_path / "corrupted.pdf"
    # Starts with %PDF- but followed by broken garbage bytes
    corrupt_pdf.write_bytes(b"%PDF-1.4\n\x00\x01\x02\xff\xfe\xfd<<corrupted stream without closing tags")
    with pytest.raises(ValueError) as excinfo:
        extract_text_from_pdf(str(corrupt_pdf))
    assert "corrupted or unreadable" in str(excinfo.value).lower()


def test_config_custom_size_limit_enforced(monkeypatch, tmp_path):
    """Verify upload validation dynamically respects config.py size limits."""
    test_pdf = tmp_path / "test_2mb.pdf"
    test_pdf.write_bytes(b"%PDF-1.4\n" + b"B" * (2 * 1024 * 1024))

    # Configure limit to 1 MB -> should reject
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 1 * 1024 * 1024)
    is_valid, msg = validate_file_size(str(test_pdf))
    assert is_valid is False
    assert "exceeds the maximum allowed size of 1 MB" in msg

    # Configure limit to 10 MB -> should accept
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 10)
    monkeypatch.setattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 10 * 1024 * 1024)
    is_valid, msg = validate_file_size(str(test_pdf))
    assert is_valid is True
    assert msg == ""


def test_analyze_route_rejects_renamed_fake_pdf():
    """Verify POST /analyze rejects a renamed non-PDF file with a readable flash message."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        fake_content = io.BytesIO(b"This is a text file renamed to resume.pdf")
        data = {
            "resume": (fake_content, "fake_resume.pdf"),
            "company": "General",
        }
        res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert res.status_code == 200
        assert b"not a valid PDF document" in res.data


def test_analyze_route_rejects_oversized_pdf(monkeypatch):
    """Verify POST /analyze rejects files exceeding configured size limit with a readable error."""
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 1 * 1024 * 1024)

    app.config["TESTING"] = True
    with app.test_client() as client:
        # 2 MB PDF
        oversized_content = io.BytesIO(b"%PDF-1.4\n" + b"X" * (2 * 1024 * 1024))
        data = {
            "resume": (oversized_content, "oversized_resume.pdf"),
            "company": "General",
        }
        res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert res.status_code == 200
        assert b"exceeds the maximum allowed size of 1 MB" in res.data


def test_api_analysis_start_rejects_fake_and_oversized_files(monkeypatch):
    """Verify POST /api/analysis/start returns 400 Bad Request with actionable JSON errors."""
    monkeypatch.setattr(config, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(config, "MAX_RESUME_FILE_SIZE_BYTES", 1 * 1024 * 1024)

    app.config["TESTING"] = True
    with app.test_client() as client:
        # Fake PDF
        fake_stream = io.BytesIO(b"Not a genuine PDF header")
        res_fake = client.post(
            "/api/analysis/start",
            data={"resume": (fake_stream, "not_real.pdf"), "company": "Google"},
            content_type="multipart/form-data"
        )
        assert res_fake.status_code == 400
        json_fake = res_fake.get_json()
        assert json_fake["success"] is False
        assert "not a valid PDF document" in json_fake["error"]

        # Oversized PDF (2 MB)
        big_stream = io.BytesIO(b"%PDF-1.4\n" + b"Y" * (2 * 1024 * 1024))
        res_big = client.post(
            "/api/analysis/start",
            data={"resume": (big_stream, "huge.pdf"), "company": "Google"},
            content_type="multipart/form-data"
        )
        assert res_big.status_code == 400
        json_big = res_big.get_json()
        assert json_big["success"] is False
        assert "exceeds the maximum allowed size of 1 MB" in json_big["error"]


def test_valid_pdf_continues_to_work_unchanged(tmp_path):
    """Verify that genuine valid PDFs extract cleanly and completely without regressions."""
    valid_pdf_path = tmp_path / "valid_resume.pdf"
    c = canvas.Canvas(str(valid_pdf_path))
    c.drawString(50, 750, "Jane Doe - Full Stack Developer | B.Tech Computer Science")
    c.drawString(50, 730, "Technical Skills: Python, Flask, Docker, Kubernetes, SQL, Data Structures")
    c.drawString(50, 710, "Experience: Software Engineering Intern at Tech Innovations building APIs")
    c.drawString(50, 690, "Education: National Institute of Technology, CGPA 9.2, CSE")
    c.save()

    extracted = extract_text_from_pdf(str(valid_pdf_path))
    assert len(extracted) >= 100
    assert "Jane Doe" in extracted
    assert "Technical Skills" in extracted
    assert "Python, Flask" in extracted
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


