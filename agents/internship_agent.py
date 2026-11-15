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
        work_mode: Optional[str] = None,
        stipend_type: Optional[str] = None,
        duration: Optional[str] = None,
        technology: Optional[str] = None,
        deadline_status: Optional[str] = None,
        include_unspecified: bool = True,
        min_match: int = 20
    ) -> Dict[str, Any]:
        """
        Retrieves real internship opportunities and scores them against candidate skills (#142, #356).
        Applies multi-dimensional search filtering: location, role, work mode, stipend, duration,
        technology, and application deadline status.
        """
        try:
            from utils.job_dedup_expiration import process_jobs_feed_with_expiration_and_dedup
            from utils.job_feed_service import extract_job_filter_metadata

            raw_all_jobs = self.feed_service.get_all_jobs()
            processed_feed = process_jobs_feed_with_expiration_and_dedup(raw_all_jobs, hide_expired=False)
            all_jobs = processed_feed["jobs"]

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
                search_query=search_query,
                work_mode=work_mode,
                stipend_type=stipend_type,
                duration=duration,
                technology=technology,
                deadline_status=deadline_status,
                include_unspecified=include_unspecified
            )

            # Score each opportunity against candidate skills
            normalized_candidate_skills = {s.strip().lower() for s in candidate_skills if s and s.strip()}
            recommendations = []

            for opp in filtered:
                meta = extract_job_filter_metadata(opp)
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
                    "work_mode": opp.get("work_mode") or meta.get("work_mode", "Not Specified"),
                    "work_mode_specified": meta.get("work_mode_specified", False),
                    "role_type": opp.get("role_type", "Internship"),
                    "duration": opp.get("duration") or meta.get("duration", "Not Specified"),
                    "duration_specified": meta.get("duration_specified", False),
                    "salary_range": opp.get("salary_range", "Stipend Provided"),
                    "stipend_type": meta.get("stipend_type", "Paid Stipend"),
                    "stipend_specified": meta.get("stipend_specified", False),
                    "batch_eligibility": opp.get("batch_eligibility", "2025 & 2026 Batch"),
                    "description": opp.get("description", ""),
                    "apply_url": opp.get("apply_url", "https://careers.google.com"),
                    "match_percentage": match_percentage,
                    "matched_skills": matched,
                    "missing_skills": missing,
                    "technologies": meta.get("technologies", []),
                    "rationale": rationale,
                    "posted_date": opp.get("posted_date", "Active Drive"),
                    "deadline": opp.get("deadline", "Open"),
                    "deadline_status": meta.get("deadline_status", "Active Drives"),
                    "deadline_specified": meta.get("deadline_specified", False),
                    "unspecified_fields": meta.get("unspecified_fields", [])
                })

            # Sort by match percentage descending
            recommendations.sort(key=lambda x: x["match_percentage"], reverse=True)

            # Available location and role options for dynamic UI dropdowns
            available_locations = ["All", "Bengaluru", "Hyderabad", "Pune", "Mumbai", "Noida", "Remote"]
            for opp in internships:
                loc_cand = opp.get("location")
                if loc_cand and loc_cand not in available_locations and loc_cand != "Remote / Hybrid":
                    available_locations.append(loc_cand)

            return {
                "success": True,
                "total_found": len(recommendations),
                "recommendations": recommendations,
                "filters_applied": {
                    "role": preferred_role or "All",
                    "location": location or "All",
                    "search": search_query or "",
                    "work_mode": work_mode or "All",
                    "stipend": stipend_type or "All",
                    "duration": duration or "All",
                    "technology": technology or "All",
                    "deadline": deadline_status or "All",
                    "include_unspecified": include_unspecified
                },
                "filter_options": {
                    "locations": available_locations,
                    "work_modes": ["All", "Remote", "On-site", "Hybrid"],
                    "stipends": ["All", "Paid Stipend", "Unpaid / Any"],
                    "durations": ["All", "1-2 Months", "3 Months", "6 Months"],
                    "technologies": ["All", "Python", "Java", "C++", "React", "JavaScript", "TypeScript", "Node.js", "SQL", "Go", "Docker", "Kubernetes", "AWS", "Machine Learning"],
                    "roles": ["All", "Software Engineer", "Backend Developer", "Frontend Developer", "Data & AI", "Cloud & DevOps"],
                    "deadlines": ["All", "Active Drives", "Closing Soon"]
                }
            }
        except Exception as exc:
            logger.error(f"Internship recommendation matching error: {exc}")
            return {
                "success": False,
                "error": f"Failed to retrieve internship opportunities: {str(exc)}",
                "recommendations": []
            }
