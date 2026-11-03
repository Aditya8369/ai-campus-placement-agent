"""
Tests for AI Behavioral STAR Story Coach & Non-Verbal Composure Analyzer
"""

import json
from unittest.mock import MagicMock
import pytest

from app import app
from agents.star_agent import StarEvaluationAgent


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def star_agent():
    return StarEvaluationAgent()


SAMPLE_STAR_ANSWER = (
    "During my summer internship at TechCorp, our production API experienced a critical memory leak (Situation). "
    "My specific responsibility was to identify the root cause and restore 99.9% uptime (Task). "
    "I analyzed heap dumps, refactored the caching mechanism with Redis, and implemented connection pooling (Action). "
    "As a result, we reduced latency by 65%, eliminated memory crashes, and supported 10,000 concurrent users (Result)."
)


def test_star_agent_parse_score(star_agent):
    assert star_agent.parse_score(85) == 85
    assert star_agent.parse_score(92.7) == 93
    assert star_agent.parse_score("78%") == 78
    assert star_agent.parse_score("4/5") == 80
    assert star_agent.parse_score(None, default=60) == 60
    assert star_agent.parse_score("invalid_val", default=50) == 50
    assert star_agent.parse_score(150) == 100
    assert star_agent.parse_score(-20) == 0


def test_star_agent_detect_fillers(star_agent):
    text_with_fillers = "Um, so basically, like, I think our team was, you know, actually trying to resolve the bug."
    res = star_agent.detect_fillers(text_with_fillers)
    assert res["filler_word_count"] >= 4
    assert "um" in res["filler_words_detected"]
    assert "like" in res["filler_words_detected"]
    assert "actually" in res["filler_words_detected"]
    assert "basically" in res["filler_words_detected"]

    clean_text = "I architected the database schema and deployed the microservice."
    clean_res = star_agent.detect_fillers(clean_text)
    assert clean_res["filler_word_count"] == 0
    assert len(clean_res["filler_words_detected"]) == 0


def test_star_agent_evaluate_complete_answer(star_agent):
    res = star_agent.evaluate_star(
        question="Tell me about a challenging technical problem you solved.",
        answer=SAMPLE_STAR_ANSWER,
        question_type="Behavioral",
        speech_metrics={
            "duration_seconds": 38,
            "words_per_minute": 132,
            "eye_contact_ratio": 0.88,
            "composure_score": 90,
        },
    )

    assert "star_score" in res
    assert res["star_score"] >= 70

    # Verify S-T-A-R dimensions
    assert res["situation"]["present"] is True
    assert res["situation"]["score"] >= 70
    assert len(res["situation"]["feedback"]) > 0

    assert res["task"]["present"] is True
    assert res["task"]["score"] >= 70

    assert res["action"]["present"] is True
    assert res["action"]["score"] >= 75

    assert res["result"]["present"] is True
    assert res["result"]["score"] >= 70

    # Verbal & non-verbal telemetry
    assert "verbal_metrics" in res
    assert res["verbal_metrics"]["speech_pace_wpm"] > 0
    assert res["verbal_metrics"]["pacing_evaluation"] == "Optimal"

    assert "non_verbal_composure" in res
    assert res["non_verbal_composure"]["eye_contact_score"] >= 80
    assert "Good" in res["non_verbal_composure"]["eye_contact_status"]
    assert res["non_verbal_composure"]["composure_score"] == 90

    # Coaching suggestions
    assert len(res["coaching"]["strengths"]) > 0
    assert len(res["coaching"]["improvements"]) > 0
    assert len(res["coaching"]["suggested_star_rewrite"]) > 0


def test_star_agent_insufficient_answer(star_agent):
    brief_answer = "I fixed a bug."
    res = star_agent.evaluate_star(
        question="Describe a difficult challenge you faced.",
        answer=brief_answer,
        question_type="Behavioral",
    )
    assert res["star_score"] <= 40
    assert res["situation"]["present"] is False
    assert res["action"]["present"] is False
    assert res["verbal_metrics"]["pacing_evaluation"] == "Too Short"
    assert "at least" in res["coaching"]["improvements"][0]


def test_star_agent_with_mock_llm(monkeypatch, star_agent):
    mock_llm_payload = {
        "star_score": 92,
        "situation": {
            "present": True,
            "score": 90,
            "feedback": "Strong background context.",
            "excerpt": "During my summer internship...",
        },
        "task": {
            "present": True,
            "score": 88,
            "feedback": "Clear personal assignment.",
            "excerpt": "My specific responsibility...",
        },
        "action": {
            "present": True,
            "score": 95,
            "feedback": "Decisive technical ownership.",
            "excerpt": "I refactored the caching mechanism...",
        },
        "result": {
            "present": True,
            "score": 94,
            "feedback": "Impressive 65% latency reduction metric.",
            "excerpt": "We reduced latency by 65%...",
        },
        "verbal_metrics": {
            "filler_words_detected": [],
            "filler_word_count": 0,
            "clarity_score": 95,
            "conciseness_score": 90,
            "speech_pace_wpm": 135.0,
            "pacing_evaluation": "Optimal",
        },
        "non_verbal_composure": {
            "eye_contact_score": 92,
            "eye_contact_status": "Good Center Focus",
            "composure_score": 90,
            "composure_rating": "Confident & Composed",
            "feedback": "Excellent posture.",
        },
        "coaching": {
            "strengths": ["Excellent quantitative metrics"],
            "improvements": ["Keep doing this"],
            "suggested_star_rewrite": "Model STAR response example",
        },
    }

    import agents.star_agent as sa_module

    monkeypatch.setattr(sa_module, "generate_json_response", lambda **kwargs: mock_llm_payload)

    eval_result = star_agent.evaluate_star(
        question="Walk me through a difficult bug you diagnosed.",
        answer=SAMPLE_STAR_ANSWER,
        question_type="Behavioral",
    )
    assert eval_result["star_score"] == 92
    assert eval_result["action"]["score"] == 95
    assert eval_result["result"]["score"] == 94
    assert eval_result["coaching"]["suggested_star_rewrite"] == "Model STAR response example"


def test_api_evaluate_star_endpoint_success(client):
    payload = {
        "question": "Tell me about a time you handled a conflict in your team.",
        "answer": SAMPLE_STAR_ANSWER,
        "question_type": "Behavioral",
        "speech_metrics": {
            "duration_seconds": 35,
            "words_per_minute": 130,
            "filler_word_count": 1,
            "eye_contact_ratio": 0.85,
            "composure_score": 88,
        },
    }

    res = client.post(
        "/api/interview/evaluate-star",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["success"] is True
    assert "star_evaluation" in data
    star_eval = data["star_evaluation"]
    assert "situation" in star_eval
    assert "task" in star_eval
    assert "action" in star_eval
    assert "result" in star_eval
    assert star_eval["star_score"] >= 70


def test_api_evaluate_star_endpoint_missing_answer(client):
    res = client.post(
        "/api/interview/evaluate-star",
        data=json.dumps({"question": "Tell me about yourself.", "answer": "   "}),
        content_type="application/json",
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "error"
    assert "required" in data["message"]


def test_api_evaluate_star_form_encoded(client):
    res = client.post(
        "/api/interview/evaluate-star",
        data={
            "question": "Describe a major mistake you made and learned from.",
            "answer": SAMPLE_STAR_ANSWER,
            "question_type": "Behavioral",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "star_evaluation" in data


def test_interview_template_has_star_and_video_elements():
    """Verify templates/interview.html contains video coach and STAR breakdown elements."""
    with open("templates/interview.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Video Coach Elements
    assert 'id="videoCoachPanel"' in html
    assert 'id="btnToggleVideoCoach"' in html
    assert 'id="candidateVideoFeed"' in html
    assert 'id="btnStopCamera"' in html
    assert 'id="telemetryEyeScore"' in html
    assert 'id="telemetryComposureScore"' in html
    assert 'id="telemetryCadenceWpm"' in html

    # STAR Story Architecture Elements
    assert 'id="starBreakdownCard"' in html
    assert 'id="starOverallScoreBadge"' in html
    assert 'id="pillSituation"' in html
    assert 'id="pillTask"' in html
    assert 'id="pillAction"' in html
    assert 'id="pillResult"' in html
    assert 'id="starModelRewriteText"' in html

