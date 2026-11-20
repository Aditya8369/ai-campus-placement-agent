"""
Unit and Integration Tests for 'What if I learn this skill?' Simulator (#557)
=============================================================================
Tests:
- Empty missing skills list
- Nothing ticked: results strictly consistent with original analysis
- Single skill ticked
- Several skills ticked
- Ranking by individual contribution and best next skill highlight
- Case-insensitivity and whitespace normalization
- Disclaimer regarding pasted job description estimate
- REST API endpoint POST /api/skill-gap/simulate
- Web dashboard view rendering of simulator card and table checkboxes
"""

from pathlib import Path
import tempfile
import uuid

import pytest

import config
from app import app
from utils.database import init_db, save_analysis
from utils.skill_impact_simulator import (
    SIMULATION_DISCLAIMER,
    get_skill_simulation_data,
    simulate_job_match,
)


@pytest.fixture
def client(monkeypatch):
    """Test client configured with an isolated database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(config, "DATABASE_PATH", str(Path(tmpdir) / "sim_test.db"))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()
        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as test_client:
            yield test_client


# ==============================================================================
# UNIT TESTS: ENGINE & RECALCULATION
# ==============================================================================

def test_empty_missing_skills_list():
    """Acceptance criteria: unit tests cover an empty list."""
    matched = ["Python", "SQL", "Git"]
    missing = []

    res = simulate_job_match(
        matched_skills=matched,
        missing_skills=missing,
        ticked_skills=[],
        original_percentage=100,
    )

    assert res["original_percentage"] == 100
    assert res["simulated_percentage"] == 100
    assert res["percentage_change"] == 0
    assert res["percentage_change_str"] == "0%"
    assert res["ticked_count"] == 0
    assert res["total_missing_count"] == 0
    assert res["ranked_skills"] == []
    assert res["best_next_skill"] is None
    assert res["has_missing_skills"] is False
    assert res["disclaimer"] == SIMULATION_DISCLAIMER


def test_nothing_ticked_consistent_with_original():
    """
    Acceptance criteria: Results are strictly consistent with the original
    analysis when nothing is ticked.
    """
    matched = ["Python", "Django"]
    missing = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "Kubernetes", "importance": "Medium"},
    ]

    res = simulate_job_match(
        matched_skills=matched,
        missing_skills=missing,
        ticked_skills=[],
        original_percentage=65,
    )

    # Simulated percentage must exactly match original percentage
    assert res["original_percentage"] == 65
    assert res["simulated_percentage"] == 65
    assert res["percentage_change"] == 0
    assert res["percentage_change_str"] == "0%"
    assert res["ticked_count"] == 0
    assert res["total_missing_count"] == 2
    assert len(res["ranked_skills"]) == 2
    assert res["has_missing_skills"] is True


def test_single_skill_ticked():
    """Acceptance criteria: unit tests cover single skill."""
    matched = ["Python", "SQL"]
    missing = [
        {"skill": "Docker", "importance": "High", "priority": "High"},
        {"skill": "Redis", "importance": "Medium", "priority": "Medium"},
    ]

    # Docker weight = 3.0, Redis weight = 2.0; total = 5.0
    # Gap = 100 - 70 = 30. Docker gain = (3/5) * 30 = +18%
    res = simulate_job_match(
        matched_skills=matched,
        missing_skills=missing,
        ticked_skills=["Docker"],
        original_percentage=70,
    )

    assert res["original_percentage"] == 70
    assert res["simulated_percentage"] == 88
    assert res["percentage_change"] == 18
    assert res["percentage_change_str"] == "+18%"
    assert res["ticked_count"] == 1
    assert res["remaining_missing_count"] == 1
    assert "Docker" in res["ticked_skills"]


def test_several_skills_ticked():
    """Acceptance criteria: unit tests cover several skills."""
    matched = ["Python"]
    missing = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "Kubernetes", "importance": "High"},
        {"skill": "Redis", "importance": "Medium"},
        {"skill": "Linux", "importance": "Low"},
    ]

    # Weights: Docker (3), K8s (3), Redis (2), Linux (1) -> Total = 9
    # Gap = 100 - 55 = 45
    # Ticked: Docker (3) + Redis (2) -> 5/9 * 45 = 25
    res = simulate_job_match(
        matched_skills=matched,
        missing_skills=missing,
        ticked_skills=["Docker", "Redis"],
        original_percentage=55,
    )

    assert res["original_percentage"] == 55
    assert res["simulated_percentage"] == 80
    assert res["percentage_change"] == 25
    assert res["percentage_change_str"] == "+25%"
    assert res["ticked_count"] == 2
    assert res["remaining_missing_count"] == 2
    assert set(res["ticked_skills"]) == {"Docker", "Redis"}


def test_all_skills_ticked_reaches_100_percent():
    """Ticking all missing skills should bridge the gap fully to 100%."""
    matched = ["Python", "SQL"]
    missing = [
        {"skill": "Docker", "importance": "High"},
        {"skill": "AWS", "importance": "Medium"},
    ]

    res = simulate_job_match(
        matched_skills=matched,
        missing_skills=missing,
        ticked_skills=["Docker", "AWS"],
        original_percentage=60,
    )

    assert res["original_percentage"] == 60
    assert res["simulated_percentage"] == 100
    assert res["percentage_change"] == 40


def test_skills_ranked_by_individual_contribution():
    """
    Acceptance criteria: Skills are ranked by contribution to the match,
    and the best next skill is highlighted.
    """
    missing = [
        {"skill": "LowSkill", "importance": "Low"},
        {"skill": "CriticalSkill", "importance": "Critical"},
        {"skill": "MediumSkill", "importance": "Medium"},
    ]

    res = simulate_job_match(
        matched_skills=["Python"],
        missing_skills=missing,
        ticked_skills=[],
        original_percentage=60,
    )

    ranked = res["ranked_skills"]
    assert len(ranked) == 3

    # Rank 1 must be CriticalSkill
    assert ranked[0]["skill"] == "CriticalSkill"
    assert ranked[0]["rank"] == 1
    assert ranked[0]["is_best_next"] is True
    assert ranked[0]["individual_gain"] > ranked[1]["individual_gain"]

    # Rank 2 must be MediumSkill
    assert ranked[1]["skill"] == "MediumSkill"
    assert ranked[1]["rank"] == 2
    assert ranked[1]["is_best_next"] is False

    # Rank 3 must be LowSkill
    assert ranked[2]["skill"] == "LowSkill"
    assert ranked[2]["rank"] == 3

    # Best next skill pointer
    assert res["best_next_skill"]["skill"] == "CriticalSkill"


def test_case_insensitivity_and_whitespace_handling():
    """Ticking skills handles casing and leading/trailing whitespace robustly."""
    missing = [{"skill": "PostgreSQL", "importance": "High"}]

    res = simulate_job_match(
        matched_skills=["Python"],
        missing_skills=missing,
        ticked_skills=["  postgresql  "],
        original_percentage=50,
    )

    assert res["ticked_count"] == 1
    assert res["simulated_percentage"] == 100
    assert res["percentage_change"] == 50


def test_get_skill_simulation_data_from_analysis_record():
    """Verifies convenience loader from standard stored analysis record."""
    analysis_record = {
        "id": "aid_test_sim",
        "results": {
            "job_match": {
                "match_percentage": 75,
                "matched_skills": ["Python", "Flask", "SQL"],
                "missing_skills": ["Docker", "Kubernetes"],
            },
            "skill_gap": [
                {
                    "skill": "Docker",
                    "importance": "High",
                    "priority": "High",
                    "learning_time": "1 week",
                    "project_suggestion": "Containerize a Flask app",
                },
                {
                    "skill": "Kubernetes",
                    "importance": "Medium",
                    "priority": "Medium",
                    "learning_time": "2 weeks",
                    "project_suggestion": "Deploy to minikube",
                },
            ],
        },
    }

    sim = get_skill_simulation_data(analysis_record, ticked_skills=["Docker"])
    assert sim["original_percentage"] == 75
    assert sim["simulated_percentage"] > 75
    assert sim["best_next_skill"]["skill"] == "Docker"
    assert sim["best_next_skill"]["project_suggestion"] == "Containerize a Flask app"


# ==============================================================================
# INTEGRATION TESTS: REST API & WEB DASHBOARD
# ==============================================================================

def test_api_simulate_custom_payload(client):
    """Verifies REST endpoint POST /api/skill-gap/simulate with custom payload."""
    payload = {
        "matched_skills": ["Java", "Spring Boot"],
        "missing_skills": [
            {"skill": "Microservices", "importance": "High"},
            {"skill": "Kafka", "importance": "Medium"},
        ],
        "ticked_skills": ["Microservices"],
        "original_percentage": 60,
    }

    res = client.post("/api/skill-gap/simulate", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    sim = data["data"]
    assert sim["original_percentage"] == 60
    assert sim["simulated_percentage"] > 60
    assert sim["ticked_count"] == 1
    assert "Microservices" in sim["ticked_skills"]


def test_api_simulate_with_analysis_id(client):
    """Verifies REST endpoint POST /api/skill-gap/simulate using stored analysis ID."""
    aid = f"aid_api_{uuid.uuid4().hex[:8]}"
    save_analysis(
        analysis_id=aid,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Backend developer with Docker experience",
        results_dict={
            "job_match": {
                "match_percentage": 70,
                "matched_skills": ["Python"],
                "missing_skills": ["Docker"],
            },
            "skill_gap": [
                {"skill": "Docker", "importance": "High", "priority": "High"}
            ],
        },
        student_id="default_student",
    )

    # 1. Nothing ticked
    res1 = client.post("/api/skill-gap/simulate", json={"analysis_id": aid, "ticked_skills": []})
    assert res1.status_code == 200
    d1 = res1.get_json()["data"]
    assert d1["original_percentage"] == 70
    assert d1["simulated_percentage"] == 70
    assert d1["percentage_change"] == 0

    # 2. Docker ticked
    res2 = client.post("/api/skill-gap/simulate", json={"analysis_id": aid, "ticked_skills": ["Docker"]})
    assert res2.status_code == 200
    d2 = res2.get_json()["data"]
    assert d2["simulated_percentage"] == 100
    assert d2["percentage_change"] == 30


def test_dashboard_renders_skill_impact_simulator(client):
    """Verifies dashboard HTML renders the simulator card, checkboxes, and disclaimer."""
    aid = f"aid_dash_{uuid.uuid4().hex[:8]}"
    save_analysis(
        analysis_id=aid,
        resume_filename="resume.pdf",
        company_name="Amazon",
        job_description="Cloud software engineer",
        results_dict={
            "resume_analysis": {"ats_score": 82},
            "job_match": {
                "match_percentage": 68,
                "matched_skills": ["Python", "SQL"],
                "missing_skills": ["Docker", "AWS"],
            },
            "skill_gap": [
                {
                    "skill": "Docker",
                    "importance": "High",
                    "priority": "High",
                    "learning_time": "1 week",
                    "learning_resource": "Docker Docs",
                    "project_suggestion": "Containerize service",
                },
                {
                    "skill": "AWS",
                    "importance": "Medium",
                    "priority": "Medium",
                    "learning_time": "2 weeks",
                    "learning_resource": "AWS Whitepapers",
                    "project_suggestion": "Deploy Lambda",
                },
            ],
        },
        student_id="default_student",
    )

    res = client.get(f"/dashboard/{aid}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Simulator card container present
    assert 'id="skillSimulatorCard"' in html
    assert "What if I learn this skill?" in html

    # 2. Before / After score metrics present
    assert 'id="simOriginalScore"' in html
    assert 'id="simProjectedScore"' in html
    assert 'id="simDeltaBadge"' in html

    # 3. Interactive checkboxes present
    assert 'sim-skill-checkbox' in html
    assert 'table-skill-checkbox' in html

    # 4. Best next skill and ranking present
    assert 'Best Next:' in html
    assert "Docker" in html

    # 5. Clear disclaimer present
    assert 'id="simDisclaimerText"' in html
    assert "estimated projection" in html
