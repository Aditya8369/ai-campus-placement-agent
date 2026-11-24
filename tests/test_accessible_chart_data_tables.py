"""
Test Suite for Accessible Chart Data Tables (#task-accessible-chart-tables)
============================================================================
Verifies:
- Data table alternative views for all major charts across the application.
- Inclusion of explicit labels, scope attributes, units of measurement, and captions.
- Keyboard navigation hooks (focusable wrappers, aria-expanded, aria-controls, toggle buttons).
- Accessible empty data states with role="status" and aria-live="polite".
"""

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

from utils.formatters import format_datetime_ist, format_date_ist


@pytest.fixture
def jinja_env():
    env = Environment(loader=FileSystemLoader("templates"))
    env.filters["format_datetime_ist"] = format_datetime_ist
    env.filters["format_date_ist"] = format_date_ist
    return env


def test_dashboard_progress_trend_table_rendered_with_units(jinja_env):
    """Verifies the longitudinal progress trend chart includes an accessible data table with units."""
    template = jinja_env.get_template("dashboard.html")

    dummy_analysis = {
        "id": "test-analysis-1",
        "company_name": "Google",
        "resume_filename": "sample_resume.pdf",
        "created_at": "2026-03-01 10:00:00",
        "results": {
            "section_status": {"resume_analysis": "available"}
        }
    }
    dummy_trend_series = {
        "labels": ["v1", "v2"],
        "dates": ["2026-03-01", "2026-03-05"],
        "ats_scores": [72, 85],
        "match_scores": [60, 78],
        "gap_counts": [5, 2],
        "filenames": ["resume_v1.pdf", "resume_v2.pdf"]
    }

    html = template.render(
        analysis=dummy_analysis,
        analysis_id="test-analysis-1",
        versions=[{"id": "v1"}, {"id": "v2"}],
        trend_series=dummy_trend_series,
        delta_data={"newly_matched_keywords": [], "resolved_skill_gaps": [], "remaining_skill_gaps": []},
        sc={"total_skills": 10, "matched_count": 7, "missing_count": 3, "match_percentage": 70, "missing_percentage": 30},
        r_sum={"readiness_badge": "success", "readiness_icon": "fa-check", "readiness_status": "Ready"},
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    # 1. Toggle Button
    toggle_btn = soup.find(id="btnToggleProgressTrendTable")
    assert toggle_btn is not None, "Toggle button for progress trend chart table must exist"
    assert toggle_btn.get("aria-expanded") == "false"
    assert toggle_btn.get("aria-controls") == "progressTrendTableWrapper"

    # 2. Table Wrapper & Accessibility
    wrapper = soup.find(id="progressTrendTableWrapper")
    assert wrapper is not None, "Progress trend table wrapper must exist"
    assert wrapper.get("role") == "region"
    assert wrapper.get("tabindex") == "0"

    # 3. Table Headers & Units
    table = soup.find(id="progressTrendTable")
    assert table is not None
    assert table.find("caption") is not None, "Table must have a descriptive caption"

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("ATS Profile Score" in h and "pts" in h for h in headers), "Header must include 'pts' unit"
    assert any("Job Match Score" in h and "%" in h for h in headers), "Header must include '%' unit"
    assert any("Skill Gaps" in h and "count" in h for h in headers), "Header must include 'count' unit"

    # 4. Values include units
    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("72 pts" in c for c in cells)
    assert any("60%" in c for c in cells)
    assert any("5 gaps" in c for c in cells)


def test_dashboard_progress_trend_empty_state(jinja_env):
    """Verifies that empty progress trend data shows accessible empty state."""
    template = jinja_env.get_template("dashboard.html")

    html = template.render(
        analysis={"id": "test", "company_name": "Google", "results": {}},
        analysis_id="test",
        versions=[],
        trend_series={"labels": [], "dates": []},
        delta_data={},
        sc={"total_skills": 0},
        r_sum={"readiness_badge": "warning", "readiness_icon": "fa-clock", "readiness_status": "Pending"},
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")
    empty_state = soup.find(id="progressTrendEmptyState")
    assert empty_state is not None, "Empty state must be rendered when trend series has no data"
    assert empty_state.get("role") == "status"
    assert empty_state.get("aria-live") == "polite"
    assert "No Historical Progress Data Available" in empty_state.get_text()


def test_dashboard_skills_comparison_table_rendered_with_units(jinja_env):
    """Verifies skills comparison chart includes accessible data table view with units."""
    template = jinja_env.get_template("dashboard.html")

    sc_data = {
        "total_skills": 15,
        "matched_count": 12,
        "missing_count": 3,
        "match_percentage": 80,
        "missing_percentage": 20,
        "matched_skills": ["Python", "SQL"],
        "missing_skills": ["Docker"]
    }

    html = template.render(
        analysis={"id": "test", "company_name": "Google", "results": {}},
        analysis_id="test",
        versions=[],
        trend_series={"labels": []},
        delta_data={},
        sc=sc_data,
        r_sum={"readiness_badge": "success", "readiness_icon": "fa-check", "readiness_status": "Ready"},
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    # Toggle Button
    toggle_btn = soup.find(id="btnToggleSkillsComparisonTable")
    assert toggle_btn is not None
    assert toggle_btn.get("aria-controls") == "skillsTableWrapper"

    # Table & Units
    table = soup.find(id="skillsComparisonTable")
    assert table is not None
    assert table.find("caption") is not None

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("Skill Count" in h for h in headers)
    assert any("Share (%)" in h for h in headers)

    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("12 skills" in c for c in cells)
    assert any("80%" in c for c in cells)
    assert any("3 skills" in c for c in cells)
    assert any("20%" in c for c in cells)


def test_interview_history_score_trend_table(jinja_env):
    """Verifies interview history score progression chart has accessible table and empty state."""
    template = jinja_env.get_template("interview_history.html")

    analytics_with_data = {
        "score_trend": [
            {"company": "Amazon", "date": "2026-03-01", "score": 85},
            {"company": "Microsoft", "date": "2026-03-04", "score": 65}
        ],
        "technical_average": 78,
        "hr_average": 82,
        "behavioral_average": 74,
        "strengths": ["Clear communication"],
        "weaknesses": []
    }

    html = template.render(
        analytics=analytics_with_data,
        sessions=[],
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    toggle_btn = soup.find(id="btnToggleScoreTrendTable")
    assert toggle_btn is not None
    assert toggle_btn.get("aria-controls") == "scoreTrendTableWrapper"

    table = soup.find(id="scoreTrendTable")
    assert table is not None
    assert table.find("caption") is not None

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("Performance Score" in h and "%" in h for h in headers)

    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("85%" in c for c in cells)
    assert any("65%" in c for c in cells)

    # Test empty state
    html_empty = template.render(
        analytics={"score_trend": []},
        sessions=[],
        csrf_token=lambda: "token"
    )
    soup_empty = BeautifulSoup(html_empty, "html.parser")
    empty_el = soup_empty.find(id="scoreTrendEmptyState")
    assert empty_el is not None
    assert empty_el.get("role") == "status"
    assert empty_el.get("aria-live") == "polite"


def test_compare_previous_ats_trend_table(jinja_env):
    """Verifies compare previous revisions chart includes accessible table view with units."""
    template = jinja_env.get_template("compare_previous.html")

    comparison_data = {
        "has_previous": True,
        "previous_version": 1,
        "current_version": 2,
        "score_difference": 10,
        "ats_after": 85,
        "ats_before": 75,
        "skills_added": ["Docker"],
        "skills_removed": [],
        "skills_retained": [],
        "weaknesses_fixed": [],
        "weaknesses_still_present": [],
        "target_role": "Backend Engineer",
        "company_name": "Google",
        "trend_chart": [
            {"version": "v1", "version_number": 1, "ats_score": 75, "date": "2026-03-01"},
            {"version": "v2", "version_number": 2, "ats_score": 85, "date": "2026-03-05"}
        ]
    }

    html = template.render(
        comparison=comparison_data,
        analysis_id="curr-id",
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    toggle_btn = soup.find(id="btnToggleAtsTrendTable")
    assert toggle_btn is not None
    assert toggle_btn.get("aria-controls") == "atsTrendTableWrapper"

    table = soup.find(id="atsTrendTable")
    assert table is not None
    assert table.find("caption") is not None

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("ATS Score" in h and "pts" in h for h in headers)

    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("75 pts" in c for c in cells)
    assert any("85 pts" in c for c in cells)


def test_admin_ai_metrics_daily_table(jinja_env):
    """Verifies admin AI metrics chart includes daily metrics table with ms and count units."""
    template = jinja_env.get_template("admin_ai_metrics.html")

    summary_data = {
        "total_calls": 50,
        "successful_calls": 48,
        "failed_calls": 2,
        "failure_rate_pct": 4.0,
        "avg_latency_ms": 1250,
        "p95_latency_ms": 2800,
        "common_errors": [],
        "daily_metrics": [
            {
                "date": "2026-03-01",
                "total_calls": 30,
                "successful_calls": 29,
                "failed_calls": 1,
                "avg_latency_ms": 1100,
                "p95_latency_ms": 2400
            }
        ]
    }

    html = template.render(
        summary=summary_data,
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    toggle_btn = soup.find(id="btnToggleDailyMetricsTable")
    assert toggle_btn is not None
    assert toggle_btn.get("aria-controls") == "dailyMetricsTableWrapper"

    table = soup.find(id="dailyMetricsTable")
    assert table is not None
    assert table.find("caption") is not None

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("Avg Latency" in h and "ms" in h for h in headers)
    assert any("p95 Latency" in h and "ms" in h for h in headers)
    assert any("Total Calls" in h and "count" in h for h in headers)

    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("30 calls" in c for c in cells)
    assert any("1100 ms" in c for c in cells)
    assert any("2400 ms" in c for c in cells)


def test_batch_compare_radar_dimensions_table(jinja_env):
    """Verifies batch company comparison radar chart includes multi-dimensional capability table."""
    template = jinja_env.get_template("batch_compare.html")

    comparisons_data = [
        {
            "rank": 1,
            "company_name": "Google",
            "tier_label": "Tier 1 Product",
            "tier_badge": "success",
            "likelihood_tier": "Strong Fit",
            "offer_probability": 85,
            "radar_scores": [88, 80, 85, 78, 82, 85],
            "style": {"background": "rgba(26,115,232,0.1)", "border": "#1a73e8"}
        }
    ]

    html = template.render(
        comparisons=comparisons_data,
        radar_data_json="{}",
        summary_insights={"common_missing_skills": []},
        csrf_token=lambda: "token"
    )

    soup = BeautifulSoup(html, "html.parser")

    toggle_btn = soup.find(id="btnToggleRadarTable")
    assert toggle_btn is not None
    assert toggle_btn.get("aria-controls") == "radarTableWrapper"

    table = soup.find(id="radarDimensionsTable")
    assert table is not None
    assert table.find("caption") is not None

    headers = [th.get_text(strip=True) for th in table.find_all("th", scope="col")]
    assert any("Coding & DSA" in h and "pts" in h for h in headers)
    assert any("System Design" in h and "pts" in h for h in headers)
    assert any("ATS Score" in h and "pts" in h for h in headers)

    cells = [td.get_text(strip=True) for td in table.find_all("td")]
    assert any("88 pts" in c for c in cells)
    assert any("80 pts" in c for c in cells)
    assert any("85 pts" in c for c in cells)
