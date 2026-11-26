"""
Tests for Rule-Based Basic Analysis Fallback on AI Failure (#849).
=================================================================
Verifies acceptance criteria:
1. An AI failure produces a labelled basic analysis instead of an error page.
2. The basic result is never cached as a full analysis.
3. The normal path is unchanged.
4. Tests simulate AI errors (rate limit, service unavailable, auth error) and check the labelled fallback.
"""

import pytest
from app import app
from agents.coordinator import CoordinatorAgent
from utils.gemini import (
    AIRateLimitError,
    AIServiceUnavailableError,
    AIAuthError,
    AITimeoutError,
)
from utils.basic_analysis_fallback import (
    BASIC_ANALYSIS_LABEL,
    generate_basic_fallback_analysis,
)
from utils.analysis_cache import (
    compute_analysis_hash,
    get_cached_analysis,
    set_cached_analysis,
)
from utils.database import get_analysis


SAMPLE_RESUME = """
Alex Chen
San Francisco, CA | (555) 019-2834 | alex.chen@example.com | github.com/alexchen | linkedin.com/in/alexchen

Professional Summary
Computer Science undergraduate with 2 years of practical software engineering experience
specializing in Python, backend development, REST APIs, and relational databases.

Technical Skills
Languages: Python, JavaScript, SQL, C++
Frameworks & Tools: Flask, FastAPI, Docker, Git, PostgreSQL, Redis

Work Experience
Software Engineering Intern - CloudTech Solutions (June 2025 - August 2025)
- Developed and optimized RESTful microservices in Python, improving reporting pipeline throughput by 25%.
- Implemented PostgreSQL database indexing and query caching with Redis, reducing p99 query latency by 40ms.
- Containerized development workflows using Docker, accelerating local setup for 12 engineers.

Projects & Portfolio
Distributed Task Queue (Python, Redis, Docker)
- Architected asynchronous background workers processing 5,000+ jobs per minute with priority scheduling.
- Implemented exponential backoff retries and dead-letter queue handling, cutting job dropouts by 40%.

Education
B.S. in Computer Science, University of California, Berkeley (Graduation: May 2026)
GPA: 3.8 / 4.0 | Relevant Coursework: Data Structures, Algorithms, Operating Systems, Database Systems
"""

SAMPLE_JD = """
Software Engineer - Campus Graduate
We are looking for an engineer proficient in Python, SQL, REST APIs, and Docker.
Knowledge of Kubernetes and CI/CD pipelines is a plus.
"""


def test_generate_basic_fallback_analysis_structure():
    """Verify the shape, labels, and rule-based computations of generate_basic_fallback_analysis."""
    result = generate_basic_fallback_analysis(
        resume_text=SAMPLE_RESUME,
        job_description=SAMPLE_JD,
        company_name="Google",
        error_reason="Rate limit exceeded (429)",
    )

    # 1. Labels
    assert result["is_basic_analysis"] is True
    assert result["ai_unavailable"] is True
    assert result["analysis_label"] == BASIC_ANALYSIS_LABEL
    assert result["analysis_mode"] == "basic_fallback"
    assert "Rate limit" in result["fallback_reason"]

    # 2. Section completeness & ATS score
    ra = result["resume_analysis"]
    assert ra["ats_score"] > 0
    assert isinstance(ra["strengths"], list)
    assert len(ra["strengths"]) > 0
    assert isinstance(ra["areas_of_improvement"], list)
    assert BASIC_ANALYSIS_LABEL.lower() in ra["overall_feedback"].lower()

    # 3. Keyword and skill overlap with JD
    jm = result["job_match"]
    assert jm["match_percentage"] > 0
    # Python, SQL, REST APIs, Docker are in both resume and JD
    matched = [s.lower() for s in jm["matched_skills"]]
    assert any("python" in s for s in matched)
    # Missing skills like kubernetes or ci/cd
    missing = [s.lower() for s in jm["missing_skills"]]
    assert any("k8s" in s or "kubernetes" in s or "ci/cd" in s for s in missing)

    # 4. Format compatibility
    assert "format_compatibility" in result
    assert "checks" in result["format_compatibility"]

    # 5. Skill gap and roadmap
    assert len(result["skill_gap"]) > 0
    assert len(result["learning_roadmap"]) == 6
    assert len(result["interview_questions"]["technical"]) >= 3


def test_basic_fallback_without_job_description_uses_role_template():
    """Verify that when no JD is provided, the fallback uses standard role templates."""
    result = generate_basic_fallback_analysis(
        resume_text=SAMPLE_RESUME,
        job_description="",
        company_name="Amazon",
        error_reason="Service 503 unavailable",
    )

    assert result["is_basic_analysis"] is True
    assert result["job_match"]["match_percentage"] > 0
    assert len(result["job_match"]["matched_skills"]) > 0


def test_analyze_route_rate_limit_produces_labelled_basic_analysis(monkeypatch):
    """Simulate AIRateLimitError and verify student receives labelled basic analysis, not error page."""
    def mock_fail(*args, **kwargs):
        raise AIRateLimitError("Resource exhausted: quota exceeded")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_fail)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post(
            "/analyze",
            data={
                "resume_text": SAMPLE_RESUME,
                "job_description": SAMPLE_JD,
                "company": "Google",
            },
            follow_redirects=True,
        )

        assert res.status_code == 200
        html = res.data.decode("utf-8").lower()

        # Acceptance Criteria 1: Labelled basic analysis instead of error page
        assert BASIC_ANALYSIS_LABEL.lower() in html
        assert "rule-based placement evaluation" in html
        assert "re-run with ai" in html
        # Should not display the index error page
        assert "upload your resume" not in html or "dashboard" in html


def test_analyze_route_service_unavailable_produces_labelled_basic_analysis(monkeypatch):
    """Simulate AIServiceUnavailableError (500/503) and verify labelled fallback is generated."""
    def mock_fail(*args, **kwargs):
        raise AIServiceUnavailableError("Model backend overloaded (503)")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_fail)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post(
            "/analyze",
            data={
                "resume_text": SAMPLE_RESUME,
                "job_description": SAMPLE_JD,
                "company": "Microsoft",
            },
            follow_redirects=True,
        )

        assert res.status_code == 200
        html = res.data.decode("utf-8").lower()
        assert BASIC_ANALYSIS_LABEL.lower() in html
        assert "re-run with ai" in html


def test_basic_result_is_never_cached_as_full_analysis(monkeypatch):
    """
    Acceptance Criteria 2: The basic result is never cached as a full analysis.
    Verifies that cache lookup returns None after a basic fallback run.
    """
    def mock_fail(*args, **kwargs):
        raise AIRateLimitError("Quota limit hit")

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_fail)

    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post(
            "/analyze",
            data={
                "resume_text": SAMPLE_RESUME,
                "job_description": SAMPLE_JD,
                "company": "Amazon",
            },
            follow_redirects=True,
        )
        assert res.status_code == 200

        # Compute hash of the inputs
        input_hash = compute_analysis_hash(
            resume_text=SAMPLE_RESUME,
            job_description=SAMPLE_JD,
            company_name="Amazon",
        )

        # Cache must NOT contain this input_hash
        cached_record = get_cached_analysis(input_hash)
        assert cached_record is None, "Basic fallback analysis must never be stored in cache as full result"


def test_explicit_set_cached_analysis_rejects_basic_analysis():
    """Verify that set_cached_analysis refuses to store an analysis marked as basic fallback."""
    from utils.database import save_analysis
    import uuid

    fake_id = str(uuid.uuid4())
    save_analysis(
        analysis_id=fake_id,
        resume_filename="test_resume.pdf",
        company_name="General",
        job_description="Sample JD",
        results_dict={
            "is_basic_analysis": True,
            "ai_unavailable": True,
            "analysis_label": BASIC_ANALYSIS_LABEL,
            "resume_analysis": {"ats_score": 70},
        },
        student_id="test_student",
    )

    test_hash = "fake_test_hash_12345"
    set_cached_analysis(
        input_hash=test_hash,
        analysis_id=fake_id,
        student_id="test_student",
    )

    # get_cached_analysis must return None
    cached = get_cached_analysis(test_hash, student_id="test_student")
    assert cached is None, "set_cached_analysis must not cache an analysis with is_basic_analysis=True"


def test_normal_path_is_unchanged(monkeypatch):
    """
    Acceptance Criteria 3: The normal path is unchanged when AI succeeds.
    Verifies full analysis is produced, not labelled as basic fallback, and is cached.
    """
    mock_payload = {
        "resume_analysis": {
            "ats_score": 85,
            "overall_feedback": "Excellent candidate with strong technical foundations.",
            "strengths": ["Strong backend experience", "Docker mastery"],
            "areas_of_improvement": ["Add more cloud metrics"],
            "keywords_found": ["Python", "Docker"],
            "keywords_missing": ["Kubernetes"],
        },
        "job_match": {
            "match_percentage": 88,
            "matched_skills": ["Python", "Docker", "SQL"],
            "missing_skills": ["Kubernetes"],
            "hiring_criteria": "Campus hiring bar satisfied.",
            "recommendation": "Ready for technical interview.",
        },
        "skill_gap": [
            {
                "skill": "Kubernetes",
                "priority": "High",
                "reason": "Crucial container orchestration skill",
                "suggested_project": "Deploy microservice on K8s",
            }
        ],
        "learning_roadmap": [
            {"week": i, "focus": f"Week {i} Plan", "tasks": [f"Task {i}"]}
            for i in range(1, 7)
        ],
        "interview_questions": {
            "hr": ["Tell me about yourself"],
            "technical": ["Explain Python GIL"],
            "behavioral": ["Tell me about a team conflict"],
        },
        "overall_recommendation_summary": "Highly recommended for campus interview.",
    }

    def mock_success(*args, **kwargs):
        return mock_payload

    monkeypatch.setattr(CoordinatorAgent, "analyze", mock_success)

    unique_company = "NormalPathUnchangedCorp"
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post(
            "/analyze",
            data={
                "resume_text": SAMPLE_RESUME,
                "job_description": SAMPLE_JD,
                "company": unique_company,
            },
            follow_redirects=True,
        )

        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Normal path should NOT show basic analysis fallback banner
        assert BASIC_ANALYSIS_LABEL not in html.lower()

        # Cache SHOULD be populated for the normal path
        norm_hash = compute_analysis_hash(
            resume_text=SAMPLE_RESUME,
            job_description=SAMPLE_JD,
            company_name=unique_company,
        )
        cached = get_cached_analysis(norm_hash)
        assert cached is not None, "Normal path must cache analysis results"
        assert cached["results"]["resume_analysis"]["ats_score"] == 85
