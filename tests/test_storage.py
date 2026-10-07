"""数据目录：空间统计、清理、搬移登记；启动时执行搬移。"""

import json

from gongkao import paths


def test_storage_overview(client):
    status, st, _ = client.get("/api/storage")
    assert status == 200
    assert st["dir"] and st["total"] >= 0
    assert {p["key"] for p in st["parts"]} >= {"app", "backups", "docs", "cache"}


def test_clean_rejects_important_parts(client):
    status, r, _ = client.post("/api/storage/clean", {"what": "app"})
    assert status == 400
    status, r, _ = client.post("/api/storage/clean", {"what": "ocr"})
    assert status == 400


def test_clean_stale_and_cache(client):
    base = paths.data_dir()
    (base / "library").mkdir(exist_ok=True)
    (base / "library" / "docs.v1.bak.db").write_bytes(b"x" * 100)
    (base / "library" / "cache").mkdir(exist_ok=True)
    (base / "library" / "cache" / "a.png").write_bytes(b"y" * 50)
    _s, st, _ = client.get("/api/storage")
    assert st["stale_size"] >= 100
    _s, r, _ = client.post("/api/storage/clean", {"what": "stale"})
    assert r["freed"] >= 100 and not (base / "library" / "docs.v1.bak.db").exists()
    _s, r, _ = client.post("/api/storage/clean", {"what": "cache"})
    assert r["freed"] >= 50 and (base / "library" / "cache").is_dir()


def test_move_blocked_by_env_override(client):
    # 测试环境用 GONGKAO_DATA_DIR 指定了数据目录
    status, r, _ = client.post("/api/datadir/move", {"target": "E:\\x"})
    assert status == 400 and "GONGKAO_DATA_DIR" in r["error"]


def test_apply_pending_move(tmp_path, monkeypatch):
    """登记的搬移在下次启动时执行：文件搬过去、核对、原处删除，location.json 指向新位置。"""
    home = tmp_path / "home"
    src = home  # 默认数据目录就是 %APPDATA%/GongkaoPrep
    dst = tmp_path / "E" / "AppData" / "GongkaoPrep"
    (src / "library" / "ocr").mkdir(parents=True)
    (src / "app.db").write_bytes(b"db")
    (src / "library" / "ocr" / "1.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("GONGKAO_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "home_dir", lambda: home)
    paths.write_location({"data_dir": str(src), "pending_move": str(dst)})
    assert paths.apply_pending_move(log=lambda *a: None) == ""
    assert (dst / "app.db").read_bytes() == b"db"
    assert (dst / "library" / "ocr" / "1.json").exists()
    assert not (src / "app.db").exists() and not (src / "library").exists()
    assert json.loads((home / "location.json").read_text(encoding="utf-8")) == {"data_dir": str(dst)}


def test_pending_move_refuses_to_overwrite(tmp_path, monkeypatch):
    home = tmp_path / "home"
    dst = tmp_path / "dst"
    home.mkdir()
    dst.mkdir()
    (home / "app.db").write_bytes(b"mine")
    (dst / "app.db").write_bytes(b"other")
    monkeypatch.delenv("GONGKAO_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "home_dir", lambda: home)
    paths.write_location({"data_dir": str(home), "pending_move": str(dst)})
    err = paths.apply_pending_move(log=lambda *a: None)
    assert err and (home / "app.db").read_bytes() == b"mine" and (dst / "app.db").read_bytes() == b"other"
    loc = paths.read_location()
    assert "pending_move" not in loc and loc["move_error"]
