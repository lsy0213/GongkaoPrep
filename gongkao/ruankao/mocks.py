"""资料文件夹里的模拟题（希赛模拟卷 PDF）。

综合知识卷：“一、单项选择题”下面是“1、题干……A．B．C．D．”，共用题干的几道题前面先印一段题干，空的位置是题号
（“其中供应关系是6 的联系”），后面的“6、A．…”“7、A．…”只有选项；“答案:”之后是“1、B  [解析] ……”。
案例卷：“试题一 [说明] … 1、[问题1] …”，问题按全卷顺序编号，“答案:”之后按同样的编号给答案。
论文卷：和真题的论文试卷一个格式（papers.parse_essay_paper）。
文件放在哪个文件夹不一定对（“案例分析模拟题”里也有综合知识卷），按内容判断是哪一科。
"""

import os
import re

from . import papers
from .pdflines import join_lines, read_lines, tidy

ITEM_RE = re.compile(r"^(\d{1,2})\s*[、.．]\s*(.*)$")
OPT_LINE_RE = re.compile(r"^\s*([A-D])\s*[．.、]")
ANS_HEAD_RE = re.compile(r"^\s*(?:参考)?答案\s*[:：]\s*$")


def _kind(lines):
    text = "\n".join(ln.text for ln in lines[:400])
    if re.search(r"单项选择题", text):
        return "zh"
    if re.search(r"\[\s*问题\s*\d\s*\]|【\s*问题\s*\d\s*】", text) or (
            re.search(r"(?m)^\s*试题\s*[一二]\s*$", text) and re.search(r"[\[【]\s*说明\s*[\]】]", text)):
        return "al"
    if re.search(r"(?m)^\s*论\S{3,}", text) and re.search(r"论题|为题", text):
        return "lw"
    return ""


def _split_answer_part(lines):
    k = next((i for i, ln in enumerate(lines) if ANS_HEAD_RE.match(ln.text)), None)
    return (lines, []) if k is None else (lines[:k], lines[k + 1:])


def _mark_blanks(stem, nums):
    """共用题干里的空是光秃秃的题号（“是6 的联系”），改成“（6）”，好取出每一空所在的那句话。"""
    for n in nums:
        stem = re.sub(rf"(?<=[一-鿿，、：:（(“])\s*{n}\s*(?=[一-鿿，。、；：)）”])", f"（{n}）", stem, count=1)
    return stem


def parse_zh(lines):
    """→ [{num, stem, options, answer, explain, group}]。"""
    qpart, apart = _split_answer_part(lines)
    items, cur, pre = [], None, []
    for ln in qpart:
        t = ln.text
        if re.match(r"^[一二三四五六]、\s*单项选择题", t):
            pre = []
            continue
        m = ITEM_RE.match(t)
        if m and 1 <= int(m.group(1)) <= 75 and (not items or 1 <= int(m.group(1)) - items[-1]["num"] <= 3):
            cur = {"num": int(m.group(1)), "lines": [m.group(2)] if m.group(2).strip() else []}
            items.append(cur)
        elif cur is not None:
            cur["lines"].append(t)
        else:
            pre.append(t)
    # 每题：题干 + 四个选项；D 选项之后多出来的长行，若下一题只有选项，就是下一组的共用题干
    for i, it in enumerate(items):
        ls = it["lines"]
        d = next((k for k, x in enumerate(ls) if re.match(r"^\s*D\s*[．.、]", x)), None)
        it["tail"] = []
        if d is not None:
            k = d + 1
            while k < len(ls) and len(ls[k]) <= 12 and not OPT_LINE_RE.match(ls[k]):
                k += 1
            nxt_opts_only = i + 1 < len(items) and items[i + 1]["lines"] and OPT_LINE_RE.match(items[i + 1]["lines"][0])
            if nxt_opts_only:
                it["tail"], it["lines"] = ls[k:], ls[:k]
    out, group_stem, group_nums = [], tidy(join_lines(pre)), []
    for i, it in enumerate(items):
        text = "\n".join(it["lines"])
        first_opt = re.search(r"(?m)^\s*A\s*[．.、]", text)
        if not first_opt:
            continue
        own = text[:first_opt.start()].strip()
        if own:
            stem, group = tidy(join_lines(own.splitlines())), None
            group_stem, group_nums = "", []
        else:
            if not group_stem and i > 0:
                group_stem = tidy(join_lines(items[i - 1]["tail"]))
                group_nums = []
            stem, group = group_stem, group_stem
            group_nums.append(it["num"])
        opts = papers._split_options(text[first_opt.start():].replace("\n", " "))
        if not opts:
            continue
        out.append({"num": it["num"], "stem": stem, "options": opts, "group": group})
        if i + 1 < len(items) and items[i]["tail"]:
            group_stem = tidy(join_lines(items[i]["tail"]))
    # 答案和解析
    ans, cur = {}, None
    for ln in apart:
        m = re.match(r"^(\d{1,2})\s*[、.．]\s*([A-D])\s*(.*)$", ln.text)
        if m:
            cur = int(m.group(1))
            ans[cur] = {"answer": "ABCD".index(m.group(2)), "lines": [m.group(3)] if m.group(3).strip() else []}
        elif cur is not None and not re.match(r"^[一二三四五六]、", ln.text):
            ans[cur]["lines"].append(ln.text)
    for q in out:
        a = ans.get(q["num"])
        if a:
            q["answer"] = a["answer"]
            q["explain"] = tidy(join_lines(a["lines"])).removeprefix("[解析]").strip()
        else:
            q["answer"], q["explain"] = None, ""
    # 共用题干里标出每一空
    groups = {}
    for q in out:
        if q["group"]:
            groups.setdefault(q["group"], []).append(q["num"])
    for q in out:
        if q["group"]:
            marked = _mark_blanks(q["group"], groups[q["group"]])
            q["group"] = marked
            q["stem"] = papers._clause(marked, q["num"])
    return out


CASE_RE = re.compile(r"^\s*试题\s*([一二三四五六七八九])\s*$")
CQ_RE = re.compile(r"^(\d{1,2})\s*[、.．]\s*(?:[\[【]\s*问题\s*(\d)\s*[\]】])?\s*(?:[(（]\s*(\d+)\s*分\s*[)）])?\s*(.*)$")


def parse_case(lines):
    qpart, apart = _split_answer_part(lines)
    sets, cur, q = [], None, None
    for ln in qpart:
        m = CASE_RE.match(ln.text)
        if m:
            cur = {"no": "一二三四五六七八九".index(m.group(1)) + 1, "mlines": [], "questions": []}
            sets.append(cur)
            q = None
            continue
        if cur is None:
            continue
        m = CQ_RE.match(ln.text)
        last_k = max([x["k"] for s2 in sets for x in s2["questions"]], default=0)
        if m and (m.group(2) or (int(m.group(1)) == last_k + 1 and re.search(r"请|说明|指出|简要|给出|分析|计算|填", m.group(4)))):
            q = {"k": int(m.group(1)), "n": int(m.group(2) or len(cur["questions"]) + 1), "score": int(m.group(3) or 0),
                 "lines": [m.group(4)] if m.group(4).strip() else []}
            cur["questions"].append(q)
        elif q is not None:
            q["lines"].append(ln.text)
        else:
            cur["mlines"].append(ln.text)
    ans, k = {}, None
    for ln in apart:
        if CASE_RE.match(ln.text):
            continue
        m = re.match(r"^(\d{1,2})\s*[、.．]\s*(.*)$", ln.text)
        if m and int(m.group(1)) == (k or 0) + 1:
            k = int(m.group(1))
            ans[k] = [m.group(2)] if m.group(2).strip() else []
        elif k is not None:
            ans[k].append(ln.text)
    out = []
    for s in sets:
        if not s["questions"]:
            continue
        material = tidy(join_lines(s["mlines"]))
        qs = [{"n": q["n"], "score": q["score"], "text": tidy(join_lines(q["lines"])),
               "answer": tidy(join_lines(ans.get(q["k"], [])))} for q in s["questions"]]
        out.append({"no": s["no"], "title": "", "material": material, "questions": qs, "analysis": "",
                    "score": sum(q["score"] for q in qs) or 25})
    return out


def _essay_guides(lines):
    """论文模拟卷“答案:”之后，按“试题一……”分开的写作要点。"""
    out, cur = {}, None
    for ln in lines:
        m = CASE_RE.match(ln.text)
        if m:
            cur = "一二三四五六七八九".index(m.group(1)) + 1
            out[cur] = []
        elif cur is not None:
            out[cur].append(ln.text)
    return {k: tidy(join_lines(v)) for k, v in out.items()}


GENERIC_SET_RE = re.compile(r"(?m)^\s*(?:第\s*(\d)\s*题\s*[（(]\s*案例题\s*[)）]\s*[:：]?|\[\s*案例题\s*\]|试题\s*([一二三四五]))\s*$")


def parse_case_generic(text):
    """其他排法的案例卷（“第1题（案例题）：”“[案例题]”，问题用【问题N】，答案按【问题N】再来一遍）。"""
    from .mdimport import _split_case

    sets = list(GENERIC_SET_RE.finditer(text))
    out = []
    for i, m in enumerate(sets):
        body = text[m.end(): sets[i + 1].start() if i + 1 < len(sets) else len(text)]
        material, qs, analysis = _split_case(body)
        if qs:
            out.append({"no": i + 1, "title": "", "material": material, "questions": qs, "analysis": analysis,
                        "score": sum(q["score"] for q in qs) or 25})
    return out


def collect(cat, job=None):
    """资料文件夹里所有模拟题 → (sources, questions, materials, cases, essays)。"""
    root = cat.get("root") or ""
    files = [f for f in cat.get("files", []) if f.get("cat") == "模拟题" and f.get("ext") == "pdf" and f.get("text", True)]
    seen = set()
    sources, qs, mats, cases, essays = [], [], [], [], []
    for i, f in enumerate(files):
        if job:
            job.progress("解析模拟题", i, len(files), f["name"])
        if f["name"] in seen:  # 同一份文件放在两个文件夹（考前冲刺）
            continue
        seen.add(f["name"])
        try:
            lines = read_lines(os.path.join(root, f["rel"]))
        except Exception:  # noqa: BLE001
            continue
        kind = _kind(lines)
        name = re.sub(r"\.pdf$", "", f["name"])
        sid = f"rkx-{f['id'][2:8]}"
        if kind == "zh":
            items = parse_zh(lines)
            mat_of = {}
            for q in items:
                if q["group"] and q["group"] not in mat_of:
                    nums = [x["num"] for x in items if x["group"] == q["group"]]
                    mid = f"{sid}-m{q['num']}"
                    mat_of[q["group"]] = mid
                    mats.append({"id": mid, "source": sid, "title": f"第 {nums[0]}–{nums[-1]} 题共用题干", "text": q["group"],
                                 "crop": [], "fig": 0, "fid": f["id"]})
            got = []
            for q in items:
                got.append({"id": f"{sid}-{q['num']:02d}", "source": sid, "num": q["num"], "stem": q["stem"],
                            "options": q["options"], "answer": q["answer"], "explain": q["explain"],
                            "material": mat_of.get(q["group"]), "crop": [], "fig": 0, "year": 0, "src": "模拟",
                            "origin": name, "fid": f["id"]})
            if got:
                from .build import _classify

                qs += [_classify(x) for x in got]
                sources.append({"id": sid, "title": f"模拟卷 · {name}", "exam": "软考", "year": 0, "level": "",
                                "module": "综合知识", "file": f["rel"], "fid": f["id"], "count": len(got),
                                "answered": sum(1 for x in got if x["answer"] is not None), "note": "资料文件夹 · 模拟题"})
        elif kind == "al":
            got = parse_case(lines) or parse_case_generic("\n".join(ln.text for ln in lines))
            for c in got:
                cases.append({**c, "id": f"{sid}-c{c['no']}", "year": 0, "half": "", "kind": "mock",
                              "source": f"模拟卷 · {name}", "fid": f["id"], "required": c["no"] == 1})
        elif kind == "lw":
            qpart, apart = _split_answer_part(lines)
            guides = _essay_guides(apart)
            for e in papers.parse_essay_paper(None, qpart):
                essays.append({**e, "id": f"{sid}-e{e['no']}", "year": 0, "half": "", "kind": "mock",
                               "source": f"模拟卷 · {name}", "fid": f["id"], "guide": guides.get(e["no"], "")})
    return sources, qs, mats, cases, essays
