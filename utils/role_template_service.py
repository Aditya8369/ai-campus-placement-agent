"""
Role Skill Templates Service (#646).
====================================
Provides predefined campus placement role templates (e.g. Software Developer,
Backend Developer, Data Analyst, DevOps, QA, Android, etc.) with core skills,
good-to-have skills, and typical tools.

Enables students (especially 1st and 2nd year students) to conduct targeted
skill gap analysis and receive personalized preparation roadmaps against
standardized campus roles without needing to paste a custom job description.

Acceptance Criteria:
- A role can be chosen instead of pasting a job description and produces a skill gap result.
- Templates are validated (schema test) so malformed entries fail CI.
- Adding a role requires editing only `data/role_templates.json`.
- Tests cover template loading, schema validation, and the role-based analysis path.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import config

logger = logging.getLogger(__name__)

# Default location for the unified role templates JSON
DEFAULT_ROLE_TEMPLATES_FILE = (
    Path(getattr(config, "BASE_DIR", Path(__file__).resolve().parent.parent))
    / "data"
    / "role_templates.json"
)

# Canonical skill aliases for normalization
SKILL_ALIASES: Dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "c++": "c++",
    "cpp": "c++",
    "c#": "c#",
    "golang": "go",
    "reactjs": "react",
    "react.js": "react",
    "nextjs": "next.js",
    "next.js": "next.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "k8s": "kubernetes",
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
    "powerbi": "power bi",
    "power bi": "power bi",
    "dsa": "data structures & algorithms",
    "data structures": "data structures",
    "algorithms": "algorithms",
    "ci cd": "ci/cd",
    "rest": "rest apis",
    "rest api": "rest apis",
    "rest apis": "rest apis",
    "restful apis": "rest apis",
}


def normalize_skill(skill: str) -> str:
    """Normalizes a skill name to its canonical lowercased representation."""
    if not skill or not isinstance(skill, str):
        return ""
    cleaned = re.sub(r"[\t\r\n]+", " ", skill).strip().lower()
    return SKILL_ALIASES.get(cleaned, cleaned)


def validate_role_template_schema(data: Any) -> Tuple[bool, List[str]]:
    """
    Validates the role templates data against strict schema rules.
    
    Rules:
    1. Data must be a non-empty list of dictionaries.
    2. Each dictionary must contain all required keys:
       'id', 'name', 'description', 'core_skills', 'good_to_have_skills', 'typical_tools'.
    3. 'id' must be a non-empty string consisting only of alphanumeric chars, hyphens, or underscores.
    4. All 'id' values must be unique.
    5. 'name' and 'description' must be non-empty strings.
    6. 'core_skills' must be a non-empty list of non-empty strings.
    7. 'good_to_have_skills' and 'typical_tools' must be lists of non-empty strings.
    
    Returns:
        (is_valid, errors_list)
    """
    errors: List[str] = []

    if not isinstance(data, list):
        return False, ["Root structure must be a JSON array (list)."]

    if len(data) == 0:
        return False, ["Role templates list must not be empty."]

    seen_ids: Set[str] = set()

    for idx, entry in enumerate(data):
        prefix = f"Entry [{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: Must be a JSON object (dict).")
            continue

        entry_id = entry.get("id")
        if entry_id:
            prefix = f"Role '{entry_id}' (index {idx})"

        # Check required fields
        required_keys = ["id", "name", "description", "core_skills", "good_to_have_skills", "typical_tools"]
        for key in required_keys:
            if key not in entry:
                errors.append(f"{prefix}: Missing required key '{key}'.")

        # Validate 'id'
        if "id" in entry:
            if not isinstance(entry["id"], str) or not entry["id"].strip():
                errors.append(f"{prefix}: 'id' must be a non-empty string.")
            else:
                cid = entry["id"].strip()
                if not re.match(r"^[a-zA-Z0-9_\-]+$", cid):
                    errors.append(f"{prefix}: 'id' '{cid}' must contain only alphanumeric characters, dashes, or underscores.")
                if cid.lower() in seen_ids:
                    errors.append(f"{prefix}: Duplicate role id '{cid}'.")
                seen_ids.add(cid.lower())

        # Validate 'name'
        if "name" in entry:
            if not isinstance(entry["name"], str) or not entry["name"].strip():
                errors.append(f"{prefix}: 'name' must be a non-empty string.")

        # Validate 'description'
        if "description" in entry:
            if not isinstance(entry["description"], str) or not entry["description"].strip():
                errors.append(f"{prefix}: 'description' must be a non-empty string.")

        # Validate 'core_skills'
        if "core_skills" in entry:
            if not isinstance(entry["core_skills"], list) or len(entry["core_skills"]) == 0:
                errors.append(f"{prefix}: 'core_skills' must be a non-empty list of skill names.")
            else:
                for s_idx, skill in enumerate(entry["core_skills"]):
                    if not isinstance(skill, str) or not skill.strip():
                        errors.append(f"{prefix}: 'core_skills' item at index {s_idx} must be a non-empty string.")

        # Validate 'good_to_have_skills'
        if "good_to_have_skills" in entry:
            if not isinstance(entry["good_to_have_skills"], list):
                errors.append(f"{prefix}: 'good_to_have_skills' must be a list of strings.")
            else:
                for s_idx, skill in enumerate(entry["good_to_have_skills"]):
                    if not isinstance(skill, str) or not skill.strip():
                        errors.append(f"{prefix}: 'good_to_have_skills' item at index {s_idx} must be a non-empty string.")

        # Validate 'typical_tools'
        if "typical_tools" in entry:
            if not isinstance(entry["typical_tools"], list):
                errors.append(f"{prefix}: 'typical_tools' must be a list of strings.")
            else:
                for t_idx, tool in enumerate(entry["typical_tools"]):
                    if not isinstance(tool, str) or not tool.strip():
                        errors.append(f"{prefix}: 'typical_tools' item at index {t_idx} must be a non-empty string.")

    return len(errors) == 0, errors


def assert_valid_role_templates(data: Any) -> None:
    """Raises ValueError if data fails role template schema validation."""
    valid, errors = validate_role_template_schema(data)
    if not valid:
        err_msg = "Role templates schema validation failed:\n" + "\n".join(f" - {e}" for e in errors)
        logger.error(err_msg)
        raise ValueError(err_msg)


def load_role_templates(
    file_path: Optional[str | Path] = None,
    validate: bool = True
) -> List[Dict[str, Any]]:
    """
    Loads predefined role templates from `data/role_templates.json`.
    
    If validate=True, verifies schema compliance and raises ValueError on any violation.
    """
    target_path = Path(file_path) if file_path else DEFAULT_ROLE_TEMPLATES_FILE

    if not target_path.exists():
        logger.warning(f"Role templates file not found at: {target_path}")
        return []

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        err = f"Failed to parse role templates JSON at {target_path}: {exc}"
        logger.error(err)
        raise ValueError(err) from exc

    if validate:
        assert_valid_role_templates(data)

    return data


def get_role_template_by_id(
    role_id: str,
    file_path: Optional[str | Path] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a specific role template by its unique identifier (slug)."""
    if not role_id:
        return None
    normalized_id = str(role_id).strip().lower()
    templates = load_role_templates(file_path=file_path, validate=False)
    for template in templates:
        if template.get("id", "").strip().lower() == normalized_id:
            return template
    return None


def format_role_template_as_job_description(template: Dict[str, Any]) -> str:
    """
    Formats a role template into a standardized, rich job description string.
    
    This text is seamlessly processed by the existing analysis coordinator,
    maintaining 100% compatibility with ATS scoring, skill extraction,
    and preparation roadmaps.
    """
    if not template or not isinstance(template, dict):
        return ""

    name = template.get("name", "Software Developer")
    description = template.get("description", "")
    core_skills = template.get("core_skills", [])
    good_to_have = template.get("good_to_have_skills", [])
    tools = template.get("typical_tools", [])

    core_bullets = "\n".join(f"- {s}" for s in core_skills) if core_skills else "- General Engineering Competence"
    good_bullets = "\n".join(f"- {s}" for s in good_to_have) if good_to_have else "- Continuous Learning"
    tools_bullets = "\n".join(f"- {t}" for t in tools) if tools else "- Modern Developer Tools"

    return (
        f"Role: {name}\n"
        f"Target Profile Overview:\n{description}\n\n"
        f"Core Technical Competencies & Requirements:\n{core_bullets}\n\n"
        f"Good-to-Have Skills & Secondary Qualifications:\n{good_bullets}\n\n"
        f"Typical Industry Tools & Development Stack:\n{tools_bullets}\n"
    )


def build_role_template_skill_gap(
    candidate_skills: List[str],
    template: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Computes a deterministic skill gap analysis for a candidate's skills
    against a given role template.
    
    Weights: Core Skills (70%), Good-to-have Skills (30%).
    """
    if not template:
        raise ValueError("Role template must be provided.")

    core_skills = template.get("core_skills", [])
    good_skills = template.get("good_to_have_skills", [])

    candidate_norm_set = {normalize_skill(s) for s in candidate_skills if s}

    matched_core: List[str] = []
    missing_core: List[str] = []
    for skill in core_skills:
        if normalize_skill(skill) in candidate_norm_set:
            matched_core.append(skill)
        else:
            missing_core.append(skill)

    matched_good: List[str] = []
    missing_good: List[str] = []
    for skill in good_skills:
        if normalize_skill(skill) in candidate_norm_set:
            matched_good.append(skill)
        else:
            missing_good.append(skill)

    # Compute weighted score
    core_ratio = len(matched_core) / max(len(core_skills), 1)
    good_ratio = len(matched_good) / max(len(good_skills), 1) if good_skills else 1.0

    match_percentage = round((core_ratio * 70.0) + (good_ratio * 30.0))
    match_percentage = max(0, min(100, match_percentage))

    if match_percentage >= 75:
        match_status = "Strong Match"
    elif match_percentage >= 50:
        match_status = "Moderate Match"
    else:
        match_status = "Needs Preparation"

    # Construct gap recommendations
    skill_gap_items: List[Dict[str, Any]] = []

    for skill in missing_core:
        skill_gap_items.append({
            "skill": skill,
            "importance": "High",
            "priority": "High",
            "category": "Core Requirement",
            "learning_time": "2-3 weeks",
            "learning_resource": f"Official {skill} Documentation & Guided Practice",
            "project_suggestion": f"Build a project module applying {skill} to real-world workflows.",
        })

    for skill in missing_good:
        skill_gap_items.append({
            "skill": skill,
            "importance": "Medium",
            "priority": "Medium",
            "category": "Good to Have",
            "learning_time": "1-2 weeks",
            "learning_resource": f"Interactive {skill} tutorials and best practice guides",
            "project_suggestion": f"Enhance an existing repository with {skill} capabilities.",
        })

    all_matched = matched_core + matched_good
    all_missing = missing_core + missing_good

    return {
        "job_match": {
            "match_percentage": match_percentage,
            "matched_skills": all_matched,
            "missing_skills": all_missing,
            "core_matched": matched_core,
            "core_missing": missing_core,
            "status": match_status,
        },
        "skill_gap": skill_gap_items,
        "target_role": template.get("name", "Software Developer"),
        "role_id": template.get("id", ""),
    }
