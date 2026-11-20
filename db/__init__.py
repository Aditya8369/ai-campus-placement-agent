"""
Database Package (db)
=====================
Modular domain repositories for database access, schema migrations, and connection helpers.
"""

from db.connection import (
    create_connection,
    get_connection,
    get_db_connection,
    transaction,
)
from db.migrations import (
    MIGRATIONS,
    ensure_migration_table,
    get_applied_migrations,
    init_db,
    run_migrations,
)
from db import (
    analyses,
    coding_practice,
    cohorts,
    connection,
    interviews,
    migrations,
    reports,
    streaks,
    system,
    tracker,
    users,
)

__all__ = [
    "create_connection",
    "get_connection",
    "transaction",
    "get_db_connection",
    "MIGRATIONS",
    "init_db",
    "run_migrations",
    "ensure_migration_table",
    "get_applied_migrations",
    "connection",
    "migrations",
    "users",
    "analyses",
    "interviews",
    "tracker",
    "coding_practice",
    "reports",
    "streaks",
    "cohorts",
    "system",
]
