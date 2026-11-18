"""
Role-Targeted Skill Gap Analysis Service (#495).
================================================
Empowers students to benchmark their current skill profile against specific,
customizable job roles (e.g. Software Developer, Data Analyst, Web Developer)
rather than general placement baselines.

Key Capabilities:
1. Dynamic Role Profile Discovery:
   - Reads editable JSON profiles from the `data/roles/` directory.
   - A new role profile can be added by placing a single JSON file into `data/roles/`.
2. Robust Skill Alias Normalization:
   - Correctly matches variations of skill names (e.g. "JS" -> "JavaScript",
     "TS" -> "TypeScript", "ReactJS" -> "React", "Postgres" -> "PostgreSQL",
     "Python 3" -> "Python", "PowerBI" -> "Power BI", "K8s" -> "Kubernetes").
3. Multi-Faceted Gap Remediation:
   - Identifies matched skills and missing competencies (split by Required vs Nice-to-Have).
   - Provides concrete, actionable suggested topics to learn for each identified gap.
   - Computes role-specific match percentage and readiness verdict.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import config

logger = logging.getLogger(__name__)

# Default location for role JSON profiles
DEFAULT_ROLES_DIR = Path(getattr(config, "BASE_DIR", Path(__file__).resolve().parent.parent)) / "data" / "roles"

# Canonical skill aliases mapping (lowercased alias -> canonical representation)
SKILL_ALIASES: Dict[str, str] = {
    # JavaScript & TypeScript
    "javascript": "javascript",
    "js": "javascript",
    "ecmascript": "javascript",
    "es6": "javascript",
    "es6+": "javascript",
    "vanilla js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",

    # Python
    "python": "python",
    "py": "python",
    "python3": "python",
    "python 3": "python",
    "python2": "python",

    # C / C++ / C# / Go
    "c++": "c++",
    "cpp": "c++",
    "c plus plus": "c++",
    "c#": "c#",
    "csharp": "c#",
    "c-sharp": "c#",
    "c sharp": "c#",
    "golang": "go",
    "go lang": "go",
    "go": "go",
    "java": "java",
    "core java": "java",

    # Web & Frontend Frameworks
    "html": "html",
    "html5": "html",
    "css": "css",
    "css3": "css",
    "react": "react",
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "vue": "vue",
    "vue.js": "vue",
    "vuejs": "vue",
    "angular": "angular",
    "angular.js": "angular",
    "angularjs": "angular",
    "next.js": "next.js",
    "nextjs": "next.js",
    "next js": "next.js",
    "node": "node.js",
    "node.js": "node.js",
    "nodejs": "node.js",
    "node js": "node.js",
    "express": "express",
    "express.js": "express",
    "expressjs": "express",
    "tailwind": "tailwind css",
    "tailwindcss": "tailwind css",
    "tailwind css": "tailwind css",
    "bootstrap": "bootstrap",
    "redux": "redux",
    "redux toolkit": "redux",
    "responsive design": "responsive design",
    "responsive web design": "responsive design",
    "web performance": "web performance",

    # Databases
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "sql": "sql",
    "structured query language": "sql",
    "t-sql": "sql",
    "pl/sql": "sql",
    "redis": "redis",
    "elasticsearch": "elasticsearch",

    # Cloud, DevOps & Linux
    "docker": "docker",
    "docker container": "docker",
    "docker containers": "docker",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "azure": "azure",
    "microsoft azure": "azure",
    "ci/cd": "ci/cd",
    "ci cd": "ci/cd",
    "continuous integration": "ci/cd",
    "terraform": "terraform",
    "ansible": "ansible",
    "linux": "linux",
    "unix": "linux",
    "bash": "bash",
    "shell": "bash",
    "shell scripting": "bash",
    "git": "git",
    "github": "git",
    "gitlab": "git",

    # Data & Analytics
    "power bi": "power bi",
    "powerbi": "power bi",
    "excel": "excel",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "tableau": "tableau",
    "pandas": "pandas",
    "numpy": "numpy",
    "scipy": "scipy",
    "spark": "spark",
    "apache spark": "spark",
    "pyspark": "spark",
    "hadoop": "hadoop",
    "kafka": "kafka",
    "apache kafka": "kafka",
    "airflow": "airflow",
    "apache airflow": "airflow",
    "etl": "etl",
    "data warehouse": "data warehousing",
    "data warehousing": "data warehousing",
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "statistics": "statistics",
    "data visualization": "data visualization",
    "data cleaning": "data cleaning",
    "a/b testing": "a/b testing",
    "ab testing": "a/b testing",
    "r": "r",

    # Machine Learning & AI
    "machine learning": "machine learning",
    "ml": "machine learning",
    "deep learning": "deep learning",
    "dl": "deep learning",
    "pytorch": "pytorch",
    "torch": "pytorch",
    "tensorflow": "tensorflow",
    "tf": "tensorflow",
    "keras": "keras",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "nlp": "nlp",
    "natural language processing": "nlp",
    "computer vision": "computer vision",
    "cv": "computer vision",

    # Core Engineering & Architecture
    "dsa": "data structures & algorithms",
    "data structures": "data structures",
    "algorithms": "algorithms",
    "data structures & algorithms": "data structures & algorithms",
    "system design": "system design",
    "rest api": "rest apis",
    "rest apis": "rest apis",
    "restful api": "rest apis",
    "restful apis": "rest apis",
    "rest": "rest apis",
    "graphql": "graphql",
    "microservices": "microservices",
    "oop": "oop",
    "object oriented programming": "oop",
    "unit testing": "unit testing",
}

# General fallback topics for common skills if not provided in role JSON
GLOBAL_SKILL_TOPICS_CATALOG: Dict[str, List[str]] = {
    "sql": [
        "Window Functions & CTEs",
        "Indexing & Query Plan Optimization",
        "Complex Joins & Aggregations",
    ],
    "python": [
        "Object-Oriented Programming & Dataclasses",
        "Asynchronous I/O and Concurrency (asyncio)",
        "Generators, Decorators, and Iterators",
    ],
    "javascript": [
        "Async/Await, Promises & Event Loop",
        "DOM Traversal and Event Handling",
        "ES6+ Modern Syntax & Modules",
    ],
    "typescript": [
        "Static Typing & Interfaces",
        "Generics and Utility Types",
        "Type Guards & Narrowing",
    ],
    "react": [
        "Hooks (useState, useEffect, useMemo)",
        "Component Composition & State Architecture",
        "Rendering Optimization & Virtual DOM",
    ],
    "data structures": [
        "Binary Trees, Heaps, and Priority Queues",
        "Hash Tables and Collision Resolution",
        "Graph Representations and Traversals",
    ],
    "algorithms": [
        "Dynamic Programming and Memoization",
        "Graph Algorithms (BFS, DFS, Dijkstra)",
        "Sorting & Binary Search Patterns",
    ],
    "git": [
        "Branching Models and Pull Request Workflows",
        "Interactive Rebasing and Conflict Resolution",
        "Stashing, Cherry-Picking, and History Cleanup",
    ],
    "docker": [
        "Multi-stage Dockerfile Optimization",
        "Container Networking and Volume Mounts",
        "Docker Compose Orchestration",
    ],
    "system design": [
        "Horizontal vs. Vertical Scaling & Load Balancing",
        "Caching Strategies & Invalidation",
        "Database Partitioning and CAP Theorem",
    ],
    "rest apis": [
        "RESTful HTTP Methods & Status Codes",
        "Authentication (JWT / OAuth2)",
        "Pagination, Rate Limiting & Error Contracts",
    ],
    "power bi": [
        "DAX Measures & Time Intelligence",
        "Star Schema Data Modeling",
        "Interactive Dashboards & Row-Level Security",
    ],
    "tableau": [
        "Level of Detail (LOD) Calculations",
        "Interactive Dashboard Actions & Filters",
        "Calculated Fields and Visual Best Practices",
    ],
    "excel": [
        "Advanced Lookup Formulas (XLOOKUP, INDEX/MATCH)",
        "Dynamic Pivot Tables, Slicers, and Timelines",
        "Power Query Automation and Data Transformation",
    ],
    "html": [
        "Semantic Markup and Accessible Architecture",
        "ARIA Attributes & Screen Reader Compatibility",
        "HTML5 Form Validation and Responsive Media",
    ],
    "css": [
        "Flexbox and CSS Grid Two-Dimensional Layouts",
        "Custom Properties (Variables) and Theming",
        "Animations, Transitions, and Mobile Breakpoints",
    ],
}


def normalize_skill_name(skill: str) -> str:
    """
    Normalizes a skill name string using the canonical aliases dictionary (#495).
    Strips whitespace, converts to lowercase, resolves aliases (e.g. "JS" -> "javascript"),
    and strips punctuation suffixes for robust comparison.
    """
    if not skill or not isinstance(skill, str):
        return ""

    raw_lower = skill.strip().lower()
    if raw_lower in SKILL_ALIASES:
        return SKILL_ALIASES[raw_lower]

    # Strip surrounding punctuation
    trimmed = re.sub(r"^[^\w+#]+|[^\w+#]+$", "", raw_lower)
    if trimmed in SKILL_ALIASES:
        return SKILL_ALIASES[trimmed]

    # Check without dots, hyphens, and spaces
    stripped = re.sub(r"[.\-_\s]", "", raw_lower)
    for alias_key, canonical in SKILL_ALIASES.items():
        if re.sub(r"[.\-_\s]", "", alias_key) == stripped:
            return canonical

    return raw_lower


def skills_match(skill_a: str, skill_b: str) -> bool:
    """
    Determines whether two skill representations represent the same technical competency.
    Returns True if their normalized canonical forms match.
    """
    norm_a = normalize_skill_name(skill_a)
    norm_b = normalize_skill_name(skill_b)

    if not norm_a or not norm_b:
        return False

    if norm_a == norm_b:
        return True

    # Multi-word containment check (e.g. "rest api" vs "rest apis" or "docker" vs "docker container")
    tokens_a = set(re.split(r"[\s\-_/]+", norm_a))
    tokens_b = set(re.split(r"[\s\-_/]+", norm_b))
    if tokens_a == tokens_b:
        return True

    return False


def get_roles_directory(custom_dir: Optional[Path] = None) -> Path:
    """Resolves the active directory containing editable role profile JSON files."""
    if custom_dir is not None:
        return Path(custom_dir)
    return DEFAULT_ROLES_DIR


def get_available_roles(roles_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Dynamically discovers and loads all role profiles from editable JSON files in data/roles/ (#495).
    A new role can be added simply by dropping one JSON file into the directory.
    """
    target_dir = get_roles_directory(roles_dir)
    if not target_dir.exists() or not target_dir.is_dir():
        logger.warning(f"Role profile directory not found at: {target_dir}")
        return []

    roles: List[Dict[str, Any]] = []
    for json_file in sorted(target_dir.glob("*.json")):
        if not json_file.is_file():
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                continue

            file_stem = json_file.stem
            role_id = str(data.get("id") or file_stem).strip().lower()
            role_name = str(data.get("name") or data.get("title") or file_stem.replace("_", " ").title()).strip()
            category = str(data.get("category") or "General").strip()
            description = str(data.get("description") or "").strip()

            req_skills = data.get("required_skills")
            if not isinstance(req_skills, list):
                req_skills = data.get("primary_skills") or []

            nice_skills = data.get("nice_to_have_skills")
            if not isinstance(nice_skills, list):
                nice_skills = data.get("secondary_skills") or data.get("optional_skills") or []

            roles.append({
                "id": role_id,
                "name": role_name,
                "category": category,
                "description": description,
                "file_path": str(json_file),
                "required_skills": [str(s).strip() for s in req_skills if s and str(s).strip()],
                "nice_to_have_skills": [str(s).strip() for s in nice_skills if s and str(s).strip()],
                "total_skills_count": len(req_skills) + len(nice_skills),
                "suggested_topics": data.get("suggested_topics") or {},
            })
        except Exception as exc:
            logger.error(f"Error loading role JSON {json_file.name}: {exc}")

    return roles


def get_role_profile(role_id: str, roles_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a specific role profile by its identifier, slug, or title.
    """
    if not role_id:
        return None

    clean_id = str(role_id).strip().lower()
    all_roles = get_available_roles(roles_dir)

    # 1. Exact match by id
    for r in all_roles:
        if r["id"] == clean_id:
            return r

    # 2. Match by normalized name
    for r in all_roles:
        if r["name"].strip().lower() == clean_id:
            return r

    # 3. Match by partial or slugified name
    clean_slug = re.sub(r"[^a-z0-9]", "_", clean_id).strip("_")
    for r in all_roles:
        r_slug = re.sub(r"[^a-z0-9]", "_", r["id"]).strip("_")
        if r_slug == clean_slug:
            return r

    return None


def extract_candidate_skills(source: Any) -> List[str]:
    """
    Extracts an aggregated, deduplicated list of candidate skills from various input shapes:
    - An analysis record dict (job_match, resume_analysis, resume_text)
    - A list of skill strings
    - A raw comma-separated string
    """
    skills: Set[str] = set()

    if isinstance(source, dict):
        results = source.get("results") or source

        # 1. Matched skills from job_match
        jm = results.get("job_match") or results.get("job_compatibility") or {}
        for s in jm.get("matched_skills", []):
            if s and str(s).strip():
                skills.add(str(s).strip())

        # 2. Skills from resume_analysis
        ra = results.get("resume_analysis") or {}
        for s in ra.get("skills", []):
            if s and str(s).strip():
                skills.add(str(s).strip())

        # 3. Known skills mentioned in resume_text
        resume_text = source.get("resume_text") or results.get("resume_text") or ""
        if isinstance(resume_text, str) and resume_text.strip():
            text_lower = resume_text.lower()
            cleaned_text = re.sub(r"[^\w\s\+\#\./-]", " ", text_lower)
            for alias, canonical in SKILL_ALIASES.items():
                pattern = r"(?:^|\s|\b)" + re.escape(alias) + r"(?:\b|\s|$)"
                if re.search(pattern, cleaned_text):
                    skills.add(alias)

    elif isinstance(source, list):
        for item in source:
            if isinstance(item, str) and item.strip():
                skills.add(item.strip())
            elif isinstance(item, dict) and item.get("skill"):
                skills.add(str(item["skill"]).strip())

    elif isinstance(source, str) and source.strip():
        # Split on commas or newlines
        parts = re.split(r"[,;\n]+", source)
        for p in parts:
            if p.strip():
                skills.add(p.strip())

    return sorted(list(skills))


def _resolve_suggested_topics_for_skill(skill_name: str, role_topics: Dict[str, Any]) -> List[str]:
    """
    Resolves suggested learning topics for a missing skill:
    1. Checks role profile JSON's `suggested_topics` block (with alias normalization)
    2. Falls back to global common topics catalog
    3. Generates high-quality targeted curriculum topics dynamically
    """
    norm_target = normalize_skill_name(skill_name)

    # 1. Role profile JSON lookup
    if isinstance(role_topics, dict):
        for k, v in role_topics.items():
            if normalize_skill_name(k) == norm_target and isinstance(v, list) and v:
                return [str(t).strip() for t in v if str(t).strip()]

    # 2. Global catalog lookup
    for k, v in GLOBAL_SKILL_TOPICS_CATALOG.items():
        if normalize_skill_name(k) == norm_target and v:
            return list(v)

    # 3. Synthesized fallback curriculum
    clean_display = skill_name.strip()
    return [
        f"Core principles, foundational concepts, and syntax of {clean_display}",
        f"Applied hands-on implementation and common architecture patterns in {clean_display}",
        f"Production best practices, testing, and performance optimization for {clean_display}",
    ]


def analyze_role_skill_gap(
    candidate_skills: Any,
    role_id_or_profile: Any,
    roles_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Performs a role-specific skill gap analysis against a selected job profile (#495).

    Returns:
    - matched_skills: list of matched competencies with type (Required / Nice-to-Have)
    - missing_skills: list of missing competencies with suggested topics to learn
    - match_percentage: weighted compatibility score (Required: 75%, Nice-to-Have: 25%)
    - summary: descriptive readiness breakdown
    """
    # 1. Resolve role profile
    if isinstance(role_id_or_profile, dict):
        role_profile = role_id_or_profile
    else:
        role_profile = get_role_profile(str(role_id_or_profile), roles_dir)

    if not role_profile:
        # Fallback to software developer if unknown
        available = get_available_roles(roles_dir)
        role_profile = available[0] if available else {
            "id": "software_developer",
            "name": "Software Developer",
            "category": "Core Engineering",
            "description": "General Software Development Profile",
            "required_skills": ["Data Structures", "Algorithms", "Python", "SQL", "Git"],
            "nice_to_have_skills": ["Docker", "Linux"],
            "suggested_topics": {},
        }

    raw_candidate_skills = extract_candidate_skills(candidate_skills)
    normalized_candidate_map: Dict[str, str] = {
        normalize_skill_name(s): s for s in raw_candidate_skills if s and str(s).strip()
    }

    required_skills = role_profile.get("required_skills") or []
    nice_to_have_skills = role_profile.get("nice_to_have_skills") or []
    role_topics = role_profile.get("suggested_topics") or {}

    matched_skills: List[Dict[str, Any]] = []
    missing_skills: List[Dict[str, Any]] = []

    matched_required_count = 0
    matched_nice_count = 0

    # 2. Evaluate Required Skills
    for req_skill in required_skills:
        clean_req = str(req_skill).strip()
        norm_req = normalize_skill_name(clean_req)

        matched_candidate_val = None
        for norm_cand, orig_cand in normalized_candidate_map.items():
            if skills_match(norm_cand, norm_req):
                matched_candidate_val = orig_cand
                break

        if matched_candidate_val:
            matched_required_count += 1
            matched_skills.append({
                "skill": clean_req,
                "matched_from": matched_candidate_val,
                "type": "Required",
                "importance": "High",
                "is_required": True,
            })
        else:
            topics = _resolve_suggested_topics_for_skill(clean_req, role_topics)
            missing_skills.append({
                "skill": clean_req,
                "type": "Required",
                "importance": "High",
                "priority": "High",
                "is_required": True,
                "learning_time": "2-3 weeks",
                "suggested_topics": topics,
                "project_suggestion": f"Build a practical proof-of-concept module applying {clean_req} principles.",
            })

    # 3. Evaluate Nice-to-Have Skills
    for nice_skill in nice_to_have_skills:
        clean_nice = str(nice_skill).strip()
        norm_nice = normalize_skill_name(clean_nice)

        matched_candidate_val = None
        for norm_cand, orig_cand in normalized_candidate_map.items():
            if skills_match(norm_cand, norm_nice):
                matched_candidate_val = orig_cand
                break

        if matched_candidate_val:
            matched_nice_count += 1
            matched_skills.append({
                "skill": clean_nice,
                "matched_from": matched_candidate_val,
                "type": "Nice-to-Have",
                "importance": "Medium",
                "is_required": False,
            })
        else:
            topics = _resolve_suggested_topics_for_skill(clean_nice, role_topics)
            missing_skills.append({
                "skill": clean_nice,
                "type": "Nice-to-Have",
                "importance": "Medium",
                "priority": "Medium",
                "is_required": False,
                "learning_time": "1-2 weeks",
                "suggested_topics": topics,
                "project_suggestion": f"Implement a side feature or CI script integrating {clean_nice}.",
            })

    # 4. Calculate Match Percentage
    total_req = len(required_skills)
    total_nice = len(nice_to_have_skills)

    req_score = (matched_required_count / total_req * 75) if total_req > 0 else 75
    nice_score = (matched_nice_count / total_nice * 25) if total_nice > 0 else 25
    match_pct = max(0, min(100, int(round(req_score + nice_score))))

    # 5. Readiness Verdict
    if match_pct >= 80:
        readiness_verdict = "Role Ready"
        summary_text = (
            f"Strong alignment with {role_profile['name']}. You possess {matched_required_count}/{total_req} required "
            f"skills. Polish the remaining gaps to stand out."
        )
    elif match_pct >= 55:
        readiness_verdict = "Targeted Prep Needed"
        summary_text = (
            f"Moderate alignment with {role_profile['name']} ({match_pct}%). Focus on mastering the "
            f"{len([m for m in missing_skills if m['is_required']])} critical required skill gaps."
        )
    else:
        readiness_verdict = "Significant Skill Gap"
        summary_text = (
            f"Active preparation required for {role_profile['name']} ({match_pct}% match). Dedicate dedicated "
            f"study to the missing core competencies."
        )

    return {
        "role_id": role_profile["id"],
        "role_name": role_profile["name"],
        "role_category": role_profile.get("category", "General"),
        "role_description": role_profile.get("description", ""),
        "match_percentage": match_pct,
        "readiness_verdict": readiness_verdict,
        "summary": summary_text,
        "total_required": total_req,
        "total_nice_to_have": total_nice,
        "matched_required_count": matched_required_count,
        "matched_nice_count": matched_nice_count,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "candidate_skills_detected": raw_candidate_skills,
    }
