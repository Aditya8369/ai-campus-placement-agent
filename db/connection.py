"""
Database Connection & Transaction Manager (db/connection.py)
============================================================
Centralizes connection creation, row factory configuration, commit/rollback
transaction handling, and resource cleanup.
"""

from contextlib import contextmanager
import logging
import sqlite3
from typing import Generator, Optional

import config

logger = logging.getLogger(__name__)


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and configures a new SQLite connection.
    - Enables WAL mode and busy timeout for concurrent safety.
    - Sets row_factory = sqlite3.Row for dictionary-like column access.
    - Enforces foreign key constraints.
    - Uses MonitoredConnection to safely record query latency metrics (#task-performance-monitoring).
    """
    target_path = db_path or config.DATABASE_PATH
    try:
        from utils.performance_monitor import MonitoredConnection
        conn = sqlite3.connect(target_path, timeout=10.0, factory=MonitoredConnection)
    except Exception:
        conn = sqlite3.connect(target_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_connection(
    db_path: Optional[str] = None
) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields an active SQLite connection and guarantees
    cleanup upon exit.
    """
    conn = create_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(
    db_path: Optional[str] = None
) -> Generator[sqlite3.Cursor, None, None]:
    """
    Context manager that executes statements inside an atomic transaction.
    - Automatically commits on successful completion.
    - Automatically rolls back on any uncaught exception.
    - Yields a cursor for executing queries.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.debug(f"Transaction rolled back due to error: {e}")
            raise e


def get_db_connection(
    db_path: Optional[str] = None
) -> sqlite3.Connection:
    """
    Compatibility helper returning an open SQLite connection.
    Preserved for callers that manage connection lifecycles directly.
    """
    return create_connection(db_path)
