"""
Subject-Wise Confidence Tracker Service (#513)

Enables students to self-rate and audit their confidence (1-5 scale) across key placement subjects:
- Data Structures & Algorithms (DSA)
- Database Management Systems (DBMS / SQL)
- Operating Systems (OS)
- Computer Networks (CN)
- Object-Oriented Programming (OOP)
- Aptitude & Quantitative Reasoning
- Communication & HR Behavioral

Features:
- Historical confidence rating logs and progression tracking
- Identifies weak focus areas (rating <= 2) and generates targeted revision advice
- Independent heuristic recommendations with no mandatory AI API dependencies
- Multi-tenant student isolation with SQLite persistence
"""

import os
import json
import sqlite3
import datetime
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "placement_agent.db")


def _get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_subject_confidence_table():
    """Initializes schema for subject confidence ratings."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subject_confidence_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    subject_key TEXT NOT NULL, -- 'dsa', 'dbms', 'os', 'cn', 'oop', 'aptitude', 'communication'
                    subject_name TEXT NOT NULL,
                    confidence_score INTEGER NOT NULL, -- 1 to 5
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, subject_key)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subject_confidence_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    confidence_score INTEGER NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scr_user ON subject_confidence_ratings(user_id)")
    finally:
        conn.close()


init_subject_confidence_table()


class SubjectConfidenceService:
    """Manages student self-evaluations across placement subjects."""

    STANDARD_SUBJECTS = {
        "dsa": {"name": "Data Structures & Algorithms", "icon": "bi-code-square"},
        "dbms": {"name": "Database Management (DBMS & SQL)", "icon": "bi-database"},
        "os": {"name": "Operating Systems (OS)", "icon": "bi-cpu"},
        "cn": {"name": "Computer Networks", "icon": "bi-diagram-3"},
        "oop": {"name": "Object-Oriented Programming (OOP)", "icon": "bi-boxes"},
        "aptitude": {"name": "Quantitative & Logical Aptitude", "icon": "bi-calculator"},
        "communication": {"name": "Communication & HR Skills", "icon": "bi-chat-dots"}
    }

    SUBJECT_RECOMMENDATIONS = {
        "dsa": "Dedicate 45 minutes daily to LeetCode Mediums on Trees, Graphs, and Dynamic Programming.",
        "dbms": "Practice writing multi-table JOINs, indexing strategies, and review ACID transaction anomalies.",
        "os": "Review Virtual Memory paging, Deadlock avoidance (Banker's Algorithm), and thread synchronization.",
        "cn": "Study TCP 3-way handshakes, DNS lookup flows, and HTTP/HTTPS SSL handshake layers.",
        "oop": "Review the 4 pillars (A-PIE), SOLID design principles, and design a parking lot system.",
        "aptitude": "Practice time, speed & distance, permutations, and percentage formulas with 20 timed questions.",
        "communication": "Record your answers to 'Tell me about yourself' and 'Greatest technical failure' using Voice Mode."
    }

    @classmethod
    def update_rating(cls, user_id: str, subject_key: str, score: int, notes: str = "") -> Dict[str, Any]:
        """Updates confidence score (1-5) and records historical snapshot."""
        key = subject_key.lower().strip()
        if key not in cls.STANDARD_SUBJECTS:
            raise ValueError(f"Unknown subject '{subject_key}'. Supported: {list(cls.STANDARD_SUBJECTS.keys())}")

        if not (1 <= score <= 5):
            raise ValueError("Confidence score must be an integer between 1 and 5.")

        subject_name = cls.STANDARD_SUBJECTS[key]["name"]
        conn = _get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO subject_confidence_ratings (
                        user_id, subject_key, subject_name, confidence_score, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, subject_key) DO UPDATE SET
                        confidence_score = excluded.confidence_score,
                        notes = excluded.notes,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, key, subject_name, score, notes))

                conn.execute("""
                    INSERT INTO subject_confidence_history (user_id, subject_key, confidence_score)
                    VALUES (?, ?, ?)
                """, (user_id, key, score))

            return cls.get_subject_ratings(user_id)
        finally:
            conn.close()

    @classmethod
    def get_subject_ratings(cls, user_id: str) -> Dict[str, Any]:
        """Retrieves current ratings, weak subjects, average confidence, and revision tips."""
        conn = _get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM subject_confidence_ratings WHERE user_id = ?", (user_id,)
            ).fetchall()
            ratings_map = {r["subject_key"]: r for r in rows}
        finally:
            conn.close()

        subjects_data = []
        total_score = 0
        weak_areas = []

        for key, meta in cls.STANDARD_SUBJECTS.items():
            record = ratings_map.get(key)
            score = record["confidence_score"] if record else 3
            notes = record["notes"] if record else ""
            updated_at = str(record["updated_at"]) if record else None

            total_score += score
            is_weak = score <= 2
            if is_weak:
                weak_areas.append({
                    "key": key,
                    "name": meta["name"],
                    "score": score,
                    "recommendation": cls.SUBJECT_RECOMMENDATIONS.get(key, "Review fundamental core concepts.")
                })

            subjects_data.append({
                "key": key,
                "name": meta["name"],
                "icon": meta["icon"],
                "score": score,
                "notes": notes,
                "is_weak": is_weak,
                "recommendation": cls.SUBJECT_RECOMMENDATIONS.get(key, ""),
                "updated_at": updated_at
            })

        avg_confidence = round(total_score / len(cls.STANDARD_SUBJECTS), 1)

        return {
            "average_confidence": avg_confidence,
            "total_subjects": len(cls.STANDARD_SUBJECTS),
            "weak_subjects_count": len(weak_areas),
            "subjects": subjects_data,
            "weak_areas": weak_areas
        }

    @classmethod
    def get_confidence_history(cls, user_id: str, subject_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns historical audit progression for graphs or audit."""
        conn = _get_db_connection()
        try:
            if subject_key:
                rows = conn.execute("""
                    SELECT * FROM subject_confidence_history
                    WHERE user_id = ? AND subject_key = ?
                    ORDER BY recorded_at ASC
                """, (user_id, subject_key.lower().strip())).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM subject_confidence_history
                    WHERE user_id = ?
                    ORDER BY recorded_at ASC
                """, (user_id,)).fetchall()

            return [
                {
                    "id": r["id"],
                    "subject_key": r["subject_key"],
                    "score": r["confidence_score"],
                    "recorded_at": str(r["recorded_at"])
                }
                for r in rows
            ]
        finally:
            conn.close()
