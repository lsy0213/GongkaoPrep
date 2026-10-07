"""题目纠错：改过的题干、答案盖在原题上，恢复后回到原样；不影响内置题在内存里的原对象。"""


def test_fix_and_restore(client):
    _s, picked, _ = client.post("/api/bank/pick", {"src": "builtin", "module": "常识判断", "count": 1})
    qid = picked["ids"][0]
    _s, got, _ = client.post("/api/bank/get", {"ids": [qid]})
    q = got["questions"][0]
    new_ans = (q["answer"] + 1) % 4
    _s, r, _ = client.post("/api/qfix", {"qid": qid, "stem": q["stem"] + "（改）", "options": q["options"], "answer": new_ans,
                                         "explain": "新解析", "note": "测试"})
    fixed = r["question"]
    assert fixed["answer"] == new_ans and fixed["stem"].endswith("（改）") and fixed["fixed"]["orig"]["answer"] == q["answer"]
    _s, got2, _ = client.post("/api/bank/get", {"ids": [qid]})
    assert got2["questions"][0]["explain"] == "新解析"
    _s, lst, _ = client.get("/api/qfix")
    assert any(x["qid"] == qid for x in lst["items"])
    client.post("/api/qfix/delete", {"qid": qid})
    _s, got3, _ = client.post("/api/bank/get", {"ids": [qid]})
    assert got3["questions"][0]["answer"] == q["answer"] and "fixed" not in got3["questions"][0]


def test_fix_validation(client):
    status, _r, _ = client.post("/api/qfix", {"qid": "x", "options": ["only one"]})
    assert status == 400
    status, _r, _ = client.post("/api/qfix", {"qid": "x", "answer": 9})
    assert status == 400
