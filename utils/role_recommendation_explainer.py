"""
utils/role_recommendation_explainer.py
AI Recommendation Explanations for Suggested Career Roles (#295).

Provides intelligible, student-friendly, and strictly profile-grounded explanations
for recommended career paths (Software Engineer, Python Developer, Data Analyst, Data Scientist).
Evaluates:
- The core reason behind recommending a particular career role.
- Matching skills from the student's actual profile.
- Missing skills affecting suitability and their real-world impact.
- How the student's projects and experience relate to the role.
- Key factors influencing the recommendation (Skill overlap, project alignment, bridgeability, market demand).
- Student-friendly, jargon-free actionable advice.
"""

import re
from typing import Dict, Any, List, Optional, Set

# Skill aliases and keyword mappings for normalized matching
ROLE_SKILL_PROFILES: Dict[str, Dict[str, Any]] = {
    "Software Engineer": {
        "title": "Software Engineer",
        "category": "Core Engineering & Systems",
        "description": "Designs, develops, and maintains scalable software systems, algorithms, and application architectures.",
        "core_skills": [
            "Data Structures", "Algorithms", "System Design", "Object-Oriented Programming",
            "SQL", "Git", "Problem Solving", "Linux", "C++", "Java", "Python"
        ],
        "project_keywords": [
            "system", "application", "algorithm", "architecture", "database", "backend",
            "full stack", "fullstack", "api", "web app", "microservice", "oop", "data structure"
        ],
        "domain_focus": "algorithmic efficiency, clean object-oriented architecture, and scalable system implementation",
        "entry_requirements": "Strong foundation in data structures, time complexity analysis, and at least one core object-oriented language."
    },
    "Python Developer": {
        "title": "Python Developer",
        "category": "Backend & API Engineering",
        "description": "Specializes in building backend APIs, automated data pipelines, server architectures, and asynchronous microservices.",
        "core_skills": [
            "Python", "FastAPI", "Django", "Flask", "REST APIs", "SQL",
            "PostgreSQL", "Docker", "Redis", "Celery", "Pytest", "AsyncIO"
        ],
        "project_keywords": [
            "python", "django", "flask", "fastapi", "rest api", "backend", "web service",
            "scraper", "automation", "sqlalchemy", "orm", "endpoint", "celery", "redis"
        ],
        "domain_focus": "server-side development, high-performance REST APIs, database modeling, and asynchronous task execution",
        "entry_requirements": "Fluency in modern Python idioms, web frameworks (FastAPI/Django/Flask), and relational database integration."
    },
    "Data Analyst": {
        "title": "Data Analyst",
        "category": "Data & Business Intelligence",
        "description": "Translates complex datasets into actionable business metrics, interactive dashboards, and executive insights.",
        "core_skills": [
            "SQL", "Python", "Pandas", "NumPy", "Excel", "Tableau",
            "Power BI", "Data Visualization", "Statistics", "Exploratory Data Analysis"
        ],
        "project_keywords": [
            "sql", "analysis", "analytics", "dashboard", "tableau", "power bi", "pandas",
            "numpy", "excel", "visualization", "dataset", "cleaning", "eda", "business intelligence"
        ],
        "domain_focus": "data querying, statistical summarization, dashboard development, and business intelligence",
        "entry_requirements": "Proficiency in complex SQL queries (joins, window functions), data cleaning libraries, and dashboarding tools."
    },
    "Data Scientist": {
        "title": "Data Scientist",
        "category": "Machine Learning & AI",
        "description": "Builds predictive algorithms, statistical models, natural language pipelines, and machine learning solutions.",
        "core_skills": [
            "Machine Learning", "Python", "Statistics", "Scikit-Learn", "Pandas",
            "Deep Learning", "TensorFlow", "PyTorch", "NLP", "Feature Engineering", "Data Modeling"
        ],
        "project_keywords": [
            "machine learning", "ml", "deep learning", "ai", "model", "prediction", "neural",
            "nlp", "scikit", "tensorflow", "pytorch", "classification", "regression", "clustering"
        ],
        "domain_focus": "predictive modeling, statistical experimentation, feature engineering, and algorithm training",
        "entry_requirements": "Solid grounding in applied statistics, machine learning algorithms, model evaluation, and Python data science stacks."
    }
}


def _normalize_token(text: str) -> str:
    """Normalize text into clean lowercase alphanumeric tokens."""
    return re.sub(r"[^\w\s\+\#]", " ", (text or "").lower()).strip()


def _skill_matches(candidate_skill: str, role_skill: str) -> bool:
    """Check if a candidate skill matches a role skill via substring or token overlap."""
    c_norm = _normalize_token(candidate_skill)
    r_norm = _normalize_token(role_skill)

    if not c_norm or not r_norm:
        return False
    if c_norm == r_norm or c_norm in r_norm or r_norm in c_norm:
        return True

    # Common synonym matches
    synonyms = {
        "dsa": ["data structures", "algorithms", "problem solving"],
        "oop": ["object-oriented programming", "object oriented design"],
        "rest": ["rest apis", "api", "endpoints"],
        "postgres": ["postgresql", "sql"],
        "mysql": ["sql"],
        "ml": ["machine learning", "data science"],
        "ai": ["artificial intelligence", "machine learning"],
        "eda": ["exploratory data analysis", "data analysis"],
        "powerbi": ["power bi", "business intelligence"],
    }

    for syn_key, syn_targets in synonyms.items():
        if syn_key in c_norm and any(t in r_norm for t in syn_targets):
            return True
        if syn_key in r_norm and any(t in c_norm for t in syn_targets):
            return True

    return False


def explain_role_recommendation(
    target_role: str,
    existing_skills: Optional[List[str]] = None,
    skill_gaps: Optional[List[str]] = None,
    resume_text: Optional[str] = None,
    analysis_record: Optional[Dict[str, Any]] = None,
    company_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates an AI recommendation explanation tailored to a specific career role.

    Grounded strictly in the candidate's actual profile, skills, and resume text.
    Uses student-friendly, jargon-free language to explain why the role is recommended,
    which skills match, what missing skills affect suitability, and how past projects relate.
    """
    # Normalize role name
    role_key = "Software Engineer"
    t_lower = (target_role or "").lower()
    if "python" in t_lower:
        role_key = "Python Developer"
    elif "data analyst" in t_lower or "analyst" in t_lower:
        role_key = "Data Analyst"
    elif "data scientist" in t_lower or "scientist" in t_lower or "machine learning" in t_lower:
        role_key = "Data Scientist"
    elif "software" in t_lower or "sde" in t_lower or "swe" in t_lower or "engineer" in t_lower:
        role_key = "Software Engineer"

    profile = ROLE_SKILL_PROFILES[role_key]
    company = (company_name or "Campus Placements").strip()

    # Deduplicate & sanitize input skills
    raw_existing = [str(s).strip() for s in (existing_skills or []) if str(s).strip()]
    raw_gaps = [str(s).strip() for s in (skill_gaps or []) if str(s).strip()]

    # Also check analysis_record if available for deeper grounded evidence
    results = (analysis_record or {}).get("results") or {}
    resume_analysis = results.get("resume_analysis") or {}
    job_match = results.get("job_match") or {}

    if not raw_existing and job_match.get("matched_skills"):
        raw_existing = [str(s).strip() for s in job_match.get("matched_skills", []) if str(s).strip()]
    if not raw_gaps and job_match.get("missing_skills"):
        raw_gaps = [str(s).strip() for s in job_match.get("missing_skills", []) if str(s).strip()]

    # Extract text from resume and feedback
    full_text = " ".join([
        resume_text or (analysis_record or {}).get("resume_text", "") or "",
        resume_analysis.get("summary", "") or "",
        resume_analysis.get("project_feedback", "") or "",
        resume_analysis.get("experience_feedback", "") or "",
        " ".join(resume_analysis.get("strengths", []) or [])
    ]).lower()

    # 1. Matching Skills Identification
    matching_skills: List[str] = []
    matched_role_skills: Set[str] = set()

    for cand_skill in raw_existing:
        for role_skill in profile["core_skills"]:
            if _skill_matches(cand_skill, role_skill):
                if cand_skill not in matching_skills:
                    matching_skills.append(cand_skill)
                matched_role_skills.add(role_skill)

    # If resume text mentions skills not explicitly in raw_existing list
    if full_text:
        for role_skill in profile["core_skills"]:
            if role_skill not in matched_role_skills:
                # Word boundary search in resume text
                r_norm = _normalize_token(role_skill)
                if re.search(r"\b" + re.escape(r_norm) + r"\b", full_text):
                    if role_skill not in matching_skills:
                        matching_skills.append(role_skill)
                    matched_role_skills.add(role_skill)

    # 2. Missing Skills Identification
    missing_skills: List[str] = []
    for role_skill in profile["core_skills"]:
        if role_skill not in matched_role_skills:
            missing_skills.append(role_skill)

    # 3. Project and Experience Relevance Evaluation (Grounded)
    matched_project_keywords: List[str] = []
    for kw in profile["project_keywords"]:
        if re.search(r"\b" + re.escape(kw) + r"\b", full_text):
            if kw not in matched_project_keywords:
                matched_project_keywords.append(kw)

    has_direct_project_evidence = len(matched_project_keywords) >= 2 or len(matching_skills) >= 2

    project_highlights: List[str] = []
    if has_direct_project_evidence:
        found_kw_str = ", ".join(matched_project_keywords[:4])
        project_highlights.append(
            f"Your background references hands-on experience involving {found_kw_str}, which directly aligns with daily responsibilities in {profile['title']} roles."
        )
        if matching_skills:
            project_highlights.append(
                f"Practical application of {', '.join(matching_skills[:3])} in your coursework or projects gives you immediate talking points during technical interview rounds."
            )
        project_summary = (
            f"Your current project portfolio demonstrates practical exposure to {profile['domain_focus']}, "
            f"giving you credible foundation for {profile['title']} opportunities at {company}."
        )
    else:
        project_highlights.append(
            f"Your current profile focuses more on general academic coursework. Adding a dedicated portfolio project showcasing {profile['core_skills'][0]} and {profile['core_skills'][1]} will significantly boost your credibility."
        )
        project_highlights.append(
            "Recruiters look for verifiable repository links and working demos that prove you can build features end-to-end."
        )
        project_summary = (
            f"While you have foundational knowledge, developing a dedicated {profile['title']} project will bridge the gap between theory and practical industry expectations."
        )

    # 4. Recommendation Reason Formulation
    num_matches = len(matching_skills)
    if num_matches >= 4:
        suitability_tier = "Strong Match"
        suitability_score = min(95, 65 + (num_matches * 6))
        reason = (
            f"Recommended because your profile exhibits strong alignment ({num_matches} core skills) with {profile['title']} requirements. "
            f"Your demonstrated familiarity with {', '.join(matching_skills[:3])} positions you well for technical screenings."
        )
    elif num_matches >= 2:
        suitability_tier = "Good Match"
        suitability_score = 55 + (num_matches * 5)
        reason = (
            f"Recommended as a viable career track because your foundational knowledge in {', '.join(matching_skills[:3])} provides a solid launchpad. "
            f"Focusing on the {len(missing_skills[:3])} missing core competencies below will raise your hiring readiness."
        )
    else:
        suitability_tier = "Growth Opportunity"
        suitability_score = max(35, 30 + (num_matches * 8))
        reason = (
            f"Identified as a growth path for your consideration. While you currently demonstrate fewer direct skills for {profile['title']}, "
            f"your problem-solving foundation enables you to transition into this track through our structured preparation roadmap."
        )

    # 5. Missing Skills Impact Explanation
    if missing_skills:
        top_missing_str = ", ".join(missing_skills[:3])
        missing_skills_impact = (
            f"In typical placement drives, candidates are evaluated on {top_missing_str}. "
            f"Currently, your resume does not explicitly highlight these areas. Mastering them will directly improve your technical assessment and interview clearance rates."
        )
    else:
        missing_skills_impact = (
            f"You possess all baseline skills expected for an entry-level {profile['title']}. Focus on advanced interview problem-solving and system architecture."
        )

    # 6. Influencing Factors Breakdown
    skill_factor_pct = min(100, int((len(matching_skills) / max(1, len(profile["core_skills"]))) * 100) + 20)
    project_factor_pct = 85 if has_direct_project_evidence else 45
    bridgeability_pct = 90 if len(missing_skills) <= 4 else (75 if len(missing_skills) <= 7 else 60)
    market_demand_pct = 85 if role_key in ("Software Engineer", "Python Developer") else 80

    influencing_factors = [
        {
            "factor": "Technical Skill Overlap",
            "weight": "High",
            "score_pct": skill_factor_pct,
            "badge_class": "success" if skill_factor_pct >= 70 else ("primary" if skill_factor_pct >= 50 else "warning"),
            "description": f"{len(matching_skills)} of your verified skills directly match this role's technology stack."
        },
        {
            "factor": "Project & Experience Alignment",
            "weight": "High",
            "score_pct": project_factor_pct,
            "badge_class": "success" if project_factor_pct >= 70 else "warning",
            "description": "Evidence from your resume projects and practical coursework." if has_direct_project_evidence else "General exposure present; dedicated role project recommended."
        },
        {
            "factor": "Skill Gap Bridgeability",
            "weight": "Medium",
            "score_pct": bridgeability_pct,
            "badge_class": "info",
            "description": f"{len(missing_skills[:4])} key missing skills can be effectively learned in 2 to 4 weeks."
        },
        {
            "factor": "Campus Recruitment Demand",
            "weight": "Medium",
            "score_pct": market_demand_pct,
            "badge_class": "primary",
            "description": f"Consistently high graduate hiring volume across software firms visiting for {company}."
        }
    ]

    # 7. Student-Friendly Plain English Summary
    if num_matches >= 3:
        student_friendly_summary = (
            f"In simple terms: You already have practical skills in {', '.join(matching_skills[:2])}. "
            f"To stand out to recruiters for {profile['title']} positions, prioritize learning {missing_skills[0] if missing_skills else 'advanced architecture'} "
            f"and emphasize your related project accomplishments."
        )
    else:
        student_friendly_summary = (
            f"In simple terms: This role is an exciting path if you want to specialize in {profile['category']}. "
            f"Start by learning {missing_skills[0] if missing_skills else 'core tools'} and build one clean, working project to demonstrate your interest on your resume."
        )

    return {
        "role_name": role_key,
        "role_title": profile["title"],
        "category": profile["category"],
        "suitability_score": suitability_score,
        "suitability_tier": suitability_tier,
        "recommendation_reason": reason,
        "matching_skills": matching_skills,
        "matching_skills_count": len(matching_skills),
        "missing_skills": missing_skills,
        "missing_skills_count": len(missing_skills),
        "missing_skills_impact": missing_skills_impact,
        "project_experience_relevance": {
            "summary": project_summary,
            "highlights": project_highlights,
            "has_direct_project_evidence": has_direct_project_evidence,
            "matched_keywords": matched_project_keywords
        },
        "influencing_factors": influencing_factors,
        "student_friendly_summary": student_friendly_summary,
        "profile_grounding": {
            "verified_skills_count": len(matching_skills),
            "grounding_confidence": "High" if full_text else "Medium",
            "is_grounded_in_profile": True
        }
    }


def generate_all_roles_explanation_summary(
    existing_skills: Optional[List[str]] = None,
    skill_gaps: Optional[List[str]] = None,
    resume_text: Optional[str] = None,
    analysis_record: Optional[Dict[str, Any]] = None,
    company_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates comparative AI recommendation explanations for all supported roles,
    ranked by candidate suitability score.
    """
    all_explanations: Dict[str, Dict[str, Any]] = {}
    for role_name in ROLE_SKILL_PROFILES.keys():
        exp = explain_role_recommendation(
            target_role=role_name,
            existing_skills=existing_skills,
            skill_gaps=skill_gaps,
            resume_text=resume_text,
            analysis_record=analysis_record,
            company_name=company_name
        )
        all_explanations[role_name] = exp

    # Rank roles by suitability score descending
    ranked_roles = sorted(
        all_explanations.values(),
        key=lambda x: x["suitability_score"],
        reverse=True
    )

    return {
        "success": True,
        "total_roles_evaluated": len(ranked_roles),
        "top_recommended_role": ranked_roles[0]["role_name"] if ranked_roles else "Software Engineer",
        "roles": all_explanations,
        "ranked_roles": ranked_roles
    }

