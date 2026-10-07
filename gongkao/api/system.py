"""设置、界面偏好、导出导入、备份、AI 服务商信息。"""

import json

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


@route("GET", "/api/ai/presets")
def ai_presets(ctx):
    return ai.PRESETS


@route("GET", "/api/ai/status")
def ai_status(ctx):
    return ai.status(get_settings(ctx.conn, include_secret=True))
