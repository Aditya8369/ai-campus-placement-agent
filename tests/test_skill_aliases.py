"""
Tests for Skill Aliases and Normalization (#843)

Acceptance Criteria:
1. Aliases of the same skill are matched as one skill.
2. Unrelated skills sharing a prefix (Java vs JavaScript, C vs C++ vs C#) are not merged.
3. The alias file is schema-validated in a test.
4. Unit tests cover at least 20 alias pairs.
5. Integration with JobMatchAgent, Coordinator conflict detection, and Analysis routes.
"""

import json
import os
import pytest
from agents.job_match_agent import JobMatchAgent
from agents.coordinator import CoordinatorAgent
from utils.skill_alias_service import (
    SKILL_ALIASES_PATH,
    get_canonical_skill,
    are_skills_equivalent,
    canonicalize_skill_list,
    reconcile_matched_and_missing_skills,
    normalize_skill_token,
    reload_skill_aliases,
)


def test_skill_aliases_file_exists_and_schema_validation():
    """Validates the skill_aliases.json file structure and schema."""
    assert os.path.exists(SKILL_ALIASES_PATH), "data/skill_aliases.json must exist"

    with open(SKILL_ALIASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict), "Root must be a JSON object"
    assert "aliases" in data, "'aliases' key is required in skill_aliases.json"
    assert isinstance(data["aliases"], dict), "'aliases' must be a dict"
    assert len(data["aliases"]) >= 20, "Should define canonical skills for at least 20 technologies"

    for canonical, aliases in data["aliases"].items():
        assert isinstance(canonical, str) and canonical.strip(), f"Canonical name '{canonical}' must be non-empty string"
        assert isinstance(aliases, list), f"Aliases for '{canonical}' must be a list"
        assert len(aliases) > 0, f"Aliases list for '{canonical}' should not be empty"
        for alias in aliases:
            assert isinstance(alias, str) and alias.strip(), f"Alias '{alias}' under '{canonical}' must be a non-empty string"


def test_twenty_plus_alias_pairs_resolve_to_same_canonical():
    """Unit tests cover at least 20 alias pairs resolving to the same canonical skill."""
    test_pairs = [
        # (Alias input, Expected Canonical Skill)
        ("JS", "JavaScript"),
        ("javascript", "JavaScript"),
        ("ECMAScript", "JavaScript"),
        ("es6", "JavaScript"),
        ("vanilla js", "JavaScript"),
        ("TS", "TypeScript"),
        ("typescript", "TypeScript"),
        ("ReactJS", "React"),
        ("react.js", "React"),
        ("react js", "React"),
        ("NodeJS", "Node.js"),
        ("node.js", "Node.js"),
        ("Postgres", "PostgreSQL"),
        ("postgresql", "PostgreSQL"),
        ("psql", "PostgreSQL"),
        ("mongo", "MongoDB"),
        ("mongodb", "MongoDB"),
        ("k8s", "Kubernetes"),
        ("kubernetes", "Kubernetes"),
        ("Golang", "Golang"),
        ("go", "Golang"),
        ("aws", "AWS"),
        ("Amazon Web Services", "AWS"),
        ("gcp", "GCP"),
        ("google cloud platform", "GCP"),
        ("docker containers", "Docker"),
        ("containerization", "Docker"),
        ("python 3", "Python"),
        ("python3", "Python"),
        ("vuejs", "Vue.js"),
        ("vue.js", "Vue.js"),
        ("nextjs", "Next.js"),
        ("next.js", "Next.js"),
        ("fastapi", "FastAPI"),
        ("django rest framework", "Django"),
        ("drf", "Django"),
        ("ci/cd", "CI/CD"),
        ("cicd", "CI/CD"),
        ("github", "Git"),
        ("tailwind", "Tailwind CSS"),
        ("tailwindcss", "Tailwind CSS"),
    ]

    assert len(test_pairs) >= 20, "Must test at least 20 alias pairs"

    for alias, expected_canonical in test_pairs:
        resolved = get_canonical_skill(alias)
        assert resolved == expected_canonical, f"Expected '{alias}' -> '{expected_canonical}', got '{resolved}'"


def test_unrelated_prefix_sharing_skills_not_merged():
    """Ensure unrelated skills sharing a prefix (e.g., Java vs JavaScript, C vs C++ vs C#) are not merged."""
    # Java vs JavaScript
    assert get_canonical_skill("Java") == "Java"
    assert get_canonical_skill("JavaScript") == "JavaScript"
    assert get_canonical_skill("JS") == "JavaScript"
    assert not are_skills_equivalent("Java", "JavaScript")
    assert not are_skills_equivalent("Java", "JS")
    assert not are_skills_equivalent("core java", "es6")

    # C vs C++ vs C#
    assert get_canonical_skill("C++") == "C++"
    assert get_canonical_skill("cpp") == "C++"
    assert get_canonical_skill("C#") == "C#"
    assert get_canonical_skill("csharp") == "C#"
    assert not are_skills_equivalent("C++", "C#")
    assert not are_skills_equivalent("C", "C++")
    assert not are_skills_equivalent("C", "C#")

    # Go vs Google Cloud
    assert not are_skills_equivalent("Go", "GCP")


def test_are_skills_equivalent():
    """Verifies equivalence logic between different aliases of the same skill."""
    assert are_skills_equivalent("React", "reactjs")
    assert are_skills_equivalent("React.js", "REACT JS")
    assert are_skills_equivalent("PostgreSQL", "postgres")
    assert are_skills_equivalent("k8s", "Kubernetes")
    assert are_skills_equivalent("Python 3", "Python")
    assert are_skills_equivalent("NodeJS", "node.js")

    # False cases
    assert not are_skills_equivalent("Python", "Ruby")
    assert not are_skills_equivalent("Docker", "Kubernetes")
    assert not are_skills_equivalent("", "React")


def test_canonicalize_skill_list():
    """Tests canonicalizing a list of skills and deduplicating."""
    raw = ["reactjs", "React", "JS", "JavaScript", "Docker", "k8s", "Kubernetes"]
    canonical = canonicalize_skill_list(raw)
    assert canonical == ["React", "JavaScript", "Docker", "Kubernetes"]


def test_reconcile_matched_and_missing_skills():
    """Tests reconciling matched and missing skills to avoid false gaps."""
    # Candidate has 'JS' and 'ReactJS', JD requires 'JavaScript', 'React', and 'PostgreSQL'
    raw_matched = ["JS", "ReactJS"]
    raw_missing = ["JavaScript", "React", "PostgreSQL", "Go"]

    reconciled_matched, reconciled_missing = reconcile_matched_and_missing_skills(
        raw_matched, raw_missing
    )

    # JavaScript and React should NOT appear in missing skills because candidate has JS and ReactJS!
    assert "JavaScript" in reconciled_matched
    assert "React" in reconciled_matched
    assert "JavaScript" not in reconciled_missing
    assert "React" not in reconciled_missing
    assert "PostgreSQL" in reconciled_missing
    assert "Golang" in reconciled_missing or "Go" in reconciled_missing


def test_version_and_punctuation_handling():
    """Handles version suffixes, dots, and trailing modifiers cleanly."""
    assert get_canonical_skill("Python 3.11") == "Python"
    assert get_canonical_skill("Vue 3") == "Vue.js"
    assert get_canonical_skill("React framework") == "React"
    assert get_canonical_skill("node.js") == "Node.js"


def test_job_match_agent_reconciliation_integration():
    """Tests that JobMatchAgent eliminates false gaps when aliases match."""
    agent = JobMatchAgent()
    data = {
        "match_percentage": 75,
        "matched_skills": ["JS", "Postgres", "Docker"],
        "missing_skills": ["JavaScript", "PostgreSQL", "Kubernetes"],
        "required_certifications": [],
        "recommended_improvements": [],
        "top_5_resume_changes": []
    }

    result = agent.process(data)
    matched = result["matched_skills"]
    missing = result["missing_skills"]

    # Canonical JavaScript and PostgreSQL should be matched and NOT missing
    assert "JavaScript" in matched
    assert "PostgreSQL" in matched
    assert "JavaScript" not in missing
    assert "PostgreSQL" not in missing
    assert "Kubernetes" in missing


def test_coordinator_conflict_detection_with_aliases():
    """Coordinator detects cross-section contradiction when aliases refer to same skill."""
    coordinator = CoordinatorAgent()

    job_match = {
        "matched_skills": ["ReactJS"],
        "missing_skills": ["React"]
    }
    skill_gap = [
        {"skill": "react.js", "priority": "high"}
    ]

    conflicts = coordinator._detect_conflicts(job_match, skill_gap, {})
    conflict_types = [c["conflict_type"] for c in conflicts]

    # ReactJS in matched vs React in missing_skills and react.js in skill_gap should be flagged!
    assert "matched_skill_in_missing_skills" in conflict_types
    assert "matched_skill_in_skill_gap" in conflict_types
