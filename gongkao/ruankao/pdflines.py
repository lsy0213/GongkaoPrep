"""软考 PDF 的文字行：去掉水印、页眉页脚，保留每行在哪一页、什么位置（切原卷截图用）。

还有几个小工具：把 PDF 的硬换行接回成段落、文字归一化后在另一份文件里找同一段话（真题卷 ↔ 答案详解对齐）。
"""

import re

# 每页都有的推广水印、页眉页脚
NOISE_RE = re.compile(
    r"软考达人|ruankaodaren|手机端题库|PC端题库|微信搜索|免费提供\d+w\+|1TB免费|"
    r"^\s*第\s*\d+\s*页\s*(共\s*\d+\s*页)?\s*$|^\s*\d{1,3}\s*$|"
    r"系统架构设计师\s*(上午|下午)试卷\s*(I{1,2}|Ⅰ|Ⅱ)?\s*第\s*\d+\s*页|"
    r"^\s*(上午|下午)试题\s*[(（]?\s*(Ⅰ|Ⅱ|I{1,2})?\s*[)）]?\s*模拟\s*\d+\s*$|"
    r"全国计算机技术与软件专业技术资格[（(]水平[)）]考试\s*$")


class Line:
    __slots__ = ("text", "page", "bbox")

    def __init__(self, text, page, bbox):
        self.text = text
        self.page = page
        self.bbox = bbox

    def __repr__(self):
        return f"<{self.page}:{self.text[:30]}>"


def read_lines(path):
    """PDF → [Line]（按页、按版面从上到下），去掉水印和页眉页脚、空行。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    out = []
    d = pymupdf.open(path)
    try:
        for pno, page in enumerate(d):
            for b in page.get_text("dict", sort=True)["blocks"]:
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    t = "".join(s["text"] for s in ln["spans"])
                    t = t.replace("　", " ").replace("\xa0", " ").rstrip()
                    if not t.strip() or NOISE_RE.search(t):
                        continue
                    out.append(Line(t.strip(), pno, tuple(round(v, 1) for v in ln["bbox"])))
    finally:
        d.close()
    return out


# ---------------------------------------------------------------- 文字

FULL = str.maketrans("（）．，：；！？０１２３４５６７８９ＡＢＣＤ　", "().,:;!?0123456789ABCD ")


def norm(t):
    """对齐用的归一化：全角转半角、去掉空白和标点，只留字和数字。"""
    t = (t or "").translate(FULL)
    return re.sub(r"[\s\W_]+", "", t)


class Normed:
    """归一化后的文字，并记住每个字在原文里的位置，找到以后能换回原文的位置。"""

    def __init__(self, text):
        self.text = text
        chars, idx = [], []
        for i, ch in enumerate((text or "").translate(FULL)):
            if re.match(r"[\w]", ch) and ch != "_":
                chars.append(ch)
                idx.append(i)
        self.n = "".join(chars)
        self.idx = idx

    def find(self, needle, start=0):
        """在原文里找一段话（归一化比较），返回原文位置（找不到 -1）。start 是原文位置。"""
        k = norm(needle)
        if not k:
            return -1
        s = self._to_n(start)
        j = self.n.find(k, s)
        return self.idx[j] if j >= 0 else -1

    def find_end(self, needle, start=0):
        """同上，返回这段话结束处的原文位置。"""
        k = norm(needle)
        if not k:
            return -1
        s = self._to_n(start)
        j = self.n.find(k, s)
        if j < 0:
            return -1
        e = j + len(k) - 1
        return self.idx[e] + 1

    def _to_n(self, pos):
        import bisect

        return bisect.bisect_left(self.idx, pos)


END_PUNCT = "。！？；：…”」）)!?;:"
LIST_START_RE = re.compile(r"^\s*(?:[(（]?\d{1,2}[)）.、．]|[①-⑳]|[一二三四五六七八九十]+[、.．]|[A-H][.．、]|【|●|■|◆|▲|·|-\s|•)")


def join_lines(lines):
    """PDF 的硬换行接回段落：上一行没以句末标点结束、下一行也不是列表项开头，就接在一起。"""
    out = []
    for t in lines:
        t = t.strip()
        if not t:
            continue
        if out and not out[-1].endswith(tuple(END_PUNCT)) and not LIST_START_RE.match(t) and len(out[-1]) >= 18:
            sep = " " if re.search(r"[A-Za-z0-9]$", out[-1]) and re.match(r"[A-Za-z0-9]", t) else ""
            out[-1] += sep + t
        else:
            out.append(t)
    return "\n".join(out)


def tidy(t):
    """常见的文字层小毛病：全角括号里的空格、“C.C.”这种重复的选项字母、连续空格。"""
    t = re.sub(r"[ \t]+", " ", t or "")
    t = re.sub(r"\s+([，。；：、）)])", r"\1", t)
    t = re.sub(r"([（(])\s+", r"\1", t)
    return t.strip()


def crop_segments(lines, pad=4.0):
    """一组行 → 原卷截图的区域 [[页, x0, y0, x1, y1], …]（跨页的每页一段）。整页宽度，免得切掉表格的边。"""
    by_page = {}
    for ln in lines:
        x0, y0, x1, y1 = ln.bbox
        p = by_page.setdefault(ln.page, [x0, y0, x1, y1])
        p[0], p[1], p[2], p[3] = min(p[0], x0), min(p[1], y0), max(p[2], x1), max(p[3], y1)
    segs = []
    for pg in sorted(by_page):
        x0, y0, x1, y1 = by_page[pg]
        segs.append([pg, round(max(0, min(x0, 40) - pad), 1), round(max(0, y0 - pad), 1), round(max(x1, 560) + pad, 1),
                     round(y1 + pad, 1)])
    return segs
