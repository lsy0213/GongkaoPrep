"""资料库、时政晨读、阅读进度与标注、资料里的例题、后台整理任务。"""

import os
import subprocess

from .. import docs as docmod
from .. import library, shizheng
from ..userdb import get_settings, now_str, rows
from . import route
from .home import log_minutes
from .practice import bank, record_attempts


@route("GET", "/api/library")
def library_overview(ctx):
    cat = library.load_catalog()
    prog = {r["fid"]: dict(r) for r in ctx.conn.execute("SELECT * FROM lib_progress")}
    b = bank()
    c = b.counts()
    return {
        "root": cat.get("root", ""), "scanned_at": cat.get("scanned_at", ""), "files": cat.get("files", []),
        "progress": prog, "text_index": library.text_index_info(),
        "real": {"papers": sum(1 for x in b.sources if x["kind"] == "paper"), "questions": c["国考"] + c["四川"],
                 "books": sum(1 for x in b.sources if x["kind"] == "book"), "book_questions": c["千题册"],
                 "essays": len(library.real_essays().get("sets", [])),
                 "decks": len(library.lib_decks().get("decks", []))},
    }


@route("GET", "/api/library/search")
def library_search(ctx):
    fids = set(filter(None, (ctx.q("fids") or "").split(","))) or None
    return library.search(ctx.q("q", ""), fids=fids)


@route("GET", "/api/docs")
def docs_overview(ctx):
    """资料库首页：文档列表、阅读进度、标注数量。"""
    conn = ctx.conn
    prog = {r["doc"]: dict(r) for r in conn.execute("SELECT * FROM doc_progress")}
    marks = {r[0]: r[1] for r in conn.execute("SELECT doc, COUNT(*) FROM doc_marks GROUP BY doc")}
    cat = library.load_catalog()
    return {"docs": docmod.doc_list(), "groups": docmod.GROUPS, "progress": prog, "marks": marks, "root": cat.get("root", ""),
            "scanned_at": cat.get("scanned_at", ""), "total_files": len(docmod.selected(cat.get("files", [])))}


@route("GET", "/api/news")
def news_overview(ctx):
    """时政晨读首页：资料列表 + 阅读进度、成语积累日历和每天的掌握情况（prefs 里的 cy_marks）。"""
    data = shizheng.overview()
    ids = {it["id"] for it in data["items"]}
    data["progress"] = {r["doc"]: dict(r) for r in ctx.conn.execute("SELECT * FROM doc_progress") if r["doc"] in ids}
    data["marks"] = {r[0]: r[1] for r in ctx.conn.execute("SELECT doc, COUNT(*) FROM doc_marks GROUP BY doc") if r[0] in ids}
    data["job"] = library.jobs.status()
    return data


@route("GET", "/api/news/chengyu")
def news_chengyu(ctx):
    dates = [x for x in (ctx.q("dates") or "").split(",") if x]
    return shizheng.chengyu(ctx.q("month"), dates or None)


@route("GET", "/api/news/chengyu_all")
def news_chengyu_all(ctx):
    return shizheng.chengyu_all()


@route("GET", "/api/news/quiz")
def news_quiz(ctx):
    return shizheng.quiz(int(ctx.q("n") or 20), ctx.q("since") or "", ctx.q("src") or "")


@route("GET", "/api/news/search")
def news_search(ctx):
    return {"hits": shizheng.search(ctx.q("q", ""))}


@route("GET", "/api/docs/get", write=True)
def doc_get(ctx):
    conn = ctx.conn
    d = docmod.doc_get(ctx.q("id", "")) or shizheng.doc_get(ctx.q("id", ""))
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


@route("GET", "/api/sucai")
def sucai(ctx):
    from .. import sucai as sucaimod

    return sucaimod.load()


@route("GET", "/api/docs/search")
def docs_search(ctx):
    doc = ctx.q("doc")
    if doc and doc in shizheng.titles():
        return {"hits": shizheng.search(ctx.q("q", ""), doc)}
    return {"hits": docmod.search(ctx.q("q", ""), doc or None)}


@route("GET", "/api/docmarks")
def docmarks(ctx):
    titles = {**shizheng.titles(), **{d["id"]: d["title"] for d in docmod.doc_list()}}
    items = rows(ctx.conn, "SELECT * FROM doc_marks ORDER BY id DESC")
    for m in items:
        m["title"] = titles.get(m["doc"], "（资料已移除）")
    return {"items": items}


@route("POST", "/api/docmarks")
def docmark_save(ctx):
    conn, b = ctx.conn, ctx.body
    if b.get("id"):
        if "seq" in b:  # 资料重新整理后，标注重新定位到的新位置
            conn.execute("UPDATE doc_marks SET seq=?, start=?, end_seq=?, end=? WHERE id=?",
                         (int(b["seq"]), int(b.get("start") or 0), int(b.get("end_seq", b["seq"])),
                          int(b.get("end") or 0), b["id"]))
            return {"id": b["id"]}
        conn.execute("UPDATE doc_marks SET color=?, note=? WHERE id=?", (b.get("color") or "y", b.get("note") or "", b["id"]))
        return {"id": b["id"]}
    cur = conn.execute(
        "INSERT INTO doc_marks(doc, seq, start, end_seq, end, text, color, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (b["doc"], int(b["seq"]), int(b.get("start") or 0), int(b.get("end_seq", b["seq"])), int(b.get("end") or 0),
         b.get("text") or "", b.get("color") or "y", b.get("note") or "", now_str()),
    )
    return {"id": cur.lastrowid}


@route("POST", "/api/docmarks/delete")
def docmark_delete(ctx):
    ctx.conn.execute("DELETE FROM doc_marks WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


@route("POST", "/api/docs/progress")
def doc_progress(ctx):
    conn, b = ctx.conn, ctx.body
    doc = b["doc"]
    row = conn.execute("SELECT * FROM doc_progress WHERE doc=?", (doc,)).fetchone()
    cur = dict(row) if row else {"seq": 0, "pct": 0, "done": 0, "fav": 0, "opened_at": now_str()}
    for k in ("seq", "pct", "done", "fav"):
        if k in b:
            cur[k] = b[k]
    conn.execute(
        "INSERT OR REPLACE INTO doc_progress(doc, seq, pct, done, fav, opened_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (doc, int(cur["seq"] or 0), float(cur["pct"] or 0), 1 if cur["done"] else 0, 1 if cur["fav"] else 0,
         cur.get("opened_at") or now_str(), now_str()),
    )
    log_minutes(conn, b.get("module") or "综合", int(b.get("minutes") or 0), "资料库")
    return {"ok": True}


@route("POST", "/api/docquiz")
def doc_quiz(ctx):
    """资料里的例题：记住选了什么；是题库里的原题就同时记一次练习（答错进错题本）。"""
    conn, b = ctx.conn, ctx.body
    if b.get("reset"):
        conn.execute("DELETE FROM doc_quiz WHERE doc=?", (b["doc"],))
        return {"ok": True}
    conn.execute("INSERT OR REPLACE INTO doc_quiz(doc, qkey, choice, correct, created_at) VALUES (?,?,?,?,?)",
                 (b["doc"], b["qkey"], b.get("choice") or "", 1 if b.get("correct") else 0, now_str()))
    if b.get("qid"):
        record_attempts(conn, {"mode": "资料例题", "title": b.get("title") or "", "items": [{
            "qid": b["qid"], "module": b.get("module"), "chosen": b.get("chosen"),
            "correct": bool(b.get("correct")), "seconds": int(b.get("seconds") or 0)}]})
    return {"ok": True}


@route("POST", "/api/library/progress")
def lib_progress(ctx):
    conn, b = ctx.conn, ctx.body
    fid = b["fid"]
    row = conn.execute("SELECT * FROM lib_progress WHERE fid=?", (fid,)).fetchone()
    cur = dict(row) if row else {"page": 0, "done": 0, "fav": 0, "note": ""}
    for k in ("page", "done", "fav", "note"):
        if k in b:
            cur[k] = b[k]
    conn.execute(
        "INSERT OR REPLACE INTO lib_progress(fid, rel, page, done, fav, note, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fid, b.get("rel") or "", int(cur["page"] or 0), 1 if cur["done"] else 0, 1 if cur["fav"] else 0,
         cur["note"] or "", now_str()),
    )
    log_minutes(conn, b.get("module") or "综合", int(b.get("minutes") or 0), "资料库")
    return {"ok": True}


@route("POST", "/api/library/open", write=False)
def lib_open(ctx):
    target, _f = library.resolve(ctx.body["fid"])
    if not target:
        return {"error": "找不到这个文件，可能已被移动。请在设置里重新扫描资料文件夹。"}
    if ctx.body.get("reveal"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
    else:
        os.startfile(target)  # noqa: S606 —— 用系统默认程序打开用户自己的资料
    return {"ok": True}


# ---------------------------------------------------------------- 后台整理任务

JOBS = {
    "all": ("整理全部资料", lambda root: lambda j: library.full_rebuild(root, j)),
    "scan": ("扫描资料目录", lambda root: lambda j: library.scan(root, j)),
    "real": ("生成真题题库", lambda root: lambda j: library.build_real(root, j)),
    "index": ("提取全文", lambda root: lambda j: library.build_text_index(j)),
    "docs": ("整理资料库文档", lambda root: lambda j: library.build_docs(root, j)),
    "books": ("识别题册", lambda root: lambda j: library.build_books(root, j)),
    "sucai": ("整理素材库", lambda root: lambda j: library.build_sucai(j)),
    "shizheng": ("整理时政晨读", lambda root: lambda j: library.build_shizheng(root, j)),
}


@route("GET", "/api/jobs")
def jobs(ctx):
    return library.jobs.status()


@route("POST", "/api/jobs/start", write=False)
def jobs_start(ctx):
    root = get_settings(ctx.conn).get("library_root") or ""
    if not os.path.isdir(root):
        return {"error": "资料文件夹不存在，请先在设置里填写正确的路径"}
    name, make = JOBS.get(ctx.body.get("job") or "all", JOBS["all"])
    if not library.jobs.start(name, make(root)):
        return {"error": "已经有整理任务在进行，请等它完成"}
    return {"ok": True}
