import io
import pytest
from utils.resume_library_service import (
    ResumeLibraryService,
    ResumeLimitExceededError,
    ResumeNotFoundError,
    ResumeAccessDeniedError,
    MAX_STORED_RESUMES_PER_USER
)


@pytest.fixture
def service():
    srv = ResumeLibraryService()
    srv._ensure_table()
    return srv


class TestResumeLibraryService:
    def test_create_and_list_resumes(self, service):
        """User can store named resumes and list them."""
        student_id = "test_student_lib_1"
        res1 = service.create_resume(
            student_id=student_id,
            label="Backend SDE Resume",
            role_focus="Software Engineer - Backend",
            extracted_text="Python, FastAPI, Docker, PostgreSQL, Redis",
            resume_filename="sde_backend.pdf"
        )
        assert res1["id"] is not None
        assert res1["label"] == "Backend SDE Resume"
        assert res1["role_focus"] == "Software Engineer - Backend"
        assert res1["word_count"] == 5

        res_list = service.list_resumes(student_id)
        assert len(res_list) >= 1
        assert any(r["id"] == res1["id"] for r in res_list)

    def test_limit_of_5_is_enforced_with_clear_message(self, service):
        """The limit of 5 stored resumes is enforced with a clear message."""
        import uuid
        student_id = f"test_student_limit_{uuid.uuid4()}"
        # Store 5 resumes
        for i in range(1, 6):
            service.create_resume(
                student_id=student_id,
                label=f"Resume Variant {i}",
                role_focus=f"Role {i}",
                extracted_text=f"Experience for role {i} with specific skills."
            )

        assert service.count_resumes(student_id) == 5

        # 6th attempt must raise ResumeLimitExceededError
        with pytest.raises(ResumeLimitExceededError) as exc_info:
            service.create_resume(
                student_id=student_id,
                label="Resume Variant 6",
                role_focus="Role 6",
                extracted_text="Attempting to exceed capacity limit."
            )

        assert "maximum limit of 5 stored resumes" in str(exc_info.value)
        assert "delete or replace" in str(exc_info.value)

    def test_ownership_checks(self, service):
        """Resumes are private to the user; another user cannot read, update or delete."""
        owner_id = "student_owner"
        other_id = "student_intruder"

        resume = service.create_resume(
            student_id=owner_id,
            label="Confidential Resume",
            role_focus="Executive",
            extracted_text="Confidential projects and career history"
        )
        resume_id = resume["id"]

        # Other user cannot get resume
        with pytest.raises(ResumeAccessDeniedError):
            service.get_resume(resume_id, other_id)

        # Other user cannot update resume
        with pytest.raises(ResumeAccessDeniedError):
            service.update_resume(resume_id, other_id, label="Hacked Label")

        # Other user cannot delete resume
        with pytest.raises(ResumeAccessDeniedError):
            service.delete_resume(resume_id, other_id)

        # Owner can read, update, delete
        assert service.get_resume(resume_id, owner_id) is not None
        updated = service.update_resume(resume_id, owner_id, label="Updated Label", role_focus="New Focus")
        assert updated["label"] == "Updated Label"
        assert updated["role_focus"] == "New Focus"

        assert service.delete_resume(resume_id, owner_id) is True
        assert service.get_resume(resume_id, owner_id) is None

    def test_deleting_resume_keeps_past_analyses_readable(self, client, monkeypatch):
        """Deleting a resume keeps past analyses readable and accessible."""
        student_id = "test_student_deletion_preservation"
        from utils.resume_library_service import resume_library_service
        from utils.database import save_analysis, get_analysis, get_analyses_history

        # Create stored resume
        r = resume_library_service.create_resume(
            student_id=student_id,
            label="Data Science Resume",
            role_focus="Data Science",
            extracted_text="Python, PyTorch, Pandas, Scikit-Learn machine learning",
            resume_filename="ds_resume.pdf"
        )
        r_id = r["id"]

        # Run analysis using this stored resume
        analysis_id = "test-analysis-stored-resume-842"
        save_analysis(
            analysis_id=analysis_id,
            resume_filename=r["resume_filename"],
            company_name="Meta",
            job_description="Data scientist role",
            results_dict={
                "resume_analysis": {"ats_score": 88},
                "job_match": {"match_percentage": 82},
                "stored_resume_id": r_id,
                "stored_resume_label": r["label"]
            },
            student_id=student_id,
            stored_resume_id=r_id,
            stored_resume_label=r["label"]
        )

        # Verify analysis exists and has stored resume label
        past_record = get_analysis(analysis_id)
        assert past_record is not None
        assert past_record["results"]["stored_resume_label"] == "Data Science Resume"

        # Now delete the stored resume from the library
        deleted = resume_library_service.delete_resume(r_id, student_id)
        assert deleted is True

        # Verify past analysis is STILL intact and readable
        preserved_record = get_analysis(analysis_id)
        assert preserved_record is not None
        assert preserved_record["id"] == analysis_id
        assert preserved_record["results"]["stored_resume_label"] == "Data Science Resume"


class TestResumeLibraryRoutes:
    def test_my_resumes_page_requires_login(self, client):
        """Unauthenticated user is redirected to index when login enforcement is enabled."""
        from app import app
        orig = app.config.get("ENFORCE_LOGIN_IN_TESTS", False)
        app.config["ENFORCE_LOGIN_IN_TESTS"] = True
        try:
            resp = client.get("/resumes")
            assert resp.status_code == 302
        finally:
            app.config["ENFORCE_LOGIN_IN_TESTS"] = orig

    def test_my_resumes_page_renders_for_logged_in_user(self, client):
        """Logged-in student sees My Resumes page with capacity badge."""
        student_id = "student_my_resumes_ui"
        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        resp = client.get("/resumes")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "My Resumes Library" in html
        assert "resumeLibraryCapacityBadge" in html

    def test_api_crud_stored_resumes(self, client):
        """Full API CRUD workflow for stored resumes."""
        student_id = "student_api_crud"
        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        # 1. Create
        create_resp = client.post("/api/resumes", data={
            "label": "Mobile Dev Resume",
            "role_focus": "Android Developer",
            "resume_text": "Kotlin, Android SDK, Jetpack Compose, Coroutines"
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert create_resp.status_code == 201
        data = create_resp.get_json()
        assert data["success"] is True
        res_id = data["resume"]["id"]
        assert data["resume"]["label"] == "Mobile Dev Resume"

        # 2. List
        list_resp = client.get("/api/resumes")
        assert list_resp.status_code == 200
        assert list_resp.get_json()["count"] >= 1

        # 3. Get single
        get_resp = client.get(f"/api/resumes/{res_id}")
        assert get_resp.status_code == 200
        assert get_resp.get_json()["resume"]["id"] == res_id

        # 4. Update
        update_resp = client.post(f"/api/resumes/{res_id}", data={
            "label": "Senior Android Dev Resume",
            "role_focus": "Lead Mobile Engineer"
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert update_resp.status_code == 200
        assert update_resp.get_json()["resume"]["label"] == "Senior Android Dev Resume"

        # 5. Delete
        delete_resp = client.post(f"/api/resumes/{res_id}/delete", headers={"X-Requested-With": "XMLHttpRequest"})
        assert delete_resp.status_code == 200
        assert delete_resp.get_json()["success"] is True

        # Verify 404 after deletion
        assert client.get(f"/api/resumes/{res_id}").status_code == 404

    def test_analysis_submission_with_stored_resume(self, client, monkeypatch):
        """Analysis form selects stored resume and runs analysis successfully."""
        student_id = "student_analysis_with_stored"
        from utils.resume_library_service import resume_library_service
        stored = resume_library_service.create_resume(
            student_id=student_id,
            label="DevOps Resume",
            role_focus="Cloud / DevOps",
            extracted_text="Terraform, Kubernetes, AWS, CI/CD, Docker, Prometheus",
            resume_filename="devops_resume.pdf"
        )

        with client.session_transaction() as sess:
            sess["user_id"] = student_id
            sess["student_id"] = student_id

        # Mock coordinator agent
        from agents.coordinator import CoordinatorAgent
        monkeypatch.setattr(
            CoordinatorAgent,
            "analyze",
            lambda self, resume_text, job_description, company_name, on_progress=None: {
                "resume_analysis": {"ats_score": 90, "strengths": ["DevOps"], "weaknesses": []},
                "job_match": {"match_percentage": 85, "matched_skills": ["Kubernetes"], "missing_skills": []}
            }
        )

        resp = client.post("/analyze", data={
            "stored_resume_id": stored["id"],
            "company": "Amazon",
            "job_description": "Looking for DevOps / Cloud Engineer",
            "privacy_consent": "true",
            "data_processing_consent": "true"
        }, follow_redirects=False)

        assert resp.status_code in (302, 200)
        # Should redirect to dashboard/<analysis_id>
        location = resp.headers.get("Location", "")
        assert "/dashboard/" in location
