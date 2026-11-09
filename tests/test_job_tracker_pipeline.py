import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app, APPLICATION_STAGES
from utils.database import (
    init_db,
    save_job_application,
    get_job_applications,
    get_job_application_by_id,
    update_job_application,
    update_job_application_status,
    get_application_stage_counts,
    delete_job_application
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_tracker_pipeline.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_pipeline_stages_and_counts(tmp_path):
    test_db = tmp_path / "test_stages_counts.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "tracker_user_1"

        # Initially counts are all 0
        initial_counts = get_application_stage_counts(student_id)
        assert initial_counts["Total"] == 0
        assert initial_counts["Applied"] == 0
        assert initial_counts["Assessment"] == 0
        assert initial_counts["Interview"] == 0
        assert initial_counts["Selected"] == 0
        assert initial_counts["Rejected"] == 0

        # Add one application in each stage
        stages_to_test = ["Applied", "Assessment", "Interview", "Selected", "Rejected"]
        created_ids = {}
        for idx, stage in enumerate(stages_to_test):
            app_id = f"app-{stage.lower()}-{idx}"
            created_ids[stage] = app_id
            save_job_application(
                app_id=app_id,
                student_id=student_id,
                company_name=f"Company {stage}",
                role_title=f"Engineer {stage}",
                status=stage,
                application_date="2026-03-01",
                job_url=f"https://careers.com/{stage.lower()}",
                notes=f"Note for {stage}",
                location="Bangalore",
                job_type="Full-Time",
                experience_level="Entry-Level"
            )

        # Verify counts
        counts = get_application_stage_counts(student_id)
        assert counts["Total"] == 5
        assert counts["Applied"] == 1
        assert counts["Assessment"] == 1
        assert counts["Interview"] == 1
        assert counts["Selected"] == 1
        assert counts["Rejected"] == 1

        # Test single application retrieval
        retrieved = get_job_application_by_id(created_ids["Interview"], student_id)
        assert retrieved is not None
        assert retrieved["company_name"] == "Company Interview"
        assert retrieved["status"] == "Interview"

        # Update stage from Interview to Selected
        updated_status = update_job_application_status(created_ids["Interview"], student_id, "Selected")
        assert updated_status is True

        counts_after = get_application_stage_counts(student_id)
        assert counts_after["Total"] == 5
        assert counts_after["Interview"] == 0
        assert counts_after["Selected"] == 2

        # Test full application update
        update_success = update_job_application(
            app_id=created_ids["Applied"],
            student_id=student_id,
            company_name="Company Applied Updated",
            role_title="Lead Architect",
            status="Assessment",
            application_date="2026-03-10",
            job_url="https://newurl.com",
            notes="Updated referral contact",
            location="Remote",
            job_type="Internship",
            experience_level="Mid-Level"
        )
        assert update_success is True
        updated_app = get_job_application_by_id(created_ids["Applied"], student_id)
        assert updated_app["company_name"] == "Company Applied Updated"
        assert updated_app["role_title"] == "Lead Architect"
        assert updated_app["status"] == "Assessment"
        assert updated_app["location"] == "Remote"
        assert updated_app["notes"] == "Updated referral contact"

def test_add_application_endpoints(client):
    # 1. Add application via HTML form POST
    res_form = client.post("/applications", data={
        "student_id": "student_alpha",
        "company_name": "Stripe",
        "role_title": "Backend Systems Engineer",
        "status": "Applied",
        "location": "Remote",
        "job_type": "Full-Time",
        "experience_level": "Mid-Level",
        "application_date": "2026-03-15",
        "job_url": "https://stripe.com/jobs/123",
        "notes": "Referred by alum"
    }, follow_redirects=True)
    assert res_form.status_code == 200
    assert b"Stripe" in res_form.data

    # 2. Add application via JSON API POST
    res_api = client.post("/api/applications", json={
        "student_id": "student_alpha",
        "company_name": "Databricks",
        "role_title": "Data Platform Engineer",
        "status": "Assessment",
        "location": "Bangalore",
        "job_type": "Full-Time",
        "experience_level": "Entry-Level",
        "application_date": "2026-03-16",
        "notes": "Hackerrank link received"
    })
    assert res_api.status_code == 201
    api_data = json.loads(res_api.data)
    assert api_data["success"] is True
    assert api_data["application"]["company_name"] == "Databricks"
    assert api_data["application"]["status"] == "Assessment"
    app_id = api_data["application"]["id"]

    # 3. Validation: missing company or role should fail with 400
    res_bad = client.post("/api/applications", json={
        "student_id": "student_alpha",
        "company_name": "",
        "role_title": "Developer"
    })
    assert res_bad.status_code == 400

def test_update_application_status_and_stats(client):
    # Create application
    res_create = client.post("/api/applications", json={
        "student_id": "student_beta",
        "company_name": "Atlassian",
        "role_title": "Site Reliability Engineer",
        "status": "Applied"
    })
    assert res_create.status_code == 201
    app_id = json.loads(res_create.data)["application"]["id"]

    # Check stats endpoint
    res_stats1 = client.get("/api/applications/stats?student_id=student_beta")
    assert res_stats1.status_code == 200
    stats1 = json.loads(res_stats1.data)["counts"]
    assert stats1["Applied"] == 1
    assert stats1["Interview"] == 0

    # Advance stage to Interview
    res_up1 = client.post(f"/api/applications/{app_id}/status", json={
        "student_id": "student_beta",
        "status": "Interview"
    })
    assert res_up1.status_code == 200
    data_up1 = json.loads(res_up1.data)
    assert data_up1["success"] is True
    assert data_up1["status"] == "Interview"

    # Advance stage to Selected
    res_up2 = client.post(f"/api/applications/{app_id}/status", json={
        "student_id": "student_beta",
        "status": "Selected"
    })
    assert res_up2.status_code == 200

    # Invalid stage should be rejected with 400
    res_invalid = client.post(f"/api/applications/{app_id}/status", json={
        "student_id": "student_beta",
        "status": "NonExistentStage"
    })
    assert res_invalid.status_code == 400
    assert "Invalid stage" in json.loads(res_invalid.data)["error"]

    # Check stats updated
    res_stats2 = client.get("/api/applications/stats?student_id=student_beta")
    stats2 = json.loads(res_stats2.data)["counts"]
    assert stats2["Applied"] == 0
    assert stats2["Selected"] == 1

def test_update_full_application_details_api(client):
    # Create application
    res_create = client.post("/api/applications", json={
        "student_id": "student_gamma",
        "company_name": "Canva",
        "role_title": "Frontend Engineer",
        "status": "Applied",
        "location": "Sydney",
        "job_type": "Full-Time",
        "experience_level": "Entry-Level"
    })
    app_id = json.loads(res_create.data)["application"]["id"]

    # Fetch details via GET
    res_get = client.get(f"/api/applications/{app_id}?student_id=student_gamma")
    assert res_get.status_code == 200
    get_data = json.loads(res_get.data)
    assert get_data["application"]["company_name"] == "Canva"

    # Update full details via POST/PUT
    res_update = client.post(f"/api/applications/{app_id}", json={
        "student_id": "student_gamma",
        "company_name": "Canva Global",
        "role_title": "Senior Frontend Engineer",
        "status": "Interview",
        "location": "Remote",
        "job_type": "Full-Time",
        "experience_level": "Mid-Level",
        "application_date": "2026-03-20",
        "job_url": "https://canva.com/careers/senior-frontend",
        "notes": "Completed initial screening call"
    })
    assert res_update.status_code == 200
    updated_data = json.loads(res_update.data)
    assert updated_data["success"] is True
    assert updated_data["application"]["company_name"] == "Canva Global"
    assert updated_data["application"]["role_title"] == "Senior Frontend Engineer"
    assert updated_data["application"]["status"] == "Interview"
    assert updated_data["application"]["notes"] == "Completed initial screening call"

def test_candidate_data_isolation(client):
    # Candidate 1 adds application
    res1 = client.post("/api/applications", json={
        "student_id": "candidate_1",
        "company_name": "SecretCorp",
        "role_title": "Security Analyst",
        "status": "Applied"
    })
    app_id_1 = json.loads(res1.data)["application"]["id"]

    # Candidate 2 cannot access Candidate 1's application
    res_unauth_get = client.get(f"/api/applications/{app_id_1}?student_id=candidate_2")
    assert res_unauth_get.status_code == 404

    # Candidate 2 cannot update Candidate 1's application
    res_unauth_put = client.post(f"/api/applications/{app_id_1}", json={
        "student_id": "candidate_2",
        "company_name": "HackedCorp",
        "role_title": "Hacker"
    })
    assert res_unauth_put.status_code == 404

    # Candidate 2 cannot update status
    res_unauth_status = client.post(f"/api/applications/{app_id_1}/status", json={
        "student_id": "candidate_2",
        "status": "Selected"
    })
    assert res_unauth_status.status_code == 404

def test_html_view_rendering(client):
    # Seed an application
    client.post("/applications", data={
        "student_id": "student_ui",
        "company_name": "Acme Innovations",
        "role_title": "AI Researcher",
        "status": "Interview",
        "location": "Bangalore",
        "job_type": "Full-Time",
        "experience_level": "Entry-Level",
        "application_date": "2026-03-05",
        "job_url": "https://acme.org/jobs/ai",
        "notes": "Stage 2 tech round scheduled"
    }, follow_redirects=True)

    # View page
    html_res = client.get("/applications?student_id=student_ui")
    assert html_res.status_code == 200
    html = html_res.data.decode("utf-8")

    # Verify structured elements
    assert "Job Application Tracker" in html
    assert "Acme Innovations" in html
    assert "AI Researcher" in html
    assert "stat-total" in html
    assert "stat-applied" in html
    assert "stat-assessment" in html
    assert "stat-interview" in html
    assert "stat-selected" in html
    assert "stat-rejected" in html
    assert "tableViewContainer" in html
    assert "kanbanViewContainer" in html
    assert "kanban-column-Applied" in html
    assert "kanban-column-Interview" in html
    assert "viewAppModal" in html
    assert "editAppModal" in html
    assert "newApplicationModal" in html
