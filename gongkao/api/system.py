"""设置、界面偏好、导出导入、备份、AI 服务商信息。"""

import json
import re

from .. import ai, secret, userdb
from ..userdb import DEFAULT_SETTINGS, get_settings
from . import route


@route("GET", "/api/ping")
def ping(ctx):
    return {"app": "gongkao-prep"}


@route("GET", "/api/settings")
def settings_get(ctx):
    return get_settings(ctx.conn)


@route("POST", "/api/settings")
def settings_save(ctx):
    from .home import ensure_today_tasks

    conn, body, day = ctx.conn, ctx.body, ctx.day
    if body.get("ai_clear_key"):
        conn.execute("UPDATE settings SET value='' WHERE key='ai_api_key'")
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k == "ai_api_key":
            if not (v or "").strip():
                continue  # Key 输入框留空表示「不修改」
            v = secret.protect(str(v).strip())
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v).strip()))
    # 修改考试日期后，重新生成今天尚未开始的计划任务
    if {"guokao_date", "shengkao_date", "start_date", "daily_hours"} & body.keys():
        conn.execute("DELETE FROM tasks WHERE day=? AND source='plan' AND done=0", (day,))
        if not conn.execute("SELECT 1 FROM tasks WHERE day=? AND source='plan'", (day,)).fetchone():
            ensure_today_tasks(conn, get_settings(conn))
    return get_settings(conn)


@route("GET", "/api/prefs")
def prefs_get(ctx):
    return {r["key"]: json.loads(r["value"]) for r in ctx.conn.execute("SELECT key, value FROM prefs")}


@route("POST", "/api/prefs")
def prefs_save(ctx):
    # 界面偏好（主题、草稿、已学章节等），值为任意 JSON；值为 null 表示删除
    for k, v in ctx.body.items():
        if v is None:
            ctx.conn.execute("DELETE FROM prefs WHERE key=?", (k,))
        else:
            ctx.conn.execute("INSERT OR REPLACE INTO prefs(key, value) VALUES (?, ?)",
                             (k, json.dumps(v, ensure_ascii=False)))
    return {"ok": True}


@route("GET", "/api/export")
def export(ctx):
    return userdb.export_all(ctx.conn)


@route("POST", "/api/import")
def import_(ctx):
    return userdb.import_all(ctx.conn, ctx.body)


@route("GET", "/api/backups")
def backups(ctx):
    return {"items": userdb.list_backups(), "dir": str(userdb.BACKUP_DIR), "keep": userdb.DAILY_KEEP}


@route("POST", "/api/backups/create")
def backup_create(ctx):
    ctx.conn.commit()
    return {"ok": True, "name": userdb.snapshot("手动").name}


@route("POST", "/api/backups/restore")
def backup_restore(ctx):
    ctx.conn.commit()
    return userdb.restore_backup(str(ctx.body["name"]))


@route("GET", "/api/diagnostics")
def diagnostics(ctx):
    """诊断信息：版本、环境、数据目录、数据库状态、后台任务和最近的日志。不含 API Key 和学习内容。"""
    import platform
    import sys

    from .. import VERSION, library, logs
    from ..paths import data_dir

    conn = ctx.conn
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("attempts", "wrongbook", "cards", "essays", "interviews", "memo_items", "doc_marks")}
    s = get_settings(conn)
    return {
        "app": "gongkao-prep", "version": VERSION, "python": sys.version, "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)), "data_dir": str(data_dir()),
        "schema": conn.execute("PRAGMA user_version").fetchone()[0],
        "integrity": conn.execute("PRAGMA quick_check").fetchone()[0],
        "counts": counts, "library_root": s.get("library_root"), "ai_provider": s.get("ai_provider"),
        "ai_key_saved": s.get("ai_key_saved"), "job": library.jobs.status(), "log": logs.tail(400),
    }


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


@route("GET", "/api/update/check")
def update_check(ctx):
    """点“检查更新”时才联网：读 GitHub 上本项目的最新 Release，和当前版本比较。"""
    import urllib.error
    import urllib.request

    from .. import REPO, VERSION

    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "GongkaoPrep"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 —— 固定的 https 地址
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"current": VERSION, "latest": "", "newer": False, "note": "还没有发布过新版本"}
        return {"error": f"检查更新失败（{e.code}）"}
    except (OSError, ValueError) as e:
        return {"error": f"连不上 GitHub：{e}"}
    latest = (data.get("tag_name") or "").lstrip("vV")
    return {
        "current": VERSION, "latest": latest, "newer": _ver(latest) > _ver(VERSION),
        "url": data.get("html_url") or f"https://github.com/{REPO}/releases", "notes": (data.get("body") or "")[:2000],
        "published_at": data.get("published_at") or "",
    }


@route("GET", "/api/ai/presets")
def ai_presets(ctx):
    return ai.PRESETS


@route("GET", "/api/ai/status")
def ai_status(ctx):
    return ai.status(get_settings(ctx.conn, include_secret=True))
