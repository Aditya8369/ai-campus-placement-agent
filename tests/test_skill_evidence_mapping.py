import pytest
import json
import uuid
from unittest.mock import patch
import config
from app import app
from utils.database import init_db, save_analysis
from utils.skill_evidence_mapper import (
    detect_skills_in_resume,
    map_skill_evidence,
    generate_skill_guidance
)

SAMPLE_RESUME_WITH_EVIDENCE = """
Aditya Mahajan
aditya@campus.edu | (555) 123-4567

TECHNICAL SKILLS:
Python, Java, Docker, Kubernetes, React, PostgreSQL, Git, AWS

PROJECTS:
E-Commerce Microservices Platform | Python, PostgreSQL, Git
- Architected asynchronous REST APIs in Python using FastAPI and SQLAlchemy.
- Designed relational schemas and executed complex queries in PostgreSQL with indexing.
- Maintained source control workflows and feature branches with Git.

AI Campus Placement Agent | React, Python
- Built interactive candidate dashboard interfaces using React and modern component hooks.
- Integrated automated interview pipelines communicating with backend web services.

WORK EXPERIENCE:
Software Engineering Intern - CloudTech Solutions (June 2025 - August 2025)
- Automated deployment scripts in Python to monitor server metrics and pipeline health.

EDUCATION:
B.Tech in Computer Science & Engineering - XYZ Institute of Technology
- Relevant Coursework: Data Structures & Algorithms, Database Systems, Cloud Computing (AWS).
"""

SAMPLE_RESUME_UNSUPPORTED_ONLY = """
John Doe
john@example.com

TECHNICAL SKILLS:
Docker, Kubernetes, Terraform, Redis, GraphQL

SUMMARY:
Passionate computer science student seeking software engineering internships.

EDUCATION:
B.S. in Computer Science - State University
"""


def test_detect_skills_in_resume():
    skills = detect_skills_in_resume(SAMPLE_RESUME_WITH_EVIDENCE)
    assert "Python" in skills
    assert "React" in skills
    assert "Docker" in skills
    assert "PostgreSQL" in skills
    assert "Kubernetes" in skills


def test_skill_evidence_mapping_supported_and_unsupported():
    mapping = map_skill_evidence(
        resume_text=SAMPLE_RESUME_WITH_EVIDENCE,
        target_skills=["Python", "React", "PostgreSQL", "Docker", "Kubernetes", "AWS"]
    )

    assert mapping["total_skills"] == 6
    assert mapping["supported_skills_count"] >= 3
    assert mapping["unsupported_skills_count"] >= 2
    assert mapping["evidence_score"] > 0

    skills_dict = {item["skill"]: item for item in mapping["skills"]}

    # Python is in Projects (E-Commerce & AI Placement Agent) and Experience -> Strong Evidence
    python_entry = skills_dict["Python"]
    assert python_entry["is_supported"] is True
    assert python_entry["evidence_level"] == "Strong Evidence"
    assert python_entry["status"] == "supported"
    assert any(loc["section"] == "Projects" for loc in python_entry["evidence_locations"])
    assert any(loc["section"] == "Work Experience" for loc in python_entry["evidence_locations"])

    # React is in Projects (AI Campus Placement Agent) -> Strong Evidence
    react_entry = skills_dict["React"]
    assert react_entry["is_supported"] is True
    assert react_entry["evidence_level"] == "Strong Evidence"
    assert any(loc["section"] == "Projects" for loc in react_entry["evidence_locations"])

    # Docker is ONLY in Technical Skills list -> No Supporting Evidence
    docker_entry = skills_dict["Docker"]
    assert docker_entry["is_supported"] is False
    assert docker_entry["evidence_level"] == "No Supporting Evidence"
    assert docker_entry["status"] == "unsupported"
    assert "Projects" not in docker_entry["sections_found"]
    assert "Work Experience" not in docker_entry["sections_found"]
    # Suggestions must be provided for unsupported skill
    assert len(docker_entry["suggestions"]) >= 2
    assert docker_entry["recommended_project"] != ""
    assert docker_entry["example_bullet"] != ""

    # Kubernetes is ONLY in Technical Skills list -> No Supporting Evidence
    k8s_entry = skills_dict["Kubernetes"]
    assert k8s_entry["is_supported"] is False
    assert k8s_entry["status"] == "unsupported"
    assert k8s_entry["recommended_project"] != ""

    # AWS is in Education (Cloud Computing coursework) -> Partial Evidence
    aws_entry = skills_dict["AWS"]
    assert aws_entry["is_supported"] is False
    assert aws_entry["evidence_level"] == "Partial Evidence"
    assert aws_entry["status"] == "partial"
    assert "Education" in aws_entry["sections_found"]
    assert len(aws_entry["suggestions"]) > 0


def test_resume_all_unsupported_skills():
    mapping = map_skill_evidence(
        resume_text=SAMPLE_RESUME_UNSUPPORTED_ONLY,
        target_skills=["Docker", "Kubernetes", "Terraform", "Redis"]
    )
    assert mapping["total_skills"] == 4
    assert mapping["supported_skills_count"] == 0
    assert mapping["unsupported_skills_count"] == 4
    assert mapping["evidence_score"] == 0

    for item in mapping["skills"]:
        assert item["is_supported"] is False
        assert item["status"] == "unsupported"
        assert len(item["suggestions"]) >= 2
        assert len(item["example_bullet"]) > 10


def test_generate_skill_guidance():
    proj, bullet, suggestions = generate_skill_guidance("Docker")
    assert "Containerized" in proj or "Docker" in proj
    assert "Docker" in bullet
    assert len(suggestions) >= 2


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_skill_evidence.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "student_evidence_test"
            yield client


def test_api_skill_evidence_endpoint(client, tmp_path):
    test_db = tmp_path / "test_api_evidence.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        analysis_id = "test-analysis-evidence-01"

        evidence_payload = map_skill_evidence(
            resume_text=SAMPLE_RESUME_WITH_EVIDENCE,
            target_skills=["Python", "Docker"]
        )

        results = {
            "resume_analysis": {"ats_score": 85, "strengths": ["Strong backend skills"]},
            "job_match": {"match_percentage": 78, "matched_skills": ["Python", "Docker"]},
            "skill_gap": [],
            "skill_evidence_mapping": evidence_payload
        }

        save_analysis(
            analysis_id=analysis_id,
            resume_filename="resume_sample.pdf",
            company_name="Google",
            job_description="Software Engineer Python",
            results_dict=results,
            student_id="student_evidence_test"
        )

        # 1. Fetch via API
        res = client.get(f"/api/analysis/{analysis_id}/skill-evidence")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        assert data["analysis_id"] == analysis_id
        assert data["skill_evidence"]["total_skills"] == 2
        assert data["skill_evidence"]["supported_skills_count"] == 1
        assert data["skill_evidence"]["unsupported_skills_count"] == 1

        # 2. Unauthorized access test
        app.config["ENFORCE_LOGIN_IN_TESTS"] = True
        app.config["ENFORCE_STUDENT_ISOLATION"] = True
        try:
            with client.session_transaction() as sess:
                sess["user_id"] = "unauthorized_student"
            res_unauth = client.get(f"/api/analysis/{analysis_id}/skill-evidence")
            assert res_unauth.status_code == 404
        finally:
            app.config["ENFORCE_STUDENT_ISOLATION"] = False
            app.config["ENFORCE_LOGIN_IN_TESTS"] = False

        # 3. HTML Dashboard render test
        with client.session_transaction() as sess:
            sess["user_id"] = "student_evidence_test"
        dash_res = client.get(f"/dashboard/{analysis_id}")
        assert dash_res.status_code == 200
        html = dash_res.data.decode("utf-8")
        assert "Skill Evidence Mapping" in html
        assert "skillEvidenceSection" in html
        assert "Needs Evidence" in html
        assert "Supported" in html
