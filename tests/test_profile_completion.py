import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_student_profile,
    get_student_profile,
    calculate_profile_completion
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_profile.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "test_profile_user"
                sess["user_name"] = "Profile Student"
            yield client


def test_database_profile_and_completion_calculation(tmp_path):
    test_db = tmp_path / "test_db_profile.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "student_calc_001"

        # 1. Check initial state for unprofiled user
        comp0 = calculate_profile_completion(student_id)
        assert comp0["completion_percentage"] == 0
        assert comp0["is_complete"] is False
        assert len(comp0["missing_fields"]) > 0

        # 2. Add basic info and academics
        save_student_profile(
            student_id=student_id,
            full_name="Samantha Ray",
            email="samantha@college.edu",
            phone="+91 9123456780",
            department="Computer Science",
            grad_year=2026,
            cgpa=9.1
        )
        comp1 = calculate_profile_completion(student_id)
        assert comp1["completion_percentage"] >= 45  # 15+5+15+10 = 45%

        # 3. Add career targets and skills
        save_student_profile(
            student_id=student_id,
            target_role="Backend Engineer",
            target_company="Google",
            skills=["Python", "SQL", "Docker", "Flask"]
        )
        comp2 = calculate_profile_completion(student_id)
        assert comp2["completion_percentage"] >= 80  # 45 + 20 + 15 = 80%

        # 4. Add portfolio & social links to reach 100%
        save_student_profile(
            student_id=student_id,
            linkedin_url="https://linkedin.com/in/samanthar",
            github_url="https://github.com/samanthar",
            has_resume_uploaded=True
        )
        comp3 = calculate_profile_completion(student_id)
        assert comp3["completion_percentage"] == 100
        assert comp3["is_complete"] is True
        assert len(comp3["missing_fields"]) == 0


def test_profile_endpoints_http(client, tmp_path):
    # 1. GET profile page
    res_page = client.get("/profile")
    assert res_page.status_code == 200
    assert b"Profile Completion & Readiness" in res_page.data

    # 2. POST update profile form
    res_post = client.post(
        "/profile",
        data={
            "full_name": "Devin Kumar",
            "email": "devin@univ.edu",
            "phone": "+91 9888877777",
            "department": "Information Technology",
            "grad_year": "2026",
            "cgpa": "8.8",
            "target_role": "Cloud Architect",
            "target_company": "Microsoft",
            "skills": "Go, Docker, Kubernetes, AWS",
            "linkedin_url": "https://linkedin.com/in/devin",
            "github_url": "https://github.com/devin"
        },
        follow_redirects=True
    )
    assert res_post.status_code == 200
    assert b"Devin Kumar" in res_post.data
    assert b"Cloud Architect" in res_post.data

    # 3. Test API completion endpoint
    res_api = client.get("/api/profile/completion")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data["status"] == "success"
    assert data["data"]["completion_percentage"] >= 75
    assert data["data"]["profile"]["full_name"] == "Devin Kumar"
