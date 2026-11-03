"""
Job Recommendation Agent - Matches student skill profiles, ATS scores, and target companies
against live curated campus drives and graduate openings to compute tailored fit metrics.
"""

import re
import logging
from typing import Dict, Any, List, Set, Optional, Tuple

logger = logging.getLogger(__name__)

# Common synonyms and sub-skill aliases for technical competencies
SKILL_ALIASES: Dict[str, Set[str]] = {
    "python": {"python", "python3", "py", "django", "flask", "fastapi"},
    "c++": {"c++", "cpp", "c/c++"},
    "c#": {"c#", "csharp", ".net", "dotnet"},
    "java": {"java", "spring", "spring boot", "springboot", "hibernate"},
    "javascript": {"javascript", "js", "es6", "vanilla js"},
    "typescript": {"typescript", "ts"},
    "golang": {"golang", "go"},
    "data structures": {"data structures", "dsa", "data structures & algorithms", "data structures and algorithms", "arrays", "trees", "graphs"},
    "algorithms": {"algorithms", "algorithm", "dsa", "dynamic programming", "time complexity"},
    "system design": {"system design", "system architecture", "scalable systems", "high level design", "low level design", "hld", "lld"},
    "object-oriented design": {"object-oriented design", "object oriented design", "ood", "oop", "object-oriented programming", "design patterns"},
    "sql": {"sql", "mysql", "postgresql", "postgres", "sqlite", "oracle sql", "plsql", "t-sql"},
    "dbms": {"dbms", "database management", "database systems", "rdbms", "sql"},
    "nosql": {"nosql", "mongodb", "cassandra", "dynamodb"},
    "cloud": {"cloud", "cloud computing", "cloud fundamentals", "cloud architecture", "aws", "azure", "gcp"},
    "aws": {"aws", "amazon web services", "s3", "ec2", "lambda"},
    "azure": {"azure", "microsoft azure"},
    "docker": {"docker", "containerization", "containers"},
    "kubernetes": {"kubernetes", "k8s"},
    "git": {"git", "github", "gitlab", "version control"},
    "rest apis": {"rest apis", "rest api", "rest", "restful", "api integration", "api design"},
    "microservices": {"microservices", "microservice architecture"},
    "linux": {"linux", "unix", "bash", "shell scripting", "ubuntu"},
    "computer networks": {"computer networks", "networking", "tcp/ip", "http", "https"},
    "react": {"react", "react.js", "reactjs", "next.js", "nextjs"},
    "redis": {"redis", "in-memory cache", "caching"},
    "kafka": {"kafka", "apache kafka", "message queue", "event streaming"},
    "machine learning": {"machine learning", "ml", "ai", "artificial intelligence", "deep learning", "nlp"},
    "communication": {"communication", "verbal communication", "written communication", "soft skills"}
}


class JobRecommendationAgent:
    """
    Evaluates candidate readiness against active campus recruitment drives,
    calculating skill match percentages, overlap ratios, and hiring probability.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _normalize_string(s: str) -> str:
        """Strips punctuation and downcases string for robust token matching."""
        return re.sub(r"[^\w\s\+\#]", " ", (s or "").lower()).strip()

    def _extract_candidate_skills(self, analysis_record: Dict[str, Any]) -> Set[str]:
        """
        Gathers candidate skills from analysis results, including matched skills,
        strengths, and standardized resume sections.
        """
        skills: Set[str] = set()

        if not analysis_record or not isinstance(analysis_record, dict):
            return skills

        results = analysis_record.get("results") or {}
        if not isinstance(results, dict):
            return skills

        # 1. Matched skills from Job Match block
        job_match = results.get("job_match") or {}
        if isinstance(job_match, dict):
            for s in job_match.get("matched_skills", []):
                if s and isinstance(s, str):
                    skills.add(s.strip().lower())

        # 2. Key strengths from Resume Analysis block
        resume_analysis = results.get("resume_analysis") or {}
        if isinstance(resume_analysis, dict):
            for s in resume_analysis.get("strengths", []):
                if s and isinstance(s, str):
                    clean_str = self._normalize_string(s)
                    # Extract skill mentions from strength sentences
                    for canon_name, aliases in SKILL_ALIASES.items():
                        if any(a in clean_str for a in aliases):
                            skills.add(canon_name)

        # 3. Direct resume text scan if available
        resume_text = analysis_record.get("resume_text") or ""
        if resume_text:
            text_lower = self._normalize_string(resume_text)
            for canon_name, aliases in SKILL_ALIASES.items():
                if any(re.search(r"\b" + re.escape(a) + r"\b", text_lower) for a in aliases):
                    skills.add(canon_name)

        return skills

    def _matches_skill(self, job_skill: str, candidate_skills: Set[str]) -> bool:
        """
        Determines whether a required job skill is possessed by the candidate,
        taking into account known technical synonyms and substrings.
        """
        job_norm = self._normalize_string(job_skill)
        if not job_norm:
            return False

        # Direct containment check
        for cand_s in candidate_skills:
            cand_norm = self._normalize_string(cand_s)
            if cand_norm == job_norm:
                return True
            if job_norm in cand_norm or cand_norm in job_norm:
                return True

        # Alias-based semantic check
        for canon_name, aliases in SKILL_ALIASES.items():
            is_job_in_alias = any(a in job_norm for a in aliases) or (canon_name in job_norm)
            if is_job_in_alias:
                # Check if candidate has any alias of this canonical skill
                for cand_s in candidate_skills:
                    c_norm = self._normalize_string(cand_s)
                    if any(a in c_norm for a in aliases) or (canon_name in c_norm):
                        return True

        return False

    def score_job_match(
        self,
        job: Dict[str, Any],
        candidate_skills: Set[str],
        ats_score: int = 70,
        target_company: str = ""
    ) -> Dict[str, Any]:
        """
        Scores an individual job against candidate skills and profile attributes.
        Returns match percentage, matched skills list, missing skills, and fit guidance.
        """
        req_skills: List[str] = job.get("required_skills", [])
        pref_skills: List[str] = job.get("preferred_skills", [])

        matched_req: List[str] = []
        missing_req: List[str] = []
        matched_pref: List[str] = []
        missing_pref: List[str] = []

        for s in req_skills:
            if self._matches_skill(s, candidate_skills):
                matched_req.append(s)
            else:
                missing_req.append(s)

        for s in pref_skills:
            if self._matches_skill(s, candidate_skills):
                matched_pref.append(s)
            else:
                missing_pref.append(s)

        # Compute overlap ratios
        total_req = max(1, len(req_skills))
        req_ratio = len(matched_req) / total_req

        total_pref = max(1, len(pref_skills))
        pref_ratio = len(matched_pref) / total_pref if pref_skills else 0.5

        # Check target company alignment bonus
        job_company = (job.get("company") or "").strip().lower()
        target_clean = (target_company or "").strip().lower()
        company_bonus = 6 if target_clean and (target_clean in job_company or job_company in target_clean) else 0

        # Weighted match formula
        # 60% Required Skills + 15% Preferred Skills + 20% ATS Profile + 5% Company Target
        ats_normalized = max(0, min(100, ats_score)) / 100.0
        raw_score = (req_ratio * 60.0) + (pref_ratio * 15.0) + (ats_normalized * 20.0) + company_bonus
        match_percentage = int(round(raw_score))

        # Clamp between 20% and 98%
        match_percentage = max(20, min(98, match_percentage))

        # Determine Tier / Badge & Fit Assessment
        if match_percentage >= 82:
            tier_badge = "success"
            tier_label = "Top Match"
            fit_summary = f"High alignment! You meet {len(matched_req)} of {len(req_skills)} core technical requirements for {job.get('company')}."
        elif match_percentage >= 68:
            tier_badge = "primary"
            tier_label = "Strong Fit"
            fit_summary = f"Strong fit for this opening. Closing gaps in {', '.join(missing_req[:2]) if missing_req else 'preferred skills'} will increase shortlist probability."
        elif match_percentage >= 50:
            tier_badge = "info"
            tier_label = "Moderate Match"
            fit_summary = f"Good baseline eligibility. Recommended to practice {', '.join(missing_req[:2]) if missing_req else 'core topics'} before applying."
        else:
            tier_badge = "secondary"
            tier_label = "Stretch Opportunity"
            fit_summary = f"Significant skill gap detected. Review roadmap tasks for {', '.join(missing_req[:3]) if missing_req else 'key topics'}."

        return {
            **job,
            "match_percentage": match_percentage,
            "tier_badge": tier_badge,
            "tier_label": tier_label,
            "matched_skills": matched_req + matched_pref,
            "missing_skills": missing_req + missing_pref,
            "matched_required_count": len(matched_req),
            "total_required_count": len(req_skills),
            "fit_summary": fit_summary,
            "is_target_company": (target_clean != "" and (target_clean in job_company or job_company in target_clean))
        }

    def recommend_jobs(
        self,
        analysis_record: Dict[str, Any],
        jobs: List[Dict[str, Any]],
        location: str = "all",
        role_type: str = "all",
        min_match: int = 0,
        search_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Scores and ranks all active jobs for the given candidate analysis.
        Filters by location, role_type, min_match threshold, and optional search query.
        """
        if not jobs:
            return []

        # Extract candidate attributes
        candidate_skills = self._extract_candidate_skills(analysis_record)
        results = (analysis_record.get("results") or {}) if isinstance(analysis_record, dict) else {}
        resume_analysis = results.get("resume_analysis") or {}
        ats_score = int(resume_analysis.get("ats_score", 70))
        target_company = str(analysis_record.get("company_name", "") if isinstance(analysis_record, dict) else "")

        scored_jobs: List[Dict[str, Any]] = []
        for job in jobs:
            scored = self.score_job_match(
                job=job,
                candidate_skills=candidate_skills,
                ats_score=ats_score,
                target_company=target_company
            )
            scored_jobs.append(scored)

        # Sort primarily by match_percentage descending, then target company match
        scored_jobs.sort(
            key=lambda j: (j.get("is_target_company", False), j.get("match_percentage", 0)),
            reverse=True
        )

        # Apply minimum match threshold
        if min_match > 0:
            scored_jobs = [j for j in scored_jobs if j.get("match_percentage", 0) >= min_match]

        # Apply location filter
        if location and location.strip().lower() not in ("all", "any"):
            loc_clean = location.strip().lower()
            scored_jobs = [
                j for j in scored_jobs
                if loc_clean in (j.get("location") or "").lower()
            ]

        # Apply role type filter
        if role_type and role_type.strip().lower() not in ("all", "any"):
            rt_clean = role_type.strip().lower()
            scored_jobs = [
                j for j in scored_jobs
                if rt_clean in (j.get("role_type") or "").lower()
            ]

        # Apply text search query
        if search_query and search_query.strip():
            q = search_query.strip().lower()
            def matches(j: Dict[str, Any]) -> bool:
                if q in (j.get("title") or "").lower():
                    return True
                if q in (j.get("company") or "").lower():
                    return True
                if q in (j.get("description") or "").lower():
                    return True
                all_s = [s.lower() for s in j.get("required_skills", []) + j.get("preferred_skills", [])]
                return any(q in s for s in all_s)

            scored_jobs = [j for j in scored_jobs if matches(j)]

        return scored_jobs

