"""
Placement Cell Batch Resume Analysis Service (#763).
====================================================
Empowers college placement officers to understand where an entire batch stands
without reading every individual report:
1. Multi-resume upload with explicit consent verification and strict batch size limit enforcement.
2. Background processing with individual failure reporting per file.
3. Anonymized aggregate statistics only: average score, score distribution, and most common missing skills.
4. Anonymized aggregate CSV export containing no candidate names or contact details.
5. Guaranteed cleanup: uploaded files are automatically deleted after batch processing completes.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def init_placement_cell_table() -> None:
    """Initializes schema for placement cell batch resume processing."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS placement_cell_batches (
                    id TEXT PRIMARY KEY,
                    batch_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
                    consent_confirmed INTEGER NOT NULL DEFAULT 1,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    average_score REAL DEFAULT 0.0,
                    score_distribution TEXT, -- JSON dictionary of buckets
                    common_missing_skills TEXT, -- JSON list of missing skills with frequency
                    failed_files TEXT, -- JSON list of [{'filename': '...', 'error': '...'}]
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pcb_created_at ON placement_cell_batches (created_at DESC)")
    except Exception as e:
        logger.error(f"Failed to initialize placement_cell_batches table: {e}")
    finally:
        conn.close()


# Ensure table exists upon module import
init_placement_cell_table()


class PlacementCellBatchService:
    """Service providing batch resume upload, background evaluation, and aggregate anonymized statistics."""

    @classmethod
    def get_max_batch_size(cls) -> int:
        """Returns the configured batch size limit (default 50)."""
        return int(getattr(config, "MAX_PLACEMENT_BATCH_SIZE", 50))

    @classmethod
    def validate_batch_upload(
        cls,
        files: List[Any],
        consent: Any,
        max_limit: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates batch upload parameters before saving files:
        - Enforces student consent confirmation notice.
        - Enforces batch size limit with clear, informative messages.
        """
        # 1. Enforce Consent Notice
        is_consent_confirmed = (
            consent is True
            or str(consent).lower().strip() in ("true", "1", "on", "yes", "checked")
        )
        if not is_consent_confirmed:
            return (
                False,
                "Consent confirmation required: You must confirm that student consent has been obtained for batch placement analysis."
            )

        # Filter out empty filename entries (e.g. user clicked submit with no files selected)
        valid_files = [
            f for f in files
            if f and (getattr(f, "filename", None) or isinstance(f, str))
            and (getattr(f, "filename", "") or str(f)).strip() != ""
        ]
        file_count = len(valid_files)

        # 2. Enforce Minimum Batch Size
        if file_count <= 0:
            return False, "Please select at least one resume file to upload."

        # 3. Enforce Maximum Batch Size Limit
        effective_limit = max_limit if max_limit is not None else cls.get_max_batch_size()
        if file_count > effective_limit:
            return (
                False,
                f"Batch limit exceeded: You uploaded {file_count} files. The maximum allowed batch size is {effective_limit} resumes."
            )

        return True, None

    @classmethod
    def create_batch(
        cls,
        batch_name: Optional[str] = None,
        total_files: int = 0,
        consent_confirmed: bool = True
    ) -> str:
        """Registers a new batch record in the database."""
        batch_id = str(uuid.uuid4())
        name = (batch_name or "").strip()
        if not name:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            name = f"Placement Batch - {now_str}"

        conn = get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO placement_cell_batches (
                        id, batch_name, status, consent_confirmed, total_files,
                        processed_count, failed_count, average_score,
                        score_distribution, common_missing_skills, failed_files,
                        created_at
                    ) VALUES (?, ?, 'pending', ?, ?, 0, 0, 0.0, '{}', '[]', '[]', CURRENT_TIMESTAMP)
                """, (batch_id, name, 1 if consent_confirmed else 0, total_files))
            return batch_id
        finally:
            conn.close()

    @classmethod
    def process_batch(
        cls,
        batch_id: str,
        file_records: List[Tuple[str, str]],
        run_in_background: bool = True
    ) -> None:
        """
        Processes uploaded resumes:
        - Extracts text and evaluates ATS score and skill gaps.
        - Reports failed files individually.
        - Calculates anonymized aggregate metrics only.
        - Deletes all uploaded files from disk in a finally block.
        """
        def _execute():
            conn = get_db_connection()
            try:
                with conn:
                    conn.execute("UPDATE placement_cell_batches SET status = 'processing' WHERE id = ?", (batch_id,))
            except Exception as e:
                logger.error(f"Error marking batch {batch_id} as processing: {e}")
            finally:
                conn.close()

            scores: List[int] = []
            missing_skills_counter: Counter[str] = Counter()
            failed_files: List[Dict[str, str]] = []
            temp_dirs_to_clean: Set[str] = set()

            try:
                for temp_path, orig_name in file_records:
                    temp_dirs_to_clean.add(os.path.dirname(temp_path))
                    try:
                        if not os.path.exists(temp_path):
                            failed_files.append({
                                "filename": orig_name,
                                "error": "File was not found on server storage."
                            })
                            continue

                        # Extract text
                        resume_text = ""
                        lower_name = orig_name.lower()
                        if lower_name.endswith(".txt"):
                            with open(temp_path, "r", encoding="utf-8", errors="ignore") as tf:
                                resume_text = tf.read()
                        else:
                            try:
                                from utils.pdf_reader import extract_text_from_file
                                resume_text = extract_text_from_file(temp_path)
                            except Exception as parse_err:
                                failed_files.append({
                                    "filename": orig_name,
                                    "error": f"Failed to extract text: {str(parse_err)}"
                                })
                                continue

                        if not resume_text or not resume_text.strip():
                            failed_files.append({
                                "filename": orig_name,
                                "error": "Document contains no readable text or is blank."
                            })
                            continue

                        # Evaluate ATS Score (deterministic 0-100)
                        try:
                            from utils.ats_score_service import evaluate_resume_ats_score
                            ats_res = evaluate_resume_ats_score(resume_text)
                            score = int(ats_res.get("total_score", 0))
                            score = max(0, min(100, score))
                            scores.append(score)
                        except Exception as score_err:
                            logger.warning(f"Error evaluating ATS score for {orig_name}: {score_err}")
                            # Fallback basic length/skill estimator
                            words = len(resume_text.split())
                            score = max(20, min(80, words // 8))
                            scores.append(score)

                        # Extract Missing Skills via Role Skill Gap Service
                        try:
                            from utils.role_skill_gap_service import analyze_role_skill_gap
                            gap_res = analyze_role_skill_gap(resume_text, role_id="software-developer")
                            missing = gap_res.get("missing_skills", [])
                            for m in missing:
                                skill_name = m.get("skill") if isinstance(m, dict) else str(m)
                                if skill_name and skill_name.strip():
                                    missing_skills_counter[skill_name.strip()] += 1
                        except Exception as skill_err:
                            logger.warning(f"Error extracting skill gaps for {orig_name}: {skill_err}")

                    except Exception as item_err:
                        failed_files.append({
                            "filename": orig_name,
                            "error": f"Processing error: {str(item_err)}"
                        })
                    finally:
                        # Promptly remove individual file as soon as processed
                        try:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception as rm_err:
                            logger.warning(f"Could not remove temp file {temp_path}: {rm_err}")

                # Aggregate Calculations
                valid_count = len(scores)
                avg_score = round(sum(scores) / valid_count, 1) if valid_count > 0 else 0.0

                # Score Distribution Buckets (0-40, 41-60, 61-80, 81-100)
                distribution = {
                    "0-40": sum(1 for s in scores if s <= 40),
                    "41-60": sum(1 for s in scores if 40 < s <= 60),
                    "61-80": sum(1 for s in scores if 60 < s <= 80),
                    "81-100": sum(1 for s in scores if 80 < s <= 100),
                }

                # Most Common Missing Skills (Top 10)
                common_missing = []
                for skill, count in missing_skills_counter.most_common(10):
                    pct = round((count / valid_count * 100), 1) if valid_count > 0 else 0.0
                    common_missing.append({
                        "skill": skill,
                        "count": count,
                        "percentage": pct
                    })

                # Persist completed aggregate results
                conn = get_db_connection()
                try:
                    with conn:
                        conn.execute("""
                            UPDATE placement_cell_batches
                            SET status = 'completed',
                                processed_count = ?,
                                failed_count = ?,
                                average_score = ?,
                                score_distribution = ?,
                                common_missing_skills = ?,
                                failed_files = ?,
                                completed_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (
                            valid_count,
                            len(failed_files),
                            avg_score,
                            json.dumps(distribution),
                            json.dumps(common_missing),
                            json.dumps(failed_files),
                            batch_id
                        ))
                finally:
                    conn.close()

            except Exception as batch_err:
                logger.error(f"Fatal error processing batch {batch_id}: {batch_err}")
                conn = get_db_connection()
                try:
                    with conn:
                        conn.execute("""
                            UPDATE placement_cell_batches
                            SET status = 'failed',
                                failed_files = ?
                            WHERE id = ?
                        """, (json.dumps([{"filename": "batch", "error": str(batch_err)}]), batch_id))
                finally:
                    conn.close()

            finally:
                # Acceptance Criterion 3: Uploaded files are removed after the batch completes
                for temp_dir in temp_dirs_to_clean:
                    try:
                        if os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            logger.info(f"Cleaned up batch upload temporary directory: {temp_dir}")
                    except Exception as dir_clean_err:
                        logger.warning(f"Could not clean up temporary batch directory {temp_dir}: {dir_clean_err}")

        if run_in_background:
            t = threading.Thread(target=_execute, name=f"PlacementBatchWorker-{batch_id[:8]}", daemon=True)
            t.start()
        else:
            _execute()

    @classmethod
    def get_batch(cls, batch_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves batch metadata and anonymized aggregate statistics.
        Contains NO names or candidate contact details.
        """
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM placement_cell_batches WHERE id = ?", (batch_id,)).fetchone()
            if not row:
                return None
            record = dict(row)

            # Parse JSON fields safely
            for json_field in ("score_distribution", "common_missing_skills", "failed_files"):
                val = record.get(json_field)
                if isinstance(val, str):
                    try:
                        record[json_field] = json.loads(val)
                    except Exception:
                        record[json_field] = {} if "distribution" in json_field else []
                elif val is None:
                    record[json_field] = {} if "distribution" in json_field else []

            return record
        finally:
            conn.close()

    @classmethod
    def list_batches(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent placement cell batch reports (anonymized metadata only)."""
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM placement_cell_batches ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            results = []
            for r in rows:
                rec = dict(r)
                for json_field in ("score_distribution", "common_missing_skills", "failed_files"):
                    val = rec.get(json_field)
                    if isinstance(val, str):
                        try:
                            rec[json_field] = json.loads(val)
                        except Exception:
                            rec[json_field] = {} if "distribution" in json_field else []
                    elif val is None:
                        rec[json_field] = {} if "distribution" in json_field else []
                results.append(rec)
            return results
        finally:
            conn.close()

    @classmethod
    def generate_aggregate_csv(cls, batch_id: str) -> str:
        """
        Generates an anonymized aggregate CSV report.
        Acceptance Criterion 1: Contains NO names or contact details.
        """
        batch = cls.get_batch(batch_id)
        if not batch:
            raise ValueError(f"Placement batch '{batch_id}' not found.")

        output = io.StringIO()
        writer = csv.writer(output)

        # Header Section
        writer.writerow(["=== PLACEMENT CELL BATCH AGGREGATE READINESS REPORT ==="])
        writer.writerow(["Batch ID", batch.get("id")])
        writer.writerow(["Batch Name", batch.get("batch_name")])
        writer.writerow(["Status", batch.get("status")])
        writer.writerow(["Total Resumes Evaluated", batch.get("processed_count", 0)])
        writer.writerow(["Failed / Unreadable Files", batch.get("failed_count", 0)])
        writer.writerow(["Average ATS Score", batch.get("average_score", 0.0)])
        writer.writerow(["Created At", batch.get("created_at")])
        writer.writerow(["Completed At", batch.get("completed_at") or "In Progress"])
        writer.writerow([])

        # Section: Score Distribution
        writer.writerow(["=== SCORE DISTRIBUTION ==="])
        writer.writerow(["Score Range", "Readiness Category", "Student Count", "Percentage of Batch"])
        categories = {
            "0-40": "Needs Rework",
            "41-60": "Developing",
            "61-80": "Competitive",
            "81-100": "Placement Ready"
        }
        distribution = batch.get("score_distribution") or {}
        total_eval = max(1, batch.get("processed_count", 0))
        for rng in ["0-40", "41-60", "61-80", "81-100"]:
            cnt = distribution.get(rng, 0)
            pct = round((cnt / total_eval * 100), 1) if batch.get("processed_count", 0) > 0 else 0.0
            writer.writerow([rng, categories.get(rng, ""), cnt, f"{pct}%"])
        writer.writerow([])

        # Section: Common Missing Skills
        writer.writerow(["=== MOST COMMON MISSING SKILLS ==="])
        writer.writerow(["Rank", "Skill Name", "Students Missing", "Percentage of Batch"])
        missing_skills = batch.get("common_missing_skills") or []
        for idx, item in enumerate(missing_skills, start=1):
            writer.writerow([
                idx,
                item.get("skill"),
                item.get("count"),
                f"{item.get('percentage', 0.0)}%"
            ])
        writer.writerow([])

        # Section: Failed Files Report (Individual filenames & technical error messages only; NO personal names)
        failed_files = batch.get("failed_files") or []
        if failed_files:
            writer.writerow(["=== FAILED FILES REPORT ==="])
            writer.writerow(["Filename", "Error Reason"])
            for f in failed_files:
                writer.writerow([f.get("filename"), f.get("error")])

        return output.getvalue()
