"""接口冒烟测试：每个接口都能正常返回，主要的读写流程前后一致。"""

import pytest

GET_ROUTES = [
    "/api/dashboard", "/api/settings", "/api/plan", "/api/bank/meta", "/api/real/progress", "/api/essay_sets",
    "/api/decks", "/api/library", "/api/library/search?q=test", "/api/jobs", "/api/docs", "/api/news",
    "/api/news/chengyu", "/api/news/chengyu_all", "/api/news/quiz?n=5", "/api/news/search?q=test",
    "/api/sucai", "/api/docs/search?q=test", "/api/docmarks", "/api/course/search?q=资料分析",
    "/api/progress", "/api/wrongbook", "/api/stats", "/api/essays", "/api/interviews", "/api/notebook",
    "/api/memo", "/api/memo/books", "/api/cards", "/api/reading", "/api/chats", "/api/prefs", "/api/export",
    "/api/ai/presets", "/api/ai/status",
]


@pytest.mark.parametrize("path", GET_ROUTES)
def test_get_routes(client, path):
    status, body, _ = client.get(path)
    assert status == 200, (path, body)
    assert isinstance(body, (dict, list))


def test_unknown_route(client):
    status, body, _ = client.get("/api/nope")
    assert status == 404 and body["error"]
    status, body, _ = client.post("/api/nope", {})
    assert status == 404


def test_missing_param(client):
    status, body, _ = client.post("/api/tasks/toggle", {})
    assert status == 400 and "缺少参数" in body["error"]


def test_bad_json(client):
    status, body, _ = client.request("POST", "/api/prefs", body="{not json", headers={"Content-Type": "application/json"})
    assert status == 400


def test_attempts_and_wrongbook(client):
    _s, meta, _ = client.get("/api/bank/meta")
    assert meta["counts"]
    _s, picked, _ = client.post("/api/bank/pick", {"module": "数量关系", "sub": "全部", "count": 3, "src": "builtin"})
    ids = picked["ids"]
    assert ids
    _s, got, _ = client.post("/api/bank/get", {"ids": ids})
    q = got["questions"][0]
    status, res, _ = client.post("/api/attempts", {"mode": "practice", "title": "t", "duration": 120, "items": [
        {"qid": q["id"], "module": q["module"], "chosen": (q["answer"] + 1) % 4, "correct": False, "seconds": 30},
    ]})
    assert status == 200 and res["total"] == 1 and res["correct"] == 0
    _s, wb, _ = client.get("/api/wrongbook")
    assert any(w["qid"] == q["id"] for w in wb["items"])
    client.post("/api/wrongbook/reason", {"qid": q["id"], "reason": "粗心"})
    client.post("/api/favorite", {"qid": q["id"], "on": True})
    client.post("/api/qnote", {"qid": q["id"], "text": "笔记"})
    _s, prog, _ = client.get("/api/progress")
    assert q["id"] in prog["done"] and q["id"] in prog["favorites"] and prog["notes"][q["id"]] == "笔记"
    _s, summ, _ = client.post("/api/bank/summary", {"src": "builtin", "module": "全部", "sub": "全部", "order": "wrong"})
    assert summ["matching"] >= 1
    client.post("/api/wrongbook/master", {"qid": q["id"], "mastered": True})
    client.post("/api/wrongbook/delete", {"qid": q["id"]})
    client.post("/api/favorite", {"qid": q["id"], "on": False})


def test_tasks_checkin_logs(client):
    client.get("/api/dashboard")
    client.post("/api/tasks/add", {"title": "自定义任务", "minutes": 10})
    _s, plan, _ = client.get("/api/plan")
    t = next(t for t in plan["tasks"] if t["title"] == "自定义任务")
    client.post("/api/tasks/toggle", {"id": t["id"]})
    client.post("/api/tasks/delete", {"id": t["id"]})
    _s, r, _ = client.post("/api/checkin", {"note": "ok"})
    assert r["streak"] >= 1
    client.post("/api/study_log", {"minutes": 5, "module": "言语理解与表达"})
    _s, st, _ = client.get("/api/stats")
    assert st["days"][-1]["minutes"] >= 5


def test_cards_and_speed(client):
    _s, r, _ = client.post("/api/cards/review", {"card_id": "test-card-1", "deck": "d", "known": True})
    assert r["due"]
    _s, cards, _ = client.get("/api/cards")
    assert any(c["card_id"] == "test-card-1" for c in cards["items"])
    status, _r, _ = client.post("/api/speed", {"kind": "两位数乘法", "total": 10, "correct": 9, "seconds": 90})
    assert status == 200


def test_writing_records(client):
    _s, e, _ = client.post("/api/essays", {"set_id": "e1", "q_index": 0, "answer": "答案", "words": 2, "seconds": 600})
    client.post("/api/essays/feedback", {"id": e["id"], "ai_feedback": "好"})
    _s, i, _ = client.post("/api/interviews", {"qid": "i1", "answer": "回答", "seconds": 180})
    client.post("/api/interviews/feedback", {"id": i["id"], "ai_feedback": "好"})
    _s, n, _ = client.post("/api/notebook", {"kind": "金句", "content": "内容"})
    client.post("/api/notebook", {"id": n["id"], "kind": "金句", "content": "改过"})
    client.post("/api/notebook/delete", {"id": n["id"]})
    client.post("/api/reading", {"title": "读", "minutes": 3})
    _s, rd, _ = client.get("/api/reading")
    client.post("/api/reading/delete", {"id": rd["items"][0]["id"]})
    client.post("/api/chats/clear", {})


def test_memo(client):
    _s, books, _ = client.get("/api/memo/books")
    assert len(books["books"]) >= 2
    _s, b, _ = client.post("/api/memo/book", {"name": "测试本"})
    _s, it, _ = client.post("/api/memo", {"book": b["id"], "content": "a+b"})
    _s, dup, _ = client.post("/api/memo", {"book": b["id"], "content": "a+b"})
    assert dup.get("dup")
    client.post("/api/memo", {"id": it["id"], "star": 1})
    client.post("/api/memo/delete", {"id": it["id"]})
    client.post("/api/memo/book/delete", {"id": b["id"]})


def test_docs_progress_marks(client):
    client.post("/api/docs/progress", {"doc": "doc-x", "seq": 3, "pct": 0.5, "minutes": 2})
    _s, m, _ = client.post("/api/docmarks", {"doc": "doc-x", "seq": 1, "start": 0, "end": 3, "text": "abc"})
    client.post("/api/docmarks", {"id": m["id"], "color": "g", "note": "n"})
    client.post("/api/docquiz", {"doc": "doc-x", "qkey": "k", "choice": "A", "correct": True})
    client.post("/api/docquiz", {"doc": "doc-x", "reset": True})
    client.post("/api/docmarks/delete", {"id": m["id"]})
    client.post("/api/library/progress", {"fid": "f1", "page": 2})


def test_export_import_roundtrip(client):
    client.post("/api/prefs", {"roundtrip": {"a": 1}})
    _s, data, _ = client.get("/api/export")
    assert data["app"] == "gongkao-prep"
    client.post("/api/prefs", {"roundtrip": None})
    status, r, _ = client.post("/api/import", data)
    assert status == 200 and r["ok"]
    _s, prefs, _ = client.get("/api/prefs")
    assert prefs["roundtrip"] == {"a": 1}
    client.post("/api/prefs", {"roundtrip": None})


def test_bank_import(client):
    bad = {"questions": [{"id": "x1", "stem": "s", "module": "瞎写", "options": ["a", "b", "c", "d"], "answer": 0}]}
    _s, r, _ = client.post("/api/bank/import", bad)
    assert r.get("error")
    good = {"questions": [{"id": "my-1", "stem": "题干", "module": "数量关系", "options": ["1", "2", "3", "4"], "answer": 1}]}
    _s, r, _ = client.post("/api/bank/import", good)
    assert r["ok"] and r["imported"] == 1
    _s, meta, _ = client.get("/api/bank/meta")
    assert meta["custom_count"] == 1
    client.post("/api/bank/clear", {})
