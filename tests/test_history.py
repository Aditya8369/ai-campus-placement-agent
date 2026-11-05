"""
Unit and integration tests for placement analysis history and deletion (#159).

Tests verify:
- History page lists saved analyses, newest first.
- Opening an old analysis in the existing dashboard view without a new AI call.
- Deleting an entry removes it from SQLite (including interviews and cohort benchmarks).
- Empty state is shown when there is no history.
- API endpoints for history retrieval and deletion.
"""

import json
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

import config
from app import app
from utils.database import (
    init_db,
    save_analysis,
    get_analysis,
    get_analyses_history,
    delete_analysis,
    create_interview_session,
    get_interview_session,
    record_or_update_cohort_benchmark,
    get_cohort_benchmark_by_analysis_id,
)


@pytest.fixture
def temp_db(tmp_path):
    test_db = tmp_path / "test_history.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        yield str(test_db)


@pytest.fixture
def client(temp_db):
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_get_analyses_history_newest_first(temp_db):
    """Verify get_analyses_history returns records in descending order of creation."""
    # Seed 3 analyses
    id_1 = str(uuid.uuid4())
    save_analysis(
        analysis_id=id_1,
        resume_filename="resume_1.pdf",
        company_name="Google",
        job_description="Backend Engineer",
        results_dict={
            "ats_score": 75,
            "target_role": "Backend Engineer",
            "resume_analysis": {"ats_score": 75},
            "job_match": {"match_percentage": 80, "target_role": "Backend Engineer"},
        },
    )

    id_2 = str(uuid.uuid4())
    save_analysis(
        analysis_id=id_2,
        resume_filename="resume_2.pdf",
        company_name="Microsoft",
        job_description="Cloud Architect",
        results_dict={
            "ats_score": 88,
            "target_role": "Cloud Architect",
            "resume_analysis": {"ats_score": 88},
            "job_match": {"match_percentage": 92, "target_role": "Cloud Architect"},
        },
    )

    history = get_analyses_history()
    assert len(history) == 2
    # Newest first: id_2 should appear before id_1
    assert history[0]["id"] == id_2
    assert history[0]["company_name"] == "Microsoft"
    assert history[0]["target_role"] == "Cloud Architect"
    assert history[0]["ats_score"] == 88

    assert history[1]["id"] == id_1
    assert history[1]["company_name"] == "Google"
    assert history[1]["target_role"] == "Backend Engineer"
    assert history[1]["ats_score"] == 75


def test_get_analyses_history_empty_state(temp_db):
    """Verify empty list is returned when database contains no analyses."""
    history = get_analyses_history()
    assert history == []


def test_history_page_renders_saved_analyses(client):
    """Verify GET /history displays analysis date, target role/company and ATS score."""
    aid = str(uuid.uuid4())
    save_analysis(
        analysis_id=aid,
        resume_filename="john_doe_resume.pdf",
        company_name="Amazon",
        job_description="DevOps Specialist",
        results_dict={
            "ats_score": 82,
            "target_role": "DevOps Specialist",
            "resume_analysis": {"ats_score": 82},
            "job_match": {"match_percentage": 85, "target_role": "DevOps Specialist"},
        },
    )

    res = client.get("/history")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "Amazon" in html
    assert "DevOps Specialist" in html
    assert "82%" in html
    assert "john_doe_resume.pdf" in html
    assert f"/dashboard/{aid}" in html
    assert f"/history/delete/{aid}" in html


def test_history_page_empty_state_rendered(client):
    """Verify GET /history renders empty state when no past analyses exist."""
    res = client.get("/history")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "emptyHistoryState" in html
    assert "No Analysis History Found" in html
    assert "Start New Analysis" in html


def test_clicking_entry_reopens_existing_dashboard_without_new_ai_calls(client):
    """Verify opening an old analysis reopens the existing dashboard view with no new Gemini calls."""
    aid = str(uuid.uuid4())
    sample_results = {
        "resume_analysis": {
            "ats_score": 89,
            "strengths": ["Strong algorithms background"],
            "summary": "Solid candidate profile",
        },
        "job_match": {
            "match_percentage": 91,
            "top_5_changes": ["Add system design details"],
        },
        "skill_gap": [],
        "roadmap": [],
        "interview_questions": {
            "hr": ["Tell me about yourself"],
            "technical": ["Explain quicksort"],
            "behavioral": ["Describe a conflict"],
        },
    }
    save_analysis(
        analysis_id=aid,
        resume_filename="sample_resume.pdf",
        company_name="Meta",
        job_description="Software Engineer",
        results_dict=sample_results,
    )

    with patch("utils.gemini.generate_json_response") as mock_gemini:
        res = client.get(f"/dashboard/{aid}")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert "Meta" in html
        assert "Strong algorithms background" in html
        # Zero Gemini calls triggered
        assert mock_gemini.call_count == 0


def test_delete_analysis_removes_from_database(client):
    """Verify delete action removes the analysis, associated interviews, and cohort data."""
    aid = str(uuid.uuid4())
    save_analysis(
        analysis_id=aid,
        resume_filename="candidate.pdf",
        company_name="Netflix",
        job_description="SRE",
        results_dict={
            "resume_analysis": {"ats_score": 78},
            "job_match": {"match_percentage": 80},
        },
    )

    # Add related interview session
    create_interview_session(
        aid,
        aid,
        [{"index": 0, "type": "Technical", "question": "Explain DNS"}]
    )
    assert get_interview_session(aid) is not None

    # Perform deletion via POST /history/delete/<aid>
    del_res = client.post(f"/history/delete/{aid}", follow_redirects=True)
    assert del_res.status_code == 200

    # Analysis must be completely gone from database
    assert get_analysis(aid) is None
    assert get_interview_session(aid) is None
    assert get_cohort_benchmark_by_analysis_id(aid) is None

    # History page should now show empty state
    html_after = del_res.get_data(as_text=True)
    assert "No Analysis History Found" in html_after


def test_api_delete_and_history_json_endpoints(client):
    """Verify REST API behavior for history retrieval and deletion."""
    aid = str(uuid.uuid4())
    save_analysis(
        analysis_id=aid,
        resume_filename="api_resume.pdf",
        company_name="Apple",
        job_description="iOS Engineer",
        results_dict={
            "ats_score": 95,
            "target_role": "iOS Engineer",
            "resume_analysis": {"ats_score": 95},
            "job_match": {"match_percentage": 90},
        },
    )

    # Fetch JSON history
    res = client.get("/history", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["total"] == 1
    assert data["analyses"][0]["company_name"] == "Apple"
    assert data["analyses"][0]["target_role"] == "iOS Engineer"

    # Delete via API
    del_res = client.delete(f"/api/analysis/{aid}")
    assert del_res.status_code == 200
    del_data = del_res.get_json()
    assert del_data["status"] == "success"

    # Second delete returns 404
    del_404 = client.delete(f"/api/analysis/{aid}")
    assert del_404.status_code == 404
