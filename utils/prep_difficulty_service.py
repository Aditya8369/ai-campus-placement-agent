"""
Role-based Preparation Difficulty Estimate Service (#604)
========================================================
Combines candidate skill gaps and selected role requirements to calculate an
objective preparation difficulty tier (Easy, Moderate, Challenging), the factors
used for the estimate, and an estimated number of practice weeks.

Guarantees:
- Every estimate includes an explicit factor breakdown and explanation.
- Changing the role dynamically updates the estimate.
- Missing skill information defaults gracefully without causing incorrect or misleading estimates.
- Does not make any claim of guaranteed placement success.
"""

from typing import Dict, Any, List, Optional
from utils.role_skill_gap_service import (
    analyze_role_skill_gap,
    extract_candidate_skills,
    get_role_profile,
    get_available_roles
)


def calculate_preparation_difficulty(
    candidate_skills: Any,
    role_id_or_profile: Any,
    hours_per_week: int = 15
) -> Dict[str, Any]:
    """
    Computes preparation difficulty and estimated practice weeks.
    
    Tiers:
    - Easy: 0 to 1 missing core required skill (1-3 practice weeks)
    - Moderate: 2 to 3 missing core skills (4-7 practice weeks)
    - Challenging: 4+ missing core skills or major foundation gap (8-14 practice weeks)
    """
    gap_result = analyze_role_skill_gap(candidate_skills, role_id_or_profile)
    role_profile = gap_result.get("role_profile") or {}
    role_name = role_profile.get("name") or "Target Role"
    role_category = role_profile.get("category") or "Engineering"

    missing_skills = gap_result.get("missing_skills") or []
    matched_skills = gap_result.get("matched_skills") or []
    match_percentage = gap_result.get("match_percentage", 0)

    missing_required = [s for s in missing_skills if s.get("type") == "Required"]
    missing_nice = [s for s in missing_skills if s.get("type") == "Nice-to-Have"]

    num_req_missing = len(missing_required)
    num_nice_missing = len(missing_nice)
    total_missing = len(missing_skills)

    # Base difficulty calculation
    factors = []
    
    total_required = len(role_profile.get("required_skills") or []) or 1
    req_match_ratio = (total_required - num_req_missing) / total_required

    # Base difficulty calculation
    factors = []

    if num_req_missing <= 1 or req_match_ratio >= 0.8:
        difficulty_tier = "Easy"
        base_weeks = 2 if num_nice_missing > 0 else 1
        factors.append({
            "factor": "High Core Alignment",
            "impact": "Favorable",
            "description": f"You already have strong alignment with required competencies for {role_name}."
        })
    elif num_req_missing <= 4 or req_match_ratio >= 0.45:
        difficulty_tier = "Moderate"
        base_weeks = 3 + num_req_missing
        factors.append({
            "factor": "Moderate Core Gap",
            "impact": "Manageable",
            "description": f"Missing {num_req_missing} required competency: {', '.join([s['skill'] for s in missing_required[:4]])}."
        })
    else:
        difficulty_tier = "Challenging"
        base_weeks = min(14, 6 + num_req_missing)
        factors.append({
            "factor": "Significant Foundational Gap",
            "impact": "High Effort",
            "description": f"Missing {num_req_missing} core competencies. Preparation requires fundamental conceptual learning."
        })

    # Adjust weeks slightly by study hours if provided
    hours = max(5, min(40, hours_per_week or 15))
    if hours >= 25:
        estimated_weeks = max(1, round(base_weeks * 0.8))
        factors.append({
            "factor": "Intensive Study Availability",
            "impact": "Accelerated",
            "description": f"Allocating ~{hours} hrs/week helps complete milestones quicker."
        })
    elif hours <= 10:
        estimated_weeks = round(base_weeks * 1.3)
        factors.append({
            "factor": "Part-Time Study Schedule",
            "impact": "Extended",
            "description": f"Allocating ~{hours} hrs/week requires pacing learning over more calendar weeks."
        })
    else:
        estimated_weeks = base_weeks

    # Explanation in plain language
    if difficulty_tier == "Easy":
        explanation = (
            f"Preparation for {role_name} appears Easy for your profile because your current skills cover "
            f"the majority of requirements ({match_percentage}% compatibility). Focused mock interview practice "
            f"and revision for ~{estimated_weeks} weeks is recommended."
        )
    elif difficulty_tier == "Moderate":
        explanation = (
            f"Preparation for {role_name} is Moderate ({match_percentage}% compatibility). You have a solid base, "
            f"but need dedicated hands-on project work in {num_req_missing} key competency areas over approximately "
            f"{estimated_weeks} practice weeks."
        )
    else:
        explanation = (
            f"Preparation for {role_name} is Challenging ({match_percentage}% compatibility). Multiple core prerequisites "
            f"need to be learned from fundamentals. Plan for around {estimated_weeks} weeks of structured practice."
        )

    return {
        "role_id": role_profile.get("id"),
        "role_name": role_name,
        "role_category": role_category,
        "difficulty_tier": difficulty_tier,
        "estimated_weeks": estimated_weeks,
        "match_percentage": match_percentage,
        "missing_required_count": num_req_missing,
        "missing_nice_count": num_nice_missing,
        "total_missing_skills": total_missing,
        "missing_skills_list": [s["skill"] for s in missing_skills],
        "factors": factors,
        "explanation": explanation,
        "disclaimer": "This difficulty estimate is an educational guideline based on skill gap heuristics and does not constitute a guarantee of interview success or job placement."
    }
