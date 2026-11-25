"""
Unit & Integration Tests for Customizable Placement Reports (#761)
==================================================================
Tests:
1. Excluded sections never appear in the output (PDF, Markdown, JSON, HTML).
2. Names and target roles with special characters (Unicode, accents, &, <, >, quotes) render correctly without errors.
3. The default report is completely unchanged when nothing is customized.
4. Custom section ordering is strictly respected in Markdown and HTML.
5. User customization choices are remembered for the session across multiple download requests.
"""

import os
import io
import json
import unittest
import tempfile

from app import app
from utils.demo_mode import get_synthetic_sample_analysis
from utils.analysis_export_service import (
    build_analysis_export_payload,
    export_analysis_to_json,
    export_analysis_to_markdown,
    normalize_report_customization,
    CANONICAL_SECTIONS,
)
from utils.report_generator import generate_pdf_report


class TestReportCustomizationLogic(unittest.TestCase):
    """Tests normalization and payload logic for report customizations."""

    def setUp(self):
        self.sample_analysis = get_synthetic_sample_analysis()

    def test_default_customization_unchanged(self):
        """Acceptance Criterion: The default report is unchanged when nothing is customized."""
        norm_none = normalize_report_customization(None)
        norm_empty = normalize_report_customization({})

        self.assertFalse(norm_none["is_customized"])
        self.assertFalse(norm_empty["is_customized"])
        self.assertIsNone(norm_none["student_name"])
        self.assertIsNone(norm_none["target_role"])
        self.assertEqual(norm_none["included_sections"], CANONICAL_SECTIONS)
        self.assertEqual(norm_none["section_order"], CANONICAL_SECTIONS)

        # Default payload contains all standard schema keys
        payload = build_analysis_export_payload(self.sample_analysis)
        self.assertIn("score", payload)
        self.assertIn("scores", payload)
        self.assertIn("summary", payload)
        self.assertIn("overall_recommendation", payload)
        self.assertIn("suggestions", payload)
        self.assertIn("skill_gaps", payload)
        self.assertIn("interview_tips", payload)
        self.assertIn("learning_roadmap", payload)

        # Default markdown matches exact legacy headings
        md = export_analysis_to_markdown(self.sample_analysis)
        self.assertIn("## 1. Readiness Scores & ATS Evaluation", md)
        self.assertIn("## 2. Executive Resume Summary & Recommendation", md)
        self.assertIn("## 3. Resume Feedback & Suggestions", md)
        self.assertIn("## 4. Skill Gap Assessment", md)
        self.assertIn("## 5. Interview Tips & Preparation Guidance", md)
        self.assertIn("## 6. Six-Week Learning Roadmap", md)

    def test_excluded_sections_never_appear_in_json(self):
        """Acceptance Criterion: Excluded sections never appear in the JSON output."""
        customization = {
            "included_sections": ["summary", "skill_gaps"],
            "student_name": "Test Student",
        }
        payload = build_analysis_export_payload(self.sample_analysis, customization=customization)

        # Included sections present
        self.assertIn("summary", payload)
        self.assertIn("skill_gaps", payload)
        self.assertEqual(payload["metadata"]["candidate_name"], "Test Student")

        # Excluded sections MUST NOT appear in payload
        self.assertNotIn("score", payload)
        self.assertNotIn("scores", payload)
        self.assertNotIn("interview_tips", payload)
        self.assertNotIn("learning_roadmap", payload)

        # JSON serialization check
        json_str = export_analysis_to_json(self.sample_analysis, customization=customization)
        parsed = json.loads(json_str)
        self.assertNotIn("scores", parsed)
        self.assertNotIn("learning_roadmap", parsed)
        self.assertIn("summary", parsed)

    def test_excluded_sections_never_appear_in_markdown(self):
        """Acceptance Criterion: Excluded sections never appear in the Markdown output."""
        customization = {
            "included_sections": ["summary", "job_adjustments"],
            "target_role": "Backend Architect",
        }
        md = export_analysis_to_markdown(self.sample_analysis, customization=customization)

        self.assertIn("Executive Resume Summary", md)
        self.assertIn("Top Recommended Resume Adjustments", md)
        self.assertIn("Target Role:** Backend Architect", md)

        # Excluded sections MUST NOT appear anywhere in the markdown document
        self.assertNotIn("Readiness Scores & ATS Evaluation", md)
        self.assertNotIn("Skill Gap Assessment", md)
        self.assertNotIn("Interview Tips & Preparation Guidance", md)
        self.assertNotIn("Six-Week Learning Roadmap", md)

    def test_custom_section_ordering_respected_in_markdown(self):
        """Verifies section order chosen by the student is honored in Markdown."""
        customization = {
            "included_sections": ["learning_roadmap", "summary", "scores"],
            "section_order": ["learning_roadmap", "summary", "scores"],
        }
        md = export_analysis_to_markdown(self.sample_analysis, customization=customization)

        pos_roadmap = md.find("Six-Week Learning Roadmap")
        pos_summary = md.find("Executive Resume Summary")
        pos_scores = md.find("Readiness Scores & ATS Evaluation")

        self.assertNotEqual(pos_roadmap, -1)
        self.assertNotEqual(pos_summary, -1)
        self.assertNotEqual(pos_scores, -1)
        self.assertLess(pos_roadmap, pos_summary)
        self.assertLess(pos_summary, pos_scores)

    def test_names_with_special_characters_in_markdown_and_json(self):
        """Acceptance Criterion: Names with special characters render correctly."""
        special_names = [
            "François Müller",
            "Alice <Tech> & Bob",
            "José María C++",
            "O'Connor & Sons",
            "“Smart Quotes” Candidate",
        ]
        for name in special_names:
            customization = {
                "student_name": name,
                "target_role": "C++ & Rust Specialist <Level 4>",
            }
            # JSON
            json_out = export_analysis_to_json(self.sample_analysis, customization=customization)
            parsed = json.loads(json_out)
            self.assertEqual(parsed["metadata"]["candidate_name"], name)
            self.assertEqual(parsed["metadata"]["target_role"], "C++ & Rust Specialist <Level 4>")
            # No unicode escaping
            self.assertIn(name, json_out)

            # Markdown
            md_out = export_analysis_to_markdown(self.sample_analysis, customization=customization)
            self.assertIn(name, md_out)
            self.assertIn("C++ & Rust Specialist <Level 4>", md_out)

    def test_pdf_generation_with_special_characters_and_custom_sections(self):
        """Verifies PDF report generates smoothly with XML-hazardous characters and excluded sections."""
        special_name = "François <Dev> & Müller"
        customization = {
            "student_name": special_name,
            "target_role": "Lead Architect & Consultant <HQ>",
            "included_sections": ["summary", "skill_gaps", "scores"],
            "section_order": ["skill_gaps", "scores", "summary"],
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name

        try:
            res_path = generate_pdf_report(
                analysis_data=self.sample_analysis,
                output_path=pdf_path,
                customization=customization,
            )
            self.assertTrue(os.path.exists(res_path))
            self.assertGreater(os.path.getsize(res_path), 500)
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)


class TestReportCustomizationRoutes(unittest.TestCase):
    """Integration tests for web routes, session persistence, and export customization."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_api_customize_report_get_and_post(self):
        """Tests getting available sections and setting customization preferences via API."""
        # GET available sections
        res_get = self.client.get("/api/analysis/demo-sample-analysis/customize-report")
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.get_json()
        self.assertTrue(data_get["success"])
        self.assertIn("available_sections", data_get)
        self.assertIn("scores", data_get["available_sections"])

        # POST preferences
        payload = {
            "student_name": "Deepika Gandla",
            "target_role": "Principal AI Engineer",
            "included_sections": ["summary", "overall_recommendation", "skill_gaps"],
            "section_order": ["skill_gaps", "summary", "overall_recommendation"],
        }
        res_post = self.client.post(
            "/api/analysis/demo-sample-analysis/customize-report",
            json=payload,
        )
        self.assertEqual(res_post.status_code, 200)
        data_post = res_post.get_json()
        self.assertTrue(data_post["success"])
        self.assertEqual(data_post["customization"]["student_name"], "Deepika Gandla")
        self.assertEqual(data_post["customization"]["target_role"], "Principal AI Engineer")
        self.assertEqual(data_post["customization"]["included_sections"], ["summary", "overall_recommendation", "skill_gaps"])

    def test_session_remembers_choices_across_export_formats(self):
        """Acceptance Criterion: Allow choosing section order and remember choices for the session."""
        with self.client.session_transaction() as sess:
            sess["report_customization"] = {
                "student_name": "Session Candidate",
                "target_role": "Security Analyst",
                "included_sections": ["summary", "interview_tips"],
                "section_order": ["interview_tips", "summary"],
                "is_customized": True,
            }

        # 1. Markdown download uses session preferences
        res_md = self.client.get("/download/demo-sample-analysis/markdown")
        self.assertEqual(res_md.status_code, 200)
        md_content = res_md.data.decode("utf-8")
        self.assertIn("Session Candidate", md_content)
        self.assertIn("Security Analyst", md_content)
        self.assertIn("Executive Resume Summary", md_content)
        self.assertIn("Interview Tips & Preparation Guidance", md_content)
        # Excluded sections not present
        self.assertNotIn("Readiness Scores & ATS Evaluation", md_content)
        self.assertNotIn("Six-Week Learning Roadmap", md_content)

        # 2. JSON download uses session preferences
        res_json = self.client.get("/download/demo-sample-analysis/json")
        self.assertEqual(res_json.status_code, 200)
        json_data = json.loads(res_json.data.decode("utf-8"))
        self.assertEqual(json_data["metadata"]["candidate_name"], "Session Candidate")
        self.assertEqual(json_data["metadata"]["target_role"], "Security Analyst")
        self.assertIn("summary", json_data)
        self.assertIn("interview_tips", json_data)
        self.assertNotIn("learning_roadmap", json_data)

        # 3. HTML report view uses session preferences
        res_html = self.client.get("/report/demo-sample-analysis")
        self.assertEqual(res_html.status_code, 200)
        html_content = res_html.data.decode("utf-8")
        self.assertIn("Session Candidate", html_content)
        self.assertIn("Security Analyst", html_content)
        self.assertIn("Executive resume summary", html_content)
        # Excluded sections not present
        self.assertNotIn("Six-week learning roadmap", html_content)
        self.assertNotIn("Skill gap assessment", html_content)

    def test_query_params_override_and_customize_output(self):
        """Verifies query parameters customize the output on the fly."""
        # Query params for markdown
        resp = self.client.get(
            "/download/demo-sample-analysis/markdown?name=François+Müller&role=Staff+Engineer&sections=summary,skill_gaps"
        )
        self.assertEqual(resp.status_code, 200)
        md = resp.data.decode("utf-8")
        self.assertIn("François Müller", md)
        self.assertIn("Staff Engineer", md)
        self.assertIn("Executive Resume Summary", md)
        self.assertIn("Skill Gap Assessment", md)
        self.assertNotIn("Readiness Scores & ATS Evaluation", md)
        self.assertNotIn("Six-Week Learning Roadmap", md)

    def test_html_report_special_characters_safety(self):
        """Acceptance Criterion: Names with special characters render correctly without XSS or breakage."""
        import urllib.parse
        hazardous_name = "Alex <script>alert(1)</script> & Co."
        quoted_name = urllib.parse.quote_plus(hazardous_name)
        resp = self.client.get(
            f"/report/demo-sample-analysis?name={quoted_name}&sections=summary"
        )
        self.assertEqual(resp.status_code, 200)
        html_body = resp.data.decode("utf-8")
        # Ensure it is HTML-escaped by Jinja2
        self.assertNotIn("<script>alert(1)</script>", html_body)
        self.assertIn("Alex &lt;script&gt;alert(1)&lt;/script&gt; &amp; Co.", html_body)


if __name__ == "__main__":
    unittest.main()
