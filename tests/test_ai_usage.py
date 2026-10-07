"""AI：申论分数读取、用量统计、每月上限。"""

from gongkao import ai, userdb


def test_parse_essay_score():
    assert ai.parse_essay_score("【得分】14.5 / 20\n总评：……") == (14.5, 20)
    assert ai.parse_essay_score("【得分】 18/20") == (18, 20)
    assert ai.parse_essay_score("没有分数行") == (None, None)
    assert ai.parse_essay_score("【得分】30 / 20") == (None, None)  # 超过满分的不信


def test_estimate_tokens():
    assert ai.estimate_tokens("一二三") >= 2
    assert ai.estimate_tokens("abcd" * 10) >= 10


def test_usage_and_monthly_limit(client):
    day = userdb.today_str()
    with userdb.db() as conn:
        conn.execute("INSERT INTO ai_usage(day, provider, model, kind, input_tokens, output_tokens, estimated, created_at) "
                     "VALUES (?, 'deepseek', 'deepseek-chat', 'essay', 1000, 500, 0, ?)", (day, day))
    client.post("/api/settings", {"ai_price_in": "2", "ai_price_out": "8", "ai_monthly_tokens": "1000"})
    _s, u, _ = client.get("/api/ai/usage")
    assert u["calls"] >= 1 and u["input"] >= 1000 and u["cost"] is not None and u["limit"] == 1000
    status, r, _ = client.post("/api/ai/explain", {"module": "数量关系", "stem": "x", "options": [], "answer": 0})
    assert status == 429 and "上限" in r["error"]
    client.post("/api/settings", {"ai_monthly_tokens": "0", "ai_price_in": "", "ai_price_out": ""})
    with userdb.db() as conn:
        conn.execute("DELETE FROM ai_usage")


def test_essay_feedback_saves_score(client):
    _s, e, _ = client.post("/api/essays", {"set_id": "e1", "q_index": 0, "answer": "作答", "words": 2, "seconds": 0})
    _s, r, _ = client.post("/api/essays/feedback", {"id": e["id"], "ai_feedback": "【得分】12 / 20\n一般"})
    assert r["ai_score"] == 12 and r["ai_full"] == 20
    _s, lst, _ = client.get("/api/essays")
    row = next(x for x in lst["items"] if x["id"] == e["id"])
    assert row["ai_score"] == 12
