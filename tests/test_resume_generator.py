"""
Automated Test Suite for ATS Resume Template Gallery & In-Memory Exporters (#561).

Acceptance Criteria:
1. Each template produces a valid DOCX and PDF that extract as clean text.
2. Missing optional sections are skipped without blank gaps.
3. Special characters render correctly (&, <, >, quotes, dashes, bullets, C++, C#).
4. Tests extract text from generated files and compare it with the input data.
5. Web endpoints support previewing, section filtering, and streaming downloads without disk storage.
"""

import io
import pytest
import docx
from PyPDF2 import PdfReader

from utils.resume_generator import (
    generate_resume_docx,
    generate_resume_pdf,
    generate_resume_preview_html,
    get_available_templates,
)
from app import app, save_resume_review_cache


@pytest.fixture
def sample_candidate_data():
    """Rich test candidate profile containing special characters and structured sections."""
    return {
        "candidate_name": "Alex Chen & Jane O'Connor <Tech Lead>",
        "email": "alex.chen@campus.edu",
        "phone": "+1 (555) 234-5678",
        "location": "San Francisco, CA",
        "linkedin": "linkedin.com/in/alexchen",
        "github": "github.com/alexchen",
        "portfolio": "alexchen.dev",
        "summary": "Full-stack engineer proficient in C++ & C#; builds distributed systems with throughput > 1,000 req/s & latency < 5ms.",
        "education": [
            {
                "degree": "B.S. in Computer Science",
                "institution": "University of California, Berkeley",
                "year": "2021 – 2025",
                "cgpa": "3.85 / 4.0",
                "highlights": "Dean's Honors List, Algorithms & Operating Systems."
            }
        ],
        "skills": [
            "Python", "C++", "C#", "React", "Flask", "PostgreSQL", "Docker", "HTML & CSS"
        ],
        "experience": [
            {
                "role": "Software Engineering Intern",
                "company": "CloudScale Systems & Co.",
                "duration": "Jun 2024 – Aug 2024",
                "responsibilities": (
                    "Architected low-latency caching (throughput > 500 req/s).\n"
                    "Refactored legacy REST APIs; improved efficiency by 25%."
                )
            }
        ],
        "projects": [
            {
                "title": "AI Placement Agent & Evaluator",
                "technologies": "Python, Flask, Google GenAI",
                "description": (
                    "Engineered automated resume parser with 98% accuracy.\n"
                    "Built full-text ATS scoring engine with zero third-party dependencies."
                )
            }
        ],
        "certifications": [
            "AWS Certified Solutions Architect – Associate (2024)",
            "CKAD – Certified Kubernetes Application Developer"
        ]
    }


class TestTemplateRegistry:
    """Verifies that all 3 single-column templates are registered with proper metadata."""

    def test_available_templates_count_and_keys(self):
        templates = get_available_templates()
        assert len(templates) == 3
        template_ids = {t["id"] for t in templates}
        assert template_ids == {"classic", "compact", "project-focused"}

        for t in templates:
            assert t["name"]
            assert t["description"]
            assert t["font_family_docx"]
            assert t["font_family_pdf"]
            assert t["margin_inches"] > 0


class TestValidDocxGenerationAndExtraction:
    """Acceptance Criterion 1 & 4: Each template produces valid DOCX extracting clean text."""

    @pytest.mark.parametrize("template_name", ["classic", "compact", "project-focused"])
    def test_docx_produces_valid_document_matching_input_data(self, sample_candidate_data, template_name):
        docx_bytes = generate_resume_docx(sample_candidate_data, template=template_name)
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 2000

        # Load back into python-docx to verify document structure integrity
        doc = docx.Document(io.BytesIO(docx_bytes))
        extracted_text = "\n".join(p.text for p in doc.paragraphs if p.text)

        # Verify candidate contact info
        assert "Alex Chen & Jane O'Connor <Tech Lead>" in extracted_text
        assert "alex.chen@campus.edu" in extracted_text
        assert "+1 (555) 234-5678" in extracted_text

        # Verify sections extracted
        assert "PROFESSIONAL SUMMARY" in extracted_text.upper()
        assert "C++ & C#" in extracted_text
        assert "University of California, Berkeley" in extracted_text
        assert "B.S. in Computer Science" in extracted_text
        assert "CloudScale Systems & Co." in extracted_text
        assert "AI Placement Agent & Evaluator" in extracted_text
        assert "HTML & CSS" in extracted_text

        # Ensure single-column: verify no tables exist in document
        assert len(doc.tables) == 0


class TestValidPdfGenerationAndExtraction:
    """Acceptance Criterion 1 & 4: Each template produces valid PDF extracting clean text."""

    @pytest.mark.parametrize("template_name", ["classic", "compact", "project-focused"])
    def test_pdf_produces_valid_document_matching_input_data(self, sample_candidate_data, template_name):
        pdf_bytes = generate_resume_pdf(sample_candidate_data, template=template_name)
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 2000

        # Load back into PyPDF2 to verify PDF format and text flow
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 1
        pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)

        # Verify candidate details in PDF stream
        assert "Alex Chen & Jane O'Connor" in pdf_text
        assert "alex.chen@campus.edu" in pdf_text
        assert "University of California, Berkeley" in pdf_text
        assert "CloudScale Systems" in pdf_text
        assert "AI Placement Agent" in pdf_text


class TestSkippingMissingOptionalSections:
    """Acceptance Criterion 2: Missing optional sections are skipped without blank gaps."""

    def test_missing_experience_and_summary_omits_headings(self, sample_candidate_data):
        # Exclude summary and experience
        selected_sections = ["education", "skills", "projects"]

        docx_bytes = generate_resume_docx(sample_candidate_data, sections=selected_sections)
        doc = docx.Document(io.BytesIO(docx_bytes))
        docx_text = "\n".join(p.text for p in doc.paragraphs if p.text)

        assert "EDUCATION" in docx_text.upper()
        assert "TECHNICAL SKILLS" in docx_text.upper()
        assert "PROJECTS" in docx_text.upper()
        assert "WORK EXPERIENCE" not in docx_text.upper()
        assert "PROFESSIONAL SUMMARY" not in docx_text.upper()

        # Same test for PDF
        pdf_bytes = generate_resume_pdf(sample_candidate_data, sections=selected_sections)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)

        assert "EDUCATION" in pdf_text.upper()
        assert "WORK EXPERIENCE" not in pdf_text.upper()
        assert "PROFESSIONAL SUMMARY" not in pdf_text.upper()

    def test_empty_optional_fields_skipped_gracefully(self):
        sparse_candidate = {
            "candidate_name": "Minimalist Student",
            "email": "student@college.edu",
            "education": [{"degree": "B.Sc Physics", "institution": "City College"}],
            "skills": ["Python", "MATLAB"],
            # Summary, experience, projects, certifications omitted
        }

        docx_bytes = generate_resume_docx(sparse_candidate)
        doc = docx.Document(io.BytesIO(docx_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text)

        assert "Minimalist Student" in text
        assert "B.Sc Physics" in text
        assert "WORK EXPERIENCE" not in text.upper()
        assert "PROJECTS" not in text.upper()
        assert "CERTIFICATIONS" not in text.upper()


class TestSpecialCharactersRendering:
    """Acceptance Criterion 3: Special characters render correctly without escaping errors."""

    def test_special_characters_render_in_docx_and_pdf(self):
        special_data = {
            "candidate_name": "Rene Descartes & Francois O'Neill",
            "email": "rene+test@sorbonne.fr",
            "summary": "Special characters test: C++ & C# <OOP / Design Patterns> \"Smart Quotes\" -- em—dash – en-dash • bullet",
            "skills": ["C++", "C#", "HTML & CSS", "JSON & XML", "Bash / sh"],
            "projects": [
                {
                    "title": "Query Optimizer <v2.0>",
                    "technologies": "C++20, SQL & Redis",
                    "description": "Throughput > 10,000 req/sec; latency < 1.5ms; cost reduced by 50% & reliability improved."
                }
            ]
        }

        # Verify PDF does not raise SAXParseException and extracts clean text
        pdf_bytes = generate_resume_pdf(special_data, template="classic")
        assert len(pdf_bytes) > 1000
        reader = PdfReader(io.BytesIO(pdf_bytes))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

        assert "Rene Descartes & Francois O'Neill" in extracted
        assert "C++ & C#" in extracted
        assert "Query Optimizer" in extracted

        # Verify DOCX
        docx_bytes = generate_resume_docx(special_data, template="compact")
        doc = docx.Document(io.BytesIO(docx_bytes))
        docx_text = "\n".join(p.text for p in doc.paragraphs if p.text)

        assert "Rene Descartes & Francois O'Neill" in docx_text
        assert "C++ & C#" in docx_text
        assert "HTML & CSS" in docx_text


class TestHtmlPreviewGenerator:
    """Verifies live in-browser preview generation."""

    def test_preview_html_structure(self, sample_candidate_data):
        html_content = generate_resume_preview_html(sample_candidate_data, template="project-focused")
        assert isinstance(html_content, str)
        assert "Alex Chen" in html_content
        assert "Professional Summary" in html_content
        assert "Technical Skills" in html_content
        assert "Projects &amp; Technical Work" in html_content or "Projects & Technical Work" in html_content
        assert "resume-preview-sheet" in html_content


class TestWebRoutesAndDownloads:
    """Acceptance Criterion 5: Endpoints for gallery, dynamic preview, and streaming downloads."""

    def test_gallery_page_renders_cleanly(self):
        with app.test_client() as client:
            resp = client.get("/resume/templates")
            assert resp.status_code == 200
            html_text = resp.get_data(as_text=True)
            assert "ATS-Friendly Resume Template Gallery" in html_text
            assert "Classic Academic / Corporate" in html_text
            assert "Compact 1-Page Modern" in html_text
            assert "Project-Focused Tech" in html_text

    def test_gallery_page_with_cached_uuid(self, sample_candidate_data):
        test_uuid = "test-uuid-review-999"
        save_resume_review_cache(test_uuid, sample_candidate_data)

        with app.test_client() as client:
            resp = client.get(f"/resume/templates/{test_uuid}")
            assert resp.status_code == 200
            html_text = resp.get_data(as_text=True)
            assert "Alex Chen" in html_text

    def test_api_resume_preview_endpoint(self):
        with app.test_client() as client:
            resp = client.post("/api/resume/preview", json={
                "template": "compact",
                "sections": ["education", "skills"]
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert "Education" in data["html"]
            assert "Work Experience" not in data["html"]

    def test_resume_download_docx_attachment(self, sample_candidate_data):
        test_uuid = "download-uuid-docx-111"
        save_resume_review_cache(test_uuid, sample_candidate_data)

        with app.test_client() as client:
            resp = client.post("/resume/download", data={
                "file_uuid": test_uuid,
                "format": "docx",
                "template": "classic",
                "sections": ["education", "skills", "projects"]
            })
            assert resp.status_code == 200
            assert resp.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disposition = resp.headers.get("Content-Disposition", "")
            assert "attachment;" in disposition
            assert ".docx" in disposition

            # Verify downloaded payload is valid DOCX
            doc = docx.Document(io.BytesIO(resp.data))
            assert len(doc.paragraphs) > 5

    def test_resume_download_pdf_attachment(self, sample_candidate_data):
        test_uuid = "download-uuid-pdf-222"
        save_resume_review_cache(test_uuid, sample_candidate_data)

        with app.test_client() as client:
            resp = client.post("/resume/download", data={
                "file_uuid": test_uuid,
                "format": "pdf",
                "template": "project-focused",
                "sections": ["skills", "projects"]
            })
            assert resp.status_code == 200
            assert resp.mimetype == "application/pdf"
            disposition = resp.headers.get("Content-Disposition", "")
            assert "attachment;" in disposition
            assert ".pdf" in disposition

            # Verify downloaded payload is valid PDF
            reader = PdfReader(io.BytesIO(resp.data))
            assert len(reader.pages) >= 1
