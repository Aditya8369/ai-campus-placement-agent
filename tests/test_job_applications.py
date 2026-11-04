import pytest
import json
import os
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_job_application,
    get_job_applications,
    update_job_application_status,
    delete_job_application
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_applications.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_database_application_crud(tmp_path):
    test_db = tmp_path / "test_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app_id = str(uuid.uuid4())
        
        # Test creation
        save_job_application(
            app_id=app_id,
            student_id="student_123",
            company_name="Google",
            role_title="Software Engineer Intern",
            status="Applied",
            application_date="2026-03-01",
            job_url="https://careers.google.com/jobs/123",
            job_description="Backend microservices",
            notes="Submitted referral link"
        )
        
        # Test retrieval
        apps = get_job_applications("student_123")
        assert len(apps) == 1
        assert apps[0]["company_name"] == "Google"
        assert apps[0]["role_title"] == "Software Engineer Intern"
        assert apps[0]["status"] == "Applied"
        
        # Test update stage
        updated = update_job_application_status(app_id, "student_123", "Interview")
        assert updated is True
        
        apps_after_update = get_job_applications("student_123")
        assert apps_after_update[0]["status"] == "Interview"
        
        # Test status filter
        interview_apps = get_job_applications("student_123", status_filter="Interview")
        assert len(interview_apps) == 1
        rejected_apps = get_job_applications("student_123", status_filter="Rejected")
        assert len(rejected_apps) == 0
        
        # Test student data isolation
        other_apps = get_job_applications("student_other")
        assert len(other_apps) == 0

        # Test deletion
        deleted = delete_job_application(app_id, "student_123")
        assert deleted is True
        assert len(get_job_applications("student_123")) == 0

def test_api_application_endpoints(client):
    # Add application via POST
    response = client.post("/applications", data={
        "company_name": "Microsoft",
        "role_title": "SDE-1",
        "status": "Applied",
        "application_date": "2026-03-02",
        "job_url": "https://careers.microsoft.com",
        "notes": "Passed online assessment"
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Microsoft" in response.data

    # Fetch applications JSON via /applications with header
    api_res = client.get("/applications", headers={"X-Requested-With": "XMLHttpRequest"})
    assert api_res.status_code == 200
    data = json.loads(api_res.data)
    assert data["success"] is True
    assert len(data["applications"]) == 1
    app_id = data["applications"][0]["id"]
    assert data["applications"][0]["company_name"] == "Microsoft"

    # Update status via API
    status_res = client.post(f"/api/applications/{app_id}/status", json={
        "status": "Selected"
    })
    assert status_res.status_code == 200
    status_data = json.loads(status_res.data)
    assert status_data["success"] is True

    # Check updated status
    verify_res = client.get("/applications?status=Selected", headers={"X-Requested-With": "XMLHttpRequest"})
    verify_data = json.loads(verify_res.data)
    assert len(verify_data["applications"]) == 1
    assert verify_data["applications"][0]["status"] == "Selected"

    # Delete application via API
    del_res = client.delete(f"/api/applications/{app_id}")
    assert del_res.status_code == 200
    del_data = json.loads(del_res.data)
    assert del_data["success"] is True

    # Verify empty
    empty_res = client.get("/applications", headers={"X-Requested-With": "XMLHttpRequest"})
    empty_data = json.loads(empty_res.data)
    assert len(empty_data["applications"]) == 0
