"""
Test interview scorecard and performance summary display in templates.
"""

from app import app


def test_interview_template_contains_scorecard():
    """Verify interview template includes the completion scorecard elements."""
    with app.test_client() as client:
        # We can inspect the template structure or test interview route
        with open("templates/interview.html", "r", encoding="utf-8") as f:
            content = f.read()
        assert "interviewScorecard" in content
        assert "scorecardTechScore" in content
        assert "scorecardCommScore" in content
        assert "scorecardClarityScore" in content
        assert "progressBarTech" in content
