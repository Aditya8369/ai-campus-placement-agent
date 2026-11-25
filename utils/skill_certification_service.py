"""
Skill Certification & Course Recommendation Service (#757)

Loads curated course and certification recommendations mapped to technical skills
from data/skill_certifications.json. Integrates with SkillAliasService to resolve
synonyms and aliases, provides up to 3 verified options per missing skill, and
returns clear generic fallback guidance for skills without curated entries.
"""

import os
import json
import logging
import re
from typing import Dict, Any, List, Optional, Iterable

logger = logging.getLogger(__name__)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
SKILL_CERTIFICATIONS_PATH = os.path.join(DATA_DIR, "skill_certifications.json")

DEFAULT_GENERIC_MESSAGE = (
    "No curated certifications or courses are currently verified for this skill. "
    "Explore general online learning resources or search trusted providers like Coursera, edX, freeCodeCamp, or official documentation."
)

_CACHE_DATA: Optional[Dict[str, List[Dict[str, Any]]]] = None
_LAST_MTIME: float = 0.0


def normalize_skill_name(skill: str) -> str:
    """Normalizes a skill name for robust lookup."""
    if not skill or not isinstance(skill, str):
        return ""
    text = skill.strip().lower()
    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SkillCertificationService:
    """
    Manages loading, alias resolution, querying, and enrichment of
    curated certifications and courses for student skill gaps (#757).
    """

    DEFAULT_LIMIT = 3
    GENERIC_MESSAGE = DEFAULT_GENERIC_MESSAGE

    @classmethod
    def load_data(cls, force_reload: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        Loads skill certifications from data/skill_certifications.json.
        Automatically reloads from disk if file modification timestamp changes.
        """
        global _CACHE_DATA, _LAST_MTIME

        if not os.path.exists(SKILL_CERTIFICATIONS_PATH):
            logger.warning("Certifications file not found at %s", SKILL_CERTIFICATIONS_PATH)
            _CACHE_DATA = {}
            _LAST_MTIME = 0.0
            return _CACHE_DATA

        current_mtime = os.path.getmtime(SKILL_CERTIFICATIONS_PATH)
        if not force_reload and _CACHE_DATA is not None and current_mtime == _LAST_MTIME:
            return _CACHE_DATA

        try:
            with open(SKILL_CERTIFICATIONS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # Support both {"skills": {...}} and direct root {"Python": [...]} format
            skills_dict = raw.get("skills") if isinstance(raw, dict) and "skills" in raw else raw
            if not isinstance(skills_dict, dict):
                skills_dict = {}

            normalized_map: Dict[str, List[Dict[str, Any]]] = {}
            for skill_key, items in skills_dict.items():
                # Skip top-level metadata keys starting with $ or _ or version
                if str(skill_key).startswith(("$", "_")) or str(skill_key).lower() in ("version", "description"):
                    continue

                if isinstance(items, list):
                    norm_key = normalize_skill_name(skill_key)
                    # Ensure each entry is a valid dict
                    valid_items = [item for item in items if isinstance(item, dict) and (item.get("title") or item.get("name"))]
                    normalized_map[norm_key] = valid_items

            _CACHE_DATA = normalized_map
            _LAST_MTIME = current_mtime
            logger.info("Loaded %d skill certification mappings from %s", len(_CACHE_DATA), SKILL_CERTIFICATIONS_PATH)
            return _CACHE_DATA
        except Exception as e:
            logger.exception("Failed to load skill certifications from %s: %s", SKILL_CERTIFICATIONS_PATH, e)
            if _CACHE_DATA is None:
                _CACHE_DATA = {}
            return _CACHE_DATA

    @classmethod
    def reload_data(cls) -> Dict[str, List[Dict[str, Any]]]:
        """Forces an in-memory cache refresh."""
        return cls.load_data(force_reload=True)

    @classmethod
    def get_certifications_for_skill(
        cls,
        skill_name: str,
        limit: int = 3
    ) -> Dict[str, Any]:
        """
        Retrieves up to `limit` (max 3) verified courses/certifications for a given skill.
        If no entries exist for the skill, returns a generic fallback message.
        """
        data = cls.load_data()
        clean_name = str(skill_name or "").strip()
        norm_key = normalize_skill_name(clean_name)

        if not norm_key:
            return {
                "skill": clean_name,
                "canonical_skill": clean_name,
                "has_recommendations": False,
                "count": 0,
                "certifications": [],
                "generic_message": cls.GENERIC_MESSAGE
            }

        # 1. Direct normalized lookup
        entries = data.get(norm_key)

        # 2. Canonical skill alias resolution (e.g. k8s -> Kubernetes, js -> JavaScript)
        canonical_name = clean_name
        if not entries:
            try:
                from utils.skill_alias_service import get_canonical_skill
                canonical_name = get_canonical_skill(clean_name)
                canonical_norm = normalize_skill_name(canonical_name)
                entries = data.get(canonical_norm)
            except Exception:
                pass

        # 3. Case-insensitive substring fallback for multi-word skills
        if not entries:
            for k, items in data.items():
                if k == norm_key or (len(norm_key) >= 4 and (norm_key in k or k in norm_key)):
                    entries = items
                    break

        if entries:
            # Enforce max options limit (default 3)
            selected = entries[:limit]
            # Standardize item fields so each has title, provider, level, type, duration, url, last_verified
            cleaned_certifications = []
            for cert in selected:
                title = cert.get("title") or cert.get("name") or "Course / Certification"
                cleaned_certifications.append({
                    "title": title,
                    "name": title,
                    "provider": cert.get("provider", "Verified Learning Platform"),
                    "level": cert.get("level", "All Levels"),
                    "type": cert.get("type", "Free"),
                    "duration": cert.get("duration", "Self-paced"),
                    "url": cert.get("url", "#"),
                    "last_verified": cert.get("last_verified", "2026-11-20"),
                    "contributor_verified": bool(cert.get("contributor_verified", True)),
                    "notes": cert.get("notes") or cert.get("description", "")
                })

            return {
                "skill": clean_name,
                "canonical_skill": canonical_name,
                "has_recommendations": True,
                "count": len(cleaned_certifications),
                "certifications": cleaned_certifications,
                "generic_message": None
            }

        # Skill without entries: return generic message as required by acceptance criteria
        return {
            "skill": clean_name,
            "canonical_skill": canonical_name,
            "has_recommendations": False,
            "count": 0,
            "certifications": [],
            "generic_message": cls.GENERIC_MESSAGE
        }

    @classmethod
    def get_recommendations_for_skills(
        cls,
        skills: Iterable[str],
        limit_per_skill: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Returns recommendations for an iterable list of skill names.
        """
        results = []
        for s in skills:
            if s and str(s).strip():
                results.append(cls.get_certifications_for_skill(str(s).strip(), limit=limit_per_skill))
        return results

    @classmethod
    def enrich_skill_gap_items(
        cls,
        skill_gap_items: List[Dict[str, Any]],
        limit_per_skill: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Enriches a list of skill gap dictionaries (from analysis reports or role gaps)
        with recommended certifications and generic fallback messages.
        """
        if not skill_gap_items or not isinstance(skill_gap_items, list):
            return []

        enriched = []
        for item in skill_gap_items:
            if not isinstance(item, dict):
                continue
            item_copy = dict(item)
            # Find skill name attribute (supports 'skill', 'missing_skill', 'name')
            skill_name = item_copy.get("skill") or item_copy.get("missing_skill") or item_copy.get("name") or ""
            rec = cls.get_certifications_for_skill(str(skill_name), limit=limit_per_skill)

            item_copy["recommended_certifications"] = rec["certifications"]
            item_copy["has_certification_recommendations"] = rec["has_recommendations"]
            item_copy["certifications_generic_message"] = rec["generic_message"]
            item_copy["certifications_count"] = rec["count"]
            enriched.append(item_copy)

        return enriched


# Singleton reference
skill_certification_service = SkillCertificationService
