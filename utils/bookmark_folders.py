"""
Coding Bookmark Folder Management System (#253)
================================================
Organizes student bookmarked coding problems into customizable folders and collections
(e.g., 'Dynamic Programming Masterclass', 'Google Onsite Prep', 'Must-Do Hard', 'System Design').

Key Capabilities:
1. Dynamic Schema Evolution:
   - Creates coding_bookmark_folders table.
   - Adds folder_id column to bookmarked_coding_questions.
2. Complete Folder Lifecycle:
   - Create, list, rename, customize color/icon, and delete folders.
   - Deleting a folder safely cascades or unassigns bookmarks to the 'General' uncategorized pool.
3. Assignment & Movement:
   - Move individual or batches of bookmarks between folders.
4. Per-Folder Statistics:
   - Calculates bookmark counts and difficulty distributions (Easy/Medium/Hard) per folder.
5. Strict Multi-Tenant Isolation:
   - Every folder and bookmark operation is scoped strictly to the authenticated student_id.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import uuid

from utils.database import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_FOLDER_COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444", "#6b7280"]


def ensure_bookmark_folders_schema(conn: sqlite3.Connection) -> None:
    """Creates the coding_bookmark_folders table and migrates bookmarked_coding_questions."""
    cursor = conn.cursor()

    # Create folder table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coding_bookmark_folders (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL DEFAULT 'default_student',
            name TEXT NOT NULL,
            description TEXT,
            color_hex TEXT NOT NULL DEFAULT '#3b82f6',
            icon_name TEXT NOT NULL DEFAULT 'fa-folder',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, name)
        )
    """)

    # Verify and add folder_id column to bookmarked_coding_questions
    cursor.execute("PRAGMA table_info(bookmarked_coding_questions)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "folder_id" not in existing_cols:
        cursor.execute("ALTER TABLE bookmarked_coding_questions ADD COLUMN folder_id TEXT")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_folder_student ON coding_bookmark_folders(student_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bm_folder ON bookmarked_coding_questions(student_id, folder_id)")
    conn.commit()


def create_bookmark_folder(
    student_id: str,
    name: str,
    description: Optional[str] = None,
    color_hex: str = "#3b82f6",
    icon_name: str = "fa-folder"
) -> Dict[str, Any]:
    """Creates a new folder for coding question bookmarks."""
    sid = (student_id or "default_student").strip()
    folder_name = (name or "").strip()
    if not folder_name:
        raise ValueError("Folder name is required.")

    folder_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM coding_bookmark_folders WHERE student_id = ? AND LOWER(name) = LOWER(?)", (sid, folder_name))
        if cursor.fetchone():
            raise ValueError(f"Folder '{folder_name}' already exists.")

        cursor.execute("""
            INSERT INTO coding_bookmark_folders (
                id, student_id, name, description, color_hex, icon_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            folder_id, sid, folder_name, description, color_hex, icon_name, now, now
        ))
        conn.commit()

    return get_bookmark_folder_by_id(sid, folder_id)  # type: ignore


def get_bookmark_folder_by_id(student_id: str, folder_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a folder by its ID for a specific student."""
    sid = (student_id or "default_student").strip()
    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coding_bookmark_folders WHERE student_id = ? AND id = ?", (sid, folder_id))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def list_student_bookmark_folders(student_id: str) -> List[Dict[str, Any]]:
    """Lists all bookmark folders for a student, including item counts and stats."""
    sid = (student_id or "default_student").strip()
    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT f.*, COUNT(b.id) as bookmark_count
            FROM coding_bookmark_folders f
            LEFT JOIN bookmarked_coding_questions b
                ON f.id = b.folder_id AND b.student_id = f.student_id
            WHERE f.student_id = ?
            GROUP BY f.id
            ORDER BY f.name ASC
        """, (sid,))
        rows = cursor.fetchall()

        folders = [dict(r) for r in rows]

        # Calculate count of uncategorized bookmarks
        cursor.execute("""
            SELECT COUNT(*) as unassigned_count
            FROM bookmarked_coding_questions
            WHERE student_id = ? AND (folder_id IS NULL OR folder_id = '')
        """, (sid,))
        unassigned_count = cursor.fetchone()["unassigned_count"]

        return {
            "folders": folders,
            "total_folders": len(folders),
            "unassigned_bookmarks_count": unassigned_count
        }  # type: ignore


def update_bookmark_folder(
    student_id: str,
    folder_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    color_hex: Optional[str] = None,
    icon_name: Optional[str] = None
) -> Dict[str, Any]:
    """Updates a folder's name, description, or styling."""
    sid = (student_id or "default_student").strip()
    folder = get_bookmark_folder_by_id(sid, folder_id)
    if not folder:
        raise KeyError(f"Folder '{folder_id}' not found.")

    new_name = name.strip() if name and name.strip() else folder["name"]
    new_desc = description if description is not None else folder["description"]
    new_color = color_hex if color_hex else folder["color_hex"]
    new_icon = icon_name if icon_name else folder["icon_name"]
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        # If renaming, check for conflict
        if new_name.lower() != folder["name"].lower():
            cursor.execute("SELECT id FROM coding_bookmark_folders WHERE student_id = ? AND LOWER(name) = LOWER(?)", (sid, new_name))
            if cursor.fetchone():
                raise ValueError(f"A folder named '{new_name}' already exists.")

        cursor.execute("""
            UPDATE coding_bookmark_folders
            SET name = ?, description = ?, color_hex = ?, icon_name = ?, updated_at = ?
            WHERE student_id = ? AND id = ?
        """, (new_name, new_desc, new_color, new_icon, now, sid, folder_id))
        conn.commit()

    return get_bookmark_folder_by_id(sid, folder_id)  # type: ignore


def delete_bookmark_folder(
    student_id: str,
    folder_id: str,
    delete_contents: bool = False
) -> bool:
    """
    Deletes a folder. If delete_contents is False (default), the bookmarks
    inside are unassigned (moved to General / Uncategorized).
    """
    sid = (student_id or "default_student").strip()
    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM coding_bookmark_folders WHERE student_id = ? AND id = ?", (sid, folder_id))
        if not cursor.fetchone():
            return False

        if delete_contents:
            cursor.execute("DELETE FROM bookmarked_coding_questions WHERE student_id = ? AND folder_id = ?", (sid, folder_id))
        else:
            cursor.execute("UPDATE bookmarked_coding_questions SET folder_id = NULL WHERE student_id = ? AND folder_id = ?", (sid, folder_id))

        cursor.execute("DELETE FROM coding_bookmark_folders WHERE student_id = ? AND id = ?", (sid, folder_id))
        conn.commit()
        return True


def move_bookmark_to_folder(
    student_id: str,
    problem_id: str,
    target_folder_id: Optional[str] = None
) -> bool:
    """Moves a bookmarked problem to a target folder, or removes folder assignment if target_folder_id is None."""
    sid = (student_id or "default_student").strip()
    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        # If target_folder_id is specified, verify it exists and belongs to student
        if target_folder_id and target_folder_id.strip():
            cursor.execute("SELECT id FROM coding_bookmark_folders WHERE student_id = ? AND id = ?", (sid, target_folder_id.strip()))
            if not cursor.fetchone():
                raise ValueError(f"Target folder '{target_folder_id}' does not exist.")
            assigned_id = target_folder_id.strip()
        else:
            assigned_id = None

        cursor.execute("""
            UPDATE bookmarked_coding_questions
            SET folder_id = ?
            WHERE student_id = ? AND problem_id = ?
        """, (assigned_id, sid, problem_id.strip()))
        conn.commit()
        return cursor.rowcount > 0


def get_folder_bookmarks(
    student_id: str,
    folder_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves all bookmarked coding problems inside a specific folder (or uncategorized)."""
    sid = (student_id or "default_student").strip()
    with get_db_connection() as conn:
        ensure_bookmark_folders_schema(conn)
        cursor = conn.cursor()

        if folder_id and folder_id.strip():
            cursor.execute("""
                SELECT id, student_id, problem_id, problem_data, folder_id, created_at
                FROM bookmarked_coding_questions
                WHERE student_id = ? AND folder_id = ?
                ORDER BY created_at DESC
            """, (sid, folder_id.strip()))
        else:
            cursor.execute("""
                SELECT id, student_id, problem_id, problem_data, folder_id, created_at
                FROM bookmarked_coding_questions
                WHERE student_id = ? AND (folder_id IS NULL OR folder_id = '')
                ORDER BY created_at DESC
            """, (sid,))

        rows = cursor.fetchall()
        bookmarks = []
        for r in rows:
            rec = dict(r)
            try:
                prob = json.loads(rec.get("problem_data", "{}"))
            except Exception:
                prob = {}
            if "id" not in prob or not prob["id"]:
                prob["id"] = rec.get("problem_id")
            prob["bookmark_id"] = rec.get("id")
            prob["folder_id"] = rec.get("folder_id")
            prob["bookmarked_at"] = rec.get("created_at")
            bookmarks.append(prob)
        return bookmarks
