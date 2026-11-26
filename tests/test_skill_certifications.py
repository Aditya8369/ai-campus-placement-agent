"""
Tests for Skill Gap Certifications and Courses Recommendation Feature (#757).

Acceptance Criteria:
1. A new entry can be added by editing the data file only.
2. Skills without entries show a generic message.
3. Every entry displays its last-verified date.
4. Up to three options shown for each missing skill.
5. Links verified and contribution template provided.
"""

import os
import re
import json
import pytest
from app import create_app
from utils.skill_certification_service import (
    SkillCertificationService,
    SKILL_CERTIFICATIONS_PATH,
    DEFAULT_GENERIC_MESSAGE,
    normalize_skill_name,
)

DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


class TestSkillCertificationsDataFileAndSchema:
    """Validates the schema, verification dates, and contribution template."""

    def test_certifications_data_file_exists_and_is_valid_json(self):
        assert os.path.exists(SKILL_CERTIFICATIONS_PATH), "data/skill_certifications.json must exist"
        with open(SKILL_CERTIFICATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, dict), "Root must be a JSON object"
        skills_dict = data.get("skills") if "skills" in data else data
        assert len(skills_dict) >= 20, "Must cover at least 20 skills"

    def test_every_entry_has_required_fields_and_verified_date(self):
        """Acceptance Criterion: Every entry displays its last-verified date, provider, level, type, duration, url."""
        data = SkillCertificationService.load_data(force_reload=True)
        assert len(data) >= 20, "Should have loaded at least 20 skills"

        total_entries = 0
        for skill_name, entries in data.items():
            assert isinstance(entries, list), f"Entries for {skill_name} must be a list"
            assert len(entries) > 0, f"Entries for {skill_name} cannot be empty"

            for entry in entries:
                total_entries += 1
                # 1. Title/Name
                title = entry.get("title") or entry.get("name")
                assert title and isinstance(title, str), f"Missing title in {skill_name}"

                # 2. Provider
                provider = entry.get("provider")
                assert provider and isinstance(provider, str), f"Missing provider in {skill_name} entry: {title}"

                # 3. Level (Beginner / Intermediate / Advanced)
                level = entry.get("level")
                assert level and isinstance(level, str), f"Missing level in {skill_name} entry: {title}"

                # 4. Type (Free / Paid / Free to Audit)
                price_type = entry.get("type")
                assert price_type and isinstance(price_type, str), f"Missing type in {skill_name} entry: {title}"

                # 5. Duration
                duration = entry.get("duration")
                assert duration and isinstance(duration, str), f"Missing duration in {skill_name} entry: {title}"

                # 6. URL
                url = entry.get("url")
                assert url and (url.startswith("http://") or url.startswith("https://")), f"Invalid URL in {skill_name}: {url}"

                # 7. Last-Verified Date (Acceptance Criterion: Every entry displays its last-verified date)
                last_verified = entry.get("last_verified")
                assert last_verified, f"Missing last_verified date in {skill_name} entry: {title}"
                assert DATE_REGEX.match(str(last_verified)), f"last_verified must be YYYY-MM-DD in {skill_name}: {last_verified}"

        assert total_entries >= 40, "Expected at least 40 curated entries across all skills"

    def test_contribution_template_exists(self):
        """Verifies that the contribution template exists and provides guidance."""
        template_path = os.path.join(os.path.dirname(SKILL_CERTIFICATIONS_PATH), "certification_contribution_template.json")
        assert os.path.exists(template_path), "data/certification_contribution_template.json must exist"

        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)

        assert "$schema_description" in template or "instructions" in template
        assert "example_submission" in template or "certifications" in template

        # Also check CONTRIBUTING_CERTIFICATIONS.md
        contrib_doc = os.path.join(os.path.dirname(os.path.dirname(SKILL_CERTIFICATIONS_PATH)), "CONTRIBUTING_CERTIFICATIONS.md")
        assert os.path.exists(contrib_doc), "CONTRIBUTING_CERTIFICATIONS.md must exist in repository root"


class TestSkillCertificationServiceLogic:
    """Verifies core service behaviors including limit, generic message, alias matching, and file-only additions."""

    def test_up_to_three_options_returned_per_skill(self):
        """Requirement: Show up to three options for each missing skill."""
        rec = SkillCertificationService.get_certifications_for_skill("Python", limit=3)
        assert rec["has_recommendations"] is True
        assert len(rec["certifications"]) <= 3
        assert rec["count"] <= 3
        for cert in rec["certifications"]:
            assert cert["last_verified"]
            assert cert["provider"]
            assert cert["type"]

    def test_skills_without_entries_show_generic_message(self):
        """Acceptance Criterion: Skills without entries show a generic message."""
        unlisted_skill = "NonExistentQuantumSkillXyz123"
        rec = SkillCertificationService.get_certifications_for_skill(unlisted_skill)

        assert rec["has_recommendations"] is False
        assert rec["certifications"] == []
        assert rec["count"] == 0
        assert rec["generic_message"] is not None
        assert "No curated certifications or courses" in rec["generic_message"]

    def test_alias_resolution_for_skills(self):
        """Verifies aliases like 'k8s' -> Kubernetes, 'js' -> JavaScript, 'postgres' -> PostgreSQL."""
        k8s_rec = SkillCertificationService.get_certifications_for_skill("k8s")
        assert k8s_rec["has_recommendations"] is True
        assert len(k8s_rec["certifications"]) > 0

        js_rec = SkillCertificationService.get_certifications_for_skill("js")
        assert js_rec["has_recommendations"] is True
        assert len(js_rec["certifications"]) > 0

        pg_rec = SkillCertificationService.get_certifications_for_skill("postgres")
        assert pg_rec["has_recommendations"] is True
        assert len(pg_rec["certifications"]) > 0

    def test_new_entry_added_by_editing_data_file_only(self):
        """Acceptance Criterion: A new entry can be added by editing the data file only."""
        # Read current data file
        with open(SKILL_CERTIFICATIONS_PATH, "r", encoding="utf-8") as f:
            original_content = f.read()

        try:
            data = json.loads(original_content)
            skills_target = data.get("skills", data)
            test_skill_name = "SuperTestFramework99"
            skills_target[test_skill_name] = [
                {
                    "title": "SuperTest Complete Mastery",
                    "provider": "SuperTest Academy",
                    "level": "Beginner",
                    "type": "Free",
                    "duration": "8 hours",
                    "url": "https://example.com/supertest",
                    "last_verified": "2026-11-25"
                }
            ]

            # Write updated JSON to file
            with open(SKILL_CERTIFICATIONS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Query service - should automatically detect file change and return the new entry
            rec = SkillCertificationService.get_certifications_for_skill(test_skill_name)
            assert rec["has_recommendations"] is True
            assert rec["count"] == 1
            assert rec["certifications"][0]["title"] == "SuperTest Complete Mastery"
            assert rec["certifications"][0]["provider"] == "SuperTest Academy"
            assert rec["certifications"][0]["last_verified"] == "2026-11-25"

        finally:
            # Restore original data file exactly
            with open(SKILL_CERTIFICATIONS_PATH, "w", encoding="utf-8") as f:
                f.write(original_content)
            SkillCertificationService.reload_data()

    def test_enrich_skill_gap_items(self):
        """Verifies skill gap list enrichment for dashboard rendering."""
        gaps = [
            {"skill": "Python", "importance": "High"},
            {"skill": "TotallyUnknownSkill404", "importance": "Medium"}
        ]
        enriched = SkillCertificationService.enrich_skill_gap_items(gaps)
        assert len(enriched) == 2

        # First gap has recommendations
        assert enriched[0]["has_certification_recommendations"] is True
        assert len(enriched[0]["recommended_certifications"]) <= 3
        assert enriched[0]["recommended_certifications"][0]["last_verified"]

        # Second gap has generic message
        assert enriched[1]["has_certification_recommendations"] is False
        assert enriched[1]["recommended_certifications"] == []
        assert "No curated certifications or courses" in enriched[1]["certifications_generic_message"]


class TestSkillCertificationsAPIRoutes:
    """Tests the REST API routes for querying certifications."""

    def test_api_get_skill_certifications_found(self, client):
        resp = client.get("/api/skills/certifications?skill=Docker")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        rec = data["data"]
        assert rec["has_recommendations"] is True
        assert rec["count"] >= 1
        assert rec["certifications"][0]["last_verified"]
        assert rec["certifications"][0]["provider"]

    def test_api_get_skill_certifications_unlisted_generic_message(self, client):
        resp = client.get("/api/skills/certifications?skill=ObscureFrameworkX99")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        rec = data["data"]
        assert rec["has_recommendations"] is False
        assert rec["certifications"] == []
        assert "No curated certifications or courses" in rec["generic_message"]

    def test_api_get_skill_certifications_missing_param(self, client):
        resp = client.get("/api/skills/certifications")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "required" in data["error"]

    def test_api_batch_skill_certifications(self, client):
        resp = client.post("/api/skills/certifications/batch", json={
            "skills": ["AWS", "Kubernetes", "UnknownSkillFoo"]
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["count"] == 3
        # First two have certifications
        assert data["results"][0]["has_recommendations"] is True
        assert data["results"][1]["has_recommendations"] is True
        # Third has generic message
        assert data["results"][2]["has_recommendations"] is False
        assert data["results"][2]["generic_message"] is not None


class TestDashboardTemplateCertificationsUI:
    """Verifies that templates/dashboard.html renders certification options, verified date, and generic message."""

    def test_dashboard_template_contains_certifications_markup(self):
        template_path = os.path.join(os.path.dirname(SKILL_CERTIFICATIONS_PATH), "..", "templates", "dashboard.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        assert "skill-certifications-block" in html
        assert "Recommended Certifications &amp; Courses:" in html
        assert "cert-last-verified-badge" in html
        assert "Verified: {{ cert.last_verified }}" in html
        assert "skill-cert-generic-msg" in html
        assert "gap.certifications_generic_message" in html
