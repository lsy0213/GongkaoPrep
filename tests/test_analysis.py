"""考点归类、弱项诊断、用时分析、估分。"""

from gongkao import scoring, topics


def test_classify_common_question_shapes():
    c = topics.classify
    assert c("资料分析", "资料分析", "2023年该市社会消费品零售总额比2021年增长了约百分之几？") == "data-gap"
    assert c("资料分析", "资料分析", "2024年A省粮食产量占全国的比重比上年约：") == "data-share"
    assert c("资料分析", "资料分析", "能够从上述资料中推出的是：") == "data-judge"
    assert c("数量关系", "数学运算", "甲乙两人同时从A、B两地出发相向而行，速度分别为……几小时后相遇？") == "math-travel"
    assert c("数量关系", "数学运算", "某商品按定价打八折出售，仍可获利20%……") == "math-profit"
    assert c("数量关系", "数字推理", "1, 3, 7, 15, ( )") == "math-seq"
    assert c("判断推理", "逻辑判断", "以下哪项如果为真，最能削弱上述论证？") == "reason-weaken"
    assert c("判断推理", "图形推理", "从所给的四个选项中，选择最合适的一个") == "reason-fig"
    stem = "依次填入画横线部分最恰当的一项是："
    assert c("言语理解与表达", "逻辑填空", stem, ["不胫而走", "不翼而飞", "一蹴而就", "按部就班"]) == "verbal-idiom"
    assert c("言语理解与表达", "逻辑填空", stem, ["发挥", "发扬", "发展", "发起"]) == "verbal-word"
    assert c("言语理解与表达", "片段阅读", "这段文字意在说明：") == "verbal-intent"
    assert c("言语理解与表达", "语句表达", "将以上6个句子重新排列，语序正确的是：") == "verbal-order"
    assert c("常识判断", "常识判断", "根据《中华人民共和国民法典》，下列说法正确的是") == "common-law"
    assert c("不存在的模块", "", "x") == ""


def test_every_topic_points_to_a_lesson():
    titles = topics._lesson_titles()
    for t in topics.all_topics():
        assert t["lesson"] in titles, t


def test_score_estimate():
    full = {m: (10, 10) for m in scoring.SCORE_WEIGHTS}
    assert scoring.estimate_score(full) == 100
    half = {"资料分析": (10, 20), "常识判断": (0, 0)}
    assert scoring.estimate_score(half) == 50
    # 资料分析分值高：同样做对一半，资料全对比常识全对得分高
    a = scoring.estimate_score({"资料分析": (10, 10), "常识判断": (0, 10)})
    b = scoring.estimate_score({"资料分析": (0, 10), "常识判断": (10, 10)})
    assert a > 50 > b


def test_analysis_endpoint_and_topic_practice(client):
    _s, picked, _ = client.post("/api/bank/pick", {"src": "builtin", "module": "数量关系", "count": 12})
    _s, got, _ = client.post("/api/bank/get", {"ids": picked["ids"]})
    items = [{"qid": q["id"], "module": q["module"], "chosen": 0, "correct": False, "seconds": 200} for q in got["questions"]]
    _s, r, _ = client.post("/api/attempts", {"mode": "exam", "title": "模考 · 测试", "duration": 600, "items": items})
    assert r["score"] == 0
    status, a, _ = client.get("/api/analysis")
    assert status == 200 and a["topics"] and a["subs"]
    math = [t for t in a["topics"] if t["module"] == "数量关系" and t["n"]]
    assert math
    weak = a["weak"]
    assert all(t["recent_acc"] < 70 for t in weak)
    sub = next(x for x in a["subs"] if x["module"] == "数量关系")
    assert sub["over_pct"] > 0
    # 只练某个考点
    tid = max(math, key=lambda t: t["n"])["id"]
    _s, picked2, _ = client.post("/api/bank/pick", {"src": "builtin", "topic": tid, "count": 5})
    _s, got2, _ = client.post("/api/bank/get", {"ids": picked2["ids"]})
    for q in got2["questions"]:
        assert topics.classify(q["module"], q.get("sub"), q.get("stem"), q.get("options")) == tid
    _s, mh, _ = client.get("/api/mock/history")
    assert mh["items"] and mh["items"][-1]["score"] == 0 and mh["target"] > 0
    for q in got["questions"]:
        client.post("/api/wrongbook/delete", {"qid": q["id"]})
