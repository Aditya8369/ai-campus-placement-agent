"""
Regression tests for #478: dashboard() computes link check results, annotations and
keyword highlight data, and has to hand all of them to dashboard.html.
"""

import tempfile
from pathlib import Path

import pytest

import config
from app import app
from utils import link_checker
from utils.database import create_analysis_annotation, init_db, save_analysis


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(config, "DATABASE_PATH", str(Path(tmpdir) / "dashboard_links.db"))
        monkeypatch.setattr(config, "BASE_DIR", str(tmpdir))
        init_db()
        app.config["TESTING"] = True
        app.config["ENFORCE_LOGIN_IN_TESTS"] = False
        with app.test_client() as test_client:
            yield test_client


def _save(aid, skill_gap):
    save_analysis(
        analysis_id=aid,
        resume_filename="resume.pdf",
        company_name="Google",
        job_description="Python and Docker engineer",
        results_dict={
            "resume_analysis": {"ats_score": 80},
            "job_match": {
                "match_percentage": 70,
                "matched_skills": ["Python"],
                "missing_skills": ["Docker"],
            },
            "skill_gap": skill_gap,
            "extracted_resume_text": "I write Python services.",
        },
        student_id="default_student",
    )


def test_dashboard_shows_working_and_broken_link_badges(client, monkeypatch):
    def fake_check_link(url, timeout=link_checker.CHECK_TIMEOUT_SECONDS):
        if "good" in url:
            return {"url": url, "status": "working", "label": "Working", "detail": "HTTP 200"}
        return {"url": url, "status": "broken", "label": "Broken", "detail": "HTTP 404"}

    monkeypatch.setattr(link_checker, "check_link", fake_check_link)
    _save("aid_links_478", [
        {
            "skill": "Docker",
            "importance": "High",
            "learning_time": "1 week",
            "learning_resource": "Docs at https://example.com/good and https://example.com/dead",
            "project_suggestion": "Containerise an app",
            "priority": "High",
        }
    ])

    res = client.get("/dashboard/aid_links_478")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "https://example.com/good" in html
    assert "https://example.com/dead" in html
    assert "Working" in html
    assert "Broken" in html
    assert 'id="badgeMatchedKeywordsCount"' in html


def test_dashboard_shows_saved_annotations(client):
    _save("aid_annot_478", [])
    create_analysis_annotation(
        "default_student", "aid_annot_478", "note", "General", "Mention the capstone deployment"
    )

    res = client.get("/dashboard/aid_annot_478")
    assert res.status_code == 200
    assert "Mention the capstone deployment" in res.get_data(as_text=True)


def test_dashboard_renders_without_skill_gaps_or_annotations(client):
    _save("aid_empty_478", [])

    res = client.get("/dashboard/aid_empty_478")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "No Skill Gaps Identified" in html
    assert 'id="resumeKeywordHighlightSection"' in html
