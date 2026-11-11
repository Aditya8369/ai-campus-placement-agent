"""
Automated Test Suite for First-Time User Walkthrough & Feature Tour (#350).
Verifies:
- All 4 core areas (Resume Analysis, Mock Interviews, Prep Plans, Application Tracker) are explained.
- Recommended next step guidance is provided.
- Dismiss and reset session endpoints work cleanly.
- Walkthrough UI (banner, modal, action buttons, skip/dismiss, reopen trigger) renders on the home page.
- Walkthrough does NOT repeat the profile completion feature or force users through a tutorial.
"""

import json
import pytest
from app import app, WALKTHROUGH_STEPS_CATALOG


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_walkthrough_catalog_structure():
    """Verify WALKTHROUGH_STEPS_CATALOG defines all 4 required areas without profile completion."""
    assert len(WALKTHROUGH_STEPS_CATALOG) == 4
    step_ids = [s["id"] for s in WALKTHROUGH_STEPS_CATALOG]
    assert "resume_analysis" in step_ids
    assert "interview_practice" in step_ids
    assert "preparation_plans" in step_ids
    assert "application_tracker" in step_ids

    # Ensure profile completion fields are NOT asked for
    for step in WALKTHROUGH_STEPS_CATALOG:
        content = (step["title"] + " " + step["short_desc"] + " " + step["long_desc"]).lower()
        assert "gpa" not in content
        assert "phone number" not in content
        assert "graduation year" not in content
        assert step["action_url"] is not None
        assert step["action_text"] is not None


def test_api_walkthrough_endpoint(client):
    """Verify GET /api/walkthrough returns structured metadata for all 4 core features."""
    res = client.get("/api/walkthrough")
    assert res.status_code == 200
    data = res.get_json()

    assert data["success"] is True
    assert data["total_steps"] == 4
    assert "recommended_next_step" in data
    assert data["recommended_next_step"]["feature"] == "resume_analysis"
    assert "steps" in data
    assert len(data["steps"]) == 4

    titles = [s["title"] for s in data["steps"]]
    assert any("Resume" in t for t in titles)
    assert any("Interview" in t for t in titles)
    assert any("Preparation" in t or "Roadmap" in t for t in titles)
    assert any("Application" in t or "Tracker" in t for t in titles)


def test_api_walkthrough_dismiss_and_reset(client):
    """Verify users can dismiss the walkthrough and reset/reopen it later."""
    # 1. Initially not dismissed
    res_init = client.get("/api/walkthrough")
    assert res_init.get_json()["dismissed"] is False

    # 2. Dismiss walkthrough
    res_dismiss = client.post("/api/walkthrough/dismiss")
    assert res_dismiss.status_code == 200
    assert res_dismiss.get_json()["dismissed"] is True

    # 3. Check status is now dismissed
    res_check = client.get("/api/walkthrough")
    assert res_check.get_json()["dismissed"] is True

    # 4. Reset walkthrough state
    res_reset = client.post("/api/walkthrough/reset")
    assert res_reset.status_code == 200
    assert res_reset.get_json()["dismissed"] is False

    # 5. Check status is no longer dismissed
    res_final = client.get("/api/walkthrough")
    assert res_final.get_json()["dismissed"] is False


def test_homepage_walkthrough_ui_rendering(client):
    """Verify home page renders walkthrough banner, interactive modal, and reopen trigger."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Navbar reopen button
    assert 'id="btnOpenWalkthrough"' in html
    assert "Tour" in html

    # 2. Walkthrough Banner
    assert 'id="userWalkthroughBanner"' in html
    assert "Quick Walkthrough" in html
    assert "btnDismissWalkthroughBanner" in html
    assert "btnLaunchWalkthroughModal" in html

    # 3. Recommended Next Step callout
    assert "Recommended Next Step" in html
    assert "Upload your PDF or DOCX resume" in html
    assert 'id="btnWalkthroughNextStep"' in html

    # 4. Navigation to all 4 features
    assert "Resume Analysis" in html
    assert "Mock Interviews" in html or "Interview Practice" in html
    assert "Preparation Plans" in html
    assert "Application Tracker" in html
    assert "/applications" in html
    assert "/company-checklist" in html
    assert "/coding-practice" in html

    # 5. Interactive Modal
    assert 'id="userWalkthroughModal"' in html
    assert "btnDismissWalkthroughModal" in html
    assert "btnWalkthroughPrev" in html
    assert "btnWalkthroughNext" in html
    assert "btnResetWalkthroughState" in html


def test_homepage_walkthrough_dismissed_hides_banner_retains_tour_button(client):
    """Verify that dismissed walkthrough hides the banner while retaining the navbar reopen trigger."""
    with client.session_transaction() as sess:
        sess["walkthrough_dismissed"] = True

    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # The banner has d-none class when dismissed
    assert 'id="userWalkthroughBanner"' in html
    assert "d-none" in html

    # The Tour button is still present in the navbar to reopen anytime
    assert 'id="btnOpenWalkthrough"' in html

