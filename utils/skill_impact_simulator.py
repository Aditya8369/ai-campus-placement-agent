"""
Skill Impact Simulator Engine (#557)
=====================================
Calculates projected job match improvements when a student assumes they learn
one or more missing skills identified during resume and job description
analysis.

Features:
- Deterministic recalculation using the original analysis weighting without
  any AI calls.
- Individual contribution ranking to highlight the best next skill to learn.
- Consistent baseline: returns original score when nothing is ticked.
- Support for single skill, multiple skills, and empty missing skills states.
- Clean disclaimer clarifying estimates are based on the pasted job
  description.
"""

from typing import Any, Dict, List, Optional, Set, Union


# Weight mappings for skill importance / priority
IMPORTANCE_WEIGHTS: Dict[str, float] = {
    "critical": 3.0,
    "high": 3.0,
    "required": 3.0,
    "medium": 2.0,
    "moderate": 2.0,
    "low": 1.0,
    "nice-to-have": 1.0,
    "optional": 1.0,
}
DEFAULT_SKILL_WEIGHT: float = 2.0

SIMULATION_DISCLAIMER: str = (
    "This is an estimated projection calculated deterministically from the "
    "competencies extracted from your provided job description and resume. "
    "Individual recruiter weightings may vary."
)


def normalize_skill_name(name: Any) -> str:
    """Returns trimmed, lowercase normalized skill name for comparison."""
    if not name:
        return ""
    return str(name).strip().lower()


def extract_skill_metadata(
    raw_skill: Union[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Extracts standardized metadata from a skill item."""
    if isinstance(raw_skill, dict):
        name = str(
            raw_skill.get("skill")
            or raw_skill.get("name")
            or raw_skill.get("missing_skill")
            or ""
        ).strip()
        imp_raw = str(raw_skill.get("importance", "")).strip().capitalize()
        importance = imp_raw or "Medium"
        prio_raw = str(raw_skill.get("priority", "")).strip().capitalize()
        priority = prio_raw or "Medium"
        is_required = bool(raw_skill.get("is_required", False))
        lt_raw = raw_skill.get("learning_time", "1-2 weeks")
        learning_time = str(lt_raw).strip()
        project_sugg = str(raw_skill.get("project_suggestion", "")).strip()

        # Determine weight
        lookup_key = (
            "required"
            if is_required
            else (
                importance.lower()
                if importance.lower() in IMPORTANCE_WEIGHTS
                else priority.lower()
            )
        )
        weight = IMPORTANCE_WEIGHTS.get(lookup_key, DEFAULT_SKILL_WEIGHT)
    else:
        name = str(raw_skill).strip()
        importance = "Medium"
        priority = "Medium"
        is_required = False
        learning_time = "1-2 weeks"
        project_sugg = ""
        weight = DEFAULT_SKILL_WEIGHT

    return {
        "skill": name,
        "importance": importance,
        "priority": priority,
        "is_required": is_required,
        "learning_time": learning_time,
        "project_suggestion": project_sugg,
        "weight": weight,
    }


def calculate_individual_gains(
    missing_items: List[Dict[str, Any]],
    original_percentage: int
) -> List[Dict[str, Any]]:
    """
    Ranks missing skills by their individual contribution to closing the gap.
    Skills with higher importance/priority have higher weights and yield
    greater boosts.
    """
    if not missing_items:
        return []

    gap_to_100 = max(0, 100 - original_percentage)
    total_missing_weight = sum(item["weight"] for item in missing_items)

    ranked: List[Dict[str, Any]] = []
    for item in missing_items:
        if total_missing_weight > 0 and gap_to_100 > 0:
            raw_gain = (item["weight"] / total_missing_weight) * gap_to_100
            gain = round(raw_gain, 1)
        else:
            gain = 0.0

        ranked.append({
            "skill": item["skill"],
            "importance": item["importance"],
            "priority": item["priority"],
            "is_required": item["is_required"],
            "weight": item["weight"],
            "learning_time": item["learning_time"],
            "project_suggestion": item["project_suggestion"],
            "individual_gain": gain,
            "individual_gain_str": f"+{gain:.1f}%" if gain > 0 else "0%",
        })

    # Sort descending by individual_gain, then weight, then alphabetically
    ranked.sort(
        key=lambda x: (-x["individual_gain"], -x["weight"], x["skill"].lower())
    )

    # Assign rank indices and highlight the best next skill
    for idx, r in enumerate(ranked, start=1):
        r["rank"] = idx
        r["is_best_next"] = (idx == 1 and r["individual_gain"] > 0)

    return ranked


def simulate_job_match(
    matched_skills: List[Union[str, Dict[str, Any]]],
    missing_skills: List[Union[str, Dict[str, Any]]],
    ticked_skills: Optional[List[str]] = None,
    original_percentage: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Recalculates the job match percentage deterministically when a student
    assumes they learn one or more missing skills (#557).

    Args:
        matched_skills: list of matched skill names or dicts
        missing_skills: list of missing skill names or dicts
        ticked_skills: list of missing skill names assumed learned
        original_percentage: baseline match percentage

    Returns:
        Dict with before, after, change, ranked skills list, and best next.
    """
    # 1. Clean and deduplicate matched skills
    clean_matched: List[str] = []
    seen_matched: Set[str] = set()
    for s in matched_skills or []:
        name = str(s.get("skill") if isinstance(s, dict) else s).strip()
        if name and name.lower() not in seen_matched:
            clean_matched.append(name)
            seen_matched.add(name.lower())

    # 2. Clean and structure missing skills
    missing_items: List[Dict[str, Any]] = []
    seen_missing: Set[str] = set()
    for s in missing_skills or []:
        meta = extract_skill_metadata(s)
        norm = meta["skill"].lower()
        if (
            meta["skill"]
            and norm not in seen_missing
            and norm not in seen_matched
        ):
            missing_items.append(meta)
            seen_missing.add(norm)

    total_skills = len(clean_matched) + len(missing_items)

    # 3. Determine baseline original percentage
    if original_percentage is not None:
        orig_pct = max(0, min(100, int(original_percentage)))
    else:
        if total_skills > 0:
            orig_pct = round((len(clean_matched) / total_skills) * 100)
        else:
            orig_pct = 0

    # 4. Rank missing skills by individual contribution
    ranked_skills = calculate_individual_gains(missing_items, orig_pct)
    best_next_skill = None
    if ranked_skills:
        best_next_skill = (
            ranked_skills[0]
            if ranked_skills[0].get("is_best_next")
            else ranked_skills[0]
        )

    # 5. Process ticked skills
    ticked_set: Set[str] = {
        normalize_skill_name(t)
        for t in (ticked_skills or [])
        if t and str(t).strip()
    }

    # Filter ticked skills to those that actually exist in missing_items
    valid_ticked_items = [
        item for item in missing_items
        if item["skill"].lower() in ticked_set
    ]
    ticked_count = len(valid_ticked_items)

    # 6. Calculate simulated match percentage
    if not missing_items or ticked_count == 0:
        simulated_pct = orig_pct
        pct_change = 0
    else:
        total_missing_weight = sum(item["weight"] for item in missing_items)
        ticked_weight = sum(item["weight"] for item in valid_ticked_items)
        gap_to_100 = max(0, 100 - orig_pct)

        if total_missing_weight > 0 and gap_to_100 > 0:
            boost = (ticked_weight / total_missing_weight) * gap_to_100
            simulated_pct = min(100, max(0, int(round(orig_pct + boost))))
        else:
            simulated_pct = orig_pct

        pct_change = simulated_pct - orig_pct

    # Mark which ranked skills are currently ticked
    for r in ranked_skills:
        r["is_ticked"] = (r["skill"].lower() in ticked_set)

    change_str = f"+{pct_change}%" if pct_change > 0 else f"{pct_change}%"

    return {
        "original_percentage": orig_pct,
        "simulated_percentage": simulated_pct,
        "percentage_change": pct_change,
        "percentage_change_str": change_str,
        "ticked_skills": [item["skill"] for item in valid_ticked_items],
        "ticked_count": ticked_count,
        "total_missing_count": len(missing_items),
        "remaining_missing_count": len(missing_items) - ticked_count,
        "ranked_skills": ranked_skills,
        "best_next_skill": best_next_skill,
        "has_missing_skills": bool(missing_items),
        "disclaimer": SIMULATION_DISCLAIMER,
    }


def get_skill_simulation_data(
    analysis_record: Optional[Dict[str, Any]],
    ticked_skills: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Convenience helper extracting data from an analysis record to run
    the simulation (#557).
    """
    if not analysis_record:
        return simulate_job_match(
            [], [], ticked_skills=ticked_skills, original_percentage=0
        )

    results = analysis_record.get("results") or {}
    job_match = (
        results.get("job_match")
        or results.get("job_compatibility")
        or {}
    )

    matched_skills = (
        job_match.get("matched_skills")
        or job_match.get("matching_skills")
        or []
    )
    missing_skills = (
        results.get("skill_gap")
        or job_match.get("missing_skills")
        or []
    )

    # If skill_gap is missing from results, try job_match.missing_skills
    if not missing_skills and job_match.get("missing_skills"):
        missing_skills = job_match["missing_skills"]

    original_percentage = None
    if "match_percentage" in job_match:
        try:
            original_percentage = int(job_match["match_percentage"])
        except (ValueError, TypeError):
            pass

    return simulate_job_match(
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        ticked_skills=ticked_skills,
        original_percentage=original_percentage,
    )
