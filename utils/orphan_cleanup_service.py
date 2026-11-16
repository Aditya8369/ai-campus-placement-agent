"""
Orphaned File Identification and Safe Cleanup Service (#352).

Identifies files in upload and report directories that have no valid database references,
or are leftover from failed/incomplete analyses, and removes only files confirmed unused.
Ensures active user files (referenced in analyses, resumes, student profiles, etc.) are never deleted.
Includes a safety threshold (grace period) for newly uploaded in-flight files.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Set

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)


def get_active_referenced_filenames() -> Set[str]:
    """
    Scans the database to collect all active filenames and file paths currently referenced
    by analyses, job applications, student profiles, or generated reports.
    """
    referenced: Set[str] = set()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Resume filenames from analyses table
        try:
            cursor.execute("SELECT resume_filename FROM analyses WHERE resume_filename IS NOT NULL")
            for row in cursor.fetchall():
                fn = row["resume_filename"]
                if fn:
                    referenced.add(Path(fn).name.lower())
        except Exception as e:
            logger.warning(f"Error checking analyses resume_filename: {e}")

        # 2. Resume filenames from job_applications
        try:
            cursor.execute("SELECT resume_filename FROM job_applications WHERE resume_filename IS NOT NULL")
            for row in cursor.fetchall():
                fn = row["resume_filename"]
                if fn:
                    referenced.add(Path(fn).name.lower())
        except Exception as e:
            logger.debug(f"Error checking job_applications: {e}")

        # 3. Resume filenames or reports from student_profiles
        try:
            cursor.execute("SELECT resume_filename FROM student_profiles WHERE resume_filename IS NOT NULL")
            for row in cursor.fetchall():
                fn = row["resume_filename"]
                if fn:
                    referenced.add(Path(fn).name.lower())
        except Exception as e:
            logger.debug(f"Error checking student_profiles: {e}")

        # 4. Analysis IDs (often part of report filenames like report_{analysis_id}.pdf)
        try:
            cursor.execute("SELECT id FROM analyses")
            for row in cursor.fetchall():
                aid = str(row["id"]).lower()
                referenced.add(aid)
        except Exception as e:
            logger.warning(f"Error checking analyses IDs: {e}")

    finally:
        conn.close()

    return referenced


def is_file_orphaned(file_path: Path, active_references: Set[str], min_age_seconds: int = 1800) -> bool:
    """
    Determines if a file is confirmed orphaned:
    - Not referenced in active database records.
    - Older than min_age_seconds (grace period, default 30 mins) to avoid deleting in-flight uploads.
    """
    try:
        stat = file_path.stat()
        file_age = time.time() - stat.st_mtime
        if file_age < min_age_seconds:
            # Within in-flight grace period
            return False

        filename_lower = file_path.name.lower()
        # Direct filename match
        if filename_lower in active_references:
            return False

        # Check if any active analysis ID is embedded in the report filename
        for ref in active_references:
            if ref and len(ref) >= 8 and ref in filename_lower:
                return False

        return True
    except Exception as e:
        logger.warning(f"Error checking orphan status for {file_path}: {e}")
        return False


def cleanup_orphaned_files(
    min_age_minutes: int = 30,
    dry_run: bool = False,
    target_dirs: List[Path] = None
) -> Dict[str, Any]:
    """
    Scans upload and report directories and removes files confirmed to be orphaned.
    """
    min_age_seconds = min_age_minutes * 60
    if target_dirs is None:
        target_dirs = [
            Path(getattr(config, "UPLOAD_FOLDER", "uploads")),
            Path(getattr(config, "REPORT_FOLDER", "reports"))
        ]

    active_references = get_active_referenced_filenames()

    stats: Dict[str, Any] = {
        "success": True,
        "scanned_files": 0,
        "orphaned_files_found": 0,
        "orphaned_files_deleted": 0,
        "bytes_reclaimed": 0,
        "reclaimed_human": "0 KB",
        "dry_run": dry_run,
        "orphaned_files": [],
        "errors": []
    }

    for folder in target_dirs:
        if not folder.exists():
            continue

        for item in folder.iterdir():
            if not item.is_file():
                continue

            # Don't delete .gitkeep or hidden config
            if item.name.startswith("."):
                continue

            stats["scanned_files"] += 1
            if is_file_orphaned(item, active_references, min_age_seconds=min_age_seconds):
                stats["orphaned_files_found"] += 1
                file_size = item.stat().st_size
                stats["orphaned_files"].append({
                    "filename": item.name,
                    "path": str(item),
                    "size_bytes": file_size,
                    "modified_time": item.stat().st_mtime
                })

                if not dry_run:
                    try:
                        item.unlink()
                        stats["orphaned_files_deleted"] += 1
                        stats["bytes_reclaimed"] += file_size
                        logger.info(f"Safely purged orphaned file: {item}")
                    except Exception as e:
                        err_str = f"Failed to unlink orphaned file {item}: {e}"
                        logger.error(err_str)
                        stats["errors"].append(err_str)
                else:
                    stats["bytes_reclaimed"] += file_size

    # Human readable bytes
    reclaimed = stats["bytes_reclaimed"]
    if reclaimed >= 1024 * 1024:
        stats["reclaimed_human"] = f"{reclaimed / (1024 * 1024):.2f} MB"
    else:
        stats["reclaimed_human"] = f"{reclaimed / 1024:.2f} KB"

    return stats


def get_orphan_cleanup_summary_report() -> Dict[str, Any]:
    """
    Generates a quick diagnostics summary of disk usage, orphaned file candidates,
    and active database document references without performing deletions.
    """
    upload_folder = Path(getattr(config, "UPLOAD_FOLDER", "uploads"))
    report_folder = Path(getattr(config, "REPORT_FOLDER", "reports"))
    active_refs = get_active_referenced_filenames()

    upload_count = sum(1 for f in upload_folder.iterdir() if f.is_file()) if upload_folder.exists() else 0
    report_count = sum(1 for f in report_folder.iterdir() if f.is_file()) if report_folder.exists() else 0

    return {
        "active_db_references_count": len(active_refs),
        "total_uploads_on_disk": upload_count,
        "total_reports_on_disk": report_count,
        "upload_folder": str(upload_folder),
        "report_folder": str(report_folder)
    }

