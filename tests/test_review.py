"""错题本、闪卡按 FSRS 调度。"""

from datetime import date, timedelta

from gongkao import userdb


def _attempt(client, qid, ok):
    client.post("/api/attempts", {"mode": "practice", "items": [
        {"qid": qid, "module": "数量关系", "chosen": 0, "correct": ok, "seconds": 20}]})


def _row(qid):
    with userdb.db() as conn:
        return dict(conn.execute("SELECT * FROM wrongbook WHERE qid=?", (qid,)).fetchone())


def _set(qid, **kw):
    with userdb.db() as conn:
        sets = ", ".join(f"{k}=?" for k in kw)
        conn.execute(f"UPDATE wrongbook SET {sets} WHERE qid=?", [*kw.values(), qid])


def test_wrong_then_review_until_mastered(client):
    qid = "fsrs-test-q1"
    today = date.today()
    _attempt(client, qid, False)
    r = _row(qid)
    assert r["next_review"] == (today + timedelta(days=1)).isoformat() and r["stability"] > 0 and not r["mastered"]
    _attempt(client, qid, True)  # 没到期就做对：不推进
    assert _row(qid)["next_review"] == r["next_review"]
    intervals = []
    for _ in range(12):
        row = _row(qid)
        if row["mastered"]:
            break
        # 假装已经到期、上次复习在一段时间之前
        gap = max(1, round(row["stability"]))
        _set(qid, next_review=today.isoformat(), last_review=(today - timedelta(days=gap)).isoformat())
        _attempt(client, qid, True)
        nxt = _row(qid)["next_review"]
        intervals.append((date.fromisoformat(nxt) - today).days)
    assert _row(qid)["mastered"] == 1
    assert intervals == sorted(intervals) and intervals[-1] >= 30
    client.post("/api/wrongbook/delete", {"qid": qid})


def test_legacy_wrongbook_row(client):
    """升级前的错题（只有阶段、没有稳定性）到期做对时按原来的间隔折算，不报错。"""
    qid = "fsrs-legacy-q"
    today = date.today().isoformat()
    with userdb.db() as conn:
        conn.execute("INSERT INTO wrongbook(qid, module, wrong_count, last_wrong_at, stage, next_review) "
                     "VALUES (?, '判断推理', 2, '2026-09-01 10:00:00', 3, ?)", (qid, today))
    _attempt(client, qid, True)
    r = _row(qid)
    assert r["stage"] == 4 and r["stability"] > 7 and r["next_review"] > today
    client.post("/api/wrongbook/delete", {"qid": qid})


def test_card_rating_and_preview(client):
    cid = "fsrs-card-1"
    _s, p, _ = client.post("/api/cards/preview", {"ids": [cid]})
    pv = p[cid]
    assert pv["1"] == 0 and pv["2"] <= pv["3"] < pv["4"]
    _s, r, _ = client.post("/api/cards/review", {"card_id": cid, "deck": "d", "rating": 3})
    assert r["days"] == pv["3"]
    _s, cards, _ = client.get("/api/cards")
    assert cards["new_today"] >= 1 and cards["new_limit"] > 0
    c = next(x for x in cards["items"] if x["card_id"] == cid)
    assert c["stability"] > 0 and c["last_review"] == cards["today"]
    status, _r, _ = client.post("/api/cards/review", {"card_id": cid, "rating": 9})
    assert status == 400


def test_legacy_card_known_flag(client):
    with userdb.db() as conn:
        conn.execute("INSERT OR REPLACE INTO cards(card_id, deck, box, due, reps, lapses, updated_at) "
                     "VALUES ('legacy-card', 'd', 4, ?, 4, 0, '2026-09-20 08:00:00')", (date.today().isoformat(),))
    _s, r, _ = client.post("/api/cards/review", {"card_id": "legacy-card", "known": True})
    assert r["days"] > 14  # 原来第 4 盒（14 天）记住了，间隔继续拉长
