"""
Unit and Integration Tests for Resume Information Review and Correction Step.

Tests:
1. Extraction of structured sections (Name, Contact, Education, Skills, Projects, Experience).
2. Detection and highlighting of incomplete or low-confidence fields (needs_review flags).
3. Student editing of extracted data and manual addition of missing information.
4. Validation rules for reviewed information (name, skills, education requirements).
5. Downstream integration: verified/corrected information is formatted and used by coordinator.
6. Original uploaded file preservation: disk file remains untouched and unmodified.
7. Web endpoints: /resume/review, /resume/review/<file_uuid>, /api/resume/parse-preview,
   /api/resume/validate-info, and /api/resume/confirm-analysis.
"""

import os
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
import app as flask_app_module
from app import app
from utils.resume_info_extractor import (
    extract_resume_information,
    extract_candidate_name,
    extract_emails,
    extract_phone,
    extract_education_entries,
    extract_skills_list,
    extract_projects_entries,
    extract_experience_entries,
    validate_reviewed_information,
    reconstruct_resume_markdown
)
import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "test_student_review_01"
            sess["user_name"] = "Alice Tester"
            sess["role"] = "student"
        yield client


SAMPLE_COMPLETE_RESUME = """
Ananya Sharma
ananya.sharma@example.com | +91 9876543210
Bangalore, India

Professional Summary:
Passionate Software Engineering undergraduate with strong foundations in distributed systems, full-stack web applications, and algorithmic problem solving.

Education:
B.Tech in Computer Science and Engineering
National Institute of Technology Karnataka (2020 - 2024) - CGPA: 9.2

Technical Skills:
Python, Java, JavaScript, React, Node.js, FastAPI, Docker, PostgreSQL, Redis, Git, Data Structures

Projects:
Campus Placement Orchestrator | Python, FastAPI, React
Engineered an intelligent placement preparation assistant coordinating multi-agent evaluations and live mock interviews.
Reduced evaluation latency by 45%.

Experience:
Backend Engineering Intern at TechVenture Labs (May 2023 - Jul 2023)
Designed and deployed microservices in Go and Docker, handling 50k requests per minute with 99.9% uptime.
"""

SAMPLE_INCOMPLETE_RESUME = """
Curriculum Vitae
Page 1 of 1

Academic Background:
College student studying programming.

Work:
Helped with local website development.
"""


# ============================================================================
# 1. TEST STRUCTURED INFORMATION EXTRACTION
# ============================================================================

def test_extract_resume_information_complete():
    """Verify that complete resumes have all entities extracted with positive status."""
    result = extract_resume_information(SAMPLE_COMPLETE_RESUME, filename="ananya_resume.pdf")

    assert result["candidate_name"] == "Ananya Sharma"
    assert result["email"] == "ananya.sharma@example.com"
    assert "9876543210" in result["phone"]
    assert len(result["education"]) >= 1
    assert any("Computer Science" in e.get("degree", "") or "Computer Science" in e.get("field_of_study", "") for e in result["education"])
    assert len(result["skills"]) >= 5
    assert "Python" in result["skills"]
    assert "React" in result["skills"]
    assert len(result["projects"]) >= 1
    assert "Placement" in result["projects"][0]["title"] or "Campus" in result["projects"][0]["title"]
    assert len(result["experience"]) >= 1
    assert "TechVenture" in result["experience"][0]["company"] or "Backend" in result["experience"][0]["role"]

    # Quality check
    assert result["overall_extraction_quality"] == "good"
    assert result["review_flags"]["candidate_name"]["status"] == "extracted"
    assert result["review_flags"]["email"]["status"] == "extracted"


def test_extract_resume_information_incomplete_highlights_needs_review():
    """Verify that incomplete or poorly scanned resumes flag missing fields for review."""
    result = extract_resume_information(SAMPLE_INCOMPLETE_RESUME, filename="scan_doc.pdf")

    # Name should be ambiguous/needs review
    assert result["review_flags"]["candidate_name"]["status"] == "needs_review"
    # Contact info missing
    assert result["review_flags"]["email"]["status"] == "needs_review"
    assert result["review_flags"]["phone"]["status"] == "needs_review"
    # Skills missing
    assert result["review_flags"]["skills"]["status"] == "needs_review"
    # Total review items should be > 0
    assert result["total_review_items"] >= 3
    assert result["overall_extraction_quality"] in ("needs_attention", "poor")


# ============================================================================
# 2. TEST EDITING & MANUAL ADDITIONS
# ============================================================================

def test_manual_addition_of_missing_information():
    """Verify students can add education, skills, projects, and experiences manually."""
    # Start with empty/incomplete data
    reviewed_data = {
        "file_uuid": str(uuid.uuid4()),
        "original_filename": "incomplete.pdf",
        "candidate_name": "Rohan Verma",  # Corrected name
        "email": "rohan.verma@example.com",  # Added email
        "phone": "+91 9123456789",  # Added phone
        "summary": "Enthusiastic developer preparing for product engineering roles.",
        "skills": ["Python", "Django", "PostgreSQL", "AWS"],  # Added skills
        "education": [  # Added education
            {
                "institution": "Delhi Technological University",
                "degree": "B.Tech",
                "field_of_study": "Information Technology",
                "graduation_year": "2025",
                "score": "8.7 CGPA"
            }
        ],
        "projects": [  # Added project
            {
                "title": "Cloud File Synchronizer",
                "technologies": "Python, AWS S3, SQLite",
                "description": "Built real-time client-server directory synchronization tool."
            }
        ],
        "experience": [  # Added internship
            {
                "role": "Frontend Intern",
                "company": "Startup Hub",
                "duration": "Jan 2024 - Mar 2024",
                "responsibilities": "Built dashboard views in React."
            }
        ]
    }

    is_valid, errors = validate_reviewed_information(reviewed_data)
    assert is_valid is True
    assert len(errors) == 0

    # Reconstructed markdown contains all manually added information
    reconstructed_md = reconstruct_resume_markdown(reviewed_data)
    assert "# Rohan Verma" in reconstructed_md
    assert "rohan.verma@example.com" in reconstructed_md
    assert "Delhi Technological University" in reconstructed_md
    assert "Python, Django, PostgreSQL, AWS" in reconstructed_md
    assert "Cloud File Synchronizer" in reconstructed_md
    assert "Startup Hub" in reconstructed_md


# ============================================================================
# 3. TEST VALIDATION LOGIC
# ============================================================================

def test_validation_rejects_missing_name():
    """Validation must require a valid candidate name."""
    data = {
        "candidate_name": "",
        "skills": ["Python", "SQL"]
    }
    is_valid, errors = validate_reviewed_information(data)
    assert is_valid is False
    assert "candidate_name" in errors


def test_validation_rejects_digits_only_name():
    """Validation must reject numeric-only names."""
    data = {
        "candidate_name": "123456",
        "skills": ["Python"]
    }
    is_valid, errors = validate_reviewed_information(data)
    assert is_valid is False
    assert "candidate_name" in errors


def test_validation_rejects_empty_skills():
    """Validation must require at least one skill."""
    data = {
        "candidate_name": "Priya Patel",
        "skills": []
    }
    is_valid, errors = validate_reviewed_information(data)
    assert is_valid is False
    assert "skills" in errors


def test_validation_rejects_blank_education_and_projects():
    """Education entries must have an institution or degree."""
    data = {
        "candidate_name": "Priya Patel",
        "skills": ["Java"],
        "education": [{"institution": "", "degree": ""}],
        "projects": [{"title": "", "description": "some project"}]
    }
    is_valid, errors = validate_reviewed_information(data)
    assert is_valid is False
    assert "education_0" in errors
    assert "project_0" in errors


# ============================================================================
# 4. TEST ORIGINAL DOCUMENT PRESERVATION
# ============================================================================

def test_original_uploaded_document_preserved_unaltered(tmp_path):
    """Ensure that the original uploaded resume file on disk is untouched."""
    # Create a dummy original PDF file
    original_file_content = b"%PDF-1.4 original binary content cannot be modified"
    test_uuid = str(uuid.uuid4())
    filename = f"{test_uuid}_my_original_resume.pdf"
    file_path = os.path.join(config.UPLOAD_FOLDER, filename)

    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(original_file_content)

    try:
        # Simulate review & confirmation
        reviewed_payload = {
            "file_uuid": test_uuid,
            "original_filename": "my_original_resume.pdf",
            "candidate_name": "Siddharth Nair",
            "skills": ["C++", "Python", "Linux"],
            "education": [{"institution": "IIT Madras", "degree": "B.Tech", "graduation_year": "2024"}]
        }

        # Reconstruct and validate
        is_valid, _ = validate_reviewed_information(reviewed_payload)
        assert is_valid is True
        md = reconstruct_resume_markdown(reviewed_payload)
        assert "Siddharth Nair" in md

        # Verify disk file is 100% byte-identical
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            current_content = f.read()
        assert current_content == original_file_content

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# ============================================================================
# 5. TEST WEB ROUTES AND ENDPOINTS
# ============================================================================

def test_resume_review_post_route(client):
    """POST to /resume/review should render review page with extracted details."""
    response = client.post(
        "/resume/review",
        data={
            "resume_text": SAMPLE_COMPLETE_RESUME,
            "company": "Amazon",
            "job_description": "Software Development Engineer"
        }
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Review &amp; Correct Resume Details" in html or "Review & Correct Resume Details" in html
    assert "Ananya Sharma" in html
    assert "Original Document Preserved Unaltered" in html


def test_api_resume_parse_preview(client):
    """API endpoint /api/resume/parse-preview returns JSON with structured extraction and flags."""
    response = client.post(
        "/api/resume/parse-preview",
        data={
            "resume_text": SAMPLE_COMPLETE_RESUME,
            "company": "Google"
        }
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "file_uuid" in data
    assert "review_data" in data
    assert data["review_data"]["candidate_name"] == "Ananya Sharma"
    assert "/resume/review/" in data["review_url"]


def test_api_validate_resume_info(client):
    """API endpoint /api/resume/validate-info returns validation results."""
    # Invalid request
    bad_res = client.post(
        "/api/resume/validate-info",
        json={"candidate_name": "", "skills": []}
    )
    assert bad_res.status_code == 200
    bad_data = bad_res.get_json()
    assert bad_data["is_valid"] is False
    assert "candidate_name" in bad_data["errors"]
    assert "skills" in bad_data["errors"]

    # Valid request
    good_res = client.post(
        "/api/resume/validate-info",
        json={"candidate_name": "Kavita Rao", "skills": ["Python", "Django"]}
    )
    assert good_res.status_code == 200
    good_data = good_res.get_json()
    assert good_data["is_valid"] is True


def test_api_confirm_resume_analysis_uses_reviewed_data(client):
    """
    Submitting confirmed corrected information must pass reviewed text to coordinator
    and redirect to dashboard.
    """
    test_uuid = str(uuid.uuid4())
    payload = {
        "file_uuid": test_uuid,
        "original_filename": "uploaded_resume.pdf",
        "candidate_name": "Vikram Singh",
        "email": "vikram@example.com",
        "phone": "+91 9988776655",
        "summary": "Full stack engineer specializing in Python and Cloud.",
        "skills": ["Python", "FastAPI", "Docker", "PostgreSQL"],
        "education": [{
            "institution": "BITS Pilani",
            "degree": "B.E. Computer Science",
            "graduation_year": "2024"
        }],
        "projects": [{
            "title": "Cloud Deployment Orchestrator",
            "technologies": "Python, Docker, AWS",
            "description": "Automated blue-green deployments."
        }],
        "experience": [{
            "role": "Cloud Intern",
            "company": "DevCloud",
            "duration": "Summer 2023",
            "responsibilities": "Managed infrastructure as code."
        }],
        "target_company": "Microsoft",
        "job_description": "Cloud Solution Architect"
    }

    mock_analysis_result = {
        "overall_score": 88,
        "ats_compatibility": 90,
        "job_match_score": 85,
        "readiness_verdict": "Interview Ready",
        "interview_readiness": "High",
        "skills_analysis": {"matching_skills": ["Python", "Docker"]},
        "recommendations": ["Expand on Kubernetes experience"]
    }

    with patch.object(flask_app_module.coordinator_agent, "analyze", return_value=mock_analysis_result) as mock_analyze:
        response = client.post(
            "/api/resume/confirm-analysis",
            json=payload
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["analysis_id"] == test_uuid
        assert f"/dashboard/{test_uuid}" in data["redirect_url"]

        # Verify coordinator was called with reviewed text containing candidate's corrections
        mock_analyze.assert_called_once()
        call_kwargs = mock_analyze.call_args[1]
        passed_resume_text = call_kwargs["resume_text"]
        assert "Vikram Singh" in passed_resume_text
        assert "BITS Pilani" in passed_resume_text
        assert "Cloud Deployment Orchestrator" in passed_resume_text
        assert call_kwargs["company_name"] == "Microsoft"


def test_resume_review_by_uuid_view(client):
    """GET /resume/review/<file_uuid> should render review page when cache exists."""
    test_uuid = str(uuid.uuid4())
    review_data = extract_resume_information(SAMPLE_COMPLETE_RESUME, filename="test.pdf", file_uuid=test_uuid)
    flask_app_module.save_resume_review_cache(test_uuid, review_data)

    response = client.get(f"/resume/review/{test_uuid}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Ananya Sharma" in html
    assert "Review &amp; Correct Resume Details" in html or "Review & Correct Resume Details" in html
