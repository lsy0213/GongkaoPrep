"""选岗：职位表导入、条件判断、筛选、报名人数。"""

import io

import openpyxl

from gongkao import positions as P

GK_HEAD = ["部门代码", "部门名称", "用人司局", "机构性质", "招考职位", "职位属性", "职位分布", "职位简介", "职位代码", "机构层级",
           "考试类别", "招考人数", "专业", "学历", "学位", "政治面貌", "基层工作最低年限", "服务基层项目工作经历",
           "是否在面试阶段组织专业能力测试", "面试人员比例", "工作地点", "落户地点", "备注"]


def _xlsx(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(code, title, count, major, edu, politics="不限", years="无限制", project="无限制", region="四川省成都市"):
    vals = dict(zip(GK_HEAD, [""] * len(GK_HEAD)))
    vals.update({"部门代码": "100", "部门名称": "国家税务总局成都市税务局", "用人司局": "第一税务分局", "招考职位": title,
                 "职位代码": code, "招考人数": count, "专业": major, "学历": edu, "学位": "与最高学历相对应的学位",
                 "政治面貌": politics, "基层工作最低年限": years, "服务基层项目工作经历": project, "工作地点": region})
    return [vals[h] for h in GK_HEAD]


def sample():
    return _xlsx({
        "中央国家行政机关省级以下直属机构": [
            ["2027年度中央机关及其直属机构考试录用公务员职位表"],
            GK_HEAD,
            _row("300110001001", "一级行政执法员（一）", 3, "计算机类", "本科及以上"),
            _row("300110001002", "一级行政执法员（二）", 2, "财务财会类、经济学类", "仅限本科", politics="中共党员"),
            _row("300110001003", "一级主任科员及以下", 1, "不限", "硕士研究生及以上", years="二年"),
            _row("300110001004", "一级科员", 1, "法学类", "本科或硕士研究生", project="大学生村官"),
            ["合计", "", "", "", "", "", "", "", "", "", "", 7],
        ],
        "说明": [["本表仅供参考"]],
    })


def test_condition_rules():
    assert P.edu_ok("本科及以上", "本科") and P.edu_ok("本科及以上", "硕士研究生") and not P.edu_ok("本科及以上", "大专")
    assert P.edu_ok("仅限本科", "本科") and not P.edu_ok("仅限本科", "硕士")
    assert P.edu_ok("本科或硕士研究生", "硕士") and not P.edu_ok("本科或硕士研究生", "博士")
    assert P.politics_ok("中共党员", "中共党员") and not P.politics_ok("中共党员", "共青团员")
    assert P.politics_ok("中共党员或共青团员", "共青团员") and P.politics_ok("不限", "")
    assert P.years_required("二年") == 2 and P.years_required("无限制") == 0 and P.years_required("3年") == 3
    assert P.major_ok("计算机类", ["计算机类"]) and not P.major_ok("法学类", ["计算机类"]) and P.major_ok("不限", ["x"])


def test_import_and_search(client):
    data = sample()
    status, r, _ = client.request("POST", "/api/positions/upload?file=test.xlsx&name=2027国考",
                                  body=data, headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    assert status == 200 and r["count"] == 4  # 合计行和说明表不算
    bid = r["batch"]
    client.post("/api/prefs", {"job_profile": {"edu": "本科", "politics": "共青团员", "years": 0, "project": False, "majors": ["计算机类"]}})
    _s, all_, _ = client.post("/api/positions/search", {"batch": bid})
    assert all_["total"] == 4
    _s, mine, _ = client.post("/api/positions/search", {"batch": bid, "mine": True})
    assert [p["code"] for p in mine["items"]] == ["300110001001"]
    blocked = {p["code"]: p["blocked"] for p in all_["items"]}
    assert "政治面貌" in blocked["300110001002"] and "专业" in blocked["300110001002"]
    assert set(blocked["300110001003"]) >= {"学历", "基层年限"}
    assert "服务基层项目" in blocked["300110001004"]
    _s, q, _ = client.post("/api/positions/search", {"batch": bid, "q": "主任科员"})
    assert q["total"] == 1
    # 报名人数
    appl = _xlsx({"Sheet1": [["职位代码", "过审人数"], ["300110001001", 300], ["300110001002", 50]]})
    _s, a, _ = client.request("POST", f"/api/positions/applicants?batch={bid}&file=a.xlsx", body=appl,
                              headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    assert a["matched"] == 2
    _s, srt, _ = client.post("/api/positions/search", {"batch": bid, "sort": "ratio"})
    assert srt["items"][0]["ratio"] == 25.0 and srt["items"][1]["ratio"] == 100.0
    client.post("/api/positions/delete", {"batch": bid})
    client.post("/api/prefs", {"job_profile": None})


def test_bad_file(client):
    status, r, _ = client.request("POST", "/api/positions/upload?file=x.xlsx", body=_xlsx({"S": [["a", "b"], [1, 2]]}),
                                  headers={"Content-Type": "application/octet-stream"})
    assert status == 400 and "职位表" in r["error"]
    status, _r, _ = client.request("POST", "/api/positions/upload?file=x.xlsx", body=b"x", headers={"Content-Type": "text/plain"})
    assert status == 403
