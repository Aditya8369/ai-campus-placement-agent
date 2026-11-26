"""
Learning Resources Catalog Validator & Loader (#885)
=====================================================
Validates data/learning_resources.json against its JSON schema and provides
functions to query and match resources against student skill gaps and roadmap steps.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESOURCES_FILE = DATA_DIR / "learning_resources.json"
SCHEMA_FILE = DATA_DIR / "schemas" / "learning_resources.schema.json"

ALLOWED_TYPES = {"course", "interactive", "documentation", "video", "book", "tutorial"}
VALID_STATUSES = {"not_started", "started", "done"}


class LearningResourceValidationError(Exception):
    """Raised when learning_resources.json fails schema or link validation."""
    def __init__(
        self,
        message: str,
        skill: Optional[str] = None,
        resource_id: Optional[str] = None,
        field: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.skill = skill
        self.resource_id = resource_id
        self.field = field


def _validate_single_resource(skill: str, idx: int, item: Any, seen_ids: set) -> List[str]:
    """Validates individual resource attributes."""
    errors: List[str] = []
    if not isinstance(item, dict):
        return [f"Skill '{skill}' resource #{idx + 1} must be a dictionary."]

    r_id = item.get("id")
    title = item.get("title")
    link = item.get("link")
    r_type = item.get("type")
    hours = item.get("estimated_hours")
    note = item.get("review_note")

    # Check ID
    if not r_id or not isinstance(r_id, str) or not re.match(r"^[a-z0-9_-]+$", r_id):
        errors.append(f"Skill '{skill}' resource #{idx + 1}: Invalid or missing 'id' (must match ^[a-z0-9_-]+$).")
    elif r_id in seen_ids:
        errors.append(f"Duplicate resource id '{r_id}' found in skill '{skill}'.")
    else:
        seen_ids.add(r_id)

    # Check Title
    if not title or not isinstance(title, str) or len(title.strip()) < 3:
        errors.append(f"Skill '{skill}' resource '{r_id}': 'title' must be at least 3 characters.")

    # Check Link
    if not link or not isinstance(link, str) or not link.startswith("https://"):
        errors.append(f"Skill '{skill}' resource '{r_id}': 'link' must start with https://.")

    # Check Type
    if r_type not in ALLOWED_TYPES:
        errors.append(f"Skill '{skill}' resource '{r_id}': Invalid 'type' '{r_type}'. Allowed: {sorted(ALLOWED_TYPES)}.")

    # Check Estimated Hours
    if not isinstance(hours, (int, float)) or hours <= 0:
        errors.append(f"Skill '{skill}' resource '{r_id}': 'estimated_hours' must be a positive number.")

    # Check Review Note
    if not note or not isinstance(note, str) or len(note.strip()) < 10:
        errors.append(f"Skill '{skill}' resource '{r_id}': 'review_note' must be at least 10 characters.")

    return errors


def validate_learning_resources_data(data: Dict[str, Any]) -> List[str]:
    """
    Validates learning resources data against the schema requirements.
    """
    errors: List[str] = []

    if not isinstance(data, dict):
        return ["Root must be a JSON object"]

    if "version" not in data or not isinstance(data["version"], str):
        errors.append("Missing or invalid 'version' field (must be string).")

    resources = data.get("resources")
    if not isinstance(resources, dict) or len(resources) == 0:
        errors.append("'resources' must be a non-empty dictionary of skill mappings.")
        return errors

    seen_ids = set()

    for skill, item_list in resources.items():
        if not isinstance(skill, str) or not skill.strip():
            errors.append(f"Invalid skill name '{skill}'.")
            continue

        if not isinstance(item_list, list) or len(item_list) == 0:
            errors.append(f"Skill '{skill}' must contain a non-empty list of learning resources.")
            continue

        for idx, item in enumerate(item_list):
            errors.extend(_validate_single_resource(skill, idx, item, seen_ids))

    return errors


def load_learning_resources() -> Dict[str, List[Dict[str, Any]]]:
    """
    Loads and caches curated learning resources from data/learning_resources.json.
    """
    if not RESOURCES_FILE.exists():
        logger.warning(f"Learning resources file not found at {RESOURCES_FILE}")
        return {}

    try:
        with open(RESOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        errors = validate_learning_resources_data(data)
        if errors:
            logger.error(f"Validation errors in {RESOURCES_FILE}: {errors}")
            return {}
        return data.get("resources", {})
    except Exception as e:
        logger.exception(f"Error loading {RESOURCES_FILE}: {e}")
        return {}


def get_resources_for_skill(skill_name: str) -> List[Dict[str, Any]]:
    """
    Returns curated free resources for a given skill name, with alias resolution.
    Returns empty list if skill is not present in the catalog.
    """
    if not skill_name or not isinstance(skill_name, str):
        return []

    clean_name = skill_name.strip()
    catalog = load_learning_resources()

    # 1. Exact match (case-insensitive)
    for k, res_list in catalog.items():
        if k.lower() == clean_name.lower():
            return res_list

    # 2. Canonical skill alias match
    try:
        from utils.skill_alias_service import get_canonical_skill
        canonical = get_canonical_skill(clean_name)
        if canonical:
            for k, res_list in catalog.items():
                if k.lower() == canonical.lower():
                    return res_list
    except Exception:
        pass

    # 3. Substring matching for multi-word or compound skills
    clean_lower = clean_name.lower()
    for k, res_list in catalog.items():
        k_lower = k.lower()
        if (len(k_lower) >= 4 and k_lower in clean_lower) or (len(clean_lower) >= 4 and clean_lower in k_lower):
            return res_list

    return []


# ==============================================================================
# Database User Progress Tracking
# ==============================================================================

def get_db_connection() -> sqlite3.Connection:
    """Returns database connection based on config.DATABASE_PATH."""
    import config
    db_path = config.DATABASE_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_resource_progress(user_id: str) -> Dict[str, str]:
    """
    Returns a dictionary mapping resource_id -> status ('not_started', 'started', 'done')
    for the specified user.
    """
    if not user_id:
        return {}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT resource_id, status FROM student_learning_resource_progress WHERE user_id = ?",
            (user_id,),
        )
        rows = cur.fetchall()
        return {row["resource_id"]: row["status"] for row in rows}
    except Exception as e:
        logger.warning(f"Error fetching user resource progress for {user_id}: {e}")
        return {}
    finally:
        conn.close()


def set_user_resource_progress(user_id: str, resource_id: str, status: str, skill_name: str = "") -> Dict[str, Any]:
    """
    Updates or inserts a student's progress for a learning resource ('started', 'done', or 'not_started').
    """
    if not user_id:
        raise ValueError("user_id is required")
    if not resource_id:
        raise ValueError("resource_id is required")

    clean_status = status.lower().strip()
    if clean_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        rec_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO student_learning_resource_progress (id, user_id, resource_id, skill_name, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, resource_id) DO UPDATE SET
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (rec_id, user_id, resource_id, skill_name, clean_status),
        )
        conn.commit()
        return {
            "success": True,
            "user_id": user_id,
            "resource_id": resource_id,
            "status": clean_status,
        }
    except Exception as e:
        conn.rollback()
        logger.exception(f"Error updating resource progress for {user_id}/{resource_id}: {e}")
        raise
    finally:
        conn.close()


def enrich_items_with_resources(items: List[Dict[str, Any]], user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Enriches a list of skill gap or roadmap items with matching curated learning resources
    and the user's progress status for each resource.
    """
    if not items or not isinstance(items, list):
        return []

    user_progress = get_user_resource_progress(user_id) if user_id else {}

    enriched = []
    for item in items:
        if not isinstance(item, dict):
            enriched.append(item)
            continue

        item_copy = dict(item)
        skill_name = item_copy.get("skill") or item_copy.get("missing_skill") or item_copy.get("name") or ""
        resources = get_resources_for_skill(str(skill_name))

        res_with_progress = []
        for r in resources:
            r_copy = dict(r)
            r_copy["status"] = user_progress.get(r["id"], "not_started")
            res_with_progress.append(r_copy)

        item_copy["curated_learning_resources"] = res_with_progress
        item_copy["has_curated_resources"] = len(res_with_progress) > 0
        enriched.append(item_copy)

    return enriched
