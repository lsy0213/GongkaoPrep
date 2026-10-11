"""软考真题（2009–2018 年这种“试卷 + 答案详解”的文字版 PDF）解析。

综合知识：题干和选项取自试卷（每道题以“●”开头，一个题干可以有好几个空，如“（1）……（2）”，每个空是一道题、1 分），
答案和解析取自答案详解（重排了一遍题目，每题后面是【答案】【解析】），按空号和题干文字对齐。
一个题干有几个空时，题干作为共用材料，每个空单独一题，题干显示含这个空的那句话。
案例分析：说明和问题取自案例试卷，参考答案取自答案详解里每个【问题N】题目原文之后的文字。
论文：论题、背景和三点要求取自论文试卷，写作要点取自答案详解。
"""

import re

from .pdflines import Normed, crop_segments, join_lines, read_lines, tidy

BLANK_OPT_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[)）]\s*(?=A\s*[.．、])")
LETTER_RE = {L: re.compile(rf"(?<![A-Za-z]){L}\s*[.．、]") for L in "ABCD"}
FIG_RE = re.compile(r"如下图|下图|如图|图中|下表|如表|表中|示意图|所示的")
CN_NUM = "一二三四五六七八九十"


# ---------------------------------------------------------------- 综合知识（试卷）

def _split_options(seg):
    """一个空的选项文字 → [A, B, C, D]（按 A→B→C→D 的顺序找字母，免得选项里的“C.”被当成分隔）。"""
    pos, out = 0, []
    starts = []
    for L in "ABCD":
        m = LETTER_RE[L].search(seg, pos)
        if not m:
            return None
        starts.append((m.start(), m.end()))
        pos = m.end()
    for i, (_s, e) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < 4 else len(seg)
        t = tidy(seg[e:end].replace("\n", " "))
        t = re.sub(rf"^{'ABCD'[i]}\s*[.．、]\s*", "", t)  # “C.C. 1, 0”：文字层把选项字母印了两遍
        out.append(t)
    return out


def _clause(stem, n):
    """多空题干里含第 n 空的那句话（作为这一空的题干）。"""
    m = re.search(rf"[（(]\s*{n}\s*[)）]", stem)
    if not m:
        return f"上面题干中第（{n}）空应选："
    a = max(stem.rfind(ch, 0, m.start()) for ch in "。；;\n")
    b_candidates = [stem.find(ch, m.end()) for ch in "。；;\n"]
    b = min([x for x in b_candidates if x >= 0], default=len(stem))
    return tidy(stem[a + 1: b + 1]).strip("；;\n ") or f"上面题干中第（{n}）空应选："


def parse_paper(path):
    """综合知识试卷 → [{blanks, stem, options{n: [A..D]}, lines, fig}]（不含答案）。"""
    lines = read_lines(path)
    groups, cur = [], None
    for ln in lines:
        t = ln.text
        if t.startswith("●"):
            cur = {"lines": [ln], "texts": [t.lstrip("●").strip()]}
            groups.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
            cur["texts"].append(t)
    out = []
    for g in groups:
        text = "\n".join(g["texts"])
        ms = list(BLANK_OPT_RE.finditer(text))
        if not ms:
            continue
        blanks = [int(m.group(1)) for m in ms]
        if not all(1 <= b <= 75 for b in blanks):
            continue  # 卷首的填涂例题（88）（89）
        stem = join_lines(text[:ms[0].start()].splitlines())
        opts = {}
        for i, m in enumerate(ms):
            seg = text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)]
            opts[blanks[i]] = _split_options(seg)
        # 选项是公式、图片（文字层里只有“A.”）的，要看原卷
        blank_opts = any(not o or any(not x for x in o) for o in opts.values())
        out.append({"blanks": blanks, "stem": tidy(stem), "options": opts, "lines": g["lines"],
                    "fig": bool(FIG_RE.search(stem)) or blank_opts})
    return out


# ---------------------------------------------------------------- 综合知识（答案详解）

ANS_RE = re.compile(r"【\s*答\s*案\s*】")
JX_RE = re.compile(r"【\s*解\s*析\s*】")
PM_RE = re.compile(r"(?m)^\s*试题\s*[一1]\s*[(（]?\s*(?:共\s*\d+\s*分)?")


def _answers_text(path):
    lines = read_lines(path)
    return "\n".join(ln.text for ln in lines)


def attach_answers(groups, ans_path):
    """答案详解里每个【答案】块属于哪些空：看它前面最近的选项标记“(n)A.”。解析到下一题的题干为止。
    返回 (groups, 下午部分开始的位置, 答案详解全文)。"""
    text = _answers_text(ans_path)
    nt = Normed(text)
    by_blank = {b: g for g in groups for b in g["blanks"]}
    order = {id(g): i for i, g in enumerate(groups)}
    blocks = list(ANS_RE.finditer(text))
    prev = 0
    last_end = 0
    for k, m in enumerate(blocks):
        seg = text[prev: m.start()]
        found = [int(x.group(1)) for x in BLANK_OPT_RE.finditer(seg)]
        found = [b for b in found if b in by_blank]
        if not found:
            prev = m.end()
            continue
        g = by_blank[found[-1]]
        jx = JX_RE.search(text, m.end())
        nxt = blocks[k + 1].start() if k + 1 < len(blocks) else len(text)
        if not jx or jx.start() > nxt:
            ans_part, exp_start = text[m.end(): nxt], None
        else:
            ans_part, exp_start = text[m.end(): jx.start()], jx.end()
        letters = _letters(ans_part, g["blanks"])
        g["answers"] = letters
        # 解析到哪里结束：下一道题的题干（按试卷原文在答案详解里找）；找不到就到下一个【答案】前面的选项开头
        if exp_start is not None:
            i = order[id(g)]
            end = -1
            if i + 1 < len(groups):
                head = groups[i + 1]["stem"][:24]
                end = nt.find(head, exp_start) if head else -1
            if end < 0 or end > nxt:
                mm = list(BLANK_OPT_RE.finditer(text, exp_start, nxt))
                end = mm[0].start() if mm else nxt
                # 往回退到这道题的题干开头：选项前面最后一个句末之后
                if mm and i + 1 < len(groups):
                    back = nt.find(groups[i + 1]["stem"][:8], exp_start)
                    if 0 <= back < end:
                        end = back
            if i + 1 == len(groups):
                pm = PM_RE.search(text, exp_start)
                end = pm.start() if pm else nxt
            g["explain"] = _clean_explain(text[exp_start:end])
            last_end = max(last_end, end)
        prev = m.end()
    pm = PM_RE.search(text, last_end) if last_end else None
    return groups, (pm.start() if pm else len(text)), text


def _letters(part, blanks):
    """【答案】后面的字母：“B D”“(1)B (2)D”“（30）C”……按空的顺序。"""
    pairs = re.findall(r"[（(]\s*(\d{1,2})\s*[)）]\s*([A-D])", part)
    if pairs and len(pairs) >= len(blanks):
        d = {int(n): L for n, L in pairs}
        if all(b in d for b in blanks):
            return {b: "ABCD".index(d[b]) for b in blanks}
    letters = re.findall(r"(?<![A-Za-z])([A-D])(?![A-Za-z])", part)
    if len(letters) >= len(blanks):
        return {b: "ABCD".index(letters[i]) for i, b in enumerate(blanks)}
    return {}


def _clean_explain(t):
    t = join_lines([x for x in t.splitlines() if x.strip()])
    return tidy(t)


# ---------------------------------------------------------------- 整理成题库记录

def to_bank(groups, src_id, fid, year, half, title):
    """→ (questions, materials)。题目 id：rk-<年><上/下>-<空号>。"""
    hcode = "a" if half == "上半年" else "b"
    qs, mats = [], []
    for g in groups:
        multi = len(g["blanks"]) > 1
        mid = f"rk-{year}{hcode}-m{g['blanks'][0]}" if multi else None
        crop = crop_segments(g["lines"])
        if multi:
            mats.append({"id": mid, "source": src_id, "title": f"第 {g['blanks'][0]}–{g['blanks'][-1]} 题共用题干",
                         "text": g["stem"], "crop": crop, "fig": 1 if g["fig"] else 0, "fid": fid})
        for b in g["blanks"]:
            opts = g["options"].get(b)
            ans = (g.get("answers") or {}).get(b)
            qs.append({
                "id": f"rk-{year}{hcode}-{b:02d}", "source": src_id, "num": b,
                "module": "", "sub": "",
                "stem": _clause(g["stem"], b) if multi else g["stem"],
                "options": opts, "answer": ans, "explain": g.get("explain", ""),
                "material": mid, "crop": [] if multi else crop, "fig": 1 if (g["fig"] and not multi) else 0,
                "year": year, "src": "真题", "origin": title, "fid": fid,
            })
    return qs, mats


# ---------------------------------------------------------------- 案例分析

CASE_HEAD_RE = re.compile(r"^\s*试题\s*([一二三四五六七八九十])\s*(?:[(（]\s*共?\s*(\d+)\s*分\s*[)）])?\s*$")
Q_HEAD_RE = re.compile(r"【\s*问题\s*(\d)\s*】\s*(?:[(（]\s*(\d+)\s*分\s*[)）])?")


def parse_case_paper(path):
    """案例分析试卷 → [{no, score, material, questions:[{n, score, text}], pages}]。"""
    lines = read_lines(path)
    sets, cur = [], None
    for ln in lines:
        m = CASE_HEAD_RE.match(ln.text)
        if m:
            cur = {"no": CN_NUM.index(m.group(1)) + 1, "score": int(m.group(2) or 0), "lines": [], "pages": set()}
            sets.append(cur)
            cur["pages"].add(ln.page)
            continue
        if cur is not None:
            cur["lines"].append(ln.text)
            cur["pages"].add(ln.page)
    out = []
    for s in sets:
        text = "\n".join(s["lines"])
        qm = list(Q_HEAD_RE.finditer(text))
        if not qm:
            continue
        material = join_lines(text[:qm[0].start()].splitlines())
        material = re.sub(r"^.*?(?=【\s*说明\s*】)", "", material, flags=re.S) or material
        questions = []
        for i, m in enumerate(qm):
            body = text[m.end(): qm[i + 1].start() if i + 1 < len(qm) else len(text)]
            questions.append({"n": int(m.group(1)), "score": int(m.group(2) or 0), "text": tidy(join_lines(body.splitlines()))})
        if not s["score"]:
            s["score"] = sum(q["score"] for q in questions)
        out.append({"no": s["no"], "score": s["score"], "material": tidy(material), "questions": questions,
                    "pages": sorted(s["pages"])})
    return out


def attach_case_answers(cases, ans_text, start):
    """答案详解的下午部分：每个【问题N】后面先是题目原文，再是参考答案。按题目原文的结尾切开。"""
    nt = Normed(ans_text)
    pos = start
    for c in cases:
        head = re.compile(rf"(?m)^\s*试题\s*{CN_NUM[c['no'] - 1]}")
        hm = head.search(ans_text, pos)
        if not hm:
            continue
        nxt_head = re.compile(rf"(?m)^\s*试题\s*{CN_NUM[c['no']] if c['no'] < 10 else '十一'}")
        nm = nxt_head.search(ans_text, hm.end())
        end_set = nm.start() if nm else len(ans_text)
        sec = ans_text[hm.end():end_set]
        am = re.search(r"(?m)^\s*(?:参考)?答案\s*[:：]", sec)
        if am:
            # 另一种排法（2018 年起）：先列全部问题，再“答案：”逐题给答案，最后“解析：”
            region = sec[am.end():]
            jm = re.search(r"(?m)^\s*(?:试题)?解析\s*[:：]", region)
            if jm:
                c["analysis"] = tidy(join_lines(region[jm.end():].splitlines()))
                region = region[:jm.start()]
            parts = list(Q_HEAD_RE.finditer(region))
            for i, m in enumerate(parts):
                body = region[m.end(): parts[i + 1].start() if i + 1 < len(parts) else len(region)]
                q = next((x for x in c["questions"] if x["n"] == int(m.group(1))), None)
                if q is not None:
                    q["answer"] = tidy(join_lines(body.splitlines()))
            pos = end_set
            continue
        qpos = list(Q_HEAD_RE.finditer(ans_text, hm.end(), end_set))
        for q in c["questions"]:
            qm = next((x for x in qpos if int(x.group(1)) == q["n"]), None)
            if not qm:
                continue
            k = qpos.index(qm)
            q_end = qpos[k + 1].start() if k + 1 < len(qpos) else end_set
            # 题目原文的最后十几个字在哪里结束，后面就是答案（文字层两份稍有出入，依次试短一些的结尾）
            flat = re.sub(r"\s+", "", q["text"])
            a = -1
            for n in (14, 10, 7):
                tail = flat[-n:]
                a = nt.find_end(tail, qm.end()) if tail else -1
                if 0 <= a <= q_end:
                    break
            if a < 0 or a > q_end:
                a = qm.end()
            ans = tidy(join_lines(ans_text[a:q_end].splitlines()))
            q["answer"] = re.sub(r"^[。．.，,；;:：)）\s]+", "", ans)
        pos = end_set
    return cases


# ---------------------------------------------------------------- 论文

ESSAY_HEAD_RE = re.compile(r"^\s*试题\s*([一二三四五六七八九十])\s*[、.．:：]?\s*(论.*)?$")
TOPIC_RE = re.compile(r"请(?:围绕|以|结合)\s*[“\"「]([^”\"」]{2,40})[”\"」]\s*(?:论.|为题|为主题)[^。：:\n]{0,30}?论述\s*[。：:.]?")


def parse_essay_paper(path, lines=None):
    """论文试卷 → [{no, title, background, requirements}]。lines 给了就不再读文件（模拟卷只传题目部分）。"""
    lines = read_lines(path) if lines is None else lines
    sets, cur = [], None
    for ln in lines:
        m = ESSAY_HEAD_RE.match(ln.text)
        if m:
            cur = {"no": CN_NUM.index(m.group(1)) + 1, "title": (m.group(2) or "").strip(), "lines": []}
            sets.append(cur)
            continue
        if cur is not None:
            if not cur["title"] and ln.text.startswith("论"):
                cur["title"] = ln.text.strip()
                continue
            cur["lines"].append(ln.text)
    out = []
    for s in sets:
        text = join_lines(s["lines"])
        m = TOPIC_RE.search(text)
        if m:
            background, req = tidy(text[:m.start()]), text[m.end():]
            topic = m.group(1).strip()
            title = s["title"] or (topic if topic.startswith("论") else "论" + topic)
        else:
            k = re.search(r"(?m)^\s*1\s*[.．、]", text)
            background, req = tidy(text[:k.start()] if k else text), text[k.start():] if k else ""
            title = s["title"]
        reqs = [tidy(x) for x in re.split(r"(?m)^\s*(?:[1-4][.．、]|[（(][1-4][)）])\s*", req) if x.strip()]
        out.append({"no": s["no"], "title": tidy(title).rstrip("。."), "background": background, "requirements": reqs})
    return [e for e in out if e["title"]]


def attach_essay_guides(essays, ans_text, start):
    """答案详解里每道论文题后面的写作要点。"""
    nt = Normed(ans_text)

    def anchor(e, frm):
        p = nt.find(e["title"].lstrip("论"), frm)
        return p if p >= 0 else nt.find(e["background"][:20], frm)

    for i, e in enumerate(essays):
        p = anchor(e, start)
        if p < 0:
            continue
        last_req = e["requirements"][-1] if e["requirements"] else e["background"][-20:]
        a = nt.find_end(re.sub(r"\s+", "", last_req)[-14:], p)
        nxt = anchor(essays[i + 1], p + 5) if i + 1 < len(essays) else -1
        end = nxt if nxt > 0 else len(ans_text)
        if a < 0 or a > end:
            continue
        guide = tidy(join_lines(ans_text[a:end].splitlines()))
        guide = re.sub(r"(?m)^\s*试题\s*[一二三四五六七八九十]\s*$", "", guide).strip()
        e["guide"] = re.sub(r"^[。．.，,；;:：)）\s]+", "", guide)
    return essays
