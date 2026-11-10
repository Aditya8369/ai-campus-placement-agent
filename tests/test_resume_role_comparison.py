"""
Unit & Integration Tests for Resume Analysis Comparison by Job Role (#256)
==========================================================================
Tests:
1. Available technical role catalog retrieval and taxonomy validation.
2. Skill extraction precision from sample candidate resumes.
3. Multi-role comparative analysis across different career tracks (Software Engineer, ML, Data, Frontend).
4. Calculation of role match scores and role-specific missing skills.
5. Identification of common transferable skills present across all evaluated roles.
6. Error handling for empty resumes, missing role inputs, and unsupported roles.
7. Database persistence and retrieval of historical role comparisons.
8. REST API Endpoints:
   - GET /api/resume/compare-roles/catalog
   - POST /api/resume/compare-roles
   - GET /api/resume/compare-roles/history
"""

import pytest
import json

import config
from utils.database import init_db, get_db_connection
from utils.resume_role_comparator import (
    ensure_role_comparison_table,
    get_available_roles,
    extract_skills_from_resume_text,
    compare_resume_across_roles,
    save_multi_role_comparison,
    get_student_role_comparisons,
    TECHNICAL_ROLE_TAXONOMY
)
from app import app


@pytest.fixture
def role_comp_env(tmp_path, monkeypatch):
    """Sets up an isolated database and client for multi-role comparison testing."""
    test_db = tmp_path / "test_role_comparison.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_role_comparison_table(conn)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "role-comp-secret-key"

    with app.test_client() as client:
        yield client


SAMPLE_BACKEND_RESUME = """
John Doe - Software Engineer
Experience building microservices with Python, Go, and PostgreSQL.
Designed REST APIs, utilized Docker for containerization, and implemented Redis caching.
Proficient in Data Structures, Algorithms, Git, and Linux. Built high throughput systems.
"""

SAMPLE_FULLSTACK_RESUME = """
Jane Developer - Full Stack
Built dynamic web applications using React, TypeScript, HTML, CSS, and Tailwind.
Created backend REST APIs with Node.js and Express connected to MongoDB and PostgreSQL.
Experienced with Git, Docker, and CI/CD pipelines.
"""


def test_available_roles_catalog():
    """Verify available roles catalog contains all major technical archetypes."""
    roles = get_available_roles()
    assert len(roles) >= 6
    role_keys = [r["key"] for r in roles]
    assert "software_engineer" in role_keys
    assert "frontend_engineer" in role_keys
    assert "data_engineer" in role_keys
    assert "ml_engineer" in role_keys


def test_extract_skills_from_resume():
    """Verify regex tokenization extracts known technical keywords correctly."""
    skills = extract_skills_from_resume_text(SAMPLE_BACKEND_RESUME)
    assert "python" in skills
    assert "postgresql" in skills
    assert "docker" in skills
    assert "redis" in skills
    assert "git" in skills


def test_compare_resume_across_multiple_roles():
    """Verify differential match scores, missing skills, and common skills calculation."""
    roles_to_compare = ["software_engineer", "frontend_engineer", "data_engineer"]
    result = compare_resume_across_roles(
        resume_text=SAMPLE_BACKEND_RESUME,
        target_role_keys=roles_to_compare
    )

    assert result["evaluated_roles_count"] == 3
    assert len(result["candidate_skills"]) > 0

    # Backend resume should score significantly higher on software_engineer than frontend_engineer
    eval_map = {r["role_key"]: r for r in result["role_comparisons"]}
    se_score = eval_map["software_engineer"]["match_score"]
    fe_score = eval_map["frontend_engineer"]["match_score"]
    assert se_score > fe_score

    # Check missing skills in frontend
    assert any("react" in s for s in eval_map["frontend_engineer"]["missing_skills"])

    # Check common transferable skills (e.g., git)
    common = result["common_transferable_skills"]
    assert "git" in common or "git" in result["candidate_skills"]


def test_compare_resume_invalid_inputs():
    """Verify validation errors for missing or completely invalid roles."""
    with pytest.raises(ValueError) as exc1:
        compare_resume_across_roles(SAMPLE_BACKEND_RESUME, [])
    assert "At least one target job role must be selected" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        compare_resume_across_roles(SAMPLE_BACKEND_RESUME, ["chief_executive_officer", "musician"])
    assert "No valid roles found" in str(exc2.value)


def test_save_and_retrieve_role_comparisons(role_comp_env):
    """Verify database persistence of role comparison records per student."""
    student_id = "student_role_tester"
    result = compare_resume_across_roles(
        resume_text=SAMPLE_FULLSTACK_RESUME,
        target_role_keys=["fullstack_engineer", "frontend_engineer"]
    )

    saved = save_multi_role_comparison(
        student_id=student_id,
        resume_text=SAMPLE_FULLSTACK_RESUME,
        selected_roles=["fullstack_engineer", "frontend_engineer"],
        comparison_results=result
    )
    assert "comparison_id" in saved

    history = get_student_role_comparisons(student_id)
    assert len(history) == 1
    assert "fullstack_engineer" in history[0]["selected_roles"]
    assert history[0]["comparison"]["evaluated_roles_count"] == 2


def test_api_role_comparison_endpoints(role_comp_env):
    """Verify REST endpoints for role comparison catalog, execution, and history."""
    # 1. Catalog
    resp_cat = role_comp_env.get("/api/resume/compare-roles/catalog")
    assert resp_cat.status_code == 200
    assert resp_cat.get_json()["total_roles"] >= 6

    # 2. Execution
    resp_post = role_comp_env.post("/api/resume/compare-roles", json={
        "resume_text": SAMPLE_BACKEND_RESUME,
        "roles": ["software_engineer", "devops_cloud_engineer"]
    })
    assert resp_post.status_code == 200
    res_data = resp_post.get_json()
    assert res_data["status"] == "success"
    assert res_data["comparison"]["evaluated_roles_count"] == 2

    # 3. History
    resp_hist = role_comp_env.get("/api/resume/compare-roles/history")
    assert resp_hist.status_code == 200
    assert resp_hist.get_json()["total_comparisons"] >= 1
