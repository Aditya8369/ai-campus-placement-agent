"""
Resume Improvement Simulator Service (#600)
===========================================
Allows students to test "What-If" scenarios (e.g. adding missing skills,
quantifying project metrics, completing role-aligned projects) and see estimated
impacts on their ATS and Placement Readiness Scores before modifying their actual resume.

Guarantees:
1. The original analysis and resume text remain completely unchanged and read-only.
2. Simulated changes are never saved to the stored resume or analysis in the database.
3. Estimates clearly explain contributing factors and disclaim guarantees.
"""

from typing import Dict, Any, List, Optional
import copy


DEFAULT_WHAT_IF_SUGGESTIONS = [
    {
        "id": "add_cloud_devops",
        "title": "Add Docker & AWS / Cloud Deployment",
        "category": "skill",
        "detail": "Demonstrate containerization and modern cloud architecture on projects.",
        "skills": ["Docker", "AWS", "CI/CD"],
        "project": None,
        "estimated_ats_delta": 6,
        "estimated_match_delta": 8,
    },
    {
        "id": "add_system_design",
        "title": "Add Microservices & System Architecture",
        "category": "project",
        "detail": "Highlight scalable backend design, API gateways, and distributed caching (Redis).",
        "skills": ["System Design", "Microservices", "Redis"],
        "project": "Scalable Distributed Backend Service",
        "estimated_ats_delta": 8,
        "estimated_match_delta": 10,
    },
    {
        "id": "add_unit_testing",
        "title": "Add Test Automation & CI/CD Pipeline",
        "category": "skill",
        "detail": "Include unit/integration test coverage (pytest / JUnit) in project descriptions.",
        "skills": ["Automated Testing", "PyTest", "GitHub Actions"],
        "project": None,
        "estimated_ats_delta": 5,
        "estimated_match_delta": 6,
    },
    {
        "id": "quantify_impact",
        "title": "Quantify Project Impact & Metrics",
        "category": "project",
        "detail": "Add measurable achievements (e.g. 'improved latency by 35%', 'handled 10k requests').",
        "skills": ["Performance Optimization", "Data Analytics"],
        "project": "Production-Grade High-Throughput System",
        "estimated_ats_delta": 7,
        "estimated_match_delta": 7,
    },
    {
        "id": "add_dsa_problem_solving",
        "title": "Highlight Data Structures & Algorithmic Complexities",
        "category": "skill",
        "detail": "Mention algorithmic problem solving, time/space complexity optimizations.",
        "skills": ["Data Structures", "Algorithms", "Optimization"],
        "project": None,
        "estimated_ats_delta": 6,
        "estimated_match_delta": 8,
    }
]


def get_default_what_if_suggestions(analysis_record: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Returns curated What-If suggestions tailored to the student's analysis gaps if available.
    """
    suggestions = [dict(s) for s in DEFAULT_WHAT_IF_SUGGESTIONS]
    
    if not analysis_record:
        return suggestions

    results = analysis_record.get("results") or {}
    skill_gaps = results.get("skill_gap") or []
    
    # Extract string skill names from skill_gaps if available
    gap_names = []
    if isinstance(skill_gaps, list):
        for g in skill_gaps:
            if isinstance(g, dict) and "skill" in g:
                gap_names.append(g["skill"])
            elif isinstance(g, str):
                gap_names.append(g)

    # If there are specific skill gaps, generate a dynamic tailored suggestion
    if gap_names:
        top_gaps = gap_names[:3]
        tailored = {
            "id": "tailored_gap_fix",
            "title": f"Bridge Priority Gaps: {', '.join(top_gaps)}",
            "category": "skill",
            "detail": f"Incorporate target role competencies ({', '.join(top_gaps)}) into your technical stack.",
            "skills": top_gaps,
            "project": None,
            "estimated_ats_delta": min(10, len(top_gaps) * 4),
            "estimated_match_delta": min(12, len(top_gaps) * 4),
            "is_tailored": True
        }
        suggestions.insert(0, tailored)

    return suggestions


def simulate_resume_improvements(
    analysis_record: Dict[str, Any],
    simulated_skills: Optional[List[str]] = None,
    simulated_projects: Optional[List[str]] = None,
    selected_suggestion_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Recalculates an estimated Placement Readiness Score and ATS score on an in-memory copy
    of the existing analysis without persisting or altering the original report.

    Returns the simulation results comparing base vs estimated scores.
    """
    if not analysis_record:
        raise ValueError("Valid analysis record is required for simulation.")

    # Work purely on an isolated deep copy
    simulated_analysis = copy.deepcopy(analysis_record)
    results = simulated_analysis.get("results") or {}
    resume_analysis = results.get("resume_analysis") or {}
    job_match = results.get("job_match") or {}

    base_ats_score = int(resume_analysis.get("ats_score") or 0)
    base_match_score = int(job_match.get("match_percentage") or 0)
    base_readiness_score = int(round((base_ats_score * 0.5) + (base_match_score * 0.5)))

    simulated_skills = [s.strip() for s in (simulated_skills or []) if s and s.strip()]
    simulated_projects = [p.strip() for p in (simulated_projects or []) if p and p.strip()]
    selected_ids = set(selected_suggestion_ids or [])

    # Factor calculations
    ats_boost = 0
    match_boost = 0
    factors_applied = []

    # Apply selected catalog suggestions
    catalog = {s["id"]: s for s in get_default_what_if_suggestions(analysis_record)}
    for sid in selected_ids:
        if sid in catalog:
            item = catalog[sid]
            ats_boost += item.get("estimated_ats_delta", 5)
            match_boost += item.get("estimated_match_delta", 6)
            factors_applied.append({
                "source": "suggestion",
                "id": sid,
                "title": item["title"],
                "ats_impact": item.get("estimated_ats_delta", 5),
                "match_impact": item.get("estimated_match_delta", 6),
                "description": item.get("detail", "")
            })

    # Apply custom skills added by student
    if simulated_skills:
        skill_ats_gain = min(15, len(simulated_skills) * 4)
        skill_match_gain = min(18, len(simulated_skills) * 5)
        ats_boost += skill_ats_gain
        match_boost += skill_match_gain
        factors_applied.append({
            "source": "custom_skills",
            "skills": simulated_skills,
            "title": f"Added {len(simulated_skills)} Simulated Skill(s): {', '.join(simulated_skills)}",
            "ats_impact": skill_ats_gain,
            "match_impact": skill_match_gain,
            "description": "Expanded technical domain coverage with relevant target keywords."
        })

    # Apply custom projects added by student
    if simulated_projects:
        project_ats_gain = min(12, len(simulated_projects) * 6)
        project_match_gain = min(15, len(simulated_projects) * 7)
        ats_boost += project_ats_gain
        match_boost += project_match_gain
        factors_applied.append({
            "source": "custom_projects",
            "projects": simulated_projects,
            "title": f"Added {len(simulated_projects)} Simulated Project(s)",
            "ats_impact": project_ats_gain,
            "match_impact": project_match_gain,
            "description": "Demonstrated hands-on domain engineering with full-stack or architecture work."
        })

    # Cap estimated scores reasonably at 98%
    estimated_ats_score = min(98, base_ats_score + ats_boost)
    estimated_match_score = min(98, base_match_score + match_boost)
    estimated_readiness_score = int(round((estimated_ats_score * 0.5) + (estimated_match_score * 0.5)))

    ats_delta = estimated_ats_score - base_ats_score
    match_delta = estimated_match_score - base_match_score
    readiness_delta = estimated_readiness_score - base_readiness_score

    def _determine_status(ats: int, match: int) -> str:
        if ats >= 75 and match >= 65:
            return "Placement Ready"
        if ats >= 67 and match >= 57:
            return "Targeted Prep Needed"
        return "Foundation Building Required"

    base_status = _determine_status(base_ats_score, base_match_score)
    estimated_status = _determine_status(estimated_ats_score, estimated_match_score)

    return {
        "analysis_id": analysis_record.get("id") or analysis_record.get("analysis_id"),
        "company_name": analysis_record.get("company_name", "Target Company"),
        "base_metrics": {
            "ats_score": base_ats_score,
            "match_percentage": base_match_score,
            "readiness_score": base_readiness_score,
            "readiness_status": base_status,
        },
        "estimated_metrics": {
            "ats_score": estimated_ats_score,
            "match_percentage": estimated_match_score,
            "readiness_score": estimated_readiness_score,
            "readiness_status": estimated_status,
        },
        "deltas": {
            "ats_delta": ats_delta,
            "match_delta": match_delta,
            "readiness_delta": readiness_delta,
        },
        "simulated_inputs": {
            "skills": simulated_skills,
            "projects": simulated_projects,
            "selected_suggestion_ids": list(selected_ids),
        },
        "factors_applied": factors_applied,
        "disclaimer": (
            "This simulation provides an automated heuristic estimate for planning purposes. "
            "Simulated changes are never saved to your resume, and these projections do not guarantee placement outcomes."
        ),
        "is_estimate": True
    }
