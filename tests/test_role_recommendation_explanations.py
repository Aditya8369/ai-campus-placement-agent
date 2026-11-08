"""
tests/test_role_recommendation_explanations.py
Unit and integration tests for AI Recommendation Explanations for Suggested Career Roles (#295).

Verifies:
1. Reason behind every recommended career role is clearly generated and grounded.
2. Matching skills are accurately extracted and highlighted.
3. Missing skills and their suitability impact are explicitly identified.
4. Projects and experience relevance is evaluated with grounded highlights.
5. Key influencing factors (Technical Skill Overlap, Project Alignment, Bridgeability, Market Demand)
   are calculated with weights and progress percentages.
6. Explanations avoid hallucinating unsupported achievements or experience.
7. Plain English, student-friendly summaries are provided without jargon.
8. API endpoints and template elements support dynamic role switching on desktop and mobile.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from utils.role_recommendation_explainer import (
    explain_role_recommendation,
    generate_all_roles_explanation_summary,
    ROLE_SKILL_PROFILES,
    _skill_matches,
    _normalize_token
)
from agents.role_prep_agent import RolePreparationAgent, role_prep_agent


class TestRoleRecommendationExplainer:
    """Tests for utils/role_recommendation_explainer.py core functions."""

    def test_normalize_token_and_skill_matches(self):
        """Tests token normalization and synonym matching logic."""
        assert _normalize_token("Python 3.10+ / Django") == "python 3 10+ django"
        assert _skill_matches("DSA", "Data Structures") is True
        assert _skill_matches("PostgreSQL", "SQL") is True
        assert _skill_matches("ML", "Machine Learning") is True
        assert _skill_matches("FastAPI", "FastAPI") is True
        assert _skill_matches("Cooking", "Data Structures") is False

    def test_explain_role_recommendation_strong_match(self):
        """
        Tests role explanation for a candidate with high skill overlap for Python Developer.
        Expects 'Strong Match' suitability tier and direct project evidence.
        """
        existing_skills = ["Python", "FastAPI", "Django", "SQL", "Docker", "Pytest"]
        resume_text = (
            "Built a high-performance REST API backend using FastAPI and PostgreSQL. "
            "Implemented Redis caching and automated testing with Pytest in a Docker container."
        )

        result = explain_role_recommendation(
            target_role="Python Developer",
            existing_skills=existing_skills,
            resume_text=resume_text,
            company_name="Acme Corp"
        )

        assert result["role_name"] == "Python Developer"
        assert result["suitability_tier"] == "Strong Match"
        assert result["suitability_score"] >= 70
        assert len(result["matching_skills"]) >= 4
        assert "Python" in result["matching_skills"]
        assert "FastAPI" in result["matching_skills"]

        # Reason contains profile title and match count
        assert "Python Developer" in result["recommendation_reason"]
        assert "Acme Corp" in result["project_experience_relevance"]["summary"]

        # Projects relevance is grounded in provided resume text
        proj = result["project_experience_relevance"]
        assert proj["has_direct_project_evidence"] is True
        assert len(proj["highlights"]) >= 1

        # Missing skills impact is calculated
        assert result["missing_skills_count"] == len(result["missing_skills"])
        assert "missing_skills_impact" in result

        # 4 Influencing factors present
        factors = result["influencing_factors"]
        assert len(factors) == 4
        factor_names = [f["factor"] for f in factors]
        assert "Technical Skill Overlap" in factor_names
        assert "Project & Experience Alignment" in factor_names
        assert "Skill Gap Bridgeability" in factor_names
        assert "Campus Recruitment Demand" in factor_names

        # Plain English summary
        assert "In simple terms:" in result["student_friendly_summary"]
        assert result["profile_grounding"]["is_grounded_in_profile"] is True

    def test_explain_role_recommendation_growth_opportunity(self):
        """
        Tests role explanation for a candidate with minimal overlap (e.g. general CS profile evaluating Data Scientist).
        Expects 'Growth Opportunity' tier, grounded lack of project evidence, and no hallucinated achievements.
        """
        existing_skills = ["HTML", "CSS", "Basic Java"]
        resume_text = "Built a personal portfolio website with HTML and CSS."

        result = explain_role_recommendation(
            target_role="Data Scientist",
            existing_skills=existing_skills,
            resume_text=resume_text
        )

        assert result["role_name"] == "Data Scientist"
        assert result["suitability_tier"] == "Growth Opportunity"
        assert result["suitability_score"] <= 55
        assert result["project_experience_relevance"]["has_direct_project_evidence"] is False

        # Clear explanation that dedicated project is required
        assert "growth path" in result["recommendation_reason"].lower()
        assert len(result["missing_skills"]) >= 5
        assert "Machine Learning" in result["missing_skills"]

        # Plain English student-friendly summary advises learning core tools
        assert "In simple terms:" in result["student_friendly_summary"]

    def test_explain_role_recommendation_data_analyst(self):
        """Tests Data Analyst role explanation with SQL, Pandas and Excel."""
        existing_skills = ["SQL", "Pandas", "Excel", "Data Visualization"]
        resume_text = "Analyzed sales dataset using SQL queries and generated Excel pivot tables."

        result = explain_role_recommendation(
            target_role="Data Analyst",
            existing_skills=existing_skills,
            resume_text=resume_text
        )

        assert result["role_name"] == "Data Analyst"
        assert result["suitability_tier"] in ("Good Match", "Strong Match")
        assert "SQL" in result["matching_skills"]
        assert "Excel" in result["matching_skills"]

    def test_explain_role_recommendation_software_engineer(self):
        """Tests Software Engineer role explanation with DSA, System Design, and C++."""
        existing_skills = ["Data Structures", "Algorithms", "C++", "Git", "OOP"]
        resume_text = "Solved 300+ LeetCode problems on algorithms and data structures. Developed microservice backend."

        result = explain_role_recommendation(
            target_role="Software Engineer",
            existing_skills=existing_skills,
            resume_text=resume_text
        )

        assert result["role_name"] == "Software Engineer"
        assert result["suitability_tier"] in ("Good Match", "Strong Match")
        assert "Data Structures" in result["matching_skills"]
        assert "Algorithms" in result["matching_skills"]

    def test_grounding_with_empty_profile(self):
        """
        Strict profile grounding check:
        When inputs are completely empty, explainer should not invent imaginary skills or projects.
        """
        result = explain_role_recommendation(
            target_role="Software Engineer",
            existing_skills=[],
            resume_text=""
        )

        assert result["matching_skills"] == []
        assert result["matching_skills_count"] == 0
        assert result["suitability_tier"] == "Growth Opportunity"
        assert result["project_experience_relevance"]["has_direct_project_evidence"] is False
        assert "General exposure present" in result["influencing_factors"][1]["description"]

    def test_generate_all_roles_explanation_summary(self):
        """
        Tests ranking and evaluation of all 4 supported roles for a Python-focused candidate.
        Expects Python Developer or Software Engineer at the top of ranked_roles.
        """
        existing_skills = ["Python", "FastAPI", "SQL", "Git"]
        resume_text = "Python backend developer with experience in REST APIs and SQL databases."

        summary = generate_all_roles_explanation_summary(
            existing_skills=existing_skills,
            resume_text=resume_text
        )

        assert summary["success"] is True
        assert summary["total_roles_evaluated"] == 4
        assert len(summary["ranked_roles"]) == 4

        # Verify all 4 roles are in the map
        for role_key in ["Software Engineer", "Python Developer", "Data Analyst", "Data Scientist"]:
            assert role_key in summary["roles"]
            role_eval = summary["roles"][role_key]
            assert "suitability_score" in role_eval
            assert "suitability_tier" in role_eval
            assert "recommendation_reason" in role_eval

        # Ranked roles are ordered descending by suitability score
        scores = [r["suitability_score"] for r in summary["ranked_roles"]]
        assert scores == sorted(scores, reverse=True)


class TestRolePreparationAgentIntegration:
    """Tests integration of AI recommendation explanations into RolePreparationAgent."""

    def test_generate_role_preparation_includes_ai_explanation(self):
        """
        Verifies that role_prep_agent.generate_role_preparation() returns
        both ai_recommendation_explanation and all_recommended_roles_summary.
        """
        agent = RolePreparationAgent()
        result = agent.generate_role_preparation(
            target_role="Software Engineer",
            existing_skills=["Data Structures", "Algorithms", "Python"],
            skill_gaps=["System Design", "Docker"],
            company_name="Microsoft",
            resume_text="CS graduate with strong coding skills in Python and algorithms."
        )

        assert result["success"] is True
        assert "ai_recommendation_explanation" in result
        assert "all_recommended_roles_summary" in result

        ai_rec = result["ai_recommendation_explanation"]
        assert ai_rec["role_name"] == "Software Engineer"
        assert "recommendation_reason" in ai_rec
        assert "matching_skills" in ai_rec
        assert "missing_skills" in ai_rec
        assert "missing_skills_impact" in ai_rec
        assert "project_experience_relevance" in ai_rec
        assert "influencing_factors" in ai_rec
        assert "student_friendly_summary" in ai_rec

        all_roles = result["all_recommended_roles_summary"]
        assert all_roles["total_roles_evaluated"] == 4

    def test_get_all_role_recommendations_helper(self):
        """Tests role_prep_agent.get_all_role_recommendations() helper method."""
        agent = RolePreparationAgent()
        summary = agent.get_all_role_recommendations(
            existing_skills=["SQL", "Python", "Pandas"],
            resume_text="Data analyst intern with SQL queries and dashboarding."
        )

        assert summary["success"] is True
        assert summary["total_roles_evaluated"] == 4
        assert "Data Analyst" in summary["roles"]


class TestFlaskEndpointsAndTemplates:
    """Tests Flask endpoints and template DOM elements for AI explanations."""

    def test_api_role_prep_career_recommendations_not_found(self):
        """Tests /api/role-prep/career-recommendations/<analysis_id> with nonexistent ID."""
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/role-prep/career-recommendations/nonexistent_test_id")
            assert resp.status_code == 404
            data = resp.get_json()
            assert data["success"] is False

    @patch("app.get_analysis")
    def test_api_role_prep_career_recommendations_success(self, mock_get_analysis):
        """Tests /api/role-prep/career-recommendations/<analysis_id> returns ranked roles."""
        mock_get_analysis.return_value = {
            "analysis_id": "test_rec_123",
            "company_name": "TestCorp",
            "resume_text": "Experienced Python and SQL engineer with Django microservices.",
            "results": {
                "job_match": {
                    "matched_skills": ["Python", "SQL", "Django"],
                    "missing_skills": ["Docker", "Kubernetes"]
                },
                "skill_gap": [
                    {"missing_skill": "Docker", "importance": "High"}
                ]
            }
        }

        from app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/role-prep/career-recommendations/test_rec_123")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["total_roles_evaluated"] == 4
            assert len(data["ranked_roles"]) == 4
            assert "Python Developer" in data["roles"]

    @patch("app.get_analysis")
    def test_api_role_prep_for_analysis_includes_explanation(self, mock_get_analysis):
        """Tests /api/role-prep/<analysis_id> includes ai_recommendation_explanation."""
        mock_get_analysis.return_value = {
            "analysis_id": "test_prep_456",
            "company_name": "Google",
            "resume_text": "Software engineer with C++ and Algorithms experience.",
            "results": {
                "job_match": {
                    "matched_skills": ["C++", "Algorithms"],
                    "missing_skills": ["System Design"]
                }
            }
        }

        from app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/role-prep/test_prep_456?role=Software%20Engineer")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert "ai_recommendation_explanation" in data
            assert data["ai_recommendation_explanation"]["role_name"] == "Software Engineer"

    def test_template_role_preparation_dom_ids(self):
        """
        Verifies that templates/role_preparation.html includes all required DOM element IDs
        for displaying AI recommendation explanations on desktop and mobile.
        """
        with open("templates/role_preparation.html", "r", encoding="utf-8") as f:
            html = f.read()

        required_ids = [
            "aiRoleRecommendationCard",
            "aiSuitabilityTierBadge",
            "aiRecReasonText",
            "aiMatchingSkillsCount",
            "aiMatchingSkillsContainer",
            "aiMissingSkillsCount",
            "aiMissingSkillsImpact",
            "aiMissingSkillsContainer",
            "aiProjectRelevanceText",
            "aiProjectHighlightsList",
            "aiInfluencingFactorsContainer",
            "aiStudentSummaryText"
        ]

        for elem_id in required_ids:
            assert f'id="{elem_id}"' in html, f"Missing element ID '{elem_id}' in role_preparation.html"

    def test_template_dashboard_dom_ids(self):
        """
        Verifies that templates/dashboard.html includes all required DOM element IDs
        for displaying AI recommendation explanations in the dashboard prep tab.
        """
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            html = f.read()

        required_ids = [
            "dashAiRecommendationCard",
            "dashAiSuitabilityTierBadge",
            "dashAiRecReasonText",
            "dashAiMatchingSkillsCount",
            "dashAiMatchingSkillsContainer",
            "dashAiMissingSkillsCount",
            "dashAiMissingSkillsImpact",
            "dashAiMissingSkillsContainer",
            "dashAiProjectRelevanceText",
            "dashAiProjectHighlightsList",
            "dashAiInfluencingFactorsContainer",
            "dashAiStudentSummaryText"
        ]

        for elem_id in required_ids:
            assert f'id="{elem_id}"' in html, f"Missing element ID '{elem_id}' in dashboard.html"

    def test_css_mobile_responsiveness(self):
        """
        Verifies that static/css/style.css contains responsive layout rules for
        #aiRoleRecommendationCard and #dashAiRecommendationCard on mobile devices.
        """
        with open("static/css/style.css", "r", encoding="utf-8") as f:
            css = f.read()

        assert "#aiRoleRecommendationCard" in css
        assert "#dashAiRecommendationCard" in css
        assert "@media (max-width: 575.98px)" in css

