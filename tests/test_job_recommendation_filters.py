"""
Tests for Pluggable Job Data Sources and Filterable Job Recommendations (#533)
==============================================================================
Verifies:
1. Pluggable JobDataSource architecture (JsonFileJobDataSource, InMemoryJobDataSource, CompositeJobDataSource).
2. Runtime swapping of data source without altering scoring or ranking logic.
3. Filtering by location, role type (internship vs full-time), and experience level.
4. Ranking listings by skill overlap and explaining fit with recommendation reasons.
5. Actionable suggestions to broaden filters when zero listings match.
6. Flask REST API endpoint /api/jobs/recommendations/<analysis_id>.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.job_recommendation_agent import JobRecommendationAgent
from utils.job_data_source import (
    JobDataSource,
    JsonFileJobDataSource,
    InMemoryJobDataSource,
    CompositeJobDataSource,
    DEFAULT_FALLBACK_JOBS,
)
from app import app
import config


SAMPLE_CANDIDATE_ANALYSIS = {
    "student_id": "test_student_533",
    "company_name": "Google",
    "target_role": "Software Engineer",
    "results": {
        "resume_analysis": {
            "ats_score": 85,
            "skills_detected": ["Python", "C++", "Java", "Data Structures", "Algorithms", "Git", "SQL"],
        },
        "job_match": {
            "matched_skills": ["Python", "C++", "Java", "Data Structures", "Algorithms", "Git", "SQL"],
            "missing_skills": ["Cloud Architecture", "System Design"],
            "target_role": "Software Engineer"
        }
    }
}

SAMPLE_MOCK_JOBS = [
    {
        "id": "mock-job-1",
        "title": "Backend Software Engineer",
        "company": "Google",
        "location": "Bengaluru",
        "role_type": "Full-time",
        "experience_level": "Fresher / 0-1 Years",
        "required_skills": ["Python", "Data Structures", "Algorithms", "Git"],
        "preferred_skills": ["Cloud Architecture"],
        "salary_range": "₹24 - ₹38 LPA",
        "apply_url": "https://careers.google.com/test",
        "deadline": "Active"
    },
    {
        "id": "mock-job-2",
        "title": "Software Development Intern",
        "company": "Amazon",
        "location": "Hyderabad",
        "role_type": "Internship",
        "experience_level": "Student / Pre-final Year",
        "required_skills": ["Java", "Data Structures", "SQL"],
        "preferred_skills": ["AWS"],
        "salary_range": "₹80,000 / month",
        "apply_url": "https://amazon.jobs/test",
        "deadline": "Active"
    },
    {
        "id": "mock-job-3",
        "title": "Full Stack Engineer",
        "company": "StartupX",
        "location": "Remote",
        "role_type": "Full-time",
        "experience_level": "Fresher / 0-1 Years",
        "required_skills": ["JavaScript", "React", "Node.js"],
        "preferred_skills": ["MongoDB"],
        "salary_range": "₹12 - ₹18 LPA",
        "apply_url": "https://startupx.com/test",
        "deadline": "Active"
    }
]


class TestJobDataSource(unittest.TestCase):
    """Verifies pluggable data source implementations and runtime swapping."""

    def test_in_memory_data_source(self):
        source = InMemoryJobDataSource(SAMPLE_MOCK_JOBS)
        jobs = source.get_jobs()
        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0]["id"], "mock-job-1")

        # Test updating jobs
        source.set_jobs([SAMPLE_MOCK_JOBS[0]])
        self.assertEqual(len(source.get_jobs()), 1)

    def test_json_file_data_source_fallback(self):
        # Non-existent file should fall back gracefully
        non_existent = Path("non_existent_jobs_file_9999.json")
        source = JsonFileJobDataSource(file_path=non_existent)
        jobs = source.get_jobs()
        self.assertTrue(len(jobs) >= 1)
        self.assertEqual(jobs[0]["id"], DEFAULT_FALLBACK_JOBS[0]["id"])

    def test_composite_data_source_deduplication(self):
        source1 = InMemoryJobDataSource([SAMPLE_MOCK_JOBS[0], SAMPLE_MOCK_JOBS[1]])
        source2 = InMemoryJobDataSource([SAMPLE_MOCK_JOBS[1], SAMPLE_MOCK_JOBS[2]])
        composite = CompositeJobDataSource([source1, source2])

        jobs = composite.get_jobs()
        self.assertEqual(len(jobs), 3)
        ids = [j["id"] for j in jobs]
        self.assertEqual(ids, ["mock-job-1", "mock-job-2", "mock-job-3"])

    def test_swap_data_source_without_changing_ranking_code(self):
        """Acceptance criterion: The data source can be swapped without changing the ranking code."""
        # Start with source A (1 job)
        source_a = InMemoryJobDataSource([SAMPLE_MOCK_JOBS[0]])
        agent = JobRecommendationAgent(data_source=source_a)

        recs_a = agent.recommend_jobs(analysis_record=SAMPLE_CANDIDATE_ANALYSIS)
        self.assertEqual(len(recs_a), 1)
        self.assertEqual(recs_a[0]["id"], "mock-job-1")

        # Swap to source B (all 3 jobs) at runtime
        source_b = InMemoryJobDataSource(SAMPLE_MOCK_JOBS)
        agent.set_data_source(source_b)

        recs_b = agent.recommend_jobs(analysis_record=SAMPLE_CANDIDATE_ANALYSIS)
        self.assertEqual(len(recs_b), 3)

        # Ranking logic remains identical
        self.assertGreater(recs_b[0]["match_percentage"], recs_b[2]["match_percentage"])


class TestJobFilteringAndRanking(unittest.TestCase):
    """Verifies ranking by skill overlap, matched skills listing, and multi-criteria filtering."""

    def setUp(self):
        self.source = InMemoryJobDataSource(SAMPLE_MOCK_JOBS)
        self.agent = JobRecommendationAgent(data_source=self.source)

    def test_ranking_by_skill_overlap(self):
        """Candidate skills: Python, C++, Java, Data Structures, Algorithms, Git, SQL."""
        recs = self.agent.recommend_jobs(analysis_record=SAMPLE_CANDIDATE_ANALYSIS)
        self.assertEqual(len(recs), 3)

        # Job 1 (Python, DS, Algo, Git) matches 4/4 skills -> highest score
        top_job = recs[0]
        self.assertEqual(top_job["id"], "mock-job-1")
        self.assertGreaterEqual(top_job["match_percentage"], 80)

        # Job 3 (JS, React, Node) matches 0 required skills -> lowest score
        lowest_job = recs[2]
        self.assertEqual(lowest_job["id"], "mock-job-3")
        self.assertLess(lowest_job["match_percentage"], top_job["match_percentage"])
        self.assertLess(lowest_job["match_percentage"], 60)

    def test_matched_skills_and_recommendation_reason(self):
        """Acceptance criterion: Each recommendation lists the matched skills and explains fit."""
        recs = self.agent.recommend_jobs(analysis_record=SAMPLE_CANDIDATE_ANALYSIS)
        for job in recs:
            self.assertIn("matched_skills", job)
            self.assertIsInstance(job["matched_skills"], list)
            self.assertIn("recommendation_reason", job)
            self.assertTrue(len(job["recommendation_reason"]) > 10)

        # Check specific matched skills on top job
        top_job = recs[0]
        for skill in ["Python", "Data Structures", "Algorithms", "Git"]:
            self.assertIn(skill, top_job["matched_skills"])

    def test_filter_by_location(self):
        """Acceptance criterion: Changing a filter updates the list."""
        all_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, location="all")
        self.assertEqual(len(all_recs), 3)

        blr_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, location="Bengaluru")
        self.assertEqual(len(blr_recs), 1)
        self.assertEqual(blr_recs[0]["location"], "Bengaluru")

        remote_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, location="Remote")
        self.assertEqual(len(remote_recs), 1)
        self.assertEqual(remote_recs[0]["location"], "Remote")

    def test_filter_by_role_type(self):
        """Filters between Full-time and Internship."""
        ft_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, role_type="Full-time")
        self.assertEqual(len(ft_recs), 2)
        for j in ft_recs:
            self.assertEqual(j["role_type"], "Full-time")

        intern_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, role_type="Internship")
        self.assertEqual(len(intern_recs), 1)
        self.assertEqual(intern_recs[0]["role_type"], "Internship")

    def test_filter_by_experience_level(self):
        """Filters by experience level (fresher vs student/intern)."""
        fresher_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, experience_level="fresher")
        self.assertEqual(len(fresher_recs), 2)

        intern_recs = self.agent.recommend_jobs(SAMPLE_CANDIDATE_ANALYSIS, experience_level="intern")
        self.assertEqual(len(intern_recs), 1)
        self.assertEqual(intern_recs[0]["id"], "mock-job-2")

    def test_suggestions_to_broaden_when_no_match(self):
        """Acceptance criterion: Show suggestions to broaden the filters when nothing matches."""
        # Unmatched combination
        recs = self.agent.recommend_jobs(
            SAMPLE_CANDIDATE_ANALYSIS,
            location="Antarctica",
            role_type="Internship",
            experience_level="fresher"
        )
        self.assertEqual(len(recs), 0)

        suggestions = self.agent.get_broaden_suggestions(
            total_available=3,
            filtered_count=len(recs),
            location="Antarctica",
            role_type="Internship",
            experience_level="fresher"
        )
        self.assertTrue(len(suggestions) >= 2)
        suggestions_text = " ".join(suggestions)
        self.assertIn("Antarctica", suggestions_text)
        self.assertIn("All Locations", suggestions_text)

        # When results match, suggestions should be empty
        has_results = self.agent.get_broaden_suggestions(
            total_available=3,
            filtered_count=2,
            location="Bengaluru"
        )
        self.assertEqual(len(has_results), 0)


class TestJobRecommendationsAPI(unittest.TestCase):
    """Verifies the Flask REST endpoint /api/jobs/recommendations/<analysis_id>."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_api_job_recommendations_default(self, mock_auth, mock_analysis):
        mock_analysis.return_value = SAMPLE_CANDIDATE_ANALYSIS

        resp = self.client.get("/api/jobs/recommendations/test-analysis-123")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["analysis_id"], "test-analysis-123")
        self.assertIn("jobs", data)
        self.assertIsInstance(data["jobs"], list)
        self.assertGreater(len(data["jobs"]), 0)

        # Verify each job contains matched skills and reason
        first_job = data["jobs"][0]
        self.assertIn("matched_skills", first_job)
        self.assertIn("recommendation_reason", first_job)
        self.assertIn("filters_applied", data)

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_api_job_recommendations_filtered(self, mock_auth, mock_analysis):
        mock_analysis.return_value = SAMPLE_CANDIDATE_ANALYSIS

        resp = self.client.get("/api/jobs/recommendations/test-analysis-123?location=Bengaluru&role_type=Full-time")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["filters_applied"]["location"], "Bengaluru")
        self.assertEqual(data["filters_applied"]["role_type"], "Full-time")

        for job in data["jobs"]:
            self.assertIn("bengaluru", job["location"].lower())
            self.assertEqual(job["role_type"].lower(), "full-time")

    @patch("app.get_analysis")
    @patch("app._is_student_authorized", return_value=True)
    def test_api_job_recommendations_empty_with_broaden_suggestions(self, mock_auth, mock_analysis):
        mock_analysis.return_value = SAMPLE_CANDIDATE_ANALYSIS

        resp = self.client.get("/api/jobs/recommendations/test-analysis-123?location=NowhereCity&role_type=Internship")
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_matched"], 0)
        self.assertEqual(len(data["jobs"]), 0)

        self.assertIn("suggestions_to_broaden", data)
        self.assertTrue(len(data["suggestions_to_broaden"]) > 0)
        suggestions_str = " ".join(data["suggestions_to_broaden"])
        self.assertIn("NowhereCity", suggestions_str)


if __name__ == "__main__":
    unittest.main()
