import os
import time
import sqlite3
import pytest
from pathlib import Path

import config
from utils.database import init_db
from utils.backup_retention import (
    get_backup_directory,
    get_active_database_path,
    scan_backup_catalog,
    evaluate_backup_retention,
    prune_expired_backups
)
from app import app


@pytest.fixture
def retention_env(tmp_path, monkeypatch):
    """Sets up an isolated database and backup directory."""
    db_file = tmp_path / "live_active.db"
    backup_dir = tmp_path / "retention_backups"
    backup_dir.mkdir()

    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "admin-secret-key")

    init_db()

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield {
            "client": client,
            "db_path": str(db_file),
            "backup_dir": str(backup_dir),
            "tmp_path": tmp_path
        }


def _create_mock_backup(filepath: str, age_days: float = 0):
    """Creates a mock backup SQLite file and artificially modifies its timestamp."""
    conn = sqlite3.connect(filepath)
    conn.execute("CREATE TABLE mock_data (id INT, note TEXT)")
    conn.execute("INSERT INTO mock_data VALUES (1, 'Sample data')")
    conn.commit()
    conn.close()

    target_time = time.time() - (age_days * 86400)
    os.utime(filepath, (target_time, target_time))


def test_scan_backup_catalog_excludes_active_db(retention_env):
    b_dir = retention_env["backup_dir"]
    db_path = retention_env["db_path"]

    # Place a regular backup
    b1 = os.path.join(b_dir, "backup_recent.db")
    _create_mock_backup(b1, age_days=1)

    catalog = scan_backup_catalog(backup_dir=b_dir)
    assert len(catalog) == 1
    assert catalog[0]["filename"] == "backup_recent.db"

    # If the active db somehow sits in the same directory, it should be excluded
    catalog_with_live = scan_backup_catalog(backup_dir=os.path.dirname(db_path))
    paths = [item["path"] for item in catalog_with_live]
    assert db_path not in paths


def test_evaluate_retention_policy_rules(retention_env):
    b_dir = retention_env["backup_dir"]

    # Create 5 backups with varying ages: 1d, 3d, 10d, 15d, 20d
    ages = [1, 3, 10, 15, 20]
    for i, age in enumerate(ages):
        _create_mock_backup(os.path.join(b_dir, f"backup_{i}_{age}d.db"), age_days=age)

    # Policy: retention_days=7, min_preserved=3
    # Top 3 newest: 1d, 3d, 10d (preserved despite 10d > 7d because of min_preserved=3)
    # Beyond top 3: 15d and 20d are > 7d -> expired
    eval_res = evaluate_backup_retention(retention_days=7, min_preserved=3, backup_dir=b_dir)

    assert eval_res["total_backups_found"] == 5
    assert eval_res["preserved_count"] == 3
    assert eval_res["expired_count"] == 2

    expired_files = [b["filename"] for b in eval_res["expired_backups"]]
    assert "backup_3_15d.db" in expired_files
    assert "backup_4_20d.db" in expired_files


def test_prune_expired_backups_dry_run(retention_env):
    b_dir = retention_env["backup_dir"]

    # Create 4 backups: 2 recent (1d, 2d), 2 old (14d, 30d)
    for age in [1, 2, 14, 30]:
        _create_mock_backup(os.path.join(b_dir, f"backup_{age}d.db"), age_days=age)

    # Dry run
    res = prune_expired_backups(retention_days=7, min_preserved=2, dry_run=True, backup_dir=b_dir)
    assert res["status"] == "success"
    assert res["dry_run"] is True
    assert res["deleted_count"] == 2

    # Files must still exist on disk
    assert os.path.exists(os.path.join(b_dir, "backup_14d.db"))
    assert os.path.exists(os.path.join(b_dir, "backup_30d.db"))


def test_prune_expired_backups_real_deletion(retention_env):
    b_dir = retention_env["backup_dir"]

    # Create 4 backups: 2 recent (1d, 2d), 2 old (14d, 30d)
    for age in [1, 2, 14, 30]:
        _create_mock_backup(os.path.join(b_dir, f"backup_{age}d.db"), age_days=age)

    # Real prune
    res = prune_expired_backups(retention_days=7, min_preserved=2, dry_run=False, backup_dir=b_dir)
    assert res["status"] == "success"
    assert res["deleted_count"] == 2
    assert "backup_14d.db" in res["deleted_files"]
    assert "backup_30d.db" in res["deleted_files"]

    # Old files removed, recent files preserved
    assert not os.path.exists(os.path.join(b_dir, "backup_14d.db"))
    assert not os.path.exists(os.path.join(b_dir, "backup_30d.db"))
    assert os.path.exists(os.path.join(b_dir, "backup_1d.db"))
    assert os.path.exists(os.path.join(b_dir, "backup_2d.db"))


def test_prune_never_deletes_live_active_database(retention_env):
    b_dir = retention_env["backup_dir"]
    live_db = retention_env["db_path"]

    # Put an old backup
    _create_mock_backup(os.path.join(b_dir, "old_backup.db"), age_days=60)

    # Attempt to evaluate / prune
    res = prune_expired_backups(retention_days=5, min_preserved=0, dry_run=False, backup_dir=b_dir)
    assert os.path.exists(live_db)
    assert not os.path.exists(os.path.join(b_dir, "old_backup.db"))


def test_api_backup_retention_endpoints(retention_env):
    client = retention_env["client"]
    b_dir = retention_env["backup_dir"]

    for age in [1, 2, 12, 25]:
        _create_mock_backup(os.path.join(b_dir, f"api_backup_{age}d.db"), age_days=age)

    # 1. Unauthorized GET
    unauth_get = client.get("/api/admin/database/backup/retention")
    assert unauth_get.status_code == 403

    # 2. Authorized GET
    auth_get = client.get(
        "/api/admin/database/backup/retention?retention_days=7&min_preserved=2",
        headers={"X-Admin-Key": "admin-secret-key"}
    )
    assert auth_get.status_code == 200
    get_data = auth_get.get_json()["data"]
    assert get_data["total_backups_found"] == 4
    assert get_data["expired_count"] == 2

    # 3. Authorized POST prune (dry run)
    post_dry = client.post(
        "/api/admin/database/backup/retention",
        headers={"X-Admin-Key": "admin-secret-key"},
        json={"retention_days": 7, "min_preserved": 2, "dry_run": True}
    )
    assert post_dry.status_code == 200
    assert post_dry.get_json()["prune_result"]["deleted_count"] == 2

    # 4. Authorized POST prune (real run)
    post_real = client.post(
        "/api/admin/database/backup/retention",
        headers={"X-Admin-Key": "admin-secret-key"},
        json={"retention_days": 7, "min_preserved": 2, "dry_run": False}
    )
    assert post_real.status_code == 200
    assert post_real.get_json()["prune_result"]["deleted_count"] == 2
    assert not os.path.exists(os.path.join(b_dir, "api_backup_25d.db"))
