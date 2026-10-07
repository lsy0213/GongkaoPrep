"""学习记录数据库：版本迁移、自动备份、导入前快照、恢复。"""

import sqlite3

import pytest

from gongkao import userdb


def test_schema_version_current(httpd):
    with userdb.db() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == userdb.schema_version()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "attempts_created" in idx


def test_migrate_old_database(tmp_path, monkeypatch):
    """没有 user_version 的老库（只有部分表）能升级到最新。"""
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT INTO settings VALUES ('nickname', '老用户')")
    c.commit()
    c.close()
    conn = userdb.open_db(path)
    done = userdb.migrate(conn)
    assert done == [v for v, _d, _f in userdb.MIGRATIONS]
    assert conn.execute("SELECT value FROM settings WHERE key='nickname'").fetchone()[0] == "老用户"
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert userdb.migrate(conn) == []  # 再跑一遍什么都不做
    conn.close()


def test_daily_backup_once_per_day(httpd):
    for p in userdb.BACKUP_DIR.glob("daily-*.db"):
        p.unlink()
    first = userdb.auto_backup()
    assert first and first.exists()
    assert userdb.auto_backup() is None
    c = sqlite3.connect(first)
    assert c.execute("SELECT COUNT(*) FROM settings").fetchone()[0] > 0
    c.close()


def test_prune_keeps_recent(httpd):
    userdb.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(1, 12):
        (userdb.BACKUP_DIR / f"daily-2020-01-{i:02d}.db").write_bytes(b"x")
    userdb._prune("daily-", userdb.DAILY_KEEP)
    left = sorted(p.name for p in userdb.BACKUP_DIR.glob("daily-*.db"))
    assert len(left) == userdb.DAILY_KEEP
    assert "daily-2020-01-01.db" not in left
    for p in userdb.BACKUP_DIR.glob("daily-2020-*.db"):
        p.unlink()


def test_import_takes_snapshot_and_rejects_garbage(client):
    status, r, _ = client.post("/api/import", {"foo": 1})
    assert status == 400 and "备份文件" in r["error"]
    _s, data, _ = client.get("/api/export")
    before = {p.name for p in userdb.BACKUP_DIR.glob("snap-*.db")}
    status, r, _ = client.post("/api/import", data)
    assert status == 200 and r["snapshot"].startswith("snap-")
    after = {p.name for p in userdb.BACKUP_DIR.glob("snap-*.db")}
    assert after - before


def test_restore_backup(client):
    client.post("/api/prefs", {"restore-test": "v1"})
    _s, r, _ = client.post("/api/backups/create", {})
    name = r["name"]
    client.post("/api/prefs", {"restore-test": "v2"})
    _s, lst, _ = client.get("/api/backups")
    assert any(b["name"] == name for b in lst["items"])
    status, r, _ = client.post("/api/backups/restore", {"name": name})
    assert status == 200 and r["ok"]
    _s, prefs, _ = client.get("/api/prefs")
    assert prefs["restore-test"] == "v1"
    client.post("/api/prefs", {"restore-test": None})


def test_restore_rejects_bad_names(client):
    status, _r, _ = client.post("/api/backups/restore", {"name": "../app.db"})
    assert status == 400
    status, _r, _ = client.post("/api/backups/restore", {"name": "nope.db"})
    assert status == 400


@pytest.mark.parametrize("bad", ["", "a"])
def test_snapshot_reason_sanitized(httpd, bad):
    p = userdb.snapshot(bad + "/../x")
    assert p.parent == userdb.BACKUP_DIR
