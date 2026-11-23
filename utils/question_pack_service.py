"""
Custom interview question pack builder service (#611).
Enables candidates to create, curate, order, and practice custom sets of interview questions.
Packs are stored securely and remain private to the authenticated candidate.
"""

import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from db.connection import get_db_connection

def init_question_packs_table():
    """Initializes the database table for custom question packs."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_question_packs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'general',
                difficulty TEXT DEFAULT 'intermediate',
                questions_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()

init_question_packs_table()

def create_question_pack(
    user_id: str,
    title: str,
    questions: List[Dict[str, Any]],
    description: str = "",
    category: str = "general",
    difficulty: str = "intermediate"
) -> Dict[str, Any]:
    """Creates a new custom question pack for the user."""
    if not user_id or not title or not title.strip():
        return {"success": False, "error": "User ID and Title are required"}

    if not questions or not isinstance(questions, list) or len(questions) == 0:
        return {"success": False, "error": "At least one question is required to build a pack"}

    # Validate and normalize questions list
    formatted_questions = []
    for idx, q in enumerate(questions):
        if isinstance(q, str):
            q_text = q.strip()
            if q_text:
                formatted_questions.append({
                    "id": f"q-{idx+1}",
                    "order": idx + 1,
                    "text": q_text,
                    "type": "technical"
                })
        elif isinstance(q, dict):
            q_text = q.get("text", "").strip()
            if q_text:
                formatted_questions.append({
                    "id": q.get("id") or f"q-{idx+1}",
                    "order": q.get("order", idx + 1),
                    "text": q_text,
                    "type": q.get("type", "technical")
                })

    if not formatted_questions:
        return {"success": False, "error": "Pack must contain non-empty questions"}

    pack_id = str(uuid.uuid4())
    now_str = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO custom_question_packs (id, user_id, title, description, category, difficulty, questions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pack_id,
            user_id,
            title.strip(),
            description.strip() if description else "",
            category.lower().strip() if category else "general",
            difficulty.lower().strip() if difficulty else "intermediate",
            json.dumps(formatted_questions),
            now_str,
            now_str
        ))
        conn.commit()

    return {
        "success": True,
        "pack": {
            "id": pack_id,
            "user_id": user_id,
            "title": title.strip(),
            "description": description,
            "category": category,
            "difficulty": difficulty,
            "questions_count": len(formatted_questions),
            "questions": formatted_questions,
            "created_at": now_str,
            "updated_at": now_str
        }
    }

def get_user_question_packs(user_id: str) -> List[Dict[str, Any]]:
    """Retrieves all custom packs belonging to the given user."""
    if not user_id:
        return []

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, title, description, category, difficulty, questions_json, created_at, updated_at
            FROM custom_question_packs
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        rows = cursor.fetchall()

    packs = []
    for r in rows:
        try:
            questions = json.loads(r["questions_json"])
        except Exception:
            questions = []
        packs.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "title": r["title"],
            "description": r["description"],
            "category": r["category"],
            "difficulty": r["difficulty"],
            "questions_count": len(questions),
            "questions": questions,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"]
        })
    return packs

def get_question_pack_by_id(pack_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a specific question pack, enforcing privacy to the user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, title, description, category, difficulty, questions_json, created_at, updated_at
            FROM custom_question_packs
            WHERE id = ? AND user_id = ?
        """, (pack_id, user_id))
        row = cursor.fetchone()

    if not row:
        return None

    try:
        questions = json.loads(row["questions_json"])
    except Exception:
        questions = []

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "difficulty": row["difficulty"],
        "questions_count": len(questions),
        "questions": questions,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

def delete_question_pack(pack_id: str, user_id: str) -> bool:
    """Deletes a question pack owned by the user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM custom_question_packs
            WHERE id = ? AND user_id = ?
        """, (pack_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
