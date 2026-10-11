"""多考试：考试清单、按 Cookie 切换考试、学习记录分库（公考原地不动）、共用表和共用偏好。"""

import pytest

from gongkao import exams, userdb

RK = "ruankao-arch"


@pytest.fixture()
def rk(client):
    """带着软考 Cookie 的客户端：之后的请求都读写软考的库。"""

    class RkClient:
        def _h(self, kw):
            h = dict(kw.pop("headers", None) or {})
            h["Cookie"] = f"{client.cookie}; {exams.COOKIE}={RK}"
            return h

        def get(self, path, **kw):
            return client.get(path, headers=self._h(kw), **kw)

        def post(self, path, body=None, **kw):
            return client.post(path, body, headers=self._h(kw), **kw)

    return RkClient()


def test_exam_list(client):
    status, r, _ = client.get("/api/exams")
    assert status == 200
    ids = [e["id"] for e in r["exams"]]
    assert ids[0] == "gongkao" and RK in ids
    assert r["current"] == "gongkao"
    gk = r["exams"][0]
    # 公考清单还原了原来的侧栏
    labels = [it.get("label") for it in gk["nav"]]
    assert labels[:3] == ["首页", "复习计划", "选岗"]
    assert gk["routes"][""] == "home" and gk["routes"]["positions"] == "positions"


def test_cookie_selects_exam(rk):
    status, r, _ = rk.get("/api/exams")
    assert r["current"] == RK
    status, d, _ = rk.get("/api/rk/dashboard")
    assert status == 200, d
    assert [s["name"] for s in d["exam"]["subjects"]] == ["综合知识", "案例分析", "论文"]
    assert d["exam_date"]


def test_unknown_cookie_falls_back(client):
    status, r, _ = client.get("/api/exams", headers={"Cookie": f"{client.cookie}; {exams.COOKIE}=nope"})
    assert r["current"] == "gongkao"


def test_attempts_are_separate(client, rk):
    item = {"qid": "rk-test-q1", "module": "综合知识", "chosen": 1, "correct": False, "seconds": 20}
    status, _, _ = rk.post("/api/attempts", {"mode": "practice", "items": [item], "duration": 30})
    assert status == 200
    _, wb_rk, _ = rk.get("/api/wrongbook")
    _, wb_gk, _ = client.get("/api/wrongbook")
    assert any(x["qid"] == "rk-test-q1" for x in wb_rk["items"])
    assert not any(x["qid"] == "rk-test-q1" for x in wb_gk["items"])
    # 软考的库在 exams/ruankao-arch/app.db，公考的 app.db 里没有这条
    with userdb.db(RK) as conn:
        assert conn.execute("SELECT COUNT(*) FROM main.attempts WHERE qid='rk-test-q1'").fetchone()[0] == 1
    with userdb.db("gongkao") as conn:
        assert conn.execute("SELECT COUNT(*) FROM attempts WHERE qid='rk-test-q1'").fetchone()[0] == 0
    assert exams.app_db(RK).exists()


def test_shared_tables_and_prefs(client, rk):
    # 打卡、笔记本是共用的：在软考里打卡，公考也看得到
    rk.post("/api/checkin", {"note": "软考打卡"})
    with userdb.db("gongkao") as conn:
        assert conn.execute("SELECT note FROM checkins WHERE note='软考打卡'").fetchone()
    with userdb.db(RK) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    assert not names & set(exams.SHARED_TABLES)
    assert "exam_settings" in names
    # 外观偏好共用，教程进度之类各考试分开
    rk.post("/api/prefs", {"theme": "dark", "course": {"x": 1}})
    _, p_gk, _ = client.get("/api/prefs")
    _, p_rk, _ = rk.get("/api/prefs")
    assert p_gk.get("theme") == "dark" and p_rk.get("theme") == "dark"
    assert p_rk.get("course") == {"x": 1} and p_gk.get("course") != {"x": 1}
    client.post("/api/prefs", {"theme": None})
    rk.post("/api/prefs", {"course": None})


def test_exam_settings(client, rk):
    status, s, _ = rk.post("/api/settings", {"exam_date": "2027-05-22", "daily_hours": "2.5", "review_cap": "250"})
    assert status == 200
    assert s["exam_date"] == "2027-05-22" and s["daily_hours"] == "2.5"
    _, gk, _ = client.get("/api/settings")
    assert gk["daily_hours"] != "2.5" or gk.get("exam_date") is None
    assert "exam_date" not in gk
    # 复习参数是共用设置：在软考里改，公考也变
    assert gk["review_cap"] == "250"
    client.post("/api/settings", {"review_cap": "300"})


def test_export_import_guard(client, rk):
    _, data, _ = rk.get("/api/export")
    assert data["exam"] == RK and "exam_settings" in data["tables"]
    status, r, _ = client.post("/api/import", data)
    assert status == 400 and "切换" in r["error"]


def test_overview(client):
    status, r, _ = client.get("/api/exams/overview")
    assert status == 200
    by = {e["id"]: e for e in r["exams"]}
    assert by["gongkao"]["dates"] and by[RK]["dates"]


def test_switch_remembers_default(client):
    status, r, _ = client.post("/api/exams/current", {"id": RK})
    assert status == 200 and exams.default_id() == RK
    status, r, _ = client.post("/api/exams/current", {"id": "nope"})
    assert status == 400
    client.post("/api/exams/current", {"id": "gongkao"})
    assert exams.default_id() == "gongkao"


def test_rk_plan_and_tasks(client, rk):
    status, p, _ = rk.get("/api/plan")
    assert status == 200, p
    assert [x["key"] for x in p["phases"]] == ["base", "real", "case", "sprint", "after"]
    assert [x["key"] for x in p["form"]] == ["exam_date", "start_date", "daily_hours"]
    assert len(p["rhythm"]) == 7 and len(p["week"]) == 7
    assert any(m["exam_day"] for m in p["milestones"])
    # 今日任务按软考的计划生成，链接都指向软考自己的页面
    _, d, _ = rk.get("/api/rk/dashboard")
    assert d["tasks"] and d["phase"]
    assert all(not t["link"] or t["link"].startswith("#/") for t in d["tasks"])
    # 公考的计划不受影响
    _, gp, _ = client.get("/api/plan")
    assert "rhythm" not in gp and gp["phases"][0]["exam"] == "国考"


def test_rk_plan_dates():
    from datetime import date

    from gongkao.ruankao import plan

    s = {"exam_date": "2027-05-22", "start_date": "2026-10-11", "daily_hours": "3"}
    ps = plan.phases(s, date(2026, 10, 11))
    assert ps[0]["start"] == "2026-10-11" and ps[-2]["end"] == "2027-05-21" and ps[-1]["start"] == "2027-05-22"
    assert 14 <= ps[3]["days"] <= 21
    # 相邻阶段首尾相接
    for a, b in zip(ps, ps[1:]):
        assert date.fromisoformat(a["end"]).toordinal() + 1 == date.fromisoformat(b["start"]).toordinal()
    # 备考第一天先学《软考全景》；考试日只提醒带证件
    nl = {"rk-start": {"id": "rk-start-01", "title": "软考全景", "min": 15}}
    first = plan.tasks_for_day(s, date(2026, 10, 11), nl)
    assert first[0]["link"] == "#/learn/rk-start-01"
    assert [t["title"] for t in plan.tasks_for_day(s, date(2027, 5, 22), nl)][0].startswith("考试日")
    # 离考试太近也能排
    short = plan.phases({"exam_date": "2026-10-20", "start_date": "2026-10-11"}, date(2026, 10, 11))
    assert short[-1]["key"] == "after" and short[0]["start"] == "2026-10-11"


def test_overview_conflicts():
    from gongkao.api.system import _date_conflicts

    items = [
        {"short": "公考", "name": "公考", "dates": [{"title": "省考笔试", "date": "2027-03-14", "days_left": 154}]},
        {"short": "软考", "name": "软考", "dates": [{"title": "软考", "date": "2027-03-20", "days_left": 160}]},
    ]
    c = _date_conflicts(items)
    assert len(c) == 1 and c[0]["days"] == 6
    items[1]["dates"][0].update(date="2027-05-22", days_left=223)
    assert _date_conflicts(items) == []


def test_server_materials_root_per_exam(monkeypatch):
    import os

    from gongkao import library

    monkeypatch.setenv("GONGKAO_LIBRARY_ROOT", "/srv/materials")
    exams.set_request(None)
    assert library._root_and_rel({"root": "D:/x"}, "a")[0] == "/srv/materials"
    exams.set_request(RK)
    try:
        assert library._root_and_rel({"root": "D:/x"}, "a")[0] == os.path.join("/srv/materials", "exams", RK)
    finally:
        exams.set_request(None)


def test_rk_drop_ad_blocks():
    from gongkao.ruankao.build import drop_ad_blocks

    ad = ["【软考达人】", "软考资料免费获取", "1、最新软考题库", "2、软考备考资料", "微信扫一扫，", "立马获取", "欧身达人", "6W+免费题库"]
    blocks = [{"k": "h", "t": "第2章 计算机系统基础知识", "pg": 0}] + [{"k": "p", "t": t, "pg": 0} for t in ad]
    blocks += [{"k": "h", "t": "免费备考资料计算机硬件", "pg": 0}, {"k": "p", "t": "立马获取", "pg": 3}]
    out = [b["t"] for b in drop_ad_blocks(blocks)]
    # 广告页上的广告词去掉，书签标题和粘在后面的正文标题留下；别的页零星的同样字眼不动
    assert out == ["第2章 计算机系统基础知识", "计算机硬件", "立马获取"]
