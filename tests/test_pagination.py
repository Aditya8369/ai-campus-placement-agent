import pytest
from unittest.mock import patch
import config
from app import app
from utils.pagination import Pagination
from utils.database import (
    init_db,
    save_job_application,
    save_coding_submission,
    create_interview_session,
    update_interview_session,
    save_calendar_event,
    save_interview_experience,
    save_analysis
)


# ==============================================================================
# Unit Tests for utils.pagination.Pagination
# ==============================================================================

def test_pagination_basic_calculation():
    items = list(range(1, 26))  # 25 items
    p = Pagination(items=items, page=1, per_page=10, base_url="/test")

    assert p.total_records == 25
    assert p.total_pages == 3
    assert p.page == 1
    assert p.per_page == 10
    assert len(p.items) == 10
    assert p.items == list(range(1, 11))
    assert p.has_prev is False
    assert p.has_next is True
    assert p.prev_page is None
    assert p.next_page == 2
    assert p.start_index == 1
    assert p.end_index == 10


def test_pagination_middle_and_last_page():
    items = list(range(1, 26))  # 25 items
    # Page 2
    p2 = Pagination(items=items, page=2, per_page=10, base_url="/test")
    assert p2.page == 2
    assert len(p2.items) == 10
    assert p2.items == list(range(11, 21))
    assert p2.has_prev is True
    assert p2.has_next is True
    assert p2.prev_page == 1
    assert p2.next_page == 3
    assert p2.start_index == 11
    assert p2.end_index == 20

    # Page 3 (last page with remainder)
    p3 = Pagination(items=items, page=3, per_page=10, base_url="/test")
    assert p3.page == 3
    assert len(p3.items) == 5
    assert p3.items == list(range(21, 26))
    assert p3.has_prev is True
    assert p3.has_next is False
    assert p3.prev_page == 2
    assert p3.next_page is None
    assert p3.start_index == 21
    assert p3.end_index == 25


def test_pagination_bounds_and_invalid_inputs():
    items = [1, 2, 3]

    # Page below 1 clamps to 1
    p_low = Pagination(items=items, page=0, per_page=10, base_url="/test")
    assert p_low.page == 1

    p_neg = Pagination(items=items, page=-5, per_page=10, base_url="/test")
    assert p_neg.page == 1

    # Page above total_pages clamps to total_pages
    p_high = Pagination(items=items, page=999, per_page=10, base_url="/test")
    assert p_high.page == 1

    # per_page <= 0 is clamped to minimum 1
    p_invalid_per = Pagination(items=items, page=1, per_page=0, base_url="/test")
    assert p_invalid_per.per_page == 1


def test_pagination_empty_items():
    p = Pagination(items=[], page=1, per_page=10, base_url="/test")
    assert p.total_records == 0
    assert p.total_pages == 1
    assert p.page == 1
    assert p.items == []
    assert p.has_prev is False
    assert p.has_next is False
    assert p.start_index == 0
    assert p.end_index == 0


def test_pagination_url_for_page_preserves_query_parameters():
    endpoint_args = {
        "search": "Senior Software Engineer",
        "status": "Interview",
        "location": "Bangalore",
        "job_type": "Full-Time",
        "page": "1"
    }
    p = Pagination(items=list(range(30)), page=1, per_page=10, endpoint_args=endpoint_args, base_url="/applications")

    url_p2 = p.url_for_page(2)
    assert url_p2.startswith("/applications?")
    assert "page=2" in url_p2
    assert "status=Interview" in url_p2
    assert "location=Bangalore" in url_p2
    assert "job_type=Full-Time" in url_p2
    assert "search=Senior+Software+Engineer" in url_p2 or "search=Senior%20Software%20Engineer" in url_p2


def test_pagination_page_range_with_ellipsis():
    # Few pages: no ellipsis
    p_few = Pagination(items=list(range(20)), page=1, per_page=10)
    assert p_few.page_range() == [1, 2]

    # Many pages (10 pages)
    items_100 = list(range(100))
    # At beginning
    p_start = Pagination(items=items_100, page=1, per_page=10)
    range_start = p_start.page_range()
    assert range_start[0] == 1
    assert None in range_start
    assert range_start[-1] == 10

    # In middle (page 5)
    p_mid = Pagination(items=items_100, page=5, per_page=10)
    range_mid = p_mid.page_range()
    assert 5 in range_mid
    assert range_mid[0] == 1
    assert range_mid[-1] == 10
    assert range_mid.count(None) == 2  # Ellipsis before and after


def test_pagination_to_dict():
    p = Pagination(items=list(range(15)), page=2, per_page=5, base_url="/api/data")
    d = p.to_dict()
    assert d["page"] == 2
    assert d["per_page"] == 5
    assert d["total_records"] == 15
    assert d["total_pages"] == 3
    assert d["has_prev"] is True
    assert d["has_next"] is True
    assert d["prev_page"] == 1
    assert d["next_page"] == 3
    assert d["start_index"] == 6
    assert d["end_index"] == 10


# ==============================================================================
# Integration / Route Tests
# ==============================================================================

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_pagination.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            yield client


def test_applications_pagination_navigation_and_filters(client):
    # Seed 15 applications for student 'test_student'
    for i in range(1, 16):
        save_job_application(
            app_id=f"app-{i:03d}",
            student_id="test_student",
            company_name=f"Company {i:02d}",
            role_title="Software Developer",
            status="Interview" if i % 2 == 0 else "Applied",
            application_date="2026-03-01",
            location="Remote",
            job_type="Full-Time",
            experience_level="Entry-Level"
        )

    # 1. Page 1 request (per_page=5)
    res_p1 = client.get("/applications?student_id=test_student&per_page=5&page=1")
    assert res_p1.status_code == 200
    html_p1 = res_p1.data.decode("utf-8")

    # Check total records and current page display
    assert "Showing" in html_p1
    assert "1" in html_p1  # start_index
    assert "5" in html_p1  # end_index
    assert "15" in html_p1  # total_records
    assert "Page" in html_p1
    assert "3" in html_p1  # total_pages

    # Check Previous and Next buttons
    assert "btn-pagination-prev" in html_p1
    assert "btn-pagination-next" in html_p1
    # On page 1, previous should be disabled
    assert 'class="page-link rounded-start-pill px-3 py-1 btn-pagination-prev disabled"' in html_p1 or 'disabled' in html_p1

    # 2. Page 2 request
    res_p2 = client.get("/applications?student_id=test_student&per_page=5&page=2")
    assert res_p2.status_code == 200
    html_p2 = res_p2.data.decode("utf-8")
    assert "Showing" in html_p2
    assert "6" in html_p2  # start_index
    assert "10" in html_p2  # end_index

    # 3. Filter retention during pagination
    res_filtered = client.get("/applications?student_id=test_student&status=Interview&per_page=3&page=1")
    assert res_filtered.status_code == 200
    html_filt = res_filtered.data.decode("utf-8")
    # Total interview records = 7
    assert "7" in html_filt
    # Next link must preserve status=Interview
    assert "status=Interview" in html_filt
    assert "page=2" in html_filt

    # 4. JSON API endpoint pagination verification
    api_res = client.get("/api/applications?student_id=test_student&per_page=5&page=2")
    assert api_res.status_code == 200
    api_data = api_res.get_json()
    assert api_data["success"] is True
    assert len(api_data["applications"]) == 5
    assert api_data["pagination"]["page"] == 2
    assert api_data["pagination"]["total_records"] == 15
    assert api_data["pagination"]["total_pages"] == 3


def test_applications_pagination_empty_results(client):
    # Empty student with no applications
    res = client.get("/applications?student_id=empty_student")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Should show empty state without crashing or breaking
    assert "No Applications Match Your Filters" in html
    # Record count badge should show 0 matching records
    assert 'id="recordCountBadge"' in html
    assert "Showing 0 of 0 matching" in html


def test_coding_submissions_pagination(client):
    # Seed 12 coding submissions
    for i in range(1, 13):
        save_coding_submission(
            sub_id=f"sub-{i:03d}",
            student_id="test_coder",
            question_title=f"Algorithm Problem {i}",
            language="Python",
            code="def solution(): pass",
            passed=(i % 2 == 0),
            score=100 if i % 2 == 0 else 50,
            tests_passed=10,
            total_tests=10
        )

    res = client.get("/coding-submissions?student_id=test_coder&per_page=5&page=1")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "12" in html  # total_records


def test_interview_history_pagination(client):
    # Seed 14 interview sessions tied to analyses
    for i in range(1, 15):
        analysis_id = f"analysis-hist-{i:03d}"
        session_id = f"{analysis_id}_tech"
        dummy_results = {
            "ats_score": 80,
            "interview_questions": {
                "technical": [f"Question {i}"]
            }
        }
        save_analysis(
            analysis_id=analysis_id,
            resume_filename=f"candidate_{i}.pdf",
            company_name=f"Company {i}",
            job_description="Backend Engineer",
            results_dict=dummy_results,
            student_id="test_candidate"
        )
        questions = [{"index": 0, "type": "Technical", "question": f"Question {i}"}]
        create_interview_session(session_id, analysis_id, questions)
        answers = [{"question_index": 0, "type": "Technical", "question": f"Question {i}", "answer": "Answer", "evaluation": {"score": 85}}]
        update_interview_session(session_id, current_question_index=0, answers_list=answers, completed=True)

    res = client.get("/interview-history?student_id=test_candidate&per_page=5&page=2")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "14" in html  # total records


def test_leaderboard_pagination(client):
    # Cohort benchmarks are seeded with 24 default peers
    res = client.get("/leaderboard?per_page=5&page=1")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "24" in html  # total records in seeded cohort benchmarks

    api_res = client.get("/api/leaderboard?per_page=5&page=1")
    assert api_res.status_code == 200
    api_data = api_res.get_json()
    assert api_data["success"] is True
    assert api_data["pagination"]["page"] == 1
    assert api_data["pagination"]["total_records"] == 24
    assert api_data["pagination"]["total_pages"] == 5
    assert len(api_data["leaderboard"]) == 5


def test_placement_calendar_pagination_and_filters(client):
    # Seed 15 calendar events
    for i in range(1, 16):
        save_calendar_event(
            event_id=f"evt-{i:03d}",
            student_id="test_calendar_user",
            title=f"Prep Session {i}",
            event_type="preparation",
            event_date="2026-03-15",
            company_name=f"Org {i}",
            priority="High"
        )

    res = client.get("/calendar?student_id=test_calendar_user&month=2026-03&per_page=5&page=1")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "15" in html  # total events
    assert "month=2026-03" in html  # Filter preserved in pagination link


def test_interview_experiences_pagination_and_search_retention(client):
    # Seed 12 interview experiences
    for i in range(1, 13):
        save_interview_experience(
            exp_id=f"exp-{i:03d}",
            student_id="contributor_1",
            candidate_name="Anonymous",
            company_name="Google" if i <= 6 else "Amazon",
            role_title="SWE Intern",
            interview_date="2026-02-20",
            rounds=[{"round_number": 1, "category": "Technical", "description": "Graph algorithms", "questions": ["Dijkstra"]}],
            overall_verdict="Offer",
            difficulty_level="Medium",
            tips_and_preparation="Practice LeetCode mediums"
        )

    # Page 1 with company filter
    res = client.get("/interview-experiences?company=Google&per_page=4&page=1")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "6" in html  # Total 6 Google experiences
    assert "company=Google" in html  # Filter preserved


def test_history_pagination(client):
    # Seed 10 saved analyses
    for i in range(1, 11):
        save_analysis(
            analysis_id=f"analysis-{i:03d}",
            resume_filename="resume.pdf",
            company_name=f"Company {i}",
            job_description=f"Role {i}",
            results_dict={"ats_score": 70 + i, "summary": f"Test summary {i}"},
            student_id="default_student"
        )

    res = client.get("/history?per_page=4&page=2")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "btn-pagination-prev" in html
    assert "btn-pagination-next" in html
    assert "10" in html


def test_pagination_mobile_responsiveness_markup(client):
    # Test that mobile responsiveness classes are present
    p = Pagination(items=list(range(50)), page=2, per_page=10, base_url="/applications")
    assert p.total_pages == 5

    res = client.get("/applications?student_id=dummy&per_page=10&page=1")
    # Verify CSS contains mobile responsive rules
    css_res = client.get("/static/css/style.css")
    assert css_res.status_code == 200
    css_content = css_res.data.decode("utf-8")
    assert ".pagination-container" in css_content
    assert "@media (max-width: 575.98px)" in css_content
