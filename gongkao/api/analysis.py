"""做题分析：按考点找弱项（对应到教程的课）、按题型看用时、建议的模块作答顺序、模考估分。"""

from .. import topics
from ..scoring import SCORE_WEIGHTS, estimate_score
from ..userdb import get_settings
from . import route
from .practice import bank

# 各题型每题的参考用时（秒），按 120 分钟做完 130 题、各模块常见分配折算
TARGET_SECONDS = {
    "政治理论": 30, "常识判断": 35, "逻辑填空": 40, "片段阅读": 60, "语句表达": 60, "数学运算": 75, "数字推理": 50,
    "图形推理": 45, "定义判断": 50, "类比推理": 30, "逻辑判断": 70, "资料分析": 70,
}
MODULE_TARGET = {"政治理论": 30, "常识判断": 35, "言语理解与表达": 50, "数量关系": 75, "判断推理": 50, "资料分析": 70}

MODULES = list(SCORE_WEIGHTS)


def _target(module, sub):
    return TARGET_SECONDS.get(sub) or MODULE_TARGET.get(module) or 60


@route("GET", "/api/analysis")
def analysis(ctx):
    b = bank()
    tmap = b.topic_map()
    sub_of = {r[0]: (r[1], r[2]) for r in b.index}
    attempts = ctx.conn.execute(
        "SELECT qid, module, correct, seconds, created_at FROM attempts WHERE mode != '资料例题' ORDER BY id").fetchall()

    # ---- 考点
    per_topic = {}
    for a in attempts:
        tid = tmap.get(a["qid"])
        if not tid:
            continue
        t = per_topic.setdefault(tid, {"n": 0, "ok": 0, "sec": 0, "timed": 0, "recent": []})
        t["n"] += 1
        t["ok"] += a["correct"] or 0
        if a["seconds"]:
            t["sec"] += a["seconds"]
            t["timed"] += 1
        t["recent"] = (t["recent"] + [a["correct"] or 0])[-20:]
    available = {}
    for qid, tid in tmap.items():
        available[tid] = available.get(tid, 0) + 1
    topic_rows = []
    for tp in topics.all_topics():
        st = per_topic.get(tp["id"], {"n": 0, "ok": 0, "sec": 0, "timed": 0, "recent": []})
        topic_rows.append({
            **tp, "n": st["n"], "correct": st["ok"], "acc": round(st["ok"] / st["n"] * 100) if st["n"] else None,
            "recent_acc": round(sum(st["recent"]) / len(st["recent"]) * 100) if st["recent"] else None,
            "avg_sec": round(st["sec"] / st["timed"]) if st["timed"] else None, "available": available.get(tp["id"], 0),
        })
    # 弱项：做过至少 5 题、最近正确率低于 70%，按正确率从低到高
    weak = sorted((t for t in topic_rows if t["n"] >= 5 and (t["recent_acc"] or 0) < 70 and t["available"]),
                  key=lambda t: (t["recent_acc"], -t["n"]))[:8]

    # ---- 题型用时
    per_sub = {}
    for a in attempts:
        if not a["seconds"]:
            continue
        module, sub = sub_of.get(a["qid"], (a["module"], ""))
        key = (module or a["module"] or "", sub or "")
        s = per_sub.setdefault(key, {"n": 0, "ok": 0, "sec": 0, "over": 0, "slow_right": 0, "fast_wrong": 0})
        target = _target(*key)
        s["n"] += 1
        s["ok"] += a["correct"] or 0
        s["sec"] += a["seconds"]
        if a["seconds"] > target * 1.5:
            s["over"] += 1
            if a["correct"]:
                s["slow_right"] += 1
        elif a["seconds"] < target * 0.4 and not a["correct"]:
            s["fast_wrong"] += 1
    sub_rows = []
    for (module, sub), s in sorted(per_sub.items(), key=lambda kv: (MODULES.index(kv[0][0]) if kv[0][0] in MODULES else 9, kv[0][1])):
        sub_rows.append({"module": module, "sub": sub or module, "n": s["n"], "acc": round(s["ok"] / s["n"] * 100),
                         "avg_sec": round(s["sec"] / s["n"]), "target": _target(module, sub),
                         "over_pct": round(s["over"] / s["n"] * 100), "slow_right": s["slow_right"],
                         "fast_wrong": s["fast_wrong"]})

    # ---- 作答顺序：每分钟能拿到的分（正确率 × 分值 ÷ 平均用时）高的先做
    per_mod = {}
    for a in attempts:
        if not a["seconds"] or a["module"] not in SCORE_WEIGHTS:
            continue
        m = per_mod.setdefault(a["module"], [0, 0, 0])
        m[0] += 1
        m[1] += a["correct"] or 0
        m[2] += a["seconds"]
    order = []
    for m, (n, ok, sec) in per_mod.items():
        if n < 10:
            continue
        acc = ok / n
        order.append({"module": m, "n": n, "acc": round(acc * 100), "avg_sec": round(sec / n),
                      "per_min": round(acc * SCORE_WEIGHTS[m] / (sec / n) * 60, 2)})
    order.sort(key=lambda x: -x["per_min"])
    return {"topics": topic_rows, "weak": weak, "subs": sub_rows, "order": order}


@route("GET", "/api/mock/history")
def mock_history(ctx):
    """模考、限时练习、真题整卷的估分记录（按模块正确数折算），用来看分数走势。"""
    conn = ctx.conn
    target = float(get_settings(conn).get("target_score") or 70)
    sessions = conn.execute("SELECT id, title, total, correct, duration, created_at FROM sessions WHERE mode='exam' "
                            "ORDER BY id DESC LIMIT 60").fetchall()
    out = []
    for s in sessions:
        per = {}
        for r in conn.execute("SELECT module, COUNT(*) AS n, SUM(correct) AS ok FROM attempts WHERE session_id=? GROUP BY module",
                              (s["id"],)):
            per[r["module"]] = (r["ok"] or 0, r["n"])
        if not per:
            continue
        out.append({"id": s["id"], "title": s["title"], "created_at": s["created_at"], "total": s["total"],
                    "correct": s["correct"], "duration": s["duration"], "score": estimate_score(per),
                    "modules": {m: {"ok": ok, "n": n} for m, (ok, n) in per.items()}})
    return {"items": out[::-1], "target": target, "weights": SCORE_WEIGHTS}
