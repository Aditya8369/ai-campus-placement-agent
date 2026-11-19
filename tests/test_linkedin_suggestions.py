"""
Tests for LinkedIn Profile Suggestions: Headline Options, First-Person About,
Recruiter Search Keywords, and Copy Actions (#538).
"""

import json
import pytest
from app import app
from agents.linkedin_agent import LinkedInAgent
from utils.database import save_analysis


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


SAMPLE_RICH_RESUME = """
Alex Chen
San Francisco, CA | (555) 019-2834 | alex.chen@example.com
Education:
Bachelor of Science in Computer Science, 2026
Technical Skills:
Python, React, Docker, PostgreSQL, Redis, REST APIs, Git, Microservices, Linux
Experience:
Software Engineering Intern at CloudTech Solutions
- Developed asynchronous microservices using Python and Flask
- Optimized database query throughput by 25% with Redis caching
Projects:
Distributed Task Queue in Python and Redis
- Architected background worker system processing 5,000 tasks/min
- Implemented exponential backoff and dead-letter queues
"""

SAMPLE_SPARSE_RESUME = """
Jane Doe
Skills: Python, SQL
"""


def test_headline_options_length_limit():
    """
    Acceptance criterion: Headlines respect the length limit (<= 220 chars).
    All 3 headline options must strictly be <= 220 characters.
    """
    agent = LinkedInAgent()
    suggestions = agent.generate_linkedin_suggestions(
        resume_text=SAMPLE_RICH_RESUME,
        target_role="Software Engineer"
    )

    headlines = suggestions.get("headline_options", [])
    assert len(headlines) == 3, f"Expected 3 headline options, got {len(headlines)}"

    for opt in headlines:
        headline = opt.get("headline", "")
        char_count = opt.get("char_count", len(headline))
        assert len(headline) <= 220, f"Headline exceeds 220 chars ({len(headline)} chars): {headline}"
        assert char_count <= 220
        assert opt.get("max_chars") == 220
        assert opt.get("type") in [
            "Role & Core Stack",
            "Impact & Experience",
            "Specialization & Vision"
        ]


def test_headline_truncation_for_very_long_inputs():
    """
    Acceptance criterion: Headlines respect the length limit even when inputs are extremely verbose.
    """
    agent = LinkedInAgent()
    super_long_role = "Senior Principal Distributed Cloud Architecture & Scalable Microservices Infrastructure Engineering Specialist"
    verbose_resume = SAMPLE_RICH_RESUME + "\nSkills: " + ", ".join(["SuperTech" + str(i) for i in range(50)])

    suggestions = agent.generate_linkedin_suggestions(
        resume_text=verbose_resume,
        target_role=super_long_role
    )

    headlines = suggestions.get("headline_options", [])
    assert len(headlines) == 3
    for opt in headlines:
        headline = opt.get("headline", "")
        assert len(headline) <= 220, f"Clipped headline exceeds 220 chars: {headline}"


def test_first_person_about_section():
    """
    Acceptance criterion: Draft a first-person About section from the resume.
    Must use first-person pronouns ('I', 'my') and only reference details in the resume.
    """
    agent = LinkedInAgent()
    suggestions = agent.generate_linkedin_suggestions(
        resume_text=SAMPLE_RICH_RESUME,
        target_role="Software Engineer"
    )

    about = suggestions.get("about_section", "")
    assert len(about.strip()) > 0, "About section must not be empty"
    # Verify first-person voice
    assert "I " in about or "I am" in about or "my " in about.lower()
    # Verify only skills present in the resume appear
    assert "Python" in about
    assert suggestions["about_word_count"] > 10
    assert suggestions["about_char_count"] > 50


def test_recruiter_keywords_generation():
    """
    Acceptance criterion: List keywords recruiters search for that match the student's target role.
    """
    agent = LinkedInAgent()
    suggestions = agent.generate_linkedin_suggestions(
        resume_text=SAMPLE_RICH_RESUME,
        target_role="Software Engineer"
    )

    keywords = suggestions.get("recruiter_keywords", [])
    matched = suggestions.get("matched_keywords", [])
    recommended = suggestions.get("recommended_keywords", [])

    assert len(keywords) > 0, "Recruiter keywords list must not be empty"
    assert "Python" in matched or "Python" in keywords
    assert "Docker" in matched or "Docker" in keywords
    assert suggestions["target_role"] == "Software Engineer"


def test_handles_sparse_and_minimal_resumes():
    """
    Acceptance criterion: The feature handles resumes with very little content.
    Must not crash, must return valid <= 220 char headlines, honest first-person About,
    and role keywords.
    """
    agent = LinkedInAgent()

    # 1. Very sparse resume (only 1-2 skills)
    sparse_sug = agent.generate_linkedin_suggestions(
        resume_text=SAMPLE_SPARSE_RESUME,
        target_role="Data Analyst"
    )
    assert sparse_sug["is_sparse"] is True
    assert len(sparse_sug["headline_options"]) == 3
    for h in sparse_sug["headline_options"]:
        assert len(h["headline"]) <= 220
    assert "I am" in sparse_sug["about_section"]
    assert "Python" in sparse_sug["about_section"]
    assert len(sparse_sug["recruiter_keywords"]) > 0

    # 2. Completely empty resume text
    empty_sug = agent.generate_linkedin_suggestions(
        resume_text="",
        target_role="Frontend Developer"
    )
    assert empty_sug["is_sparse"] is True
    assert len(empty_sug["headline_options"]) == 3
    for h in empty_sug["headline_options"]:
        assert len(h["headline"]) <= 220
    assert "I am" in empty_sug["about_section"]

    # 3. Whitespace-only resume
    ws_sug = agent.generate_linkedin_suggestions(
        resume_text="   \n\t  \n  ",
        target_role="Web Developer"
    )
    assert len(ws_sug["headline_options"]) == 3
    for h in ws_sug["headline_options"]:
        assert len(h["headline"]) <= 220


def test_api_analysis_linkedin_suggestions_endpoint(client):
    """
    Tests the GET and POST /api/analysis/<analysis_id>/linkedin-suggestions route (#538).
    """
    test_analysis_id = "test-analysis-linkedin-538"
    save_analysis(test_analysis_id, {
        "id": test_analysis_id,
        "student_id": "test_student",
        "company_name": "Google",
        "target_role": "Software Engineer",
        "resume_text": SAMPLE_RICH_RESUME,
        "results": {
            "target_role": "Software Engineer",
            "resume_text": SAMPLE_RICH_RESUME
        }
    })

    # Test GET endpoint
    with client.session_transaction() as sess:
        sess["user_id"] = "test_student"

    res_get = client.get(f"/api/analysis/{test_analysis_id}/linkedin-suggestions")
    assert res_get.status_code == 200
    data_get = json.loads(res_get.data)
    assert data_get["success"] is True
    assert data_get["analysis_id"] == test_analysis_id
    assert len(data_get["suggestions"]["headline_options"]) == 3
    for h in data_get["suggestions"]["headline_options"]:
        assert len(h["headline"]) <= 220
    assert "I am" in data_get["suggestions"]["about_section"]

    # Test role override via query param
    res_override = client.get(f"/api/analysis/{test_analysis_id}/linkedin-suggestions?target_role=Data+Analyst")
    assert res_override.status_code == 200
    data_override = json.loads(res_override.data)
    assert data_override["suggestions"]["target_role"] == "Data Analyst"


def test_api_direct_linkedin_suggestions_endpoint(client):
    """
    Tests the standalone POST /api/linkedin/suggestions endpoint (#538).
    """
    payload = {
        "resume_text": SAMPLE_RICH_RESUME,
        "target_role": "Backend Developer"
    }
    res = client.post(
        "/api/linkedin/suggestions",
        data=json.dumps(payload),
        content_type="application/json"
    )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert len(data["suggestions"]["headline_options"]) == 3
    for h in data["suggestions"]["headline_options"]:
        assert len(h["headline"]) <= 220
    assert "I am" in data["suggestions"]["about_section"]


def test_api_unauthorized_analysis(client):
    """
    Tests that requesting a non-existent or unauthorized analysis returns 404.
    """
    res = client.get("/api/analysis/non-existent-id-99999/linkedin-suggestions")
    assert res.status_code == 404
    data = json.loads(res.data)
    assert data["success"] is False


def test_dashboard_renders_linkedin_section(client):
    """
    Tests that the candidate dashboard renders the LinkedIn Profile Suggestions
    studio with headlines, about draft, recruiter keywords, and copy buttons (#538).
    """
    test_id = "test-dashboard-linkedin-538"
    save_analysis(test_id, {
        "id": test_id,
        "student_id": "test_student",
        "company_name": "Google",
        "target_role": "Software Engineer",
        "resume_text": SAMPLE_RICH_RESUME,
        "results": {
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 90},
            "skill_gap": [],
            "learning_roadmap": []
        }
    })

    with client.session_transaction() as sess:
        sess["user_id"] = "test_student"

    res = client.get(f"/dashboard/{test_id}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Check container and title
    assert 'id="linkedInSuggestionsSection"' in html
    assert "LinkedIn Profile Suggestions" in html

    # Check 3 headline options and char limit indicator
    assert 'id="linkedinHeadlineText1"' in html
    assert 'id="linkedinHeadlineText2"' in html
    assert 'id="linkedinHeadlineText3"' in html
    assert "Headline Limit: 220 chars" in html

    # Check copy buttons
    assert 'data-copy-target="linkedinHeadlineText1"' in html
    assert 'data-copy-target="linkedinHeadlineText2"' in html
    assert 'data-copy-target="linkedinHeadlineText3"' in html
    assert 'id="btnCopyLinkedInAbout"' in html
    assert 'id="btnCopyLinkedInKeywords"' in html

    # Check About section
    assert 'id="linkedinAboutText"' in html
    assert "First-Person ('I' / 'My')" in html

    # Check Recruiter Keywords
    assert 'id="linkedinMatchedContainer"' in html
    assert 'id="linkedinRecommendedContainer"' in html
