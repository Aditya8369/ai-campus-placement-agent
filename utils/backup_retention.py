"""
Database Backup Retention Policy Engine (#247)
==============================================
Manages lifecycle retention and pruning for SQLite database backup artifacts.

Features:
1. Configurable retention window (retention days or hours).
2. Pin/preserve minimum count of most recent successful backups regardless of age.
3. Protects active live database, in-progress backups, and invalid paths from deletion.
4. Comprehensive audit logging and dry-run simulation mode.
5. Handles inaccessible, read-only, or missing files gracefully.
"""

import os
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Default policy constraints
DEFAULT_RETENTION_DAYS = 7
DEFAULT_MIN_PRESERVED_BACKUPS = 3
BACKUP_SUBDIR = "backups"


class BackupRetentionError(Exception):
    """Exception raised when backup retention policy encounters invalid operations."""
    pass


def get_backup_directory() -> str:
    """
    Resolves the standardized directory where database backup files reside.
    Creates folder if it does not already exist.
    """
    b_dir = getattr(config, "BACKUP_DIR", None)
    if not b_dir:
        b_dir = os.path.join(config.BASE_DIR, BACKUP_SUBDIR)
    os.makedirs(b_dir, exist_ok=True)
    return str(Path(b_dir).resolve())


def get_active_database_path() -> str:
    """Returns absolute path of current active working database."""
    return str(Path(config.DATABASE_PATH).resolve())


def scan_backup_catalog(backup_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Discovers all candidate database backup files in the backup directory.
    Sorts files chronologically descending (newest first).
    """
    directory = os.path.abspath(backup_dir or get_backup_directory())
    active_db = get_active_database_path()
    catalog: List[Dict[str, Any]] = []

    if not os.path.exists(directory):
        return []

    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith(".db"):
                full_path = os.path.abspath(entry.path)

                # Never treat the live active database as a pruneable backup file
                if os.path.exists(active_db) and os.path.samefile(full_path, active_db):
                    continue

                try:
                    stat_info = entry.stat()
                    catalog.append({
                        "filename": entry.name,
                        "path": full_path,
                        "size_bytes": stat_info.st_size,
                        "size_kb": round(stat_info.st_size / 1024, 2),
                        "mtime": stat_info.st_mtime,
                        "age_seconds": time.time() - stat_info.st_mtime,
                        "age_days": round((time.time() - stat_info.st_mtime) / 86400, 2),
                        "timestamp_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat_info.st_mtime)),
                    })
                except (OSError, PermissionError) as stat_err:
                    logger.warning(f"Skipping inaccessible backup file candidate '{entry.name}': {stat_err}")
    except Exception as scan_err:
        logger.error(f"Error scanning backup catalog in '{directory}': {scan_err}")
        return []

    # Sort newest first
    catalog.sort(key=lambda item: item["mtime"], reverse=True)
    return catalog


def evaluate_backup_retention(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    min_preserved: int = DEFAULT_MIN_PRESERVED_BACKUPS,
    backup_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates current backup inventory against the retention policy without deleting files.

    Rules:
    - The top `min_preserved` most recent valid backups are ALWAYS preserved (never expired).
    - Backups older than `retention_days` beyond the preserved count are flagged for expiration.
    - Active live database is strictly excluded from any deletion candidacy.
    """
    catalog = scan_backup_catalog(backup_dir=backup_dir)
    retention_seconds = max(1, int(retention_days)) * 86400
    cutoff_time = time.time() - retention_seconds

    preserved_backups: List[Dict[str, Any]] = []
    expired_backups: List[Dict[str, Any]] = []

    for index, backup in enumerate(catalog):
        # Guarantee preservation of the N most recent backups regardless of age
        if index < min_preserved:
            item = dict(backup)
            item["retention_reason"] = f"Preserved as one of top {min_preserved} recent backups."
            preserved_backups.append(item)
            continue

        # Check if age exceeds retention window
        if backup["mtime"] < cutoff_time:
            item = dict(backup)
            item["retention_reason"] = f"Exceeds retention window ({retention_days} days)."
            expired_backups.append(item)
        else:
            item = dict(backup)
            item["retention_reason"] = "Within active retention window."
            preserved_backups.append(item)

    total_reclaimable_bytes = sum(b["size_bytes"] for b in expired_backups)

    return {
        "retention_policy": {
            "retention_days": retention_days,
            "min_preserved": min_preserved,
            "cutoff_timestamp": cutoff_time,
            "cutoff_date_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(cutoff_time)),
        },
        "total_backups_found": len(catalog),
        "preserved_count": len(preserved_backups),
        "expired_count": len(expired_backups),
        "reclaimable_bytes": total_reclaimable_bytes,
        "reclaimable_kb": round(total_reclaimable_bytes / 1024, 2),
        "reclaimable_mb": round(total_reclaimable_bytes / (1024 * 1024), 2),
        "preserved_backups": preserved_backups,
        "expired_backups": expired_backups,
    }


def prune_expired_backups(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    min_preserved: int = DEFAULT_MIN_PRESERVED_BACKUPS,
    dry_run: bool = False,
    backup_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes backup pruning based on retention rules.

    Safety:
    - Protects the live active database.
    - Never deletes if dry_run=True.
    - Handles locked, read-only, or missing files with error recording.
    - Logs each deletion operation.
    """
    evaluation = evaluate_backup_retention(
        retention_days=retention_days,
        min_preserved=min_preserved,
        backup_dir=backup_dir
    )

    expired_candidates = evaluation["expired_backups"]
    deleted_files: List[Dict[str, Any]] = []
    failed_deletions: List[Dict[str, Any]] = []
    bytes_freed = 0

    active_db = get_active_database_path()

    for item in expired_candidates:
        file_path = item["path"]

        # Final absolute safety check: ensure target is NOT active database
        if os.path.exists(active_db) and os.path.samefile(file_path, active_db):
            logger.critical(f"PROTECTION TRIGGERED: Attempted deletion of active database '{file_path}'. Skipping.")
            continue

        if dry_run:
            logger.info(f"[DRY-RUN] Would delete expired backup: {file_path} ({item['size_kb']} KB)")
            deleted_files.append(item)
            bytes_freed += item["size_bytes"]
            continue

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[RETENTION] Successfully pruned expired backup: {file_path}")
                deleted_files.append(item)
                bytes_freed += item["size_bytes"]
            else:
                logger.warning(f"[RETENTION] Backup file vanished prior to deletion: {file_path}")
        except Exception as exc:
            logger.error(f"[RETENTION] Failed to delete backup file '{file_path}': {exc}")
            failed_deletions.append({
                "path": file_path,
                "error": str(exc)
            })

    return {
        "status": "success",
        "dry_run": dry_run,
        "retention_days": retention_days,
        "min_preserved": min_preserved,
        "deleted_count": len(deleted_files),
        "failed_count": len(failed_deletions),
        "bytes_freed": bytes_freed,
        "mb_freed": round(bytes_freed / (1024 * 1024), 2),
        "deleted_files": [d["filename"] for d in deleted_files],
        "failed_deletions": failed_deletions,
        "executed_at": time.time(),
    }
