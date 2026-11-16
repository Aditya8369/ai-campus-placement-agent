"""
User Storage Limits and Quota Management Service (#353).

Provides configurable per-user storage and document count limits:
- Maximum file upload size (default e.g. 5 MB)
- Maximum number of stored active resumes/analyses per account (default 10)
- Maximum generated reports count per account (default 20)
- Maximum total cumulative disk storage per account (default 25 MB)

Features:
- Live computation of a student's storage utilization (bytes and counts)
- Quota pre-check validation before uploading new resumes or generating reports
- Clear, informative error messages indicating which limit was reached and how to reclaim space
- Multi-tenant student isolation ensuring quotas are computed per student_id
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import config
from utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Default Storage Quota Settings (configurable via config.py or environment variables)
DEFAULT_MAX_UPLOAD_SIZE_BYTES = int(getattr(config, "MAX_UPLOAD_SIZE_BYTES", 5 * 1024 * 1024))  # 5 MB
DEFAULT_MAX_RESUMES_PER_USER = int(getattr(config, "MAX_RESUMES_PER_USER", 10))
DEFAULT_MAX_REPORTS_PER_USER = int(getattr(config, "MAX_REPORTS_PER_USER", 20))
DEFAULT_MAX_TOTAL_STORAGE_BYTES = int(getattr(config, "MAX_TOTAL_USER_STORAGE_BYTES", 25 * 1024 * 1024))  # 25 MB


def calculate_user_storage_usage(student_id: str) -> Dict[str, Any]:
    """
    Computes current storage consumption for a given student:
    - Number of saved analyses/resumes
    - Number of generated reports
    - Total disk bytes utilized by the user's files
    """
    if not student_id:
        return {
            "resumes_count": 0,
            "reports_count": 0,
            "total_bytes_used": 0,
            "total_mb_used": 0.0
        }

    resumes_count = 0
    total_bytes = 0
    reports_count = 0

    upload_dir = Path(getattr(config, "UPLOAD_FOLDER", "uploads"))
    report_dir = Path(getattr(config, "REPORT_FOLDER", "reports"))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Count analyses and calculate resume sizes
        cursor.execute(
            """
            SELECT id, resume_filename
            FROM analyses
            WHERE student_id = ?
            """,
            (student_id,)
        )
        analyses_rows = cursor.fetchall()
        resumes_count = len(analyses_rows)

        analysis_ids = []
        for r in analyses_rows:
            analysis_ids.append(str(r["id"]))
            fn = r["resume_filename"]
            if fn and upload_dir.exists():
                file_candidate = upload_dir / Path(fn).name
                if file_candidate.is_file():
                    try:
                        total_bytes += file_candidate.stat().st_size
                    except OSError:
                        pass

        # 2. Check reports related to user's analyses
        if report_dir.exists() and analysis_ids:
            for rep_file in report_dir.iterdir():
                if not rep_file.is_file():
                    continue
                name_lower = rep_file.name.lower()
                for aid in analysis_ids:
                    if aid.lower() in name_lower:
                        reports_count += 1
                        try:
                            total_bytes += rep_file.stat().st_size
                        except OSError:
                            pass
                        break

    finally:
        conn.close()

    total_mb = round(total_bytes / (1024 * 1024), 2)
    return {
        "student_id": student_id,
        "resumes_count": resumes_count,
        "reports_count": reports_count,
        "total_bytes_used": total_bytes,
        "total_mb_used": total_mb
    }


def check_upload_quota(
    student_id: str,
    incoming_file_size_bytes: int,
    custom_limits: Optional[Dict[str, int]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validates whether an incoming resume upload complies with user storage limits.
    Returns (True, None) if allowed, or (False, error_message) if a quota is exceeded.
    """
    limits = custom_limits or {}
    max_upload_size = limits.get("max_upload_size_bytes", DEFAULT_MAX_UPLOAD_SIZE_BYTES)
    max_resumes = limits.get("max_resumes_per_user", DEFAULT_MAX_RESUMES_PER_USER)
    max_total_storage = limits.get("max_total_storage_bytes", DEFAULT_MAX_TOTAL_STORAGE_BYTES)

    # 1. Check individual file size
    if incoming_file_size_bytes > max_upload_size:
        max_mb = max_upload_size / (1024 * 1024)
        return False, (
            f"File exceeds maximum allowed upload size of {max_mb:.1f} MB. "
            "Please compress your document or upload a smaller file."
        )

    # 2. Check current user usage
    usage = calculate_user_storage_usage(student_id)

    # 3. Check resume count limit
    if usage["resumes_count"] >= max_resumes:
        return False, (
            f"Account resume limit reached ({usage['resumes_count']}/{max_resumes}). "
            "Please remove older analyses in your History to free up capacity."
        )

    # 4. Check total cumulative storage limit
    if (usage["total_bytes_used"] + incoming_file_size_bytes) > max_total_storage:
        total_limit_mb = max_total_storage / (1024 * 1024)
        return False, (
            f"Total storage quota of {total_limit_mb:.1f} MB reached. "
            f"Current usage: {usage['total_mb_used']:.2f} MB. "
            "Please delete previous reports or resumes to proceed."
        )

    return True, None


def get_user_storage_summary(student_id: str) -> Dict[str, Any]:
    """
    Returns a comprehensive overview of user's quota, usage, and percentage utilization.
    """
    usage = calculate_user_storage_usage(student_id)
    pct_resumes = round((usage["resumes_count"] / DEFAULT_MAX_RESUMES_PER_USER) * 100, 1)
    pct_storage = round((usage["total_bytes_used"] / DEFAULT_MAX_TOTAL_STORAGE_BYTES) * 100, 1)

    return {
        "success": True,
        "student_id": student_id,
        "usage": usage,
        "limits": {
            "max_upload_size_mb": round(DEFAULT_MAX_UPLOAD_SIZE_BYTES / (1024 * 1024), 1),
            "max_resumes": DEFAULT_MAX_RESUMES_PER_USER,
            "max_reports": DEFAULT_MAX_REPORTS_PER_USER,
            "max_total_storage_mb": round(DEFAULT_MAX_TOTAL_STORAGE_BYTES / (1024 * 1024), 1)
        },
        "utilization_percentage": {
            "resumes": min(100.0, pct_resumes),
            "storage": min(100.0, pct_storage)
        }
    }


def format_storage_size_human(bytes_value: int) -> str:
    """Formats raw byte counts into clean human-readable units (KB, MB, GB)."""
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1024 * 1024:
        return f"{bytes_value / 1024:.1f} KB"
    elif bytes_value < 1024 * 1024 * 1024:
        return f"{bytes_value / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_value / (1024 * 1024 * 1024):.2f} GB"


def can_generate_report(student_id: str, custom_max_reports: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    Validates whether the user has capacity to generate a new report.
    """
    max_reports = custom_max_reports or DEFAULT_MAX_REPORTS_PER_USER
    usage = calculate_user_storage_usage(student_id)
    if usage["reports_count"] >= max_reports:
        return False, (
            f"Account report generation limit reached ({usage['reports_count']}/{max_reports}). "
            "Please delete older downloaded reports or prune previous analyses."
        )
    return True, None

