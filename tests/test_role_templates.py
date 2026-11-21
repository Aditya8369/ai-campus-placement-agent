"""
Unit and integration tests for Predefined Role Skill Templates (#646).
=======================================================================
Covers:
1. Schema validation (passes valid schema, fails malformed/missing fields/duplicate ids).
2. Single-file extensibility (adding a role requires editing only the JSON file).
3. Template loading and lookup helper methods.
4. Formatting templates into standardized job descriptions for coordinator consumption.
5. Deterministic skill gap computation and prioritization.
6. API endpoints:
   - GET /api/role-templates
   - GET /api/role-templates/<role_id>
7. End-to-end web analysis workflow selecting a role instead of pasting a job description.
8. Landing page UI rendering of role selector and template options.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path
import pytest

from app import app
from utils.role_template_service import (
    DEFAULT_ROLE_TEMPLATES_FILE,
    assert_valid_role_templates,
    build_role_template_skill_gap,
    format_role_template_as_job_description,
    get_role_template_by_id,
    load_role_templates,
    validate_role_template_schema,
)
from utils.database import get_db_connection, save_analysis, get_analysis


# ==============================================================================
# 1. SCHEMA VALIDATION & INTEGRITY TESTS
# ==============================================================================

def test_production_role_templates_schema_passes_validation():
    """
    Acceptance criterion: Templates are validated (schema test) so malformed entries fail CI.
    Ensures data/role_templates.json is valid and contains at least 8-10 roles.
    """
    assert DEFAULT_ROLE_TEMPLATES_FILE.exists(), f"Role templates file missing at {DEFAULT_ROLE_TEMPLATES_FILE}"
    templates = load_role_templates(validate=True)
    assert len(templates) >= 8, f"Expected at least 8 roles, found {len(templates)}"

    # Check that required campus roles are present
    role_ids = {t["id"] for t in templates}
    expected_sample_roles = {"software_developer", "backend_developer", "frontend_developer", "data_analyst", "devops_engineer", "qa_engineer"}
    assert expected_sample_roles.issubset(role_ids), f"Missing expected sample roles in {role_ids}"


def test_schema_fails_on_non_list_root():
    """Validates that root element must be a list."""
    is_valid, errors = validate_role_template_schema({"id": "software_developer"})
    assert is_valid is False
    assert any("Root structure must be a JSON array" in err for err in errors)


def test_schema_fails_on_empty_list():
    """Validates that role templates list cannot be empty."""
    is_valid, errors = validate_role_template_schema([])
    assert is_valid is False
    assert any("must not be empty" in err for err in errors)


def test_schema_fails_on_missing_required_keys():
    """Validates that missing any required key fails schema validation."""
    malformed_entry = [{
        "id": "backend_dev",
        "name": "Backend Developer",
        # missing description, core_skills, good_to_have_skills, typical_tools
    }]
    is_valid, errors = validate_role_template_schema(malformed_entry)
    assert is_valid is False
    assert any("description" in err for err in errors)
    assert any("core_skills" in err for err in errors)


def test_schema_fails_on_empty_core_skills():
    """Validates that core_skills must be a non-empty list of strings."""
    malformed_entry = [{
        "id": "frontend_dev",
        "name": "Frontend Developer",
        "description": "Frontend UI developer",
        "core_skills": [],  # Empty!
        "good_to_have_skills": ["TypeScript"],
        "typical_tools": ["Vite"]
    }]
    is_valid, errors = validate_role_template_schema(malformed_entry)
    assert is_valid is False
    assert any("core_skills" in err and "non-empty" in err for err in errors)


def test_schema_fails_on_duplicate_ids():
    """Validates that duplicate role IDs are rejected."""
    entries_with_duplicates = [
        {
            "id": "backend_dev",
            "name": "Backend Dev 1",
            "description": "Desc 1",
            "core_skills": ["Python"],
            "good_to_have_skills": [],
            "typical_tools": ["Git"]
        },
        {
            "id": "backend_dev",
            "name": "Backend Dev 2",
            "description": "Desc 2",
            "core_skills": ["Java"],
            "good_to_have_skills": [],
            "typical_tools": ["Docker"]
        }
    ]
    is_valid, errors = validate_role_template_schema(entries_with_duplicates)
    assert is_valid is False
    assert any("Duplicate role id" in err for err in errors)


def test_assert_valid_role_templates_raises_value_error():
    """Validates that assert_valid_role_templates raises ValueError on violation."""
    with pytest.raises(ValueError) as excinfo:
        assert_valid_role_templates([{"invalid": "data"}])
    assert "Role templates schema validation failed" in str(excinfo.value)


# ==============================================================================
# 2. SINGLE-FILE EXTENSIBILITY TEST
# ==============================================================================

def test_single_json_file_role_addition():
    """
    Acceptance criterion: Adding a role requires editing only the JSON file.
    Verifies that placing an additional role into the JSON file allows it to be
    loaded and used immediately with ZERO code modifications.
    """
    sample_roles = [
        {
            "id": "cybersecurity_analyst",
            "name": "Cybersecurity Analyst",
            "description": "Protects IT infrastructure, performs penetration tests and audits security posture.",
            "core_skills": ["Network Security", "Cryptography", "Linux", "Python", "Vulnerability Assessment"],
            "good_to_have_skills": ["SIEM", "Wireshark", "Cloud Security", "Incident Response"],
            "typical_tools": ["Wireshark", "Nmap", "Metasploit", "Burp Suite", "Kali Linux"]
        }
    ]

    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(sample_roles, tmp)
        tmp_path = tmp.name

    try:
        loaded = load_role_templates(file_path=tmp_path, validate=True)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "cybersecurity_analyst"

        found = get_role_template_by_id("cybersecurity_analyst", file_path=tmp_path)
        assert found is not None
        assert found["name"] == "Cybersecurity Analyst"
        assert "Network Security" in found["core_skills"]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ==============================================================================
# 3. HELPER & FORMATTING TESTS
# ==============================================================================

def test_format_role_template_as_job_description():
    """
    Verifies that a role template formats into a structured job description
    with clear sections that the analysis engine can process.
    """
    template = {
        "id": "backend_developer",
        "name": "Backend Developer",
        "description": "Design and build scalable server-side systems and REST APIs.",
        "core_skills": ["Python", "SQL", "REST APIs"],
        "good_to_have_skills": ["Docker", "Redis"],
        "typical_tools": ["Postman", "PostgreSQL", "Docker"]
    }

    formatted_jd = format_role_template_as_job_description(template)
    assert "Role: Backend Developer" in formatted_jd
    assert "Design and build scalable server-side systems" in formatted_jd
    assert "- Python" in formatted_jd
    assert "- SQL" in formatted_jd
    assert "- Docker" in formatted_jd
    assert "- Postman" in formatted_jd


def test_build_role_template_skill_gap_computation():
    """
    Verifies deterministic skill gap calculation, match score weighting,
    and priority categorization.
    """
    template = {
        "id": "software_developer",
        "name": "Software Developer",
        "description": "Core software engineering.",
        "core_skills": ["Data Structures", "Algorithms", "Python", "SQL"],
        "good_to_have_skills": ["Docker", "System Design"],
        "typical_tools": ["Git", "VS Code"]
    }

    # Candidate has Python and SQL, plus lowercase match for DSA
    candidate_skills = ["python", "SQL", "data structures", "git"]
    gap_result = build_role_template_skill_gap(candidate_skills, template)

    assert "job_match" in gap_result
    assert "skill_gap" in gap_result
    job_match = gap_result["job_match"]

    # Matched core: Python, SQL, Data Structures (3 of 4)
    assert "Python" in job_match["core_matched"]
    assert "SQL" in job_match["core_matched"]
    assert "Data Structures" in job_match["core_matched"]
    assert "Algorithms" in job_match["core_missing"]

    # Skill gap should have High importance for missing core skill (Algorithms)
    alg_gap = next((item for item in gap_result["skill_gap"] if item["skill"] == "Algorithms"), None)
    assert alg_gap is not None
    assert alg_gap["importance"] == "High"
    assert alg_gap["priority"] == "High"
    assert "Official Algorithms Documentation" in alg_gap["learning_resource"]


# ==============================================================================
# 4. API ENDPOINT TESTS
# ==============================================================================

def test_api_get_role_templates_endpoint():
    """Verifies GET /api/role-templates returns all templates and count."""
    with app.test_client() as client:
        resp = client.get("/api/role-templates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] >= 8
        assert isinstance(data["templates"], list)

        # Confirm software_developer template exists
        sde = next((r for r in data["templates"] if r["id"] == "software_developer"), None)
        assert sde is not None
        assert sde["name"] == "Software Developer"
        assert len(sde["core_skills"]) > 0


def test_api_get_role_template_by_id_endpoint():
    """Verifies GET /api/role-templates/<role_id> for existing and non-existing roles."""
    with app.test_client() as client:
        # Existing role
        resp = client.get("/api/role-templates/data_analyst")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["template"]["name"] == "Data Analyst"
        assert "SQL" in data["template"]["core_skills"]

        # Non-existing role
        resp_404 = client.get("/api/role-templates/quantum_computing_specialist_xyz")
        assert resp_404.status_code == 404
        data_404 = resp_404.get_json()
        assert data_404["success"] is False
        assert "not found" in data_404["error"].lower()


# ==============================================================================
# 5. END-TO-END WORKFLOW & UI TESTS
# ==============================================================================

def test_landing_page_renders_role_template_options():
    """
    Verifies that index.html renders the role selection section and
    populates the dropdown with role templates.
    """
    with app.test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "roleTemplateSelect" in html
        assert "Choose a Role Instead" in html
        assert "Software Developer" in html
        assert "Backend Developer" in html
        assert "Data Analyst" in html


def test_analyze_with_role_template_produces_skill_gap(monkeypatch):
    """
    Acceptance criterion: A role can be chosen instead of pasting a job description
    and produces a skill gap result.
    """
    from routes.common import coordinator_agent

    captured_inputs = {}

    def mock_coordinator_analyze(resume_text, job_description="", company_name="General", on_progress=None):
        captured_inputs["resume_text"] = resume_text
        captured_inputs["job_description"] = job_description
        captured_inputs["company_name"] = company_name
        return {
            "ats_score": 82,
            "job_match": {
                "match_percentage": 78,
                "matched_skills": ["Python", "SQL", "REST APIs"],
                "missing_skills": ["Docker", "Redis"],
                "status": "Strong Match"
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
            ],
            "roadmap": [
                {
                    "week": 1,
                    "title": "Master Docker containerization",
                    "tasks": ["Learn Dockerfile basics", "Run multi-container setups with compose"]
                }
            ]
        }

    monkeypatch.setattr(coordinator_agent, "analyze", mock_coordinator_analyze)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "student_role_test_001"
            sess["user_name"] = "Role Tester"

        resume_content = (
            "Alex Smith\n"
            "Email: alex@campus.edu\n"
            "Education: B.Tech Computer Science\n"
            "Skills: Python, SQL, REST APIs, Git\n"
            "Experience: Built API endpoints using Flask and PostgreSQL."
        )

        resp = client.post(
            "/analyze",
            data={
                "resume_text": resume_content,
                "role_template": "backend_developer",
                "analysis_mode": "role",
                "privacy_consent": "true",
                "third_party_consent": "true",
                "company": "General",
                "rerun": "true",
            },
            follow_redirects=False,
        )

        # Should redirect to candidate dashboard on success
        assert resp.status_code == 302
        assert "/dashboard/" in resp.headers["Location"]

        # Verify coordinator received the formatted role template as the job description
        assert "Backend Developer" in captured_inputs["job_description"]
        assert "Core Technical Competencies" in captured_inputs["job_description"]
        assert "Python" in captured_inputs["job_description"]
