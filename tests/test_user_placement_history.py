import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    get_user_placement_history
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_history.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_user_placement_history(tmp_path):
    test_db = tmp_path / "test_history_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        
        # Save analysis 1
        id_1 = str(uuid.uuid4())
        save_analysis(
            analysis_id=id_1,
            resume_filename="resume_v1.pdf",
            company_name="Google",
            job_description="Backend Dev",
            results_dict={
                "ats_score": 85,
                "job_match_score": 80,
                "matched_skills": ["Python", "FastAPI"],
                "missing_skills": ["Kubernetes"]
            },
            student_id="student_history_test"
        )

        # Save analysis 2
        id_2 = str(uuid.uuid4())
        save_analysis(
            analysis_id=id_2,
            resume_filename="resume_v2.pdf",
            company_name="Microsoft",
            job_description="Cloud Engineer",
            results_dict={
                "ats_score": 90,
                "job_match_score": 88,
                "matched_skills": ["Azure", "Docker"],
                "missing_skills": ["Terraform"]
            },
            student_id="student_history_test"
        )

        # Retrieve user history
        history = get_user_placement_history("student_history_test")
        assert history["total_analyses"] == 2
        assert history["highest_ats_score"] == 90
        assert history["average_ats_score"] == 87.5
        assert len(history["analyses"]) == 2

        # Test company filter
        google_history = get_user_placement_history("student_history_test", company_filter="Google")
        assert google_history["total_analyses"] == 1
        assert google_history["analyses"][0]["company_name"] == "Google"

        # Test student isolation
        other_history = get_user_placement_history("other_student")
        assert other_history["total_analyses"] == 0

def test_api_user_placement_history_endpoints(client):
    # GET HTML page
    html_res = client.get("/my-reports?student_id=default_student")
    assert html_res.status_code == 200
    assert b"My Placement Analysis History" in html_res.data

    # GET API endpoint
    api_res = client.get("/api/user/analyses?student_id=default_student")
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert "analyses" in data["data"]
    assert "total_analyses" in data["data"]
