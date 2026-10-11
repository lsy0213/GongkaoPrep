"""软考（系统架构设计师等）的接口：首页看板。

连接是当前考试的库（软考自己的 app.db + 挂上的共用库），所以做题、错题、闪卡、学习时长都是软考自己的；
打卡是共用的（所有考试一份打卡日历）。
"""

from datetime import date

from .. import exams
from ..userdb import get_settings, rows, today, today_str
from . import route
from .home import ensure_today_tasks, plan_module, streak_days, today_review


def _d(s):
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


@route("GET", "/api/rk/dashboard")
def rk_dashboard(ctx):
    conn = ctx.conn
    ex = exams.get()
    s = get_settings(conn)
    day = today_str()
    ensure_today_tasks(conn, s)
    pl = plan_module()
    exam_day = _d(s.get("exam_date"))
    start = _d(s.get("start_date")) or today()
    q = conn.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts WHERE substr(created_at,1,10)=?", (day,)).fetchone()
    total = conn.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts").fetchone()
    minutes_today = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs WHERE day=?", (day,)).fetchone()[0]
    minutes_total = conn.execute("SELECT COALESCE(SUM(minutes),0) FROM study_logs").fetchone()[0]
    due_wrong = conn.execute("SELECT COUNT(*) FROM wrongbook WHERE mastered=0 AND next_review<=?", (day,)).fetchone()[0]
    due_cards = conn.execute("SELECT COUNT(*) FROM cards WHERE due<=?", (day,)).fetchone()[0]
    return {
        "today": day,
        "settings": s,
        "exam": {"id": ex["id"], "name": ex.get("name"), "family": ex.get("family"), "level": ex.get("level"),
                 "subjects": ex.get("subjects") or [], "sessions": ex.get("sessions") or []},
        "exam_date": exam_day.isoformat() if exam_day else "",
        "days_left": (exam_day - today()).days if exam_day else None,
        "days_studied": max(0, (today() - start).days + 1),
        "streak": streak_days(conn),
        "checked_in": bool(conn.execute("SELECT 1 FROM checkins WHERE day=?", (day,)).fetchone()),
        "checkin_total": conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0],
        "questions_today": q[0], "correct_today": q[1],
        "questions_total": total[0], "correct_total": total[1],
        "minutes_today": minutes_today, "minutes_total": minutes_total,
        "review": today_review(conn, due_wrong, due_cards),
        "tasks": rows(conn, "SELECT * FROM tasks WHERE day=? ORDER BY id", (day,)),
        "phase": pl.current_phase(s, today()) if pl else None,
        "milestones": pl.milestones(s, today()) if pl else [],
    }


# ---------------------------------------------------------------- 整理资料

def _rk_jobs():
    from ..ruankao import build, catalog, mdimport

    def scan_root():
        from ..userdb import db

        with db(exam="ruankao-arch") as c:
            return get_settings(c).get("library_root") or ""

    def scan(j):
        root = scan_root()
        if root:
            catalog.scan(root, j)

    def github(j):
        mdimport.download(j)
        build.build_bank(j)

    return {
        "all": ("软考：整理全部资料", lambda j: build.build_all(j)),
        "scan": ("软考：扫描资料目录", scan),
        "github": ("软考：下载开源题库", github),
        "bank": ("软考：生成题库、案例、论文", lambda j: build.build_bank(j)),
        "docs": ("软考：整理资料库文档", lambda j: build.build_docs(j)),
        "videos": ("软考：整理视频课", lambda j: build.build_videos(j)),
    }


@route("POST", "/api/rk/jobs/start", write=False)
def rk_jobs_start(ctx):
    import os

    from .. import library

    job = ctx.body.get("job") or "all"
    jobs = _rk_jobs()
    if job not in jobs:
        raise ValueError("没有这个整理任务")
    if job in ("all", "scan") and not os.path.isdir(get_settings(ctx.conn).get("library_root") or ""):
        raise ValueError("资料文件夹不存在，请先在设置里填写正确的路径")
    name, fn = jobs[job]
    started = library.jobs.start(name, fn)
    if not started:
        return {"error": f"“{name}”已经在进行或在排队了"}
    return {"ok": True, "queued": started == "queued", "name": name}


@route("GET", "/api/rk/library")
def rk_library(ctx):
    """软考资料整理的情况：目录、题库、案例、论文、资料库文档、视频、开源题库。"""
    from .. import library
    from ..ruankao import build, catalog, mdimport
    from .practice import bank

    cat = catalog.load()
    cats = {}
    for f in cat.get("files", []):
        cats[f.get("cat", "其他")] = cats.get(f.get("cat", "其他"), 0) + 1
    b = bank()
    c = b.counts()
    try:
        import json as _json

        gh = _json.loads((mdimport.gh_dir() / "_source.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        gh = {"downloaded": mdimport.available()}
    return {
        "root": cat.get("root", ""), "scanned_at": cat.get("scanned_at", ""), "files": len(cat.get("files", [])), "cats": cats,
        "bank": {"真题": c.get("真题", 0), "模拟": c.get("模拟", 0), "内置": c.get("内置", 0),
                 "papers": sum(1 for s in b.sources if s["kind"] == "paper"), "mocks": sum(1 for s in b.sources if s["kind"] == "mock")},
        "cases": len(build.load_json("cases.json", {}).get("sets", [])),
        "essays": len(build.load_json("essays.json", {}).get("topics", [])),
        "videos": sum(len(g["items"]) for g in build.load_json("videos.json", {}).get("groups", [])),
        "github": gh, "job": library.jobs.status(),
    }


@route("GET", "/api/rk/calc/stats")
def rk_calc_stats(ctx):
    """计算题专练每类的累计题数、正确率、平均用时（记录在 speed_records，kind = rk-<类型>）。"""
    out = {}
    for r in ctx.conn.execute("SELECT kind, SUM(total) AS n, SUM(correct) AS ok, SUM(seconds) AS sec FROM speed_records "
                              "WHERE kind LIKE 'rk-%' GROUP BY kind"):
        out[r["kind"][3:]] = {"n": r["n"] or 0, "ok": r["ok"] or 0, "sec": r["sec"] or 0}
    return out


@route("GET", "/api/rk/videos")
def rk_videos(ctx):
    from ..ruankao import build

    return build.load_json("videos.json", {"groups": []})


# ---------------------------------------------------------------- 案例分析、论文

CASE_TAGS = [
    ("质量属性与评估", r"质量属性|效用树|敏感点|权衡点|风险点|ATAM|SAAM|架构评估|心跳|Ping"),
    ("嵌入式", r"嵌入式|实时操作|RTOS|FACE|宇航|AADL|机载|航电|DO-178|可靠性设计|余度|故障检测"),
    ("数据库与缓存", r"数据库|Redis|缓存|分布式锁|分库|分表|NoSQL|反规范化|关系模式|读写分离|主从|一致性"),
    ("系统建模", r"UML|用例|类图|顺序图|序列图|数据流图|DFD|状态图|活动图|ER\s*图|E-R|实体联系"),
    ("Web 与云原生", r"Web|负载均衡|微服务|容器|Kubernetes|云原生|Serverless|JWT|Session|大数据|Lambda|Kappa|Hadoop|MVC|SOA|ESB"),
    ("架构设计", r"架构风格|架构设计|分层|事件驱动|黑板|管道|解释器|C/S|B/S|中间件|构件"),
    ("安全", r"安全|加密|认证|授权|攻击|防火墙"),
]


def case_tags(c):
    import re

    text = (c.get("title") or "") + " " + (c.get("material") or "")[:1500] + " " + " ".join(q.get("text", "") for q in c.get("questions", []))
    tags = [name for name, rx in CASE_TAGS if re.search(rx, text, re.I)]
    return tags or ["其他"]


def _case_records(conn, prefix):
    """自己作答过的记录：{题 id: {n, best, last, ai}}（存在 essays 表，set_id = case:<id> / paper:<id>）。"""
    out = {}
    for r in conn.execute("SELECT set_id, q_index, self_score, ai_score, ai_full, created_at FROM essays WHERE set_id LIKE ? ORDER BY id",
                          (prefix + "%",)):
        k = r["set_id"][len(prefix):]
        o = out.setdefault(k, {"n": 0, "last": "", "ai": None, "self": None})
        o["n"] += 1
        o["last"] = r["created_at"]
        if r["ai_score"] is not None:
            o["ai"] = r["ai_score"]
        if r["self_score"] is not None:
            o["self"] = r["self_score"]
    return out


@route("GET", "/api/rk/cases")
def rk_cases(ctx):
    from ..ruankao import build

    sets = build.load_json("cases.json", {}).get("sets", [])
    recs = _case_records(ctx.conn, "case:")
    out = []
    for c in sets:
        out.append({"id": c["id"], "source": c.get("source", ""), "year": c.get("year", 0), "half": c.get("half", ""),
                    "kind": c.get("kind", ""), "no": c.get("no"), "title": c.get("title", ""), "required": c.get("required"),
                    "score": c.get("score", 25), "nq": len(c.get("questions", [])),
                    "answered": sum(1 for q in c.get("questions", []) if q.get("answer")),
                    "tags": case_tags(c), "intro": (c.get("material") or "")[:90], "rec": recs.get(c["id"])})
    out.sort(key=lambda c: (c["kind"] != "paper", -(c["year"] or 0), c["half"] != "下半年", c["no"] or 0))
    return {"sets": out, "tags": [t for t, _ in CASE_TAGS] + ["其他"]}


@route("GET", "/api/rk/case")
def rk_case(ctx):
    from ..ruankao import build

    cid = ctx.q("id", "")
    c = next((x for x in build.load_json("cases.json", {}).get("sets", []) if x["id"] == cid), None)
    if not c:
        return {"error": "没有找到这道案例题"}
    from ..userdb import rows

    hist = rows(ctx.conn, "SELECT * FROM essays WHERE set_id=? ORDER BY id DESC LIMIT 60", ("case:" + cid,))
    return {**c, "tags": case_tags(c), "history": hist}


@route("GET", "/api/rk/essays")
def rk_essays(ctx):
    from ..ruankao import build

    topics = build.load_json("essays.json", {}).get("topics", [])
    recs = _case_records(ctx.conn, "paper:")
    topics = sorted(topics, key=lambda e: (e.get("kind") != "paper", -(e.get("year") or 0), e.get("half") != "下半年", e.get("no") or 0))
    return {"topics": [{"id": e["id"], "title": e["title"], "source": e.get("source", ""), "year": e.get("year", 0),
                        "half": e.get("half", ""), "kind": e.get("kind", ""), "has_guide": bool(e.get("guide")),
                        "rec": recs.get(e["id"])} for e in topics]}


@route("GET", "/api/rk/essay")
def rk_essay(ctx):
    from ..ruankao import build
    from ..userdb import rows

    eid = ctx.q("id", "")
    e = next((x for x in build.load_json("essays.json", {}).get("topics", []) if x["id"] == eid), None)
    if not e:
        return {"error": "没有找到这道论文题"}
    return {**e, "history": rows(ctx.conn, "SELECT * FROM essays WHERE set_id=? ORDER BY id DESC LIMIT 30", ("paper:" + eid,))}


@route("POST", "/api/rk/case/self")
def rk_case_self(ctx):
    """案例一问的自评分。"""
    if ctx.body.get("id"):
        ctx.conn.execute("UPDATE essays SET self_score=? WHERE id=?", (float(ctx.body.get("score") or 0), int(ctx.body["id"])))
    return {"ok": True}
