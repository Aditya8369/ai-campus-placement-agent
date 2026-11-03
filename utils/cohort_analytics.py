"""
Cohort Analytics Service - Benchmarks student candidate performance against peer cohorts,
calculates percentile rankings, tracks department masteries, and manages the anonymized leaderboard.
"""

import hashlib
import logging
from typing import Dict, Any, List, Optional, Tuple

from utils.database import (
    get_cohort_benchmarks,
    get_cohort_stats,
    record_or_update_cohort_benchmark,
    get_cohort_benchmark_by_analysis_id,
    get_analysis,
)

logger = logging.getLogger(__name__)

# Deterministic handle word lists
HANDLE_PREFIXES = [
    "Algo", "Byte", "Code", "Data", "Dev", "Kernel", "Logic", "Pixel",
    "Prompt", "Quantum", "Script", "Stack", "Syntax", "Tensor", "Vector",
    "Binary", "Cyber", "Matrix", "Cloud", "Neural"
]

HANDLE_SUFFIXES = [
    "Ninja", "Surgeon", "Crafter", "Voyager", "Scholar", "Monk", "Knight",
    "Wizard", "Whiz", "Falcon", "Coder", "Guru", "Sage", "Pioneer",
    "Architect", "Master", "Pilot", "Engineer"
]

DEPARTMENT_MAP = {
    "cs": "Computer Science",
    "cse": "Computer Science",
    "computer science": "Computer Science",
    "it": "Information Technology",
    "information technology": "Information Technology",
    "ece": "Electronics & Comm",
    "electronics": "Electronics & Comm",
    "electronics & comm": "Electronics & Comm",
    "electronics and communication": "Electronics & Comm",
    "ai": "Data Science & AI",
    "ds": "Data Science & AI",
    "data science": "Data Science & AI",
    "data science & ai": "Data Science & AI",
    "ee": "Electrical Engineering",
    "eee": "Electrical Engineering",
    "electrical": "Electrical Engineering",
    "me": "Mechanical Engineering",
    "mech": "Mechanical Engineering",
    "mechanical": "Mechanical Engineering",
}

DEPARTMENT_SHORT_NAMES = {
    "Computer Science": "CSE",
    "Information Technology": "IT",
    "Electronics & Comm": "ECE",
    "Data Science & AI": "AI/DS",
    "Electrical Engineering": "EE",
    "Mechanical Engineering": "ME",
    "Civil Engineering": "CE",
}


class CohortAnalyticsService:
    """
    Orchestrates peer benchmarking, percentile rank computation, and leaderboard delivery.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def generate_anonymized_handle(identifier: str) -> str:
        """
        Generates a deterministic yet privacy-preserving student handle based on an ID hash.
        Example: 'AlgoPioneer_42' or 'SyntaxNinja_88'
        """
        if not identifier:
            identifier = "student"
        
        digest = hashlib.md5(identifier.encode("utf-8")).hexdigest()
        p_idx = int(digest[0:4], 16) % len(HANDLE_PREFIXES)
        s_idx = int(digest[4:8], 16) % len(HANDLE_SUFFIXES)
        num = (int(digest[8:12], 16) % 90) + 10  # 10 to 99

        return f"{HANDLE_PREFIXES[p_idx]}{HANDLE_SUFFIXES[s_idx]}_{num}"

    @staticmethod
    def normalize_department(dept: Optional[str]) -> str:
        """Standardizes user-provided or inferred branch string."""
        if not dept or not dept.strip():
            return "Computer Science"
        clean = dept.strip().lower()
        return DEPARTMENT_MAP.get(clean, "Computer Science")

    @staticmethod
    def calculate_composite_score(ats_score: int, job_match_score: int) -> float:
        """
        Calculates weighted composite evaluation score:
        45% ATS Compatibility + 55% Job Description Match
        """
        ats_clamped = max(0, min(100, int(ats_score)))
        match_clamped = max(0, min(100, int(job_match_score)))
        return round((ats_clamped * 0.45) + (match_clamped * 0.55), 1)

    @staticmethod
    def determine_tier(overall_score: float) -> Dict[str, str]:
        """
        Categorizes student performance into competitive achievement tiers.
        """
        if overall_score >= 88.0:
            return {
                "tier": "Platinum",
                "badge_class": "platinum",
                "badge_css": "bg-primary text-white",
                "icon": "fa-crown",
                "label": "Platinum Achiever"
            }
        elif overall_score >= 78.0:
            return {
                "tier": "Gold",
                "badge_class": "gold",
                "badge_css": "bg-warning text-dark",
                "icon": "fa-medal",
                "label": "Gold Performer"
            }
        elif overall_score >= 65.0:
            return {
                "tier": "Silver",
                "badge_class": "silver",
                "badge_css": "bg-secondary text-white",
                "icon": "fa-award",
                "label": "Silver Candidate"
            }
        else:
            return {
                "tier": "Bronze",
                "badge_class": "bronze",
                "badge_css": "bg-dark-subtle text-dark",
                "icon": "fa-shield-halved",
                "label": "Bronze Challenger"
            }

    def get_or_register_candidate(
        self,
        analysis_id: str,
        analysis_record: Optional[Dict[str, Any]] = None,
        department: Optional[str] = None,
        grad_year: int = 2026
    ) -> Dict[str, Any]:
        """
        Ensures a candidate's analysis record is reflected in cohort_benchmarks.
        Returns the benchmark dictionary.
        """
        existing = get_cohort_benchmark_by_analysis_id(analysis_id)
        if existing:
            return existing

        # Load parent analysis if omitted
        record = analysis_record or get_analysis(analysis_id)
        if not record:
            # Fallback mock benchmark if analysis not found
            anon_handle = self.generate_anonymized_handle(analysis_id)
            dept = self.normalize_department(department)
            overall = self.calculate_composite_score(75, 70)
            tier_info = self.determine_tier(overall)
            b_id = record_or_update_cohort_benchmark(
                analysis_id=analysis_id,
                student_handle=anon_handle,
                department=dept,
                grad_year=grad_year,
                ats_score=75,
                job_match_score=70,
                overall_score=overall,
                target_company="General",
                skills_count=5,
                tier=tier_info["tier"]
            )
            return {
                "id": b_id,
                "analysis_id": analysis_id,
                "student_handle": anon_handle,
                "department": dept,
                "grad_year": grad_year,
                "ats_score": 75,
                "job_match_score": 70,
                "overall_score": overall,
                "target_company": "General",
                "skills_count": 5,
                "tier": tier_info["tier"]
            }

        results = record.get("results") or {}
        resume_analysis = results.get("resume_analysis") or {}
        job_match = results.get("job_match") or {}

        ats_score = int(resume_analysis.get("ats_score", 70))
        match_score = int(job_match.get("match_percentage", 65))
        matched_skills = job_match.get("matched_skills") or []
        skills_count = len(matched_skills) if isinstance(matched_skills, list) else 0
        company = record.get("company_name", "General")
        student_id = record.get("student_id") or analysis_id

        dept = self.normalize_department(department)
        anon_handle = self.generate_anonymized_handle(student_id)
        overall = self.calculate_composite_score(ats_score, match_score)
        tier_info = self.determine_tier(overall)

        b_id = record_or_update_cohort_benchmark(
            analysis_id=analysis_id,
            student_handle=anon_handle,
            department=dept,
            grad_year=grad_year,
            ats_score=ats_score,
            job_match_score=match_score,
            overall_score=overall,
            target_company=company,
            skills_count=skills_count,
            tier=tier_info["tier"]
        )

        return {
            "id": b_id,
            "analysis_id": analysis_id,
            "student_handle": anon_handle,
            "department": dept,
            "grad_year": grad_year,
            "ats_score": ats_score,
            "job_match_score": match_score,
            "overall_score": overall,
            "target_company": company,
            "skills_count": skills_count,
            "tier": tier_info["tier"]
        }

    def calculate_percentile_rank(
        self,
        analysis_id: str,
        department: Optional[str] = None,
        grad_year: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculates candidate's competitive percentile rank, standing, and delta
        relative to the university cohort.
        """
        # Ensure candidate is registered
        cand_bench = self.get_or_register_candidate(
            analysis_id=analysis_id,
            department=department,
            grad_year=grad_year or 2026
        )

        dept = cand_bench.get("department", "Computer Science")
        year = cand_bench.get("grad_year", 2026)
        cand_overall = float(cand_bench.get("overall_score", 70.0))
        cand_ats = int(cand_bench.get("ats_score", 70))
        cand_match = int(cand_bench.get("job_match_score", 65))

        # Fetch peers in same department and year
        peers = get_cohort_benchmarks(department=dept, grad_year=year, limit=200)
        if not peers:
            # Fallback to all peers
            peers = get_cohort_benchmarks(limit=200)

        total_peers = len(peers)
        if total_peers == 0:
            total_peers = 1

        # Determine rank (1-indexed)
        rank = 1
        for p in peers:
            if float(p.get("overall_score", 0)) > cand_overall:
                rank += 1

        # Percentile rank: % of peers candidate scored higher than
        peers_below = max(0, total_peers - rank)
        percentile = max(1, min(99, int(round((peers_below / total_peers) * 100))))
        top_percent = max(1, min(99, 100 - percentile))

        # If candidate is rank #1
        if rank == 1:
            top_percent = 1
            percentile = 99

        # Fetch cohort averages
        stats = get_cohort_stats(department=dept, grad_year=year)
        avg_ats = stats.get("avg_ats", 70.0)
        avg_match = stats.get("avg_match", 65.0)
        avg_overall = stats.get("avg_overall", 67.5)

        ats_delta = round(cand_ats - avg_ats, 1)
        match_delta = round(cand_match - avg_match, 1)
        overall_delta = round(cand_overall - avg_overall, 1)

        tier_info = self.determine_tier(cand_overall)
        dept_short = DEPARTMENT_SHORT_NAMES.get(dept, "CSE")

        percentile_badge = f"Top {top_percent}% in {dept_short}"

        return {
            "analysis_id": analysis_id,
            "student_handle": cand_bench.get("student_handle", "Student"),
            "rank": rank,
            "total_peers": total_peers,
            "percentile": percentile,
            "top_percent": top_percent,
            "percentile_badge": percentile_badge,
            "department": dept,
            "department_short": dept_short,
            "grad_year": year,
            "candidate_ats": cand_ats,
            "candidate_match": cand_match,
            "candidate_overall": cand_overall,
            "tier": tier_info["tier"],
            "tier_badge_class": tier_info["badge_class"],
            "tier_icon": tier_info["icon"],
            "tier_label": tier_info["label"],
            "cohort_avg_ats": avg_ats,
            "cohort_avg_match": avg_match,
            "cohort_avg_overall": avg_overall,
            "ats_delta": ats_delta,
            "match_delta": match_delta,
            "overall_delta": overall_delta
        }

    def get_leaderboard_view(
        self,
        department: Optional[str] = None,
        grad_year: Optional[int] = None,
        search: Optional[str] = None,
        current_analysis_id: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Prepares the full leaderboard data model including podium (ranks 1-3),
        summary stats, and candidate highlight.
        """
        dept_norm = self.normalize_department(department) if department and department.lower() not in ("all", "any") else None
        year_filter = int(grad_year) if grad_year and int(grad_year) > 0 else None

        benchmarks = get_cohort_benchmarks(
            department=dept_norm,
            grad_year=year_filter,
            search=search,
            limit=limit
        )

        stats = get_cohort_stats(
            department=dept_norm,
            grad_year=year_filter
        )

        # Enhance each benchmark record with tier badge styling & current candidate flag
        enhanced = []
        for idx, b in enumerate(benchmarks):
            rec = dict(b)
            rec["rank"] = idx + 1
            tier_info = self.determine_tier(float(rec.get("overall_score", 0)))
            rec["tier_badge_class"] = tier_info["badge_class"]
            rec["tier_icon"] = tier_info["icon"]
            rec["is_current_user"] = (current_analysis_id is not None and rec.get("analysis_id") == current_analysis_id)
            enhanced.append(rec)

        # Podium: top 3
        podium = enhanced[:3] if len(enhanced) >= 3 else enhanced

        return {
            "filters": {
                "department": department or "all",
                "grad_year": grad_year or "all",
                "search": search or ""
            },
            "stats": stats,
            "total_ranked": len(enhanced),
            "podium": podium,
            "leaderboard": enhanced,
            "current_analysis_id": current_analysis_id
        }

