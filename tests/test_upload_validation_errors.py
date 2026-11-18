"""
Comprehensive test suite for resume upload validation and friendly error handling (#493).

Covers:
- Acceptance of supported formats (PDF and DOCX) only, rejecting unsupported extensions and fake headers.
- File size limit enforcement (rejecting oversized uploads > 5MB and empty 0-byte uploads).
- Detection of files with no extractable text (scanned images / image-only documents in both PDF and DOCX).
- Distinct, helpful error messages for each failure case.
- Assurance that the app never crashes with unhandled 500 errors or blank analyses on bad files.
- Cleanup of temporary files on all error and failure paths.
"""

import io
import os
import pytest
from PyPDF2 import PdfWriter
from docx import Document
from reportlab.pdfgen import canvas

import config
from app import app
from utils.pdf_reader import (
    validate_resume_file,
    validate_file_size,
    validate_pdf_content,
    validate_docx_content,
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_file,
    ScannedPDFError,
    ALLOWED_RESUME_EXTENSIONS,
)


@pytest.fixture
def client():
    """Flask test client with an authenticated session."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as test_client:
        with test_client.session_transaction() as sess:
            sess["user_id"] = "test-student-493"
            sess["privacy_consent"] = True
        yield test_client


@pytest.fixture
def valid_pdf_bytes():
    """Generates an in-memory valid text-based PDF resume."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Jane Doe - Placement Candidate")
    c.drawString(100, 730, "Email: jane.doe@example.com | Phone: +1 555-0199")
    c.drawString(100, 700, "Education: B.Tech Computer Science, National Institute of Technology")
    c.drawString(100, 680, "Technical Skills: Python, Flask, Docker, Kubernetes, SQL, Data Structures")
    c.drawString(100, 650, "Experience: Software Engineering Intern at Tech Corp building REST APIs")
    c.drawString(100, 620, "Projects: Placement Preparation Agent using multi-agent LLM coordination")
    c.save()
    buf.seek(0)
    return buf


@pytest.fixture
def valid_docx_bytes():
    """Generates an in-memory valid text-based DOCX resume."""
    doc = Document()
    doc.add_heading("Jane Doe - Software Engineer Resume", level=1)
    doc.add_paragraph("Email: jane.doe@example.com | Phone: +1 555-0199 | Location: San Francisco, CA")
    doc.add_heading("Education", level=2)
    doc.add_paragraph("B.Tech in Computer Science and Engineering from National Institute of Technology.")
    doc.add_heading("Technical Skills", level=2)
    doc.add_paragraph("Python, Flask, Django, PostgreSQL, Docker, Git, REST APIs, System Design.")
    doc.add_heading("Experience", level=2)
    doc.add_paragraph("Software Engineering Intern: Architected microservices and automated deployment pipelines.")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


@pytest.fixture
def scanned_empty_pdf_bytes():
    """Generates a valid PDF structure containing 1 completely blank page (0 extractable text)."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


@pytest.fixture
def scanned_watermark_pdf_bytes():
    """Generates a PDF containing only 15 characters (e.g. a scanned resume with a tiny watermark)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Page 1 Resume")
    c.save()
    buf.seek(0)
    return buf


@pytest.fixture
def empty_docx_bytes():
    """Generates a valid DOCX document structure with zero paragraphs or text blocks."""
    doc = Document()
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


# =========================================================================
# 1. Supported Format & Wrong Type Tests
# =========================================================================

def test_allowed_resume_extensions_set():
    """Verify that only PDF and DOCX extensions are accepted."""
    assert ALLOWED_RESUME_EXTENSIONS == {".pdf", ".docx"}


@pytest.mark.parametrize("invalid_name", [
    "resume.png",
    "resume.jpg",
    "resume.jpeg",
    "resume.txt",
    "script.exe",
    "archive.zip",
    "legacy.doc",
    "code.py",
    "resume",
])
def test_validate_resume_file_rejects_unsupported_extensions(invalid_name):
    """Verify that any non-pdf and non-docx extension is rejected with an unsupported message."""
    content = b"Some dummy content for testing"
    is_valid, err_msg = validate_resume_file(content, filename=invalid_name)
    assert not is_valid
    assert "Unsupported file format" in err_msg
    assert "Only PDF (.pdf) and Word (.docx) resumes are supported" in err_msg


def test_validate_resume_file_detects_fake_pdf_signature():
    """Verify that a non-PDF file disguised as .pdf is rejected by magic byte checking."""
    fake_pdf = b"Plain text disguised as a PDF document"
    is_valid, err_msg = validate_resume_file(fake_pdf, filename="resume.pdf")
    assert not is_valid
    assert "not a valid PDF document" in err_msg


def test_validate_resume_file_detects_fake_docx_signature():
    """Verify that a non-DOCX file disguised as .docx is rejected by magic byte checking."""
    fake_docx = b"Plain text disguised as a Word docx"
    is_valid, err_msg = validate_resume_file(fake_docx, filename="resume.docx")
    assert not is_valid
    assert "not a valid Word document" in err_msg


# =========================================================================
# 2. Oversized & Empty File Tests
# =========================================================================

def test_validate_file_size_rejects_oversized_file():
    """Verify that files exceeding MAX_UPLOAD_SIZE_MB (default 5 MB) are rejected."""
    max_mb = getattr(config, "MAX_UPLOAD_SIZE_MB", 5)
    huge_data = b"X" * ((max_mb * 1024 * 1024) + 1024)  # 5MB + 1KB
    is_valid, err_msg = validate_file_size(huge_data)
    assert not is_valid
    assert f"exceeds the maximum allowed size of {max_mb} MB" in err_msg


def test_validate_file_size_rejects_zero_byte_empty_file():
    """Verify that a 0-byte empty file is rejected with a specific empty message."""
    empty_data = b""
    is_valid, err_msg = validate_file_size(empty_data)
    assert not is_valid
    assert "The uploaded file is empty" in err_msg


# =========================================================================
# 3. Empty-Text and Scanned Image Detection Tests
# =========================================================================

def test_scanned_pdf_zero_text_explains_scanned_images_not_supported(monkeypatch, tmp_path, scanned_empty_pdf_bytes):
    """Verify that a PDF with no extractable text raises ScannedPDFError stating scanned images are not supported."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    test_pdf = tmp_path / "scanned_resume.pdf"
    test_pdf.write_bytes(scanned_empty_pdf_bytes.getvalue())

    with pytest.raises(ScannedPDFError) as exc_info:
        extract_text_from_pdf(str(test_pdf))

    err_msg = str(exc_info.value)
    assert "scanned or image-based" in err_msg
    assert "Scanned images are not supported" in err_msg
    assert "upload a text-based PDF" in err_msg


def test_scanned_pdf_watermark_insufficient_text_explains_scanned_images(monkeypatch, tmp_path, scanned_watermark_pdf_bytes):
    """Verify that a PDF with fewer characters than threshold explains scanned images are not supported."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    monkeypatch.setattr(config, "MIN_PDF_TEXT_CHARS", 100)
    test_pdf = tmp_path / "watermark_only.pdf"
    test_pdf.write_bytes(scanned_watermark_pdf_bytes.getvalue())

    with pytest.raises(ScannedPDFError) as exc_info:
        extract_text_from_pdf(str(test_pdf))

    err_msg = str(exc_info.value)
    assert "scanned or image-based" in err_msg
    assert "Scanned images are not supported" in err_msg


def test_empty_text_docx_explains_scanned_images_not_supported(tmp_path, empty_docx_bytes):
    """Verify that a DOCX with no extractable text raises ValueError explaining scanned images are not supported."""
    test_docx = tmp_path / "empty_doc.docx"
    test_docx.write_bytes(empty_docx_bytes.getvalue())

    with pytest.raises(ValueError) as exc_info:
        extract_text_from_docx(str(test_docx))

    err_msg = str(exc_info.value)
    assert "Could not extract sufficient text from DOCX document" in err_msg
    assert "Scanned images and image-only documents are not supported" in err_msg


# =========================================================================
# 4. End-to-End Route Validation Tests (App Never Crashes)
# =========================================================================

def test_analyze_route_rejects_unsupported_file_and_never_crashes(client):
    """Verify that uploading an unsupported format (.png) to /analyze flashes error and redirects without crashing."""
    png_data = io.BytesIO(b"\x89PNG\r\n\x1a\nFake PNG resume image")
    data = {
        "resume": (png_data, "resume.png"),
        "company": "Google",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Unsupported file format" in html
    assert "Only PDF (.pdf) and Word (.docx) resumes are supported" in html


def test_analyze_route_rejects_oversized_file_and_never_crashes(client):
    """Verify that uploading an oversized file to /analyze flashes error and redirects without crashing."""
    huge_buf = io.BytesIO(b"%PDF-" + b"0" * (6 * 1024 * 1024))  # 6 MB fake PDF
    data = {
        "resume": (huge_buf, "huge_resume.pdf"),
        "company": "Amazon",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "exceeds the maximum allowed size of 5 MB" in html


def test_analyze_route_rejects_empty_file_and_never_crashes(client):
    """Verify that uploading a 0-byte file to /analyze flashes error and redirects without crashing."""
    empty_buf = io.BytesIO(b"")
    data = {
        "resume": (empty_buf, "empty.pdf"),
        "company": "Microsoft",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "The uploaded file is empty" in html


def test_analyze_route_rejects_scanned_pdf_and_never_crashes(client, scanned_empty_pdf_bytes, monkeypatch):
    """Verify that uploading a scanned PDF to /analyze flashes error explaining scanned images and does not call AI."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    data = {
        "resume": (scanned_empty_pdf_bytes, "scanned_resume.pdf"),
        "company": "General",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "scanned or image-based" in html
    assert "Scanned images are not supported" in html


def test_analyze_route_rejects_empty_docx_and_never_crashes(client, empty_docx_bytes):
    """Verify that uploading an empty-text DOCX to /analyze flashes error explaining scanned images are not supported."""
    data = {
        "resume": (empty_docx_bytes, "empty_scan.docx"),
        "company": "General",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Scanned images and image-only documents are not supported" in html


def test_analyze_route_rejects_corrupted_pdf_and_never_crashes(client):
    """Verify that uploading a corrupt PDF document gives a friendly error and never crashes."""
    corrupt_buf = io.BytesIO(b"%PDF-1.4\nCorrupted garbage header << >> trailer")
    data = {
        "resume": (corrupt_buf, "corrupt.pdf"),
        "company": "General",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert any(term in html for term in ("corrupted or unreadable", "Unable to read PDF file", "Could not process uploaded file"))


def test_async_analyze_api_returns_400_on_unsupported_file_type(client):
    """Verify that the async analysis API returns 400 Bad Request with distinct error JSON on unsupported format."""
    bad_file = io.BytesIO(b"executable binary dummy")
    data = {
        "resume": (bad_file, "resume.exe"),
        "company": "Google",
    }
    res = client.post("/api/analysis/start", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    json_data = res.get_json()
    assert json_data["success"] is False
    assert "Unsupported file format" in json_data["error"]


def test_async_analyze_api_returns_400_on_oversized_file(client):
    """Verify that the async analysis API returns 400 Bad Request or 413 Payload Too Large on oversized files."""
    huge_buf = io.BytesIO(b"%PDF-" + b"0" * (6 * 1024 * 1024))
    data = {
        "resume": (huge_buf, "huge.pdf"),
        "company": "Google",
    }
    res = client.post("/api/analysis/start", data=data, content_type="multipart/form-data")
    assert res.status_code in (400, 413)
    json_data = res.get_json()
    assert json_data["success"] is False
    assert "exceeds the maximum allowed size of 5 MB" in json_data["error"]


def test_async_analyze_api_returns_400_on_scanned_pdf(client, scanned_empty_pdf_bytes, monkeypatch):
    """Verify that the async analysis API returns 400 Bad Request on scanned PDFs explaining scanned images are not supported."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    data = {
        "resume": (scanned_empty_pdf_bytes, "scanned.pdf"),
        "company": "Google",
    }
    res = client.post("/api/analysis/start", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    json_data = res.get_json()
    assert json_data["success"] is False
    assert "scanned or image-based" in json_data["error"]
    assert "Scanned images are not supported" in json_data["error"]


def test_api_parse_preview_returns_400_on_bad_file(client):
    """Verify that /api/resume/parse-preview returns 400 on invalid uploads."""
    data = {
        "resume": (io.BytesIO(b"image data"), "picture.jpg"),
        "company": "Google",
    }
    res = client.post("/api/resume/parse-preview", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    json_data = res.get_json()
    assert json_data["success"] is False
    assert "Unsupported file format" in json_data["error"]


def test_compare_resumes_rejects_unsupported_file_gracefully(client):
    """Verify that /compare-resumes returns 400 on invalid files and never throws a 500 server error."""
    data = {
        "resume_v1": (io.BytesIO(b"text file content"), "resume_v1.txt"),
        "text_v2": "Jane Doe - Python Software Engineer with B.Tech degree and Flask experience.",
    }
    res = client.post("/compare-resumes", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Unsupported file format" in html


def test_missing_both_file_and_text_shows_friendly_message(client):
    """Verify that submitting an empty form without selecting a file or entering text shows a helpful prompt."""
    data = {
        "company": "Google",
    }
    res = client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Please upload a PDF resume or paste your resume text" in html


def test_temporary_upload_files_cleaned_up_on_failure(client, scanned_empty_pdf_bytes, monkeypatch):
    """Verify that whenever a file upload fails validation or parsing, no orphaned file is left in uploads/."""
    monkeypatch.setattr(config, "ENABLE_OCR_FALLBACK", False)
    upload_dir = config.UPLOAD_FOLDER

    before_files = set(os.listdir(upload_dir)) if os.path.exists(upload_dir) else set()

    data = {
        "resume": (scanned_empty_pdf_bytes, "transient_scan.pdf"),
        "company": "Google",
    }
    client.post("/analyze", data=data, content_type="multipart/form-data", follow_redirects=True)

    after_files = set(os.listdir(upload_dir)) if os.path.exists(upload_dir) else set()
    # The temporary uploaded resume must have been removed
    assert after_files == before_files
