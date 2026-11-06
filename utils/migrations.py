import os
import glob
import logging
import sqlite3
from typing import List, Dict, Any, Optional
import config

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    """
    Creates the schema_migrations tracking table if it does not already exist.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    """)
    conn.commit()


def get_applied_migrations(conn: sqlite3.Connection) -> List[str]:
    """
    Returns list of already applied migration version keys in sorted order.
    """
    ensure_migration_table(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
    return [row[0] for row in cursor.fetchall()]


def get_available_migrations(migrations_directory: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Discovers all SQL migration files in the migrations directory in ascending numerical order.
    """
    target_dir = migrations_directory or MIGRATIONS_DIR
    if not os.path.exists(target_dir):
        return []

    pattern = os.path.join(target_dir, "*.sql")
    files = sorted(glob.glob(pattern))
    migrations = []
    for f in files:
        base = os.path.basename(f)
        version = os.path.splitext(base)[0]
        migrations.append({
            "version": version,
            "filename": base,
            "filepath": f
        })
    return migrations


def apply_migration(conn: sqlite3.Connection, migration: Dict[str, str]) -> bool:
    """
    Executes a single migration script inside a transaction and records its completion (#204).
    """
    version = migration["version"]
    filepath = migration["filepath"]
    with open(filepath, "r", encoding="utf-8") as f:
        sql_content = f.read()

    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN TRANSACTION")
        cursor.executescript(sql_content)
        cursor.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, f"Applied from {migration['filename']}")
        )
        conn.commit()
        logger.info(f"Successfully applied database migration: {version}")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to apply database migration {version}: {e}")
        raise e


def run_database_migrations(db_path: Optional[str] = None, migrations_directory: Optional[str] = None) -> Dict[str, Any]:
    """
    Main migration runner: discovers pending migrations, executes them sequentially,
    and returns migration execution summary metrics (#204).
    """
    target_db = db_path or config.DATABASE_PATH
    os.makedirs(os.path.dirname(os.path.abspath(target_db)), exist_ok=True)
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row

    try:
        ensure_migration_table(conn)
        applied = set(get_applied_migrations(conn))
        available = get_available_migrations(migrations_directory)

        pending = [m for m in available if m["version"] not in applied]
        applied_now = []

        for mig in pending:
            apply_migration(conn, mig)
            applied_now.append(mig["version"])

        total_applied = len(applied) + len(applied_now)
        logger.info(f"Database migration check completed. {len(applied_now)} applied, {total_applied} total.")

        return {
            "status": "success",
            "applied_count": len(applied_now),
            "applied_versions": applied_now,
            "total_versions": total_applied,
            "pending_count": 0
        }
    finally:
        conn.close()


def get_migration_status(db_path: Optional[str] = None, migrations_directory: Optional[str] = None) -> Dict[str, Any]:
    """
    Reports current database schema version status against available disk migrations (#204).
    """
    target_db = db_path or config.DATABASE_PATH
    if not os.path.exists(target_db):
        return {
            "database_exists": False,
            "applied_count": 0,
            "pending_count": len(get_available_migrations(migrations_directory)),
            "migrations": []
        }

    conn = sqlite3.connect(target_db)
    try:
        applied = set(get_applied_migrations(conn))
        available = get_available_migrations(migrations_directory)
        history = []
        for m in available:
            history.append({
                "version": m["version"],
                "filename": m["filename"],
                "status": "applied" if m["version"] in applied else "pending"
            })
        return {
            "database_exists": True,
            "applied_count": len(applied),
            "pending_count": len([m for m in history if m["status"] == "pending"]),
            "migrations": history
        }
    finally:
        conn.close()
