"""
Test suite for Certificate PDF generation and download route.

Verifies:
- ReportLab generation of certificate PDF with candidate name, scores, and metadata
- Route /certificate/<id>/download serving valid PDF file attachment
- Graceful error redirection when analysis ID is missing
"""

import os
import tempfile
from pathlib import Path
import pytest
from utils.database import init_db, save_analysis
from utils.report_generator import generate_certificate_pdf
from app import app
import config


@pytest.fixture
def mock_db_and_records(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "cert_test.db"
        test_reports = Path(tmpdir) / "reports"
        test_reports.mkdir()

        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "REPORT_FOLDER", str(test_reports))
        init_db()

        aid = "test_cert_analysis_123"
        analysis_data = {
            "resume_filename": "Alice_Smith_Resume.pdf",
            "company_name": "Google",
            "created_at": "2026-11-02 10:00:00",
            "results": {
                "resume_analysis": {"ats_score": 88},
                "job_match": {"match_percentage": 92},
            },
        }
        save_analysis(
            analysis_id=aid,
            resume_filename=analysis_data["resume_filename"],
            company_name=analysis_data["company_name"],
            job_description="Software Engineer",
            results_dict=analysis_data["results"],
        )
        yield aid, analysis_data, str(test_reports)


def test_generate_certificate_pdf_creates_valid_file(mock_db_and_records):
    """Verify generate_certificate_pdf compiles a non-empty PDF file."""
    aid, analysis_data, report_dir = mock_db_and_records
    output_pdf = os.path.join(report_dir, f"cert_{aid}.pdf")

    result_path = generate_certificate_pdf(analysis_data, output_pdf)
    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 1000

    # Verify PDF magic number
    with open(result_path, "rb") as f:
        header = f.read(4)
        assert header == b"%PDF"


def test_download_certificate_pdf_endpoint(mock_db_and_records):
    """Verify GET /certificate/<aid>/download returns application/pdf attachment."""
    aid, _, _ = mock_db_and_records
    app.config["TESTING"] = True

    with app.test_client() as client:
        res = client.get(f"/certificate/{aid}/download")
        assert res.status_code == 200
        assert res.mimetype == "application/pdf"
        assert "Placement_Certificate_Google.pdf" in res.headers.get("Content-Disposition", "")
        assert len(res.data) > 1000
        res.close()


def test_download_certificate_pdf_not_found():
    """Verify non-existent analysis id redirects to index with flash error."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/certificate/non_existent_id_404/download", follow_redirects=True)
        assert res.status_code == 200
        assert b"Placement record not found" in res.data
