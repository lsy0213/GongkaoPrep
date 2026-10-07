"""《决战行测5000题》→ 题目。

一套五个模块，每个模块分上下两册：
- 上册是文字版 PDF：讲解 + “决战真题”练习题（按 章 / 节 / 考点 / (一)夯实基础 (二)高难进阶 分组，每组题号从 1 开始），
  书末“答案速览”（两栏排版）按同样的分组列出每题答案（“1—5CBDBC 6—10…”）；
- 下册是扫描版的详细解析（“N.【答案】X。【解析】…”），要 OCR，结果按页缓存在 library/ocr/。

做法：上册按行扫描，记下标题层级和每道题（题干、选项、在原页上的位置）；题号回到 1 就是新的一组。
答案速览、下册解析也切成组，三者按“节名 + 题数 + 答案是否一致”做序列对齐。
资料分析的“(一)(2020 江苏 116~120)根据下列资料…”到第一道题之间是共用材料。
数量、资料里的分数是数学字体叠排的，文字层拼不对，这类题（以及带图的题）默认显示原书截图。
"""

import os
import re

from .pdftext import AD_RE, Doc, fix_chars, join_text, mark_header_footer, page_lines
from .books import _split_options
from .realexam import _find_options

VERSION = 1
CN = "一二三四五六七八九十"
SERIES = "5000题"
# 卷 → 模块（常识卷里政治理论、常识判断两篇分开）
MODULE_OF = {"数量": "数量关系", "言语": "言语理解与表达", "判断": "判断推理", "资料": "资料分析", "常识": "常识判断"}
VOLS = ["常识", "数量", "言语", "判断", "资料"]

PART_RE = re.compile(rf"^第[{CN}]+篇\s*[|｜]?\s*(\S*)$")
CHAP_RE = re.compile(rf"^第[{CN}]+章\s*[|｜]?\s*([^\d…·\s]*)")
SECT_RE = re.compile(rf"^第[{CN}]+节\s*[：:]?\s*([^\d…·\s]*)")
POINT_RE = re.compile(r"^考点\s*\d+\s*(.*)$")
SUBT_RE = re.compile(rf"^[{CN}]{{1,2}}、\s*(\S.*)$")
GROUP_RE = re.compile(
    rf"^[(（]\s*([{CN}]{{1,2}})\s*[)）]\s*(夯实基础|高难进阶|提升进阶|基础练习)?\s*$|^(夯实基础|高难进阶|提升进阶)$|"
    rf"^(卷[{CN}]+)$|^(综合训练\s*\d+)$|^(综合练习\s*[{CN}\d]+)$|^(作业题\s*\d+)$|^(专项集训)$|^(模块练习)$"
)
QNUM_RE = re.compile(r"^(\d{1,4})\s*[.．]\s*(.*)$")
SRC_RE = re.compile(r"^[(（]\s*((?:19|20)\d\d)\s*([^)）]{0,30})[)）]\s*")
MAT_RE = re.compile(r"根据(下列|以下|下面|所给|如下)?.{0,10}(资料|材料|图表|图|表|文字).{0,8}(完成|回答|作答)")
NOISE_RE = re.compile(
    r"^(☆?本部分题目解析见下册.*|决战行测\s*5000\s*题.*|[「」『』【】(（]?\s*(知识梳理|考点介绍|决战真题|考情分析|粉笔提示|解题思维|会解题思维)"
    r"\s*[「」』】)）]?|[ⅠⅡⅢⅣⅤ]+|图|续表)$"
)
TEACH_RE = re.compile(r"^[「『【]?\s*(知识梳理|考点介绍|考情分析|粉笔提示|解题思维|会解题思维)")
HEADLIKE = re.compile(r"[，。？！；]")


def _clean(t):
    if any("\ud800" <= c <= "\udfff" for c in t):
        # 数学粗体字母数字（𝟏𝟐）被拆成了代理对：拼回去再规范化成普通字符
        t = t.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
        t = fix_chars("".join(c for c in t if not "\ud800" <= c <= "\udfff"))
    return re.sub(r"\s+", " ", t).strip()


def _norm(t):
    return re.sub(r"[\s、，·.…|｜:：]", "", t or "")


# ---------------------------------------------------------------- 标题层级（正文、答案速览、下册共用）

class Labeler:
    def __init__(self):
        self.lab = {"part": "", "chap": "", "sect": "", "point": "", "subt": "", "grp": ""}
        self.pending = None  # 章、节名单独占一行

    def feed(self, t, pos=None):
        """是标题行就更新层级并返回 True。pos=(页, y0, y1)：单独一行的章名、节名必须紧挨在“第×章”下面。"""
        lab = self.lab
        if self.pending:
            (key, ppos), self.pending = self.pending, None
            near = pos is None or ppos is None or (pos[0] == ppos[0] and pos[1] - ppos[2] < 60)
            if near and re.fullmatch(r"[一-鿿、与和]{2,12}", t):
                lab[key] = t
                return True
        m = PART_RE.match(t)
        if m and len(m.group(1)) >= 2:
            if m.group(1) != lab["part"]:
                lab.update(part=m.group(1))
            return True
        m = CHAP_RE.match(t)
        if m and len(t) <= 24 and not HEADLIKE.search(t):
            name = m.group(1)
            if not name:
                self.pending = ("chap", pos)
            elif name != lab["chap"]:
                lab.update(chap=name, sect="", point="", subt="", grp="")
            return True
        m = SECT_RE.match(t)
        if m and len(t) <= 30 and not HEADLIKE.search(t):
            lab.update(sect=m.group(1), point="", subt="", grp="")
            if not m.group(1):
                self.pending = ("sect", pos)
            return True
        m = POINT_RE.match(t)
        if m and len(t) <= 30:
            lab.update(point=m.group(1), subt="", grp="")
            return True
        m = GROUP_RE.match(t)
        if m:
            lab["grp"] = next(g for g in m.groups() if g)
            return True
        m = SUBT_RE.match(t)
        if m and len(t) <= 24 and not HEADLIKE.search(t):
            lab.update(subt=m.group(1), grp="")
            return True
        return False


# ---------------------------------------------------------------- 上册：题目

def load_doc(path):
    """同 pdftext.load_pdf，但打开竖排分数还原。"""
    import pymupdf

    d = pymupdf.open(path)
    doc = Doc(path)
    for i, page in enumerate(d):
        doc.sizes.append((page.rect.width, page.rect.height))
        doc.pages.append(page_lines(page, i, math=True))
    mark_header_footer(doc)
    d.close()
    return doc


def parse_body(path):
    """返回 (doc, groups, key_pages)。

    groups: [{"label": {...}, "qs": [{"num", "lines", "boxes", "end", "mat", "label"}], "mats": [...]}]
    boxes 是每行在原页上的位置 (页, x0, y0, x1, y1)；end 是题目之后第一行的位置 (页, y)，截图截到那里。
    """
    doc = load_doc(path)
    # 正文左边界（每页的最小缩进取中位数；表格多的页单页算不准）
    pm = sorted(min((l.x0 for l in p if not l.tag and len(l.text) > 15), default=1e9) for p in doc.pages)
    pm = [x for x in pm if x < 1e9]
    doc_margin = pm[len(pm) // 2] if pm else 0
    L = Labeler()
    groups = []
    cur = None          # 正在收集行的题或材料
    cur_mat = None      # 当前题目所属的材料
    pending_mats = []   # 材料出现在它的第一题之前，等题号决定它归哪一组
    teaching = False
    key_pages = []
    in_key = False
    last_num = 0
    all_mats = []

    def close(pi, y):
        nonlocal cur
        if cur is not None:
            cur["end"] = (pi, y)
        cur = None

    for pi, lines in enumerate(doc.pages):
        for ln in lines:
            if ln.tag in ("header", "footer", "ad"):
                continue
            t = re.sub(r"^图\s*(?=[(（「【第])", "", _clean(ln.text))  # 插图的替代字“图”粘在标题前
            if not t:
                continue
            if in_key:
                if pi not in key_pages:
                    key_pages.append(pi)
                continue
            if t == "答案速览" and pi > len(doc.pages) // 2:
                close(pi, ln.y0)
                in_key = True
                key_pages.append(pi)
                continue
            if re.match(r"^决战行测\s*5000\s*题", t) or re.fullmatch(r"\d{1,3}|[ⅠⅡⅢⅣⅤ]+", t):
                continue  # 页眉页码（没被识别成页眉的）
            if re.match(r"^.?本部分题目解析见下册", t):
                continue  # 页脚注：题目常跨过它接到下一页，不能在这里断开
            if NOISE_RE.match(t):
                close(pi, ln.y0)
                if TEACH_RE.match(t):
                    teaching = True
                elif "决战真题" in t:
                    teaching = False
                continue
            before = dict(L.lab)
            if L.feed(t, (pi, ln.y0, ln.y1)):
                if L.lab != before:
                    close(pi, ln.y0)
                    if L.lab["grp"] != before["grp"] and L.lab["grp"]:
                        teaching = False
                    elif L.lab["point"] != before["point"] or L.lab["sect"] != before["sect"]:
                        teaching = True
                    if L.lab["sect"] != before["sect"] or L.lab["chap"] != before["chap"]:
                        cur_mat = None
                continue
            m = QNUM_RE.match(t)
            if m and not teaching:
                ns, rest = m.group(1), m.group(2)
                rest = re.sub(r"^[一-鿿]{1,3}\s*(?=[(（]\s*(19|20)\d\d)", "", rest)  # “1.答案(2022 山西50)”：混进来的批注字
                has_src = bool(SRC_RE.match(rest))
                expect = last_num + 1
                digit = bool(re.match(r"^\d", rest))
                # “1.5%；文化装备…”是材料折行，不是题：题号行有首行缩进，折行顶格
                margin = min([l.x0 for l in lines if not l.tag and len(l.text) > 15] + [doc_margin + 10])
                if digit and ln.x0 < margin + 12 and not has_src:
                    m = None
            if m and not teaching:
                num = None
                if int(ns) == expect and (not digit or pending_mats or cur_mat):
                    num = expect
                elif int(ns) == 1 and (has_src or pending_mats or (digit and cur_mat)):
                    num = 1
                elif has_src and ns.endswith(str(expect)):
                    num = expect  # 分数的分子分母粘到了题号前面
                elif last_num and expect < int(ns) <= expect + 2 and (has_src or not digit):
                    num = int(ns)  # 漏认了一两道（版式特殊），不要让后面整组都断掉
                if num is not None:
                    close(pi, ln.y0)
                    if num == 1 or not groups:
                        groups.append({"label": dict(L.lab), "qs": [], "mats": []})
                    if pending_mats:
                        groups[-1]["mats"] += pending_mats
                        cur_mat = pending_mats[-1]
                        pending_mats = []
                    cur = {"num": num, "lines": [rest] if rest else [], "boxes": [(pi, ln.x0, ln.y0, ln.x1, ln.y1)],
                           "mat": cur_mat["id"] if cur_mat else None, "label": dict(L.lab)}
                    groups[-1]["qs"].append(cur)
                    last_num = num
                    continue
            if MAT_RE.search(t) and len(t) < 90:
                close(pi, ln.y0)
                cur = {"id": len(all_mats), "lines": [t], "boxes": [(pi, ln.x0, ln.y0, ln.x1, ln.y1)]}
                all_mats.append(cur)
                pending_mats.append(cur)
                continue
            if cur is not None:
                cur["lines"].append(t)
                cur["boxes"].append((pi, ln.x0, ln.y0, ln.x1, ln.y1))
    close(len(doc.pages) - 1, 1e9)
    for g in groups:
        for q in g["qs"]:
            q.setdefault("end", (q["boxes"][-1][0], 1e9))
        for m in g["mats"]:
            m.setdefault("end", (m["boxes"][-1][0], 1e9))
    return doc, [g for g in groups if g["qs"]], key_pages


# ---------------------------------------------------------------- 上册：答案速览

def key_text(path, pages):
    """答案速览是两栏排版：按居中标题把页面切成几段，每段先左栏后右栏。"""
    import pymupdf

    d = pymupdf.open(path)
    out = []
    for pno in pages:
        page = d[pno]
        mid = page.rect.width / 2
        rows = {}
        for w in page.get_text("words"):
            x0, y0, x1, y1, word = w[:5]
            side = 0 if (x0 < mid - 20 and x1 > mid + 20) else (1 if (x0 + x1) / 2 < mid else 2)
            rows.setdefault((side, round((y0 + y1) / 2 / 6)), []).append((x0, y0, word))
        lines = []
        for (side, _), ws in rows.items():
            ws.sort()
            lines.append((side, min(w[1] for w in ws), _clean("".join(w[2] for w in ws)), min(w[0] for w in ws)))
        heads = sorted(y for s, y, _, _ in lines if s == 0)
        bands = [-1] + heads + [1e9]

        def band(y):
            return max(i for i, b in enumerate(bands) if b <= y + 0.5)

        by_band = {}
        for ln in lines:
            by_band.setdefault(band(ln[1]), []).append(ln)
        for b in sorted(by_band):
            ls = by_band[b]
            heads_b = sorted((l for l in ls if l[0] == 0), key=lambda l: l[1])
            body = [l for l in ls if l[0] != 0]
            # 有的段是两栏，有的段通栏（一行 1—5 … 16—20，折行的字母另起一行）：两种读法都试，选区间和字母数对得上的
            cols = sorted(body, key=lambda l: (l[0], l[1]))
            rowwise = sorted(body, key=lambda l: (round(l[1] / 12), l[3]))
            best = max((cols, rowwise), key=lambda o: _range_fit([l[2] for l in o]))
            out += [l[2] for l in heads_b + best if l[2].strip()]
    d.close()
    return out


def _range_fit(lines):
    """答案速览一段文字里，“a—b”后面跟着的字母数正好是 b-a+1 的区间个数。"""
    score = 0
    cur = None
    for t in lines:
        if re.search(r"[一-鿿]", t):
            continue
        for m in KEY_TOKEN_RE.finditer(t):
            if m.group(3):
                if cur:
                    cur[1] += 1
            else:
                if cur:
                    score += 1 if cur[1] == cur[0] else -1
                a, b = int(m.group(1)), int(m.group(2) or m.group(1))
                cur = [b - a + 1, 0]
    if cur:
        score += 1 if cur[1] == cur[0] else -1
    return score


KEY_TOKEN_RE = re.compile(r"(\d{1,3})\s*(?:[-—–－~～]+\s*(\d{1,3}))?|([A-H])")


def parse_key(lines):
    """答案速览 → [{"label": {...}, "ans": {题号: 0-3 或 None}, "n": 题数}]。题号区间重新从 1 开始就是新的一组。"""
    L = Labeler()
    groups = []
    pos = None
    for t in lines:
        if re.search(r"[一-鿿]", t):
            L.feed(t)
            continue
        for m in KEY_TOKEN_RE.finditer(t):
            if m.group(3):
                if pos is None or not groups:
                    continue
                groups[-1]["ans"][pos] = "ABCD".find(m.group(3)) if m.group(3) in "ABCD" else None
                pos += 1
            else:
                a = int(m.group(1))
                if a == 1:
                    groups.append({"label": dict(L.lab), "ans": {}})
                pos = a
    for g in groups:
        g["n"] = max(g["ans"]) if g["ans"] else 0
    return [g for g in groups if g["n"]]


# ---------------------------------------------------------------- 下册：解析（OCR）

EXP_START_RE = re.compile(r"^(\d{1,3})\s*[.．,，、]\s*【\s*答\s*案\s*】\s*([A-D])?")
EXP_DROP_RE = re.compile(r"^(决战行测.*|第[一二三四五六七八九十]+[篇章节].{0,16}|[(（][一二三四五六七八九十][)）].{0,8}|"
                         r"考点\s*\d+.{0,16}|[一二三四五六七八九十]、.{0,14}|\d{1,3}|[ⅠⅡⅢⅣⅤIV]+|[?？·.]+)$")


def explain_lines(fid, path):
    """下册每页 OCR 后的行（按页缓存）。没有缓存又不能 OCR 时返回 None。"""
    import pymupdf

    from . import docs

    d = pymupdf.open(path)
    out = []
    for pno in range(d.page_count):
        boxes = docs._ocr_boxes(fid, pno, d[pno])
        if boxes is None:
            d.close()
            return None
        out += [(pno, ln) for ln in docs._boxes_to_lines(boxes, pno)]
    d.close()
    return out


def parse_explains(lines):
    """→ [{"label", "items": {题号: {"ans": 0-3, "text": 解析}}, "n"}]"""
    L = Labeler()
    groups = []
    cur = None
    last = 0
    for pno, ln in lines:
        t = _clean(ln.text)
        if not t:
            continue
        m = EXP_START_RE.match(t)
        if m:
            num = int(m.group(1))
            if num == 1 or not groups or num <= last:
                groups.append({"label": dict(L.lab), "items": {}})
            ans = "ABCD".find(m.group(2)) if m.group(2) else None
            cur = {"ans": ans, "lines": [t[m.end():]]}
            groups[-1]["items"][num] = cur
            last = num
            continue
        if len(t) < 20 and EXP_DROP_RE.match(t):
            if L.feed(t):
                cur = None  # 新的节、组：上一题的解析到此为止
            continue
        if cur is not None:
            cur["lines"].append(t)
    for g in groups:
        g["n"] = max(g["items"]) if g["items"] else 0
        for it in g["items"].values():
            it["text"] = tidy_explain(it.pop("lines"))
    return groups


FINAL_RE = re.compile(r"(?:故|因此|所以)?\s*(?:正确)?答案(?:为|是|选)\s*([A-D])\s*(?:项)?[。.]?\s*$|本题选\s*([A-D])")


def final_answer(text):
    """解析末尾的“故正确答案为 B。”（拓展内容之前）。"""
    body = text.split("【拓展】")[0].strip()
    ms = list(re.finditer(r"故(?:正确)?答案为\s*([A-D])", body)) or list(FINAL_RE.finditer(body[-40:]))
    if not ms:
        return None
    g = ms[-1].group(1) or ms[-1].group(2)
    return "ABCD".find(g)


def tidy_explain(lines):
    text = join_text([l for l in lines if l and not AD_RE.search(l)])
    text = re.sub(r"^[。.，,\s]*", "", text)
    text = re.sub(r"粉笔大数据[:：]?\s*本题正确率为\s*([\d.]+%)\s*[，,]?\s*易错项为\s*([A-D])[。.]?",
                  r"（正确率 \1，易错项 \2）\n", text)
    text = re.sub(r"【\s*解\s*析\s*】", "", text)
    text = re.sub(r"\n?(粉笔拓展|粉笔提醒|拓展)\s*\n?", "\n【拓展】", text)
    return text.strip()


# ---------------------------------------------------------------- 对齐

def _sim(a_label, a_n, b_label, b_n, a_ans=None, b_ans=None):
    s = 0.0
    if a_n == b_n:
        s += 3
    elif abs(a_n - b_n) <= max(2, a_n // 5):
        s += 1
    else:
        s -= 2
    if a_label.get("sect") and _norm(a_label.get("sect")) == _norm(b_label.get("sect")):
        s += 1.5
    if a_label.get("chap") and _norm(a_label.get("chap")) == _norm(b_label.get("chap")):
        s += 0.5
    if a_ans and b_ans:
        common = [k for k in a_ans if k in b_ans and a_ans[k] is not None and b_ans[k] is not None]
        if common:
            agree = sum(a_ans[k] == b_ans[k] for k in common) / len(common)
            s += 6 * agree - 2
    return s


def align(A, B, score):
    """序列对齐：返回 {A 的下标: B 的下标}。跳过一组扣 1 分。"""
    n, m = len(A), len(B)
    S = [[score(a, b) for b in B] for a in A]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0], bt[i][0] = -i, 1
    for j in range(1, m + 1):
        dp[0][j], bt[0][j] = -j, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j], bt[i][j] = max((dp[i - 1][j - 1] + S[i - 1][j - 1], 0), (dp[i - 1][j] - 1, 1), (dp[i][j - 1] - 1, 2))
    out = {}
    i, j = n, m
    while i > 0 and j > 0:
        if bt[i][j] == 0:
            if S[i - 1][j - 1] > 0:
                out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif bt[i][j] == 1:
            i -= 1
        else:
            j -= 1
    return out


def _content_scores(groups, exps):
    """组内容（题干、选项、材料）和解析组文字的重合度 → 对齐加分。两边文字都够多才算（图形题组不算）。"""
    from .docq import _sig

    gs = [_sig(" ".join(" ".join(q["lines"]) for q in g["qs"]) + " ".join(" ".join(m["lines"]) for m in g["mats"])) for g in groups]
    es = [_sig(" ".join(it["text"] for it in e["items"].values())) for e in exps]
    df = {}
    for x in gs:
        for t in x:
            df[t] = df.get(t, 0) + 1
    gen = {t for t, n in df.items() if n > max(2, len(gs) * 0.15)}
    gs = [x - gen for x in gs]
    es = [x - gen for x in es]
    out = {}
    for i, a in enumerate(gs):
        if len(a) < 30:
            continue
        for j, b in enumerate(es):
            if len(b) < 30:
                continue
            c = len(a & b) / min(len(a), len(b))
            out[(i, j)] = 12 * c - 2
    return out


# ---------------------------------------------------------------- 截图区域、是否带图

def _content_box(doc, pno):
    """页面正文区：页眉之下、页码之上。"""
    w, h = doc.sizes[pno]
    top, bot = h * 0.06, h * 0.93
    for ln in doc.pages[pno]:
        t = ln.text.strip()
        if (ln.tag == "header" or re.match(rf"^决战行测\s*5000|^第[{CN}]+章\S*$|^第[{CN}]+篇", t)) and ln.y1 < h * 0.12:
            top = max(top, ln.y1 + 3)
        if (ln.tag == "footer" or re.fullmatch(r"\d{1,3}", t)) and ln.y0 > h * 0.88:
            bot = min(bot, ln.y0 - 3)
    return top, bot


def crop_segments(doc, item, x_range):
    """题目（或材料）从第一行到下一项开始前的区域，跨页时每页一段。"""
    p0, y0 = item["boxes"][0][0], item["boxes"][0][2]
    pe, ye = item["end"]
    plast = max(b[0] for b in item["boxes"])
    if pe > plast + 1:  # 后面隔了整页讲解，只截到本题最后一行所在页
        pe, ye = plast, 1e9
    segs = []
    for p in range(p0, pe + 1):
        top, bot = _content_box(doc, p)
        a = y0 - 3 if p == p0 else top
        b = min(bot, ye - 2) if p == pe else bot
        if b - a > 6:
            segs.append([p, round(x_range[0] - 6, 1), round(a, 1), round(x_range[1] + 6, 1), round(b, 1)])
    return segs


class Visuals:
    """每页的图片、矢量图形、数学字体文字的位置，判断截图区域里有没有文字层表达不了的东西。"""

    def __init__(self, path):
        import pymupdf

        self.d = pymupdf.open(path)
        self.cache = {}

    def page(self, pno):
        if pno not in self.cache:
            pg = self.d[pno]
            rects = [tuple(i["bbox"]) for i in pg.get_image_info() if (i["bbox"][2] - i["bbox"][0]) > 25]
            for dr in pg.get_drawings():
                r = dr["rect"]
                if r.width > 3 or r.height > 3:
                    rects.append((r.x0, r.y0, r.x1, r.y1))
            maths = []
            for b in pg.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        if "Math" in s["font"] and s["text"].strip():
                            maths.append(tuple(s["bbox"]))
            self.cache[pno] = (rects, maths, pg.rect.width)
        return self.cache[pno]

    def has_visual(self, segs, lines=True):
        """lines=False：细线（下划线、破折号、分隔线）不算图，只认图片、色块和公式。"""
        for p, x0, y0, x1, y1 in segs:
            rects, maths, w = self.page(p)
            for r in rects + maths:
                cy = (r[1] + r[3]) / 2
                if not lines and min(r[2] - r[0], r[3] - r[1]) < 2.5:
                    continue
                if y0 < cy < y1 and r[0] < x1 and r[2] > x0 and not (r[2] - r[0] > w * 0.7 and r[3] - r[1] < 2):
                    return True
        return False

    def close(self):
        self.d.close()


# ---------------------------------------------------------------- 组装

def sub_of(vol, label):
    chap, sect = label.get("chap", ""), label.get("sect", "")
    if vol == "常识":
        if not chap.endswith("常识"):  # 常识判断篇各章都叫“××常识”，其余是政治理论篇
            return "政治理论", (chap if chap in ("马克思主义哲学", "理论与政策") else "政治综合")
        if chap.startswith("人文"):
            for k in ("文化", "文学", "历史"):
                if sect.startswith(k):
                    return "常识判断", k
            return "常识判断", "人文综合"
        return "常识判断", re.sub(r"常识$", "", chap) or "综合"
    return MODULE_OF[vol], chap or "综合"


def _parse_src(text):
    m = SRC_RE.match(text)
    if not m:
        return text, 0, ""
    return text[m.end():], int(m.group(1)), _clean(m.group(1) + " " + m.group(2))


def find_files(catalog_files):
    """在资料里找 5000题 的上册（必需）和下册（解析，可选）。"""
    out = {}
    for f in catalog_files:
        rel = f["rel"]
        if f["ext"] != "pdf" or "5000题" not in rel:
            continue
        name = os.path.basename(rel)
        for v in VOLS:
            if v in name:
                if "上册" in name and f.get("text"):
                    out.setdefault(v, {})["up"] = f
                elif "下册" in name:
                    out.setdefault(v, {})["down"] = f
    return {v: x for v, x in out.items() if "up" in x}


def build_volume(vol, up_path, up_fid, down_path=None, down_fid=None):
    """解析一卷，返回 (questions, materials, stats)。"""
    doc, groups, key_pages = parse_body(up_path)
    keys = parse_key(key_text(up_path, key_pages))
    exps = []
    if down_path:
        lines = explain_lines(down_fid, down_path)
        if lines:
            exps = parse_explains(lines)

    def gmax(g):
        return max(q["num"] for q in g["qs"])

    # 上册组 ↔ 答案速览组
    bk = align(groups, keys, lambda g, k: _sim(g["label"], gmax(g), k["label"], k["n"]))
    # 上册组 ↔ 下册解析组：除了节名、题数、答案（速览）一致，还看内容——解析里引用的题干、材料里的数字和名词。
    # 资料分析各组都是“N 篇 × 5 题”，只看题数和答案会整体错开一两组（解析挂到别的材料的题上）
    eg = {}
    if exps:
        content = _content_scores(groups, exps)
        eg = align(list(range(len(groups))), list(range(len(exps))), lambda gi, ej: _sim(
            groups[gi]["label"], gmax(groups[gi]), exps[ej]["label"], exps[ej]["n"],
            keys[bk[gi]]["ans"] if gi in bk else None, {n: it["ans"] for n, it in exps[ej]["items"].items()})
            + content.get((gi, ej), 0))

    xs0 = sorted(b[1] for g in groups for q in g["qs"] for b in q["boxes"])
    xs1 = sorted(b[3] for g in groups for q in g["qs"] for b in q["boxes"])
    x_range = (xs0[int(len(xs0) * 0.03)], xs1[int(len(xs1) * 0.97) - 1]) if xs0 else (60, 900)
    vis = Visuals(up_path)
    questions, materials = [], []
    stats = {"groups": len(groups), "key_groups": len(keys), "exp_groups": len(exps), "questions": 0, "answered": 0,
             "explained": 0, "matched_groups": len(bk), "mismatch": [], "disagree": 0}
    for gi, g in enumerate(groups):
        key = keys[bk[gi]] if gi in bk else None
        exp = exps[eg[gi]] if gi in eg else None
        nmax = gmax(g)
        ref = key["n"] if key else (exp["n"] if exp else None)
        if ref != nmax:
            stats["mismatch"].append((gi, "/".join(v for v in g["label"].values() if v), nmax, ref))
        if key is not None and exp is not None:
            # 这一组的答案速览和下册答案大多对不上，说明速览读串了（两栏/通栏混排），这组只信下册
            pairs = [(key["ans"].get(n), it["ans"]) for n, it in exp["items"].items()
                     if key["ans"].get(n) is not None and it["ans"] is not None]
            if len(pairs) >= 3 and sum(a == b for a, b in pairs) / len(pairs) < 0.6:
                key = None
                stats["key_dropped"] = stats.get("key_dropped", 0) + 1
        mat_ids = {}
        for mi, m in enumerate(g["mats"]):
            mid = f"m5k-{up_fid}-{gi:03d}-{mi}"
            mat_ids[m["id"]] = mid
            text = join_text(m["lines"][1:]) if len(m["lines"]) > 1 else ""
            materials.append({"id": mid, "title": _clean(m["lines"][0])[:60], "text": text,
                              "crop": crop_segments(doc, m, x_range), "fig": True, "fid": up_fid})
        for q in g["qs"]:
            n = q["num"]
            ans = key["ans"].get(n) if key else None
            it = exp["items"].get(n) if exp else None
            if it is not None:
                # 三方投票：答案速览、下册“【答案】X”、解析末尾“故正确答案为 X”。OCR 偶尔认错字母，速览偶有印刷错误
                votes = [v for v in (ans, it["ans"], final_answer(it["text"])) if v is not None]
                if len(set(votes)) > 1:
                    stats["disagree"] += 1
                    stats.setdefault("disagree_list", []).append((gi, n, ans, it["ans"], final_answer(it["text"])))
                if votes:
                    best = max(set(votes), key=lambda v: (votes.count(v), v == ans))
                    if votes.count(best) > 1 or ans is None:
                        ans = best
            text = join_text(q["lines"])
            body, year, origin = _parse_src(text)
            opt = _find_options(body)
            stem, options = (opt[0], opt[1]) if opt else (body, None)
            # 夹在题目中间的“★本部分题目解析见下册第××页”（★常被认成别的字）
            stem = re.sub(r"(?:(?:^|\n).?|[★☆])?本部分题目解析见下册第[\d~～\-—]+页。?", "", stem)
            stem = re.sub(r"_{4,}", "____", stem)
            segs = crop_segments(doc, q, x_range)
            module, sub = sub_of(vol, q["label"])
            if options and sub == "逻辑填空" and "____" in stem:
                options = _split_options(options, stem.count("____"), it["text"] if it else "")
            # 言语题里画出来的只有横线、方框，不是图；其他模块有图、公式就看原卷
            # 常识、判断（图形推理除外）里的细线是下划线，资料分析、数量关系的细线可能是表格、图形
            fig = not options or (module != "言语理解与表达" and vis.has_visual(
                segs, lines=module not in ("常识判断", "政治理论", "判断推理") or sub == "图形推理"))
            stats["questions"] += 1
            if ans is None:
                continue
            stats["answered"] += 1
            if it and it["text"]:
                stats["explained"] += 1
            questions.append({
                "id": f"q5k-{up_fid}-{gi:03d}-{n:03d}", "num": n, "module": module, "sub": sub,
                "stem": stem.strip(), "options": options, "answer": ans, "explain": it["text"] if it else "",
                "material": mat_ids.get(q["mat"]) if q.get("mat") is not None else None,
                "crop": segs, "explain_crop": [], "fig": bool(fig), "year": year, "origin": origin or SERIES,
                "src": "千题册", "fid": up_fid,
            })
    vis.close()
    return questions, materials, stats


def build_all(catalog_files, root, progress=None, skip_keys=()):
    """返回 (sources, questions, materials)。每卷按章（题型）分成若干题源，方便“顺序练”。"""
    from .books import dedup_key

    files = find_files(catalog_files)
    sources, questions, materials = [], [], []
    seen = set(skip_keys)
    for i, vol in enumerate(VOLS):
        if vol not in files:
            continue
        up, down = files[vol]["up"], files[vol].get("down")
        if progress:
            progress(i, len(VOLS), up["name"])
        try:
            qs, mats, _st = build_volume(vol, os.path.join(root, up["rel"]), up["id"],
                                         os.path.join(root, down["rel"]) if down else None, down["id"] if down else None)
        except Exception as e:  # noqa: BLE001
            print("5000题解析失败", up["rel"], e)
            continue
        by_src = {}
        for q in qs:
            key = dedup_key(q["stem"], q["explain"]) if not q["fig"] else None
            if key and key in seen and not q.get("material"):
                continue
            if key:
                seen.add(key)
            sid = f"b5k-{vol}-{_norm(q['module'])}-{_norm(q['sub'])}"
            q["source"] = sid
            by_src.setdefault(sid, []).append(q)
        mat_src = {}
        for sid, sqs in by_src.items():
            q0 = sqs[0]
            sources.append({
                "id": sid, "title": q0["sub"], "exam": SERIES, "module": q0["module"], "sub": q0["sub"],
                "file": up["rel"], "fid": up["id"], "count": len(sqs), "answered": len(sqs),
                "modules": {q0["module"]: len(sqs)}, "year": max((q["year"] for q in sqs), default=0),
                "note": "决战行测5000题" + ("，解析来自下册" if any(q["explain"] for q in sqs) else ""),
            })
            for q in sqs:
                if q.get("material"):
                    mat_src.setdefault(q["material"], sid)
            questions += sqs
        materials += [{**m, "source": mat_src[m["id"]]} for m in mats if m["id"] in mat_src]
    return sources, questions, materials
