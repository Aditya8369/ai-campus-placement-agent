"""
Test suite for candidate placement profile sharing, social intent links, and modal structure.

Checks:
- Presence of share profile modal and button in dashboard template
- Correct copy-link input target and clipboard handler bindings
- Pre-populated social sharing links (LinkedIn, X/Twitter, WhatsApp)
"""

import tempfile
from pathlib import Path
import pytest
from utils.database import init_db, save_analysis
from app import app
import config


@pytest.fixture
def sample_analysis(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "share_test.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db)
        init_db()

        aid = "test_share_aid_777"
        sample_results = {
            "resume_analysis": {"ats_score": 90, "skills": ["Python", "Flask"]},
            "job_match": {"match_percentage": 85, "matching_skills": ["Python"]},
            "skill_gap": {"missing_skills": []},
            "roadmap": {"weeks": []},
            "interview_questions": {"hr": [], "technical": [], "behavioral": []},
            "overall_recommendation_summary": "Top readiness score",
        }
        save_analysis(aid, "Candidate_Resume.pdf", "Amazon", "SWE", sample_results)
        yield aid


def test_dashboard_renders_share_modal_and_button(sample_analysis):
    """Verify GET /dashboard/<aid> includes share profile modal and button."""
    aid = sample_analysis
    app.config["TESTING"] = True

    with app.test_client() as client:
        res = client.get(f"/dashboard/{aid}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")

        # Check share button
        assert 'id="btnShareProfileModal"' in html
        assert 'data-bs-target="#shareProfileModal"' in html

        # Check modal structure
        assert 'id="shareProfileModal"' in html
        assert 'id="shareProfileUrl"' in html
        assert 'id="btnCopyShareUrl"' in html

        # Check social share links
        assert "linkedin.com/sharing" in html
        assert "twitter.com/intent/tweet" in html
        assert "api.whatsapp.com/send" in html
