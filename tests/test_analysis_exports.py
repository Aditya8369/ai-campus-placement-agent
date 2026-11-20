"""
Unit & Integration Tests for Analysis Multi-Format Exports (#534)
=================================================================
Tests:
1. JSON export payload generation and schema validation (version 1.0).
2. Markdown export document generation and section completeness.
3. Content parity between on-screen report and exported files.
4. Strict preservation of non-English text, accents, symbols (C++, C#, &), and Unicode without ASCII escaping.
5. Flask web download routes and REST API endpoints:
   - /download/<analysis_id>/markdown
   - /download/<analysis_id>/json
   - /download/<analysis_id>?format=markdown
   - /download/<analysis_id>?format=json
   - /api/analysis/<analysis_id>/export
"""

import json
import unittest
from unittest.mock import patch

from app import app
from utils.demo_mode import get_synthetic_sample_analysis
from utils.analysis_export_service import (
    build_analysis_export_payload,
    export_analysis_to_json,
    export_analysis_to_markdown,
    get_export_filename,
    CURRENT_EXPORT_VERSION,
)


class TestAnalysisExportService(unittest.TestCase):
    """Tests for core export functions in utils/analysis_export_service.py."""

    def setUp(self):
        self.sample_analysis = get_synthetic_sample_analysis()

    def test_build_analysis_export_payload_schema(self):
        """Verifies that the payload contains all required keys and matches the stable 1.0 schema."""
        payload = build_analysis_export_payload(self.sample_analysis)

        # Root fields
        self.assertEqual(payload["version"], CURRENT_EXPORT_VERSION)
        self.assertIn("metadata", payload)
        self.assertIn("score", payload)
        self.assertIn("scores", payload)
        self.assertIn("summary", payload)
        self.assertIn("overall_recommendation", payload)
        self.assertIn("suggestions", payload)
        self.assertIn("skill_gaps", payload)
        self.assertIn("interview_tips", payload)
        self.assertIn("learning_roadmap", payload)
        self.assertIn("advisories", payload)

        # Metadata fields
        meta = payload["metadata"]
        self.assertEqual(meta["company_name"], "Google")
        self.assertIn("Software Development Engineer", meta["target_role"])
        self.assertIn("analysis_id", meta)
        self.assertIn("exported_at", meta)

        # Score fields
        self.assertIsInstance(payload["score"], int)
        self.assertGreaterEqual(payload["score"], 0)
        self.assertIn("ats_score", payload["scores"])
        self.assertIn("job_match_score", payload["scores"])
        self.assertIn("readiness_verdict", payload["scores"])
        self.assertIn("breakdown", payload["scores"])

        # Suggestions fields
        suggs = payload["suggestions"]
        self.assertIn("strengths", suggs)
        self.assertIn("weaknesses", suggs)
        self.assertIn("grammar_suggestions", suggs)
        self.assertIn("formatting_suggestions", suggs)
        self.assertIn("resume_changes", suggs)
        self.assertIsInstance(suggs["strengths"], list)
        self.assertIsInstance(suggs["resume_changes"], list)

        # Skill gaps list
        gaps = payload["skill_gaps"]
        self.assertIsInstance(gaps, list)
        self.assertGreater(len(gaps), 0)
        first_gap = gaps[0]
        self.assertIn("skill", first_gap)
        self.assertIn("importance", first_gap)
        self.assertIn("learning_time", first_gap)
        self.assertIn("priority", first_gap)
        self.assertIn("learning_resource", first_gap)
        self.assertIn("project_suggestion", first_gap)

        # Interview tips
        tips = payload["interview_tips"]
        self.assertIn("preparation_tips", tips)
        self.assertIn("questions", tips)
        self.assertIn("elevator_pitch_guidance", tips)
        self.assertGreater(len(tips["preparation_tips"]), 0)
        self.assertGreater(len(tips["questions"]), 0)

        # Learning roadmap
        roadmap = payload["learning_roadmap"]
        self.assertIsInstance(roadmap, list)
        self.assertEqual(len(roadmap), 6)
        self.assertEqual(roadmap[0]["week"], "Week 1")

    def test_export_analysis_to_json_validity_and_parity(self):
        """Verifies that export_analysis_to_json generates valid, parseable JSON with full content parity."""
        json_str = export_analysis_to_json(self.sample_analysis)
        self.assertIsInstance(json_str, str)

        parsed = json.loads(json_str)
        self.assertEqual(parsed["version"], "1.0")
        self.assertEqual(parsed["metadata"]["company_name"], "Google")
        self.assertEqual(parsed["score"], self.sample_analysis["results"]["resume_analysis"]["ats_score"])
        self.assertEqual(len(parsed["skill_gaps"]), len(self.sample_analysis["results"]["skill_gap"]))
        self.assertIn("Alex", parsed["overall_recommendation"])

    def test_export_analysis_to_markdown_structure(self):
        """Verifies that export_analysis_to_markdown generates complete, structured GFM document."""
        md_str = export_analysis_to_markdown(self.sample_analysis)
        self.assertIsInstance(md_str, str)

        # Check required headers and sections
        self.assertIn("# Placement Readiness Report: Google", md_str)
        self.assertIn("## 1. Readiness Scores & ATS Evaluation", md_str)
        self.assertIn("## 2. Executive Resume Summary & Recommendation", md_str)
        self.assertIn("## 3. Resume Feedback & Suggestions", md_str)
        self.assertIn("## 4. Skill Gap Assessment", md_str)
        self.assertIn("## 5. Interview Tips & Preparation Guidance", md_str)
        self.assertIn("## 6. Six-Week Learning Roadmap", md_str)

        # Check content presence
        self.assertIn("ATS Compatibility Score", md_str)
        self.assertIn("Job Role Match", md_str)
        self.assertIn("Strengths", md_str)
        self.assertIn("Weaknesses", md_str)
        self.assertIn("Top Recommended Resume Adjustments", md_str)
        self.assertIn("Distributed System Design", md_str)
        self.assertIn("Week 1", md_str)

    def test_unicode_and_special_character_preservation(self):
        """
        Verifies that non-English text, diacritics, accents, math symbols, and tech symbols
        (C++, C#, &) are preserved without ASCII escaping.
        """
        custom_record = {
            "analysis_id": "test-unicode-analysis",
            "company_name": "München Tech GmbH & Co.",
            "target_role": "Senior C++ / C# Developer (सॉफ्टवेयर इंजीनियर)",
            "resume_filename": "CV_François_Müller_2026.pdf",
            "created_at": "2026-11-20 18:30:00",
            "results": {
                "resume_analysis": {
                    "ats_score": 92,
                    "summary": "Erfahrener Entwickler mit Fachkenntnissen in C++, Rust & Python. Résumé validé.",
                    "strengths": [
                        "Maîtrise approfondie des algorithmes et structures de données",
                        "हिन्दी और अंग्रेज़ी दोनों भाषाओं में उत्कृष्ट संवाद कौशल",
                        "Deep mastery of C++20 and asynchronous I/O",
                    ],
                    "weaknesses": [
                        "Besoin d'expérience avec les conteneurs Docker (≤ 1 an)",
                    ],
                    "grammar_suggestions": ["Ensure “smart quotes” and em—dashes are formatted cleanly."],
                    "formatting_suggestions": [],
                    "overall_recommendation": "Sehr empfehlenswert für internationale Campus-Placements! 🚀",
                },
                "job_match": {
                    "match_percentage": 94,
                    "top_5_resume_changes": [
                        "Préciser l'expérience avec les architectures distribuées.",
                        "Add explicit metrics on C++ memory optimization (reduction of 30% latency).",
                    ],
                },
                "skill_gap": [
                    {
                        "skill": "C++ Template Metaprogramming",
                        "importance": "High",
                        "learning_time": "2 Wochen",
                        "priority": "P1",
                        "learning_resource": "Modern C++ Design (Andrei Alexandrescu)",
                        "project_suggestion": "Build compile-time JSON parser in C++20",
                    }
                ],
                "learning_roadmap": [
                    {
                        "week": "Woche 1",
                        "estimated_hours": 10,
                        "topics": ["C++ Concepts & Constraints"],
                        "coding_practice": ["Implement constexpr matrix multiplier"],
                        "mini_projects": ["Template-based unit testing mini-framework"],
                        "interview_questions": ["Wie funktioniert SFINAE in modernem C++?"],
                        "revision_tasks": ["C++ Core Guidelines wiederholen"],
                    }
                ],
            },
        }

        # 1. Test JSON Export
        json_output = export_analysis_to_json(custom_record)

        # Crucial: Ensure NO escaped unicode sequences like \u00fc or \u0939 appear
        self.assertNotIn(r"\u00fc", json_output)
        self.assertNotIn(r"\u09", json_output)

        # Ensure verbatim unicode presence
        self.assertIn("München Tech GmbH & Co.", json_output)
        self.assertIn("सॉफ्टवेयर इंजीनियर", json_output)
        self.assertIn("CV_François_Müller_2026.pdf", json_output)
        self.assertIn("Résumé validé", json_output)
        self.assertIn("हिन्दी और अंग्रेज़ी", json_output)
        self.assertIn("C++20", json_output)
        self.assertIn("≤ 1 an", json_output)
        self.assertIn("“smart quotes”", json_output)
        self.assertIn("em—dashes", json_output)
        self.assertIn("🚀", json_output)

        # Valid JSON round-trip
        parsed = json.loads(json_output)
        self.assertEqual(parsed["metadata"]["company_name"], "München Tech GmbH & Co.")
        self.assertEqual(parsed["score"], 92)

        # 2. Test Markdown Export
        md_output = export_analysis_to_markdown(custom_record)
        self.assertIn("München Tech GmbH & Co.", md_output)
        self.assertIn("सॉफ्टवेयर इंजीनियर", md_output)
        self.assertIn("François_Müller", md_output)
        self.assertIn("Résumé validé", md_output)
        self.assertIn("हिन्दी और अंग्रेज़ी", md_output)
        self.assertIn("C++ Template Metaprogramming", md_output)
        self.assertIn("🚀", md_output)

    def test_get_export_filename(self):
        """Verifies clean filename sanitization."""
        record = {
            "company_name": "Google LLC / DeepMind",
            "analysis_id": "test:analysis*id#123",
        }
        json_name = get_export_filename(record, "json")
        md_name = get_export_filename(record, "md")

        self.assertTrue(json_name.endswith(".json"))
        self.assertTrue(md_name.endswith(".md"))
        self.assertNotIn("/", json_name)
        self.assertNotIn(":", json_name)
        self.assertNotIn("*", json_name)
        self.assertIn("Google_LLC_DeepMind", json_name)


class TestAnalysisExportRoutes(unittest.TestCase):
    """Integration tests for web download routes and REST API endpoints."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_download_markdown_route_demo_analysis(self):
        """Verifies that /download/<id>/markdown serves a valid UTF-8 Markdown attachment."""
        resp = self.client.get("/download/demo-sample-analysis/markdown")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp.headers.get("Content-Type", ""))
        self.assertIn("utf-8", resp.headers.get("Content-Type", "").lower())
        disposition = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn(".md", disposition)

        body = resp.data.decode("utf-8")
        self.assertIn("# Placement Readiness Report: Google", body)
        self.assertIn("## 1. Readiness Scores & ATS Evaluation", body)
        self.assertIn("## 4. Skill Gap Assessment", body)
        self.assertIn("Distributed System Design", body)

    def test_download_json_route_demo_analysis(self):
        """Verifies that /download/<id>/json serves a valid UTF-8 JSON attachment."""
        resp = self.client.get("/download/demo-sample-analysis/json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        self.assertIn("utf-8", resp.headers.get("Content-Type", "").lower())
        disposition = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn(".json", disposition)

        parsed = json.loads(resp.data.decode("utf-8"))
        self.assertEqual(parsed["version"], "1.0")
        self.assertEqual(parsed["metadata"]["company_name"], "Google")
        self.assertIn("score", parsed)
        self.assertIn("skill_gaps", parsed)
        self.assertIn("interview_tips", parsed)

    def test_download_query_param_format_switch(self):
        """Verifies that /download/<id>?format=markdown and ?format=json redirect/serve correctly."""
        # Query param markdown
        resp_md = self.client.get("/download/demo-sample-analysis?format=markdown")
        self.assertEqual(resp_md.status_code, 200)
        self.assertIn("text/markdown", resp_md.headers.get("Content-Type", ""))
        self.assertIn(".md", resp_md.headers.get("Content-Disposition", ""))

        # Query param json
        resp_json = self.client.get("/download/demo-sample-analysis?format=json")
        self.assertEqual(resp_json.status_code, 200)
        self.assertIn("application/json", resp_json.headers.get("Content-Type", ""))
        self.assertIn(".json", resp_json.headers.get("Content-Disposition", ""))

    def test_api_export_analysis_endpoint(self):
        """Verifies REST API endpoint /api/analysis/<id>/export with json and markdown formats."""
        # JSON API response
        api_resp = self.client.get("/api/analysis/demo-sample-analysis/export?format=json")
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.get_json()
        self.assertTrue(data.get("success"))
        analysis_data = data.get("analysis")
        self.assertEqual(analysis_data["version"], "1.0")
        self.assertEqual(analysis_data["metadata"]["company_name"], "Google")
        self.assertIn("skill_gaps", analysis_data)

        # Markdown API response
        api_md_resp = self.client.get("/api/analysis/demo-sample-analysis/export?format=markdown")
        self.assertEqual(api_md_resp.status_code, 200)
        self.assertIn("# Placement Readiness Report: Google", api_md_resp.data.decode("utf-8"))

        # Download attachment via API
        api_dl_resp = self.client.get("/api/analysis/demo-sample-analysis/export?format=json&download=true")
        self.assertEqual(api_dl_resp.status_code, 200)
        self.assertIn("attachment", api_dl_resp.headers.get("Content-Disposition", ""))

    def test_download_routes_unauthorized_or_nonexistent_handling(self):
        """Verifies graceful handling when an analysis record does not exist."""
        # Non-existent analysis ID
        resp_md = self.client.get("/download/nonexistent-id-99999/markdown")
        self.assertEqual(resp_md.status_code, 302)  # Redirects with flash error

        resp_json = self.client.get("/download/nonexistent-id-99999/json")
        self.assertEqual(resp_json.status_code, 302)

        # API endpoint returns 404
        api_resp = self.client.get("/api/analysis/nonexistent-id-99999/export")
        self.assertEqual(api_resp.status_code, 404)
        data = api_resp.get_json()
        self.assertFalse(data["success"])

    def test_report_and_dashboard_pages_contain_export_buttons(self):
        """Verifies that the HTML report and dashboard views include the Markdown and JSON download options."""
        # 1. HTML report view
        html_report_resp = self.client.get("/report/demo-sample-analysis")
        self.assertEqual(html_report_resp.status_code, 200)
        html_body = html_report_resp.data.decode("utf-8")
        self.assertIn("Download Markdown", html_body)
        self.assertIn("Download JSON", html_body)
        self.assertIn("btnDownloadMarkdownReport", html_body)
        self.assertIn("btnDownloadJsonReport", html_body)

        # 2. Dashboard view
        dash_resp = self.client.get("/dashboard/demo-sample-analysis")
        self.assertEqual(dash_resp.status_code, 200)
        dash_body = dash_resp.data.decode("utf-8")
        self.assertIn("btnDownloadMarkdownNav", dash_body)
        self.assertIn("btnDownloadJsonNav", dash_body)
        self.assertIn("btnDownloadMarkdownSummary", dash_body)
        self.assertIn("btnDownloadJsonSummary", dash_body)
        self.assertIn("btnDownloadMarkdownCard", dash_body)
        self.assertIn("btnDownloadJsonCard", dash_body)


if __name__ == "__main__":
    unittest.main()
