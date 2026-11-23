"""
Unit tests for Section-by-section resume approval (#601)
"""

import pytest
from utils.resume_section_approval_service import (
    parse_resume_for_approval,
    reassemble_approved_resume,
    CANONICAL_SECTIONS
)


def test_parse_resume_for_approval_full_text():
    sample_resume = """
    John Doe
    Email: john@example.com | Phone: 123-456-7890
    
    EDUCATION
    B.Tech in Computer Science, State University, 2024, GPA: 3.8/4.0
    
    TECHNICAL SKILLS
    Python, Flask, JavaScript, SQL, Git, Linux
    
    PROJECTS
    Placement Preparation Agent: An intelligent multi-agent platform for students.
    
    EXPERIENCE
    Software Engineering Intern at Acme Corp. Built backend REST APIs.
    
    CERTIFICATIONS
    AWS Certified Solutions Architect Associate
    """
    
    result = parse_resume_for_approval(sample_resume)
    assert result["is_complete"] is True
    assert result["detected_count"] >= 5
    assert len(result["sections"]) == len(CANONICAL_SECTIONS)
    assert result["sections"]["name"]["detected"] is True
    assert "John Doe" in result["sections"]["name"]["content"]
    assert result["sections"]["education"]["detected"] is True
    assert result["sections"]["skills"]["detected"] is True
    assert result["sections"]["projects"]["detected"] is True
    assert result["sections"]["experience"]["detected"] is True


def test_parse_resume_for_approval_missing_section_warning():
    # Resume missing education and projects
    sparse_resume = """
    Jane Smith
    Phone: 9876543210
    
    SKILLS
    Python, C++
    """
    result = parse_resume_for_approval(sparse_resume)
    assert result["is_complete"] is False
    assert len(result["warnings"]) > 0
    assert any("education" in w.lower() for w in result["warnings"])
    assert result["sections"]["education"]["detected"] is False
    assert result["sections"]["education"]["warning"] is not None


def test_reassemble_approved_resume():
    approved = {
        "name": "Alex Johnson\nalex@domain.com",
        "skills": "Python, Django, PostgreSQL",
        "education": "BS in Computer Engineering, Top Institute",
        "projects": "Distributed Key-Value Store with Raft consensus."
    }
    reassembled = reassemble_approved_resume(approved)
    assert "# CANDIDATE INFORMATION" in reassembled
    assert "Alex Johnson" in reassembled
    assert "# TECHNICAL SKILLS" in reassembled
    assert "Django" in reassembled
    assert "# PROJECTS" in reassembled
    assert "Distributed Key-Value Store" in reassembled
    assert "# EDUCATION" in reassembled


def test_api_parse_sections_endpoint(client):
    # Test POST /api/resume/parse-sections with form text
    valid_text = (
        "Bob Builder\n"
        "Email: bob@builder.example.com | Phone: 9876543210\n"
        "Skills: Python, Docker, Kubernetes, Linux, Git, SQL\n"
        "Education: Bachelor of Technology in Computer Science, 2025\n"
        "Projects: Built automated distributed placement pipelines.\n"
    )
    resp = client.post(
        "/api/resume/parse-sections",
        data={
            "resume_text": valid_text
        }
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data
    assert "sections" in data["data"]
    assert "name" in data["data"]["sections"]
