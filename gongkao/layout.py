"""版面还原：思维导图、框图、表格、旁批这类“不是成段文字”的区域，按文字块的位置还原成结构化文字。

资料库只显示文字，不放截图。扫描页、插图、Word 里的图片先 OCR 成文字块，PDF 文字层取逐段片段，
再在这里判断版面：
- 表格 tbl：多行文字左右对齐成列；
- 树 tree：思维导图——父节点在左、子节点在右（或从中间向两边展开），还原成逐级缩进的提纲；
- 框 box：其他框图、流程图，按行保留原来的左右位置；
- 旁批：正文右侧窄栏里的批注（范文解析），挂在对应段落旁边。
输入的文字块都是 [x0, y0, x1, y1, 文字, …]，坐标单位随意（PDF 点或像素），按字高换算。
"""

import re

SENT_END_RE = re.compile(r"[。；;！!？?]$")
WRAP_END_RE = re.compile(r"[/、，,（(“的和与及或+\-—…·：:是在对为把将从以]$")  # 行尾这样结束，下一行是接着的
OPT_SEG_RE = re.compile(r"^\s*[A-H]\s*[.．、:：]")
NUM_CH_RE = re.compile(r"[\d.%,，\-+~～／/]")


class B:
    __slots__ = ("x0", "y0", "x1", "y1", "t", "i")

    def __init__(self, x0, y0, x1, y1, t, i=-1):
        self.x0, self.y0, self.x1, self.y1, self.t, self.i = x0, y0, x1, y1, t, i

    h = property(lambda s: max(s.y1 - s.y0, 1))
    w = property(lambda s: max(s.x1 - s.x0, 1))
    cx = property(lambda s: (s.x0 + s.x1) / 2)
    cy = property(lambda s: (s.y0 + s.y1) / 2)

    def __repr__(self):
        return f"B({self.x0:.0f},{self.y0:.0f},{self.x1:.0f},{self.y1:.0f},{self.t!r})"


def to_boxes(raw):
    return [B(r[0], r[1], r[2], r[3], str(r[4]).strip(), i) for i, r in enumerate(raw) if str(r[4]).strip()]


def _median(vals, default=10):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else default


def char_h(boxes):
    """正文字高：取有几个字的块的高度中位数（单字块常是图形里的标注，高度不准）。"""
    return _median([b.h for b in boxes if len(b.t) >= 3] or [b.h for b in boxes])


def _join(a, b, gap, h):
    if not a:
        return b
    if gap > h * 0.6 and not (a[-1] in "，、：:（(“" or b[:1] in "，。、：:）)”"):
        return a + " " + b
    if re.match(r"[A-Za-z0-9]", a[-1]) and re.match(r"[A-Za-z0-9]", b[0]):
        return a + " " + b
    return a + b


def rows_of(boxes):
    """按高度分行：中线相差不到半个字高的算同一行。每行按从左到右排好。"""
    rows = []
    for b in sorted(boxes, key=lambda b: (b.cy, b.x0)):
        for r in rows[-4:]:
            rh = r["y1"] - r["y0"]
            if abs(b.cy - (r["y0"] + r["y1"]) / 2) < min(b.h, rh) * 0.5:
                r["b"].append(b)
                r["y0"], r["y1"] = min(r["y0"], b.y0), max(r["y1"], b.y1)
                break
        else:
            rows.append({"y0": b.y0, "y1": b.y1, "b": [b]})
    return [sorted(r["b"], key=lambda b: b.x0) for r in sorted(rows, key=lambda r: r["y0"])]


def segs(row, gap):
    """同一行里间距小于 gap 的块拼成一段。"""
    out = []
    for b in row:
        if out and b.x0 - out[-1].x1 < gap:
            o = out[-1]
            o.t = _join(o.t, b.t, b.x0 - o.x1, b.h)
            o.x1, o.y0, o.y1 = max(o.x1, b.x1), min(o.y0, b.y0), max(o.y1, b.y1)
        else:
            out.append(B(b.x0, b.y0, b.x1, b.y1, b.t))
    return out


# ---------------------------------------------------------------- 整页：找出非成段文字的区域

def analyse(raw, W, pno, whole=False):
    """一页（或一张图）的文字块 → (区域块 [(y0, x0, 块)], 剩下的普通文字块原样)。
    whole=True：整页都当成一个区域（海报、思维导图整页）。"""
    boxes = to_boxes(raw)
    if not boxes:
        return [], []
    h = char_h(boxes)
    if whole:
        box = (min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))
        blks = convert(boxes, pno, h, strict=True)
        for b in blks:
            b["_box"] = box
        return [(box[1], 0, b) for b in blks], []
    longs = [b for b in boxes if b.w >= h * 6]
    if len(longs) >= 4:
        left = sorted(b.x0 for b in longs)[len(longs) // 10]
        right = sorted(b.x1 for b in longs)[min(len(longs) - 1, len(longs) * 9 // 10)]
    else:
        left, right = min(b.x0 for b in boxes), max(b.x1 for b in boxes)
    wc = max(right - left, h * 10)
    out = []
    # 旁批：右侧窄栏的短文字，左边是成段的正文
    side = [b for b in boxes if b.x0 >= left + wc * 0.68 and b.w <= wc * 0.32 and not re.fullmatch(r"[\d\s.\-—/]+", b.t)]
    if len(side) >= 3:
        sx = min(b.x0 for b in side)
        body = [b for b in boxes if b.w >= wc * 0.45 and b.x1 <= sx + h]
        # 正文和批注之间要有一道空白（不然只是正文行被 OCR 断成了两块）
        gutter = all(b.x1 < sx - h * 0.8 for b in boxes if b.x0 < sx - h and b.x1 > sx - h * 3)
        if len(body) >= 5 and len(body) >= len(side) * 0.8 and gutter:
            out += _side_notes(side, h, pno)
            ids = {b.i for b in side}
            boxes = [b for b in boxes if b.i not in ids]
            right = max((b.x1 for b in body), default=right)
            wc = max(right - left, h * 10)
    rows = rows_of(boxes)
    kinds = [_row_kind(r, h, left, right, wc) for r in rows]
    taken = set()
    i = 0
    while i < len(rows):
        if kinds[i] != "diag":
            i += 1
            continue
        j = i
        k = i + 1
        while k < len(rows):
            gap_y = min(b.y0 for b in rows[k]) - max(b.y1 for b in rows[k - 1])
            if gap_y > h * 4:
                break
            if kinds[k] == "diag":
                j = k
                k += 1
                continue
            # 区域中间夹着的一两行短字（节点名）也算进去
            if kinds[k] in ("short", "mid") and any(kinds[m] == "diag" for m in range(k + 1, min(len(rows), k + 3))):
                k += 1
                continue
            break
        span = rows[i:j + 1]
        nd = sum(1 for m in range(i, j + 1) if kinds[m] == "diag")
        nb = sum(len(r) for r in span)
        if nd >= 3 and nb >= 6:
            bs = [b for r in span for b in r]
            box = (min(b.x0 for b in bs), min(b.y0 for b in bs), max(b.x1 for b in bs), max(b.y1 for b in bs))
            for blk in convert(bs, pno, h, strict=len(span) > 18):
                blk["_box"] = box
                out.append((box[1], box[0], blk))
            taken.update(b.i for b in bs)
        i = j + 1
    return out, [raw[b.i] for b in boxes if b.i not in taken]


def _row_kind(row, h, left, right, wc):
    """一行是成段正文（prose）、导图/框图里的一行（diag）、还是零星短字（short）。"""
    ss = segs(row, h * 1.5)
    text = "".join(s.t for s in ss)
    if any(OPT_SEG_RE.match(s.t) for s in ss) and sum(1 for s in ss if OPT_SEG_RE.match(s.t)) >= len(ss) - 1:
        return "prose"  # A.… B.… C.… D.… 选项排成一行
    if len(ss) == 1:
        s = ss[0]
        near = s.x0 - left < h * 3.2  # 顶格或首行缩进两字
        if near and (s.w >= wc * 0.5 or len(s.t) >= 8):
            return "prose"  # 正文行、段落末行、顶格的小标题
        if abs(s.cx - (left + right) / 2) < h * 1.2 and 4 <= len(s.t) <= 30:
            return "mid"  # 居中的一行：标题，或导图中间的节点
        return "short" if near else "diag"  # 离左边很远的单段：导图里的节点
    if len(ss) == 2 and all(s.w >= wc * 0.3 for s in ss):
        return "prose"  # 两栏排版
    if len(text) >= 40 and max(s.w for s in ss) >= wc * 0.6:
        return "prose"
    return "diag"


def _side_notes(side, h, pno):
    """旁批：上下挨着的几块拼成一条。"""
    side = sorted(side, key=lambda b: (b.y0, b.x0))
    groups = []
    for b in side:
        g = groups[-1] if groups else None
        if g and b.y0 - g["y1"] < h * 0.9:
            g["t"] = _join(g["t"], b.t, 0, h)
            g["y1"] = max(g["y1"], b.y1)
        else:
            groups.append({"y0": b.y0, "y1": b.y1, "t": b.t, "x0": b.x0})
    out = []
    for g in groups:
        t = g["t"].strip()
        if not t or re.fullmatch(r"解\s*析|批\s*注|旁\s*批|点\s*评", t):
            continue
        out.append((g["y0"], g["x0"], {"k": "p", "t": t, "pg": pno, "d": {"side": 1}}))
    return out


# ---------------------------------------------------------------- 区域 → 表格 / 树 / 框

def convert(boxes, pno, h=None, strict=False):
    """一块区域的文字块 → 资料库块（通常一块）。strict：整页、很高的区域，只凭坐标轴、饼图标签认统计图
    （数字多的整页常是表格 + 题目，表格没对齐成功时不能整页截成图）。"""
    h0 = h or char_h(boxes)
    # 水印 logo 里的大号字母（“L”“DE”）不是内容
    boxes = [b for b in boxes if b.t and not (re.fullmatch(r"[A-Za-z]{1,3}", b.t) and b.h > h0 * 1.8)]
    if not boxes:
        return []
    h = h or char_h(boxes)
    text = "".join(b.t for b in boxes)
    numeric = len(NUM_CH_RE.findall(text)) >= len(text) * 0.4  # 统计图的坐标、数据标签：不是导图
    long = sum(1 for b in boxes if len(CJK_RE.findall(b.t)) >= 10)
    if not (strict and long > 2) and is_chart(boxes, h, numeric):
        # 统计图：文字还原只剩一堆零散数字，调用方按区域截成图（文字留作搜索用）
        return [{"k": "chart", "t": _rows_box(boxes, h, pno)["t"], "pg": pno}]
    tbl = _table(boxes, h)
    if tbl:
        return [{"k": "tbl", "t": " ".join(" ".join(r) for r in tbl), "pg": pno, "d": {"rows": tbl}}]
    if numeric and not strict and not FORMULA_RE.search(text) and not _wordy(boxes) and sum(1 for b in boxes if NUM_TOKEN_RE.match(b.t.replace(" ", ""))) >= 6:
        return [{"k": "chart", "t": _rows_box(boxes, h, pno)["t"], "pg": pno}]
    items = None if numeric else _tree(boxes, h)
    if items:
        return [{"k": "tree", "t": " ".join(t for _d, t in items), "pg": pno, "d": {"items": items}}]
    return [_rows_box(boxes, h, pno)]


CJK_RE = re.compile(r"[一-鿿]")
NUM_TOKEN_RE = re.compile(r"^[-+−]?\d{1,7}(?:[.,]\d+)?[%‰]?$")
PIE_LABEL_RE = re.compile(r"^[一-鿿A-Za-z（）()]{1,12}\s*[,，:：]?\s*[-+]?\d+(?:\.\d+)?\s*(?:%|‰|万|亿|元|吨|个|人|家|辆|件)?$")
FORMULA_RE = re.compile(r"[=＝⦅×÷√]|[+\-]\s*\d+\s*[+\-]|解析|答案|故选|选[A-D]|正确")  # 速算、公式的算式区域，不是统计图


def _num(t):
    try:
        return float(t.replace(" ", "").replace(",", "").replace("−", "-").rstrip("%‰"))
    except ValueError:
        return None


def _ticks(pts):
    """[(位置, 数值)] 按位置排好：有没有至少 4 个等距排开、数值等差的刻度（坐标轴）。"""
    best = 1
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            step, gap = pts[j][1] - pts[i][1], pts[j][0] - pts[i][0]
            if not step or gap <= 0:
                continue
            run, last = [pts[i], pts[j]], pts[j]
            for p in pts[j + 1:]:
                if abs(p[1] - last[1] - step) <= abs(step) * 0.01 and abs(p[0] - last[0] - gap) <= gap * 0.25:
                    run.append(p)
                    last = p
            vals = [v for _p, v in run]
            years = all(1900 <= v <= 2100 for v in vals) and abs(step) == 1
            if len(run) >= 4 and not years and not (abs(step) == 1 and all(v == int(v) for v in vals)):
                best = max(best, len(run))
    return best >= 4


def _axis(boxes, h):
    """统计图的坐标轴：一列右对齐（或居中）的刻度数字，从下往上等距递增；或一行从左往右等距递增的数字。"""
    nums = [(b, _num(b.t)) for b in boxes if NUM_TOKEN_RE.match(b.t.replace(" ", ""))]
    nums = [(b, v) for b, v in nums if v is not None]
    if len(nums) < 4:
        return False
    seen = set()
    for key in (lambda b: b.x1, lambda b: b.cx, lambda b: b.x0):
        for b, _v in nums:
            grp = [(x, v) for x, v in nums if abs(key(x) - key(b)) <= h * 0.8]
            ids = frozenset(id(x) for x, _v in grp)
            if len(grp) < 4 or ids in seen:
                continue
            seen.add(ids)
            # 表格里的页码、序号列：同一行左边都有成串的文字；坐标轴刻度那一行旁边没有
            wordy = sum(1 for x, _v in grp if any(len(CJK_RE.findall(o.t)) >= 4 and abs(o.cy - x.cy) < h * 0.5 and o.x1 <= x.x0 for o in boxes))
            if wordy <= len(grp) * 0.25 and _ticks(sorted(((-x.cy, v) for x, v in grp), key=lambda p: p[0])):
                return True
    for b, _v in nums:
        grp = [(x, v) for x, v in nums if abs(x.cy - b.cy) <= h * 0.5]
        ids = frozenset(id(x) for x, _v in grp)
        if len(grp) < 4 or ids in seen:
            continue
        seen.add(ids)
        if _ticks(sorted(((x.cx, v) for x, v in grp), key=lambda p: p[0])):
            return True
    return False


def _wordy(boxes):
    return sum(1 for b in boxes if len(CJK_RE.findall(b.t)) >= 10) > max(2, len(boxes) * 0.2)


def is_chart(boxes, h, numeric=None):
    """这块区域是不是统计图（柱状图、折线图、饼图）：有坐标轴刻度，或有三个以上“俄罗斯，929”式的数据标签。"""
    if _wordy(boxes):
        return False  # 成句的文字多：是表格、目录、文字框、题目，不是统计图
    if _axis(boxes, h):
        return True
    pies = sum(1 for b in boxes if PIE_LABEL_RE.match(b.t.strip()) and re.search(r"\d", b.t))
    return pies >= 3 and pies >= len(boxes) * 0.3


def _rows_box(boxes, h, pno):
    x_min = min(b.x0 for b in boxes)
    lines = []
    for row in rows_of(boxes):
        ss = segs(row, h * 1.5)
        t = "　　".join(s.t for s in ss)
        lines.append([t, min(6, int((ss[0].x0 - x_min) / (h * 2)))])
    return {"k": "box", "t": "\n".join(t for t, _a in lines), "pg": pno, "d": {"lines": lines}}


def _table(boxes, h):
    rows = [segs(r, h * 0.5) for r in rows_of(boxes)]
    rows = [r for r in rows if r]
    if len(rows) < 3:
        return None
    multi = [r for r in rows if len(r) >= 2]
    if len(multi) < max(3, len(rows) * 0.6):
        return None
    top = max(len(r) for r in multi)
    full = [r for r in multi if len(r) >= max(2, top - 1)]
    ivs = sorted((s.x0, s.x1) for r in full for s in r)
    cols = []
    for a, z in ivs:
        if cols and a < cols[-1][1] - h * 0.3:
            cols[-1][1] = max(cols[-1][1], z)
        else:
            cols.append([a, z])
    if not 2 <= len(cols) <= 12:
        return None

    def col_of(s):
        best, bi = -1e9, 0
        for i, (a, z) in enumerate(cols):
            ov = min(s.x1, z) - max(s.x0, a)
            if ov > best:
                best, bi = ov, i
        return bi

    grid = []
    clash = 0
    for r in rows:
        cells = [""] * len(cols)
        for s in r:
            c = col_of(s)
            if cells[c]:
                clash += 1
                cells[c] += " " + s.t
            else:
                cells[c] = s.t
        grid.append(cells)
    filled = sum(1 for r in grid for c in r if c)
    if filled < len(grid) * len(cols) * 0.5 or clash > len(rows) * 0.25:
        return None
    # 一格里折成两行的字：下一行只有这一列有字、而且紧挨着，并回上一行
    out = []
    prev_y1 = 0.0
    for cells, r in zip(grid, rows):
        if out and sum(1 for c in cells if c) == 1 and sum(1 for c in out[-1] if c) >= 2:
            c = next(i for i, x in enumerate(cells) if x)
            if out[-1][c] and not SENT_END_RE.search(out[-1][c]) and r[0].y0 - prev_y1 < h * 0.5:
                out[-1][c] += cells[c]
                prev_y1 = max(b.y1 for b in r)
                continue
        out.append(cells)
        prev_y1 = max(b.y1 for b in r)
    return out


def _nodes(boxes, h):
    """导图节点：同一行挨着的拼起来；竖排的单字、折行的节点上下并起来。"""
    nodes = []
    for row in rows_of(boxes):
        nodes += segs(row, h * 0.6)
    changed = True
    while changed:
        changed = False
        nodes.sort(key=lambda b: (b.y0, b.x0))
        for a in nodes:
            for b in nodes:
                if b is a or b.y0 < a.y1 - h * 0.3:
                    continue
                gap = b.y0 - a.y1
                if gap > h * 0.6:
                    continue
                # 竖排的字；居中排成两行的短节点（“正面 / 提对策”）；折行的长节点（上一行没说完）
                vert = len(a.t) <= 3 and len(b.t) <= 2 and abs(a.cx - b.cx) < h * 0.6 and a.w < h * 1.6
                pair = len(a.t) <= 6 and len(b.t) <= 8 and abs(a.cx - b.cx) < h * 0.8 and gap < h * 0.5 \
                    and abs(len(a.t) - len(b.t)) <= 3
                wrap = (gap < h * 0.45 and abs(a.x0 - b.x0) < h * 0.8 and b.w <= a.w + h * 0.5
                        and WRAP_END_RE.search(a.t))
                if not (vert or pair or wrap):
                    continue
                if any(c is not a and c is not b and c.y0 < b.y0 and c.y1 > a.y1 - h * 0.3
                       and min(c.x1, max(a.x1, b.x1)) > max(c.x0, min(a.x0, b.x0)) for c in nodes):
                    continue  # 中间夹着别的节点
                a.t = a.t + b.t
                a.x0, a.x1, a.y1 = min(a.x0, b.x0), max(a.x1, b.x1), max(a.y1, b.y1)
                nodes.remove(b)
                changed = True
                break
            if changed:
                break
    return nodes


def _parents(nodes, h, mirror=False):
    """每个节点挑父节点：左边最近一列里的节点，按“父节点位于它那组子节点的中间”分配（导图连线看不到，靠位置）。
    返回 {子节点下标: 父节点下标}。mirror=True 时左右翻转（向左展开的一侧）。"""
    if mirror:
        xs = [(-b.x1, -b.x0) for b in nodes]
    else:
        xs = [(b.x0, b.x1) for b in nodes]
    n = len(nodes)
    ys = [b.cy for b in nodes]
    cands = []
    for i in range(n):
        x0 = xs[i][0]
        cs = [m for m in range(n) if m != i and xs[m][1] <= x0 + h * 0.6 and xs[m][0] < x0 - h * 0.5
              and x0 - xs[m][1] <= h * 9 and abs(ys[m] - ys[i]) <= h * 30]
        if cs:
            mx = max(xs[m][0] for m in cs)
            cs = [m for m in cs if xs[m][0] >= mx - h * 1.5]
        cands.append(set(cs))
    # 共享候选父节点的子节点放在一起分配
    comp = {}
    owner = {}
    for i in range(n):
        if not cands[i]:
            continue
        keys = {owner[p] for p in cands[i] if p in owner}
        cid = min(keys) if keys else i
        for k in keys:
            if k != cid:
                for c in comp.pop(k):
                    comp.setdefault(cid, []).append(c)
                for p, o in list(owner.items()):
                    if o == k:
                        owner[p] = cid
        comp.setdefault(cid, []).append(i)
        for p in cands[i]:
            owner[p] = cid
    par = {}
    for kids in comp.values():
        kids.sort(key=lambda i: ys[i])
        ps = sorted({p for i in kids for p in cands[i]}, key=lambda p: ys[p])
        par.update(_assign(kids, ps, cands, ys, h))
    return par


def _assign(kids, ps, cands, ys, h):
    """子节点（按高度排好）分成连续的几组，依次挂到父节点（按高度排好）下；每组的中点尽量对准父节点。"""
    k, P = len(kids), len(ps)
    INF = float("inf")
    dp = [[INF] * P for _ in range(k + 1)]
    back = [[None] * P for _ in range(k + 1)]
    pm = [[0.0] * (P + 1)]  # pm[i][b] = min(dp[i][0..b-1])；i = 0 时为 0

    pys = [ys[p] for p in ps]

    def gcost(i, j, b):
        lo, hi = ys[kids[i]], ys[kids[j]]
        py = pys[b]
        c = abs(py - (lo + hi) / 2) / h
        if py < lo - h * 2.5 or py > hi + h * 2.5:
            c += 3
        # 这组子节点的高度范围里夹着别的父节点：那个父节点本该分到这里的子节点
        c += 3 * sum(1 for a, y in enumerate(pys) if a != b and lo < y < hi)
        c += 0.1 * sum(abs(ys[kids[t]] - py) for t in range(i, j + 1)) / (j - i + 1) / h
        return c

    for j in range(1, k + 1):
        for b in range(P):
            i = j - 1
            while i >= 0 and ps[b] in cands[kids[i]]:
                prev = pm[i][b] if i else 0.0
                if prev < INF:
                    c = prev + gcost(i, j - 1, b)
                    if c < dp[j][b]:
                        dp[j][b] = c
                        back[j][b] = i
                i -= 1
        row = [INF] * (P + 1)
        for b in range(P):
            row[b + 1] = min(row[b], dp[j][b])
        pm.append(row)
    best = min(range(P), key=lambda b: dp[k][b]) if P else None
    if best is None or dp[k][best] == INF:
        return {i: min(cands[i], key=lambda p: abs(ys[p] - ys[i])) for i in kids}
    out = {}
    j, b = k, best
    while j > 0:
        i = back[j][b]
        for t in range(i, j):
            out[kids[t]] = ps[b]
        if i == 0:
            break
        b = min((a for a in range(b) if dp[i][a] < INF), key=lambda a: dp[i][a])
        j = i
    return out


def _tree(boxes, h):
    """思维导图 → [[层级, 文字], …]；不像导图就返回 None。"""
    nodes = _nodes(boxes, h)
    n = len(nodes)
    if n < 5:
        return None
    best = None
    for mode in ("ltr", "center"):
        if mode == "ltr":
            par = _parents(nodes, h)
        else:
            # 中心向两边展开：最大的字（根节点）在中间，左半边翻转后同样处理
            mid = (min(b.x0 for b in nodes) + max(b.x1 for b in nodes)) / 2
            cand = [i for i, b in enumerate(nodes) if abs(b.cx - mid) < (max(b.x1 for b in nodes) - min(b.x0 for b in nodes)) * 0.25]
            if not cand:
                continue
            root = max(cand, key=lambda i: (nodes[i].h, len(nodes[i].t) <= 12))
            L = [i for i, b in enumerate(nodes) if b.cx < nodes[root].cx and i != root]
            R = [i for i, b in enumerate(nodes) if b.cx >= nodes[root].cx and i != root]
            if len(L) < 2 or len(R) < 2:
                continue
            par = {}
            for side, mir in ((R, False), (L, True)):
                sub = [root] + side
                pp = _parents([nodes[i] for i in sub], h, mirror=mir)
                par.update({sub[c]: sub[p] for c, p in pp.items() if sub[c] != root})
        roots = [i for i in range(n) if i not in par]
        kids = {}
        for c, p in par.items():
            kids.setdefault(p, []).append(c)
        if not kids:
            continue
        fan = sum(len(v) for v in kids.values()) / len(kids)
        score = (len(roots) / n, -fan)
        if best is None or score < best[0]:
            best = (score, roots, kids)
    if best is None:
        return None
    (root_frac, neg_fan), roots, kids = best
    if root_frac > 0.3 or -neg_fan < 1.45:
        return None
    items = []
    seen = set()

    def walk(i, d):
        if i in seen:
            return
        seen.add(i)
        lift = (bool(kids.get(i)) or d == 0) and re.fullmatch(r"[A-Za-z]{1,3}", nodes[i].t)  # 水印残字：跳过它
        if not lift:
            items.append([min(d, 8), nodes[i].t])
        for c in sorted(kids.get(i, []), key=lambda c: nodes[c].cy):
            walk(c, d if lift else d + 1)

    for r in sorted(roots, key=lambda i: (nodes[i].cy, nodes[i].x0)):
        walk(r, 0)
    if len(items) < n:  # 有环（不应出现）：剩下的按顺序补上
        for i in sorted(set(range(n)) - seen, key=lambda i: nodes[i].cy):
            items.append([0, nodes[i].t])
    if not items or max(d for d, _t in items) < 1:
        return None
    return items
