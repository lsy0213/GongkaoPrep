"""首页、复习计划、今日任务、打卡、学习时长、统计、教程（搜索、进度、知识卡组）、闪卡卡组列表。"""

import json
import os
import re
from datetime import timedelta

from .. import library, planner, shizheng
from ..paths import content_dir, load_content
from ..userdb import get_settings, now_str, rows, today, today_str
from . import route

COURSE_DIR = content_dir() / "course"
_course_cache = {}


# ---------------------------------------------------------------- 计划与任务

def ensure_today_tasks(conn, settings):
    """当天第一次打开时，按复习计划生成今日任务。"""
    day = today_str()
    exists = conn.execute("SELECT 1 FROM tasks WHERE day=? AND source='plan' LIMIT 1", (day,)).fetchone()
    if exists:
        return
    for t in planner.tasks_for_day(settings, today(), next_lessons(conn)):
        conn.execute(
            "INSERT INTO tasks(day, title, module, link, minutes, done, source) VALUES (?, ?, ?, ?, ?, 0, 'plan')",
            (day, t["title"], t["module"], t["link"], t["minutes"]),
        )


def streak_days(conn):
    """连续打卡天数（今天还没打卡时，从昨天往前数）。"""
    days = {r["day"] for r in conn.execute("SELECT day FROM checkins")}
    d = today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def module_stats(conn):
    data = rows(conn, "SELECT module, COUNT(*) AS total, SUM(correct) AS correct, "
                      "AVG(seconds) AS avg_seconds FROM attempts GROUP BY module")
    for r in data:
        r["correct"] = r["correct"] or 0
        r["accuracy"] = round(r["correct"] / r["total"] * 100, 1) if r["total"] else 0
        r["avg_seconds"] = round(r["avg_seconds"] or 0)
    return data


def _per_day(conn, since):
    """since 起每天的做题数、做对数、学习分钟数 {day: (questions, correct, minutes)}。"""
    out = {}
    for r in conn.execute("SELECT substr(created_at,1,10) AS d, COUNT(*), COALESCE(SUM(correct),0) FROM attempts "
                          "WHERE created_at>=? GROUP BY d", (since,)):
        out[r[0]] = [r[1], r[2], 0]
    for r in conn.execute("SELECT day, COALESCE(SUM(minutes),0) FROM study_logs WHERE day>=? GROUP BY day", (since,)):
        out.setdefault(r[0], [0, 0, 0])[2] = r[1]
    return out


@route("GET", "/api/dashboard", write=True)
def dashboard(ctx):
    conn = ctx.conn
    settings = get_settings(conn)
    ensure_today_tasks(conn, settings)
    day = today_str()
    tasks = rows(conn, "SELECT * FROM tasks WHERE day=? ORDER BY id", (day,))
    total = conn.execute("SELECT COUNT(*), SUM(correct) FROM attempts").fetchone()
    start = (today() - timedelta(days=6)).isoformat()
    per = _per_day(conn, start)
    today_q = per.get(day, [0, 0, 0])
    minutes_total = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs").fetchone()[0]
    due_wrong = conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=0 AND next_review<=?", (day,)).fetchone()[0]
    due_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE due<=?", (day,)).fetchone()[0]
    week = []
    for i in range(6, -1, -1):
        d = (today() - timedelta(days=i)).isoformat()
        p = per.get(d, [0, 0, 0])
        week.append({"day": d, "minutes": p[2], "questions": p[0]})
    return {
        "today": day,
        "settings": settings,
        "phase": planner.current_phase(settings, today()),
        "milestones": planner.milestones(settings, today()),
        "tasks": tasks,
        "checked_in": bool(conn.execute("SELECT 1 FROM checkins WHERE day=?", (day,)).fetchone()),
        "streak": streak_days(conn),
        "checkin_total": conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0],
        "questions_total": total[0],
        "accuracy_total": round((total[1] or 0) / total[0] * 100, 1) if total[0] else 0,
        "questions_today": today_q[0],
        "correct_today": today_q[1],
        "minutes_today": today_q[2],
        "minutes_total": minutes_total,
        "due_wrong": due_wrong,
        "due_cards": due_cards,
        "modules": module_stats(conn),
        "week": week,
    }


@route("GET", "/api/plan")
def plan(ctx):
    s = get_settings(ctx.conn)
    return {
        "phases": planner.phases(s, today()),
        "current": planner.current_phase(s, today()),
        "milestones": planner.milestones(s, today()),
        "week": planner.week_preview(s, today()),
        "tasks": rows(ctx.conn, "SELECT * FROM tasks WHERE day=? ORDER BY id", (ctx.day,)),
    }


@route("POST", "/api/tasks/toggle")
def task_toggle(ctx):
    ctx.conn.execute("UPDATE tasks SET done=1-done WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


@route("POST", "/api/tasks/add")
def task_add(ctx):
    b = ctx.body
    ctx.conn.execute(
        "INSERT INTO tasks(day, title, module, link, minutes, done, source) VALUES (?, ?, ?, '', ?, 0, 'user')",
        (ctx.day, b["title"], b.get("module") or "自定义", int(b.get("minutes") or 0)),
    )
    return {"ok": True}


@route("POST", "/api/tasks/delete")
def task_delete(ctx):
    ctx.conn.execute("DELETE FROM tasks WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


@route("POST", "/api/checkin")
def checkin(ctx):
    ctx.conn.execute("INSERT OR REPLACE INTO checkins(day, note, created_at) VALUES (?, ?, ?)",
                     (ctx.day, ctx.body.get("note") or "", now_str()))
    return {"ok": True, "streak": streak_days(ctx.conn)}


def log_minutes(conn, module, minutes, source):
    if minutes > 0:
        conn.execute("INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, ?, ?, ?, ?)",
                     (today_str(), module, minutes, source, now_str()))


@route("POST", "/api/study_log")
def study_log(ctx):
    b = ctx.body
    log_minutes(ctx.conn, b.get("module") or "综合", int(b.get("minutes") or 0), b.get("source") or "计时")
    return {"ok": True}


# ---------------------------------------------------------------- 统计

@route("GET", "/api/stats")
def stats(ctx):
    conn = ctx.conn
    start = (today() - timedelta(days=29)).isoformat()
    per = _per_day(conn, start)
    days = []
    for i in range(29, -1, -1):
        d = (today() - timedelta(days=i)).isoformat()
        p = per.get(d, [0, 0, 0])
        days.append({"day": d, "questions": p[0], "correct": p[1], "minutes": p[2]})
    heat = rows(conn, "SELECT day, SUM(minutes) AS minutes FROM study_logs WHERE day>=? GROUP BY day",
                ((today() - timedelta(days=182)).isoformat(),))
    checkins = [r["day"] for r in conn.execute("SELECT day FROM checkins")]
    return {
        "modules": module_stats(conn),
        "days": days,
        "heat": heat,
        "checkins": checkins,
        "minutes_by_module": rows(
            conn, "SELECT module, SUM(minutes) AS minutes FROM study_logs GROUP BY module ORDER BY minutes DESC"),
        "sessions": rows(conn, "SELECT * FROM sessions ORDER BY id DESC LIMIT 30"),
        "speed": rows(conn, "SELECT * FROM speed_records ORDER BY id DESC LIMIT 30"),
        "essays": conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0],
        "interviews": conn.execute("SELECT COUNT(*) FROM interviews").fetchone()[0],
        "readings": conn.execute("SELECT COUNT(*) FROM reading_logs").fetchone()[0],
        "wrong_open": conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=0").fetchone()[0],
        "wrong_mastered": conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=1").fetchone()[0],
    }


# ---------------------------------------------------------------- 教程

def course_texts():
    """教程每一课的原文 {课 id: 文本}（按文件修改时间缓存）。"""
    out = {}
    if not COURSE_DIR.is_dir():
        return out
    for name in sorted(os.listdir(COURSE_DIR)):
        if not name.endswith(".md"):
            continue
        path = COURSE_DIR / name
        try:
            mt = path.stat().st_mtime
        except OSError:
            continue
        c = _course_cache.get(name)
        if not c or c[0] != mt:
            c = (mt, path.read_text(encoding="utf-8"))
            _course_cache[name] = c
        out[name[:-3]] = c[1]
    return out


def _course_done(conn):
    row = conn.execute("SELECT value FROM prefs WHERE key='course'").fetchone()
    return (json.loads(row["value"]) or {}).get("done", {}) if row else {}


def next_lessons(conn):
    """每门课程里下一节还没学完的课 {课程 id: {id, title, min}}。"""
    try:
        index = load_content(os.path.join("course", "index.json"))
    except (OSError, ValueError):
        return {}
    done = _course_done(conn)
    out = {}
    for c in index["courses"]:
        nl = next((lesson for lesson in c["lessons"] if lesson["id"] not in done), None)
        if nl:
            out[c["id"]] = nl
    return out


@route("GET", "/api/course/search")
def course_search(ctx):
    """在教程原文里找关键词，多个词用空格隔开时要求都出现。"""
    terms = [t for t in (ctx.q("q", "") or "").split() if t]
    hits = []
    if not terms:
        return {"hits": hits}
    for lid, text in course_texts().items():
        plain = re.sub(r"^:::.*$|[#*=>|`]", "", text, flags=re.M)
        if not all(t in plain for t in terms):
            continue
        pos = plain.find(terms[0])
        snippet = re.sub(r"\s+", " ", plain[max(0, pos - 50): pos + 90])
        hits.append({"id": lid, "snippet": snippet, "n": plain.count(terms[0])})
    hits.sort(key=lambda h: -h["n"])
    return {"hits": hits}


def course_deck(conn):
    """学完的课里的记忆卡（:::cards 块，每行“正面 :: 背面”）合成一个卡组。"""
    done = _course_done(conn)
    cards = []
    for lid, text in course_texts().items():
        if lid not in done:
            continue
        n = 0
        for block in re.findall(r"^:::\s*cards[^\n]*\n(.*?)^:::\s*$", text, flags=re.M | re.S):
            for line in block.splitlines():
                parts = re.split(r"\s*::\s*", line.strip(), maxsplit=1)
                if len(parts) == 2 and parts[0]:
                    n += 1
                    cards.append({"id": f"tut-{lid}-{n}", "front": re.sub(r"^[-*]\s+", "", parts[0]), "back": parts[1]})
    return {"id": "tutorial", "name": "教程知识卡", "cards": cards, "desc": "学完的教程课里的记忆卡，学完一课自动加入"}


@route("GET", "/api/decks")
def decks(ctx):
    lib = library.lib_decks().get("decks", []) + [x for x in [shizheng.chengyu_deck()] if x]
    return {"decks": [course_deck(ctx.conn)] + load_content("flashcards.json")["decks"] + lib, "lib_count": len(lib)}
