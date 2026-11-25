import os
import re
import uuid
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_STORED_RESUMES_PER_USER = 5
MAX_LABEL_LENGTH = 100
MAX_ROLE_FOCUS_LENGTH = 100
MAX_RESUME_TEXT_CHARS = 10000


def get_db_connection():
    """Returns a SQLite connection with row factory enabled."""
    from utils.database import get_db_connection as _get_db
    return _get_db()


class ResumeLimitExceededError(ValueError):
    """Raised when user attempts to exceed the 5-resume limit."""
    pass


class ResumeNotFoundError(ValueError):
    """Raised when a requested resume is not found."""
    pass


class ResumeAccessDeniedError(PermissionError):
    """Raised when a user attempts to access or modify another student's resume."""
    pass


class ResumeLibraryService:
    """
    Manages named stored resumes per student (up to 5).
    Enforces privacy, ownership, and capacity limits.
    """

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        """Creates the student_resumes table if it does not already exist."""
        conn = get_db_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS student_resumes (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    role_focus TEXT NOT NULL,
                    resume_filename TEXT NOT NULL,
                    extracted_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_student_resumes_student_id
                ON student_resumes (student_id)
            """)
            conn.commit()
        except Exception as e:
            logger.error(f"Error initializing student_resumes table: {e}")
        finally:
            conn.close()

    def _format_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Formats a database row into a standardized resume dictionary."""
        word_count = len(re.findall(r"\b\w+\b", row["extracted_text"] or ""))
        char_count = len(row["extracted_text"] or "")
        return {
            "id": row["id"],
            "student_id": row["student_id"],
            "label": row["label"],
            "role_focus": row["role_focus"],
            "resume_filename": row["resume_filename"],
            "extracted_text": row["extracted_text"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "word_count": word_count,
            "char_count": char_count,
        }

    def list_resumes(self, student_id: str) -> List[Dict[str, Any]]:
        """
        Lists all resumes owned by the student, ordered newest first.
        Private strictly to the student.
        """
        if not student_id:
            return []

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM student_resumes
                WHERE student_id = ?
                ORDER BY created_at DESC
            """, (str(student_id).strip(),))
            rows = cursor.fetchall()
            return [self._format_row(r) for r in rows]
        finally:
            conn.close()

    def count_resumes(self, student_id: str) -> int:
        """Returns the total number of resumes currently stored for the student."""
        if not student_id:
            return 0
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM student_resumes WHERE student_id = ?", (str(student_id).strip(),))
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_resume(self, resume_id: str, student_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single resume by ID, ensuring strict ownership check.
        """
        if not resume_id or not student_id:
            return None

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM student_resumes WHERE id = ?", (str(resume_id).strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            if row["student_id"] != str(student_id).strip():
                raise ResumeAccessDeniedError("Access denied: You do not own this stored resume.")
            return self._format_row(row)
        finally:
            conn.close()

    def create_resume(
        self,
        student_id: str,
        label: str,
        role_focus: str,
        extracted_text: str,
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stores a new named resume for the student.
        Enforces maximum limit of 5 resumes per student.
        """
        clean_student_id = str(student_id or "").strip()
        if not clean_student_id:
            raise ValueError("Student ID is required to store a resume.")

        clean_label = str(label or "").strip()
        if not clean_label:
            raise ValueError("A label is required for your resume (e.g., 'Software Engineer - Backend').")
        if len(clean_label) > MAX_LABEL_LENGTH:
            clean_label = clean_label[:MAX_LABEL_LENGTH]

        clean_role_focus = str(role_focus or "General").strip()
        if len(clean_role_focus) > MAX_ROLE_FOCUS_LENGTH:
            clean_role_focus = clean_role_focus[:MAX_ROLE_FOCUS_LENGTH]

        clean_text = str(extracted_text or "").strip()
        if not clean_text:
            raise ValueError("Resume text content cannot be empty.")
        if len(clean_text) > MAX_RESUME_TEXT_CHARS:
            clean_text = clean_text[:MAX_RESUME_TEXT_CHARS]

        clean_filename = str(resume_filename or f"{clean_label.replace(' ', '_')}.pdf").strip()

        # Enforce maximum 5 resumes per student
        current_count = self.count_resumes(clean_student_id)
        if current_count >= MAX_STORED_RESUMES_PER_USER:
            raise ResumeLimitExceededError(
                f"You have reached the maximum limit of {MAX_STORED_RESUMES_PER_USER} stored resumes. "
                "Please delete or replace an existing resume to add a new one."
            )

        resume_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO student_resumes
                (id, student_id, label, role_focus, resume_filename, extracted_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                resume_id,
                clean_student_id,
                clean_label,
                clean_role_focus,
                clean_filename,
                clean_text,
                now,
                now
            ))
            conn.commit()
            logger.info(f"Stored resume '{clean_label}' ({resume_id}) for student {clean_student_id}")
            return self.get_resume(resume_id, clean_student_id)
        finally:
            conn.close()

    def update_resume(
        self,
        resume_id: str,
        student_id: str,
        label: Optional[str] = None,
        role_focus: Optional[str] = None,
        extracted_text: Optional[str] = None,
        resume_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Renames or updates content/role focus of an existing resume (Replace or Rename).
        Strictly verifies student ownership.
        """
        existing = self.get_resume(resume_id, student_id)
        if not existing:
            raise ResumeNotFoundError(f"Resume '{resume_id}' not found.")

        updates = []
        params = []

        if label is not None:
            clean_label = label.strip()
            if not clean_label:
                raise ValueError("Resume label cannot be empty.")
            updates.append("label = ?")
            params.append(clean_label[:MAX_LABEL_LENGTH])

        if role_focus is not None:
            clean_role = role_focus.strip() or "General"
            updates.append("role_focus = ?")
            params.append(clean_role[:MAX_ROLE_FOCUS_LENGTH])

        if extracted_text is not None:
            clean_text = extracted_text.strip()
            if not clean_text:
                raise ValueError("Replacement resume text cannot be empty.")
            updates.append("extracted_text = ?")
            params.append(clean_text[:MAX_RESUME_TEXT_CHARS])

        if resume_filename is not None:
            updates.append("resume_filename = ?")
            params.append(resume_filename.strip())

        if not updates:
            return existing

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        updates.append("updated_at = ?")
        params.append(now)

        params.extend([str(resume_id).strip(), str(student_id).strip()])

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE student_resumes
                SET {', '.join(updates)}
                WHERE id = ? AND student_id = ?
            """, params)
            conn.commit()
            logger.info(f"Updated resume {resume_id} for student {student_id}")
            return self.get_resume(resume_id, student_id)
        finally:
            conn.close()

    def delete_resume(self, resume_id: str, student_id: str) -> bool:
        """
        Deletes a stored resume from the library.
        Strictly verifies student ownership.
        Crucial: Past analyses are preserved and readable because analyses store
        their own snapshot of resume_text/results_json.
        """
        existing = self.get_resume(resume_id, student_id)
        if not existing:
            raise ResumeNotFoundError(f"Resume '{resume_id}' not found.")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM student_resumes
                WHERE id = ? AND student_id = ?
            """, (str(resume_id).strip(), str(student_id).strip()))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted resume {resume_id} for student {student_id}")
            return deleted
        finally:
            conn.close()


resume_library_service = ResumeLibraryService()
