"""
Unit and Integration Tests for Role-Targeted Skill Gap Analysis (#495).
======================================================================
Tests:
1. Skills written in different forms such as JS and JavaScript are matched correctly.
2. A new role can be added by adding one JSON file only (dynamic discovery).
3. Selecting a different role changes the results (different matched skills, missing skills, suggested topics).
4. Suggested topics to learn are provided for every identified skill gap.
5. REST API endpoints (/api/skill-gap/roles, /api/skill-gap/roles/<id>, /api/skill-gap/analyze, /api/analysis/<id>/role-skill-gap).
6. Dashboard rendering with role selector and role gap metrics.
"""

import json
import tempfile
import uuid
from pathlib import Path
import pytest

from app import app
from utils.database import init_db, save_analysis
from utils.role_skill_gap_service import (
    DEFAULT_ROLES_DIR,
    SKILL_ALIASES,
    analyze_role_skill_gap,
    extract_candidate_skills,
    get_available_roles,
    get_role_profile,
    normalize_skill_name,
    skills_match,
)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure database is initialized before running tests."""
    init_db()


@pytest.fixture
def client():
    """Provides a Flask test client with testing and debug configs."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


# ==============================================================================
# CRITERION 1: SKILL ALIAS NORMALIZATION & MATCHING
# ==============================================================================

def test_alias_normalization_and_matching():
    """
    Acceptance Criterion 3:
    Skills written in different forms such as JS and JavaScript are matched correctly.
    """
    # Direct alias resolution
    assert normalize_skill_name("JS") == "javascript"
    assert normalize_skill_name("JavaScript") == "javascript"
    assert normalize_skill_name("ECMAScript") == "javascript"
    assert normalize_skill_name("es6") == "javascript"
    assert normalize_skill_name("Vanilla JS") == "javascript"

    # TypeScript
    assert normalize_skill_name("TS") == "typescript"
    assert normalize_skill_name("TypeScript") == "typescript"

    # Frameworks & Libraries
    assert normalize_skill_name("ReactJS") == "react"
    assert normalize_skill_name("React.js") == "react"
    assert normalize_skill_name("React") == "react"
    assert normalize_skill_name("NodeJS") == "node.js"
    assert normalize_skill_name("Node.js") == "node.js"

    # Databases & DevOps
    assert normalize_skill_name("Postgres") == "postgresql"
    assert normalize_skill_name("PostgreSQL") == "postgresql"
    assert normalize_skill_name("Python 3") == "python"
    assert normalize_skill_name("Python") == "python"
    assert normalize_skill_name("PowerBI") == "power bi"
    assert normalize_skill_name("Power BI") == "power bi"
    assert normalize_skill_name("K8s") == "kubernetes"
    assert normalize_skill_name("Kubernetes") == "kubernetes"
    assert normalize_skill_name("REST API") == "rest apis"
    assert normalize_skill_name("RESTful APIs") == "rest apis"

    # Symmetrical matching via skills_match
    assert skills_match("JS", "JavaScript") is True
    assert skills_match("javascript", "JS") is True
    assert skills_match("ReactJS", "React") is True
    assert skills_match("TS", "TypeScript") is True
    assert skills_match("Postgres", "PostgreSQL") is True
    assert skills_match("Python 3", "Python") is True
    assert skills_match("PowerBI", "Power BI") is True
    assert skills_match("K8s", "Kubernetes") is True
    assert skills_match("REST API", "REST APIs") is True

    # Negative matches
    assert skills_match("Python", "Java") is False
    assert skills_match("React", "Angular") is False
    assert skills_match("", "Python") is False


def test_alias_matching_in_role_skill_gap_analysis():
    """
    Verifies that when a candidate provides skill aliases (e.g. 'JS', 'ReactJS', 'Postgres'),
    they successfully match the canonical requirements in the role profile.
    """
    candidate_skills = ["JS", "ReactJS", "Postgres", "Python 3", "Git"]

    # Analyze against web_developer (requires JavaScript, React, HTML, CSS, Git)
    result = analyze_role_skill_gap(candidate_skills, "web_developer")

    matched_names = [m["skill"].lower() for m in result["matched_skills"]]
    matched_from = [m.get("matched_from") for m in result["matched_skills"]]

    # "JavaScript" required by Web Developer matched from candidate's "JS"
    assert any("javascript" in m for m in matched_names)
    assert "JS" in matched_from

    # "React" required by Web Developer matched from candidate's "ReactJS"
    assert any("react" in m for m in matched_names)
    assert "ReactJS" in matched_from

    # "Git" matched directly
    assert any("git" in m for m in matched_names)


# ==============================================================================
# CRITERION 2: DYNAMIC ROLE PROFILE DISCOVERY VIA SINGLE JSON FILE
# ==============================================================================

def test_single_json_file_role_addition():
    """
    Acceptance Criterion 2:
    A new role can be added by adding one JSON file only.
    Tests dynamic loading from disk without application restart or code modification.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_roles_path = Path(temp_dir)

        # 1. Initially empty directory
        initial_roles = get_available_roles(temp_roles_path)
        assert len(initial_roles) == 0

        # 2. Add ONE new JSON file: cloud_security_engineer.json
        new_role_file = temp_roles_path / "cloud_security_engineer.json"
        new_role_data = {
            "id": "cloud_security_engineer",
            "name": "Cloud Security Engineer",
            "category": "Cybersecurity & Infrastructure",
            "description": "Secures cloud workloads, architectures, and identity access boundaries.",
            "required_skills": [
                "AWS",
                "Kubernetes",
                "Terraform",
                "Linux",
                "Network Security"
            ],
            "nice_to_have_skills": [
                "Python",
                "Docker",
                "SIEM"
            ],
            "suggested_topics": {
                "Terraform": [
                    "Infrastructure as Code Security Scanning",
                    "State File Encryption and Secrets Management",
                    "Terraform Sentinel Policies"
                ],
                "Network Security": [
                    "VPC Peering, Subnets, and Security Groups",
                    "TLS/SSL Certificate Lifecycle and Mutual TLS",
                    "WAF and DDoS Mitigation Strategies"
                ]
            }
        }
        with open(new_role_file, "w", encoding="utf-8") as f:
            json.dump(new_role_data, f, indent=2)

        # 3. Verify get_available_roles discovers the role immediately
        discovered_roles = get_available_roles(temp_roles_path)
        assert len(discovered_roles) == 1
        assert discovered_roles[0]["id"] == "cloud_security_engineer"
        assert discovered_roles[0]["name"] == "Cloud Security Engineer"
        assert len(discovered_roles[0]["required_skills"]) == 5
        assert len(discovered_roles[0]["nice_to_have_skills"]) == 3

        # 4. Verify get_role_profile retrieves it
        profile = get_role_profile("cloud_security_engineer", temp_roles_path)
        assert profile is not None
        assert profile["name"] == "Cloud Security Engineer"

        # 5. Run skill gap analysis against this dynamically added role
        candidate_skills = ["AWS", "K8s", "Linux", "Python"]
        analysis_result = analyze_role_skill_gap(candidate_skills, "cloud_security_engineer", temp_roles_path)

        assert analysis_result["role_id"] == "cloud_security_engineer"
        assert analysis_result["role_name"] == "Cloud Security Engineer"

        # AWS, Kubernetes (from K8s), Linux should be matched required skills
        matched_skills_names = [m["skill"] for m in analysis_result["matched_skills"]]
        assert "AWS" in matched_skills_names
        assert "Kubernetes" in matched_skills_names
        assert "Linux" in matched_skills_names

        # Missing required skills: Terraform and Network Security
        missing_skills_names = [m["skill"] for m in analysis_result["missing_skills"]]
        assert "Terraform" in missing_skills_names
        assert "Network Security" in missing_skills_names

        # Verify suggested topics were populated from the JSON
        tf_gap = next(m for m in analysis_result["missing_skills"] if m["skill"] == "Terraform")
        assert "Infrastructure as Code Security Scanning" in tf_gap["suggested_topics"]

        net_gap = next(m for m in analysis_result["missing_skills"] if m["skill"] == "Network Security")
        assert "VPC Peering, Subnets, and Security Groups" in net_gap["suggested_topics"]


def test_default_predefined_roles_present():
    """
    Verifies that default predefined role JSON profiles are available:
    Software Developer, Data Analyst, Web Developer.
    """
    roles = get_available_roles()
    role_ids = [r["id"] for r in roles]

    assert "software_developer" in role_ids
    assert "data_analyst" in role_ids
    assert "web_developer" in role_ids

    # Check Software Developer profile
    sd_role = get_role_profile("software_developer")
    assert sd_role is not None
    assert "Python" in sd_role["required_skills"]
    assert "Data Structures" in sd_role["required_skills"]

    # Check Data Analyst profile
    da_role = get_role_profile("data_analyst")
    assert da_role is not None
    assert "SQL" in da_role["required_skills"]
    assert any("power bi" in s.lower() or "tableau" in s.lower() for s in da_role["required_skills"])

    # Check Web Developer profile
    wd_role = get_role_profile("web_developer")
    assert wd_role is not None
    assert "JavaScript" in wd_role["required_skills"]
    assert "React" in wd_role["required_skills"]


# ==============================================================================
# CRITERION 3: SELECTING A DIFFERENT ROLE CHANGES RESULTS
# ==============================================================================

def test_selecting_different_role_changes_results():
    """
    Acceptance Criterion 1:
    Selecting a different role changes the results.
    Evaluates the same candidate skill profile against Software Developer,
    Data Analyst, and Web Developer, and confirms the outputs are distinctly different.
    """
    candidate_profile = {
        "results": {
            "job_match": {
                "matched_skills": ["Python", "SQL", "Git", "Data Structures", "Algorithms"]
            },
            "resume_analysis": {
                "skills": ["Python", "SQL", "Git", "DSA", "Pandas"]
            }
        }
    }

    # 1. Benchmark against Software Developer
    sd_result = analyze_role_skill_gap(candidate_profile, "software_developer")

    # 2. Benchmark against Data Analyst
    da_result = analyze_role_skill_gap(candidate_profile, "data_analyst")

    # 3. Benchmark against Web Developer
    wd_result = analyze_role_skill_gap(candidate_profile, "web_developer")

    # The matched skills lists must differ across roles
    sd_matched = {m["skill"] for m in sd_result["matched_skills"]}
    da_matched = {m["skill"] for m in da_result["matched_skills"]}
    wd_matched = {m["skill"] for m in wd_result["matched_skills"]}

    assert sd_matched != da_matched
    assert sd_matched != wd_matched
    assert da_matched != wd_matched

    # Missing skills lists must differ across roles
    sd_missing = {m["skill"] for m in sd_result["missing_skills"]}
    da_missing = {m["skill"] for m in da_result["missing_skills"]}
    wd_missing = {m["skill"] for m in wd_result["missing_skills"]}

    assert sd_missing != da_missing
    assert sd_missing != wd_missing

    # In Web Developer, HTML, CSS, JavaScript are missing
    assert any("html" in m.lower() for m in wd_missing)
    assert any("javascript" in m.lower() for m in wd_missing)

    # In Data Analyst, Excel and BI tools are missing
    assert any("excel" in m.lower() for m in da_missing)

    # In Software Developer, candidate has high match because they have Python, SQL, Git, DSA
    assert sd_result["match_percentage"] > wd_result["match_percentage"]

    # Role metadata is role-specific
    assert sd_result["role_id"] == "software_developer"
    assert da_result["role_id"] == "data_analyst"
    assert wd_result["role_id"] == "web_developer"


# ==============================================================================
# SUGGESTED TOPICS TO LEARN COVERAGE
# ==============================================================================

def test_suggested_topics_present_for_every_missing_skill():
    """
    Acceptance Criterion:
    Show matched skills, missing skills and suggested topics to learn for each gap.
    Verifies that every missing skill contains non-empty suggested topics.
    """
    empty_candidate = []

    for role_id in ["software_developer", "data_analyst", "web_developer"]:
        result = analyze_role_skill_gap(empty_candidate, role_id)
        missing_skills = result["missing_skills"]

        assert len(missing_skills) > 0, f"Role {role_id} should have missing skills for empty candidate"

        for gap in missing_skills:
            skill_name = gap["skill"]
            topics = gap.get("suggested_topics")

            assert isinstance(topics, list), f"Gap {skill_name} in {role_id} has invalid suggested_topics type"
            assert len(topics) >= 1, f"Gap {skill_name} in {role_id} must have at least one suggested topic"
            for topic in topics:
                assert isinstance(topic, str) and topic.strip(), f"Empty topic string for {skill_name}"

            assert gap.get("type") in ("Required", "Nice-to-Have")
            assert gap.get("priority") in ("High", "Medium", "Low")
            assert gap.get("learning_time")


# ==============================================================================
# API ENDPOINT TESTS
# ==============================================================================

def test_api_get_skill_gap_roles(client):
    """Verifies GET /api/skill-gap/roles returns HTTP 200 and all predefined roles."""
    resp = client.get("/api/skill-gap/roles")
    assert resp.status_code == 200

    payload = resp.get_json()
    assert payload["status"] == "success"
    assert payload["success"] is True
    assert isinstance(payload["roles"], list)

    role_ids = [r["id"] for r in payload["roles"]]
    assert "software_developer" in role_ids
    assert "data_analyst" in role_ids
    assert "web_developer" in role_ids


def test_api_get_skill_gap_role_profile(client):
    """Verifies GET /api/skill-gap/roles/<role_id> returns profile and handles 404."""
    # Valid role
    resp = client.get("/api/skill-gap/roles/software_developer")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["role"]["id"] == "software_developer"
    assert "Python" in data["role"]["required_skills"]

    # Invalid role
    resp_404 = client.get("/api/skill-gap/roles/non_existent_role_123")
    assert resp_404.status_code == 404
    data_404 = resp_404.get_json()
    assert data_404["status"] == "error"


def test_api_analyze_skill_gap_custom_payload(client):
    """Verifies POST /api/skill-gap/analyze with arbitrary skills and role_id."""
    payload = {
        "role_id": "web_developer",
        "skills": ["HTML", "CSS", "JS"]  # JS should match JavaScript
    }
    resp = client.post("/api/skill-gap/analyze", json=payload)
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["status"] == "success"
    assert data["role_id"] == "web_developer"

    matched = [m["skill"].lower() for m in data["matched_skills"]]
    assert "javascript" in matched
    assert "html" in matched
    assert "css" in matched

    # Missing skills should include React, etc. with suggested topics
    react_gap = next((m for m in data["missing_skills"] if "react" in m["skill"].lower()), None)
    assert react_gap is not None
    assert len(react_gap["suggested_topics"]) > 0


def test_api_analysis_role_skill_gap_endpoint(client):
    """
    Verifies GET /api/analysis/<analysis_id>/role-skill-gap?role=<role_id>
    evaluates stored analysis record against the requested role.
    """
    analysis_id = str(uuid.uuid4())
    student_id = "test_student_495"
    results = {
        "job_match": {
            "matched_skills": ["Python", "SQL", "Git"]
        },
        "resume_analysis": {
            "skills": ["Python", "SQL", "Git", "Algorithms"]
        }
    }
    resume_text = "Experienced Python backend engineer with SQL database skills and Git workflows."

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Software Engineering Internship",
        results_dict=results,
        student_id=student_id,
        resume_text=resume_text,
    )

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    # 1. Evaluate against Software Developer
    resp_sd = client.get(f"/api/analysis/{analysis_id}/role-skill-gap?role=software_developer")
    assert resp_sd.status_code == 200
    data_sd = resp_sd.get_json()
    assert data_sd["selected_role_id"] == "software_developer"
    assert data_sd["match_percentage"] > 0

    # 2. Evaluate against Data Analyst
    resp_da = client.get(f"/api/analysis/{analysis_id}/role-skill-gap?role=data_analyst")
    assert resp_da.status_code == 200
    data_da = resp_da.get_json()
    assert data_da["selected_role_id"] == "data_analyst"

    # 3. Switching role changes results
    assert data_sd["match_percentage"] != data_da["match_percentage"] or (
        data_sd["missing_skills"] != data_da["missing_skills"]
    )


def test_dashboard_renders_role_selector_and_gap_analysis(client):
    """
    Verifies dashboard view renders the Role Benchmark Selector,
    role match percentage, matched skills, and suggested topics to learn.
    """
    analysis_id = str(uuid.uuid4())
    student_id = "test_student_dashboard_495"
    results = {
        "job_match": {
            "matched_skills": ["Python", "Git", "React"]
        },
        "resume_analysis": {
            "ats_score": 78,
            "skills": ["Python", "Git", "React"]
        },
        "skill_gap": [
            {
                "skill": "Docker",
                "importance": "High",
                "priority": "High",
                "learning_time": "2 weeks",
                "learning_resource": "Docker Docs",
                "project_suggestion": "Containerize microservice"
            }
        ]
    }
    resume_text = "Full stack engineer building React and Python apps."

    save_analysis(
        analysis_id=analysis_id,
        resume_filename="resume.pdf",
        company_name="Microsoft",
        job_description="Full Stack Software Engineer",
        results_dict=results,
        student_id=student_id,
        resume_text=resume_text,
    )

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    # Request dashboard with specific target role query param
    resp = client.get(f"/dashboard/{analysis_id}?role=web_developer")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)

    # 1. Role selector and container present
    assert 'id="roleSkillGapSelectorContainer"' in html
    assert 'id="roleGapSelector"' in html
    assert 'web_developer' in html

    # 2. Role match badge and metrics present
    assert 'id="roleMatchScore"' in html
    assert 'id="roleReadinessBadge"' in html
    assert 'id="roleMatchedSkillsList"' in html

    # 3. Suggested topics heading present
    assert 'Suggested Topics to Learn' in html
