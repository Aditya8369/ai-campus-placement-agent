"""
Preparation Progress Snapshots Service (#607)
=============================================
Allows students to take, persist, list, compare, and delete preparation progress snapshots
across multiple dates.

Captures:
- ATS Compatibility Score
- Coding assessment progress
- Mock interview performance
- Skill gap metrics (missing vs matched count)
- Timestamp and custom snapshot label

Guarantees:
- Snapshots are strictly isolated per student_id and contain no other user's data.
- Users can compare any two snapshots and clearly inspect changes (including unavailable metrics).
- Snapshots can be deleted.
"""

from typing import Dict, Any, List, Optional
import sqlite3
import json
import uuid
from datetime import datetime, timezone
from db.connection import get_db_connection


def _ensure_snapshots_table():
    """Creates preparation_snapshots table if not exists."""
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preparation_snapshots (
                id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                label TEXT NOT NULL,
                ats_score INTEGER DEFAULT 0,
                coding_score INTEGER DEFAULT 0,
                interview_score INTEGER DEFAULT 0,
                skill_gaps_count INTEGER DEFAULT 0,
                matched_skills_count INTEGER DEFAULT 0,
                snapshot_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_student ON preparation_snapshots(student_id)")
        conn.commit()
    finally:
        conn.close()


def create_progress_snapshot(
    student_id: str,
    label: str,
    ats_score: Optional[int] = None,
    coding_score: Optional[int] = None,
    interview_score: Optional[int] = None,
    skill_gaps_count: Optional[int] = None,
    matched_skills_count: Optional[int] = None,
    extra_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Creates and stores a named preparation progress snapshot.
    """
    _ensure_snapshots_table()
    snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
    clean_label = (label or "").strip() or f"Snapshot {datetime.now(timezone.utc).strftime('%b %d, %Y')}"

    raw_data = {
        "ats_score": ats_score,
        "coding_score": coding_score,
        "interview_score": interview_score,
        "skill_gaps_count": skill_gaps_count,
        "matched_skills_count": matched_skills_count,
        "extra": extra_data or {}
    }

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO preparation_snapshots (
                id, student_id, label, ats_score, coding_score,
                interview_score, skill_gaps_count, matched_skills_count, snapshot_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            student_id,
            clean_label,
            ats_score if ats_score is not None else 0,
            coding_score if coding_score is not None else 0,
            interview_score if interview_score is not None else 0,
            skill_gaps_count if skill_gaps_count is not None else 0,
            matched_skills_count if matched_skills_count is not None else 0,
            json.dumps(raw_data)
        ))
        conn.commit()
    finally:
        conn.close()

    return {
        "id": snapshot_id,
        "student_id": student_id,
        "label": clean_label,
        "metrics": raw_data,
        "created_at": datetime.now(timezone.utc).isoformat()
    }


def list_student_snapshots(student_id: str) -> List[Dict[str, Any]]:
    """Retrieves all snapshots for a given student in reverse chronological order."""
    _ensure_snapshots_table()
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT id, student_id, label, ats_score, coding_score,
                   interview_score, skill_gaps_count, matched_skills_count,
                   snapshot_data, created_at
            FROM preparation_snapshots
            WHERE student_id = ?
            ORDER BY created_at DESC
        """, (student_id,)).fetchall()

        out = []
        for r in rows:
            record = dict(r)
            try:
                record["data"] = json.loads(record.get("snapshot_data") or "{}")
            except Exception:
                record["data"] = {}
            out.append(record)
        return out
    finally:
        conn.close()


def delete_student_snapshot(student_id: str, snapshot_id: str) -> bool:
    """Deletes an owned snapshot."""
    _ensure_snapshots_table()
    conn = get_db_connection()
    try:
        res = conn.execute("""
            DELETE FROM preparation_snapshots
            WHERE id = ? AND student_id = ?
        """, (snapshot_id, student_id))
        conn.commit()
        return res.rowcount > 0
    finally:
        conn.close()


def compare_two_snapshots(snapshot_a: Dict[str, Any], snapshot_b: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compares two preparation progress snapshots and generates deltas.
    Highlights metric changes and explicitly marks unavailable metrics.
    """
    data_a = snapshot_a.get("data") or snapshot_a
    data_b = snapshot_b.get("data") or snapshot_b

    metrics_to_compare = [
        ("ATS Score", "ats_score", "/ 100"),
        ("Coding Assessment", "coding_score", "%"),
        ("Mock Interview", "interview_score", "%"),
        ("Skill Gaps Remaining", "skill_gaps_count", "gaps"),
        ("Matched Competencies", "matched_skills_count", "skills")
    ]

    comparisons = []
    for title, key, unit in metrics_to_compare:
        val_a = data_a.get(key)
        val_b = data_b.get(key)

        is_avail_a = val_a is not None
        is_avail_b = val_b is not None

        if is_avail_a and is_avail_b:
            delta = val_b - val_a
            status = "improved" if (delta > 0 if key != "skill_gaps_count" else delta < 0) else ("regressed" if delta != 0 else "neutral")
            comparisons.append({
                "metric": title,
                "val_before": val_a,
                "val_after": val_b,
                "unit": unit,
                "delta": delta,
                "status": status,
                "is_available": True
            })
        else:
            comparisons.append({
                "metric": title,
                "val_before": val_a if is_avail_a else "N/A",
                "val_after": val_b if is_avail_b else "N/A",
                "unit": unit,
                "delta": None,
                "status": "unavailable",
                "is_available": False,
                "note": "Metric was unavailable in one of the compared snapshots."
            })

    return {
        "snapshot_a_id": snapshot_a.get("id"),
        "snapshot_a_label": snapshot_a.get("label"),
        "snapshot_b_id": snapshot_b.get("id"),
        "snapshot_b_label": snapshot_b.get("label"),
        "comparisons": comparisons
    }
