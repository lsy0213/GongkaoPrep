"""题库（内置 + 导入 + 真题/千题册数据库）、做题记录、错题本、收藏、题目笔记、闪卡复习、速算记录。"""

import json
import os
import threading
from datetime import date, timedelta

from .. import fsrs, qdb
from ..paths import content_dir, load_content
from ..scoring import estimate_score
from ..userdb import DATA_DIR, now_str, rows, today
from . import route
from .home import log_minutes

# 老版本的固定间隔（天）：升级上来的错题、闪卡第一次按 FSRS 复习时，用它们折算记忆稳定性
REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
CARD_INTERVALS = [0, 1, 3, 7, 14, 30]

MODULES = ["政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"]
CUSTOM_BANK = DATA_DIR / "custom_questions.json"
MORE_DIR = content_dir() / "questions_more"


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _more_files():
    try:
        return sorted(str(MORE_DIR / n) for n in os.listdir(MORE_DIR) if n.endswith(".json"))
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
    if CUSTOM_BANK.is_file():
        custom = json.loads(CUSTOM_BANK.read_text(encoding="utf-8"))
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
        BANK.refresh((_mtime(content_dir() / "questions.json"), _mtime(CUSTOM_BANK),
                      tuple(_mtime(p) for p in _more_files())))
        return BANK


def user_progress(conn):
    """选题要用的个人状态：做过的题（最近一次时间）、没掌握的错题、收藏。"""
    done = {r["qid"]: r["last"] for r in conn.execute("SELECT qid, MAX(created_at) AS last FROM attempts GROUP BY qid")}
    wrong = {r["qid"] for r in conn.execute("SELECT qid FROM wrongbook WHERE mastered=0")}
    favs = {r["qid"] for r in conn.execute("SELECT qid FROM favorites")}
    return {"done": done, "wrong": wrong, "favorites": favs}


@route("GET", "/api/bank/meta")
def bank_meta(ctx):
    b = bank()
    return {"counts": b.counts(), "custom_count": b.custom_count, "sources": b.sources}


@route("POST", "/api/bank/summary", write=False)
def bank_summary(ctx):
    """按来源/年份/题源筛选后，各模块、题型的题量和做过的题数。"""
    conn, f = ctx.conn, ctx.body
    b = bank()
    all_rows = b.filtered({**f, "module": "全部", "sub": "全部"})
    done = {r["qid"] for r in conn.execute("SELECT DISTINCT qid FROM attempts")}
    mods = {}
    for r in all_rows:
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
    return {"total": len(all_rows), "modules": mods, "matching": len(picked),
            "matching_done": sum(1 for r in picked if r[0] in done)}


@route("POST", "/api/bank/pick", write=False)
def bank_pick(ctx):
    return {"ids": bank().pick(ctx.body, user_progress(ctx.conn))}


@route("POST", "/api/bank/get", write=False)
def bank_get(ctx):
    res = bank().get([str(i) for i in ctx.body.get("ids") or []])
    apply_fixes(ctx.conn, res["questions"])
    return res


# ---------------------------------------------------------------- 题目纠错

def apply_fixes(conn, questions):
    """把自己改过的题干、选项、答案、解析盖到取出的题上（原题留在 orig 里，界面可以对照）。"""
    if not questions:
        return
    ids = [q["id"] for q in questions]
    fixes = {}
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        for r in conn.execute(f"SELECT * FROM qfixes WHERE qid IN ({','.join('?' * len(chunk))})", chunk):
            fixes[r["qid"]] = r
    for i, q in enumerate(questions):
        f = fixes.get(q["id"])
        if not f:
            continue
        q = questions[i] = dict(q)  # 内置题是内存里的共享对象，不能直接改
        orig = {}
        if f["stem"] is not None:
            orig["stem"], q["stem"] = q.get("stem"), f["stem"]
        if f["options"] is not None:
            orig["options"], q["options"] = q.get("options"), json.loads(f["options"])
        if f["answer"] is not None:
            orig["answer"], q["answer"] = q.get("answer"), f["answer"]
        if f["explain"] is not None:
            orig["explain"], q["explain"] = q.get("explain"), f["explain"]
        q["fixed"] = {"note": f["note"] or "", "updated_at": f["updated_at"], "orig": orig}


@route("POST", "/api/qfix")
def qfix_save(ctx):
    """保存对一道题的修改：只传要改的字段；answer 0–3。"""
    b = ctx.body
    qid = str(b["qid"])
    opts = b.get("options")
    if opts is not None and (not isinstance(opts, list) or not 2 <= len(opts) <= 6):
        raise ValueError("选项要有 2–6 个")
    ans = b.get("answer")
    if ans is not None and ans not in (0, 1, 2, 3, 4, 5):
        raise ValueError("答案不对")
    ctx.conn.execute(
        "INSERT OR REPLACE INTO qfixes(qid, stem, options, answer, explain, note, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (qid, b.get("stem"), json.dumps(opts, ensure_ascii=False) if opts is not None else None, ans, b.get("explain"),
         b.get("note") or "", now_str()))
    res = bank().get([qid])
    apply_fixes(ctx.conn, res["questions"])
    return {"ok": True, "question": res["questions"][0] if res["questions"] else None}


@route("POST", "/api/qfix/delete")
def qfix_delete(ctx):
    ctx.conn.execute("DELETE FROM qfixes WHERE qid=?", (str(ctx.body["qid"]),))
    return {"ok": True}


@route("GET", "/api/qfix")
def qfix_list(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM qfixes ORDER BY updated_at DESC")}


@route("POST", "/api/bank/import")
def import_bank(ctx):
    """校验并合并用户导入的题目，保存到数据目录的 custom_questions.json。"""
    payload = ctx.body
    qs = payload.get("questions")
    if not isinstance(qs, list) or not qs:
        return {"error": "文件里没有 questions 列表"}
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
        return {"error": "；".join(errors)}
    current = {"materials": [], "questions": []}
    if CUSTOM_BANK.is_file() and not payload.get("replace"):
        current = json.loads(CUSTOM_BANK.read_text(encoding="utf-8"))
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
    tmp = CUSTOM_BANK.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, CUSTOM_BANK)
    return {"ok": True, "imported": len(qs), "total_custom": len(out["questions"])}


@route("POST", "/api/bank/clear")
def bank_clear(ctx):
    if CUSTOM_BANK.is_file():
        CUSTOM_BANK.unlink()
    return {"ok": True}


# ---------------------------------------------------------------- 做题记录与错题本

def review_settings(conn):
    s = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM settings WHERE key IN ('review_retention','new_cards_per_day','review_cap','wrong_master_days')")}

    def num(k, default, lo, hi):
        try:
            return min(hi, max(lo, float(s.get(k) or default)))
        except ValueError:
            return default

    return {"retention": num("review_retention", 0.9, 0.7, 0.97), "new_per_day": int(num("new_cards_per_day", 30, 0, 500)),
            "review_cap": int(num("review_cap", 300, 10, 5000)), "master_days": int(num("wrong_master_days", 30, 7, 365))}


def _wrong_memory(row):
    """错题本里一道题的记忆状态；老数据（只有阶段）按原来的间隔折算。"""
    if row is None:
        return fsrs.Memory()
    if row["stability"]:
        return fsrs.Memory(stability=row["stability"], difficulty=row["difficulty"] or 5.0,
                           last_review=row["last_review"] or (row["last_wrong_at"] or "")[:10],
                           reps=row["reps"] or 0, lapses=row["wrong_count"] or 0)
    stage = min(max(int(row["stage"] or 0), 0), len(REVIEW_INTERVALS) - 1)
    days = REVIEW_INTERVALS[stage]
    nxt = row["next_review"] or ""
    try:
        last = (date.fromisoformat(nxt) - timedelta(days=days)).isoformat()
    except ValueError:
        last = (row["last_wrong_at"] or today().isoformat())[:10]
    return fsrs.Memory(stability=float(days), difficulty=_clamp(5.0 + 0.5 * (row["wrong_count"] or 1)),
                       last_review=last, reps=stage, lapses=row["wrong_count"] or 0)


def _clamp(d):
    return min(10.0, max(1.0, d))


def record_attempts(conn, payload):
    """保存一次练习：写入 attempts，并按 FSRS 更新错题本。

    做错：记一次“重来”，明天复习；到期后做对：记一次“良好”，间隔按记忆稳定性拉长，
    间隔达到“掌握天数”（默认 30 天）就算掌握。没到期就做对的不推进，避免同一天反复刷同一题就“掌握”。
    """
    items = payload.get("items") or []
    mode = payload.get("mode") or "practice"
    created = now_str()
    correct_n = sum(1 for it in items if it.get("correct"))
    cur = conn.execute(
        "INSERT INTO sessions(mode, title, total, correct, duration, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (mode, payload.get("title") or "", len(items), correct_n, int(payload.get("duration") or 0), created),
    )
    session_id = cur.lastrowid
    day = today()
    cfg = review_settings(conn)
    for it in items:
        qid = str(it["qid"])
        ok = 1 if it.get("correct") else 0
        conn.execute(
            "INSERT INTO attempts(session_id, qid, module, chosen, correct, seconds, mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, qid, it.get("module"), it.get("chosen"), ok, int(it.get("seconds") or 0), mode, created),
        )
        row = conn.execute("SELECT * FROM wrongbook WHERE qid=?", (qid,)).fetchone()
        if not ok:
            m, _due, _days = fsrs.review(_wrong_memory(row), fsrs.AGAIN, day, cfg["retention"], qid)
            nxt = (day + timedelta(days=1)).isoformat()  # 做错的题明天再做
            if row:
                conn.execute(
                    "UPDATE wrongbook SET wrong_count=wrong_count+1, last_wrong_at=?, stage=0, next_review=?, mastered=0, "
                    "stability=?, difficulty=?, last_review=?, reps=? WHERE qid=?",
                    (created, nxt, m.stability, m.difficulty, m.last_review, m.reps, qid),
                )
            else:
                conn.execute(
                    "INSERT INTO wrongbook(qid, module, wrong_count, last_wrong_at, stage, next_review, stability, difficulty, "
                    "last_review, reps) VALUES (?, ?, 1, ?, 0, ?, ?, ?, ?, ?)",
                    (qid, it.get("module"), created, nxt, m.stability, m.difficulty, m.last_review, m.reps),
                )
        elif row and not row["mastered"] and (row["next_review"] or "") <= day.isoformat():
            m, due, days = fsrs.review(_wrong_memory(row), fsrs.GOOD, day, cfg["retention"], qid)
            mastered = 1 if days >= cfg["master_days"] else 0
            conn.execute(
                "UPDATE wrongbook SET stage=stage+1, next_review=?, mastered=?, stability=?, difficulty=?, last_review=?, "
                "reps=? WHERE qid=?",
                (due.isoformat(), mastered, m.stability, m.difficulty, m.last_review, m.reps, qid),
            )
    minutes = round(int(payload.get("duration") or 0) / 60)
    if minutes > 0:
        modules = {it.get("module") for it in items}
        log_minutes(conn, modules.pop() if len(modules) == 1 else "综合", minutes, "刷题")
    per = {}
    for it in items:
        ok_n, n = per.get(it.get("module"), (0, 0))
        per[it.get("module")] = (ok_n + (1 if it.get("correct") else 0), n + 1)
    return {"session_id": session_id, "correct": correct_n, "total": len(items), "score": estimate_score(per)}


@route("POST", "/api/attempts")
def attempts(ctx):
    return record_attempts(ctx.conn, ctx.body)


@route("GET", "/api/progress")
def progress(ctx):
    """刷题页需要的个人状态：做过的题、错题、收藏、笔记。"""
    conn = ctx.conn
    done = rows(conn, "SELECT qid, COUNT(*) AS n, SUM(correct) AS ok, MAX(created_at) AS last FROM attempts GROUP BY qid")
    return {
        "done": {r["qid"]: r for r in done},
        "wrong": {r["qid"]: r for r in rows(conn, "SELECT * FROM wrongbook")},
        "favorites": [r["qid"] for r in conn.execute("SELECT qid FROM favorites")],
        "notes": {r["qid"]: r["text"] for r in conn.execute("SELECT qid, text FROM qnotes")},
    }


@route("GET", "/api/real/progress")
def real_progress(ctx):
    """每个题源（真题卷、千题册）：做过多少题、做对多少题（按每题最近一次作答计）。"""
    latest = {}
    for r in ctx.conn.execute("SELECT qid, correct FROM attempts ORDER BY id"):
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


@route("GET", "/api/wrongbook")
def wrongbook(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM wrongbook ORDER BY mastered, next_review"), "today": ctx.day}


@route("POST", "/api/wrongbook/master")
def wrong_master(ctx):
    ctx.conn.execute("UPDATE wrongbook SET mastered=? WHERE qid=?", (1 if ctx.body.get("mastered") else 0, ctx.body["qid"]))
    return {"ok": True}


@route("POST", "/api/wrongbook/reason")
def wrong_reason(ctx):
    ctx.conn.execute("UPDATE wrongbook SET reason=? WHERE qid=?", (ctx.body.get("reason") or "", ctx.body["qid"]))
    return {"ok": True}


@route("POST", "/api/wrongbook/delete")
def wrong_delete(ctx):
    ctx.conn.execute("DELETE FROM wrongbook WHERE qid=?", (ctx.body["qid"],))
    return {"ok": True}


@route("POST", "/api/favorite")
def favorite(ctx):
    if ctx.body.get("on"):
        ctx.conn.execute("INSERT OR IGNORE INTO favorites(qid, created_at) VALUES (?, ?)", (ctx.body["qid"], now_str()))
    else:
        ctx.conn.execute("DELETE FROM favorites WHERE qid=?", (ctx.body["qid"],))
    return {"ok": True}


@route("POST", "/api/qnote")
def qnote(ctx):
    ctx.conn.execute("INSERT OR REPLACE INTO qnotes(qid, text, updated_at) VALUES (?, ?, ?)",
                     (ctx.body["qid"], ctx.body.get("text") or "", now_str()))
    return {"ok": True}


# ---------------------------------------------------------------- 闪卡、速算

@route("GET", "/api/cards")
def cards(ctx):
    cfg = review_settings(ctx.conn)
    new_today = ctx.conn.execute("SELECT COUNT(*) FROM cards WHERE first_review=?", (ctx.day,)).fetchone()[0]
    reviewed_today = ctx.conn.execute("SELECT COUNT(*) FROM cards WHERE last_review=?", (ctx.day,)).fetchone()[0]
    return {"items": rows(ctx.conn, "SELECT card_id, deck, box, due, reps, lapses, stability, difficulty, last_review "
                                    "FROM cards"),
            "today": ctx.day, "new_today": new_today, "new_limit": cfg["new_per_day"],
            "reviewed_today": reviewed_today, "review_cap": cfg["review_cap"]}


def _card_memory(row):
    if row is None:
        return fsrs.Memory()
    if row["stability"]:
        return fsrs.Memory(stability=row["stability"], difficulty=row["difficulty"] or 5.0,
                           last_review=row["last_review"] or (row["updated_at"] or "")[:10],
                           reps=row["reps"] or 0, lapses=row["lapses"] or 0)
    return fsrs.from_leitner(row["box"], row["due"], row["updated_at"], row["reps"], row["lapses"], CARD_INTERVALS)


def _rating(payload):
    if payload.get("rating") is not None:
        return int(payload["rating"])
    return fsrs.GOOD if payload.get("known") else fsrs.AGAIN  # 老版本界面只有“认识 / 不认识”


def review_card(conn, payload):
    card_id = str(payload["card_id"])
    g = _rating(payload)
    row = conn.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
    cfg = review_settings(conn)
    m, due, days = fsrs.review(_card_memory(row), g, today(), cfg["retention"], card_id)
    box = min(len(CARD_INTERVALS) - 1, 1 + sum(1 for x in CARD_INTERVALS[1:] if days >= x)) if g > 1 else 1
    conn.execute(
        "INSERT INTO cards(card_id, deck, box, due, reps, lapses, updated_at, stability, difficulty, last_review, first_review) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(card_id) DO UPDATE SET "
        "box=excluded.box, due=excluded.due, reps=excluded.reps, lapses=excluded.lapses, updated_at=excluded.updated_at, "
        "stability=excluded.stability, difficulty=excluded.difficulty, last_review=excluded.last_review",
        (card_id, payload.get("deck"), box, due.isoformat(), m.reps, m.lapses, now_str(), m.stability, m.difficulty,
         m.last_review, today().isoformat()),
    )
    return {"box": box, "due": due.isoformat(), "days": days, "stability": round(m.stability, 2),
            "difficulty": round(m.difficulty, 2), "last_review": m.last_review}


@route("POST", "/api/cards/review")
def cards_review(ctx):
    return review_card(ctx.conn, ctx.body)


@route("POST", "/api/cards/preview", write=False)
def cards_preview(ctx):
    """几张卡各自四个打分的下次间隔（天）：{卡 id: {"1": 0, "2": 1, "3": 3, "4": 16}}。"""
    ids = [str(i) for i in (ctx.body.get("ids") or [])][:200]
    cfg = review_settings(ctx.conn)
    have = {}
    if ids:
        q = ",".join("?" * len(ids))
        have = {r["card_id"]: r for r in ctx.conn.execute(f"SELECT * FROM cards WHERE card_id IN ({q})", ids)}
    return {i: fsrs.preview(_card_memory(have.get(i)), today(), cfg["retention"], i) for i in ids}


@route("POST", "/api/speed")
def speed(ctx):
    b = ctx.body
    ctx.conn.execute(
        "INSERT INTO speed_records(kind, total, correct, seconds, created_at) VALUES (?, ?, ?, ?, ?)",
        (b["kind"], int(b["total"]), int(b["correct"]), int(b["seconds"]), now_str()),
    )
    log_minutes(ctx.conn, "资料分析", round(int(b["seconds"]) / 60), "速算")
    return {"ok": True}
