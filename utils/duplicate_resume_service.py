"""
Duplicate Resume Upload Detection Service
Detects identical or near-duplicate resume uploads for a student.

Features:
- Computes SHA-256 binary hash and normalized text fingerprint.
- Compares new uploads against previously analyzed or uploaded resumes for the current user.
- Distinguishes exact byte-identical duplicates from near-identical edits.
- Provides friendly prompts offering the option to reuse existing analysis or proceed as a new version.
- Fully non-blocking: allows students to re-upload if they intentionally want a fresh analysis.
"""

from datetime import datetime, timezone
import hashlib
import os
import re
import sqlite3
from typing import Dict, Any, List, Optional
from utils.database import get_db_connection


class DuplicateResumeService:
    """Service to detect duplicate and near-duplicate resume uploads."""

    def __init__(self):
        self._ensure_duplicate_tracking_table()

    def _ensure_duplicate_tracking_table(self):
        """Ensures the resume_upload_fingerprints table exists."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resume_upload_fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                sha256_hash TEXT NOT NULL,
                content_fingerprint TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_resume_fp_student_hash 
            ON resume_upload_fingerprints(student_id, sha256_hash)
            """
        )
        conn.commit()
        conn.close()

    def compute_file_hash(self, file_bytes: bytes) -> str:
        """Calculates SHA-256 checksum of raw file bytes."""
        hasher = hashlib.sha256()
        hasher.update(file_bytes)
        return hasher.hexdigest()

    def compute_text_fingerprint(self, text: str) -> str:
        """
        Creates a normalized lexical fingerprint of resume text.
        Strips whitespace, punctuation, and casing for fuzzy duplicate detection.
        """
        if not text:
            return ""
        normalized = re.sub(r"[^a-zA-Z0-9]", "", text.lower())
        if len(normalized) > 500:
            # Sample beginning, middle, and end to form robust fingerprint
            quarter = len(normalized) // 4
            sampled = normalized[:150] + normalized[quarter:quarter+150] + normalized[-150:]
        else:
            sampled = normalized
        return hashlib.sha256(sampled.encode("utf-8")).hexdigest()

    def check_for_duplicate(
        self,
        student_id: str,
        file_bytes: bytes,
        filename: str = "resume.pdf",
        extracted_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Checks if the file or its content is identical or near-identical
        to an existing upload by this student.
        """
        file_hash = self.compute_file_hash(file_bytes)
        file_size = len(file_bytes)
        text_fp = self.compute_text_fingerprint(extracted_text or "")

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Check for exact binary duplicate
        cursor.execute(
            """
            SELECT id, filename, uploaded_at, file_size 
            FROM resume_upload_fingerprints 
            WHERE student_id = ? AND sha256_hash = ?
            ORDER BY id DESC LIMIT 1
            """,
            (student_id, file_hash)
        )
        exact_match = cursor.fetchone()

        if exact_match:
            conn.close()
            return {
                "is_duplicate": True,
                "duplicate_type": "exact_binary",
                "message": (
                    f"An identical resume file ('{exact_match['filename']}') was already uploaded on "
                    f"{exact_match['uploaded_at']}. You can reuse its existing analysis or proceed with a new analysis."
                ),
                "matched_record": {
                    "id": exact_match["id"],
                    "filename": exact_match["filename"],
                    "uploaded_at": str(exact_match["uploaded_at"]),
                    "file_size": exact_match["file_size"]
                },
                "sha256_hash": file_hash,
                "can_proceed": True
            }

        # 2. Check for fuzzy text duplicate if text fingerprint available
        if text_fp:
            cursor.execute(
                """
                SELECT id, filename, uploaded_at, file_size 
                FROM resume_upload_fingerprints 
                WHERE student_id = ? AND content_fingerprint = ?
                ORDER BY id DESC LIMIT 1
                """,
                (student_id, text_fp)
            )
            text_match = cursor.fetchone()
            if text_match:
                conn.close()
                return {
                    "is_duplicate": True,
                    "duplicate_type": "content_match",
                    "message": (
                        f"The text content in '{filename}' matches an existing resume ('{text_match['filename']}') "
                        f"uploaded on {text_match['uploaded_at']}."
                    ),
                    "matched_record": {
                        "id": text_match["id"],
                        "filename": text_match["filename"],
                        "uploaded_at": str(text_match["uploaded_at"]),
                        "file_size": text_match["file_size"]
                    },
                    "sha256_hash": file_hash,
                    "can_proceed": True
                }

        conn.close()
        return {
            "is_duplicate": False,
            "duplicate_type": "none",
            "message": "Resume is unique. Ready for processing.",
            "sha256_hash": file_hash,
            "can_proceed": True
        }

    def record_upload_fingerprint(
        self,
        student_id: str,
        file_bytes: bytes,
        filename: str = "resume.pdf",
        extracted_text: Optional[str] = None
    ) -> int:
        """Saves file fingerprint to the tracking table."""
        file_hash = self.compute_file_hash(file_bytes)
        file_size = len(file_bytes)
        text_fp = self.compute_text_fingerprint(extracted_text or "")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resume_upload_fingerprints 
            (student_id, filename, file_size, sha256_hash, content_fingerprint, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_id, filename, file_size, file_hash, text_fp, datetime.now(timezone.utc).isoformat())
        )
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return new_id


duplicate_resume_service = DuplicateResumeService()
