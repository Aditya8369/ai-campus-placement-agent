"""
Comprehensive automated tests for Timeline-Driven Learning Roadmap for Missing Skills (#536).

Acceptance Criteria:
1. The plan length matches the chosen number of weeks.
2. Every missing skill appears in the plan or is marked as deferred.
3. Zero missing skills shows a congratulatory message instead of an empty plan.
4. Missing skills are ordered by prerequisites and importance.
5. Each week outputs topics, one small practice task, and types of free resources.
"""

import json
import tempfile
from pathlib import Path
import pytest

import config
from app import app
from utils.database import init_db, save_analysis
from agents.roadmap_agent import (
    RoadmapAgent,
    generate_learning_roadmap,
    roadmap_agent,
)


@pytest.fixture
def test_client(monkeypatch):
    """Provides a Flask test client with an isolated SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        monkeypatch.setattr(config, "UPLOAD_FOLDER", Path(tmpdir) / "uploads")
        monkeypatch.setattr(config, "REPORT_FOLDER", Path(tmpdir) / "reports")
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        config.REPORT_FOLDER.mkdir(parents=True, exist_ok=True)
        init_db()

        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client


# -------------------------------------------------------------------------
# Unit Tests: Roadmap Agent Core Scheduling & Prerequisite Logic
# -------------------------------------------------------------------------

def test_plan_length_matches_chosen_weeks():
    """Acceptance criterion: The plan length matches the chosen number of weeks."""
    skills = ["Python", "SQL", "Docker", "Git", "REST APIs", "React"]

    for chosen_weeks in [2, 4, 6, 8, 12]:
        result = generate_learning_roadmap(
            missing_skills=skills,
            weeks=chosen_weeks,
            hours_per_week=10
        )
        assert result["success"] is True
        assert len(result["plan"]) == chosen_weeks, (
            f"Expected {chosen_weeks} weeks in plan, got {len(result['plan'])}"
        )
        assert result["weeks"] == chosen_weeks
        # Verify sequential week naming
        for i, week in enumerate(result["plan"], start=1):
            assert week["week"] == f"Week {i}"
            assert week["week_number"] == i


def test_every_missing_skill_scheduled_or_deferred():
    """
    Acceptance criterion: Every missing skill appears in the plan or is marked as deferred.
    When skills exceed chosen weeks timeline capacity, remaining skills are explicitly deferred.
    """
    all_skills = ["Linux", "Docker", "Kubernetes", "Python", "FastAPI", "SQL", "PostgreSQL", "Redis"]
    chosen_weeks = 4

    result = generate_learning_roadmap(
        missing_skills=all_skills,
        weeks=chosen_weeks,
        hours_per_week=10
    )

    assert result["success"] is True
    assert len(result["plan"]) == chosen_weeks

    # Collect all skills scheduled across plan weeks
    scheduled_skill_names = set()
    for week in result["plan"]:
        for s in week["skills"]:
            scheduled_skill_names.add(s.lower())

    # Collect all deferred skill names
    deferred_skill_names = set(d["skill"].lower() for d in result["deferred_skills"])

    # Every input skill must either be scheduled or deferred
    for orig in all_skills:
        assert (orig.lower() in scheduled_skill_names or orig.lower() in deferred_skill_names), (
            f"Skill '{orig}' was neither scheduled in the plan nor marked as deferred!"
        )

    # Deferred count + scheduled count matches total skills
    assert result["scheduled_count"] + result["deferred_count"] == len(all_skills)
    assert len(result["deferred_skills"]) > 0

    # Verify deferred reasons are clear and helpful
    for def_item in result["deferred_skills"]:
        assert "deferred" in def_item["reason"].lower()
        assert str(chosen_weeks) in def_item["reason"]


def test_zero_missing_skills_shows_congratulatory_message():
    """
    Acceptance criterion: Zero missing skills shows a congratulatory message
    instead of an empty plan.
    """
    # Empty list
    result = generate_learning_roadmap(missing_skills=[], weeks=6, hours_per_week=10)
    assert result["success"] is True
    assert result["is_zero_missing"] is True
    assert result["plan"] == []
    assert result["deferred_skills"] == []
    assert result["congratulatory_message"] is not None
    assert "congratulations" in result["congratulatory_message"].lower()
    assert "zero missing skills" in result["congratulatory_message"].lower()

    # None input
    result_none = generate_learning_roadmap(missing_skills=None, weeks=4, hours_per_week=15)
    assert result_none["is_zero_missing"] is True
    assert "congratulations" in result_none["congratulatory_message"].lower()


def test_order_skills_by_prerequisites_and_importance():
    """
    Proposed work: Order missing skills by importance and prerequisites.
    Verifies that prerequisites are scheduled strictly before dependent skills.
    """
    # 1. Linux -> Docker -> Kubernetes
    res_k8s = generate_learning_roadmap(
        missing_skills=["Kubernetes", "Docker", "Linux"],
        weeks=3,
        hours_per_week=10
    )
    scheduled_k8s = [w["skills"][0].lower() for w in res_k8s["plan"]]
    assert scheduled_k8s.index("linux") < scheduled_k8s.index("docker")
    assert scheduled_k8s.index("docker") < scheduled_k8s.index("kubernetes")

    # 2. Python -> FastAPI
    res_py = generate_learning_roadmap(
        missing_skills=["FastAPI", "Python"],
        weeks=2,
        hours_per_week=10
    )
    scheduled_py = [w["skills"][0].lower() for w in res_py["plan"]]
    assert scheduled_py.index("python") < scheduled_py.index("fastapi")

    # 3. JavaScript -> React
    res_react = generate_learning_roadmap(
        missing_skills=["React", "JavaScript"],
        weeks=2,
        hours_per_week=10
    )
    scheduled_react = [w["skills"][0].lower() for w in res_react["plan"]]
    assert scheduled_react.index("javascript") < scheduled_react.index("react")


def test_week_has_topics_single_practice_task_and_resource_types():
    """
    Proposed work:
    - Output a week-by-week plan with topics and one small practice task per week
    - Suggest types of free resources rather than unverified links
    """
    result = generate_learning_roadmap(
        missing_skills=["Docker", "SQL"],
        weeks=2,
        hours_per_week=10
    )

    for week in result["plan"]:
        # Topics
        assert isinstance(week["topics"], list)
        assert len(week["topics"]) >= 2
        for t in week["topics"]:
            assert isinstance(t, str) and len(t) > 5

        # Exactly one small practice task
        assert "practice_task" in week
        assert isinstance(week["practice_task"], str)
        assert len(week["practice_task"]) > 10

        # Suggested types of free resources (not unverified URLs)
        assert isinstance(week["resource_types"], list)
        assert len(week["resource_types"]) >= 2
        for rt in week["resource_types"]:
            assert isinstance(rt, str)
            # Ensure it describes types of free resources (e.g. Official Documentation, Playgrounds)
            assert not rt.startswith("http://") and not rt.startswith("https://")


# -------------------------------------------------------------------------
# Integration Tests: REST API Endpoints
# -------------------------------------------------------------------------

def test_api_analysis_custom_roadmap(test_client):
    """POST /api/analysis/<analysis_id>/custom-roadmap calculates timeline plan from analysis."""
    analysis_record = {
        "analysis_id": "test-roadmap-536-1",
        "company_name": "Google",
        "job_description": "We need a Software Engineer proficient in Docker, Linux, and PostgreSQL.",
        "resume_filename": "candidate.pdf",
        "results": {
            "job_match": {
                "matched_skills": ["Python", "Git"],
                "missing_skills": ["Linux", "Docker", "PostgreSQL"]
            },
            "skill_gap": [
                {"skill": "Linux", "importance": "High"},
                {"skill": "Docker", "importance": "High"},
                {"skill": "PostgreSQL", "importance": "Medium"}
            ]
        }
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"]
    )

    resp = test_client.post(
        "/api/analysis/test-roadmap-536-1/custom-roadmap",
        data=json.dumps({"weeks": 3, "hours_per_week": 15}),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["weeks"] == 3
    assert data["hours_per_week"] == 15
    assert len(data["plan"]) == 3
    assert data["is_zero_missing"] is False

    # Check each week has 1 small practice task and resource types
    for w in data["plan"]:
        assert "practice_task" in w
        assert len(w["resource_types"]) >= 1


def test_api_analysis_custom_roadmap_zero_missing(test_client):
    """POST /api/analysis/<analysis_id>/custom-roadmap shows congratulations when 0 missing skills."""
    analysis_record = {
        "analysis_id": "test-roadmap-zero-gaps",
        "company_name": "Stripe",
        "job_description": "Python Developer",
        "resume_filename": "cv.pdf",
        "results": {
            "job_match": {
                "matched_skills": ["Python", "Flask", "SQL"],
                "missing_skills": []
            },
            "skill_gap": []
        }
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"]
    )

    resp = test_client.post(
        "/api/analysis/test-roadmap-zero-gaps/custom-roadmap",
        data=json.dumps({"weeks": 4, "hours_per_week": 10}),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["is_zero_missing"] is True
    assert data["plan"] == []
    assert "congratulations" in data["congratulatory_message"].lower()


def test_api_roadmap_generate_standalone(test_client):
    """POST /api/roadmap/generate directly computes roadmap without analysis ID."""
    resp = test_client.post(
        "/api/roadmap/generate",
        data=json.dumps({
            "missing_skills": ["Git", "CI/CD", "Docker", "Kubernetes"],
            "weeks": 2,
            "hours_per_week": 10
        }),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["plan"]) == 2
    assert len(data["deferred_skills"]) >= 1
    assert data["scheduled_count"] + data["deferred_count"] == 4


def test_dashboard_renders_timeline_customizer_controls(test_client):
    """GET /dashboard/<analysis_id> renders timeline customizer controls and roadmap structure."""
    analysis_record = {
        "analysis_id": "test-dash-timeline-536",
        "company_name": "Microsoft",
        "job_description": "Cloud Engineer",
        "resume_filename": "candidate.pdf",
        "results": {
            "job_match": {
                "matched_skills": ["Python"],
                "missing_skills": ["Docker", "Linux"]
            },
            "skill_gap": [
                {"skill": "Docker", "importance": "High"},
                {"skill": "Linux", "importance": "High"}
            ]
        }
    }
    save_analysis(
        analysis_id=analysis_record["analysis_id"],
        resume_filename=analysis_record["resume_filename"],
        company_name=analysis_record["company_name"],
        job_description=analysis_record["job_description"],
        results_dict=analysis_record["results"]
    )

    resp = test_client.get("/dashboard/test-dash-timeline-536")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Timeline customizer controls
    assert "roadmapWeeksSelect" in html
    assert "roadmapHoursSelect" in html
    assert "btnRecalculateRoadmap" in html
    assert "zeroMissingSkillsBanner" in html
    assert "deferredSkillsContainer" in html
    assert "customRoadmapTimeline" in html
