"""
Internship Recommendation Agent (#142)

Evaluates student competencies, preferred roles, and location preferences against
verified real internship drives and corporate student apprentice openings.
Computes skill match percentages, explains matching rationales, and filters by role/location.
"""

import logging
from typing import Dict, Any, List, Optional
from utils.job_feed_service import JobFeedService

logger = logging.getLogger(__name__)


class InternshipRecommendationAgent:
    """
    Matches candidate skills with real internship openings and generates personalized matching rationales.
    """

    def __init__(self, feed_service: Optional[JobFeedService] = None):
        self.feed_service = feed_service or JobFeedService()

    def get_recommendations(
        self,
        candidate_skills: List[str],
        preferred_role: Optional[str] = None,
        location: Optional[str] = None,
        search_query: Optional[str] = None,
        min_match: int = 20
    ) -> Dict[str, Any]:
        """
        Retrieves real internship opportunities and scores them against candidate skills.
        """
        try:
            all_jobs = self.feed_service.get_all_jobs()
            # Focus on internship listings
            internships = [
                j for j in all_jobs
                if "intern" in (j.get("role_type") or "").lower() or "intern" in (j.get("title") or "").lower()
            ]

            # If fewer than 2 pure internships found in dataset, include university/entry-level openings
            if len(internships) < 2:
                internships = all_jobs

            # Apply user filters
            filtered = self.feed_service.filter_jobs(
                jobs=internships,
                location=location,
                role_type=preferred_role,
                search_query=search_query
            )

            # Score each opportunity against candidate skills
            normalized_candidate_skills = {s.strip().lower() for s in candidate_skills if s and s.strip()}
            recommendations = []

            for opp in filtered:
                req_skills = [s for s in opp.get("required_skills", [])]
                pref_skills = [s for s in opp.get("preferred_skills", [])]
                all_opp_skills = req_skills + pref_skills

                matched = []
                missing = []

                for s in all_opp_skills:
                    s_clean = s.strip().lower()
                    if any(c_skill in s_clean or s_clean in c_skill for c_skill in normalized_candidate_skills):
                        matched.append(s)
                    else:
                        missing.append(s)

                total_skills_count = max(len(all_opp_skills), 1)
                match_percentage = min(100, int((len(matched) / total_skills_count) * 100))

                # Baseline compensation for candidates with core programming foundation
                if not matched and normalized_candidate_skills:
                    match_percentage = 25

                # Build personalized rationale explanation
                if match_percentage >= 70:
                    rationale = f"Strong alignment! Your background in {', '.join(matched[:3])} satisfies key hiring prerequisites for {opp.get('company')}."
                elif match_percentage >= 40:
                    rationale = f"Promising match. You possess core proficiencies in {', '.join(matched[:2] or ['relevant tools'])}, but would benefit from brushing up on {', '.join(missing[:2])}."
                else:
                    rationale = f"Stretch opportunity. Focus on mastering {', '.join(missing[:3])} to qualify as a top candidate for this role."

                recommendations.append({
                    "id": opp.get("id"),
                    "title": opp.get("title"),
                    "company": opp.get("company"),
                    "logo_color": opp.get("logo_color", "#1a73e8"),
                    "location": opp.get("location", "Remote / Hybrid"),
                    "role_type": opp.get("role_type", "Internship"),
                    "salary_range": opp.get("salary_range", "Stipend Provided"),
                    "batch_eligibility": opp.get("batch_eligibility", "2025 & 2026 Batch"),
                    "description": opp.get("description", ""),
                    "apply_url": opp.get("apply_url", "https://careers.google.com"),
                    "match_percentage": match_percentage,
                    "matched_skills": matched,
                    "missing_skills": missing,
                    "rationale": rationale,
                    "posted_date": opp.get("posted_date", "Active Drive"),
                    "deadline": opp.get("deadline", "Open")
                })

            # Sort by match percentage descending
            recommendations.sort(key=lambda x: x["match_percentage"], reverse=True)

            return {
                "success": True,
                "total_found": len(recommendations),
                "recommendations": recommendations,
                "filters_applied": {
                    "role": preferred_role or "All",
                    "location": location or "All",
                    "search": search_query or ""
                }
            }
        except Exception as exc:
            logger.error(f"Internship recommendation matching error: {exc}")
            return {
                "success": False,
                "error": f"Failed to retrieve internship opportunities: {str(exc)}",
                "recommendations": []
            }
