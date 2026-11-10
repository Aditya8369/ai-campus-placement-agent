import logging
import os
import time
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def cleanup_expired_files(max_age_hours: int = 24, dry_run: bool = False) -> dict:
    """
    Scans upload and report directories and removes files older than max_age_hours.
    Returns a summary dictionary of deleted files and reclaimed bytes.
    """
    cutoff_time = time.time() - (max_age_hours * 3600)
    directories = [Path(config.UPLOAD_FOLDER), Path(config.REPORT_FOLDER)]

    stats = {"files_scanned": 0, "files_removed": 0, "bytes_reclaimed": 0, "errors": []}

    for target_dir in directories:
        if not target_dir.exists():
            continue

        for file_path in target_dir.iterdir():
            if not file_path.is_file():
                continue

            stats["files_scanned"] += 1
            try:
                mtime = file_path.stat().st_mtime
                file_size = file_path.stat().st_size

                if mtime < cutoff_time:
                    if not dry_run:
                        file_path.unlink()
                        logger.info(f"Removed expired file: {file_path}")
                    stats["files_removed"] += 1
                    stats["bytes_reclaimed"] += file_size
            except Exception as e:
                err_msg = f"Failed to delete {file_path}: {e}"
                logger.error(err_msg)
                stats["errors"].append(err_msg)

    return stats


def cleanup_database_records(max_age_days: int = 30, dry_run: bool = False) -> dict:
    """
    Cleans up obsolete analysis and interview records older than max_age_days.
    Returns a dictionary of deleted record counts.
    """
    from utils.database import get_db_connection
    cutoff_timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - (max_age_days * 86400)))
    conn = get_db_connection()
    stats = {"analyses_scanned": 0, "analyses_purged": 0, "interviews_purged": 0}

    try:
        # Scan analyses count
        row = conn.execute("SELECT count(*) as cnt FROM analyses WHERE created_at < ?", (cutoff_timestamp,)).fetchone()
        stats["analyses_scanned"] = row["cnt"] if row else 0

        if not dry_run and stats["analyses_scanned"] > 0:
            # Delete corresponding interview sessions first to maintain integrity
            conn.execute(
                "DELETE FROM interviews WHERE analysis_id IN (SELECT id FROM analyses WHERE created_at < ?)",
                (cutoff_timestamp,),
            )
            stats["interviews_purged"] = conn.total_changes

            cur = conn.execute("DELETE FROM analyses WHERE created_at < ?", (cutoff_timestamp,))
            stats["analyses_purged"] = cur.rowcount
            conn.commit()
            logger.info(f"Purged {stats['analyses_purged']} old analyses before {cutoff_timestamp}")
    except Exception as e:
        logger.error(f"Error purging old database records: {e}")
        stats["error"] = str(e)
    finally:
        conn.close()

    return stats


def run_full_retention_policy(max_file_age_hours: int = 24, max_db_age_days: int = 30, dry_run: bool = False) -> dict:
    """
    Executes a comprehensive data retention pass across both local artifacts and database entries.
    """
    file_stats = cleanup_expired_files(max_age_hours=max_file_age_hours, dry_run=dry_run)
    db_stats = cleanup_database_records(max_age_days=max_db_age_days, dry_run=dry_run)
    return {
        "files": file_stats,
        "database": db_stats,
        "dry_run": dry_run
    }


if __name__ == "__main__":
    from utils.logger_config import configure_logging
    configure_logging()
    logger.info("Executing automated upload and report file cleanup...")
    results = cleanup_expired_files(max_age_hours=24)
    logger.info(
        f"Cleanup finished: {results['files_removed']} files removed, {results['bytes_reclaimed']} bytes reclaimed."
    )
