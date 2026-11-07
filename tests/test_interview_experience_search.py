"""
Unit & Integration Tests for Interview Experience Search & Filtering System (#254)
==================================================================================
Tests:
1. Multi-facet search: company, role, verdict, difficulty, round category, year.
2. Configurable sorting: date_desc, date_asc, difficulty_desc, difficulty_asc, company_asc.
3. Full-text search over tips, role, and problem round descriptions.
4. Pagination behavior (page, page_size, total_pages).
5. Dynamic facets generation (companies, verdicts, difficulties, roles, sort options).
6. REST API endpoints:
   - GET /api/interview-experiences/search
   - GET /api/interview-experiences/facets
"""

import pytest
import json

import config
from utils.database import (
    init_db,
    save_interview_experience,
    get_db_connection
)
from utils.experience_search_service import (
    search_and_filter_interview_experiences,
    get_interview_filter_facets
)
from app import app


@pytest.fixture
def search_env(tmp_path, monkeypatch):
    """Sets up an isolated test database with seeded interview experiences."""
    test_db = tmp_path / "test_exp_search.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "search-secret-test"

    # Seed diverse dataset
    save_interview_experience(
        exp_id="exp_s_1",
        student_id="student_1",
        candidate_name="Alice",
        company_name="Google",
        role_title="Software Engineer",
        interview_date="2026-10-10",
        rounds=[
            {"round_name": "Coding 1", "round_type": "Technical", "difficulty": "Hard"},
            {"round_name": "System Design", "round_type": "Architecture", "difficulty": "Hard"}
        ],
        overall_verdict="Offer",
        difficulty_level="Hard",
        tips_and_preparation="Extensive LeetCode dynamic programming and distributed caching."
    )

    save_interview_experience(
        exp_id="exp_s_2",
        student_id="student_2",
        candidate_name="Bob",
        company_name="Microsoft",
        role_title="Data Scientist",
        interview_date="2026-08-15",
        rounds=[
            {"round_name": "ML Screening", "round_type": "Technical", "difficulty": "Medium"},
            {"round_name": "Behavioral", "round_type": "HR", "difficulty": "Easy"}
        ],
        overall_verdict="Rejected",
        difficulty_level="Medium",
        tips_and_preparation="Review bias-variance tradeoff and transformer architectures."
    )

    save_interview_experience(
        exp_id="exp_s_3",
        student_id="student_3",
        candidate_name="Charlie",
        company_name="Amazon",
        role_title="Cloud Support Associate",
        interview_date="2025-11-20",
        rounds=[
            {"round_name": "LP Round", "round_type": "Behavioral", "difficulty": "Easy"}
        ],
        overall_verdict="Offer",
        difficulty_level="Easy",
        tips_and_preparation="Prepare STAR stories aligned with customer obsession."
    )

    save_interview_experience(
        exp_id="exp_s_4",
        student_id="student_4",
        candidate_name="Diana",
        company_name="Google",
        role_title="Product Manager",
        interview_date="2026-09-05",
        rounds=[
            {"round_name": "Product Sense", "round_type": "Design", "difficulty": "Very Hard"}
        ],
        overall_verdict="Pending",
        difficulty_level="Very Hard",
        tips_and_preparation="Product design frameworks and metrics decomposition."
    )

    with app.test_client() as client:
        yield client


def test_filter_by_company_and_role(search_env):
    """Verify exact company and partial role matching."""
    res = search_and_filter_interview_experiences(company_name="Google")
    assert res["total_matches"] == 2
    assert all(e["company_name"] == "Google" for e in res["experiences"])

    res_role = search_and_filter_interview_experiences(role_title="Data Scientist")
    assert res_role["total_matches"] == 1
    assert res_role["experiences"][0]["company_name"] == "Microsoft"


def test_filter_by_verdict_and_difficulty(search_env):
    """Verify verdict and difficulty filtering."""
    offers = search_and_filter_interview_experiences(verdict="Offer")
    assert offers["total_matches"] == 2
    assert all(e["overall_verdict"] == "Offer" for e in offers["experiences"])

    hard_items = search_and_filter_interview_experiences(difficulty="Hard")
    assert hard_items["total_matches"] == 1
    assert hard_items["experiences"][0]["id"] == "exp_s_1"


def test_filter_by_year(search_env):
    """Verify year-based filtering."""
    y2025 = search_and_filter_interview_experiences(year_filter="2025")
    assert y2025["total_matches"] == 1
    assert y2025["experiences"][0]["company_name"] == "Amazon"

    y2026 = search_and_filter_interview_experiences(year_filter="2026")
    assert y2026["total_matches"] == 3


def test_full_text_search(search_env):
    """Verify keyword searching over preparation tips and content."""
    res = search_and_filter_interview_experiences(search_query="customer obsession")
    assert res["total_matches"] == 1
    assert res["experiences"][0]["company_name"] == "Amazon"


def test_sorting_order(search_env):
    """Verify date and difficulty ordering."""
    # Difficulty descending (Very Hard -> Hard -> Medium -> Easy)
    diff_desc = search_and_filter_interview_experiences(sort_by="difficulty_desc")
    diffs = [e["difficulty_level"] for e in diff_desc["experiences"]]
    assert diffs[0] == "Very Hard"
    assert diffs[-1] == "Easy"

    # Date ascending (oldest first: 2025-11-20 -> 2026-08-15 -> 2026-09-05 -> 2026-10-10)
    date_asc = search_and_filter_interview_experiences(sort_by="date_asc")
    dates = [e["interview_date"] for e in date_asc["experiences"]]
    assert dates[0] == "2025-11-20"
    assert dates[-1] == "2026-10-10"


def test_pagination(search_env):
    """Verify page and page_size boundary handling."""
    res_p1 = search_and_filter_interview_experiences(page=1, page_size=2)
    assert res_p1["total_matches"] == 4
    assert res_p1["total_pages"] == 2
    assert len(res_p1["experiences"]) == 2

    res_p2 = search_and_filter_interview_experiences(page=2, page_size=2)
    assert len(res_p2["experiences"]) == 2
    assert res_p1["experiences"][0]["id"] != res_p2["experiences"][0]["id"]


def test_api_search_and_facets_endpoints(search_env):
    """Test GET /api/interview-experiences/search and GET /api/interview-experiences/facets."""
    # Test Search API
    resp = search_env.get("/api/interview-experiences/search?company=Google&sort=difficulty_desc")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_matches"] == 2
    assert data["experiences"][0]["difficulty_level"] == "Very Hard"

    # Test Facets API
    facets_resp = search_env.get("/api/interview-experiences/facets")
    assert facets_resp.status_code == 200
    facets = facets_resp.get_json()["facets"]
    comp_names = [c["name"] for c in facets["companies"]]
    assert "Google" in comp_names
    assert "Microsoft" in comp_names
    assert len(facets["sort_options"]) >= 5
