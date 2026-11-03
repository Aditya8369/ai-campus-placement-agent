"""
Multi-Company Batch Comparison & Placement Offer Likelihood Matrix

Orchestrates multi-company placement evaluations concurrently using background workers,
calculating comparative match metrics, 6-dimensional capability radar data, and hiring
offer probability rankings across campus recruiters.
"""

import uuid
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional
from pathlib import Path

import config
from utils.database import save_analysis, save_batch_comparison
from agents.coordinator import CoordinatorAgent

logger = logging.getLogger(__name__)

# Company Brand Palettes for Chart.js Radar Multi-Datasets
COMPANY_PALETTES: Dict[str, Dict[str, str]] = {
    "google": {
        "border": "rgba(66, 133, 244, 1)",
        "background": "rgba(66, 133, 244, 0.2)",
        "badge": "primary"
    },
    "microsoft": {
        "border": "rgba(0, 164, 239, 1)",
        "background": "rgba(0, 164, 239, 0.2)",
        "badge": "info"
    },
    "amazon": {
        "border": "rgba(245, 158, 11, 1)",
        "background": "rgba(245, 158, 11, 0.2)",
        "badge": "warning"
    },
    "tcs": {
        "border": "rgba(99, 102, 241, 1)",
        "background": "rgba(99, 102, 241, 0.2)",
        "badge": "indigo"
    },
    "infosys": {
        "border": "rgba(14, 165, 233, 1)",
        "background": "rgba(14, 165, 233, 0.2)",
        "badge": "info"
    },
    "accenture": {
        "border": "rgba(168, 85, 247, 1)",
        "background": "rgba(168, 85, 247, 0.2)",
        "badge": "purple"
    },
    "capgemini": {
        "border": "rgba(37, 99, 235, 1)",
        "background": "rgba(37, 99, 235, 0.2)",
        "badge": "primary"
    },
    "wipro": {
        "border": "rgba(20, 184, 166, 1)",
        "background": "rgba(20, 184, 166, 0.2)",
        "badge": "teal"
    },
    "default": {
        "border": "rgba(100, 116, 139, 1)",
        "background": "rgba(100, 116, 139, 0.2)",
        "badge": "secondary"
    }
}


def _get_company_style(company_name: str) -> Dict[str, str]:
    key = str(company_name or "").strip().lower()
    return COMPANY_PALETTES.get(key, COMPANY_PALETTES["default"])


def _calculate_offer_likelihood(
    company_name: str,
    match_percentage: int,
    ats_score: int,
    matched_skills: List[str],
    missing_skills: List[str]
) -> Dict[str, Any]:
    """
    Computes a quantitative Offer Probability Score (15% - 95%) and likelihood tier
    factoring company recruitment rigor, skill coverage ratio, and ATS compatibility.
    """
    comp_lower = company_name.strip().lower()
    tier_1_firms = {"google", "microsoft", "amazon", "apple", "meta", "netflix"}

    total_skills = max(1, len(matched_skills) + len(missing_skills))
    skill_coverage = len(matched_skills) / total_skills

    # Difficulty rigor scaling
    if comp_lower in tier_1_firms:
        tier_label = "Tier 1 (High Rigor Product)"
        difficulty_factor = 0.88
        target_ats = 80
        target_match = 75
    else:
        tier_label = "Tier 2 (Global Technology Services)"
        difficulty_factor = 1.05
        target_ats = 70
        target_match = 65

    # Calibrated probability calculation
    raw_probability = (
        (match_percentage * 0.45) +
        (ats_score * 0.35) +
        (skill_coverage * 100 * 0.20)
    ) * difficulty_factor

    probability = int(max(15, min(95, round(raw_probability))))

    if probability >= 75:
        likelihood_tier = "High Probability"
        tier_badge = "success"
        verdict = "Strong Offer Candidate"
    elif probability >= 55:
        likelihood_tier = "Moderate Probability"
        tier_badge = "warning"
        verdict = "Competitive Candidate"
    else:
        likelihood_tier = "Reach Opportunity"
        tier_badge = "danger"
        verdict = "Skill Gap Exists"

    # Preparation time estimate in weeks
    prep_weeks = max(1, min(12, int(len(missing_skills) * 1.2 + max(0, target_match - match_percentage) / 10)))

    return {
        "probability": probability,
        "tier": likelihood_tier,
        "tier_badge": tier_badge,
        "tier_label": tier_label,
        "verdict": verdict,
        "target_ats": target_ats,
        "target_match": target_match,
        "prep_weeks": prep_weeks
    }


def _calculate_radar_metrics(
    company_name: str,
    resume_analysis: Dict[str, Any],
    job_match: Dict[str, Any]
) -> List[int]:
    """
    Calculates 6-dimensional readiness scores (0-100) for the Chart.js Radar Chart:
    1. Coding & DSA Rigor
    2. System Design & Architecture
    3. Core Tech Stack Match
    4. Project Scope & Impact
    5. Behavioral & Cultural Fit
    6. ATS Resume Optimization
    """
    ats = int(resume_analysis.get("ats_score", 70))
    match_pct = int(job_match.get("match_percentage", 65))
    matched = [s.lower() for s in job_match.get("matched_skills", [])]
    strengths = [s.lower() for s in resume_analysis.get("strengths", [])]

    # 1. Coding & DSA Rigor
    dsa_keywords = {"python", "java", "c++", "c#", "algorithms", "data structures", "problem solving", "dsa", "leetcode"}
    dsa_matches = sum(1 for k in dsa_keywords if any(k in m for m in matched))
    coding_score = int(min(98, max(45, 55 + (dsa_matches * 10) + (match_pct * 0.2))))

    # 2. System Design & Architecture
    sys_keywords = {"system design", "distributed", "microservices", "sql", "nosql", "database", "docker", "cloud", "aws", "azure", "kubernetes", "rest"}
    sys_matches = sum(1 for k in sys_keywords if any(k in m for m in matched))
    comp_lower = company_name.strip().lower()
    if comp_lower in {"google", "microsoft", "amazon"}:
        sys_score = int(min(95, max(40, 45 + (sys_matches * 10))))
    else:
        sys_score = int(min(98, max(50, 60 + (sys_matches * 8))))

    # 3. Core Tech Stack Match
    tech_score = int(min(98, max(40, match_pct)))

    # 4. Project Scope & Impact
    proj_text = str(resume_analysis.get("project_feedback", "")).lower()
    impact_boost = 15 if any(w in proj_text for w in ["impressive", "scalable", "strong", "metrics", "good"]) else 5
    project_score = int(min(98, max(45, 55 + (ats * 0.3) + impact_boost)))

    # 5. Behavioral & Cultural Fit
    beh_boost = 12 if len(strengths) >= 2 else 5
    cultural_score = int(min(98, max(50, 60 + beh_boost + (ats * 0.2))))

    # 6. ATS Resume Optimization
    ats_score = int(min(99, max(40, ats)))

    return [coding_score, sys_score, tech_score, project_score, cultural_score, ats_score]


def run_batch_company_comparison(
    resume_text: str,
    companies: List[str],
    job_description: str = "",
    resume_filename: str = "resume.pdf",
    student_id: str = "default_student",
    coordinator_agent: Optional[CoordinatorAgent] = None,
    save_to_db: bool = True
) -> Dict[str, Any]:
    """
    Executes concurrent evaluations across the requested company list using a background
    thread pool, computes offer likelihood matrices, generates multi-dataset radar charts,
    and returns a structured comparison payload.
    """
    if coordinator_agent is None:
        coordinator_agent = CoordinatorAgent()

    # Deduplicate and normalize company names
    cleaned_companies: List[str] = []
    seen = set()
    for c in companies:
        name = str(c or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            cleaned_companies.append(name)

    if not cleaned_companies:
        cleaned_companies = ["Google", "Microsoft", "Amazon", "TCS"]

    # Limit to at most 8 companies
    cleaned_companies = cleaned_companies[:8]

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    comparisons: List[Dict[str, Any]] = []

    def evaluate_company(company: str) -> Dict[str, Any]:
        analysis_id = f"{batch_id}_{company.lower()}"
        try:
            results = coordinator_agent.analyze(
                resume_text=resume_text,
                job_description=job_description,
                company_name=company
            )
        except Exception as err:
            logger.error(f"Coordinator error analyzing {company}: {err}")
            results = {
                "resume_analysis": {"ats_score": 70, "summary": "Resume evaluated under fallback mode.", "strengths": ["Core CS fundamentals"]},
                "job_match": {"match_percentage": 65, "matched_skills": ["Python"], "missing_skills": ["System Design"]},
                "skill_gap": []
            }

        resume_analysis = results.get("resume_analysis", {})
        job_match = results.get("job_match", {})
        matched_skills = job_match.get("matched_skills", [])
        missing_skills = job_match.get("missing_skills", [])
        ats_score = resume_analysis.get("ats_score", 70)
        match_percentage = job_match.get("match_percentage", 65)

        offer_meta = _calculate_offer_likelihood(
            company_name=company,
            match_percentage=match_percentage,
            ats_score=ats_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills
        )

        radar_scores = _calculate_radar_metrics(
            company_name=company,
            resume_analysis=resume_analysis,
            job_match=job_match
        )

        style = _get_company_style(company)

        # Save individual analysis record to DB for seamless single-dashboard drill-down
        if save_to_db:
            try:
                save_analysis(
                    analysis_id=analysis_id,
                    resume_filename=resume_filename,
                    company_name=company,
                    job_description=job_description,
                    results_dict=results,
                    student_id=student_id
                )
            except Exception as save_err:
                logger.warning(f"Failed to save single analysis for batch {batch_id} - {company}: {save_err}")

        return {
            "company_name": company,
            "analysis_id": analysis_id,
            "ats_score": ats_score,
            "match_percentage": match_percentage,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "offer_probability": offer_meta["probability"],
            "likelihood_tier": offer_meta["tier"],
            "tier_badge": offer_meta["tier_badge"],
            "tier_label": offer_meta["tier_label"],
            "verdict": offer_meta["verdict"],
            "target_ats": offer_meta["target_ats"],
            "target_match": offer_meta["target_match"],
            "prep_weeks": offer_meta["prep_weeks"],
            "radar_scores": radar_scores,
            "style": style
        }

    # Execute company evaluations concurrently via thread pool
    max_workers = min(len(cleaned_companies), 4)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="BatchWorker") as executor:
        future_map = {executor.submit(evaluate_company, comp): comp for comp in cleaned_companies}
        for future in as_completed(future_map):
            try:
                comp_result = future.result()
                comparisons.append(comp_result)
            except Exception as exc:
                comp_name = future_map[future]
                logger.error(f"Error evaluating {comp_name} in batch: {exc}")

    # Sort comparisons by offer_probability descending (Rank #1 first)
    comparisons.sort(key=lambda x: x["offer_probability"], reverse=True)

    # Assign rank numbers
    for idx, c in enumerate(comparisons, start=1):
        c["rank"] = idx

    # Build Chart.js Radar Multi-Dataset Payload
    radar_labels = [
        "Coding & DSA Rigor",
        "System Design",
        "Tech Stack Fit",
        "Project Scope & Impact",
        "Cultural Alignment",
        "ATS Optimization"
    ]

    radar_datasets = []
    for c in comparisons:
        style = c["style"]
        radar_datasets.append({
            "label": c["company_name"],
            "data": c["radar_scores"],
            "borderColor": style["border"],
            "backgroundColor": style["background"],
            "pointBackgroundColor": style["border"],
            "pointHoverBorderColor": "#fff",
            "pointBorderColor": "#fff",
            "borderWidth": 2
        })

    # Comparative Strategic Insights
    best_offer = comparisons[0] if comparisons else None
    quickest_entry = min(comparisons, key=lambda x: x["prep_weeks"]) if comparisons else None

    # Count common missing skills across companies
    skill_counts: Dict[str, int] = {}
    for c in comparisons:
        for sk in c.get("missing_skills", []):
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

    top_missing_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    summary_insights = {
        "top_company": best_offer["company_name"] if best_offer else "General",
        "top_probability": best_offer["offer_probability"] if best_offer else 0,
        "fastest_path_company": quickest_entry["company_name"] if quickest_entry else "General",
        "fastest_prep_weeks": quickest_entry["prep_weeks"] if quickest_entry else 1,
        "common_missing_skills": [sk[0] for sk in top_missing_skills],
        "total_evaluated": len(comparisons)
    }

    batch_payload = {
        "batch_id": batch_id,
        "student_id": student_id,
        "resume_filename": resume_filename,
        "total_companies": len(comparisons),
        "companies_list": [c["company_name"] for c in comparisons],
        "comparisons": comparisons,
        "best_match": best_offer,
        "quickest_entry": quickest_entry,
        "summary_insights": summary_insights,
        "radar_data": {
            "labels": radar_labels,
            "datasets": radar_datasets
        }
    }

    if save_to_db:
        try:
            save_batch_comparison(
                batch_id=batch_id,
                student_id=student_id,
                resume_filename=resume_filename,
                companies_list=cleaned_companies,
                results_dict=batch_payload
            )
        except Exception as e:
            logger.error(f"Error persisting batch comparison {batch_id}: {e}")

    return batch_payload

