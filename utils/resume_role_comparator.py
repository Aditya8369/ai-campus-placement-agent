"""
Multi-Role Resume Analysis & Capability Comparison Service (#256)
==================================================================
Empowers students to evaluate a single resume simultaneously across multiple distinct
technical job roles (e.g., Software Engineer, Data Engineer, Machine Learning Engineer,
DevOps / Cloud Architect, Full Stack Developer, Cybersecurity Analyst).

Key Capabilities:
1. Standard Technical Roles Taxonomy:
   - Pre-configured archetypes with essential skill stacks, typical frameworks, and evaluation rubrics.
2. Multi-Role Comparative Assessment:
   - Calculates role-specific match percentage and score distributions.
   - Highlights role-specific missing skills for targeted upskilling.
   - Computes common / transferable skills shared across all selected career tracks.
   - Generates tailored role-specific improvement suggestions (projects, certifications, keywords).
3. Resilient Error Handling & Incomplete Data Fallbacks:
   - Gracefully handles empty resumes, unselected roles, unknown roles, or partial analyses.
4. Export & Persistence:
   - Stores multi-role comparison results in the database for candidate dashboards.
"""

import logging
import json
import uuid
import re
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Standard industry job role archetypes with required competency clusters
TECHNICAL_ROLE_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "software_engineer": {
        "title": "Software Engineer (Backend / General)",
        "category": "Core Engineering",
        "primary_skills": ["python", "java", "c++", "go", "data structures", "algorithms", "system design", "git", "sql", "rest api", "unit testing"],
        "secondary_skills": ["docker", "microservices", "redis", "concurrency", "ci/cd", "linux"],
        "critical_keywords": ["algorithms", "scalability", "latency", "oop", "clean code"]
    },
    "frontend_engineer": {
        "title": "Frontend / Web Developer",
        "category": "Core Engineering",
        "primary_skills": ["javascript", "typescript", "react", "html", "css", "vue", "angular", "responsive design", "webpack", "next.js", "tailwind"],
        "secondary_skills": ["state management", "redux", "web vitals", "accessibility", "jest", "cypress", "graphql"],
        "critical_keywords": ["ui/ux", "dom", "component architecture", "single page application", "lighthouse"]
    },
    "fullstack_engineer": {
        "title": "Full Stack Engineer",
        "category": "Core Engineering",
        "primary_skills": ["javascript", "typescript", "react", "node.js", "python", "sql", "rest api", "html", "css", "mongodb", "postgresql", "docker"],
        "secondary_skills": ["express", "next.js", "redis", "aws", "graphql", "tailwind"],
        "critical_keywords": ["end-to-end", "database", "api design", "client-server", "authentication"]
    },
    "data_engineer": {
        "title": "Data Engineer",
        "category": "Data & Analytics",
        "primary_skills": ["python", "sql", "spark", "hadoop", "kafka", "airflow", "etl", "data warehouse", "bigquery", "snowflake", "postgres"],
        "secondary_skills": ["scala", "dbt", "parquet", "aws s3", "data modeling", "pandas"],
        "critical_keywords": ["pipeline", "batch processing", "streaming", "data lake", "schema design"]
    },
    "ml_engineer": {
        "title": "Machine Learning Engineer / AI Specialist",
        "category": "Artificial Intelligence",
        "primary_skills": ["python", "machine learning", "deep learning", "pytorch", "tensorflow", "scikit-learn", "numpy", "pandas", "nlp", "computer vision"],
        "secondary_skills": ["mlops", "docker", "hugging face", "fastapi", "gpu", "onnx", "vector databases"],
        "critical_keywords": ["model training", "inference", "feature engineering", "loss function", "fine-tuning"]
    },
    "devops_cloud_engineer": {
        "title": "DevOps & Cloud Platform Engineer",
        "category": "Infrastructure",
        "primary_skills": ["docker", "kubernetes", "linux", "aws", "gcp", "azure", "terraform", "ci/cd", "bash", "ansible", "git"],
        "secondary_skills": ["prometheus", "grafana", "helm", "networking", "security", "yaml"],
        "critical_keywords": ["infrastructure as code", "orchestration", "observability", "high availability", "automation"]
    },
    "cybersecurity_analyst": {
        "title": "Cybersecurity & Information Security Analyst",
        "category": "Security",
        "primary_skills": ["network security", "owasp", "linux", "vulnerability assessment", "penetration testing", "wireshark", "cryptography", "python", "siem"],
        "secondary_skills": ["incident response", "burp suite", "firewalls", "iam", "iso 27001", "compliance"],
        "critical_keywords": ["threat detection", "zero trust", "encryption", "mitigation", "soc"]
    }
}


def ensure_role_comparison_table(conn) -> None:
    """Creates the role comparison persistence table."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS multi_role_comparisons (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL DEFAULT 'default_student',
            resume_snippet TEXT,
            roles_json TEXT NOT NULL,
            comparison_results_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_role_comp_student ON multi_role_comparisons(student_id)")
    conn.commit()


def get_available_roles() -> List[Dict[str, Any]]:
    """Returns catalog of all supported target technical roles."""
    return [
        {
            "key": k,
            "title": v["title"],
            "category": v["category"],
            "core_skills_sample": v["primary_skills"][:5]
        }
        for k, v in TECHNICAL_ROLE_TAXONOMY.items()
    ]


def extract_skills_from_resume_text(resume_text: str) -> Set[str]:
    """Tokenizes and matches known technical skills from candidate resume content."""
    if not resume_text or not resume_text.strip():
        return set()

    text_lower = resume_text.lower()
    # Normalize punctuation for token boundaries
    cleaned_text = re.sub(r"[^\w\s\+\#\./-]", " ", text_lower)

    found_skills: Set[str] = set()

    # Match across all known taxonomy skills
    all_known_skills = set()
    for role_data in TECHNICAL_ROLE_TAXONOMY.values():
        all_known_skills.update(role_data["primary_skills"])
        all_known_skills.update(role_data["secondary_skills"])

    for skill in all_known_skills:
        # Regex boundary match
        pattern = r"(?:^|\s|\b)" + re.escape(skill) + r"(?:\b|\s|$)"
        if re.search(pattern, cleaned_text):
            found_skills.add(skill)

    return found_skills


def compare_resume_across_roles(
    resume_text: str,
    target_role_keys: List[str]
) -> Dict[str, Any]:
    """
    Evaluates candidate resume against selected job roles, calculating match scores,
    role-specific missing competencies, cross-role common skills, and tailored suggestions.

    Raises:
        ValueError: If no target roles are provided or all roles are invalid.
    """
    if not target_role_keys:
        raise ValueError("At least one target job role must be selected.")

    valid_keys = [k.strip().lower() for k in target_role_keys if k and k.strip().lower() in TECHNICAL_ROLE_TAXONOMY]
    if not valid_keys:
        raise ValueError(
            f"No valid roles found in selection. Supported roles: {', '.join(sorted(TECHNICAL_ROLE_TAXONOMY.keys()))}"
        )

    # 1. Extract candidate skills from resume
    candidate_skills = extract_skills_from_resume_text(resume_text)

    role_evaluations: List[Dict[str, Any]] = []
    all_matched_skills: List[Set[str]] = []

    for r_key in valid_keys:
        archetype = TECHNICAL_ROLE_TAXONOMY[r_key]
        primary_set = set(archetype["primary_skills"])
        secondary_set = set(archetype["secondary_skills"])

        matched_primary = candidate_skills.intersection(primary_set)
        matched_secondary = candidate_skills.intersection(secondary_set)
        matched_total = matched_primary.union(matched_secondary)
        all_matched_skills.append(matched_total)

        missing_primary = primary_set - candidate_skills
        missing_secondary = secondary_set - candidate_skills

        # Weighted score: Primary 70%, Secondary 30%
        primary_ratio = len(matched_primary) / max(1, len(primary_set))
        secondary_ratio = len(matched_secondary) / max(1, len(secondary_set))
        raw_score = int(round((primary_ratio * 70) + (secondary_ratio * 30)))

        # Baseline compensation if resume contains relevant content
        if candidate_skills and raw_score == 0:
            raw_score = min(20, len(candidate_skills) * 4)

        match_score = max(0, min(100, raw_score))

        # Role-specific recommendations
        suggestions = []
        if missing_primary:
            top_missing = sorted(list(missing_primary))[:3]
            suggestions.append(f"Acquire high-impact competencies: {', '.join(top_missing)}.")
        if match_score < 50:
            suggestions.append(f"Build at least one end-to-end portfolio project tailored specifically for {archetype['title']}.")
        else:
            suggestions.append(f"Highlight production impact, scalability metrics, and testing for {archetype['title']} applications.")

        role_evaluations.append({
            "role_key": r_key,
            "role_title": archetype["title"],
            "category": archetype["category"],
            "match_score": match_score,
            "matched_skills": sorted(list(matched_total)),
            "matched_skills_count": len(matched_total),
            "missing_skills": sorted(list(missing_primary.union(missing_secondary))),
            "top_missing_skills": sorted(list(missing_primary))[:4],
            "role_suggestions": suggestions
        })

    # Sort role evaluations by highest match score
    role_evaluations.sort(key=lambda x: x["match_score"], reverse=True)

    # 2. Identify common / transferable skills present across ALL evaluated roles
    if all_matched_skills:
        common_matched = set.intersection(*all_matched_skills)
    else:
        common_matched = set()

    # 3. Best-fit career track summary
    best_fit = role_evaluations[0] if role_evaluations else None

    return {
        "evaluated_roles_count": len(role_evaluations),
        "total_extracted_skills_count": len(candidate_skills),
        "candidate_skills": sorted(list(candidate_skills)),
        "common_transferable_skills": sorted(list(common_matched)),
        "best_fit_role": {
            "role_title": best_fit["role_title"] if best_fit else "N/A",
            "match_score": best_fit["match_score"] if best_fit else 0
        },
        "role_comparisons": role_evaluations,
        "comparison_timestamp": datetime.now(timezone.utc).isoformat()
    }


def save_multi_role_comparison(
    student_id: str,
    resume_text: str,
    selected_roles: List[str],
    comparison_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Persists multi-role comparison in database."""
    comp_id = str(uuid.uuid4())
    snippet = resume_text[:300] if resume_text else ""

    with get_db_connection() as conn:
        ensure_role_comparison_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO multi_role_comparisons (
                id, student_id, resume_snippet, roles_json, comparison_results_json
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            comp_id, student_id, snippet, json.dumps(selected_roles), json.dumps(comparison_results)
        ))
        conn.commit()

    return {
        "comparison_id": comp_id,
        "student_id": student_id,
        "saved_at": datetime.now(timezone.utc).isoformat()
    }


def get_student_role_comparisons(student_id: str) -> List[Dict[str, Any]]:
    """Retrieves saved role comparisons for the candidate."""
    with get_db_connection() as conn:
        ensure_role_comparison_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, student_id, resume_snippet, roles_json, comparison_results_json, created_at
            FROM multi_role_comparisons
            WHERE student_id = ?
            ORDER BY created_at DESC
        """, (student_id,))
        rows = cursor.fetchall()
        results = []
        for r in rows:
            rec = dict(r)
            try:
                rec["comparison"] = json.loads(rec.get("comparison_results_json") or "{}")
            except Exception:
                rec["comparison"] = {}
            try:
                rec["selected_roles"] = json.loads(rec.get("roles_json") or "[]")
            except Exception:
                rec["selected_roles"] = []
            rec.pop("comparison_results_json", None)
            rec.pop("roles_json", None)
            results.append(rec)
        return results
