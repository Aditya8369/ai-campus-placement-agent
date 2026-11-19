import pytest
from unittest.mock import patch

import config
from app import app
from utils.database import init_db, save_analysis


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _seed(analysis_id, owner):
    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume_sample.pdf",
        company_name="Acme",
        job_description="Software Engineer Python",
        results_dict={"resume_analysis": {"ats_score": 70}, "job_match": {}, "skill_gap": []},
        student_id=owner,
    )


def test_version_and_reproducibility_reads_are_owner_only(client, tmp_path):
    with patch.object(config, "DATABASE_PATH", str(tmp_path / "isolation.db")):
        init_db()
        analysis_id = "iso-analysis-1"
        _seed(analysis_id, "owner_student")

        _login(client, "owner_student")
        assert client.post("/api/analysis/version-metadata", json={
            "analysis_id": analysis_id,
            "model_name": "Gemini",
            "model_version": "v1",
            "prompt_version": "p1",
        }).status_code == 201
        assert client.post("/api/analysis/reproducibility-summary", json={
            "analysis_id": analysis_id,
            "resume_text": "Candidate details",
            "target_role": "Backend",
        }).status_code == 201

        app.config["ENFORCE_STUDENT_ISOLATION"] = True
        try:
            # the owner can still read both
            assert client.get(f"/api/analysis/version-metadata?analysis_id={analysis_id}").status_code == 200
            assert client.get(f"/api/analysis/reproducibility-summary?analysis_id={analysis_id}").status_code == 200

            # another logged in student gets the same not found answer as for an unknown id
            _login(client, "someone_else")
            assert client.get(f"/api/analysis/version-metadata?analysis_id={analysis_id}").status_code == 404
            assert client.get(f"/api/analysis/reproducibility-summary?analysis_id={analysis_id}").status_code == 404
        finally:
            app.config["ENFORCE_STUDENT_ISOLATION"] = False
