import pytest
import json
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    record_viewed_job,
    get_recently_viewed_jobs,
    remove_recently_viewed_job,
    clear_recently_viewed_jobs
)


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_viewed_jobs.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_database_recently_viewed_jobs_crud(tmp_path):
    test_db = tmp_path / "test_db_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_a = "student_viewed_001"
        student_b = "student_viewed_002"

        # 1. Record viewed jobs for student A
        j1 = record_viewed_job(
            student_id=student_a,
            job_id="job-101",
            company_name="Google",
            role_title="Software Engineering Intern",
            location="Mountain View, CA",
            salary_range="$45-55/hr",
            apply_url="https://careers.google.com/jobs/101"
        )
        assert j1["company_name"] == "Google"
        assert j1["role_title"] == "Software Engineering Intern"

        j2 = record_viewed_job(
            student_id=student_a,
            job_id="job-102",
            company_name="Microsoft",
            role_title="Data Science Intern",
            location="Redmond, WA",
            salary_range="$42-50/hr",
            apply_url="https://careers.microsoft.com/jobs/102"
        )
        assert j2["company_name"] == "Microsoft"

        # 2. Record viewed job for student B (isolation check)
        j_b = record_viewed_job(
            student_id=student_b,
            job_id="job-201",
            company_name="Amazon",
            role_title="Cloud Support Associate",
            location="Seattle, WA"
        )
        assert j_b["student_id"] == student_b

        # 3. Retrieve student A viewed jobs
        history_a = get_recently_viewed_jobs(student_id=student_a)
        assert len(history_a) == 2
        # Most recently viewed job should come first
        assert history_a[0]["job_id"] == "job-102"
        assert history_a[1]["job_id"] == "job-101"

        # 4. Verify student B does not see student A's jobs
        history_b = get_recently_viewed_jobs(student_id=student_b)
        assert len(history_b) == 1
        assert history_b[0]["job_id"] == "job-201"

        # 5. Re-visiting job-101 updates timestamp and bumps to top
        record_viewed_job(
            student_id=student_a,
            job_id="job-101",
            company_name="Google",
            role_title="Senior Software Engineering Intern",
            location="Remote"
        )
        history_a_bumped = get_recently_viewed_jobs(student_id=student_a)
        assert len(history_a_bumped) == 2
        assert history_a_bumped[0]["job_id"] == "job-101"
        assert history_a_bumped[0]["role_title"] == "Senior Software Engineering Intern"

        # 6. Remove single job
        removed = remove_recently_viewed_job(student_id=student_a, job_id="job-102")
        assert removed is True
        history_after_remove = get_recently_viewed_jobs(student_id=student_a)
        assert len(history_after_remove) == 1
        assert history_after_remove[0]["job_id"] == "job-101"

        # 7. Clear all for student A
        cleared_count = clear_recently_viewed_jobs(student_id=student_a)
        assert cleared_count == 1
        assert len(get_recently_viewed_jobs(student_id=student_a)) == 0
        # Student B's jobs remain untouched
        assert len(get_recently_viewed_jobs(student_id=student_b)) == 1


def test_recently_viewed_jobs_endpoints(client):
    # 1. GET initially empty
    res = client.get("/api/jobs/viewed?student_id=endpoint_student")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "success"
    assert data["total"] == 0
    assert data["jobs"] == []

    # 2. POST invalid payload (missing company or role)
    bad_post = client.post("/api/jobs/viewed?student_id=endpoint_student", json={
        "job_id": "job-bad"
    })
    assert bad_post.status_code == 400

    # 3. POST valid view
    post_res = client.post("/api/jobs/viewed?student_id=endpoint_student", json={
        "job_id": "job-netflix-1",
        "company_name": "Netflix",
        "role_title": "Core Systems Engineer",
        "location": "Los Gatos, CA",
        "salary_range": "$120,000",
        "apply_url": "https://jobs.netflix.com/jobs/1"
    })
    assert post_res.status_code == 201
    post_data = json.loads(post_res.data)
    assert post_data["status"] == "success"
    assert post_data["viewed_job"]["company_name"] == "Netflix"

    # 4. GET now shows recorded job
    get_res = client.get("/api/jobs/viewed?student_id=endpoint_student")
    assert get_res.status_code == 200
    get_data = json.loads(get_res.data)
    assert get_data["total"] == 1
    assert get_data["jobs"][0]["job_id"] == "job-netflix-1"

    # 5. Internships HTML page renders recently viewed section
    page_res = client.get("/internships?student_id=endpoint_student")
    assert page_res.status_code == 200
    assert b"Recently Viewed Jobs" in page_res.data
    assert b"Netflix" in page_res.data

    # 6. DELETE single job
    del_res = client.delete("/api/jobs/viewed?student_id=endpoint_student", json={
        "job_id": "job-netflix-1"
    })
    assert del_res.status_code == 200

    # 7. DELETE clear all
    clear_res = client.delete("/api/jobs/viewed?student_id=endpoint_student", json={})
    assert clear_res.status_code == 200
    clear_data = json.loads(clear_res.data)
    assert clear_data["status"] == "success"
