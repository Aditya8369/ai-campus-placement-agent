"""
Unit and integration tests for Internship Search Filter Panel (#356).
Verifies multi-dimensional filtering across location, work mode, stipend availability,
duration, technology stack, role domain, deadline status, combined filters, and empty state rendering.
"""

import pytest
from agents.internship_agent import InternshipRecommendationAgent
from utils.job_feed_service import JobFeedService, extract_job_filter_metadata
from app import app


@pytest.fixture
def agent():
    """Returns an instance of InternshipRecommendationAgent."""
    return InternshipRecommendationAgent()


def test_extract_job_filter_metadata_dimensions():
    """Verify metadata extraction across work mode, stipend, duration, tech, and deadline."""
    remote_job = {
        "title": "React Frontend Intern",
        "location": "Remote",
        "salary_range": "₹40,000 / month Stipend",
        "duration": "3 Months",
        "required_skills": ["React", "JavaScript"],
        "deadline": "Closes Nov 30, 2026"
    }
    meta = extract_job_filter_metadata(remote_job)
    assert meta["work_mode"] == "Remote"
    assert meta["work_mode_specified"] is True
    assert meta["has_stipend"] is True
    assert meta["stipend_type"] == "Paid Stipend"
    assert meta["duration"] == "3 Months"
    assert "React" in meta["technologies"]
    assert meta["deadline_status"] == "Closing Soon"
    assert len(meta["unspecified_fields"]) == 0


def test_extract_job_filter_metadata_unspecified_tracking():
    """Verify that listings lacking explicit dimensions are tracked in unspecified_fields."""
    sparse_job = {
        "title": "General Apprentice",
        "location": "Remote / Hybrid",
        "description": "General apprentice work."
    }
    meta = extract_job_filter_metadata(sparse_job)
    assert meta["work_mode_specified"] is False
    assert meta["stipend_specified"] is False
    assert meta["duration_specified"] is False
    assert meta["deadline_specified"] is False
    assert "work_mode" in meta["unspecified_fields"]
    assert "stipend" in meta["unspecified_fields"]
    assert "duration" in meta["unspecified_fields"]
    assert "deadline" in meta["unspecified_fields"]


def test_filter_by_location(agent):
    """Verify filtering opportunities by location."""
    res = agent.get_recommendations(
        candidate_skills=["Python", "SQL"],
        location="Bengaluru"
    )
    assert res["success"] is True
    assert res["total_found"] > 0
    for opp in res["recommendations"]:
        assert "bengaluru" in opp["location"].lower() or opp["location"] == "Remote / Hybrid"


def test_filter_by_work_mode(agent):
    """Verify filtering opportunities by work mode (Remote vs On-site vs Hybrid)."""
    # Remote
    res_remote = agent.get_recommendations(
        candidate_skills=["Python", "React"],
        work_mode="Remote"
    )
    assert res_remote["success"] is True
    assert res_remote["total_found"] > 0
    for opp in res_remote["recommendations"]:
        assert opp["work_mode"] == "Remote" or not opp["work_mode_specified"]

    # On-site
    res_onsite = agent.get_recommendations(
        candidate_skills=["Python"],
        work_mode="On-site",
        include_unspecified=False
    )
    assert res_onsite["success"] is True
    assert res_onsite["total_found"] > 0
    for opp in res_onsite["recommendations"]:
        assert opp["work_mode"] == "On-site"


def test_filter_by_stipend(agent):
    """Verify filtering opportunities by stipend availability."""
    res_paid = agent.get_recommendations(
        candidate_skills=["Python"],
        stipend_type="Paid Stipend",
        include_unspecified=False
    )
    assert res_paid["success"] is True
    assert res_paid["total_found"] > 0
    for opp in res_paid["recommendations"]:
        assert opp["stipend_specified"] is True
        assert opp["stipend_type"] == "Paid Stipend"


def test_filter_by_duration(agent):
    """Verify filtering opportunities by duration (3 Months vs 6 Months)."""
    res_3m = agent.get_recommendations(
        candidate_skills=["Python"],
        duration="3 Months",
        include_unspecified=False
    )
    assert res_3m["success"] is True
    assert res_3m["total_found"] > 0
    for opp in res_3m["recommendations"]:
        assert "3" in opp["duration"]

    res_6m = agent.get_recommendations(
        candidate_skills=["Java"],
        duration="6 Months",
        include_unspecified=False
    )
    assert res_6m["success"] is True
    assert res_6m["total_found"] > 0
    for opp in res_6m["recommendations"]:
        assert "6" in opp["duration"]


def test_filter_by_technology(agent):
    """Verify filtering opportunities by specific technology/skill."""
    res_react = agent.get_recommendations(
        candidate_skills=["React", "TypeScript"],
        technology="React"
    )
    assert res_react["success"] is True
    assert res_react["total_found"] > 0
    for opp in res_react["recommendations"]:
        assert (
            any("react" in t.lower() for t in opp["technologies"])
            or "react" in opp["title"].lower()
            or "react" in opp["description"].lower()
        )


def test_filter_by_role(agent):
    """Verify filtering opportunities by domain/role category."""
    res_backend = agent.get_recommendations(
        candidate_skills=["Python", "FastAPI"],
        preferred_role="Backend Developer"
    )
    assert res_backend["success"] is True
    assert res_backend["total_found"] > 0
    for opp in res_backend["recommendations"]:
        title_lower = opp["title"].lower()
        assert any(k in title_lower for k in ["backend", "api", "systems", "fastapi", "sde", "engineer"])


def test_filter_by_deadline_status(agent):
    """Verify filtering opportunities by deadline status (Closing Soon)."""
    res_closing = agent.get_recommendations(
        candidate_skills=["Python"],
        deadline_status="Closing Soon",
        include_unspecified=False
    )
    assert res_closing["success"] is True
    assert res_closing["total_found"] > 0
    for opp in res_closing["recommendations"]:
        assert opp["deadline_status"] == "Closing Soon"


def test_combined_filters(agent):
    """Verify combining multiple filters simultaneously."""
    res_combined = agent.get_recommendations(
        candidate_skills=["Python"],
        location="Bengaluru",
        stipend_type="Paid Stipend",
        duration="3 Months",
        include_unspecified=False
    )
    assert res_combined["success"] is True
    for opp in res_combined["recommendations"]:
        assert "bengaluru" in opp["location"].lower()
        assert opp["stipend_type"] == "Paid Stipend"
        assert "3" in opp["duration"]


def test_web_route_filter_panel_rendering():
    """Verify HTML rendering of the filter panel, controls, and active filter tags."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/internships?student_id=test_student&location=Bengaluru&work_mode=Hybrid&duration=3+Months")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Internship Recommendation Engine" in html
        assert "Search &amp; Filter Panel" in html or "Search & Filter Panel" in html
        assert "Active Filters:" in html
        assert "Location: Bengaluru" in html
        assert "Mode: Hybrid" in html
        assert "Duration: 3 Months" in html
        assert "Clear Filters" in html
        assert "Match Opportunities" in html


def test_web_route_filter_panel_empty_state():
    """Verify that impossible filter combinations render the helpful empty state and reset button."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get(
            "/internships?student_id=test_student&location=Pune&work_mode=Remote&technology=NonExistentTechXYZ&include_unspecified=false"
        )
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "No Matching Internships Found" in html
        assert "Reset All Filters" in html
        assert "btnResetFiltersEmpty" in html


def test_web_route_filter_panel_ajax_json():
    """Verify AJAX / JSON responses include filters_applied, filter_options, and recommendation items."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get(
            "/internships?student_id=test_student&work_mode=Remote&stipend=Paid+Stipend",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "filters_applied" in data
        assert data["filters_applied"]["work_mode"] == "Remote"
        assert data["filters_applied"]["stipend"] == "Paid Stipend"
        assert "filter_options" in data
        assert "work_modes" in data["filter_options"]
        assert "durations" in data["filter_options"]
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0
        top = data["recommendations"][0]
        assert "work_mode" in top
        assert "duration" in top
        assert "stipend_type" in top
        assert "unspecified_fields" in top
