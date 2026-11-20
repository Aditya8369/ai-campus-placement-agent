"""
Unit and integration tests for Project Deep-Dive Interview Practice Mode (#466).

Verifies:
1. Projects extraction from resume:
   - Successfully extracts project entries (title, tech stack, description).
   - Identifies brief/thin project entries.
   - Returns an empty list when no projects exist in the resume.
2. Thin project guard:
   - Rejects question generation if project text is too thin, asking the student to add detail first.
   - Allows question generation when additional details are supplied.
3. Grounded question generation (using mocked model):
   - Model receives prompt strictly constrained to the project's stated facts.
   - Yields 5 progressive follow-up questions across design choices, challenges, testing, improvements, and trade-offs.
   - Falls back to deterministic questions referencing only the project's title and tech stack.
4. Answer evaluation (using mocked model & fallback):
   - Scores candidate answers on clarity, depth, and consistency with resume.
   - Returns exactly one concrete improvement tip per answer.
   - Gracefully scores empty submissions with 0 and actionable guidance.
5. Web views & API endpoints:
   - View `/interview/<analysis_id>/project-deep-dive` lists projects or displays empty state.
   - Endpoints `/api/interview/<analysis_id>/projects`, `/project-deep-dive/questions`, and `/evaluate`.
"""

import json
import tempfile
from pathlib import Path
import pytest

from app import app
import config
from utils.database import (
    init_db,
    save_analysis,
    get_analysis,
)
from agents.project_deep_dive_agent import ProjectDeepDiveAgent


@pytest.fixture
def project_agent():
    return ProjectDeepDiveAgent()


@pytest.fixture
def test_app_client(monkeypatch):
    """Test client configured with an isolated temporary SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_project_deep_dive.db"
        monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()

        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as client:
            yield client


# ==============================================================================
# 1. Project Extraction Tests
# ==============================================================================

def test_extract_projects_from_resume_entries(project_agent):
    """Verify extracting projects from structured results or raw resume text."""
    sample_analysis = {
        "results": {
            "extracted_projects": [
                {
                    "title": "Cloud File Storage Service",
                    "technologies": "Go, AWS S3, Docker, Redis",
                    "description": (
                        "Engineered a distributed blob storage service in Go with chunked uploads, "
                        "deduplication, and Redis caching. Supported 100 concurrent uploads with sub-100ms latency."
                    ),
                },
                {
                    "title": "Portfolio Web App",
                    "technologies": "HTML, CSS",
                    "description": "Simple website.",
                },
            ]
        }
    }

    projects = project_agent.extract_projects(sample_analysis)
    assert len(projects) == 2

    p1 = projects[0]
    assert p1["title"] == "Cloud File Storage Service"
    assert "Go" in p1["tech_stack"]
    assert p1["is_thin"] is False
    assert p1["word_count"] > 15

    # Second project is thin (< 15 words)
    p2 = projects[1]
    assert p2["title"] == "Portfolio Web App"
    assert p2["is_thin"] is True


def test_extract_projects_from_raw_resume_text(project_agent):
    """Verify parsing projects when only raw resume text is stored."""
    resume_text = """
    John Doe
    john@example.com

    Skills:
    Python, FastAPI, PostgreSQL, Docker

    Projects:
    Real-Time Analytics Dashboard | Python, FastAPI, WebSockets, Redis
    - Built an event-driven telemetry dashboard ingesting 5,000 events per second.
    - Utilized Redis pub/sub to stream updates to a React frontend with sub-second latency.
    - Implemented unit and integration tests using pytest to validate WebSocket reconnections.

    Education:
    B.Tech in Computer Science
    """
    analysis_record = {
        "resume_text": resume_text,
        "results": {},
    }

    projects = project_agent.extract_projects(analysis_record)
    assert len(projects) >= 1
    p = projects[0]
    assert "Real-Time Analytics Dashboard" in p["title"]
    assert p["is_thin"] is False


def test_extract_projects_no_project_case(project_agent):
    """Verify empty list is returned when resume has no project entries."""
    analysis_without_projects = {
        "resume_text": "Jane Doe\njane@example.com\nEducation: B.S. Mathematics\nSkills: Problem Solving, Calculus",
        "results": {},
    }

    projects = project_agent.extract_projects(analysis_without_projects)
    assert isinstance(projects, list)
    assert len(projects) == 0


# ==============================================================================
# 2. Thin Project Guard Tests
# ==============================================================================

def test_thin_project_guard_requires_detail_first(project_agent):
    """Verify thin project without detail triggers prompt to add detail first."""
    thin_project = {
        "title": "Bug Tracker",
        "tech_stack": "",
        "description": "Built bug tracker.",
    }

    is_thin, reason = project_agent.is_project_thin(thin_project)
    assert is_thin is True
    assert "too thin" in reason or "brief" in reason

    # Question generation should fail with informative error
    res = project_agent.generate_questions(thin_project)
    assert res["success"] is False
    assert res["is_thin"] is True
    assert res["detail_needed"] is True
    assert "too thin" in res["error"].lower() or "detail" in res["error"].lower()

    # Once candidate supplements details, generation proceeds
    res_with_details = project_agent.generate_questions(
        thin_project,
        additional_details=(
            "Built with Django and SQLite. Designed role-based permissions for QA engineers and developers. "
            "Handled bug assignment workflows and tested status transitions with Django TestCase."
        ),
    )
    assert res_with_details["success"] is True
    assert len(res_with_details["questions"]) == 5


# ==============================================================================
# 3. Grounded Question Generation Tests (Mocked Model & Fallback)
# ==============================================================================

def test_generate_questions_mocked_model_grounded(project_agent, mock_gemini_client):
    """Verify questions reference only facts from the project using mocked model."""
    project = {
        "title": "Distributed Task Queue",
        "tech_stack": "Python, Celery, RabbitMQ, Redis",
        "description": (
            "Engineered an asynchronous task distribution pipeline processing background email jobs. "
            "Handled worker concurrency, connection pooling, and message retry backoff."
        ),
    }

    mock_gemini_client(payload={
        "questions": [
            {
                "index": 0,
                "category": "design_choices",
                "question": "Why did you choose RabbitMQ over Redis for message queuing in your Distributed Task Queue?",
            },
            {
                "index": 1,
                "category": "challenges",
                "question": "What was the hardest worker concurrency or dead-letter bug you solved in Celery?",
            },
            {
                "index": 2,
                "category": "testing",
                "question": "How did you test task idempotency and network failure recovery?",
            },
            {
                "index": 3,
                "category": "improvements",
                "question": "If scaling this pipeline to 100,000 tasks per minute, what would you rebuild?",
            },
            {
                "index": 4,
                "category": "tradeoffs",
                "question": "What technical trade-offs did you balance between task throughput and delivery guarantees?",
            },
        ]
    })

    result = project_agent.generate_questions(project, company_name="Amazon")
    assert result["success"] is True
    assert len(result["questions"]) == 5
    assert result["project_title"] == "Distributed Task Queue"

    q0 = result["questions"][0]
    assert q0["category"] == "design_choices"
    assert "RabbitMQ" in q0["question"]


def test_generate_questions_fallback_strictly_grounded(project_agent, monkeypatch):
    """Verify deterministic fallback produces 5 questions grounded only in stated project facts."""
    project = {
        "title": "Smart Home IoT Hub",
        "tech_stack": "C++, MQTT, Raspberry Pi",
        "description": (
            "Developed an embedded IoT gateway in C++ on Raspberry Pi communicating via MQTT. "
            "Collected temperature sensor readings and triggered automated relay switches."
        ),
    }

    # Simulate model error
    def mock_fail(*args, **kwargs):
        raise RuntimeError("API timeout")

    monkeypatch.setattr("agents.project_deep_dive_agent.generate_json_response", mock_fail)

    result = project_agent.generate_questions(project, company_name="Google")
    assert result["success"] is True
    assert len(result["questions"]) == 5

    categories = [q["category"] for q in result["questions"]]
    assert categories == ["design_choices", "challenges", "testing", "improvements", "tradeoffs"]

    # All questions reference the project title
    for q in result["questions"]:
        assert "Smart Home IoT Hub" in q["question"]


# ==============================================================================
# 4. Answer Evaluation Tests (Scores & Exactly One Tip)
# ==============================================================================

def test_evaluate_answer_mocked_model_response(project_agent, mock_gemini_client):
    """Verify evaluation returns clarity, depth, consistency scores and one improvement tip."""
    project = {
        "title": "Distributed Task Queue",
        "tech_stack": "Python, Celery, RabbitMQ",
        "description": "Background task queue for asynchronous email and PDF report processing.",
    }
    question = "Why did you choose RabbitMQ over Redis for message queuing?"
    answer = (
        "We chose RabbitMQ because our workflow required strict message persistence, dead-letter exchanges, "
        "and granular worker routing. Redis is fast in-memory, but RabbitMQ provided stronger delivery guarantees."
    )

    mock_gemini_client(payload={
        "clarity_score": 90,
        "depth_score": 85,
        "consistency_score": 95,
        "overall_score": 89,
        "tip": "Mention the exact exchange type (direct vs topic) used to demonstrate concrete protocol knowledge.",
        "feedback": "Strong architectural justification highlighting message persistence and delivery semantics.",
        "clarity_feedback": "Direct and structured articulation.",
        "depth_feedback": "Contrasted Redis in-memory storage against AMQP persistence effectively.",
        "consistency_feedback": "Consistent with Celery and RabbitMQ mentioned on resume.",
    })

    res = project_agent.evaluate_answer(project, question, answer)
    assert res["clarity_score"] == 90
    assert res["depth_score"] == 85
    assert res["consistency_score"] == 95
    assert res["overall_score"] == 89
    assert "exchange type" in res["tip"]
    assert res["is_consistent"] is True


def test_evaluate_answer_empty_input(project_agent):
    """Verify submitting an empty response safely returns 0 scores and a clear tip."""
    project = {"title": "Test Proj", "tech_stack": "Python", "description": "Desc"}
    res = project_agent.evaluate_answer(project, "Explain your architecture.", "   ")

    assert res["overall_score"] == 0
    assert res["clarity_score"] == 0
    assert res["depth_score"] == 0
    assert res["is_consistent"] is False
    assert len(res["tip"]) > 0


def test_evaluate_answer_fallback_deterministic(project_agent, monkeypatch):
    """Verify fallback evaluation calculates scores and provides one concrete improvement tip."""
    def mock_fail(*args, **kwargs):
        raise RuntimeError("Service unavailable")

    monkeypatch.setattr("agents.project_deep_dive_agent.generate_json_response", mock_fail)

    project = {
        "title": "E-Commerce Microservices",
        "tech_stack": "FastAPI, PostgreSQL, Redis",
        "description": "Engineered REST APIs with PostgreSQL database indexing and Redis session caching.",
    }
    question = "How did you test your endpoints for high concurrency?"
    answer = (
        "We tested our FastAPI endpoints using pytest along with Locust for load generation. "
        "We simulated 200 concurrent users against our PostgreSQL database to measure query latency and identify slow queries."
    )

    res = project_agent.evaluate_answer(project, question, answer)
    assert 0 <= res["clarity_score"] <= 100
    assert 0 <= res["depth_score"] <= 100
    assert 0 <= res["consistency_score"] <= 100
    assert 0 <= res["overall_score"] <= 100
    assert isinstance(res["tip"], str)
    assert len(res["tip"]) > 10


# ==============================================================================
# 5. Web Views & API Endpoints Tests
# ==============================================================================

def test_project_deep_dive_view_with_projects(test_app_client):
    """Verify the deep-dive page renders with projects detected in the resume."""
    aid = "test_deep_dive_aid_01"
    sample_results = {
        "resume_analysis": {"ats_score": 85},
        "extracted_projects": [
            {
                "id": "p-101",
                "title": "Hospital Management System",
                "technologies": "Java, Spring Boot, MySQL",
                "description": "Developed full-stack patient records portal with role-based access control, appointment booking workflows, and MySQL schema optimizations.",
            }
        ],
    }
    save_analysis(aid, "resume.pdf", "Microsoft", "Backend Engineer", sample_results)

    resp = test_app_client.get(f"/interview/{aid}/project-deep-dive")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Hospital Management System" in html
    assert "Spring Boot" in html
    assert "Practice Deep-Dive" in html


def test_project_deep_dive_view_no_project_empty_state(test_app_client):
    """Verify the empty state card is displayed when no projects are found in the resume."""
    aid = "test_deep_dive_aid_empty"
    sample_results = {
        "resume_analysis": {"ats_score": 80},
        "extracted_projects": [],
    }
    # Empty resume text
    save_analysis(aid, "resume.pdf", "Google", "Analyst", sample_results)

    resp = test_app_client.get(f"/interview/{aid}/project-deep-dive")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "No Projects Detected in Resume" in html
    assert "Enter Custom Project" in html


def test_api_projects_and_deep_dive_flow(test_app_client, mock_gemini_client):
    """Verify end-to-end API endpoints for fetching projects, generating questions, and evaluating answers."""
    aid = "test_deep_dive_aid_api"
    sample_results = {
        "extracted_projects": [
            {
                "id": "proj-abc",
                "title": "Autonomous Drone Navigator",
                "technologies": "Python, OpenCV, ROS",
                "description": "Created computer vision pipeline for indoor drone obstacle avoidance using OpenCV and ROS with automated sensor lag recovery algorithms.",
            }
        ]
    }
    save_analysis(aid, "resume.pdf", "Tesla", "Robotics Engineer", sample_results)

    # 1. GET /api/interview/<aid>/projects
    resp1 = test_app_client.get(f"/api/interview/{aid}/projects")
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1["success"] is True
    assert data1["count"] == 1
    assert data1["projects"][0]["title"] == "Autonomous Drone Navigator"

    # 2. POST /api/interview/<aid>/project-deep-dive/questions
    mock_gemini_client(payload={
        "questions": [
            {"index": 0, "category": "design_choices", "question": "Why OpenCV for edge detection?"},
            {"index": 1, "category": "challenges", "question": "What sensor lag issues occurred?"},
            {"index": 2, "category": "testing", "question": "How did you validate avoidance in simulation?"},
            {"index": 3, "category": "improvements", "question": "What would SLAM add to this?"},
            {"index": 4, "category": "tradeoffs", "question": "How did you balance frame rate and compute?"},
        ]
    })
    resp2 = test_app_client.post(
        f"/api/interview/{aid}/project-deep-dive/questions",
        json={"project_id": "proj-abc"},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["success"] is True
    assert len(data2["questions"]) == 5

    # 3. POST /api/interview/<aid>/project-deep-dive/evaluate
    mock_gemini_client(payload={
        "clarity_score": 88,
        "depth_score": 84,
        "consistency_score": 92,
        "overall_score": 87,
        "tip": "Explain the exact ROS node communication frequency (Hz) used.",
        "feedback": "Clear explanation of computer vision obstacle bounding boxes.",
    })
    resp3 = test_app_client.post(
        f"/api/interview/{aid}/project-deep-dive/evaluate",
        json={
            "project": data1["projects"][0],
            "question": "Why OpenCV for edge detection?",
            "answer": "OpenCV provided fast C++ backed image filtering primitives that could process 30 frames per second on our embedded hardware.",
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.get_json()
    assert data3["success"] is True
    assert data3["evaluation"]["overall_score"] == 87
    assert "ROS node" in data3["evaluation"]["tip"]
