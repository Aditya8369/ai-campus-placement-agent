"""
Unit and integration tests for Interview Question Difficulty Selection (#266).
Verifies:
- Difficulty normalization and validation (Beginner, Intermediate, Advanced, fallback).
- Scaling of generated questions according to requested difficulty tier.
- Difficulty metadata retrieval (badges, descriptions, icons).
- Passing difficulty parameter to /interview/<id> persists and scopes the session questions.
- API endpoints /api/interview/difficulty/options and /api/interview/difficulty/generate.
"""

import json
import pytest
from app import app
import config
from utils.database import init_db, save_analysis, get_interview_session
from utils.interview_difficulty_service import (
    DIFFICULTY_BEGINNER,
    DIFFICULTY_INTERMEDIATE,
    DIFFICULTY_ADVANCED,
    normalize_difficulty,
    get_difficulty_metadata,
    generate_difficulty_interview_questions,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_diff_sel.db")
    monkeypatch.setattr(config, "DATABASE_PATH", test_db)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    save_analysis(
        analysis_id="analysis_diff_test",
        resume_filename="resume.pdf",
        company_name="Microsoft",
        job_description="Cloud & Distributed Systems Software Engineer",
        results_dict={
            "match_score": 85,
            "interview_questions": {
                "technical": ["Default technical question 1", "Default technical question 2"],
                "hr": ["Default HR 1"],
                "behavioral": ["Default behavioral 1"]
            }
        },
        student_id="default_student"
    )
    return test_db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["ENFORCE_LOGIN_IN_TESTS"] = False
    with app.test_client() as client:
        yield client


def test_normalize_difficulty():
    """Verify normalization of difficulty inputs including case and defaults."""
    assert normalize_difficulty("beginner") == DIFFICULTY_BEGINNER
    assert normalize_difficulty("Intermediate") == DIFFICULTY_INTERMEDIATE
    assert normalize_difficulty("ADVANCED") == DIFFICULTY_ADVANCED
    assert normalize_difficulty("unknown_tier") == DIFFICULTY_INTERMEDIATE
    assert normalize_difficulty(None) == DIFFICULTY_INTERMEDIATE


def test_get_difficulty_metadata():
    """Verify difficulty metadata contains badge classes and descriptive icons."""
    beg_meta = get_difficulty_metadata(DIFFICULTY_BEGINNER)
    assert beg_meta["name"] == DIFFICULTY_BEGINNER
    assert "bg-success" in beg_meta["badge_class"]

    adv_meta = get_difficulty_metadata(DIFFICULTY_ADVANCED)
    assert adv_meta["name"] == DIFFICULTY_ADVANCED
    assert "bg-danger" in adv_meta["badge_class"]


def test_generate_difficulty_interview_questions():
    """Verify generation of difficulty-tiered question batches (15 Qs: 5 HR, 5 Tech, 5 Behav)."""
    questions = generate_difficulty_interview_questions(
        difficulty="Advanced",
        target_company="Stripe",
        target_role="Backend Engineer"
    )
    assert len(questions) == 15
    tech_qs = [q for q in questions if q["type"] == "Technical"]
    assert len(tech_qs) == 5
    assert any("consensus" in q["question"].lower() or "rate limit" in q["question"].lower() for q in tech_qs)
    assert all(q["difficulty"] == DIFFICULTY_ADVANCED for q in questions)


def test_api_difficulty_options(client):
    """Test /api/interview/difficulty/options endpoint."""
    resp = client.get("/api/interview/difficulty/options")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert len(data["difficulty_options"]) == 3
    tiers = [t["name"] for t in data["difficulty_options"]]
    assert DIFFICULTY_BEGINNER in tiers
    assert DIFFICULTY_INTERMEDIATE in tiers
    assert DIFFICULTY_ADVANCED in tiers


def test_api_generate_difficulty_questions(client):
    """Test /api/interview/difficulty/generate endpoint."""
    resp = client.post(
        "/api/interview/difficulty/generate",
        data=json.dumps({"difficulty": "Beginner", "company_name": "Amazon"}),
        content_type="application/json"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["difficulty"] == DIFFICULTY_BEGINNER
    assert len(data["questions"]) == 15


def test_interview_route_with_difficulty_parameter(client):
    """Verify /interview/<analysis_id>?difficulty=Advanced initializes a difficulty-scoped session."""
    resp = client.get("/interview/analysis_diff_test?difficulty=Advanced")
    assert resp.status_code == 200
    content = resp.data.decode("utf-8")
    assert "Advanced" in content
    assert "Level: Advanced" in content

    # Verify session persisted in DB
    session = get_interview_session("analysis_diff_test_advanced")
    assert session is not None
    assert len(session["questions"]) == 15
    assert session["questions"][0].get("difficulty") == DIFFICULTY_ADVANCED
