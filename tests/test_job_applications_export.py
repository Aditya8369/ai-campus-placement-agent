import pytest
import io
import csv
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_job_application,
    get_job_applications,
    export_job_applications_csv,
    export_job_applications_json,
    delete_job_application
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_export_apps.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "test_student_exporter"
                sess["user_name"] = "Exporter Student"
            yield client


def test_database_export_applications_csv_and_json(tmp_path):
    test_db = tmp_path / "test_db_export.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "student_export_001"

        # 1. Test empty export
        empty_csv = export_job_applications_csv(student_id)
        reader = csv.reader(io.StringIO(empty_csv))
        rows = list(reader)
        assert len(rows) == 1  # Only header row
        assert rows[0][0] == "Application ID"
        assert rows[0][1] == "Company Name"

        empty_json = export_job_applications_json(student_id)
        assert empty_json["total_applications"] == 0
        assert empty_json["applications"] == []

        # 2. Add sample applications
        app1_id = f"app-{uuid.uuid4().hex[:8]}"
        save_job_application(
            app_id=app1_id,
            student_id=student_id,
            company_name="Google",
            role_title="Software Engineer Intern",
            status="Interview",
            application_date="2026-03-10",
            job_url="https://careers.google.com/jobs/101",
            job_description="Backend distributed systems",
            notes="Completed Round 1 Coding assessment."
        )

        app2_id = f"app-{uuid.uuid4().hex[:8]}"
        save_job_application(
            app_id=app2_id,
            student_id=student_id,
            company_name="Amazon",
            role_title="SDE-1",
            status="Applied",
            application_date="2026-03-12",
            job_url="https://amazon.jobs/202",
            job_description="AWS Cloud operations",
            notes="Submitted resume online"
        )

        # 3. Test non-empty CSV export
        full_csv = export_job_applications_csv(student_id)
        reader = csv.reader(io.StringIO(full_csv))
        rows = list(reader)
        assert len(rows) == 3  # Header + 2 rows
        companies = [r[1] for r in rows[1:]]
        assert "Google" in companies
        assert "Amazon" in companies

        # 4. Test status-filtered CSV export
        interview_csv = export_job_applications_csv(student_id, status_filter="Interview")
        int_rows = list(csv.reader(io.StringIO(interview_csv)))
        assert len(int_rows) == 2  # Header + Google
        assert int_rows[1][1] == "Google"
        assert int_rows[1][3] == "Interview"

        # 5. Test JSON export payload
        json_data = export_job_applications_json(student_id)
        assert json_data["total_applications"] == 2
        assert json_data["status_distribution"].get("Interview") == 1
        assert json_data["status_distribution"].get("Applied") == 1

        # 6. Test student isolation
        other_csv = export_job_applications_csv("student_other_party")
        other_rows = list(csv.reader(io.StringIO(other_csv)))
        assert len(other_rows) == 1  # Only header


def test_export_endpoints_http(client, tmp_path):
    student_id = "test_student_exporter"

    # Insert test application
    save_job_application(
        app_id="app-http-export-01",
        student_id=student_id,
        company_name="Microsoft",
        role_title="Research Intern",
        status="Assessment",
        application_date="2026-03-15",
        job_url="https://careers.microsoft.com",
        job_description="AI Models",
        notes="Scheduled online test"
    )

    # 1. Download as CSV
    res_csv = client.get(f"/applications/export?student_id={student_id}&format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["Content-Type"]
    assert "attachment;" in res_csv.headers["Content-Disposition"]
    assert b"Microsoft" in res_csv.data
    assert b"Research Intern" in res_csv.data

    # 2. Download as JSON
    res_json = client.get(f"/applications/export?student_id={student_id}&format=json")
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers["Content-Type"]
    payload = res_json.get_json()
    assert payload["total_applications"] == 1
    assert payload["applications"][0]["company_name"] == "Microsoft"

    # 3. Test API alias route
    res_api = client.get(f"/api/applications/export?student_id={student_id}&format=csv")
    assert res_api.status_code == 200
    assert b"Microsoft" in res_api.data

    # 4. Download as Markdown
    res_md = client.get(f"/applications/export?student_id={student_id}&format=md")
    assert res_md.status_code == 200
    assert "text/markdown" in res_md.headers["Content-Type"]
    assert b"# Job Applications Report" in res_md.data
    assert b"Microsoft" in res_md.data

    # 5. Export summary API
    res_sum = client.get(f"/api/applications/export-summary?student_id={student_id}")
    assert res_sum.status_code == 200
    sum_data = res_sum.get_json()
    assert sum_data["status"] == "success"
    assert sum_data["export_metadata"]["total_records"] == 1
    assert sum_data["export_metadata"]["unique_companies_count"] == 1

