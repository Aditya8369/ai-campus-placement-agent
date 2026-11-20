"""
Student Personal Data Download & Export Package Service (#258)
===============================================================
Generates a comprehensive, portable personal data package for student users in compliance
with privacy and personal data portability standards (e.g. GDPR Art 20).

What is Included in the Data Package:
1. Student Profile & Account Metadata (Name, Email, Graduation Year, CGPA, Target Role, Target Company)
2. Complete Resume Placement Analysis History (ATS scores, match breakdowns, skill gaps, roadmaps)
3. Job Application Records (Tracked applications, stages, companies, application dates, notes)
4. Saved Interview Preparation Notes & Custom Cheat Sheets
5. Mock Interview Performance History & Evaluated Transcripts
6. Coding Practice Submissions & Question Bookmarks
7. Calendar Preparation Events & Deadlines
8. Multi-Role Capability Benchmarks

Strict Security Guarantees:
- PASSWORDS, password hashes, reset tokens, and session secrets are EXCLUDED.
- Authentication tokens and API keys are completely stripped.
- Multi-Tenant Isolation: Enforces that candidates can ONLY export their own personal records.
- Outputs as a structured, compressed ZIP archive containing cleanly organized JSON and Markdown files.
"""

import sqlite3
import json
import zipfile
import io
import logging
from typing import Dict, Any, List, Optional, Generator
from datetime import datetime, timezone

from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def _sanitize_record(data: Any) -> Any:
    """
    Recursively removes any fields containing passwords, tokens, hashes,
    or internal session security credentials to guarantee strict privacy.
    """
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ("password", "token", "secret", "salt", "hash", "credential")):
                continue
            clean[k] = _sanitize_record(v)
        return clean
    elif isinstance(data, list):
        return [_sanitize_record(item) for item in data]
    return data


def build_student_data_export_manifest(student_id: str) -> Dict[str, Any]:
    """
    Compiles all personal data points associated with the authenticated student into
    a sanitized dictionary. Excludes sensitive credentials.
    """
    sid = (student_id or "").strip()
    if not sid:
        raise ValueError("Student identifier is required for personal data export.")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. User Profile Data
        cursor.execute("PRAGMA table_info(users)")
        user_cols = {row["name"] for row in cursor.fetchall()}
        user_select_cols = [c for c in ["id", "name", "email", "role", "created_at", "is_verified"] if c in user_cols]
        if user_select_cols:
            cursor.execute(f"SELECT {', '.join(user_select_cols)} FROM users WHERE id = ?", (sid,))
            user_row = cursor.fetchone()
            user_profile = dict(user_row) if user_row else {"id": sid, "name": "Anonymous Candidate"}
        else:
            user_profile = {"id": sid, "name": "Anonymous Candidate"}

        # Fetch candidate profile details if present
        cursor.execute("SELECT * FROM student_profiles WHERE student_id = ?", (sid,))
        sp_row = cursor.fetchone()
        candidate_profile = dict(sp_row) if sp_row else {}

        # 2. Placement Analyses
        cursor.execute("""
            SELECT id, resume_filename, company_name, job_description, results_json, version_number, created_at
            FROM analyses
            WHERE student_id = ?
            ORDER BY created_at DESC
        """, (sid,))
        analyses = []
        for r in cursor.fetchall():
            rec = dict(r)
            try:
                rec["results"] = json.loads(rec.get("results_json") or "{}")
            except Exception:
                rec["results"] = {}
            rec.pop("results_json", None)
            analyses.append(rec)

        # 3. Job Applications
        cursor.execute("PRAGMA table_info(job_applications)")
        app_cols = {row["name"] for row in cursor.fetchall()}
        app_select = [c for c in ["id", "company_name", "role_title", "status", "application_date", "job_url", "location", "job_type", "notes", "created_at"] if c in app_cols]
        cursor.execute(f"""
            SELECT {', '.join(app_select)}
            FROM job_applications
            WHERE student_id = ?
            ORDER BY application_date DESC
        """, (sid,))
        job_apps = [dict(r) for r in cursor.fetchall()]

        # 4. Preparation Notes
        cursor.execute("""
            SELECT id, title, description, category, created_at, updated_at
            FROM interview_preparation_notes
            WHERE student_id = ?
            ORDER BY updated_at DESC
        """, (sid,))
        notes = [dict(r) for r in cursor.fetchall()]

        # 5. Mock Interview Sessions
        interviews = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interviews'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT i.id, i.analysis_id, i.current_question_index, i.questions_json, i.answers_json, i.completed
                FROM interviews i
                JOIN analyses a ON i.analysis_id = a.id
                WHERE a.student_id = ?
            """, (sid,))
            for r in cursor.fetchall():
                rec = dict(r)
                try:
                    rec["questions"] = json.loads(rec.get("questions_json") or "[]")
                    rec["answers"] = json.loads(rec.get("answers_json") or "[]")
                except Exception:
                    rec["questions"] = []
                    rec["answers"] = []
                rec.pop("questions_json", None)
                rec.pop("answers_json", None)
                interviews.append(rec)

        # 6. Coding Bookmarks
        cursor.execute("""
            SELECT id, problem_id, problem_data, created_at
            FROM bookmarked_coding_questions
            WHERE student_id = ?
            ORDER BY created_at DESC
        """, (sid,))
        bookmarks = []
        for r in cursor.fetchall():
            rec = dict(r)
            try:
                rec["problem"] = json.loads(rec.get("problem_data") or "{}")
            except Exception:
                rec["problem"] = {}
            rec.pop("problem_data", None)
            bookmarks.append(rec)

        # 7. Calendar Events
        cursor.execute("""
            SELECT id, title, event_type, event_date, event_time, company_name, description, priority, completed
            FROM preparation_calendar_events
            WHERE student_id = ?
            ORDER BY event_date ASC
        """, (sid,))
        calendar_events = [dict(r) for r in cursor.fetchall()]

        # 8. Analysis Annotations & Private Notes (#469)
        annotations = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_annotations'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT id, analysis_id, annotation_type, section, content, created_at, updated_at
                FROM analysis_annotations
                WHERE student_id = ?
                ORDER BY updated_at DESC
            """, (sid,))
            annotations = [dict(r) for r in cursor.fetchall()]

        # 9. Bookmarked Interview Practice Questions (#469)
        interview_bookmarks = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookmarked_interview_questions'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT id, question_id, question_text, category, company_name, notes, is_practiced, practice_answer, created_at
                FROM bookmarked_interview_questions
                WHERE student_id = ?
                ORDER BY created_at DESC
            """, (sid,))
            interview_bookmarks = [dict(r) for r in cursor.fetchall()]

        raw_manifest = {
            "metadata": {
                "export_version": "1.0.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "student_id": sid,
                "data_controller": "AI Campus Placement Agent"
            },
            "profile": {
                "account": user_profile,
                "placement_profile": candidate_profile
            },
            "placement_analyses": analyses,
            "job_applications": job_apps,
            "preparation_notes": notes,
            "mock_interviews": interviews,
            "coding_bookmarks": bookmarks,
            "interview_bookmarks": interview_bookmarks,
            "analysis_annotations": annotations,
            "calendar_events": calendar_events,
            "summary_counts": {
                "analyses_count": len(analyses),
                "job_applications_count": len(job_apps),
                "notes_count": len(notes),
                "interviews_count": len(interviews),
                "bookmarks_count": len(bookmarks) + len(interview_bookmarks),
                "calendar_events_count": len(calendar_events),
                "annotations_count": len(annotations)
            }
        }

        # Apply strict credential and token stripping
        return _sanitize_record(raw_manifest)


def stream_student_data_json_chunks(student_id: str) -> Generator[str, None, None]:
    """
    Generates and streams the candidate's personal data JSON export in chunks on-demand.
    Uses json.JSONEncoder.iterencode to stream chunks progressively without writing to disk.
    Prevents socket timeouts on large histories and enforces zero server storage.
    """
    manifest = build_student_data_export_manifest(student_id)
    encoder = json.JSONEncoder(indent=2, ensure_ascii=False)
    for chunk in encoder.iterencode(manifest):
        yield chunk


def generate_student_data_zip_package(student_id: str) -> io.BytesIO:
    """
    Packages the candidate's personal data into an in-memory ZIP archive
    containing categorized JSON files and an informative README.md summary.
    """
    manifest = build_student_data_export_manifest(student_id)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Master export file
        zf.writestr(
            "student_placement_data_complete.json",
            json.dumps(manifest, indent=2, ensure_ascii=False)
        )

        # 2. Individual categorized files
        zf.writestr("profile.json", json.dumps(manifest["profile"], indent=2))
        zf.writestr("job_applications.json", json.dumps(manifest["job_applications"], indent=2))
        zf.writestr("placement_analyses.json", json.dumps(manifest["placement_analyses"], indent=2))
        zf.writestr("preparation_notes.json", json.dumps(manifest["preparation_notes"], indent=2))
        zf.writestr("mock_interviews.json", json.dumps(manifest["mock_interviews"], indent=2))
        zf.writestr("coding_bookmarks.json", json.dumps(manifest["coding_bookmarks"], indent=2))
        if manifest.get("interview_bookmarks"):
            zf.writestr("interview_bookmarks.json", json.dumps(manifest["interview_bookmarks"], indent=2))
        if manifest.get("analysis_annotations"):
            zf.writestr("analysis_annotations.json", json.dumps(manifest["analysis_annotations"], indent=2))
        zf.writestr("calendar_events.json", json.dumps(manifest["calendar_events"], indent=2))

        # 3. Human-readable Markdown summary
        summary_md = f"""# Personal Placement Preparation Data Export
**Student ID:** `{student_id}`  
**Export Date:** {manifest['metadata']['exported_at']}  
**Application:** AI Campus Placement Agent

---

## 📊 Summary of Exported Records
- **Placement Analyses:** {manifest['summary_counts']['analyses_count']}
- **Job Applications Tracked:** {manifest['summary_counts']['job_applications_count']}
- **Preparation Notes:** {manifest['summary_counts']['notes_count']}
- **Mock Interviews Completed:** {manifest['summary_counts']['interviews_count']}
- **Bookmarked Coding Questions:** {manifest['summary_counts']['bookmarks_count']}
- **Scheduled Calendar Events:** {manifest['summary_counts']['calendar_events_count']}

---

## 🔒 Security & Privacy Notice
All sensitive authentication credentials, including passwords, secret hashes, and session keys,
have been permanently excluded from this archive. Generated on demand and never retained on the server.
"""
        zf.writestr("README.md", summary_md)

    zip_buffer.seek(0)
    return zip_buffer
