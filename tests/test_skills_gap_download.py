"""
Unit tests for downloadable skills gap report endpoint and generator (#136).
"""

import os
import tempfile
from app import app
from utils.report_generator import generate_skills_gap_pdf


def test_generate_skills_gap_pdf_with_data():
    """Verify standalone skills gap PDF generation with present skills."""
    mock_data = {
        "analysis_id": "test-analysis-136",
        "company_name": "Google",
        "created_at": "2026-11-04",
        "results": {
            "skill_gap": [
                {
                    "skill": "Kubernetes",
                    "importance": "High",
                    "learning_time": "2 weeks",
                    "priority": "High",
                    "learning_resource": "Official Docs",
                    "project_suggestion": "Deploy cluster",
                },
                {
                    "skill": "GraphQL",
                    "importance": "Medium",
                    "learning_time": "1 week",
                    "priority": "Medium",
                    "learning_resource": "Apollo Tutorial",
                    "project_suggestion": "Build API",
                },
            ]
        },
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "skills_gap.pdf")
        res_path = generate_skills_gap_pdf(mock_data, out_pdf)
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000


def test_generate_skills_gap_pdf_empty_state():
    """Verify graceful PDF rendering when no skills gap is identified."""
    mock_data = {
        "analysis_id": "test-analysis-empty",
        "company_name": "Amazon",
        "created_at": "2026-11-04",
        "results": {
            "skill_gap": []
        },
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_pdf = os.path.join(tmp_dir, "skills_gap_empty.pdf")
        res_path = generate_skills_gap_pdf(mock_data, out_pdf)
        assert os.path.exists(res_path)
        assert os.path.getsize(res_path) > 1000


def test_skills_gap_download_route_not_found():
    """Verify 404/redirect when downloading skills gap for non-existent record."""
    with app.test_client() as client:
        res = client.get("/download/skills-gap/non-existent-id-xyz")
        assert res.status_code == 302
