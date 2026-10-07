"""申论、面试作答记录，素材积累、笔记本、阅读记录、AI 对话记录。"""

import json

from .. import library
from ..paths import content_dir, load_content
from ..userdb import now_str, rows
from . import route
from .home import log_minutes

# 笔记本第一次打开时准备好的本子
DEFAULT_MEMO_BOOKS = ["公式本", "知识点本"]


# ---------------------------------------------------------------- 申论、面试

@route("GET", "/api/essay_sets")
def essay_sets(ctx):
    data = load_content("essays.json")
    more = load_content("essays_more.json")["sets"] if (content_dir() / "essays_more.json").exists() else []
    real = [{**x, "fid": library.fid_of(x["file"])} for x in library.real_essays().get("sets", [])]
    return {"note": data.get("note", ""), "sets": data["sets"] + more + real, "real_count": len(real)}


@route("GET", "/api/essays")
def essays(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM essays ORDER BY id DESC")}


@route("POST", "/api/essays")
def essay_save(ctx):
    b = ctx.body
    cur = ctx.conn.execute(
        "INSERT INTO essays(set_id, q_index, answer, words, seconds, self_score, checked, ai_feedback, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (b["set_id"], int(b["q_index"]), b.get("answer") or "", int(b.get("words") or 0),
         int(b.get("seconds") or 0), b.get("self_score"), json.dumps(b.get("checked") or []),
         b.get("ai_feedback") or "", now_str()),
    )
    log_minutes(ctx.conn, "申论", round(int(b.get("seconds") or 0) / 60), "申论练习")
    return {"id": cur.lastrowid}


@route("POST", "/api/essays/feedback")
def essay_feedback(ctx):
    from .. import ai

    text = ctx.body.get("ai_feedback") or ""
    score, full = ai.parse_essay_score(text)
    ctx.conn.execute("UPDATE essays SET ai_feedback=?, ai_score=?, ai_full=? WHERE id=?", (text, score, full, ctx.body["id"]))
    return {"ok": True, "ai_score": score, "ai_full": full}


@route("GET", "/api/interviews")
def interviews(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM interviews ORDER BY id DESC")}


@route("POST", "/api/interviews")
def interview_save(ctx):
    b = ctx.body
    cur = ctx.conn.execute(
        "INSERT INTO interviews(qid, answer, seconds, ai_feedback, created_at) VALUES (?, ?, ?, ?, ?)",
        (b["qid"], b.get("answer") or "", int(b.get("seconds") or 0), b.get("ai_feedback") or "", now_str()),
    )
    log_minutes(ctx.conn, "面试", round(int(b.get("seconds") or 0) / 60), "面试练习")
    return {"id": cur.lastrowid}


@route("POST", "/api/interviews/feedback")
def interview_feedback(ctx):
    ctx.conn.execute("UPDATE interviews SET ai_feedback=? WHERE id=?", (ctx.body.get("ai_feedback") or "", ctx.body["id"]))
    return {"ok": True}


# ---------------------------------------------------------------- 素材积累（notebook 表）

@route("GET", "/api/notebook")
def notebook(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM notebook ORDER BY id DESC")}


@route("POST", "/api/notebook")
def notebook_save(ctx):
    b = ctx.body
    if b.get("id"):
        ctx.conn.execute(
            "UPDATE notebook SET kind=?, title=?, content=?, tags=?, source=? WHERE id=?",
            (b.get("kind"), b.get("title"), b.get("content"), b.get("tags"), b.get("source"), b["id"]),
        )
        return {"id": b["id"]}
    cur = ctx.conn.execute(
        "INSERT INTO notebook(kind, title, content, tags, source, created_at, box, due) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (b.get("kind") or "摘抄", b.get("title") or "", b.get("content") or "", b.get("tags") or "",
         b.get("source") or "", now_str(), ctx.day),
    )
    return {"id": cur.lastrowid}


@route("POST", "/api/notebook/delete")
def notebook_delete(ctx):
    ctx.conn.execute("DELETE FROM notebook WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


# ---------------------------------------------------------------- 笔记本（memo_books / memo_items）

def memo_books(conn):
    empty = not conn.execute("SELECT 1 FROM memo_books LIMIT 1").fetchone()
    if empty and not conn.execute("SELECT 1 FROM memo_items LIMIT 1").fetchone():
        for i, name in enumerate(DEFAULT_MEMO_BOOKS):
            conn.execute("INSERT INTO memo_books(name, sort, created_at) VALUES (?, ?, ?)", (name, i, now_str()))
    return rows(conn, "SELECT * FROM memo_books ORDER BY sort, id")


@route("GET", "/api/memo", write=True)
def memo_all(ctx):
    return {
        "books": memo_books(ctx.conn),
        "items": rows(ctx.conn, "SELECT * FROM memo_items ORDER BY star DESC, id DESC"),
    }


@route("GET", "/api/memo/books", write=True)
def memo_book_list(ctx):
    return {"books": memo_books(ctx.conn)}


@route("POST", "/api/memo")
def memo_save(ctx):
    """新建或修改一条笔记本条目；只改传进来的字段（置顶、移本子时不用带全部内容）。"""
    conn, body = ctx.conn, ctx.body
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
    same = conn.execute("SELECT id FROM memo_items WHERE book=? AND content=?",
                        (body["book"], body["content"].strip())).fetchone()
    if same:  # 同一段内容不重复记
        return {"id": same["id"], "dup": True}
    cur = conn.execute(
        "INSERT INTO memo_items(book, title, content, note, source, doc, seq, star, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (body["book"], body.get("title") or "", body["content"].strip(), body.get("note") or "",
         body.get("source") or "", body.get("doc") or "", body.get("seq"), now_str(), now_str()),
    )
    return {"id": cur.lastrowid}


@route("POST", "/api/memo/delete")
def memo_delete(ctx):
    ctx.conn.execute("DELETE FROM memo_items WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


@route("POST", "/api/memo/book")
def memo_book_save(ctx):
    name = (ctx.body.get("name") or "").strip()[:30]
    if not name:
        raise ValueError("笔记本名字不能为空")
    if ctx.body.get("id"):
        ctx.conn.execute("UPDATE memo_books SET name=? WHERE id=?", (name, ctx.body["id"]))
        return {"id": ctx.body["id"]}
    sort = ctx.conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM memo_books").fetchone()[0]
    cur = ctx.conn.execute("INSERT INTO memo_books(name, sort, created_at) VALUES (?, ?, ?)", (name, sort, now_str()))
    return {"id": cur.lastrowid}


@route("POST", "/api/memo/book/delete")
def memo_book_delete(ctx):
    ctx.conn.execute("DELETE FROM memo_items WHERE book=?", (ctx.body["id"],))
    ctx.conn.execute("DELETE FROM memo_books WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


# ---------------------------------------------------------------- 阅读记录、AI 对话

@route("GET", "/api/reading")
def reading(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM reading_logs ORDER BY id DESC LIMIT 200")}


@route("POST", "/api/reading")
def reading_save(ctx):
    b = ctx.body
    ctx.conn.execute(
        "INSERT INTO reading_logs(day, title, source, summary, created_at) VALUES (?, ?, ?, ?, ?)",
        (ctx.day, b.get("title") or "", b.get("source") or "", b.get("summary") or "", now_str()),
    )
    log_minutes(ctx.conn, "阅读积累", int(b.get("minutes") or 0), "阅读")
    return {"ok": True}


@route("POST", "/api/reading/delete")
def reading_delete(ctx):
    ctx.conn.execute("DELETE FROM reading_logs WHERE id=?", (ctx.body["id"],))
    return {"ok": True}


@route("GET", "/api/chats")
def chats(ctx):
    return {"items": rows(ctx.conn, "SELECT * FROM chats ORDER BY id DESC LIMIT 60")[::-1]}


@route("POST", "/api/chats/clear")
def chats_clear(ctx):
    ctx.conn.execute("DELETE FROM chats")
    return {"ok": True}
