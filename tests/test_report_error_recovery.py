import pytest
import os
import json
import uuid
from unittest.mock import patch, MagicMock
import config
from app import app
from utils.database import init_db, save_analysis
from utils.report_generator import (
    sanitize_report_data,
    generate_fallback_pdf_report,
    safe_generate_report_with_recovery,
    generate_pdf_report,
    generate_certificate_pdf,
    ReportGenerationError
)


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_report_recovery.db"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "DATABASE_PATH", str(test_db)), \
         patch.object(config, "REPORT_FOLDER", str(report_dir)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_sanitize_report_data_corrupt_and_missing_inputs():
    # 1. Test None input
    data_none = sanitize_report_data(None)
    assert isinstance(data_none, dict)
    assert data_none["company_name"] == "General Placement Preparation"
    assert data_none["ats_score"] == 0
    assert data_none["match_percentage"] == 0

    # 2. Test invalid string types for numbers and non-dict nested structures
    corrupt_input = {
        "company_name": "Acme Corp",
        "ats_score": "not-a-number",
        "match_percentage": None,
        "results": "corrupt_string_not_dict"
    }
    sanitized = sanitize_report_data(corrupt_input)
    assert sanitized["company_name"] == "Acme Corp"
    assert sanitized["ats_score"] == 0
    assert sanitized["match_percentage"] == 0
    assert isinstance(sanitized["results"], dict)
    assert isinstance(sanitized["results"]["skill_gap"], list)

    # 3. Test valid data preservation
    valid_input = {
        "company_name": "Google",
        "ats_score": 85,
        "match_percentage": 90,
        "results": {
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 90, "matched_skills": ["Python"]}
        }
    }
    cleaned = sanitize_report_data(valid_input)
    assert cleaned["company_name"] == "Google"
    assert cleaned["ats_score"] == 85
    assert cleaned["match_percentage"] == 90
    assert cleaned["results"]["job_match"]["matched_skills"] == ["Python"]


def test_generate_fallback_pdf_report(tmp_path):
    fallback_path = str(tmp_path / "fallback_report.pdf")
    err_msg = "Table formatting exception due to unescaped XML token <invalid>"

    result_path = generate_fallback_pdf_report(
        error_message=err_msg,
        output_path=fallback_path,
        report_type="Placement Readiness Comprehensive Report"
    )

    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 1000

    # Verify PDF starts with standard valid PDF header
    with open(result_path, "rb") as f:
        header = f.read(5)
        assert header == b"%PDF-"


def test_safe_generate_report_with_recovery_trigger(tmp_path):
    output_path = str(tmp_path / "recovered_output.pdf")

    # Mock generator that fails intentionally
    def buggy_generator(data, path):
        raise ValueError("Simulated PDF compilation error in table layout")

    recovered = safe_generate_report_with_recovery(
        generator_func=buggy_generator,
        data={"company_name": "TestCorp"},
        output_path=output_path,
        report_type="Placement Test Report"
    )

    assert os.path.exists(recovered)
    assert os.path.getsize(recovered) > 1000


def test_download_routes_safe_error_recovery(client, tmp_path):
    aid = f"analysis-{uuid.uuid4().hex[:10]}"
    # Save a record with missing and corrupt nested data
    save_analysis(
        analysis_id=aid,
        resume_filename="corrupt_resume.pdf",
        company_name="Alpha Tech",
        job_description="Sample job description",
        results_dict={"corrupted_field": True},
        student_id="default_student"
    )

    # 1. Download comprehensive report (should succeed via sanitization & safe recovery)
    res_report = client.get(f"/download/{aid}")
    assert res_report.status_code == 200
    assert "application/pdf" in res_report.headers["Content-Type"]
    assert len(res_report.data) > 1000

    # 2. Download certificate (should also succeed without crashing)
    res_cert = client.get(f"/certificate/{aid}/download")
    assert res_cert.status_code == 200
    assert "application/pdf" in res_cert.headers["Content-Type"]
    assert len(res_cert.data) > 1000

    # 3. Download skills gap report (should also succeed without crashing)
    res_gap = client.get(f"/download/skills-gap/{aid}")
    assert res_gap.status_code == 200
    assert "application/pdf" in res_gap.headers["Content-Type"]
    assert len(res_gap.data) > 1000


def test_emergency_minimal_pdf_on_catastrophic_failure(tmp_path):
    output_path = str(tmp_path / "emergency_minimal.pdf")

    # Mock SimpleDocTemplate to throw an error inside fallback generation
    with patch("utils.report_generator.SimpleDocTemplate", side_effect=RuntimeError("ReportLab engine damaged")):
        result = generate_fallback_pdf_report(
            error_message="Catastrophic engine crash",
            output_path=output_path,
            report_type="Placement Emergency Report"
        )
        assert os.path.exists(result)
        with open(result, "rb") as f:
            content = f.read()
            assert content.startswith(b"%PDF-1.4")
            assert b"%%EOF" in content

