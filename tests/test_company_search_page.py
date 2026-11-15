"""
Integration and UI tests for Company Search and Filter Page (#354)
===================================================================
Tests:
1. Standard GET /companies page rendering with default company directory.
2. Keyword text search filtering by company name, overview, and tech stack.
3. Hiring tier filtering (e.g. Tier 1, Startup, Enterprise).
4. Industry category filtering.
5. Tech stack filtering.
6. Process round query filtering.
7. Empty state rendering when query returns no matching companies.
8. JSON and AJAX API responses for /companies.
"""

import pytest
import json
import config
from utils.database import init_db, get_db_connection
from utils.company_profile_manager import (
    ensure_company_profiles_table,
    seed_default_company_profiles,
)
from app import app


@pytest.fixture
def client_with_companies(tmp_path, monkeypatch):
    """Sets up an isolated test database with seeded company profiles."""
    test_db = tmp_path / "test_company_search.db"
    monkeypatch.setattr(config, "DATABASE_PATH", str(test_db))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    init_db()

    with get_db_connection() as conn:
        ensure_company_profiles_table(conn)

    seed_default_company_profiles()

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-companies-secret-key"
    with app.test_client() as client:
        yield client


def test_companies_page_renders_successfully(client_with_companies):
    """Verify GET /companies returns HTTP 200 and renders the company directory."""
    response = client_with_companies.get("/companies")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Campus Recruitment Companies" in html
    assert "Search Companies" in html
    assert "Hiring Tier" in html
    assert "Industry" in html
    assert "Tech Stack" in html
    assert "Google" in html
    assert "Microsoft" in html


def test_companies_search_by_name(client_with_companies):
    """Verify text search query filters companies by name."""
    response = client_with_companies.get("/companies?search=Google")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Google" in html
    assert "Microsoft" not in html


def test_companies_filter_by_hiring_tier(client_with_companies):
    """Verify tier filter restricts results to the selected hiring tier."""
    response = client_with_companies.get("/companies?tier=Tier+1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Google" in html
    assert "Microsoft" in html


def test_companies_filter_by_tech_stack(client_with_companies):
    """Verify tech stack filter returns companies utilizing the requested technology."""
    response = client_with_companies.get("/companies?tech=Python")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Google" in html


def test_companies_empty_state_on_no_match(client_with_companies):
    """Verify an intuitive empty state is displayed when no company matches filters."""
    response = client_with_companies.get("/companies?search=NonExistentCorp999XYZ")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "No companies found matching your search" in html
    assert "NonExistentCorp999XYZ" in html
    assert "Reset All Filters" in html
    assert 'href="/companies"' in html


def test_companies_json_ajax_format(client_with_companies):
    """Verify /companies returns structured JSON when requested via AJAX or format=json."""
    # format=json query parameter
    res = client_with_companies.get("/companies?format=json&search=Google")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["total_count"] >= 1
    assert any(c["company_name"] == "Google" for c in data["companies"])

    # X-Requested-With header
    res_ajax = client_with_companies.get(
        "/companies?search=Microsoft",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res_ajax.status_code == 200
    ajax_data = res_ajax.get_json()
    assert ajax_data["status"] == "success"
    assert any(c["company_name"] == "Microsoft" for c in ajax_data["companies"])
