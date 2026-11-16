import pytest
from app import app
from utils.ai_disclaimer_service import AIDisclaimerService, ai_disclaimer_service


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_disclaimer_presets():
    service = AIDisclaimerService()
    for cat in ["general_ai", "resume_review", "mock_interview", "skill_gap", "coding_feedback"]:
        data = service.get_disclaimer_data(cat)
        assert data["category"] == cat
        assert len(data["title"]) > 0
        assert len(data["badge"]) > 0
        assert len(data["short_text"]) > 0
        assert len(data["full_text"]) > 0
        assert "available_languages" in data


def test_disclaimer_translations():
    service = AIDisclaimerService()
    hi_data = service.get_disclaimer_data("resume_review", lang="hi")
    assert hi_data["language"] == "hi"
    assert "एल्गोरिथम" in hi_data["short_text"]

    es_data = service.get_disclaimer_data("resume_review", lang="es")
    assert es_data["language"] == "es"
    assert "algorítmicas" in es_data["short_text"]


def test_render_banner_html():
    service = AIDisclaimerService()
    html_banner = service.render_banner_html("resume_review", is_dismissible=True)
    assert "ai-disclaimer-banner" in html_banner
    assert "AI Resume Evaluation" in html_banner
    assert "btn-close" in html_banner
    assert "details" in html_banner
    assert "Learn more" in html_banner

    # Non-dismissible
    static_banner = service.render_banner_html("resume_review", is_dismissible=False)
    assert "btn-close" not in static_banner


def test_render_footnote_html():
    service = AIDisclaimerService()
    fn = service.render_footnote_html("mock_interview")
    assert "ai-disclaimer-footnote" in fn
    assert "AI Mock Interviewer" in fn


def test_attach_disclaimer_to_payload():
    service = AIDisclaimerService()
    base_payload = {"score": 85, "recommendation": "Learn Docker"}
    enriched = service.attach_disclaimer_to_payload(base_payload, "skill_gap")
    assert enriched["score"] == 85
    assert "ai_disclaimer" in enriched
    assert enriched["ai_disclaimer"]["category"] == "skill_gap"
    assert "banner_html" in enriched["ai_disclaimer"]


def test_api_get_ai_disclaimer_endpoint(client):
    res = client.get("/api/ai/disclaimer?category=coding_feedback")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["disclaimer"]["category"] == "coding_feedback"
    assert "Automated Code Review" in data["disclaimer"]["badge"]
    assert "ai-disclaimer-banner" in data["banner_html"]
    assert "ai-disclaimer-footnote" in data["footnote_html"]


def test_api_get_ai_disclaimer_fallback(client):
    res = client.get("/api/ai/disclaimer?category=non_existent_category")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["disclaimer"]["title"] == "AI-Generated Educational Assistance"
