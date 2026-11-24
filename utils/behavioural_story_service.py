"""
Behavioural Story Bank Service (#687).
======================================
Enables students to record, refine, and organize STAR (Situation, Task, Action, Result)
stories linked to core competency tags (teamwork, leadership, problem solving, failure, initiative).

Key Features:
1. Ownership & Privacy:
   - Each story is strictly private to the student who created it.
   - Cross-user retrieval, editing, and deletion are strictly prevented.
2. Completeness & Length Intelligence:
   - Evaluates which of the 4 STAR components (Situation, Task, Action, Result) are filled.
   - Computes live word counts and provides guidance against the recommended 150-300 word benchmark.
3. Interview Integration & Tag Matching:
   - Detects competency keywords in behavioural interview questions.
   - Matches candidate stories by competency tags to serve as memory prompts during live practice.
   - Strictly acts as a prompt/reference (never automatically submitted or pasted).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Standard core competency tags recommended for placement behavioural rounds
CORE_COMPETENCY_TAGS: List[str] = [
    "teamwork",
    "leadership",
    "problem solving",
    "failure",
    "initiative",
]

# Keyword patterns to detect competencies from interview question prompts
COMPETENCY_KEYWORD_PATTERNS: Dict[str, re.Pattern] = {
    "teamwork": re.compile(
        r"\b(team|teammate|teammates|collaborat\w*|group|peer|peers|cross-functional|disagree\w*|conflict\w*|compromis\w*)\b",
        re.I,
    ),
    "leadership": re.compile(
        r"\b(lead|leader|leadership|leading|led|guid\w*|mentor\w*|direction|drove|champion\w*|ownership|delegat\w*|persuad\w*)\b",
        re.I,
    ),
    "problem solving": re.compile(
        r"\b(problem|solve|solving|solved|troubleshoot\w*|debug\w*|obstacle|hurdle|challenge|challenging|complex|analytical|creative solution)\b",
        re.I,
    ),
    "failure": re.compile(
        r"\b(fail|failed|failure|failing|mistake|error|wrong|regret|setback|missed deadline|didn't go as planned|flaw)\b",
        re.I,
    ),
    "initiative": re.compile(
        r"\b(initiative|proactive|self-starter|without being asked|innovat\w*|volunteer\w*|went beyond|unprompted|opportunity)\b",
        re.I,
    ),
}


def normalize_tag(tag: str) -> str:
    """Normalizes a competency tag string."""
    cleaned = (tag or "").strip().lower()
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    return cleaned


def normalize_tags_list(tags_input: Any) -> List[str]:
    """Parses and normalizes a list or comma-separated string of tags."""
    if isinstance(tags_input, list):
        raw_list = tags_input
    elif isinstance(tags_input, str):
        # Could be JSON string or comma-separated
        stripped = tags_input.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                raw_list = json.loads(stripped)
            except Exception:
                raw_list = [t.strip() for t in stripped[1:-1].split(",")]
        else:
            raw_list = [t.strip() for t in stripped.split(",")]
    else:
        raw_list = []

    seen: Set[str] = set()
    result: List[str] = []
    for item in raw_list:
        norm = normalize_tag(str(item))
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def calculate_completeness(situation: str, task: str, action: str, result: str) -> Dict[str, Any]:
    """
    Evaluates which STAR components are filled and returns a completeness breakdown.
    """
    s_filled = bool(situation and situation.strip())
    t_filled = bool(task and task.strip())
    a_filled = bool(action and action.strip())
    r_filled = bool(result and result.strip())

    filled_count = sum([s_filled, t_filled, a_filled, r_filled])
    percent = int((filled_count / 4) * 100)

    if filled_count == 4:
        status = "Complete"
    elif filled_count > 0:
        status = "In Progress"
    else:
        status = "Empty"

    return {
        "score": filled_count,
        "max_score": 4,
        "percent": percent,
        "status": status,
        "is_complete": filled_count == 4,
        "situation_filled": s_filled,
        "task_filled": t_filled,
        "action_filled": a_filled,
        "result_filled": r_filled,
        "filled_parts": [
            part
            for part, filled in [
                ("situation", s_filled),
                ("task", t_filled),
                ("action", a_filled),
                ("result", r_filled),
            ]
            if filled
        ],
        "missing_parts": [
            part
            for part, filled in [
                ("situation", s_filled),
                ("task", t_filled),
                ("action", a_filled),
                ("result", r_filled),
            ]
            if not filled
        ],
    }


def calculate_word_count(situation: str, task: str, action: str, result: str) -> Dict[str, Any]:
    """
    Calculates word count per section and evaluates against the 150-300 word benchmark.
    """
    s_words = len((situation or "").split())
    t_words = len((task or "").split())
    a_words = len((action or "").split())
    r_words = len((result or "").split())
    total = s_words + t_words + a_words + r_words

    if total == 0:
        assessment = "Empty"
        guidance = "Write your story across Situation, Task, Action, and Result."
    elif total < 80:
        assessment = "Brief"
        guidance = "Brief outline. Aim for 150-300 words with specific actions & metrics."
    elif total < 150:
        assessment = "Developing"
        guidance = "Good start. Add measurable results and specific tools/decisions."
    elif total <= 300:
        assessment = "Ideal"
        guidance = "Ideal length! Structured for a natural 2-minute interview answer."
    else:
        assessment = "Detailed"
        guidance = "Comprehensive story. Keep key points highlighted for quick recall."

    return {
        "situation_words": s_words,
        "task_words": t_words,
        "action_words": a_words,
        "result_words": r_words,
        "total_words": total,
        "suggested_min": 150,
        "suggested_max": 300,
        "assessment": assessment,
        "guidance": guidance,
        "is_ideal": 150 <= total <= 300,
    }


class BehaviouralStoryService:
    """Service for managing private student STAR stories and matching them to interview prompts."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Ensures the student_behavioural_stories SQLite table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_behavioural_stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id TEXT UNIQUE NOT NULL,
                student_id TEXT NOT NULL,
                title TEXT NOT NULL,
                situation TEXT,
                task TEXT,
                action TEXT,
                result TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stories_student
            ON student_behavioural_stories(student_id)
            """
        )
        conn.commit()
        conn.close()

    def _format_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Formats a database row into a structured story dictionary."""
        situation = row["situation"] or ""
        task = row["task"] or ""
        action = row["action"] or ""
        result = row["result"] or ""

        try:
            tags = json.loads(row["tags"] or "[]")
        except Exception:
            tags = []

        completeness = calculate_completeness(situation, task, action, result)
        word_count = calculate_word_count(situation, task, action, result)

        return {
            "story_id": row["story_id"],
            "student_id": row["student_id"],
            "title": row["title"],
            "situation": situation,
            "task": task,
            "action": action,
            "result": result,
            "tags": tags,
            "completeness": completeness,
            "word_count": word_count,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_story(
        self,
        student_id: str,
        title: str,
        situation: str = "",
        task: str = "",
        action: str = "",
        result: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Creates a new STAR story owned exclusively by student_id."""
        cleaned_student_id = (student_id or "").strip()
        if not cleaned_student_id:
            raise ValueError("Student ID is required.")

        cleaned_title = (title or "").strip()
        if not cleaned_title:
            raise ValueError("Story title is required.")

        story_id = f"story-{uuid.uuid4().hex[:12]}"
        normalized_tags = normalize_tags_list(tags or [])
        tags_json = json.dumps(normalized_tags)
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO student_behavioural_stories
            (story_id, student_id, title, situation, task, action, result, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                cleaned_student_id,
                cleaned_title,
                (situation or "").strip(),
                (task or "").strip(),
                (action or "").strip(),
                (result or "").strip(),
                tags_json,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
        conn.close()

        story = self.get_story(story_id, cleaned_student_id)
        if not story:
            raise RuntimeError("Failed to retrieve created story.")
        return story

    def get_story(self, story_id: str, student_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a story by ID strictly ensuring it belongs to student_id."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM student_behavioural_stories
            WHERE story_id = ? AND student_id = ?
            """,
            (story_id, student_id),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None
        return self._format_row(row)

    def update_story(
        self,
        story_id: str,
        student_id: str,
        title: Optional[str] = None,
        situation: Optional[str] = None,
        task: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates a story owned strictly by student_id."""
        existing = self.get_story(story_id, student_id)
        if not existing:
            return None

        new_title = (title if title is not None else existing["title"]).strip()
        if not new_title:
            raise ValueError("Story title cannot be empty.")

        new_situation = (situation if situation is not None else existing["situation"]).strip()
        new_task = (task if task is not None else existing["task"]).strip()
        new_action = (action if action is not None else existing["action"]).strip()
        new_result = (result if result is not None else existing["result"]).strip()

        if tags is not None:
            new_tags = normalize_tags_list(tags)
        else:
            new_tags = existing["tags"]
        tags_json = json.dumps(new_tags)
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE student_behavioural_stories
            SET title = ?, situation = ?, task = ?, action = ?, result = ?, tags = ?, updated_at = ?
            WHERE story_id = ? AND student_id = ?
            """,
            (
                new_title,
                new_situation,
                new_task,
                new_action,
                new_result,
                tags_json,
                now_iso,
                story_id,
                student_id,
            ),
        )
        conn.commit()
        conn.close()

        return self.get_story(story_id, student_id)

    def delete_story(self, story_id: str, student_id: str) -> bool:
        """Deletes a story owned strictly by student_id."""
        existing = self.get_story(story_id, student_id)
        if not existing:
            return False

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM student_behavioural_stories
            WHERE story_id = ? AND student_id = ?
            """,
            (story_id, student_id),
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def list_stories(
        self,
        student_id: str,
        tag_filter: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lists all stories belonging to student_id, with optional tag filtering and search."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM student_behavioural_stories
            WHERE student_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (student_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        stories = [self._format_row(row) for row in rows]

        if tag_filter:
            norm_tag = normalize_tag(tag_filter)
            stories = [s for s in stories if norm_tag in s["tags"]]

        if search_query:
            query = search_query.strip().lower()
            stories = [
                s
                for s in stories
                if query in s["title"].lower()
                or query in s["situation"].lower()
                or query in s["task"].lower()
                or query in s["action"].lower()
                or query in s["result"].lower()
                or any(query in t for t in s["tags"])
            ]

        return stories

    def get_student_story_stats(self, student_id: str) -> Dict[str, Any]:
        """Calculates story bank metrics for student dashboard/overview."""
        stories = self.list_stories(student_id)
        total = len(stories)
        complete = sum(1 for s in stories if s["completeness"]["is_complete"])
        in_progress = total - complete

        covered_tags: Set[str] = set()
        for s in stories:
            covered_tags.update(s["tags"])

        core_covered = [t for t in CORE_COMPETENCY_TAGS if t in covered_tags]
        core_missing = [t for t in CORE_COMPETENCY_TAGS if t not in covered_tags]

        return {
            "total_stories": total,
            "target_stories": 5,
            "complete_stories": complete,
            "in_progress_stories": in_progress,
            "covered_tags": sorted(list(covered_tags)),
            "core_covered": core_covered,
            "core_missing": core_missing,
            "core_coverage_percent": int((len(core_covered) / len(CORE_COMPETENCY_TAGS)) * 100),
        }

    def detect_question_competencies(self, question_text: str) -> List[str]:
        """Detects relevant competency tags matching an interview question string."""
        if not question_text:
            return []

        detected: List[str] = []
        for competency, pattern in COMPETENCY_KEYWORD_PATTERNS.items():
            if pattern.search(question_text):
                detected.append(competency)

        return detected

    def match_stories_for_question(
        self,
        student_id: str,
        question_text: str,
        question_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Matches a student's STAR stories against an interview question.
        Returns stories sorted by relevance (matched competency tags first).
        """
        stories = self.list_stories(student_id)
        if not stories:
            return []

        detected_competencies = self.detect_question_competencies(question_text)

        ranked_stories: List[Dict[str, Any]] = []
        for story in stories:
            story_tags = set(story["tags"])
            # Overlap with detected question competencies
            matched_tags = [t for t in detected_competencies if t in story_tags]

            # Direct word match against custom tags
            q_lower = (question_text or "").lower()
            for tag in story_tags:
                if tag not in matched_tags and tag in q_lower:
                    matched_tags.append(tag)

            relevance_score = len(matched_tags) * 10
            if story["completeness"]["is_complete"]:
                relevance_score += 2

            ranked_stories.append({
                "story": story,
                "matched_tags": matched_tags,
                "relevance_score": relevance_score,
                "is_match": len(matched_tags) > 0,
            })

        # Sort: matched first, then highest relevance score, then complete stories
        ranked_stories.sort(
            key=lambda x: (
                1 if x["is_match"] else 0,
                x["relevance_score"],
                1 if x["story"]["completeness"]["is_complete"] else 0,
            ),
            reverse=True,
        )

        return ranked_stories


# Singleton service instance
behavioural_story_service = BehaviouralStoryService()
