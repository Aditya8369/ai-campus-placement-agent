import pytest
from app import app
from utils.resume_section_validator import ResumeSectionValidator, resume_section_validator


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_validate_complete_resume():
    validator = ResumeSectionValidator()
    full_resume = """
    John Doe
    Email: john.doe@example.com | Phone: +1-555-123-4567 | LinkedIn: linkedin.com/in/johndoe
    
    Education:
    Bachelor of Technology in Computer Science, State University, CGPA: 8.9 (Graduation: 2026)
    
    Technical Skills:
    Python, Java, JavaScript, React, Flask, PostgreSQL, Docker, Git
    
    Projects:
    Campus Placement Preparation Agent: Developed full-stack web application with AI resume scoring and interview prep.
    Automated Test Runner: Architected a distributed testing framework.
    
    Experience:
    Software Engineer Intern at Tech Corp: Implemented backend microservices and optimized query latencies by 30%.

    Certifications & Achievements:
    AWS Certified Cloud Practitioner, LeetCode 300+ problems solved, Hackathon 1st place winner.
    """
    res = validator.validate_sections(full_resume)
    assert res["completeness_score"] == 100
    assert res["status"] == "Strong"
    assert len(res["missing_sections"]) == 0
    assert len(res["warnings"]) == 0
    assert res["sections"]["education"]["present"] is True
    assert res["sections"]["skills"]["present"] is True
    assert res["sections"]["projects"]["present"] is True
    assert res["sections"]["experience"]["present"] is True
    assert res["sections"]["contact"]["present"] is True
    assert res["sections"]["certifications"]["present"] is True
    assert "detected_keywords" in res


def test_validate_partial_resume_missing_projects_and_experience():
    validator = ResumeSectionValidator()
    partial_resume = """
    Jane Smith
    Email: jane.smith@university.edu
    
    Education:
    Bachelor of Science in Information Technology, City College
    
    Skills:
    C++, Python, SQL
    """
    res = validator.validate_sections(partial_resume)
    assert res["completeness_score"] < 100
    assert "projects" in res["missing_sections"]
    assert "experience" in res["missing_sections"]
    assert any("Projects" in w for w in res["warnings"])
    assert any("Projects" in r for r in res["recommendations"])


def test_extract_detected_keywords():
    validator = ResumeSectionValidator()
    text = "Contact: test@domain.com, Education: Bachelor University, Skills: Python Docker, Projects: Developed system."
    kw = validator.extract_detected_keywords(text)
    assert "test@domain.com" in kw["contact"]
    assert "bachelor" in kw["education"]
    assert "python" in kw["skills"]
    assert "developed" in kw["projects"]


def test_validate_empty_resume():
    validator = ResumeSectionValidator()
    res = validator.validate_sections("")
    assert res["completeness_score"] == 0
    assert res["status"] == "Incomplete"
    assert len(res["missing_sections"]) == 6
    assert len(res["warnings"]) > 0


def test_api_validate_sections_endpoint_success(client):
    res = client.post("/api/resume/validate-sections", json={
        "resume_text": "Email: user@example.com. Education: B.Tech University. Skills: Python, SQL. Projects: Built web app."
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "completeness" in data
    assert data["completeness"]["completeness_score"] >= 80


def test_api_validate_sections_endpoint_missing_body(client):
    res = client.post("/api/resume/validate-sections", json={
        "resume_text": ""
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "error" in data
