"""设置、界面偏好、考试切换、导出导入、备份、AI 服务商信息。"""

import json
import re

from .. import ai, exams, secret, userdb
from ..userdb import DEFAULT_SETTINGS, get_settings
from . import route


@route("GET", "/api/ping")
def ping(ctx):
    return {"app": "gongkao-prep"}


@route("GET", "/api/session")
def session(ctx):
    """界面从哪里打开的：local 本机窗口 / lan 局域网手机 / remote 服务器（用密码登录）。管理类功能只在本机显示。"""
    h = ctx.handler
    return {"mode": "remote" if h and h.is_remote else "lan" if h and h.is_lan else "local"}


@route("GET", "/api/exams")
def exams_list(ctx):
    """有哪些考试、这个界面当前在哪门考试（按 Cookie，没带就是上次选的）。"""
    return {"current": exams.current_id(), "default": exams.DEFAULT, "cookie": exams.COOKIE,
            "exams": [exams.public(e) for e in exams.all_exams()]}


@route("GET", "/api/exams/overview")
def exams_overview(ctx):
    """全部考试总览：每门考试的考试日期倒计时、做题量、正确率、学习时长、到期错题。"""
    from datetime import date

    from .. import planner

    day = ctx.day
    out = []
    for ex in exams.all_exams():
        with userdb.db(ex["id"]) as conn:
            s = get_settings(conn)
            if exams.is_default(ex["id"]):
                dates = [{"title": m["title"], "date": m["date"], "days_left": m["days_left"]}
                         for m in planner.milestones(s, userdb.today()) if m["exam_day"]]
            else:
                try:
                    d = date.fromisoformat(str(s.get("exam_date") or "")[:10])
                    dates = [{"title": f"{ex.get('family', '')}{ex.get('name', '')}".strip(), "date": d.isoformat(),
                              "days_left": (d - userdb.today()).days}]
                except ValueError:
                    dates = []
            n, ok = conn.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts").fetchone()
            minutes = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs").fetchone()[0]
            today_min = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs WHERE day=?", (day,)).fetchone()[0]
            last = conn.execute("SELECT MAX(day) FROM study_logs").fetchone()[0] or ""
            due = conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=0 AND next_review<=?", (day,)).fetchone()[0]
        out.append({"id": ex["id"], "name": ex.get("name"), "family": ex.get("family", ""), "level": ex.get("level", ""),
                    "short": ex.get("short", ""), "emblem": ex.get("emblem", ""), "color": ex.get("color", ""),
                    "desc": ex.get("desc", ""), "dates": dates, "questions": n,
                    "accuracy": round(ok / n * 100, 1) if n else 0, "minutes": minutes, "minutes_today": today_min,
                    "last_day": last, "due_wrong": due})
    return {"current": exams.current_id(), "today": day, "exams": out, "conflicts": _date_conflicts(out)}


def _date_conflicts(items, gap=21):
    """不同考试的考试日相隔不到 gap 天时提醒：冲刺期会重叠，同一天则只能选一门。"""
    dates = [(e["short"] or e["name"], m) for e in items for m in e["dates"] if m["days_left"] >= 0]
    dates.sort(key=lambda x: x[1]["date"])
    out = []
    for i, (a, ma) in enumerate(dates):
        for b, mb in dates[i + 1:]:
            if a == b:
                continue
            days = mb["days_left"] - ma["days_left"]
            if days > gap:
                break
            what = "同一天考试，只能选一门" if days == 0 else f"只隔 {days} 天，冲刺期会重叠"
            out.append({"a": ma["title"], "a_date": ma["date"], "b": mb["title"],
                        "b_date": mb["date"], "days": days, "note": what})
    return out


@route("POST", "/api/exams/current")
def exams_switch(ctx):
    """记住选的考试（界面同时把它写进 Cookie，下一个请求起就按这门考试读写）。"""
    ex = str(ctx.body.get("id") or "")
    if not exams.valid(ex):
        raise ValueError("没有这门考试")
    exams.remember(ctx.conn, ex)
    return {"ok": True, "current": ex}


@route("GET", "/api/settings")
def settings_get(ctx):
    return get_settings(ctx.conn)


@route("POST", "/api/settings")
def settings_save(ctx):
    from .home import ensure_today_tasks

    conn, body, day = ctx.conn, ctx.body, ctx.day
    if body.get("ai_clear_key"):
        conn.execute("UPDATE settings SET value='' WHERE key='ai_api_key'")
    own = exams.exam_settings()  # 当前考试自己的设置项（公考没有，都在共用设置里）
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS and k not in own:
            continue
        if k == "ai_api_key":
            if not (v or "").strip():
                continue  # Key 输入框留空表示「不修改」
            v = secret.protect(str(v).strip())
        userdb.save_setting(conn, k, str(v).strip())
    # 修改考试日期后，重新生成今天尚未开始的计划任务
    if {"guokao_date", "shengkao_date", "exam_date", "start_date", "daily_hours"} & body.keys():
        conn.execute("DELETE FROM tasks WHERE day=? AND source='plan' AND done=0", (day,))
        if not conn.execute("SELECT 1 FROM tasks WHERE day=? AND source='plan'", (day,)).fetchone():
            ensure_today_tasks(conn, get_settings(conn))
    return get_settings(conn)


@route("GET", "/api/prefs")
def prefs_get(ctx):
    return userdb.get_prefs(ctx.conn)


@route("POST", "/api/prefs")
def prefs_save(ctx):
    # 界面偏好（主题、草稿、已学章节等），值为任意 JSON；值为 null 表示删除。外观等共用偏好所有考试一份（exams.GLOBAL_PREFS）
    userdb.save_prefs(ctx.conn, ctx.body)
    return {"ok": True}


@route("GET", "/api/export")
def export(ctx):
    return userdb.export_all(ctx.conn)


@route("POST", "/api/import")
def import_(ctx):
    return userdb.import_all(ctx.conn, ctx.body)


@route("GET", "/api/backups")
def backups(ctx):
    return {"items": userdb.list_backups(), "dir": str(userdb.backups_dir()), "keep": userdb.DAILY_KEEP}


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


@route("GET", "/api/ai/usage")
def ai_usage(ctx):
    """本月 AI 用量：调用次数、输入/输出 tokens、按功能分、估算费用（填了单价才算）、每月上限。"""
    from ..userdb import today_str

    conn = ctx.conn
    month = today_str()[:7]
    rows_ = conn.execute(
        "SELECT kind, COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS i, COALESCE(SUM(output_tokens),0) AS o, "
        "COALESCE(SUM(estimated),0) AS est FROM ai_usage WHERE day >= ? GROUP BY kind ORDER BY n DESC",
        (month + "-01",)).fetchall()
    s = get_settings(conn)

    def price(k):
        try:
            return float(s.get(k) or "")
        except ValueError:
            return None

    pin, pout = price("ai_price_in"), price("ai_price_out")
    tin = sum(r["i"] for r in rows_)
    tout = sum(r["o"] for r in rows_)
    cost = round(tin / 1e6 * pin + tout / 1e6 * pout, 2) if pin is not None and pout is not None else None
    names = {"essay": "申论批改", "explain": "讲题", "interview": "面试点评", "reader": "资料问答", "lesson": "教程问答",
             "chat": "自由提问", "test": "测试连接", "followup": "面试追问"}
    return {
        "month": month, "calls": sum(r["n"] for r in rows_), "input": tin, "output": tout,
        "estimated": sum(r["est"] for r in rows_), "cost": cost,
        "limit": int(float(s.get("ai_monthly_tokens") or 0)),
        "by_kind": [{"kind": names.get(r["kind"], r["kind"]), "calls": r["n"], "tokens": r["i"] + r["o"]} for r in rows_],
    }


@route("GET", "/api/ai/presets")
def ai_presets(ctx):
    return ai.PRESETS


@route("GET", "/api/ai/status")
def ai_status(ctx):
    return ai.status(get_settings(ctx.conn, include_secret=True))
