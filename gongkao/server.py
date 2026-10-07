"""本地数据服务：界面通过 HTTP 读写学习记录，只监听 127.0.0.1。

由 main.py 在后台线程里启动，窗口关闭时随进程一起退出。
"""

import itertools
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import ai, library, planner, qdb, shizheng
from . import docs as docmod
from .paths import content_dir, data_dir, web_dir

STATIC_DIR = str(web_dir())
CONTENT_DIR = str(content_dir())
DATA_DIR = str(data_dir())
DB_PATH = os.path.join(DATA_DIR, "app.db")
HOST = "127.0.0.1"
# 固定端口优先：界面的地址不变；被占用时换一个空闲端口
PREFERRED_PORT = int(os.environ.get("GONGKAO_PORT", "27315"))

# 本次运行的会话令牌：打开界面（index.html）时写进 Cookie（SameSite=Strict），之后的接口请求都要带上。
# 别的网站发来的请求带不上这个 Cookie（跨站 + 不同主机名），也就改不了设置、读不走数据。
SESSION_TOKEN = secrets.token_urlsafe(32)
SESSION_COOKIE = "gk_session"
# 不需要会话的接口：启动时检查是否已经在运行
PUBLIC_API = {"/api/ping"}

# 错题复习间隔（天）：做错后第 1、2、4、7、15、30 天各复习一次，全部答对即视为掌握
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
# 闪卡盒子间隔（天）：认识就升一盒，不认识回到第 1 盒
CARD_INTERVALS = [0, 1, 3, 7, 14, 30]

DEFAULT_SETTINGS = {
    "guokao_date": "2026-11-29",
    "shengkao_date": "2027-03-13",
    "start_date": "",
    "daily_hours": "4",
    "paper_level": "地市级",
    "nickname": "",
    "ai_provider": "",  # 空 = 老版本升级上来，按有没有 Key 推断（见 ai.config）
    "ai_model": "",
    "ai_base_url": "",
    "ai_api_key": "",
    # 资料文件夹：真题、讲义、题册放在这里，软件只读取不修改
    "library_root": library.DEFAULT_ROOT if os.path.isdir(library.DEFAULT_ROOT) else "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, title TEXT, total INTEGER,
    correct INTEGER, duration INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, qid TEXT, module TEXT,
    chosen INTEGER, correct INTEGER, seconds INTEGER, mode TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS wrongbook (
    qid TEXT PRIMARY KEY, module TEXT, wrong_count INTEGER DEFAULT 0,
    last_wrong_at TEXT, stage INTEGER DEFAULT 0, next_review TEXT,
    mastered INTEGER DEFAULT 0, reason TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS favorites (qid TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE IF NOT EXISTS qnotes (qid TEXT PRIMARY KEY, text TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, title TEXT, module TEXT,
    link TEXT, minutes INTEGER DEFAULT 0, done INTEGER DEFAULT 0, source TEXT);
CREATE TABLE IF NOT EXISTS checkins (day TEXT PRIMARY KEY, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS study_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, module TEXT, minutes INTEGER,
    source TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS essays (
    id INTEGER PRIMARY KEY AUTOINCREMENT, set_id TEXT, q_index INTEGER, answer TEXT,
    words INTEGER, seconds INTEGER, self_score REAL, checked TEXT, ai_feedback TEXT,
    created_at TEXT);
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, qid TEXT, answer TEXT, seconds INTEGER,
    ai_feedback TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, content TEXT,
    tags TEXT, source TEXT, created_at TEXT, box INTEGER DEFAULT 1, due TEXT);
CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY, deck TEXT, box INTEGER DEFAULT 1, due TEXT,
    reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS speed_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, total INTEGER, correct INTEGER,
    seconds INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS reading_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, title TEXT, source TEXT,
    summary TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS lib_progress (
    fid TEXT PRIMARY KEY, rel TEXT, page INTEGER DEFAULT 0, done INTEGER DEFAULT 0, fav INTEGER DEFAULT 0,
    note TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS doc_progress (
    doc TEXT PRIMARY KEY, seq INTEGER DEFAULT 0, pct REAL DEFAULT 0, done INTEGER DEFAULT 0,
    fav INTEGER DEFAULT 0, opened_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS doc_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT, seq INTEGER, start INTEGER, end_seq INTEGER,
    end INTEGER, text TEXT, color TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS doc_quiz (
    doc TEXT, qkey TEXT, choice TEXT, correct INTEGER, created_at TEXT, PRIMARY KEY (doc, qkey));
CREATE TABLE IF NOT EXISTS memo_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, sort INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS memo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER, title TEXT DEFAULT '', content TEXT,
    note TEXT DEFAULT '', source TEXT DEFAULT '', doc TEXT DEFAULT '', seq INTEGER,
    star INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
"""

# 导出/导入时包含的表
USER_TABLES = [
    "settings", "sessions", "attempts", "wrongbook", "favorites", "qnotes", "tasks",
    "checkins", "study_logs", "essays", "interviews", "notebook", "cards",
    "speed_records", "reading_logs", "chats", "prefs", "lib_progress", "doc_progress", "doc_marks",
    "doc_quiz", "memo_books", "memo_items",
]

# 笔记本第一次打开时准备好的本子
DEFAULT_MEMO_BOOKS = ["公式本", "知识点本"]

_db_lock = threading.Lock()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return date.today()


def today_str():
    return today().isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    """打开连接，结束时提交（出错则回滚）并关闭。"""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        conn.execute(
            "UPDATE settings SET value=? WHERE key='start_date' AND value=''", (today_str(),)
        )


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_settings(conn, include_secret=False):
    s = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    if not include_secret:
        key = s.get("ai_api_key") or ""
        s["ai_api_key"] = ""  # 完整 Key 不回传给界面，只给一个掩码提示
        s["ai_key_saved"] = bool(key)
        s["ai_key_hint"] = f"{key[:3]}****{key[-4:]}" if len(key) > 8 else ("****" if key else "")
    return s


def load_content(name):
    with open(os.path.join(CONTENT_DIR, name), encoding="utf-8") as f:
        return json.load(f)


CUSTOM_BANK = os.path.join(DATA_DIR, "custom_questions.json")


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


MORE_DIR = os.path.join(CONTENT_DIR, "questions_more")


def _more_files():
    try:
        return sorted(os.path.join(MORE_DIR, n) for n in os.listdir(MORE_DIR) if n.endswith(".json"))
    except OSError:
        return []


def load_bank():
    """内置题库 + 用户导入的题库（题量小，放内存）。真题卷和题册在 library/questions.db 里。

    内置题 = questions.json + questions_more/*.json（按专题分文件；数量、资料的计算题由 tools/gen_questions.py 生成）。
    """
    bank = load_content("questions.json")
    ids = {q["id"] for q in bank["questions"]}
    for path in _more_files():
        with open(path, encoding="utf-8") as f:
            more = json.load(f)
        bank["questions"] += [q for q in more.get("questions", []) if q["id"] not in ids]
        bank["materials"] += more.get("materials", [])
        ids |= {q["id"] for q in more.get("questions", [])}
    bank["custom_count"] = 0
    if os.path.isfile(CUSTOM_BANK):
        with open(CUSTOM_BANK, encoding="utf-8") as f:
            custom = json.load(f)
        ids = {q["id"] for q in bank["questions"]}
        extra = [q for q in custom.get("questions", []) if q["id"] not in ids]
        bank["questions"] += extra
        bank["materials"] += custom.get("materials", [])
        bank["custom_count"] = len(extra)
    return bank


BANK = qdb.Bank(load_bank)
_bank_lock = threading.Lock()


def bank():
    """题库索引（内置 + 导入 + 数据库），文件有变化时自动重新加载。"""
    with _bank_lock:
        BANK.refresh((_mtime(os.path.join(CONTENT_DIR, "questions.json")), _mtime(CUSTOM_BANK),
                      tuple(_mtime(p) for p in _more_files())))
        return BANK


def user_progress(conn):
    """选题要用的个人状态：做过的题（最近一次时间）、没掌握的错题、收藏。"""
    done = {r["qid"]: r["last"] for r in conn.execute("SELECT qid, MAX(created_at) AS last FROM attempts GROUP BY qid")}
    wrong = {r["qid"] for r in conn.execute("SELECT qid FROM wrongbook WHERE mastered=0")}
    favs = {r["qid"] for r in conn.execute("SELECT qid FROM favorites")}
    return {"done": done, "wrong": wrong, "favorites": favs}


def bank_meta():
    b = bank()
    return {"counts": b.counts(), "custom_count": b.custom_count, "sources": b.sources}


def bank_summary(conn, f):
    """按来源/年份/题源筛选后，各模块、题型的题量和做过的题数。"""
    b = bank()
    rows = b.filtered({**f, "module": "全部", "sub": "全部"})
    done = {r["qid"] for r in conn.execute("SELECT DISTINCT qid FROM attempts")}
    mods = {}
    for r in rows:
        m = mods.setdefault(r[1], {"total": 0, "done": 0, "subs": {}})
        m["total"] += 1
        m["done"] += 1 if r[0] in done else 0
        m["subs"][r[2]] = m["subs"].get(r[2], 0) + 1
    picked = b.filtered(f)
    order = f.get("order")
    if order == "wrong":
        wrong = {r["qid"] for r in conn.execute("SELECT qid FROM wrongbook WHERE mastered=0")}
        picked = [r for r in picked if r[0] in wrong]
    elif order == "fav":
        favs = {r["qid"] for r in conn.execute("SELECT qid FROM favorites")}
        picked = [r for r in picked if r[0] in favs]
    return {"total": len(rows), "modules": mods, "matching": len(picked),
            "matching_done": sum(1 for r in picked if r[0] in done)}


MODULES = ["政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"]


def import_bank(payload):
    """校验并合并用户导入的题目，保存到 data/custom_questions.json。"""
    qs = payload.get("questions")
    if not isinstance(qs, list) or not qs:
        raise ValueError("文件里没有 questions 列表")
    mats = payload.get("materials") or []
    mat_ids = {m.get("id") for m in mats}
    errors = []
    for i, q in enumerate(qs, 1):
        where = f"第 {i} 题（id={q.get('id')}）"
        if not q.get("id") or not q.get("stem"):
            errors.append(where + "缺少 id 或 stem")
        elif q.get("module") not in MODULES:
            errors.append(where + "module 必须是：" + "、".join(MODULES))
        elif not isinstance(q.get("options"), list) or len(q["options"]) != 4:
            errors.append(where + "options 必须是 4 个选项")
        elif q.get("answer") not in (0, 1, 2, 3):
            errors.append(where + "answer 必须是 0–3（对应 A–D）")
        elif q.get("material") and q["material"] not in mat_ids:
            errors.append(where + "引用的 material 不存在")
        if len(errors) >= 5:
            break
    if errors:
        raise ValueError("；".join(errors))
    current = {"materials": [], "questions": []}
    if os.path.isfile(CUSTOM_BANK) and not payload.get("replace"):
        with open(CUSTOM_BANK, encoding="utf-8") as f:
            current = json.load(f)
    by_id = {q["id"]: q for q in current["questions"]}
    for q in qs:
        q.setdefault("sub", "导入题")
        q.setdefault("explain", "")
        q["custom"] = True
        by_id[q["id"]] = q
    mby = {m["id"]: m for m in current["materials"]}
    for m in mats:
        mby[m["id"]] = m
    out = {"materials": list(mby.values()), "questions": list(by_id.values())}
    with open(CUSTOM_BANK, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return {"ok": True, "imported": len(qs), "total_custom": len(out["questions"])}


def parse_day(s, fallback):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------- 业务逻辑

def ensure_today_tasks(conn, settings):
    """当天第一次打开时，按复习计划生成今日任务。"""
    day = today_str()
    exists = conn.execute(
        "SELECT 1 FROM tasks WHERE day=? AND source='plan' LIMIT 1", (day,)
    ).fetchone()
    if exists:
        return
    for t in planner.tasks_for_day(settings, today(), next_lessons(conn)):
        conn.execute(
            "INSERT INTO tasks(day, title, module, link, minutes, done, source) "
            "VALUES (?, ?, ?, ?, ?, 0, 'plan')",
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
    data = rows(
        conn,
        "SELECT module, COUNT(*) AS total, SUM(correct) AS correct, "
        "AVG(seconds) AS avg_seconds FROM attempts GROUP BY module",
    )
    for r in data:
        r["correct"] = r["correct"] or 0
        r["accuracy"] = round(r["correct"] / r["total"] * 100, 1) if r["total"] else 0
        r["avg_seconds"] = round(r["avg_seconds"] or 0)
    return data


def dashboard(conn):
    settings = get_settings(conn)
    ensure_today_tasks(conn, settings)
    day = today_str()
    tasks = rows(conn, "SELECT * FROM tasks WHERE day=? ORDER BY id", (day,))
    total = conn.execute("SELECT COUNT(*), SUM(correct) FROM attempts").fetchone()
    today_q = conn.execute(
        "SELECT COUNT(*), SUM(correct) FROM attempts WHERE substr(created_at,1,10)=?", (day,)
    ).fetchone()
    minutes_today = conn.execute(
        "SELECT COALESCE(SUM(minutes),0) FROM study_logs WHERE day=?", (day,)
    ).fetchone()[0]
    minutes_total = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs").fetchone()[0]
    due_wrong = conn.execute(
        "SELECT COUNT(*) FROM wrongbook WHERE mastered=0 AND next_review<=?", (day,)
    ).fetchone()[0]
    due_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE due<=?", (day,)).fetchone()[0]
    week = []
    for i in range(6, -1, -1):
        d = (today() - timedelta(days=i)).isoformat()
        m = conn.execute(
            "SELECT COALESCE(SUM(minutes),0) FROM study_logs WHERE day=?", (d,)
        ).fetchone()[0]
        q = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE substr(created_at,1,10)=?", (d,)
        ).fetchone()[0]
        week.append({"day": d, "minutes": m, "questions": q})
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
        "correct_today": today_q[1] or 0,
        "minutes_today": minutes_today,
        "minutes_total": minutes_total,
        "due_wrong": due_wrong,
        "due_cards": due_cards,
        "modules": module_stats(conn),
        "week": week,
    }


def record_attempts(conn, payload):
    """保存一次练习：写入 attempts，并更新错题本。"""
    items = payload.get("items") or []
    mode = payload.get("mode") or "practice"
    created = now_str()
    correct_n = sum(1 for it in items if it.get("correct"))
    cur = conn.execute(
        "INSERT INTO sessions(mode, title, total, correct, duration, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mode, payload.get("title") or "", len(items), correct_n,
         int(payload.get("duration") or 0), created),
    )
    session_id = cur.lastrowid
    day = today()
    for it in items:
        qid = str(it["qid"])
        ok = 1 if it.get("correct") else 0
        conn.execute(
            "INSERT INTO attempts(session_id, qid, module, chosen, correct, seconds, mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, qid, it.get("module"), it.get("chosen"), ok,
             int(it.get("seconds") or 0), mode, created),
        )
        row = conn.execute("SELECT * FROM wrongbook WHERE qid=?", (qid,)).fetchone()
        if not ok:
            nxt = (day + timedelta(days=REVIEW_INTERVALS[0])).isoformat()
            if row:
                conn.execute(
                    "UPDATE wrongbook SET wrong_count=wrong_count+1, last_wrong_at=?, stage=0, "
                    "next_review=?, mastered=0 WHERE qid=?",
                    (created, nxt, qid),
                )
            else:
                conn.execute(
                    "INSERT INTO wrongbook(qid, module, wrong_count, last_wrong_at, stage, next_review) "
                    "VALUES (?, ?, 1, ?, 0, ?)",
                    (qid, it.get("module"), created, nxt),
                )
        elif row and not row["mastered"]:
            # 只有到期后答对才推进阶段，避免同一天反复刷同一题就“掌握”
            if (row["next_review"] or "") <= day.isoformat():
                stage = row["stage"] + 1
                if stage >= len(REVIEW_INTERVALS):
                    conn.execute(
                        "UPDATE wrongbook SET stage=?, mastered=1 WHERE qid=?", (stage, qid)
                    )
                else:
                    nxt = (day + timedelta(days=REVIEW_INTERVALS[stage])).isoformat()
                    conn.execute(
                        "UPDATE wrongbook SET stage=?, next_review=? WHERE qid=?",
                        (stage, nxt, qid),
                    )
    minutes = round(int(payload.get("duration") or 0) / 60)
    if minutes > 0:
        modules = {it.get("module") for it in items}
        module = modules.pop() if len(modules) == 1 else "综合"
        conn.execute(
            "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (day.isoformat(), module, minutes, "刷题", created),
        )
    return {"session_id": session_id, "correct": correct_n, "total": len(items)}


def review_card(conn, payload):
    card_id = str(payload["card_id"])
    known = bool(payload.get("known"))
    row = conn.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
    box = row["box"] if row else 1
    reps = (row["reps"] if row else 0) + 1
    lapses = (row["lapses"] if row else 0) + (0 if known else 1)
    box = min(box + 1, len(CARD_INTERVALS) - 1) if known else 1
    due = (today() + timedelta(days=CARD_INTERVALS[box])).isoformat()
    conn.execute(
        "INSERT INTO cards(card_id, deck, box, due, reps, lapses, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(card_id) DO UPDATE SET "
        "box=excluded.box, due=excluded.due, reps=excluded.reps, lapses=excluded.lapses, "
        "updated_at=excluded.updated_at",
        (card_id, payload.get("deck"), box, due, reps, lapses, now_str()),
    )
    return {"box": box, "due": due}


def stats(conn):
    days = []
    for i in range(29, -1, -1):
        d = (today() - timedelta(days=i)).isoformat()
        q = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts WHERE substr(created_at,1,10)=?",
            (d,),
        ).fetchone()
        m = conn.execute(
            "SELECT COALESCE(SUM(minutes),0) FROM study_logs WHERE day=?", (d,)
        ).fetchone()[0]
        days.append({"day": d, "questions": q[0], "correct": q[1], "minutes": m})
    heat = rows(
        conn,
        "SELECT day, SUM(minutes) AS minutes FROM study_logs "
        "WHERE day>=? GROUP BY day",
        ((today() - timedelta(days=182)).isoformat(),),
    )
    checkins = [r["day"] for r in conn.execute("SELECT day FROM checkins")]
    return {
        "modules": module_stats(conn),
        "days": days,
        "heat": heat,
        "checkins": checkins,
        "minutes_by_module": rows(
            conn,
            "SELECT module, SUM(minutes) AS minutes FROM study_logs GROUP BY module ORDER BY minutes DESC",
        ),
        "sessions": rows(conn, "SELECT * FROM sessions ORDER BY id DESC LIMIT 30"),
        "speed": rows(conn, "SELECT * FROM speed_records ORDER BY id DESC LIMIT 30"),
        "essays": conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0],
        "interviews": conn.execute("SELECT COUNT(*) FROM interviews").fetchone()[0],
        "readings": conn.execute("SELECT COUNT(*) FROM reading_logs").fetchone()[0],
        "wrong_open": conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=0").fetchone()[0],
        "wrong_mastered": conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=1").fetchone()[0],
    }


def real_progress(conn):
    """每个题源（真题卷、千题册）：做过多少题、做对多少题（按每题最近一次作答计）。"""
    latest = {}
    for r in conn.execute("SELECT qid, correct FROM attempts ORDER BY id"):
        latest[r["qid"]] = r["correct"]
    src_of = {r[0]: r[5] for r in bank().index}
    out = {}
    for qid, ok in latest.items():
        sid = src_of.get(qid)
        if not sid:
            continue
        o = out.setdefault(sid, {"done": 0, "correct": 0})
        o["done"] += 1
        o["correct"] += 1 if ok else 0
    return out


COURSE_DIR = os.path.join(CONTENT_DIR, "course")
_course_cache = {}


def course_texts():
    """教程每一课的原文 {课 id: 文本}（按文件修改时间缓存）。"""
    out = {}
    if not os.path.isdir(COURSE_DIR):
        return out
    for name in sorted(os.listdir(COURSE_DIR)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(COURSE_DIR, name)
        mt = _mtime(path)
        c = _course_cache.get(name)
        if not c or c[0] != mt:
            with open(path, encoding="utf-8") as f:
                c = (mt, f.read())
            _course_cache[name] = c
        out[name[:-3]] = c[1]
    return out


def next_lessons(conn):
    """每门课程里下一节还没学完的课 {课程 id: {id, title, min}}。"""
    try:
        index = load_content(os.path.join("course", "index.json"))
    except (OSError, ValueError):
        return {}
    row = conn.execute("SELECT value FROM prefs WHERE key='course'").fetchone()
    done = (json.loads(row["value"]) or {}).get("done", {}) if row else {}
    out = {}
    for c in index["courses"]:
        nl = next((l for l in c["lessons"] if l["id"] not in done), None)
        if nl:
            out[c["id"]] = nl
    return out


def course_search(q):
    """在教程原文里找关键词，多个词用空格隔开时要求都出现。"""
    terms = [t for t in (q or "").split() if t]
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
    row = conn.execute("SELECT value FROM prefs WHERE key='course'").fetchone()
    done = (json.loads(row["value"]) or {}).get("done", {}) if row else {}
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
    return {"id": "tutorial", "name": "教程知识卡", "cards": cards,
            "desc": "学完的教程课里的记忆卡，学完一课自动加入"}


def essay_sets():
    data = load_content("essays.json")
    more = load_content("essays_more.json")["sets"] if os.path.exists(os.path.join(CONTENT_DIR, "essays_more.json")) else []
    real = [{**x, "fid": library.fid_of(x["file"])} for x in library.real_essays().get("sets", [])]
    return {"note": data.get("note", ""), "sets": data["sets"] + more + real, "real_count": len(real)}


def docs_overview(conn):
    """资料库首页：文档列表、阅读进度、标注数量。"""
    prog = {r["doc"]: dict(r) for r in conn.execute("SELECT * FROM doc_progress")}
    marks = {r[0]: r[1] for r in conn.execute("SELECT doc, COUNT(*) FROM doc_marks GROUP BY doc")}
    cat = library.load_catalog()
    return {"docs": docmod.doc_list(), "groups": docmod.GROUPS, "progress": prog, "marks": marks, "root": cat.get("root", ""),
            "scanned_at": cat.get("scanned_at", ""), "total_files": len(docmod.selected(cat.get("files", [])))}


def news_overview(conn):
    """时政晨读首页：资料列表 + 阅读进度、成语积累日历和每天的掌握情况（prefs 里的 cy_marks）。"""
    data = shizheng.overview()
    ids = {it["id"] for it in data["items"]}
    data["progress"] = {r["doc"]: dict(r) for r in conn.execute("SELECT * FROM doc_progress") if r["doc"] in ids}
    data["marks"] = {r[0]: r[1] for r in conn.execute("SELECT doc, COUNT(*) FROM doc_marks GROUP BY doc") if r[0] in ids}
    data["job"] = library.jobs.status()
    return data


def library_overview(conn):
    cat = library.load_catalog()
    files = cat.get("files", [])
    prog = {r["fid"]: dict(r) for r in conn.execute("SELECT * FROM lib_progress")}
    b = bank()
    c = b.counts()
    return {
        "root": cat.get("root", ""), "scanned_at": cat.get("scanned_at", ""), "files": files,
        "progress": prog, "text_index": library.text_index_info(),
        "real": {"papers": sum(1 for x in b.sources if x["kind"] == "paper"), "questions": c["国考"] + c["四川"],
                 "books": sum(1 for x in b.sources if x["kind"] == "book"), "book_questions": c["千题册"],
                 "essays": len(library.real_essays().get("sets", [])),
                 "decks": len(library.lib_decks().get("decks", []))},
    }


def memo_books(conn):
    empty = not conn.execute("SELECT 1 FROM memo_books LIMIT 1").fetchone()
    if empty and not conn.execute("SELECT 1 FROM memo_items LIMIT 1").fetchone():
        for i, name in enumerate(DEFAULT_MEMO_BOOKS):
            conn.execute("INSERT INTO memo_books(name, sort, created_at) VALUES (?, ?, ?)", (name, i, now_str()))
    return rows(conn, "SELECT * FROM memo_books ORDER BY sort, id")


def memo_all(conn):
    return {
        "books": memo_books(conn),
        "items": rows(conn, "SELECT * FROM memo_items ORDER BY star DESC, id DESC"),
    }


def memo_save(conn, body):
    """新建或修改一条笔记本条目；只改传进来的字段（置顶、移本子时不用带全部内容）。"""
    fields = ["book", "title", "content", "note", "source", "doc", "seq", "star"]
    if body.get("id"):
        sets = [f for f in fields if f in body]
        if sets:
            conn.execute(
                f"UPDATE memo_items SET {', '.join(f + '=?' for f in sets)}, updated_at=? WHERE id=?",
                [body[f] for f in sets] + [now_str(), body["id"]],
            )
        return {"id": body["id"]}
    if not (body.get("content") or "").strip():
        raise ValueError("内容不能为空")
    if not conn.execute("SELECT 1 FROM memo_books WHERE id=?", (body.get("book"),)).fetchone():
        raise ValueError("这个笔记本不存在了，换一个试试")
    same = conn.execute(
        "SELECT id FROM memo_items WHERE book=? AND content=?", (body["book"], body["content"].strip())
    ).fetchone()
    if same:  # 同一段内容不重复记
        return {"id": same["id"], "dup": True}
    cur = conn.execute(
        "INSERT INTO memo_items(book, title, content, note, source, doc, seq, star, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (body["book"], body.get("title") or "", body["content"].strip(), body.get("note") or "",
         body.get("source") or "", body.get("doc") or "", body.get("seq"), now_str(), now_str()),
    )
    return {"id": cur.lastrowid}


def export_all(conn):
    out = {"app": "gongkao-prep", "exported_at": now_str(), "tables": {}}
    for t in USER_TABLES:
        out["tables"][t] = rows(conn, f"SELECT * FROM {t}")
    for r in out["tables"]["settings"]:
        if r["key"] == "ai_api_key":
            r["value"] = ""  # 备份文件里不带密钥
    return out


def import_all(conn, data):
    tables = (data or {}).get("tables") or {}
    for t in USER_TABLES:
        if t not in tables:
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if t == "settings":
            for r in tables[t]:
                if r.get("key") == "ai_api_key":
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    (r.get("key"), r.get("value")),
                )
            continue
        conn.execute(f"DELETE FROM {t}")
        for r in tables[t]:
            keys = [k for k in r if k in cols]
            if not keys:
                continue
            conn.execute(
                f"INSERT INTO {t}({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                [r[k] for k in keys],
            )
    return {"ok": True}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "GongkaoPrep/1.0"

    def log_message(self, fmt, *args):
        # send_error 传进来的第一个参数是状态码（HTTPStatus），不是请求行
        if "/api/" in str(args[0] if args else "") and sys.stderr:
            sys.stderr.write("%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    # ---- helpers
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def send_file(self, path, set_session=False):
        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if set_session:
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def safe_join(self, base, rel):
        base = os.path.abspath(base)
        p = os.path.abspath(os.path.join(base, rel))
        try:
            return p if os.path.commonpath([base, p]) == base else None
        except ValueError:  # 不在同一个盘
            return None

    # ---- 访问控制：只接受本机界面发来的请求
    def host_ok(self):
        """Host 必须是本机地址（防 DNS 重绑定：恶意域名解析到 127.0.0.1 时，Host 是那个域名）。"""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}") or host in getattr(self.server, "extra_hosts", ())

    def session_ok(self):
        try:
            m = SimpleCookie(self.headers.get("Cookie") or "").get(SESSION_COOKIE)
        except Exception:  # noqa: BLE001 —— 格式错误的 Cookie 当作没带
            return False
        return bool(m) and secrets.compare_digest(m.value, SESSION_TOKEN)

    def post_ok(self):
        """写接口额外要求：JSON 请求体（跨站的表单、简单请求发不出来），来源是本页面。"""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        origin = (self.headers.get("Origin") or "").lower()
        if origin and origin != "http://" + (self.headers.get("Host") or "").strip().lower():
            return False
        return (self.headers.get("Sec-Fetch-Site") or "same-origin") in ("same-origin", "none")

    def deny(self, why):
        if sys.stderr:
            sys.stderr.write(f"{datetime.now():%H:%M:%S}  拒绝 {self.command} {self.path}：{why}\n")
        self.send_json({"error": "请求被拒绝：" + why}, 403)

    def guard(self, path):
        """放行返回 True；不放行时已经回了 403。"""
        if not self.host_ok():
            self.deny("只接受本机访问")
            return False
        if path.startswith("/api/") and path not in PUBLIC_API and not self.session_ok():
            self.deny("会话无效，请重新打开软件窗口")
            return False
        if self.command == "POST" and not self.post_ok():
            self.deny("来源不明")
            return False
        return True

    # ---- routing
    def send_bytes(self, body, ctype, cache="no-cache", extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_crop(self, rest):
        """/api/crop/<文件id>/<页>/<x0,y0,x1,y1>.png —— 题目在原卷上的截图。"""
        m = re.match(r"^([\w-]+)/(\d+)/([\d.]+),([\d.]+),([\d.]+),([\d.]+)\.png$", rest)
        if not m:
            return self.send_error(HTTPStatus.BAD_REQUEST)
        target, _f = library.resolve(m.group(1))
        if not target:
            return self.send_error(HTTPStatus.NOT_FOUND)
        clip = tuple(float(m.group(i)) for i in range(3, 7))
        png = library.render_png(target, int(m.group(2)), clip=clip, zoom=2.2)
        self.send_bytes(png, "image/png", cache="max-age=86400")

    def send_docimg(self, rel):
        """/api/docimg/<文件id>/<图片名> —— 资料库文档里的插图。"""
        if not re.fullmatch(r"[\w-]+/[\w.-]+\.(jpg|jpeg|png|gif|bmp)", rel or ""):
            return self.send_error(HTTPStatus.BAD_REQUEST)
        path = docmod.IMG_DIR / rel
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_bytes(path.read_bytes(), mimetypes.guess_type(str(path))[0] or "image/jpeg", cache="max-age=86400")

    def send_page(self, query):
        """/api/library/page?fid=…&p=… —— 资料某一页的整页图片（扫描件、缩略预览用）。"""
        target, _f = library.resolve((query.get("fid") or [""])[0])
        if not target or not target.lower().endswith(".pdf"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        zoom = min(3.0, max(0.3, float((query.get("z") or ["1.6"])[0])))
        png = library.render_png(target, int((query.get("p") or ["0"])[0]), zoom=zoom)
        self.send_bytes(png, "image/png", cache="max-age=86400")

    def send_source(self, fid):
        """原文件（PDF 等），支持 Range，内置 PDF 阅读器可以边下边看几百页的大文件。"""
        target, f = library.resolve(fid)
        if not target:
            return self.send_error(HTTPStatus.NOT_FOUND)
        size = os.path.getsize(target)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        from urllib.parse import quote
        self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + quote(os.path.basename(target)))
        self.end_headers()
        try:
            with open(target, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_HEAD(self):
        """PDF 阅读器会先发 HEAD 探文件大小和是否支持分段下载。"""
        path = unquote(urlparse(self.path).path)
        if not self.guard(path):
            return
        target = None
        if path.startswith("/api/library/file/"):
            target, _f = library.resolve(path[len("/api/library/file/"):].split("/")[0])
            if not target:
                return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_response(200)
        if target:
            self.send_header("Content-Type", mimetypes.guess_type(target)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(os.path.getsize(target)))
        else:
            self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if not self.guard(path):
            return
        try:
            if path.startswith("/api/crop/"):
                return self.send_crop(path[len("/api/crop/"):])
            if path.startswith("/api/docimg/"):
                return self.send_docimg(path[len("/api/docimg/"):])
            if path == "/api/library/page":
                return self.send_page(parse_qs(url.query))
            if path.startswith("/api/library/file/"):
                return self.send_source(path[len("/api/library/file/"):].split("/")[0])
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 500)
        if path.startswith("/api/"):
            return self.handle_api("GET", path, parse_qs(url.query), None)
        if path.startswith("/content/"):
            p = self.safe_join(CONTENT_DIR, path[len("/content/"):])
            return self.send_file(p) if p else self.send_error(HTTPStatus.FORBIDDEN)
        rel = path.lstrip("/") or "index.html"
        p = self.safe_join(STATIC_DIR, rel)
        if not p:
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not os.path.isfile(p):
            p = os.path.join(STATIC_DIR, "index.html")
        self.send_file(p, set_session=os.path.basename(p) == "index.html")

    def do_POST(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        if not self.guard(path):
            return
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError):
            return self.send_json({"error": "请求内容不是有效的 JSON"}, 400)
        if path.startswith("/api/ai/"):
            return self.handle_ai(path[len("/api/ai/"):], body)
        return self.handle_api("POST", path, parse_qs(url.query), body)

    def handle_api(self, method, path, query, body):
        try:
            with _db_lock, db() as conn:
                result = self.dispatch(conn, method, path, query, body or {})
        except KeyError as e:
            return self.send_json({"error": f"缺少参数：{e}"}, 400)
        except Exception as e:  # noqa: BLE001 —— 本地单用户应用，把错误原样告诉前端
            return self.send_json({"error": str(e)}, 500)
        if result is None:
            return self.send_json({"error": "接口不存在"}, 404)
        self.send_json(result)

    def dispatch(self, conn, method, path, query, body):
        q = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731
        day = today_str()

        if method == "GET":
            if path == "/api/ping":
                return {"app": "gongkao-prep"}
            if path == "/api/dashboard":
                return dashboard(conn)
            if path == "/api/settings":
                return get_settings(conn)
            if path == "/api/plan":
                s = get_settings(conn)
                return {
                    "phases": planner.phases(s, today()),
                    "current": planner.current_phase(s, today()),
                    "milestones": planner.milestones(s, today()),
                    "week": planner.week_preview(s, today()),
                    "tasks": rows(conn, "SELECT * FROM tasks WHERE day=? ORDER BY id", (day,)),
                }
            if path == "/api/bank/meta":
                return bank_meta()
            if path == "/api/real/progress":
                return real_progress(conn)
            if path == "/api/essay_sets":
                return essay_sets()
            if path == "/api/decks":
                lib = library.lib_decks().get("decks", []) + [x for x in [shizheng.chengyu_deck()] if x]
                return {"decks": [course_deck(conn)] + load_content("flashcards.json")["decks"] + lib, "lib_count": len(lib)}
            if path == "/api/library":
                return library_overview(conn)
            if path == "/api/library/search":
                fids = set(filter(None, (q("fids") or "").split(","))) or None
                return library.search(q("q", ""), fids=fids)
            if path == "/api/jobs":
                return library.jobs.status()
            if path == "/api/docs":
                return docs_overview(conn)
            if path == "/api/news":
                return news_overview(conn)
            if path == "/api/news/chengyu":
                dates = [x for x in (q("dates") or "").split(",") if x]
                return shizheng.chengyu(q("month"), dates or None)
            if path == "/api/news/chengyu_all":
                return shizheng.chengyu_all()
            if path == "/api/news/quiz":
                return shizheng.quiz(int(q("n") or 20), q("since") or "", q("src") or "")
            if path == "/api/news/search":
                return {"hits": shizheng.search(q("q", ""))}
            if path == "/api/docs/get":
                d = docmod.doc_get(q("id", "")) or shizheng.doc_get(q("id", ""))
                if not d:
                    return {"error": "没有找到这份资料，可能还没整理完"}
                row = conn.execute("SELECT * FROM doc_progress WHERE doc=?", (d["id"],)).fetchone()
                d["progress"] = dict(row) if row else {"seq": 0, "pct": 0, "done": 0, "fav": 0}
                d["marks"] = rows(conn, "SELECT * FROM doc_marks WHERE doc=? ORDER BY seq, start", (d["id"],))
                d["quiz"] = {r["qkey"]: {"choice": r["choice"], "correct": r["correct"]}
                             for r in conn.execute("SELECT * FROM doc_quiz WHERE doc=?", (d["id"],))}
                conn.execute("INSERT INTO doc_progress(doc, opened_at, updated_at) VALUES (?, ?, ?) "
                             "ON CONFLICT(doc) DO UPDATE SET opened_at=excluded.opened_at", (d["id"], now_str(), now_str()))
                return d
            if path == "/api/sucai":
                from . import sucai
                return sucai.load()
            if path == "/api/docs/search":
                if q("doc") and q("doc") in shizheng.titles():
                    return {"hits": shizheng.search(q("q", ""), q("doc"))}
                return {"hits": docmod.search(q("q", ""), q("doc") or None)}
            if path == "/api/docmarks":
                titles = {**shizheng.titles(), **{d["id"]: d["title"] for d in docmod.doc_list()}}
                items = rows(conn, "SELECT * FROM doc_marks ORDER BY id DESC")
                for m in items:
                    m["title"] = titles.get(m["doc"], "（资料已移除）")
                return {"items": items}
            if path == "/api/course/search":
                return course_search(q("q", ""))
            if path == "/api/progress":
                # 刷题页需要的个人状态：做过的题、错题、收藏、笔记
                done = rows(
                    conn,
                    "SELECT qid, COUNT(*) AS n, SUM(correct) AS ok, MAX(created_at) AS last "
                    "FROM attempts GROUP BY qid",
                )
                return {
                    "done": {r["qid"]: r for r in done},
                    "wrong": {r["qid"]: r for r in rows(conn, "SELECT * FROM wrongbook")},
                    "favorites": [r["qid"] for r in conn.execute("SELECT qid FROM favorites")],
                    "notes": {r["qid"]: r["text"] for r in conn.execute("SELECT qid, text FROM qnotes")},
                }
            if path == "/api/wrongbook":
                return {
                    "items": rows(conn, "SELECT * FROM wrongbook ORDER BY mastered, next_review"),
                    "today": day,
                }
            if path == "/api/stats":
                return stats(conn)
            if path == "/api/essays":
                return {"items": rows(conn, "SELECT * FROM essays ORDER BY id DESC")}
            if path == "/api/interviews":
                return {"items": rows(conn, "SELECT * FROM interviews ORDER BY id DESC")}
            if path == "/api/notebook":
                return {"items": rows(conn, "SELECT * FROM notebook ORDER BY id DESC")}
            if path == "/api/memo":
                return memo_all(conn)
            if path == "/api/memo/books":
                return {"books": memo_books(conn)}
            if path == "/api/cards":
                return {"items": rows(conn, "SELECT * FROM cards"), "today": day}
            if path == "/api/reading":
                return {"items": rows(conn, "SELECT * FROM reading_logs ORDER BY id DESC LIMIT 200")}
            if path == "/api/chats":
                return {"items": rows(conn, "SELECT * FROM chats ORDER BY id DESC LIMIT 60")[::-1]}
            if path == "/api/prefs":
                return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM prefs")}
            if path == "/api/export":
                return export_all(conn)
            if path == "/api/ai/presets":
                return ai.PRESETS
            if path == "/api/ai/status":
                return ai.status(get_settings(conn, include_secret=True))
            return None

        # ---- POST
        if path == "/api/settings":
            if body.get("ai_clear_key"):
                conn.execute("UPDATE settings SET value='' WHERE key='ai_api_key'")
            for k, v in body.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                if k == "ai_api_key" and not (v or "").strip():
                    continue  # Key 输入框留空表示「不修改」
                conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v).strip()))
            # 修改考试日期后，重新生成今天尚未开始的计划任务
            if {"guokao_date", "shengkao_date", "start_date", "daily_hours"} & body.keys():
                conn.execute("DELETE FROM tasks WHERE day=? AND source='plan' AND done=0", (day,))
                if not conn.execute(
                    "SELECT 1 FROM tasks WHERE day=? AND source='plan'", (day,)
                ).fetchone():
                    ensure_today_tasks(conn, get_settings(conn))
            return get_settings(conn)
        if path == "/api/prefs":
            # 界面偏好（主题、草稿、已学章节等），值为任意 JSON
            for k, v in body.items():
                if v is None:
                    conn.execute("DELETE FROM prefs WHERE key=?", (k,))
                else:
                    conn.execute("INSERT OR REPLACE INTO prefs(key, value) VALUES (?, ?)",
                                 (k, json.dumps(v, ensure_ascii=False)))
            return {"ok": True}
        if path == "/api/tasks/toggle":
            conn.execute("UPDATE tasks SET done=1-done WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/tasks/add":
            conn.execute(
                "INSERT INTO tasks(day, title, module, link, minutes, done, source) VALUES (?, ?, ?, '', ?, 0, 'user')",
                (day, body["title"], body.get("module") or "自定义", int(body.get("minutes") or 0)),
            )
            return {"ok": True}
        if path == "/api/tasks/delete":
            conn.execute("DELETE FROM tasks WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/checkin":
            conn.execute(
                "INSERT OR REPLACE INTO checkins(day, note, created_at) VALUES (?, ?, ?)",
                (day, body.get("note") or "", now_str()),
            )
            return {"ok": True, "streak": streak_days(conn)}
        if path == "/api/study_log":
            minutes = int(body.get("minutes") or 0)
            if minutes > 0:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, ?, ?, ?, ?)",
                    (day, body.get("module") or "综合", minutes, body.get("source") or "计时", now_str()),
                )
            return {"ok": True}
        if path == "/api/attempts":
            return record_attempts(conn, body)
        if path == "/api/wrongbook/master":
            conn.execute(
                "UPDATE wrongbook SET mastered=? WHERE qid=?", (1 if body.get("mastered") else 0, body["qid"])
            )
            return {"ok": True}
        if path == "/api/wrongbook/reason":
            conn.execute("UPDATE wrongbook SET reason=? WHERE qid=?", (body.get("reason") or "", body["qid"]))
            return {"ok": True}
        if path == "/api/wrongbook/delete":
            conn.execute("DELETE FROM wrongbook WHERE qid=?", (body["qid"],))
            return {"ok": True}
        if path == "/api/favorite":
            if body.get("on"):
                conn.execute("INSERT OR IGNORE INTO favorites(qid, created_at) VALUES (?, ?)", (body["qid"], now_str()))
            else:
                conn.execute("DELETE FROM favorites WHERE qid=?", (body["qid"],))
            return {"ok": True}
        if path == "/api/qnote":
            conn.execute(
                "INSERT OR REPLACE INTO qnotes(qid, text, updated_at) VALUES (?, ?, ?)",
                (body["qid"], body.get("text") or "", now_str()),
            )
            return {"ok": True}
        if path == "/api/essays":
            cur = conn.execute(
                "INSERT INTO essays(set_id, q_index, answer, words, seconds, self_score, checked, ai_feedback, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (body["set_id"], int(body["q_index"]), body.get("answer") or "", int(body.get("words") or 0),
                 int(body.get("seconds") or 0), body.get("self_score"), json.dumps(body.get("checked") or []),
                 body.get("ai_feedback") or "", now_str()),
            )
            minutes = round(int(body.get("seconds") or 0) / 60)
            if minutes:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, '申论', ?, '申论练习', ?)",
                    (day, minutes, now_str()),
                )
            return {"id": cur.lastrowid}
        if path == "/api/essays/feedback":
            conn.execute("UPDATE essays SET ai_feedback=? WHERE id=?", (body.get("ai_feedback") or "", body["id"]))
            return {"ok": True}
        if path == "/api/interviews":
            cur = conn.execute(
                "INSERT INTO interviews(qid, answer, seconds, ai_feedback, created_at) VALUES (?, ?, ?, ?, ?)",
                (body["qid"], body.get("answer") or "", int(body.get("seconds") or 0),
                 body.get("ai_feedback") or "", now_str()),
            )
            minutes = round(int(body.get("seconds") or 0) / 60)
            if minutes:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, '面试', ?, '面试练习', ?)",
                    (day, minutes, now_str()),
                )
            return {"id": cur.lastrowid}
        if path == "/api/interviews/feedback":
            conn.execute("UPDATE interviews SET ai_feedback=? WHERE id=?", (body.get("ai_feedback") or "", body["id"]))
            return {"ok": True}
        if path == "/api/notebook":
            if body.get("id"):
                conn.execute(
                    "UPDATE notebook SET kind=?, title=?, content=?, tags=?, source=? WHERE id=?",
                    (body.get("kind"), body.get("title"), body.get("content"), body.get("tags"),
                     body.get("source"), body["id"]),
                )
                return {"id": body["id"]}
            cur = conn.execute(
                "INSERT INTO notebook(kind, title, content, tags, source, created_at, box, due) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (body.get("kind") or "摘抄", body.get("title") or "", body.get("content") or "",
                 body.get("tags") or "", body.get("source") or "", now_str(), day),
            )
            return {"id": cur.lastrowid}
        if path == "/api/notebook/delete":
            conn.execute("DELETE FROM notebook WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/memo":
            return memo_save(conn, body)
        if path == "/api/memo/delete":
            conn.execute("DELETE FROM memo_items WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/memo/book":
            name = (body.get("name") or "").strip()[:30]
            if not name:
                raise ValueError("笔记本名字不能为空")
            if body.get("id"):
                conn.execute("UPDATE memo_books SET name=? WHERE id=?", (name, body["id"]))
                return {"id": body["id"]}
            sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM memo_books").fetchone()[0]
            cur = conn.execute("INSERT INTO memo_books(name, sort, created_at) VALUES (?, ?, ?)", (name, sort, now_str()))
            return {"id": cur.lastrowid}
        if path == "/api/memo/book/delete":
            conn.execute("DELETE FROM memo_items WHERE book=?", (body["id"],))
            conn.execute("DELETE FROM memo_books WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/cards/review":
            return review_card(conn, body)
        if path == "/api/speed":
            conn.execute(
                "INSERT INTO speed_records(kind, total, correct, seconds, created_at) VALUES (?, ?, ?, ?, ?)",
                (body["kind"], int(body["total"]), int(body["correct"]), int(body["seconds"]), now_str()),
            )
            minutes = round(int(body["seconds"]) / 60)
            if minutes:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, '资料分析', ?, '速算', ?)",
                    (day, minutes, now_str()),
                )
            return {"ok": True}
        if path == "/api/reading":
            conn.execute(
                "INSERT INTO reading_logs(day, title, source, summary, created_at) VALUES (?, ?, ?, ?, ?)",
                (day, body.get("title") or "", body.get("source") or "", body.get("summary") or "", now_str()),
            )
            if int(body.get("minutes") or 0) > 0:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, '阅读积累', ?, '阅读', ?)",
                    (day, int(body["minutes"]), now_str()),
                )
            return {"ok": True}
        if path == "/api/reading/delete":
            conn.execute("DELETE FROM reading_logs WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/chats/clear":
            conn.execute("DELETE FROM chats")
            return {"ok": True}
        if path == "/api/import":
            return import_all(conn, body)
        if path == "/api/bank/summary":
            return bank_summary(conn, body)
        if path == "/api/bank/pick":
            return {"ids": bank().pick(body, user_progress(conn))}
        if path == "/api/bank/get":
            return bank().get([str(i) for i in body.get("ids") or []])
        if path == "/api/docs/progress":
            doc = body["doc"]
            row = conn.execute("SELECT * FROM doc_progress WHERE doc=?", (doc,)).fetchone()
            cur = dict(row) if row else {"seq": 0, "pct": 0, "done": 0, "fav": 0, "opened_at": now_str()}
            for k in ("seq", "pct", "done", "fav"):
                if k in body:
                    cur[k] = body[k]
            conn.execute(
                "INSERT OR REPLACE INTO doc_progress(doc, seq, pct, done, fav, opened_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (doc, int(cur["seq"] or 0), float(cur["pct"] or 0), 1 if cur["done"] else 0, 1 if cur["fav"] else 0,
                 cur.get("opened_at") or now_str(), now_str()),
            )
            if int(body.get("minutes") or 0) > 0:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, ?, ?, '资料库', ?)",
                    (day, body.get("module") or "综合", int(body["minutes"]), now_str()),
                )
            return {"ok": True}
        if path == "/api/docmarks":
            if body.get("id"):
                if "seq" in body:  # 资料重新整理后，标注重新定位到的新位置
                    conn.execute("UPDATE doc_marks SET seq=?, start=?, end_seq=?, end=? WHERE id=?",
                                 (int(body["seq"]), int(body.get("start") or 0), int(body.get("end_seq", body["seq"])),
                                  int(body.get("end") or 0), body["id"]))
                    return {"id": body["id"]}
                conn.execute("UPDATE doc_marks SET color=?, note=? WHERE id=?",
                             (body.get("color") or "y", body.get("note") or "", body["id"]))
                return {"id": body["id"]}
            cur = conn.execute(
                "INSERT INTO doc_marks(doc, seq, start, end_seq, end, text, color, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (body["doc"], int(body["seq"]), int(body.get("start") or 0), int(body.get("end_seq", body["seq"])),
                 int(body.get("end") or 0), body.get("text") or "", body.get("color") or "y", body.get("note") or "",
                 now_str()),
            )
            return {"id": cur.lastrowid}
        if path == "/api/docquiz":
            # 资料里的例题：记住选了什么；是题库里的原题就同时记一次练习（答错进错题本）
            if body.get("reset"):
                conn.execute("DELETE FROM doc_quiz WHERE doc=?", (body["doc"],))
                return {"ok": True}
            conn.execute("INSERT OR REPLACE INTO doc_quiz(doc, qkey, choice, correct, created_at) VALUES (?,?,?,?,?)",
                         (body["doc"], body["qkey"], body.get("choice") or "", 1 if body.get("correct") else 0, now_str()))
            if body.get("qid"):
                record_attempts(conn, {"mode": "资料例题", "title": body.get("title") or "", "items": [{
                    "qid": body["qid"], "module": body.get("module"), "chosen": body.get("chosen"),
                    "correct": bool(body.get("correct")), "seconds": int(body.get("seconds") or 0)}]})
            return {"ok": True}
        if path == "/api/docmarks/delete":
            conn.execute("DELETE FROM doc_marks WHERE id=?", (body["id"],))
            return {"ok": True}
        if path == "/api/library/progress":
            fid = body["fid"]
            row = conn.execute("SELECT * FROM lib_progress WHERE fid=?", (fid,)).fetchone()
            cur = dict(row) if row else {"page": 0, "done": 0, "fav": 0, "note": ""}
            for k in ("page", "done", "fav", "note"):
                if k in body:
                    cur[k] = body[k]
            conn.execute(
                "INSERT OR REPLACE INTO lib_progress(fid, rel, page, done, fav, note, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fid, body.get("rel") or "", int(cur["page"] or 0), 1 if cur["done"] else 0, 1 if cur["fav"] else 0,
                 cur["note"] or "", now_str()),
            )
            if int(body.get("minutes") or 0) > 0:
                conn.execute(
                    "INSERT INTO study_logs(day, module, minutes, source, created_at) VALUES (?, ?, ?, '资料库', ?)",
                    (day, body.get("module") or "综合", int(body["minutes"]), now_str()),
                )
            return {"ok": True}
        if path == "/api/library/open":
            target, _f = library.resolve(body["fid"])
            if not target:
                return {"error": "找不到这个文件，可能已被移动。请在设置里重新扫描资料文件夹。"}
            if body.get("reveal"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            else:
                os.startfile(target)  # noqa: S606 —— 用系统默认程序打开用户自己的资料
            return {"ok": True}
        if path == "/api/jobs/start":
            root = get_settings(conn).get("library_root") or ""
            if not os.path.isdir(root):
                return {"error": "资料文件夹不存在，请先在设置里填写正确的路径"}
            job = body.get("job") or "all"
            fns = {
                "all": ("整理全部资料", lambda j: library.full_rebuild(root, j)),
                "scan": ("扫描资料目录", lambda j: library.scan(root, j)),
                "real": ("生成真题题库", lambda j: library.build_real(root, j)),
                "index": ("提取全文", lambda j: library.build_text_index(j)),
                "docs": ("整理资料库文档", lambda j: library.build_docs(root, j)),
                "books": ("识别题册", lambda j: library.build_books(root, j)),
                "sucai": ("整理素材库", lambda j: library.build_sucai(j)),
                "shizheng": ("整理时政晨读", lambda j: library.build_shizheng(root, j)),
            }
            name, fn = fns.get(job, fns["all"])
            if not library.jobs.start(name, fn):
                return {"error": "已经有整理任务在进行，请等它完成"}
            return {"ok": True}
        if path == "/api/bank/import":
            try:
                return import_bank(body)
            except ValueError as e:
                return {"error": str(e)}
        if path == "/api/bank/clear":
            if os.path.isfile(CUSTOM_BANK):
                os.remove(CUSTOM_BANK)
            return {"ok": True}
        return None

    # ---- AI（流式输出纯文本）
    def handle_ai(self, kind, body):
        with _db_lock, db() as conn:
            settings = get_settings(conn, include_secret=True)
            history = rows(conn, "SELECT role, content FROM chats ORDER BY id DESC LIMIT 20")[::-1]
        try:
            prompt = ai.build_request(kind, body, history)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        # 先取到第一段再发响应头：Key 错、地址错之类的问题能作为正常的错误返回给界面
        gen = ai.stream(settings, prompt)
        try:
            first = next(gen, "")
        except ai.AIError as e:
            return self.send_json({"error": str(e)}, 502)
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": f"AI 出错：{e}"}, 502)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        chunks = []
        try:
            for piece in itertools.chain([first], gen):
                if not piece:
                    continue
                chunks.append(piece)
                self.wfile.write(piece.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            gen.close()
            return
        except Exception as e:  # noqa: BLE001 —— 响应头已发出，只能把错误写进正文
            self.wfile.write(("\n\n[AI 出错] " + str(e)).encode("utf-8"))
            return
        if kind == "chat":
            with _db_lock, db() as conn:
                conn.execute(
                    "INSERT INTO chats(role, content, created_at) VALUES ('user', ?, ?)",
                    (body.get("message") or "", now_str()),
                )
                conn.execute(
                    "INSERT INTO chats(role, content, created_at) VALUES ('assistant', ?, ?)",
                    ("".join(chunks), now_str()),
                )


def auto_build():
    """第一次运行（或资料目录还没整理过）时，在后台自动整理一遍资料文件夹。"""
    if os.environ.get("GONGKAO_NO_AUTOBUILD"):
        return
    with db() as conn:
        root = get_settings(conn).get("library_root") or ""
    if not root or not os.path.isdir(root):
        return
    if not library.CATALOG_PATH.exists():
        library.jobs.start("整理全部资料", lambda j: library.full_rebuild(root, j))
    elif (not docmod.DB_PATH.exists() or docmod.outdated()) and qdb.DB_PATH.exists():
        # 还没整理过，或者整理规则更新了（资料库文档的 VERSION 变了）：后台重新整理
        library.jobs.start("整理资料库文档", lambda j: library.build_docs(root, j))
    elif not qdb.DB_PATH.exists():
        # 从旧版本升级：目录已有，题库还没进数据库
        def upgrade(j):
            library.build_real(root, j)
            library.build_books(root, j)

        library.jobs.start("生成题库", upgrade)
    elif not shizheng.DB_PATH.exists():
        # 时政晨读是后来加的：已经整理过资料的，单独补整理这一块
        library.jobs.start("整理时政晨读", lambda j: library.build_shizheng(root, j))


def start_server():
    """初始化数据库并在后台线程启动服务，返回端口号。"""
    init_db()
    auto_build()
    try:
        server = ThreadingHTTPServer((HOST, PREFERRED_PORT), Handler)
    except OSError:
        server = ThreadingHTTPServer((HOST, 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]
