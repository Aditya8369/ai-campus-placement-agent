import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_job_application,
    get_job_applications,
    delete_job_application
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_app_search.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_job_application_advanced_search_and_filters(tmp_path):
    test_db = tmp_path / "test_filters_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()

        # Seed test applications
        save_job_application(
            app_id="app-01",
            student_id="student_filter_test",
            company_name="Google",
            role_title="Software Engineer",
            status="Interview",
            application_date="2026-03-01",
            location="Bangalore",
            job_type="Full-Time",
            experience_level="Entry-Level"
        )
        save_job_application(
            app_id="app-02",
            student_id="student_filter_test",
            company_name="Microsoft",
            role_title="Backend Intern",
            status="Applied",
            application_date="2026-03-05",
            location="Remote",
            job_type="Internship",
            experience_level="Entry-Level"
        )
        save_job_application(
            app_id="app-03",
            student_id="student_filter_test",
            company_name="Amazon",
            role_title="Cloud Support Associate",
            status="Selected",
            application_date="2026-02-15",
            location="Hyderabad",
            job_type="Full-Time",
            experience_level="Mid-Level"
        )

        # 1. Search keyword
        search_res = get_job_applications("student_filter_test", search_query="Intern")
        assert len(search_res) == 1
        assert search_res[0]["company_name"] == "Microsoft"

        # 2. Location filter
        bengaluru_res = get_job_applications("student_filter_test", location_filter="Bangalore")
        assert len(bengaluru_res) == 1
        assert bengaluru_res[0]["company_name"] == "Google"

        # 3. Job type filter
        internship_res = get_job_applications("student_filter_test", job_type_filter="Internship")
        assert len(internship_res) == 1
        assert internship_res[0]["role_title"] == "Backend Intern"

        # 4. Multi-filter combination (Location + Status)
        combo_res = get_job_applications(
            "student_filter_test",
            location_filter="Bangalore",
            status_filter="Interview"
        )
        assert len(combo_res) == 1
        assert combo_res[0]["company_name"] == "Google"

        # 5. Sorting by company (A-Z)
        sorted_apps = get_job_applications("student_filter_test", sort_by="company")
        assert sorted_apps[0]["company_name"] == "Amazon"
        assert sorted_apps[1]["company_name"] == "Google"
        assert sorted_apps[2]["company_name"] == "Microsoft"

def test_application_search_endpoints(client):
    # Add application via POST
    client.post("/applications", data={
        "student_id": "default_student",
        "company_name": "Adobe",
        "role_title": "Frontend Engineer",
        "status": "Applied",
        "application_date": "2026-03-02",
        "location": "Noida",
        "job_type": "Full-Time",
        "experience_level": "Entry-Level"
    }, follow_redirects=True)

    # Filter via query params in HTML GET
    get_res = client.get("/applications?search=Adobe&location=Noida")
    assert get_res.status_code == 200
    assert b"Adobe" in get_res.data

    # Filter via AJAX API
    api_res = client.get("/applications?search=Adobe", headers={"X-Requested-With": "XMLHttpRequest"})
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert len(data["applications"]) == 1
    assert data["applications"][0]["company_name"] == "Adobe"

    # Search with no match
    no_match = client.get("/applications?search=NonExistentCompany", headers={"X-Requested-With": "XMLHttpRequest"})
    no_match_data = json.loads(no_match.data)
    assert len(no_match_data["applications"]) == 0
