import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app import app
from config import Config
from utils.database import get_analysis_by_id, update_analysis_section


@pytest.fixture
def isolated_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_campus_agent.db"
        monkeypatch.setattr(Config, "DATABASE_PATH", str(db_path))

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE analyses (
                id TEXT PRIMARY KEY,
                company_name TEXT,
                target_role TEXT,
                resume_text TEXT,
                job_description TEXT,
                result_json TEXT
            )
            """
        )

        initial_result = {
            "ats_score": 84,
            "resume_analysis": {
                "strengths": ["Strong Python and SQL backend projects"],
                "weaknesses": [],
            },
            "job_match": {
                "match_percentage": 80,
                "matched_keywords": ["Python", "SQL"],
                "missing_keywords": ["Docker"],
            },
            "skill_gaps": [
                {
                    "skill": "Docker",
                    "importance": "High",
                    "learning_time": "1 week",
                    "priority": "High",
                    "learning_resource": "Docker Official Docs",
                    "project_suggestion": "Containerize a Flask REST API",
                }
            ],
            "learning_roadmap": [],
            "interview_questions": [],
            "failed_sections": {
                "roadmap": "Gemini timeout during initial generation"
            },
        }

        conn.execute(
            """
            INSERT INTO analyses (id, company_name, target_role, resume_text, job_description, result_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "analysis-test-101",
                "Google",
                "Software Development Engineer",
                "Experienced Python developer with Flask, SQLite, and REST APIs.",
                "Looking for SDE with Python, Data Structures, and Distributed Systems.",
                json.dumps(initial_result),
            ),
        )
        conn.commit()
        conn.close()
        yield str(db_path)


def test_retry_failed_roadmap_preserves_existing_sections(isolated_db):
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    mock_roadmap_response = {
        "learning_roadmap": [
            {
                "week": "Week 1",
                "estimated_hours": 12,
                "topics": ["Trees & Graphs"],
                "coding_practice": ["LeetCode 200"],
                "mini_projects": ["Graph Shortest Path Visualizer"],
                "interview_questions": ["Explain BFS vs DFS space complexity"],
                "revision_tasks": ["Review adjacency list representations"],
            }
        ]
    }

    with patch("utils.section_retry.generate_structured_json", return_value=mock_roadmap_response) as mock_ai:
        client = app.test_client()
        resp = client.post(
            "/api/analysis/analysis-test-101/retry-section",
            json={"section": "roadmap"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["section"] == "roadmap"
    assert len(body["data"]) == 1
    assert body["ai_request"]["ai_request_made"] is True
    assert "targeted Gemini AI request" in body["ai_request"]["notice"]
    assert body["rate_limit"]["next_request_allowed"] is True
    mock_ai.assert_called_once()

    # Verify DB updated ONLY roadmap and preserved ats_score, skill_gaps, and job_match
    updated = get_analysis_by_id("analysis-test-101")["result"]
    assert updated["ats_score"] == 84
    assert updated["job_match"]["match_percentage"] == 80
    assert updated["skill_gaps"][0]["skill"] == "Docker"
    assert updated["learning_roadmap"][0]["week"] == "Week 1"
    assert "roadmap" not in updated.get("failed_sections", {})


def test_retry_invalid_section_returns_400(isolated_db):
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    resp = client.post(
        "/api/analysis/analysis-test-101/retry-section",
        json={"section": "non_existent_section"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_update_analysis_section_atomic_patch(isolated_db):
    new_questions = [
        {
            "category": "Technical",
            "difficulty": "Medium",
            "question": "How does SQLite handle write concurrency?",
            "expected_focus": "WAL mode and database-level locking",
        }
    ]
    patched = update_analysis_section(
        analysis_id="analysis-test-101",
        section_db_key="interview_questions",
        section_payload=new_questions,
        section_key="interview_questions",
    )
    assert patched["ats_score"] == 84
    assert patched["skill_gaps"][0]["skill"] == "Docker"
    assert patched["interview_questions"] == new_questions