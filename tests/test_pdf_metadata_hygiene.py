import io
import os
import pytest
from PyPDF2 import PdfWriter, PdfReader
from utils.pdf_metadata_service import (
    read_pdf_metadata,
    analyze_pdf_metadata_hygiene,
    strip_pdf_metadata,
    generate_suggested_filename,
    get_or_compute_pdf_metadata_hygiene,
)


def _create_sample_pdf(metadata=None) -> bytes:
    """Helper to create a PDF in-memory with optional metadata dict."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if metadata:
        writer.add_metadata(metadata)
    else:
        try:
            if hasattr(writer, "_info") and writer._info:
                info_obj = writer._info.get_object() if hasattr(writer._info, "get_object") else writer._info
                if hasattr(info_obj, "clear"):
                    info_obj.clear()
        except Exception:
            pass
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfMetadataService:
    def test_pdf_without_metadata_shows_no_warnings(self):
        """Files without metadata show no warnings when filename is clean."""
        clean_pdf_bytes = _create_sample_pdf()
        meta = read_pdf_metadata(clean_pdf_bytes)
        assert meta["author"] is None
        assert meta["title"] is None
        assert meta["creator"] is None
        assert meta["producer"] is None

        result = analyze_pdf_metadata_hygiene(
            meta,
            filename="John_Doe_Developer.pdf",
            candidate_name="John Doe",
            target_role="Developer"
        )
        assert result["has_warnings"] is False
        assert len(result["warnings"]) == 0
        assert result["is_clean"] is True
        assert result["clean_filename_pattern"] == "FirstName_LastName_Role.pdf"

    def test_pdf_with_template_author_and_title_flags_warnings(self):
        """PDF with template author and draft title triggers actionable warnings."""
        pdf_bytes = _create_sample_pdf({
            "/Author": "Canva Template Designer",
            "/Title": "Untitled Resume Draft v2",
            "/Creator": "Canva"
        })
        meta = read_pdf_metadata(pdf_bytes)
        assert meta["author"] == "Canva Template Designer"
        assert meta["title"] == "Untitled Resume Draft v2"
        assert meta["creator"] == "Canva"

        result = analyze_pdf_metadata_hygiene(
            meta,
            filename="resume_final_v3_new.pdf",
            candidate_name="Alex Smith",
            target_role="Software Engineer"
        )
        assert result["has_warnings"] is True
        warnings = result["warnings"]
        fields = [w["field"] for w in warnings]
        assert "author" in fields
        assert "title" in fields
        assert "creator" in fields
        assert "filename" in fields
        assert result["is_clean"] is False
        assert result["suggested_filename"] == "Alex_Smith_Software_Engineer.pdf"

    def test_pdf_with_author_mismatch_flags_warning(self):
        """PDF author metadata exposing another person's name flags author mismatch."""
        pdf_bytes = _create_sample_pdf({
            "/Author": "Jane Doe",
            "/Title": "Engineering Resume"
        })
        meta = read_pdf_metadata(pdf_bytes)
        result = analyze_pdf_metadata_hygiene(
            meta,
            filename="Jane_Doe_Resume.pdf",
            candidate_name="Robert Johnson",
            target_role="Backend Engineer"
        )
        assert result["has_warnings"] is True
        author_warning = [w for w in result["warnings"] if w["field"] == "author"][0]
        assert author_warning["type"] == "author_mismatch"
        assert "Robert Johnson" in author_warning["message"]
        assert "Jane Doe" in author_warning["message"]

    def test_strip_pdf_metadata_removes_all_metadata(self):
        """Cleaned copy contains no author, title, creator or producer metadata."""
        dirty_pdf_bytes = _create_sample_pdf({
            "/Author": "External Author",
            "/Title": "Old Title",
            "/Creator": "Microsoft Word",
            "/Producer": "macOS Quartz"
        })
        cleaned_stream = strip_pdf_metadata(dirty_pdf_bytes)
        cleaned_bytes = cleaned_stream.getvalue()

        cleaned_meta = read_pdf_metadata(cleaned_bytes)
        assert cleaned_meta["author"] is None
        assert cleaned_meta["title"] is None
        assert cleaned_meta["creator"] is None
        assert cleaned_meta["producer"] is None

        # Verify through PyPDF2 reader directly as well
        reader = PdfReader(io.BytesIO(cleaned_bytes))
        if reader.metadata:
            assert getattr(reader.metadata, "author", None) is None
            assert getattr(reader.metadata, "title", None) is None

    def test_filename_hygiene_checks(self):
        """Generic and versioned filenames are detected and clean patterns suggested."""
        res_generic = analyze_pdf_metadata_hygiene({}, filename="resume.pdf")
        assert res_generic["has_warnings"] is True
        assert any(w["type"] == "filename_generic" for w in res_generic["warnings"])

        res_versioned = analyze_pdf_metadata_hygiene({}, filename="my_cv_v2_final.pdf")
        assert res_versioned["has_warnings"] is True
        assert any(w["type"] == "filename_versioning" for w in res_versioned["warnings"])

        clean_suggested = generate_suggested_filename("Jane Doe", "Fullstack Developer")
        assert clean_suggested == "Jane_Doe_Fullstack_Developer.pdf"


class TestPdfMetadataRoutes:
    def test_download_clean_resume_unauthorized(self, client):
        """Anonymous or unauthorized user cannot download clean resume."""
        resp = client.get("/api/analysis/nonexistent-uuid/download-clean-resume")
        assert resp.status_code in (404, 302)

    def test_download_clean_resume_authorized(self, client, monkeypatch):
        """Authorized student downloads clean PDF copy with no author or title."""
        student_id = "test_student_hygiene_841"
        analysis_id = "test-analysis-hygiene-841"

        dirty_pdf = _create_sample_pdf({
            "/Author": "Original Template Author",
            "/Title": "Template Resume v1"
        })

        mock_analysis = {
            "id": analysis_id,
            "student_id": student_id,
            "resume_filename": "resume_final_v3.pdf",
            "company_name": "Acme Corp",
            "target_role": "Backend Developer",
            "results": {
                "candidate_info": {"name": "Alice Wonder"},
                "pdf_metadata_hygiene": analyze_pdf_metadata_hygiene(
                    read_pdf_metadata(dirty_pdf),
                    filename="resume_final_v3.pdf",
                    candidate_name="Alice Wonder",
                    target_role="Backend Developer"
                )
            }
        }

        # Mock database getters and student authorization
        from routes import analysis as analysis_module
        monkeypatch.setattr(analysis_module, "get_analysis", lambda aid: mock_analysis if aid == analysis_id else None)
        monkeypatch.setattr(analysis_module, "_is_student_authorized", lambda rec: True)

        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        # Also place the file in config.UPLOAD_FOLDER if needed
        import config
        from werkzeug.utils import secure_filename
        os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
        file_path = os.path.join(config.UPLOAD_FOLDER, secure_filename(f"{analysis_id}_resume_final_v3.pdf"))
        with open(file_path, "wb") as f:
            f.write(dirty_pdf)

        try:
            resp = client.get(f"/api/analysis/{analysis_id}/download-clean-resume")
            assert resp.status_code == 200
            assert resp.mimetype == "application/pdf"
            assert "attachment" in resp.headers.get("Content-Disposition", "")
            assert "Alice_Wonder_Backend_Developer.pdf" in resp.headers.get("Content-Disposition", "")

            # Verify downloaded PDF has stripped metadata
            downloaded_bytes = resp.data
            meta = read_pdf_metadata(downloaded_bytes)
            assert meta["author"] is None
            assert meta["title"] is None
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    def test_dashboard_renders_hygiene_card_when_warnings_present(self, client, monkeypatch):
        """Dashboard displays the PDF Metadata Hygiene card when warnings exist."""
        student_id = "test_student_hygiene_841"
        analysis_id = "test-dashboard-hygiene-841"

        dirty_pdf = _create_sample_pdf({
            "/Author": "Canva User",
            "/Title": "Draft Resume"
        })
        hygiene_data = analyze_pdf_metadata_hygiene(
            read_pdf_metadata(dirty_pdf),
            filename="resume_final_v2.pdf",
            candidate_name="Alice Wonder"
        )

        mock_record = {
            "id": analysis_id,
            "student_id": student_id,
            "resume_filename": "resume_final_v2.pdf",
            "company_name": "Google",
            "job_description": "Software engineer role",
            "results": {
                "resume_analysis": {"ats_score": 85, "strengths": ["Python"], "weaknesses": []},
                "job_match": {"match_percentage": 80, "matched_skills": ["Python"], "missing_skills": []},
                "pdf_metadata_hygiene": hygiene_data,
            }
        }

        from routes import analysis as analysis_module
        monkeypatch.setattr(analysis_module, "get_analysis", lambda aid: mock_record if aid == analysis_id else None)
        monkeypatch.setattr(analysis_module, "_is_student_authorized", lambda rec: True)
        monkeypatch.setattr(analysis_module, "get_student_versions", lambda sid: [mock_record])

        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        resp = client.get(f"/dashboard/{analysis_id}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "pdfMetadataHygieneCard" in html
        assert "PDF Metadata &amp; Filename Hygiene" in html or "PDF Metadata & Filename Hygiene" in html
        assert "btnDownloadCleanResume" in html
        assert "Download Clean Copy" in html

    def test_dashboard_hides_hygiene_card_when_clean(self, client, monkeypatch):
        """Dashboard does NOT display the PDF Metadata Hygiene card when clean."""
        student_id = "test_student_hygiene_841"
        analysis_id = "test-dashboard-clean-841"

        clean_pdf = _create_sample_pdf()
        clean_hygiene = analyze_pdf_metadata_hygiene(
            read_pdf_metadata(clean_pdf),
            filename="Alice_Wonder_Developer.pdf",
            candidate_name="Alice Wonder"
        )
        assert clean_hygiene["has_warnings"] is False

        mock_record = {
            "id": analysis_id,
            "student_id": student_id,
            "resume_filename": "Alice_Wonder_Developer.pdf",
            "company_name": "Google",
            "job_description": "Software engineer role",
            "results": {
                "resume_analysis": {"ats_score": 85, "strengths": ["Python"], "weaknesses": []},
                "job_match": {"match_percentage": 80, "matched_skills": ["Python"], "missing_skills": []},
                "pdf_metadata_hygiene": clean_hygiene,
            }
        }

        from routes import analysis as analysis_module
        monkeypatch.setattr(analysis_module, "get_analysis", lambda aid: mock_record if aid == analysis_id else None)
        monkeypatch.setattr(analysis_module, "_is_student_authorized", lambda rec: True)
        monkeypatch.setattr(analysis_module, "get_student_versions", lambda sid: [mock_record])

        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        resp = client.get(f"/dashboard/{analysis_id}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "id=\"pdfMetadataHygieneCard\"" not in html
        assert "btnDownloadCleanResume" not in html
