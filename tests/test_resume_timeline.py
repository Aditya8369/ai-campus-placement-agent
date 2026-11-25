"""
Unit & Integration Tests for Resume Timeline & Gap Analysis (#840)
==================================================================
Tests parsing of mixed date formats, gap and overlap detection,
inverted date validation, future date framing, neutral phrasing,
flag dismissal, and REST API endpoints.
"""

import json
import pytest
from utils.resume_timeline_service import (
    ResumeDate,
    parse_single_date,
    parse_date_range,
    calculate_months_between,
    calculate_overlap_months,
    extract_timeline_items_from_text,
    analyze_resume_timeline,
    make_flag_id,
)


class TestDateParsing:
    """Tests tolerant date parsing across diverse common formats."""

    def test_month_name_and_year(self):
        d1 = parse_single_date("Jan 2024")
        assert d1 is not None
        assert d1.year == 2024
        assert d1.month == 1
        assert d1.precision == "month"
        assert d1.format_display() == "Jan 2024"

        d2 = parse_single_date("December 2021", is_end_date=True)
        assert d2 is not None
        assert d2.year == 2021
        assert d2.month == 12

    def test_numeric_formats(self):
        # MM/YYYY
        d1 = parse_single_date("04/2023")
        assert d1 is not None
        assert d1.year == 2023
        assert d1.month == 4

        # MM-YYYY
        d2 = parse_single_date("11-2022")
        assert d2 is not None
        assert d2.year == 2022
        assert d2.month == 11

        # YYYY-MM
        d3 = parse_single_date("2024-06")
        assert d3 is not None
        assert d3.year == 2024
        assert d3.month == 6

    def test_season_formats(self):
        d_spring = parse_single_date("Spring 2022")
        assert d_spring is not None
        assert d_spring.year == 2022
        assert d_spring.month == 3

        d_summer = parse_single_date("Summer 2023")
        assert d_summer is not None
        assert d_summer.year == 2023
        assert d_summer.month == 6

        d_fall = parse_single_date("Fall 2021")
        assert d_fall is not None
        assert d_fall.year == 2021
        assert d_fall.month == 9

    def test_year_only(self):
        d_start = parse_single_date("2020", is_end_date=False)
        assert d_start is not None
        assert d_start.year == 2020
        assert d_start.month == 1
        assert d_start.precision == "year"
        assert d_start.format_display() == "2020"

        d_end = parse_single_date("2024", is_end_date=True)
        assert d_end is not None
        assert d_end.year == 2024
        assert d_end.month == 12

    def test_present_terms(self):
        for term in ["Present", "current", "Ongoing", "Till Date", "Now"]:
            d = parse_single_date(term, is_end_date=True)
            assert d is not None
            assert d.is_present is True
            assert d.format_display() == "Present"

    def test_unparseable_garbage_returns_none_without_exception(self):
        invalid_inputs = ["", None, "xyz", "Not a date", "12345", "@#$%", "N/A", "Unknown"]
        for item in invalid_inputs:
            assert parse_single_date(item) is None

    def test_date_range_parsing(self):
        r1 = parse_date_range("Jan 2021 - Dec 2022")
        assert r1 is not None
        assert r1[0].year == 2021 and r1[0].month == 1
        assert r1[1].year == 2022 and r1[1].month == 12

        r2 = parse_date_range("05/2020 to Present")
        assert r2 is not None
        assert r2[0].year == 2020 and r2[0].month == 5
        assert r2[1].is_present is True

        r3 = parse_date_range("2019 – 2023")
        assert r3 is not None
        assert r3[0].year == 2019
        assert r3[1].year == 2023


class TestTimelineCalculations:
    """Tests month differences and interval overlap calculations."""

    def test_consecutive_months_have_zero_gap(self):
        # End in May (month 5), Start in June (month 6)
        end_d = ResumeDate(year=2023, month=5)
        start_d = ResumeDate(year=2023, month=6)
        gap = calculate_months_between(end_d, start_d)
        assert gap == 0

    def test_gap_calculation(self):
        # End in Jan 2022 (month 1), Start in Sep 2022 (month 9) -> 7 full intervening months
        end_d = ResumeDate(year=2022, month=1)
        start_d = ResumeDate(year=2022, month=9)
        gap = calculate_months_between(end_d, start_d)
        assert gap == 7

        # 12-month gap across years: Dec 2021 to Jan 2023 -> 12 months
        end_d2 = ResumeDate(year=2021, month=12)
        start_d2 = ResumeDate(year=2023, month=1)
        gap2 = calculate_months_between(end_d2, start_d2)
        assert gap2 == 12

    def test_overlap_calculation(self):
        # Range A: Jan 2022 (m 1) to Dec 2022 (m 12)
        # Range B: Jun 2022 (m 6) to May 2023 (m 17)
        # Overlap: Jun 2022 to Dec 2022 = 7 months (6, 7, 8, 9, 10, 11, 12)
        a_s = ResumeDate(year=2022, month=1)
        a_e = ResumeDate(year=2022, month=12)
        b_s = ResumeDate(year=2022, month=6)
        b_e = ResumeDate(year=2023, month=5)
        overlap = calculate_overlap_months(a_s, a_e, b_s, b_e)
        assert overlap == 7

        # Disjoint ranges have 0 overlap
        c_s = ResumeDate(year=2023, month=6)
        c_e = ResumeDate(year=2023, month=12)
        assert calculate_overlap_months(a_s, a_e, c_s, c_e) == 0


class TestResumeTimelineAnalysis:
    """Tests core acceptance criteria: gaps, consistent dates, mixed formats, overlaps, and neutral tone."""

    def test_consistent_dates_produce_no_flags(self):
        resume = """
        EDUCATION
        B.Tech in Computer Science | National Institute of Technology
        Aug 2018 - May 2022

        EXPERIENCE
        Acme Corp | Software Engineer
        Jun 2022 - Dec 2023

        Global Cloud | Senior Software Engineer
        Jan 2024 - Present
        """
        analysis = analyze_resume_timeline(resume, gap_threshold_months=6)
        assert analysis["has_flags"] is False
        assert analysis["has_active_flags"] is False
        assert len(analysis["flags"]) == 0
        assert analysis["active_flags_count"] == 0

    def test_sample_resumes_with_gaps_are_flagged_correctly(self):
        resume = """
        EDUCATION
        B.S. in Computer Science | City College
        Aug 2017 - May 2021

        EXPERIENCE
        Tech Startups Inc | Junior Developer
        Jun 2021 - Dec 2021

        Alpha Systems | Backend Engineer
        Jan 2023 - Present
        """
        # Gap between Dec 2021 and Jan 2023 is 12 months (> 6 month threshold)
        analysis = analyze_resume_timeline(resume, gap_threshold_months=6)
        assert analysis["has_flags"] is True
        assert analysis["has_active_flags"] is True
        gap_flags = [f for f in analysis["flags"] if f["type"] == "gap"]
        assert len(gap_flags) >= 1
        assert gap_flags[0]["gap_months"] == 12
        assert "Dec 2021" in gap_flags[0]["dates"]
        assert "Jan 2023" in gap_flags[0]["dates"]
        assert gap_flags[0]["line_number"] > 0
        assert "line" in gap_flags[0]

    def test_mixed_date_formats_parsed_correctly(self):
        resume = """
        EDUCATION
        B.Tech in Information Technology | Apex University
        08/2016 - 05/2020

        EXPERIENCE
        Data Works | Systems Associate
        June 2020 - 12/2021

        Cloud Scale Inc | DevOps Engineer
        2023 - Present
        """
        analysis = analyze_resume_timeline(resume, gap_threshold_months=6)
        assert len(analysis["timeline_items"]) >= 3
        # Should flag the gap between 12/2021 and 2023
        gap_flags = [f for f in analysis["flags"] if f["type"] == "gap"]
        assert len(gap_flags) >= 1
        assert gap_flags[0]["gap_months"] >= 11

    def test_overlapping_roles_flagged_neutrally(self):
        resume = """
        EXPERIENCE
        Acme Corp | Full Stack Developer
        Jan 2022 - Dec 2023

        Beta Innovations | Open Source Maintainer
        Jun 2022 - May 2023
        """
        analysis = analyze_resume_timeline(resume)
        overlap_flags = [f for f in analysis["flags"] if f["type"] == "overlap"]
        assert len(overlap_flags) >= 1
        f = overlap_flags[0]
        assert f["overlap_months"] >= 6
        assert "Concurrent" in f["suggestion"] or "Part-time" in f["suggestion"]

    def test_inverted_dates_flagged(self):
        resume = """
        EXPERIENCE
        Tech Labs | Lead Developer
        2024 - 2022
        """
        analysis = analyze_resume_timeline(resume)
        inverted_flags = [f for f in analysis["flags"] if f["type"] == "inverted_dates"]
        assert len(inverted_flags) >= 1
        f = inverted_flags[0]
        assert "earlier than the start date" in f["explanation"].lower()
        assert "transposed" in f["suggestion"].lower() or "typo" in f["suggestion"].lower()

    def test_neutral_phrasing_without_assumed_reasons(self):
        resume = """
        EXPERIENCE
        Company A | Developer
        Jan 2020 - Dec 2020

        Company B | Engineer
        Jan 2022 - Dec 2022
        """
        analysis = analyze_resume_timeline(resume, gap_threshold_months=6)
        gap_flag = [f for f in analysis["flags"] if f["type"] == "gap"][0]
        explanation = gap_flag["explanation"].lower()

        # Prohibited judgmental terms:
        prohibited_words = [
            "unemployed", "lazy", "failed", "illness", "personal crisis",
            "slacking", "dropped out", "fired", "terminated", "gap year flaw"
        ]
        for word in prohibited_words:
            assert word not in explanation, f"Explanation assumed reasons with word '{word}': {explanation}"

        # Must suggest constructive ways to address
        suggestion = gap_flag["suggestion"].lower()
        assert any(term in suggestion for term in ["project", "coursework", "certification", "freelance", "format"])

    def test_dismiss_flag_capability(self):
        resume = """
        EXPERIENCE
        Company A | Developer
        Jan 2020 - Dec 2020

        Company B | Engineer
        Jan 2022 - Dec 2022
        """
        initial = analyze_resume_timeline(resume, gap_threshold_months=6)
        assert initial["active_flags_count"] == 1
        flag_id = initial["flags"][0]["flag_id"]

        # Student dismisses the flag
        dismissed_result = analyze_resume_timeline(
            resume,
            gap_threshold_months=6,
            dismissed_flag_ids=[flag_id]
        )
        assert dismissed_result["active_flags_count"] == 0
        assert dismissed_result["dismissed_flags_count"] == 1
        assert dismissed_result["has_active_flags"] is False
        assert dismissed_result["flags"][0]["is_dismissed"] is True


class TestResumeTimelineApi:
    """Tests the Flask endpoints for timeline verification and flag dismissal."""

    def test_api_check_resume_timeline_stateless(self, client):
        payload = {
            "resume_text": """
            EXPERIENCE
            Acme Corp | Developer
            Jan 2021 - Dec 2021

            Beta LLC | Senior Developer
            Jan 2023 - Present
            """,
            "gap_threshold_months": 6
        }
        resp = client.post("/api/resume/timeline-check", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        timeline = data["timeline"]
        assert timeline["has_flags"] is True
        assert timeline["summary"]["gaps_count"] >= 1

    def test_api_timeline_and_dismissal_cycle(self, client):
        # 1. Create a mock analysis in database
        from utils.database import save_analysis
        mock_id = "test-timeline-analysis-840"
        sample_resume_text = """
        EXPERIENCE
        Alpha Tech | Developer
        Jan 2020 - Dec 2020

        Omega Labs | Lead
        Jan 2022 - Present
        """
        save_analysis(
            analysis_id=mock_id,
            resume_filename="resume.pdf",
            company_name="Acme",
            job_description="Software Developer",
            results_dict={
                "resume_analysis": {"ats_score": 75},
                "job_match": {"match_percentage": 70},
            },
            student_id="test_student_840",
            resume_text=sample_resume_text,
        )

        with client.session_transaction() as sess:
            sess["user_id"] = "test_student_840"
            sess["student_id"] = "test_student_840"

        # 2. GET timeline analysis
        get_resp = client.get(f"/api/analysis/{mock_id}/timeline")
        assert get_resp.status_code == 200
        get_data = get_resp.get_json()
        assert get_data["success"] is True
        flags = get_data["timeline"]["flags"]
        assert len(flags) >= 1
        target_flag_id = flags[0]["flag_id"]

        # 3. Dismiss the flag
        dismiss_resp = client.post(
            f"/api/analysis/{mock_id}/dismiss-timeline-flag",
            json={"flag_id": target_flag_id, "dismissed": True}
        )
        assert dismiss_resp.status_code == 200
        dismiss_data = dismiss_resp.get_json()
        assert dismiss_data["success"] is True
        assert dismiss_data["is_dismissed"] is True
        assert dismiss_data["active_flags_count"] == 0
        assert dismiss_data["dismissed_flags_count"] == 1

        # 4. GET timeline analysis again to verify dismissed status reflected
        get_resp2 = client.get(f"/api/analysis/{mock_id}/timeline")
        get_data2 = get_resp2.get_json()
        target_flag = next(f for f in get_data2["timeline"]["flags"] if f["flag_id"] == target_flag_id)
        assert target_flag["is_dismissed"] is True

        # 5. Restore (un-dismiss) the flag
        restore_resp = client.post(
            f"/api/analysis/{mock_id}/dismiss-timeline-flag",
            json={"flag_id": target_flag_id, "dismissed": False}
        )
        assert restore_resp.status_code == 200
        restore_data = restore_resp.get_json()
        assert restore_data["success"] is True
        assert restore_data["is_dismissed"] is False
        assert restore_data["active_flags_count"] == 1


class TestCoordinatorTimelineIntegration:
    """Verifies that CoordinatorAgent includes timeline_analysis in coordinated payloads."""

    def test_coordinator_analyze_includes_timeline(self, monkeypatch):
        from agents.coordinator import CoordinatorAgent

        # Mock generate_json_response to return a valid structured payload
        mock_ai_output = {
            "resume_analysis": {
                "ats_score": 80,
                "strengths": ["Clean layout"],
                "weaknesses": [],
                "formatting_suggestions": [],
                "grammar_suggestions": []
            },
            "job_match": {
                "match_percentage": 75,
                "matched_skills": ["Python"],
                "missing_skills": ["Kubernetes"],
                "top_5_resume_changes": []
            },
            "skill_gap": [
                {"skill": "Kubernetes", "relevance": "High", "actionable_step": "Complete tutorial"}
            ],
            "learning_roadmap": [
                {"week": 1, "topic": "Docker", "resources": []}
            ],
            "interview_questions": {
                "technical": [],
                "hr": [],
                "behavioral": []
            },
            "overall_recommendation_summary": "Strong candidate."
        }

        monkeypatch.setattr(
            "agents.coordinator.generate_json_response",
            lambda *args, **kwargs: mock_ai_output
        )

        coordinator = CoordinatorAgent()
        resume_sample = """
        EXPERIENCE
        Tech Corp | SDE
        Jan 2021 - Dec 2021

        Alpha Inc | SDE 2
        Jan 2023 - Present
        """

        result = coordinator.analyze(resume_text=resume_sample, company_name="TestCorp")
        assert "timeline_analysis" in result
        timeline = result["timeline_analysis"]
        assert timeline["has_flags"] is True
        assert timeline["summary"]["gaps_count"] >= 1
