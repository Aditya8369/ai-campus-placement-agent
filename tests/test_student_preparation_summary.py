import pytest
import os
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    save_student_profile,
    save_coding_submission,
    create_interview_session,
    save_company_checklist,
    save_job_application,
    get_company_checklist,
    get_student_preparation_summary_data
)
from utils.report_generator import generate_student_preparation_summary_pdf

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_prep_summary.db"
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "DATABASE_PATH", str(test_db)), \
         patch.object(config, "REPORT_FOLDER", str(report_dir)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "student_prep_summary_01"
                sess["user_name"] = "Alex Summary"
            yield client


def test_student_preparation_summary_data_aggregation(tmp_path):
    test_db = tmp_path / "test_db_prep.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "student_prep_001"

        # 1. Profile
        save_student_profile(
            student_id=student_id,
            full_name="Alex Kumar",
            department="Computer Science",
            grad_year=2026,
            cgpa=9.0,
            target_role="Full Stack Engineer",
            target_company="Amazon",
            skills=["Python", "React", "Docker", "PostgreSQL"]
        )

        # 2. Resume Analysis
        aid = str(uuid.uuid4())
        results = {
            "ats_score": 88,
            "job_match_score": 82,
            "skill_gap": [
                {"skill": "System Design", "priority": "High", "learning_time": "2 weeks"}
            ]
        }
        save_analysis(
            analysis_id=aid,
            resume_filename="alex_resume.pdf",
            company_name="Amazon",
            job_description="Distributed systems",
            results_dict=results,
            student_id=student_id
        )

        # 3. Coding Submission
        save_coding_submission(
            sub_id=f"sub_{uuid.uuid4().hex[:10]}",
            student_id=student_id,
            question_title="LRU Cache Implementation",
            language="python",
            code="class LRUCache: pass",
            passed=True,
            score=100,
            tests_passed=10,
            total_tests=10
        )

        # 4. Mock Interview Session
        create_interview_session(
            interview_id=f"session_{aid}",
            analysis_id=aid,
            questions_list=["Explain caching"]
        )

        # 5. Checklist task
        chk = get_company_checklist(student_id=student_id, company_name="Amazon")
        checklist_items = chk["checklist"]
        for cat in checklist_items:
            if checklist_items[cat]:
                checklist_items[cat][0]["completed"] = True
                break
        save_company_checklist(
            student_id=student_id,
            company_name="Amazon",
            checklist_data=checklist_items
        )

        # 6. Job application
        save_job_application(
            app_id="app-alex-01",
            student_id=student_id,
            company_name="Amazon",
            role_title="SDE-1",
            status="Interview"
        )

        # Gather summary
        summary = get_student_preparation_summary_data(student_id)

        assert summary["student_id"] == student_id
        assert summary["profile"]["full_name"] == "Alex Kumar"
        assert summary["analyses_count"] == 1
        assert summary["latest_analysis"]["company_name"] == "Amazon"
        assert summary["coding_stats"]["total_submissions"] == 1
        assert summary["coding_stats"]["passed_count"] == 1
        assert summary["interview_stats"]["total_sessions"] == 1
        assert summary["interview_stats"]["average_score"] == 90.0
        assert summary["completed_tasks_count"] >= 1
        assert summary["applications_summary"]["total"] == 1


def test_generate_student_preparation_summary_pdf_and_route(client, tmp_path):
    student_id = "student_prep_summary_01"
    pdf_path = str(tmp_path / "test_summary.pdf")

    # Generate PDF directly
    data = get_student_preparation_summary_data(student_id)
    out_file = generate_student_preparation_summary_pdf(data, pdf_path)
    assert os.path.exists(out_file)
    assert os.path.getsize(out_file) > 1000

    # Test HTTP GET route
    res = client.get("/download/preparation-summary")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["Content-Type"]
    assert "Placement_Preparation_Summary" in res.headers["Content-Disposition"]
    assert len(res.data) > 1000

    # Test parameter route
    res_param = client.get(f"/download/preparation-summary/{student_id}")
    assert res_param.status_code == 200
    assert len(res_param.data) > 1000
