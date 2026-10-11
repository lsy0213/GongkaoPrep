"""开源题库（GitHub wujiaming88/awesome-ruankao，CC BY-SA 4.0）的 Markdown → 题库记录。

真题（2020 年至今，很多是考后回忆版）一份文件一科：综合知识.md / 案例分析.md / 论文.md；
模拟卷题目和答案分开：综合知识_题目.md + 综合知识_答案.md，案例、论文同理。
各份文件的写法不太统一（“### 第N题”“## 第N题”，“**答案**: B”“**验证答案：D**”，案例的参考答案有的跟在每问后面、
有的集中在最后），这里都按“标题 + 关键词”宽松地解析。下载用仓库的 zip（一次请求，不受 API 次数限制）。
"""

import io
import json
import os
import re
import time
import urllib.request
import zipfile

from . import lib_dir

REPO = "wujiaming88/awesome-ruankao"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"
SOURCE_NOTE = f"开源题库 github.com/{REPO}（CC BY-SA 4.0）"
WANT_RE = re.compile(r"系统架构设计师|^论文/|^案例分析/解题技巧|^docs/政策与考试指南|^docs/备考攻略/(?:机考|论文|案例|综合)")


def gh_dir():
    return lib_dir() / "github"


def download(job=None):
    """下载仓库 zip，只取系统架构设计师相关的 Markdown，存到 library/github/（zip 本身不留）。"""
    if job:
        job.progress("下载开源题库", 0, 1, ZIP_URL)
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "GongkaoPrep"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 —— 固定的 https 地址
        data = r.read()
    out = gh_dir()
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            if not name.endswith(".md") or not WANT_RE.search(name):
                continue
            parts = [p for p in name.split("/") if p not in ("", ".", "..")]
            dst = out.joinpath(*parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(info))
            n += 1
    (out / "_source.json").write_text(json.dumps({"repo": REPO, "license": "CC BY-SA 4.0", "files": n,
                                                  "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                                                 ensure_ascii=False), encoding="utf-8")
    return n


# ---------------------------------------------------------------- 文字

def strip_md(t):
    """去掉 Markdown 的加粗、标题井号、引用号，留下文字（列表的“- ”留着）。"""
    t = re.sub(r"\*\*|__", "", t or "")
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*>\s?", "", t)
    t = re.sub(r"(?m)^\s*---+\s*$", "", t)
    t = re.sub(r"<br\s*/?>", "\n", t)
    return t


def clean(t):
    t = strip_md(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ---------------------------------------------------------------- 综合知识

Q_HEAD_RE = re.compile(r"(?m)^#{2,4}\s*第\s*(\d{1,2})\s*题.*$")
OPT_RE = re.compile(r"(?m)^\s*(?:[-*]\s*)?\**([A-D])\**\s*[.．、:：]\s*(.*)$")
ANS_RE = re.compile(r"(?:\*\*)?(?:验证)?(?:正确)?答案(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*([A-D])")
EXP_RE = re.compile(r"(?:\*\*)?(?:解析|验证依据|答案解析)(?:\*\*)?\s*[:：](?:\*\*)?\s*")


def _sections(text):
    hs = list(Q_HEAD_RE.finditer(text))
    for i, m in enumerate(hs):
        yield int(m.group(1)), text[m.end(): hs[i + 1].start() if i + 1 < len(hs) else len(text)]


def _cut_tail(body):
    """一题的正文到“---”分隔线或下一个大标题为止。"""
    m = re.search(r"(?m)^\s*(?:---+|#{1,2}\s)", body)
    return body[:m.start()] if m else body


def parse_choice(text, answers_text=None):
    """→ [{num, stem, options, answer, explain}]。answers_text 是模拟卷单独的答案文件。"""
    ans = {}
    if answers_text:
        for num, body in _sections(answers_text):
            body = _cut_tail(body)
            a = ANS_RE.search(body)
            e = EXP_RE.search(body)
            ans[num] = ("ABCD".index(a.group(1)) if a else None, clean(body[e.end():]) if e else "")
    out = []
    for num, body in _sections(text):
        body = _cut_tail(body)
        opts_m = list(OPT_RE.finditer(body))
        # 只认第一组 A–D（解析里也可能出现“A.”）
        first = next((i for i, m in enumerate(opts_m) if m.group(1) == "A"), None)
        if first is None or first + 3 >= len(opts_m):
            continue
        grp = opts_m[first: first + 4]
        if [m.group(1) for m in grp] != list("ABCD"):
            continue
        stem = clean(body[:grp[0].start()])
        stem = re.sub(r"^(?:题目|题干)\s*[:：]\s*", "", stem)
        stem = re.sub(r"(?m)^\s*选项(?:[（(].*?[)）])?\s*[:：]?\s*$", "", stem).strip()
        options = [clean(m.group(2)) for m in grp]
        rest = body[grp[-1].end():]
        if num in ans:
            answer, explain = ans[num]
        else:
            a = ANS_RE.search(rest)
            e = EXP_RE.search(rest)
            answer = "ABCD".index(a.group(1)) if a else None
            explain = clean(rest[e.end():]) if e else ""
        explain = re.sub(r"(?m)^\s*(?:验证答案|答案)\s*[:：].*$", "", explain).strip()
        if stem and all(options):
            out.append({"num": num, "stem": stem, "options": options, "answer": answer, "explain": explain})
    return out


# ---------------------------------------------------------------- 案例分析

CN = "一二三四五六七八九"
SET_RE = re.compile(r"(?m)^#{1,4}\s*(?:\d+(?:\.\d+)*\.?\s*)?试题\s*([一二三四五六七八九1-9])\s*(.*)$")


def _no(ch):
    return int(ch) if ch.isdigit() else CN.index(ch) + 1
QH_RE = re.compile(r"(?m)^\s*(?:#{2,4}\s*)?【?\s*问题\s*(\d)\s*】?\s*(?:[(（]\s*(\d+)\s*分[^)）]*[)）])?\s*[：:]?")
AM_RE = re.compile(r"(?m)^\s*(?:#{1,4}\s*)?(?:【\s*参考答案\s*】|参考答案\s*[:：]?|答案(?:与解析)?\s*[:：]?)\s*$")
TAIL_RE = re.compile(r"(?m)^\s*(?:#{2,4}\s*)?(?:【\s*题型分析\s*】|题型分析|考点分析|答题技巧|【\s*解析\s*】)\s*$")


def _case_sets(text):
    t = re.sub(r"\*\*", "", text)
    sets = list(SET_RE.finditer(t))
    for i, m in enumerate(sets):
        yield _no(m.group(1)), m.group(2).strip(" ：:（）()—-"), t[m.end(): sets[i + 1].start() if i + 1 < len(sets) else len(t)]


def _split_case(body, answers_body=None):
    """一道案例 → (说明材料, [{n, score, text, answer}], 解析)。"""
    analysis = ""
    tm = TAIL_RE.search(body)
    if tm:
        analysis, body = clean(body[tm.end():]), body[:tm.start()]
    qh = list(QH_RE.finditer(body))
    if not qh:
        return clean(body), [], analysis
    am = AM_RE.search(body)
    if am is None and answers_body is None:
        # 没有“答案”标记，但问题号从头又来了一遍（问题 1、2、3、1、2、3）：后一遍是答案
        restart = next((k for k in range(1, len(qh)) if int(qh[k].group(1)) <= int(qh[k - 1].group(1))), None)
        if restart:
            answers_body = body[qh[restart].start():]
            body = body[:qh[restart].start()]
            qh = qh[:restart]
    questions = []
    if answers_body is None and am:
        # 问题集中列在前面、答案集中在后面：第一个“答案”标记前面有两个以上问题，后面又出现问题号
        before = [h for h in qh if h.start() < am.start()]
        after = [h for h in qh if h.start() > am.start()]
        if len(before) >= 2 and after:
            answers_body = body[am.end():]
            body = body[:am.start()]
            qh = before
    material = clean(body[:qh[0].start()])
    material = re.sub(r"^(?:题目描述|题目背景|考点内容|说明)\s*", "", material)
    for k, h in enumerate(qh):
        seg = body[h.end(): qh[k + 1].start() if k + 1 < len(qh) else len(body)]
        am2 = AM_RE.search(seg)
        qtext, ans = (seg[:am2.start()], seg[am2.end():]) if am2 else (seg, "")
        questions.append({"n": int(h.group(1)), "score": int(h.group(2) or 0), "text": clean(qtext), "answer": clean(ans)})
    if answers_body:
        ah = list(QH_RE.finditer(answers_body))
        if not ah:
            ah = list(re.finditer(r"(?m)^\s*问题\s*(\d)\s*[^\n]{0,12}[：:]", answers_body))
        for k, h in enumerate(ah):
            seg = answers_body[h.end(): ah[k + 1].start() if k + 1 < len(ah) else len(answers_body)]
            q = next((x for x in questions if x["n"] == int(h.group(1))), None)
            if q is not None and not q["answer"]:
                q["answer"] = clean(seg)
        if not ah and questions and not questions[0]["answer"]:
            questions[0]["answer"] = clean(answers_body)
    return material, questions, analysis


def _missing(t):
    return not t or re.match(r"^\s*(?:[(（]\s*\d+\s*分\s*[)）])?\s*(?:暂缺|缺失|略|无)\s*[。.]?\s*$", t)


def parse_cases(text, answers_text=None):
    ans_sets = {no: body for no, _t, body in _case_sets(answers_text)} if answers_text else {}
    out = []
    for no, title, body in _case_sets(text):
        material, qs, analysis = _split_case(body, ans_sets.get(no))
        if not qs:
            continue
        for q in qs:
            if _missing(q["answer"]):
                q["answer"] = ""
        out.append({"no": no, "title": title, "material": material, "questions": qs, "analysis": analysis,
                    "score": sum(q["score"] for q in qs) or 25})
    return out


# ---------------------------------------------------------------- 论文

ESSAY_SET_RE = re.compile(r"(?m)^#{1,4}\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:试题|论文)\s*([一二三四五六七八九1-9])\s*[：:、.．]?\s*(.*)$")
GUIDE_RE = re.compile(r"(?m)^\s*(?:#{1,4}\s*)?(?:\*\*)?(?:解析|写作要点|写作指导|论文素材参考|参考范文|范文|答题思路|写作思路)(?:\*\*)?\s*[:：]?\s*(?:\*\*)?\s*$")
TOPIC_RE = re.compile(r"请(?:围绕|以|结合)\s*[“\"「]([^”\"」]{2,40})[”\"」]\s*(?:论.|为题|为主题)[^。：:\n]{0,30}?论述\s*[。：:.]?")


def parse_essays(text, answers_text=None):
    ans = {}
    if answers_text:
        sets = list(ESSAY_SET_RE.finditer(answers_text))
        for i, m in enumerate(sets):
            ans[_no(m.group(1))] = clean(answers_text[m.end(): sets[i + 1].start() if i + 1 < len(sets) else len(answers_text)])
    out = []
    sets = list(ESSAY_SET_RE.finditer(text))
    for i, m in enumerate(sets):
        no = _no(m.group(1))
        body = text[m.end(): sets[i + 1].start() if i + 1 < len(sets) else len(text)]
        g = GUIDE_RE.search(body)
        guide = clean(body[g.end():]) if g else ""
        body = body[:g.start()] if g else body
        body = clean(body)
        title = m.group(2).strip(" ：:") or ""
        tm = TOPIC_RE.search(body)
        if tm:
            background, req = body[:tm.start()].strip(), body[tm.end():]
            if not title:
                title = tm.group(1) if tm.group(1).startswith("论") else "论" + tm.group(1)
        else:
            k = re.search(r"(?m)^\s*1\s*[.．、]", body)
            background, req = (body[:k.start()].strip(), body[k.start():]) if k else (body, "")
        reqs = [r.strip() for r in re.split(r"(?m)^\s*(?:[1-4][.．、]|[（(][1-4][)）])\s*", req) if r.strip()]
        if not title:
            continue
        out.append({"no": no, "title": title.rstrip("。."), "background": background, "requirements": reqs,
                    "guide": guide or ans.get(no, "")})
    return out


# ---------------------------------------------------------------- 整个目录

def year_half_of(path_part):
    m = re.search(r"(20\d\d)\s*年\s*(上半年|下半年|\d{1,2}\s*月)", path_part)
    if not m:
        return 0, ""
    h = m.group(2)
    half = h if "半年" in h else ("上半年" if int(re.sub(r"\D", "", h)) <= 6 else "下半年")
    return int(m.group(1)), half


def collect():
    """读 library/github/ 下的真题和模拟卷 → {"papers": [...], "mocks": [...]}，每份含 choice/cases/essays。"""
    root = gh_dir()
    out = {"papers": [], "mocks": []}
    real = root / "真题" / "系统架构设计师"
    if real.is_dir():
        for d in sorted(p for p in real.iterdir() if p.is_dir()):
            year, half = year_half_of(d.name)
            item = {"year": year, "half": half, "label": d.name, "dir": str(d.relative_to(root))}
            f = d / "综合知识.md"
            item["choice"] = parse_choice(f.read_text(encoding="utf-8")) if f.exists() else []
            f = d / "案例分析.md"
            item["cases"] = parse_cases(f.read_text(encoding="utf-8")) if f.exists() else []
            f = d / "论文.md"
            item["essays"] = parse_essays(f.read_text(encoding="utf-8")) if f.exists() else []
            out["papers"].append(item)
    mock = root / "模拟题" / "系统架构设计师"
    if mock.is_dir():
        for batch in sorted(p for p in mock.iterdir() if p.is_dir()):
            year, half = year_half_of(batch.name)
            for d in sorted((p for p in batch.iterdir() if p.is_dir()), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
                def pair(kind):
                    q, a = d / f"{kind}_题目.md", d / f"{kind}_答案.md"
                    return (q.read_text(encoding="utf-8") if q.exists() else "", a.read_text(encoding="utf-8") if a.exists() else None)
                qt, at = pair("综合知识")
                ct, ca = pair("案例分析")
                et, ea = pair("论文")
                out["mocks"].append({"year": year, "half": half, "label": f"{batch.name} {d.name}",
                                     "dir": str(d.relative_to(root)),
                                     "choice": parse_choice(qt, at) if qt else [],
                                     "cases": parse_cases(ct, ca) if ct else [],
                                     "essays": parse_essays(et, ea) if et else []})
    return out


def available():
    return (gh_dir() / "_source.json").exists() or os.path.isdir(gh_dir() / "真题")
