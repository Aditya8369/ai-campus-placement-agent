"""
Unit tests for Mock interview answer outline mode (#608)
"""

import pytest
from utils.interview_outline_service import (
    get_outline_template,
    convert_outline_to_draft,
    score_outline_completeness
)


def test_get_outline_template_behavioral():
    tmpl = get_outline_template("Behavioral")
    assert len(tmpl["headings"]) == 4
    keys = [h["key"] for h in tmpl["headings"]]
    assert "intro" in keys and "conclusion" in keys
    assert len(tmpl["checklist"]) >= 3


def test_get_outline_template_technical():
    tmpl = get_outline_template("Technical")
    assert len(tmpl["headings"]) == 4
    assert any("complexity" in c["key"].lower() for c in tmpl["checklist"])


def test_convert_outline_to_draft():
    sections = {
        "intro": "In my previous internship at CloudTech,",
        "main": "I was tasked with migrating legacy monolithic endpoints to microservices.",
        "example": "I set up Docker containers and configured an API gateway with JWT verification.",
        "conclusion": "we reduced response latencies by 28% and eliminated deployment downtime."
    }
    draft = convert_outline_to_draft(sections)
    assert "CloudTech" in draft
    assert "migrating legacy" in draft
    assert "reduced response latencies by 28%" in draft


def test_score_outline_completeness():
    sections = {
        "intro": "Short intro",
        "main": "Main concept explanation",
        "example": "Practical hands on work",
        "conclusion": "Outcome achieved"
    }
    checked = ["context", "ownership"]
    score_res = score_outline_completeness(sections, checked)
    assert score_res["outline_score"] >= 60
    assert score_res["is_ready_for_draft"] is True


def test_api_outline_mode_endpoints(client):
    # GET template
    resp = client.get("/api/interview/outline-mode/template?question_type=Behavioral")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "template" in data

    # POST convert outline
    conv_resp = client.post(
        "/api/interview/outline-mode/convert",
        json={
            "sections": {
                "intro": "Introduction to situation",
                "main": "Action plan",
                "example": "Execution",
                "conclusion": "Results"
            },
            "checked_items": ["context"]
        }
    )
    assert conv_resp.status_code == 200
    conv_data = conv_resp.get_json()
    assert conv_data["status"] == "success"
    assert "Introduction to situation" in conv_data["draft"]
