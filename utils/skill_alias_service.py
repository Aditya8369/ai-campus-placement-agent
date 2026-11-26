"""
Skill Alias Service
Loads canonical skill synonym mappings from data/skill_aliases.json and provides
normalization, alias resolution, canonical matching, and reconciliation utilities
to eliminate false skill gaps and duplicate skill reporting.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Path to the skill aliases configuration
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
SKILL_ALIASES_PATH = os.path.join(DATA_DIR, "skill_aliases.json")

# In-memory cached lookup structures
_CANONICAL_LOOKUP: Optional[Dict[str, str]] = None
_CANONICAL_NAMES: Optional[Set[str]] = None
_RAW_DATA: Optional[Dict[str, Any]] = None


def normalize_skill_token(token: Any) -> str:
    """
    Standardizes a skill token for lookup:
    - Lowercase
    - Strip leading/trailing whitespaces
    - Normalizes punctuation and multiple spaces, while carefully preserving
      characters essential for disambiguation (e.g., '+', '#', '.', '/').
    """
    if not token or not isinstance(token, str):
        return ""

    text = token.strip().lower()
    if not text:
        return ""

    # Replace hyphens and underscores with a space unless surrounded by special characters
    text = re.sub(r"[\t\r\n]+", " ", text)
    # Collapse multiple spaces into one
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_aliases_data() -> Dict[str, Any]:
    """
    Loads raw JSON data from data/skill_aliases.json.
    """
    global _RAW_DATA
    if _RAW_DATA is not None:
        return _RAW_DATA

    if not os.path.exists(SKILL_ALIASES_PATH):
        logger.warning(f"Skill aliases file not found at {SKILL_ALIASES_PATH}. Using empty dictionary.")
        _RAW_DATA = {"version": "1.0", "aliases": {}}
        return _RAW_DATA

    try:
        with open(SKILL_ALIASES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "aliases" not in data or not isinstance(data["aliases"], dict):
                logger.error("Skill aliases file has invalid structure.")
                _RAW_DATA = {"version": "1.0", "aliases": {}}
            else:
                _RAW_DATA = data
    except Exception as e:
        logger.error(f"Error loading skill aliases from {SKILL_ALIASES_PATH}: {e}")
        _RAW_DATA = {"version": "1.0", "aliases": {}}

    return _RAW_DATA


def _initialize_lookup_tables() -> Tuple[Dict[str, str], Set[str]]:
    """
    Builds the inverted alias-to-canonical lookup map.
    Guarantees prefix distinctions (e.g. 'java' -> 'Java', 'javascript' -> 'JavaScript',
    'c' -> 'C', 'c++' -> 'C++', 'c#' -> 'C#').
    """
    global _CANONICAL_LOOKUP, _CANONICAL_NAMES

    if _CANONICAL_LOOKUP is not None and _CANONICAL_NAMES is not None:
        return _CANONICAL_LOOKUP, _CANONICAL_NAMES

    data = _load_aliases_data()
    aliases_dict = data.get("aliases", {})

    lookup: Dict[str, str] = {}
    canonicals: Set[str] = set()

    for canonical_name, alias_list in aliases_dict.items():
        canonical_str = str(canonical_name).strip()
        if not canonical_str:
            continue

        canonicals.add(canonical_str)
        # The canonical name itself maps to itself
        norm_canonical = normalize_skill_token(canonical_str)
        if norm_canonical:
            lookup[norm_canonical] = canonical_str

        # Add all aliases
        if isinstance(alias_list, list):
            for alias in alias_list:
                norm_alias = normalize_skill_token(str(alias))
                if norm_alias:
                    lookup[norm_alias] = canonical_str

    _CANONICAL_LOOKUP = lookup
    _CANONICAL_NAMES = canonicals
    return _CANONICAL_LOOKUP, _CANONICAL_NAMES


def reload_skill_aliases() -> None:
    """
    Clears cache and forces reloading from disk (useful in tests).
    """
    global _CANONICAL_LOOKUP, _CANONICAL_NAMES, _RAW_DATA
    _CANONICAL_LOOKUP = None
    _CANONICAL_NAMES = None
    _RAW_DATA = None
    _initialize_lookup_tables()


def get_canonical_skill(skill_name: Any) -> str:
    """
    Returns the canonical skill name for a given skill or alias string.
    If the skill is not in the alias catalog, returns the cleaned original string.

    Examples:
        get_canonical_skill("JS") -> "JavaScript"
        get_canonical_skill("ReactJS") -> "React"
        get_canonical_skill("Postgres") -> "PostgreSQL"
        get_canonical_skill("k8s") -> "Kubernetes"
        get_canonical_skill("Python 3") -> "Python"
        get_canonical_skill("Java") -> "Java"
        get_canonical_skill("JavaScript") -> "JavaScript"
        get_canonical_skill("UnknownSkill") -> "UnknownSkill"
    """
    if not skill_name or not isinstance(skill_name, str):
        return ""

    raw_str = skill_name.strip()
    if not raw_str:
        return ""

    lookup, _ = _initialize_lookup_tables()
    norm = normalize_skill_token(raw_str)

    # 1. Direct match on normalized token
    if norm in lookup:
        return lookup[norm]

    # 2. Try removing trailing version patterns like " v2", " 3.x", " 3" if not matched
    # e.g. "python 3.10" -> "python"
    version_stripped = re.sub(r"\s+v?\d+(\.\w+)*$", "", norm).strip()
    if version_stripped in lookup:
        return lookup[version_stripped]

    # 3. Try removing common suffixes like " framework", " library"
    # e.g. "react framework" -> "React"
    suffix_stripped = re.sub(r"\s+(framework|library|lib|tech|stack)$", "", norm).strip()
    if suffix_stripped in lookup:
        return lookup[suffix_stripped]

    # Fallback: Return original trimmed string
    return raw_str


def are_skills_equivalent(skill_a: Any, skill_b: Any) -> bool:
    """
    Checks if two skill strings represent the same skill, either by canonical alias
    or exact case-insensitive match.
    Ensures unrelated skills sharing prefixes (e.g. Java vs JavaScript) return False.
    """
    if not skill_a or not skill_b:
        return False

    can_a = get_canonical_skill(skill_a)
    can_b = get_canonical_skill(skill_b)

    if can_a and can_b:
        return can_a.lower() == can_b.lower()

    return False


def canonicalize_skill_list(skills: Iterable[Any]) -> List[str]:
    """
    Transforms a list/iterable of skill names into their canonical representations,
    preserving first-seen ordering and deduplicating.
    """
    if not skills:
        return []

    result: List[str] = []
    seen: Set[str] = set()

    for item in skills:
        if not item:
            continue
        can_name = get_canonical_skill(item)
        if can_name and can_name.lower() not in seen:
            result.append(can_name)
            seen.add(can_name.lower())

    return result


def reconcile_matched_and_missing_skills(
    matched_skills: Iterable[Any],
    missing_skills: Iterable[Any]
) -> Tuple[List[str], List[str]]:
    """
    Reconciles matched skills and missing skills:
    1. Converts items to canonical or cleaned names.
    2. Collects set of matched canonical skills.
    3. Excludes any skill from missing_skills if its canonical representation
       is already present in matched_skills (eliminating false negative gaps).
    4. Deduplicates both lists.

    Returns:
        (clean_matched, clean_missing)
    """
    matched_list: List[str] = []
    matched_canonicals: Set[str] = set()

    for item in matched_skills or []:
        if not item:
            continue
        cleaned = str(item).strip()
        if not cleaned:
            continue
        canonical = get_canonical_skill(cleaned)
        canonical_key = canonical.lower()

        if canonical_key not in matched_canonicals:
            # Preserve the clean display or canonical name
            display_name = canonical if canonical else cleaned
            matched_list.append(display_name)
            matched_canonicals.add(canonical_key)

    missing_list: List[str] = []
    seen_missing: Set[str] = set()

    for item in missing_skills or []:
        if not item:
            continue
        cleaned = str(item).strip()
        if not cleaned:
            continue
        canonical = get_canonical_skill(cleaned)
        canonical_key = canonical.lower()

        # If already matched or already in missing, do not add as missing
        if canonical_key in matched_canonicals:
            logger.debug(
                f"reconcile_matched_and_missing_skills: Removed '{cleaned}' from missing skills "
                f"because canonical '{canonical}' is present in matched skills."
            )
            continue

        if canonical_key not in seen_missing:
            display_name = canonical if canonical else cleaned
            missing_list.append(display_name)
            seen_missing.add(canonical_key)

    return matched_list, missing_list
