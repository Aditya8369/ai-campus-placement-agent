"""
Interview Question Bank Service (#759)
======================================
Provides searchable, filterable access to common campus placement interview questions.
Questions are categorized by HR, Technical, Behavioral, and Projects, and tagged
by difficulty and target role.

Key Guarantees:
- New questions can be added through the JSON data file only, with zero code changes.
- Search query and tag/category/difficulty/role filters work together seamlessly.
- Each question provides a short answer outline and coaching takeaways.
- Supports marking and exporting session favorites as formatted text lists.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "interview_questions.json"


class QuestionBankService:
    """Manages the interview question bank dataset, filtering, and favorites formatting."""

    def __init__(self, data_path: Optional[str] = None):
        self.data_path = Path(data_path) if data_path else DEFAULT_DATA_PATH
        self._cached_questions: Optional[List[Dict[str, Any]]] = None
        self._cached_mtime: float = 0.0

    def _should_reload(self) -> bool:
        if self._cached_questions is None:
            return True
        try:
            current_mtime = os.path.getmtime(self.data_path)
            return current_mtime > self._cached_mtime
        except Exception:
            return False

    def load_questions(self, force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        Loads all questions from the JSON data file.
        Automatically reloads if the file has been modified on disk, ensuring
        new questions added to the JSON file are available without restart.
        """
        if not force_reload and not self._should_reload() and self._cached_questions is not None:
            return self._cached_questions

        if not self.data_path.exists():
            logger.warning(f"Question bank data file not found at {self.data_path}")
            self._cached_questions = []
            return []

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.error(f"Expected list in {self.data_path}, got {type(data)}")
                data = []

            self._cached_questions = data
            try:
                self._cached_mtime = os.path.getmtime(self.data_path)
            except Exception:
                self._cached_mtime = 0.0

            logger.info(f"Loaded {len(data)} interview questions from {self.data_path}")
            return self._cached_questions
        except Exception as err:
            logger.error(f"Failed to load interview questions from {self.data_path}: {err}")
            return self._cached_questions or []

    def get_all_questions(self) -> List[Dict[str, Any]]:
        """Returns the full list of interview questions."""
        return self.load_questions()

    def get_question_by_id(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Looks up a specific interview question by its unique ID."""
        questions = self.load_questions()
        for q in questions:
            if q.get("id") == question_id:
                return q
        return None

    def search_and_filter(
        self,
        query: str = "",
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        role: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Searches and filters questions simultaneously.
        Guarantees that search queries and all active filters combine (AND logic).
        """
        questions = self.load_questions()
        results: List[Dict[str, Any]] = []

        norm_query = query.strip().lower() if query else ""
        norm_cat = category.strip().lower() if category and category.lower() != "all" else None
        norm_diff = difficulty.strip().lower() if difficulty and difficulty.lower() != "all" else None
        norm_role = role.strip().lower() if role and role.lower() != "all" else None
        norm_tag = tag.strip().lower() if tag and tag.lower() != "all" else None

        for item in questions:
            # 1. Category Filter
            item_cat = str(item.get("category", "")).strip().lower()
            if norm_cat and item_cat != norm_cat:
                continue

            # 2. Difficulty Filter
            item_diff = str(item.get("difficulty", "")).strip().lower()
            if norm_diff and item_diff != norm_diff:
                continue

            # 3. Role Filter
            item_roles = [str(r).strip().lower() for r in item.get("roles", [])]
            if norm_role:
                # Matches if the role is explicitly listed or if 'all roles' is present
                role_match = any(norm_role in r or r in norm_role for r in item_roles)
                if not role_match and "all roles" not in item_roles:
                    continue

            # 4. Tag Filter
            item_tags = [str(t).strip().lower() for r in item.get("tags", []) for t in [r]]
            if norm_tag:
                tag_match = any(norm_tag in t for t in item_tags)
                if not tag_match:
                    continue

            # 5. Text Search (question text, tags, roles, outline points, takeaway)
            if norm_query:
                q_text = str(item.get("question", "")).lower()
                outline_text = " ".join([str(o).lower() for o in item.get("short_answer_outline", [])])
                takeaway_text = str(item.get("key_takeaway", "")).lower()
                all_tags_text = " ".join(item_tags)
                all_roles_text = " ".join(item_roles)

                search_corpus = f"{q_text} {outline_text} {takeaway_text} {all_tags_text} {all_roles_text}"

                # Query tokens: all tokens should be present (AND logic for search terms)
                tokens = [t for t in norm_query.split() if t]
                if not all(token in search_corpus for token in tokens):
                    continue

            results.append(item)

        return results

    def get_filter_options(self) -> Dict[str, Any]:
        """
        Dynamically extracts available categories, difficulties, roles, and top tags
        from the current dataset so frontend filter dropdowns stay in sync with the JSON file.
        """
        questions = self.load_questions()
        categories: Set[str] = set()
        difficulties: Set[str] = set()
        roles: Set[str] = set()
        tags_set: Set[str] = set()

        for q in questions:
            if q.get("category"):
                categories.add(str(q["category"]).strip().lower())
            if q.get("difficulty"):
                difficulties.add(str(q["difficulty"]).strip().capitalize())
            for r in q.get("roles", []):
                if r:
                    roles.add(str(r).strip())
            for t in q.get("tags", []):
                if t:
                    tags_set.add(str(t).strip())

        # Sort difficulties in logical order: Easy, Medium, Hard
        diff_order = {"Easy": 1, "Medium": 2, "Hard": 3}
        sorted_diffs = sorted(list(difficulties), key=lambda d: diff_order.get(d, 99))

        return {
            "categories": sorted(list(categories)),
            "difficulties": sorted_diffs,
            "roles": sorted(list(roles)),
            "tags": sorted(list(tags_set)),
            "total_questions": len(questions)
        }

    def format_favorites_as_text(self, favorite_ids: List[str], include_outlines: bool = True) -> str:
        """
        Formats a list of favorited questions into an organized text/markdown string
        ready to be copied to the student's clipboard or saved into study notes.
        """
        if not favorite_ids:
            return "No interview questions currently selected as favorites."

        questions = self.load_questions()
        q_map = {q.get("id"): q for q in questions if q.get("id")}

        lines = [
            f"# My Favorite Interview Questions ({len(favorite_ids)} Saved)",
            "",
            "Review this personalized question bank before your campus placement drives.",
            ""
        ]

        count = 1
        for fid in favorite_ids:
            item = q_map.get(fid)
            if not item:
                continue

            cat = str(item.get("category", "")).upper()
            diff = str(item.get("difficulty", "Medium"))
            q_text = item.get("question", "")
            roles_str = ", ".join(item.get("roles", []))
            tags_str = ", ".join(item.get("tags", []))

            lines.append(f"### {count}. [{cat} | {diff}] {q_text}")
            if roles_str:
                lines.append(f"- **Target Roles**: {roles_str}")
            if tags_str:
                lines.append(f"- **Tags**: {tags_str}")

            if include_outlines and item.get("short_answer_outline"):
                lines.append("- **Short Answer Outline**:")
                for bullet in item["short_answer_outline"]:
                    lines.append(f"  * {bullet}")

            if item.get("key_takeaway"):
                lines.append(f"- **Key Takeaway**: {item['key_takeaway']}")

            lines.append("")
            count += 1

        return "\n".join(lines).strip()


# Global singleton instance
question_bank_service = QuestionBankService()
