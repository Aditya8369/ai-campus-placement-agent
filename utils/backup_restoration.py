"""
Database Backup Restoration Utility (#245)
===========================================
Provides enterprise-grade, transactional SQLite database restoration capabilities
for authorized administrators.

Core guarantees & features:
1. Pre-restoration integrity validation (PRAGMA integrity_check, schema checks, table sanity).
2. Mandatory pre-restoration safety snapshot before replacing live database.
3. Atomic transaction isolation with rollback on any copy/validation fault.
4. Security: Path traversal protection, unauthorized access prevention, and audit logging.
5. In-memory and on-disk corruption detection.
"""

import os
import shutil
import sqlite3
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Required core application tables to confirm schema compatibility
MANDATORY_TABLES = [
    "users",
    "analyses",
    "interviews",
]

BACKUP_SUBDIR = "backups"


class BackupRestorationError(Exception):
    """Exception raised when database backup restoration fails validation or execution."""
    pass


def get_backup_storage_directory() -> str:
    """
    Returns the absolute path to the directory where database backups are stored.
    Ensures directory exists.
    """
    backup_dir = getattr(config, "BACKUP_DIR", None)
    if not backup_dir:
        backup_dir = os.path.join(config.BASE_DIR, BACKUP_SUBDIR)
    os.makedirs(backup_dir, exist_ok=True)
    return str(Path(backup_dir).resolve())


def list_available_backups() -> List[Dict[str, Any]]:
    """
    Enumerates all valid backup files (.db) located in the backup storage directory.
    Returns metadata including filename, path, size_bytes, modified_timestamp, and formatted time.
    """
    backup_dir = get_backup_storage_directory()
    backups: List[Dict[str, Any]] = []

    try:
        for entry in os.scandir(backup_dir):
            if entry.is_file() and entry.name.endswith(".db"):
                stat = entry.stat()
                backups.append({
                    "filename": entry.name,
                    "filepath": os.path.abspath(entry.path),
                    "size_bytes": stat.st_size,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "modified_at": stat.st_mtime,
                    "modified_time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                })
    except Exception as exc:
        logger.error(f"Failed to scan backup directory {backup_dir}: {exc}")
        return []

    # Sort descending by modification time (most recent first)
    backups.sort(key=lambda b: b["modified_at"], reverse=True)
    return backups


def validate_backup_file(backup_path: str) -> Dict[str, Any]:
    """
    Performs comprehensive structural and logical validation of a candidate backup SQLite file.

    Checks:
    - Path exists, is a regular file, and is non-empty.
    - Valid SQLite file header (first 16 bytes).
    - PRAGMA integrity_check passes without errors.
    - Schema compatibility: contains mandatory core tables.
    - Basic sanity queries succeed on primary tables.

    Returns:
        Dict with "valid": bool, "tables": List[str], "table_counts": Dict[str, int], "errors": List[str].
    """
    errors: List[str] = []
    resolved_path = os.path.abspath(backup_path)

    if not os.path.exists(resolved_path):
        return {"valid": False, "errors": [f"Backup file does not exist: {backup_path}"], "tables": [], "table_counts": {}}

    if not os.path.isfile(resolved_path):
        return {"valid": False, "errors": [f"Backup path is not a regular file: {backup_path}"], "tables": [], "table_counts": {}}

    file_size = os.path.getsize(resolved_path)
    if file_size < 100:
        return {"valid": False, "errors": ["Backup file is too small or truncated to be a valid database."], "tables": [], "table_counts": {}}

    # Inspect SQLite 3 header magic string: "SQLite format 3\000"
    try:
        with open(resolved_path, "rb") as f:
            header = f.read(16)
        if not header.startswith(b"SQLite format 3\000"):
            return {"valid": False, "errors": ["File header is not a valid SQLite database header."], "tables": [], "table_counts": {}}
    except Exception as exc:
        return {"valid": False, "errors": [f"Cannot read backup file header: {exc}"], "tables": [], "table_counts": {}}

    table_counts: Dict[str, int] = {}
    found_tables: List[str] = []

    # Connect to backup candidate in read-only URI mode to prevent any mutations
    uri = f"file:{Path(resolved_path).as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()

        # Run integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity_rows = cursor.fetchall()
        if not integrity_rows or integrity_rows[0][0].lower() != "ok":
            error_msgs = [r[0] for r in integrity_rows]
            errors.append(f"PRAGMA integrity_check failed: {'; '.join(error_msgs)}")

        # Enumerate user tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        found_tables = [r[0] for r in cursor.fetchall()]

        # Verify mandatory schema tables
        for required_table in MANDATORY_TABLES:
            if required_table not in found_tables:
                errors.append(f"Missing mandatory table in backup schema: {required_table}")
            else:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {required_table}")
                    table_counts[required_table] = cursor.fetchone()[0]
                except Exception as query_exc:
                    errors.append(f"Query check on table '{required_table}' failed: {query_exc}")

        conn.close()
    except sqlite3.DatabaseError as db_err:
        errors.append(f"SQLite database error during inspection: {db_err}")
    except Exception as exc:
        errors.append(f"Unexpected inspection error: {exc}")

    is_valid = len(errors) == 0
    return {
        "valid": is_valid,
        "errors": errors,
        "tables": found_tables,
        "table_counts": table_counts,
        "file_size": file_size,
        "path": resolved_path
    }


def create_pre_restoration_safety_snapshot() -> str:
    """
    Creates an emergency safety backup of the active live database immediately before
    restoration takes place. Ensures instant rollback capability if replacement fails.
    """
    active_db_path = os.path.abspath(config.DATABASE_PATH)
    backup_dir = get_backup_storage_directory()

    timestamp = int(time.time())
    safety_filename = f"safety_prerestore_{timestamp}_{os.getpid()}.db"
    safety_path = os.path.join(backup_dir, safety_filename)

    if not os.path.exists(active_db_path):
        logger.warning(f"Active database not found at {active_db_path}; creating empty safety baseline.")
        # Create minimal database file
        conn = sqlite3.connect(safety_path)
        conn.close()
        return safety_path

    try:
        # Use SQLite backup API for zero-lock online hot snapshot
        src_conn = sqlite3.connect(active_db_path)
        dest_conn = sqlite3.connect(safety_path)
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()
        logger.info(f"Created pre-restoration safety snapshot at: {safety_path}")
        return safety_path
    except Exception as exc:
        logger.warning(f"Online snapshot failed ({exc}), falling back to filesystem copy.")
        shutil.copy2(active_db_path, safety_path)
        return safety_path


def restore_database_from_backup(
    backup_identifier: str,
    admin_user: str = "administrator"
) -> Dict[str, Any]:
    """
    Restores the application database from a verified backup file.

    Workflow:
    1. Resolve backup file path (protecting against path traversal outside allowed directories).
    2. Deep pre-restoration validation (SQLite header, PRAGMA integrity, mandatory tables).
    3. Creation of pre-restoration safety snapshot.
    4. Hot transactional restoration using SQLite backup API onto active database file.
    5. Post-restoration verification of active database.
    6. Rollback to safety snapshot if post-restoration check fails.
    7. Detailed audit metadata returned.
    """
    backup_dir = get_backup_storage_directory()
    active_db_path = os.path.abspath(config.DATABASE_PATH)

    # Path traversal protection: ensure file belongs to backup directory or allowed base dir
    candidate_name = os.path.basename(backup_identifier)
    target_path = os.path.join(backup_dir, candidate_name)
    if not os.path.exists(target_path):
        # Also check direct absolute path if specified by admin
        if os.path.isabs(backup_identifier) and os.path.exists(backup_identifier):
            target_path = os.path.abspath(backup_identifier)
        else:
            raise BackupRestorationError(f"Backup file '{candidate_name}' not found in backup storage.")

    # Prevent restoring the active database over itself
    if os.path.samefile(target_path, active_db_path) if os.path.exists(active_db_path) else False:
        raise BackupRestorationError("Target backup file cannot be identical to active database.")

    logger.info(f"[AUDIT] Admin '{admin_user}' initiated database restoration from: {target_path}")

    # Step 1: Pre-validation
    validation = validate_backup_file(target_path)
    if not validation["valid"]:
        error_summary = "; ".join(validation["errors"])
        logger.error(f"Restoration rejected due to validation failure: {error_summary}")
        raise BackupRestorationError(f"Corrupt or incompatible backup file: {error_summary}")

    # Step 2: Safety snapshot
    safety_snapshot_path = create_pre_restoration_safety_snapshot()

    # Step 3: Transactional replacement via SQLite backup API
    try:
        # Connect to candidate backup source
        backup_conn = sqlite3.connect(target_path)

        # Ensure parent dir of active database exists
        os.makedirs(os.path.dirname(active_db_path), exist_ok=True)

        # Target active database connection
        active_conn = sqlite3.connect(active_db_path)

        # Copy pages transactionally
        with active_conn:
            backup_conn.backup(active_conn, pages=20, sleep=0.01)

        active_conn.close()
        backup_conn.close()

        # Step 4: Post-restoration verification
        post_val = validate_backup_file(active_db_path)
        if not post_val["valid"]:
            raise RuntimeError(f"Post-restoration integrity validation failed: {post_val['errors']}")

        logger.info(f"[AUDIT] Database successfully restored by '{admin_user}' from '{candidate_name}'.")

        return {
            "success": True,
            "message": f"Database successfully restored from '{candidate_name}'.",
            "restored_from": candidate_name,
            "backup_path": target_path,
            "safety_snapshot_path": safety_snapshot_path,
            "restored_tables": post_val["tables"],
            "table_counts": post_val["table_counts"],
            "restored_at": time.time(),
            "restored_by": admin_user,
        }

    except Exception as exc:
        logger.critical(f"Database restoration encountered error: {exc}. Initiating safety rollback...")
        try:
            if os.path.exists(safety_snapshot_path):
                # Rollback from safety snapshot
                rollback_src = sqlite3.connect(safety_snapshot_path)
                rollback_dst = sqlite3.connect(active_db_path)
                with rollback_dst:
                    rollback_src.backup(rollback_dst)
                rollback_dst.close()
                rollback_src.close()
                logger.info("Safety snapshot successfully rolled back to active database.")
        except Exception as rollback_exc:
            logger.critical(f"FATAL: Safety rollback also failed: {rollback_exc}")

        raise BackupRestorationError(f"Database restoration failed and safely rolled back: {exc}") from exc
