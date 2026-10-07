"""题册（千题册等表格式题本）→ 题目。

这类题本是一页一张表：题号 | 答案 | 来源 | 题目（题干 + 选项）| 解析，列的多少和顺序因书而异。
做法：
1. 把页面渲染成图，找出表格的横线、竖线 → 单元格；
2. 文字：有文字层的直接取，扫描版用 OCR（结果按页缓存）；
3. 按内容判断每一列是什么（纯数字=题号、单个字母=答案、“20xx年…”=来源、带 A–D 的=题目、带“正确答案”的=解析）；
4. 题号格为空的行是上一题跨页的续行，接到上一题后面。
每题记下题目格、解析格在原页上的位置，图形推理等题直接显示原图。
"""

import json
import os
import re

from . import ocr
from .paths import data_dir
from .pdftext import join_text
from .realexam import OPT_LOOSE_RE, OPT_RE, _answer_in, _find_options

PAGES_DIR = data_dir() / "library" / "pages"

# 题册类型 → (模块, 题型)
BOOK_TYPES = [
    ("类比推理", "判断推理", "类比推理"), ("逻辑判断", "判断推理", "逻辑判断"), ("图形推理", "判断推理", "图形推理"),
    ("定义判断", "判断推理", "定义判断"), ("逻辑填空", "言语理解与表达", "逻辑填空"),
    ("片段阅读", "言语理解与表达", "片段阅读"), ("语句表达", "言语理解与表达", "语句表达"),
]
WATERMARK_RE = re.compile(r"^(天明考?公?|明考公|考公|SLOGAN|天\s*明)$", re.I)
LETTER_IDX = {"A": 0, "B": 1, "C": 2, "D": 3}


# ---------------------------------------------------------------- 表格线

def _clusters(idx, gap=3):
    out, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > gap:
            out.append(cur)
            cur = []
        cur.append(int(i))
    if cur:
        out.append(cur)
    return [(c[0] + c[-1]) / 2 for c in out]


def _long_runs(mask, axis, min_frac):
    """沿 axis 方向，连续黑像素最长段达到 min_frac 的行（或列）号。"""
    import numpy as np

    m = mask if axis == 1 else mask.T
    n = m.shape[1]
    cand = np.where(m.mean(axis=1) > min_frac * 0.9)[0]
    out = []
    for i in cand:
        row = m[i].astype(np.int8)
        d = np.diff(np.concatenate(([0], row, [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        if len(starts) and (ends - starts).max() >= min_frac * n:
            out.append(i)
    return out


def find_grid(img, zoom):
    """返回 (横线 y 列表, 竖线 x 列表)，PDF 坐标；找不到表格返回 None。"""
    import numpy as np

    gray = img.mean(axis=2)
    dark = gray < 165
    hl = _clusters(_long_runs(dark, 1, 0.45))
    if len(hl) < 2:
        return None
    top, bot = int(hl[0]), int(hl[-1])
    if bot - top < 40:
        return None
    sub = dark[top:bot + 1]
    vl = _clusters(_long_runs(sub, 0, 0.5))
    if len(vl) < 3:
        return None
    return [round(y / zoom, 1) for y in hl], [round(x / zoom, 1) for x in vl]


# ---------------------------------------------------------------- 填空横线

BLANK = "____"
BLANKS_V = 4  # 改了找横线的规则就加 1，页缓存里的横线会重新找


def find_blanks(img, zoom, grid, boxes):
    """扫描版里画出来的填空横线 → [[x0, y, x1, 紧跟的标点], ...]（PDF 坐标）。

    OCR 只认字，横线本身和紧跟在横线后面的“，。”都会丢，题干就成了“困境愈发家庭结构”。
    横线 = 一段细长的水平黑线，上方没有字（排除“画横线的句子”那种字下面的线），
    且在文字行的底部（排除行中间的破折号“——”）。
    """
    import numpy as np

    if not grid:
        return []
    dark = img.mean(axis=2) < 165
    H, W = dark.shape
    min_len, max_len = int(14 * zoom), int(W * 0.3)
    segs = []
    for y in np.where(dark.sum(axis=1) >= min_len)[0]:
        d = np.diff(np.concatenate(([0], dark[y].astype(np.int8), [0])))
        s, e = np.where(d == 1)[0], np.where(d == -1)[0]
        keep = (e - s >= min_len) & (e - s <= max_len)
        segs += [[int(y), int(a), int(b), int(y)] for a, b in zip(s[keep], e[keep])]
    merged = []  # 线有 1–3 像素粗：相邻几行并成一条
    for y, a, b, _ in segs:
        for m in merged:
            if 0 <= y - m[3] <= 1 and min(b, m[2]) - max(a, m[1]) > 0.6 * (b - a):
                m[1], m[2], m[3] = min(a, m[1]), max(b, m[2]), y
                break
        else:
            merged.append([y, a, b, y])
    out = []
    for y0, a, b, y1 in merged:
        uy = (y0 + y1) / 2 / zoom
        if (y1 - y0) / zoom > 2.5 or any(abs(uy - g) < 3 for g in grid[0]):
            continue  # 粗线、表格线
        x0, x1 = a / zoom, b / zoom
        top, bot = int(y0 - 9 * zoom), int(y0 - 2 * zoom)
        if top < 0 or dark[top:bot, a:b].any(axis=0).mean() > 0.15:
            continue  # 线上方有字：是给句子画的线，不是空
        cols = [(l, r) for l, r in zip(grid[1], grid[1][1:]) if l - 2 <= x0 and x1 <= r + 2]
        if not cols:
            continue  # 跨了表格竖线
        cl, cr = cols[0]
        line = [bx for bx in boxes if bx[1] - 1 <= uy <= bx[3] + 2.5 and bx[3] - bx[1] > 5
                and cl <= (bx[0] + bx[2]) / 2 <= cr]
        if any((uy - bx[1]) / (bx[3] - bx[1]) < 0.65 for bx in line):
            continue  # 在行中间：破折号
        # 紧跟在横线后面的小黑点 = 被 OCR 漏掉的标点
        right = min([bx[0] for bx in line if bx[0] >= x1 - 1] + [x1 + 12, cr - 1.5])
        ca, cb = int((x1 + 0.4) * zoom), int((right - 0.3) * zoom)
        ct, cbm = int((uy - 11) * zoom), int((uy + 1.5) * zoom)
        punct = ""
        if cb > ca:
            ys, xs = np.nonzero(dark[ct:cbm, ca:cb])
            if len(xs):
                w, h = (xs.max() - xs.min() + 1) / zoom, (ys.max() - ys.min() + 1) / zoom
                if w <= 6 and h <= 7:
                    blob = dark[ct:cbm, ca:cb][ys.min():ys.max() + 1, xs.min():xs.max() + 1]

                    def runs(v):  # 一条线穿过几段黑
                        return int(np.diff(np.concatenate(([0], v.astype(np.int8), [0]))).clip(0).sum())

                    # 句号是个圈：正中横着、竖着都要穿过两段黑；逗号是一团实心带个尾巴
                    ring = (w >= 2.5 and h >= 2.5 and runs(blob[blob.shape[0] // 2]) >= 2
                            and runs(blob[:, blob.shape[1] // 2]) >= 2)
                    punct = "。" if ring else "，"
        out.append([round(x0, 1), round(uy, 1), round(x1, 1), punct])
    return out


GAPS_V = 1  # 改了补认漏行的规则就加 1


def fill_cell_gaps(img, zoom, grid, boxes):
    """文字检测偶尔整行漏掉（常是紧贴表格横线的第一行，排序题就少了一句）。

    表格线会让整页每一行都“有墨迹”，所以逐列来：把这一列抠出来、擦掉横线，再用 ocr.fill_gaps 补认。
    """
    if not grid:
        return []
    hl, vl = grid
    out = []
    for c in range(len(vl) - 1):
        x0, x1 = int(vl[c] * zoom) + 4, int(vl[c + 1] * zoom) - 4
        if x1 - x0 < 30 * zoom:
            continue
        sub = img[:, x0:x1].copy()
        sub[: max(0, int(hl[0] * zoom) + 3)] = 255
        sub[int(hl[-1] * zoom) - 3:] = 255
        for y in hl:
            sub[max(0, int(y * zoom) - 3): int(y * zoom) + 4] = 255
        dx = x0 / zoom
        col = [(b[0] - dx, b[1], b[2] - dx, b[3], b[4], b[5]) for b in boxes
               if x0 / zoom <= (b[0] + b[2]) / 2 <= x1 / zoom]
        for b in ocr.fill_gaps(sub, col, zoom):
            if b[5] >= 0.6 and not WATERMARK_RE.match(b[4].strip()):
                out.append((round(b[0] + dx, 1), b[1], round(b[2] + dx, 1), b[3], b[4], b[5]))
    return out


def blank_boxes(blanks, boxes):
    """横线 → 和文字框同一格式的“____”框，按位置插进文字行里。"""
    hs = sorted(b[3] - b[1] for b in boxes if b[3] - b[1] > 5)
    hh = hs[len(hs) // 2] if hs else 11.5
    out = []
    for x0, uy, x1, punct in blanks:
        out.append((x0, uy + 1 - hh, x1, uy + 1, BLANK + punct, 1.0))
    return out


# ---------------------------------------------------------------- 每页分析（缓存）

def analyze_page(fid, doc, pno, scanned):
    cache = PAGES_DIR / fid / f"{pno}.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if not scanned or (data.get("blanks_v") == BLANKS_V and data.get("gaps_v") == GAPS_V):
                return data
            # 老缓存：只重新看图补认漏行、找填空横线，整页 OCR 结果照用
            img = ocr.page_image(doc[pno], ocr.ZOOM)
            if data.get("gaps_v") != GAPS_V and ocr.available():
                data["gap_boxes"] = fill_cell_gaps(img, ocr.ZOOM, data.get("grid"), data["boxes"])
                data["gaps_v"] = GAPS_V
            data["blanks"] = find_blanks(img, ocr.ZOOM, data.get("grid"), data["boxes"] + data.get("gap_boxes", []))
            data["blanks_v"] = BLANKS_V
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except ValueError:
            pass
    if scanned and not ocr.available():
        # 没装 OCR 组件：这页先跳过，也不写缓存，装好后再整理一次就能补上
        return {"grid": None, "boxes": []}
    page = doc[pno]
    zoom = ocr.ZOOM if scanned else 1.5
    img = ocr.page_image(page, zoom)
    grid = find_grid(img, zoom)
    if scanned:
        boxes = ocr.recognize(img, zoom) if grid else []
    else:
        boxes = [(round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1), w[4], 1.0)
                 for w in page.get_text("words")]
    data = {"grid": grid, "boxes": boxes, "size": [page.rect.width, page.rect.height]}
    if scanned:
        data["gap_boxes"], data["gaps_v"] = fill_cell_gaps(img, zoom, grid, boxes), GAPS_V
        data["blanks"], data["blanks_v"] = find_blanks(img, zoom, grid, boxes + data["gap_boxes"]), BLANKS_V
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _cell_text(boxes):
    """单元格里的文字框 → 按行拼成段落。"""
    boxes = sorted(boxes, key=lambda b: ((b[1] + b[3]) / 2, b[0]))
    lines = []
    for b in boxes:
        cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1)
        if lines and abs(cy - lines[-1]["cy"]) < h * 0.5:
            lines[-1]["boxes"].append(b)
        else:
            lines.append({"cy": cy, "boxes": [b]})
    out = []
    for ln in lines:
        bs = sorted(ln["boxes"], key=lambda b: b[0])
        t = ""
        for i, b in enumerate(bs):
            if (i and b[0] - bs[i - 1][2] > 2.5 and not t.endswith(" ")
                    and not b[4].startswith(BLANK) and not bs[i - 1][4].startswith(BLANK)):
                t += " "
            t += b[4]
        out.append(t)
    return out


def page_rows(data):
    """一页 → 表格行列表，每行是 {列号: (文字行列表, 区域)}。"""
    if not data.get("grid"):
        return []
    hl, vl = data["grid"]
    boxes = data["boxes"] + data.get("gap_boxes", [])
    boxes += blank_boxes(data.get("blanks") or [], boxes)
    rows = []
    for r in range(len(hl) - 1):
        y0, y1 = hl[r], hl[r + 1]
        if y1 - y0 < 6:
            continue
        row = {}
        for c in range(len(vl) - 1):
            x0, x1 = vl[c], vl[c + 1]
            if x1 - x0 < 6:
                continue
            inside = [b for b in boxes
                      if x0 <= (b[0] + b[2]) / 2 <= x1 and y0 <= (b[1] + b[3]) / 2 <= y1
                      and b[5] >= 0.5 and not WATERMARK_RE.match(b[4].strip())]
            row[c] = (_cell_text(inside), [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
        rows.append(row)
    return rows


HEADER_RE = re.compile(r"^(序号|题号|编号|年份|来源|出处|题目|题干|图形|解析|答案解析|答案)\s*")
TITLE_RE = re.compile(r"千题册")
# 整格就是表头（“真题来源”“小红书：××解析”这类变体）
HEADER_FULL_RE = re.compile(r"^(序号|题号|编号|年份|(真题)?来源|出处|题目|题干|图形|答案|.{0,12}解析)$")


def strip_header(row):
    """表头没有和第一道题用横线隔开时，表头文字会并进第一道题的各个格子（“序号15”“年份2019年…”）。

    一行里有两个以上格子以表头词开头，就把这些表头词去掉；整行只有表头的变成空行。
    书名横幅（“图形推理千题册—乱序版”）也去掉。
    """
    full = {c for c, (lines, _r) in row.items() if lines and HEADER_FULL_RE.match(re.sub(r"\s+", "", "".join(lines)))}
    heads = [c for c, (lines, _r) in row.items() if lines and (c in full or HEADER_RE.match(lines[0]))]
    if len(heads) >= 2:
        for c in heads:
            lines, rect = row[c]
            if c in full:
                row[c] = ([], rect)
                continue
            first = HEADER_RE.sub("", lines[0], count=1).strip()
            row[c] = (([first] if first else []) + lines[1:], rect)
    for c, (lines, rect) in list(row.items()):
        if lines and TITLE_RE.search("".join(lines)) and len("".join(lines)) < 30:
            row[c] = ([], rect)
    return row


# ---------------------------------------------------------------- 列角色

SOURCE_RE = re.compile(r"^[（(]?\s*(20\d\d|19\d\d)\s*年?")


def detect_roles(rows):
    """统计每列内容特征，返回 {角色: 列号}。"""
    from collections import defaultdict

    stat = defaultdict(lambda: defaultdict(int))
    width = {}
    for row in rows:
        for c, (lines, rect) in row.items():
            width[c] = max(width.get(c, 0), rect[2] - rect[0])
            t = "".join(lines).strip()
            if not t:
                continue
            s = stat[c]
            s["n"] += 1
            s["len"] += len(t)
            if re.fullmatch(r"\d{1,4}", t):
                s["num"] += 1
            if re.fullmatch(r"[A-D]", t):
                s["ans"] += 1
            if SOURCE_RE.match(t) and len(t) < 30:
                s["src"] += 1
            if len(re.findall(r"(?<![A-Za-z])[A-D]\s*[.．、]", t)) >= 3:
                s["opt"] += 1
            if re.search(r"正确答案|当选|排除|故选", t):
                s["exp"] += 1
    roles = {}

    def best(key, thresh):
        cands = [(stat[c][key] / stat[c]["n"], c) for c in stat if stat[c]["n"] and c not in roles.values()]
        cands = [x for x in cands if x[0] >= thresh]
        return max(cands)[1] if cands else None

    for key, role, th in (("num", "num", 0.5), ("ans", "ans", 0.5), ("exp", "exp", 0.3), ("src", "src", 0.5)):
        c = best(key, th)
        if c is not None:
            roles[role] = c
    # 题目列：剩下的列里选项标记最多的，没有就选文字最多的；
    # 图形推理的“图形”列整列没有文字，这时选剩下最宽的那一列
    rest = [c for c in stat if c not in roles.values() and stat[c]["n"]]
    if rest:
        roles["q"] = max(rest, key=lambda c: (stat[c]["opt"] / stat[c]["n"], stat[c]["len"]))
    else:
        empty = [c for c in width if c not in roles.values() and width[c] > 60]
        if empty:
            roles["q"] = max(empty, key=lambda c: width[c])
    return roles


# ---------------------------------------------------------------- 拼题

CHOSEN_RE = re.compile(r"([A-D])\s*项[：:][^\n]*?当选")


def _chosen_in(explain):
    """解析没有“故正确答案为X”、只有逐项分析时，取写着“当选”的那一项。"""
    found = {m.group(1) for m in CHOSEN_RE.finditer(explain or "")}
    return found.pop() if len(found) == 1 else None


def _split_options(options, n, explain):
    """逻辑填空的选项每空一个词，OCR 常把词连成一串（“明显短缺基础性”）。按空数拆开。

    拆法打分：拆出来的词在解析里出现过（解析会逐个引用“B项"明显"”）加分，
    和别的选项同一位置的词一样长也加分。
    """
    from collections import Counter
    from itertools import combinations

    toks = [o.split() for o in options]
    if n < 2 or all(len(t) == n for t in toks):
        return options
    good = [t for t in toks if len(t) == n]
    mode = [Counter(len(t[i]) for t in good).most_common(1)[0][0] if good else 2 for i in range(n)]
    out = []
    for o, t in zip(options, toks):
        s = "".join(t)
        if len(t) >= n or len(s) < n or len(s) > 6 * n or not re.fullmatch(r"[一-鿿]+", s):
            out.append(o)
            continue
        fixed = {sum(len(x) for x in t[:k]) for k in range(1, len(t))}  # 已有的空格必须保留
        best = None
        for cuts in combinations(range(1, len(s)), n - 1):
            if not fixed <= set(cuts):
                continue
            parts = [s[a:b] for a, b in zip((0,) + cuts, cuts + (len(s),))]
            if any(len(p) > 5 for p in parts):
                continue
            score = sum((3 if re.search(f"[\"“”「]{p}[\"“”」]", explain) else 1 if p in explain else 0)
                        + (1 if len(p) == mode[i] else 0) for i, p in enumerate(parts))
            if best is None or score > best[0]:
                best = (score, parts)
        out.append(" ".join(best[1]) if best else o)
    return out


def _fix_markers(text):
    """OCR 把选项标记认走样：“c.”小写、“A412536”“D"低空…”丢了点。另外三个标记都好好的才补。"""
    text = re.sub(r"(?<![A-Za-z])([a-d])(?=\s*[.．、])", lambda m: m.group(1).upper(), text)
    have = [k for k in "ABCD" if OPT_RE[k].search(text)]
    if len(have) == 3:
        k = next(k for k in "ABCD" if k not in have)
        ms = list(OPT_LOOSE_RE[k].finditer(text))
        if not ms and k == "B":  # “B”认成了“8”
            a, c = OPT_RE["A"].search(text), OPT_RE["C"].search(text)
            m8 = re.search(r"(?:^|(?<=\s))8(?=\s*[.．、]?\s*[一-鿿])", text[a.end():c.start()], re.M) if a and c else None
            if m8:
                i = a.end() + m8.start()
                return text[:i] + "B." + text[i + 1:]
        if ms:
            i = ms[-1].end()
            text = text[:i] + "." + text[i:]
    return text


BRACKET_BLANK_RE = re.compile(r"(?<![是为])[（(][ 　]*[）)]")


def _blank_count(stem):
    """题干里几个空：横线“____”，有的书用“（ ）”。"""
    return stem.count(BLANK) or len(BRACKET_BLANK_RE.findall(stem))


def _fix_brackets(stem):
    """“（ ）”空 OCR 常只剩半边（“可以），”“企业(的发展”）：没配上对的括号补成“（ ）”，空括号也统一成“（ ）”。"""
    out = []
    for line in stem.split("\n"):
        chars = list(line)
        stack, orphans, pairs = [], [], []
        for i, ch in enumerate(chars):
            if ch in "（(":
                if stack:
                    orphans.append(stack.pop())  # 前一个左括号没等到右括号
                stack.append(i)
            elif ch in "）)":
                if stack:
                    pairs.append((stack.pop(), i))
                else:
                    orphans.append(i)
        orphans += stack
        for a, b in pairs:
            if not "".join(chars[a + 1:b]).strip(" 　"):
                chars[a], chars[b] = "（", "）"
                for k in range(a + 1, b):
                    chars[k] = ""
                chars[a] = "（ "
        for i in orphans:
            chars[i] = "（ ）"
        out.append(re.sub(r"（ ）[ \t　]+", "（ ）", "".join(chars)))
    return "\n".join(out)


CIRCLED = "①②③④⑤⑥⑦⑧⑨"


def _fix_order(stem, options):
    """语句排序题：OCR 常把①②…认成 1、2…，句子之间也连成一行（“长城文字砖5长城文字砖上…”）。

    选项都是序号串时，按序号个数在题干里依次找回每个序号：认对了的圆圈数字 > 行首数字 >
    夹在汉字中间的数字 > 汉字后面的数字（“619年” = ⑥ + “19年”）。找到的序号前面断行。
    """
    if not options:
        return stem, options
    opts = [re.sub(r"\s+", "", o) for o in options]
    if not all(re.fullmatch(r"[①-⑨1-9]{3,9}", o) for o in opts):
        return stem, options
    options = [re.sub(r"[1-9]", lambda m: CIRCLED[int(m.group()) - 1], o) for o in opts]
    n = max(len(o) for o in options)
    out, pos = stem, 0
    for k in range(1, n + 1):
        d = str(k)
        tiers = (re.compile(CIRCLED[k - 1]), re.compile(rf"(?:^|(?<=\n)){d}(?![\d.．、])"),
                 re.compile(rf"(?<=[一-鿿，。；：！？”\"）)、]){d}(?=[一-鿿“\"（(])(?![个句项])"),
                 re.compile(rf"(?<=[一-鿿，。；：！？”\"）)、]){d}(?![个句项.．、])"))
        m = None
        for t in tiers:
            m = t.search(out, pos)
            if m:
                break
        if not m:
            continue
        nl = "" if m.start() == 0 or out[m.start() - 1] == "\n" else "\n"
        out = out[:m.start()] + nl + CIRCLED[k - 1] + out[m.end():]
        pos = m.start() + len(nl) + 1
    # 末尾的问句接在最后一句后面
    out = re.sub(r"(?<=[^\n])(?=(将|把)(以上|上述|以下|下列|这)\S{0,4}(个|句|组)?.{0,6}(重新)?(排列|排序|组成))", "\n", out)
    out = re.sub(r"\n{2,}", "\n", out)
    return out, options


def _has_image(page, rect):
    """单元格里有没有嵌入的图片（文字版 PDF 里，部分解析是以图片形式贴进去的）。"""
    try:
        infos = page.get_image_info()
    except Exception:  # noqa: BLE001
        return False
    x0, y0, x1, y1 = rect
    for info in infos:
        bx0, by0, bx1, by1 = info["bbox"]
        if min(x1, bx1) - max(x0, bx0) > 10 and min(y1, by1) - max(y0, by0) > 10:
            return True
    return False


def parse_book(path, fid, scanned, progress=None, limit=None, figure=False):
    """解析一本题册。figure=True（图形推理）时，题目格即使没有文字也保留原图截图。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    doc = pymupdf.open(path)
    pages = []
    for pno in range(min(doc.page_count, limit or doc.page_count)):
        if progress:
            progress(pno, doc.page_count)
        try:
            data = analyze_page(fid, doc, pno, scanned)
        except Exception:  # noqa: BLE001 —— 个别坏页跳过
            continue
        pages.append((pno, [strip_header(r) for r in page_rows(data)]))
    sample = [r for _p, rows in pages[:40] for r in rows]
    roles = detect_roles(sample)
    if "num" not in roles or "q" not in roles:
        doc.close()
        return [], roles

    # 文字版里解析是图片的格子：单独 OCR 这一块（结果缓存，只识别一次）
    cell_cache_path = PAGES_DIR / fid / "cells.json"
    try:
        cell_cache = json.loads(cell_cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cell_cache = {}
    dirty = False

    def ocr_cell(pno, rect):
        nonlocal dirty
        key = f"{pno}:{','.join(str(v) for v in rect)}"
        if key not in cell_cache:
            if scanned or not ocr.available() or rect[3] - rect[1] < 15 or not _has_image(doc[pno], rect):
                return []
            try:
                boxes = [b for b in ocr.recognize_clip(doc[pno], rect) if b[5] >= 0.5]
            except Exception:  # noqa: BLE001
                return []
            cell_cache[key] = _cell_text(boxes)
            dirty = True
        return cell_cache[key]

    items = []
    cur = None
    for pno, rows in pages:
        for row in rows:
            def cell(role):
                c = roles.get(role)
                return row.get(c, ([], None)) if c is not None else ([], None)

            num_t = "".join(cell("num")[0]).strip()
            m = re.fullmatch(r"(\d{1,4})", num_t)
            q_lines, q_rect = cell("q")
            a_t = "".join(cell("ans")[0]).strip()
            # OCR 偶尔认不出很小的单个数字题号：答案格有字母、或题目以“(20xx年…)”开头，也算新的一题
            starts = bool(m) or (not num_t and (re.fullmatch(r"[A-D]", a_t) or
                                                (q_lines and re.match(r"^[（(]\s*(19|20)\d\d", q_lines[0]))))
            if not starts and not any(lines for lines, _r in row.values()):
                continue  # 空行、只有表头的行
            if starts:
                num = int(m.group(1)) if m else (cur["num"] + 1 if cur else 1)
                cur = {"num": num, "q": [], "src": [], "ans": "", "exp": [], "crop": [], "exp_crop": []}
                items.append(cur)
            elif cur is None:
                continue
            cur["q"] += q_lines
            if q_rect and (q_lines or (figure and starts)):
                cur["crop"].append([pno] + q_rect)
            cur["src"] += cell("src")[0]
            if re.fullmatch(r"[A-D]", a_t):
                cur["ans"] = a_t
            e_lines, e_rect = cell("exp")
            if not e_lines and e_rect:
                e_lines = ocr_cell(pno, e_rect)
            cur["exp"] += e_lines
            if e_rect and e_lines:
                cur["exp_crop"].append([pno] + e_rect)
    doc.close()
    if dirty:
        cell_cache_path.parent.mkdir(parents=True, exist_ok=True)
        cell_cache_path.write_text(json.dumps(cell_cache, ensure_ascii=False), encoding="utf-8")
    out = []
    for it in items:
        qtext = join_text(it["q"])
        origin = " ".join(it["src"]).strip()
        m = re.match(r"^\s*[（(]\s*((?:19|20)\d\d[^）)\n]{0,24})[）)]\s*", qtext)
        if m:
            origin = origin or m.group(1)
            qtext = qtext[m.end():]
        qtext = _fix_markers(qtext)
        parsed = _find_options(qtext)
        if not parsed and re.search(r"(?:^|\s)D\s*[.．、]?\s*$", qtext):
            # 原书 D 项只印了字母、内容没印出来（看原卷也一样缺），照样按文字题做
            parsed = _find_options(re.sub(r"D\s*([.．、]?)\s*$", r"D\1（原书缺此项内容）", qtext))
        stem, options = parsed if parsed else (qtext, None)
        stem, options = _fix_order(stem, options)
        explain = join_text(it["exp"]).strip()
        stem = re.sub(r"_{4,}", BLANK, stem)  # OCR 自己认出的“_”和找到的横线连在一起
        stem = re.sub(rf"[ \t]*({BLANK}[，。]?)[ \t]*", r"\1", stem)
        stem = re.sub(rf"({BLANK})[，。]([，。、；：！？,.])", r"\1\2", stem)  # OCR 也认出了标点，用 OCR 的
        # 问句接在文段后面时断开（只在空或句末标点后面断，“将下列词语依次填入”这类不拆）
        stem = re.sub(rf"(?<={BLANK})(?=依次填入|填入画横线)", "\n", stem)
        stem = re.sub(r"(?<=[。！？…”\"）)])(?=依次填入|填入画横线)", "\n", stem)
        if options and BLANK not in stem and "填入" in stem:
            stem = _fix_brackets(stem)
        nblank = _blank_count(stem)
        if options and nblank:
            options = _split_options(options, nblank, explain)
        letter = it["ans"] or _answer_in(explain) or _chosen_in(explain)
        # 来源格只取第一个“20xx年……”（防止续页的内容混进来）
        om = re.match(r"((?:19|20)\d\d年(?:(?!(?:19|20)\d\d).){0,16})", re.sub(r"\s+", "", origin))
        origin = om.group(1) if om else origin
        origin = re.sub(r"(题目|真题)?(来\s*源|年份)$", "", origin).strip()
        year = re.search(r"(19|20)\d\d", origin)
        out.append({
            "num": it["num"], "stem": stem.strip(), "options": options,
            "answer": LETTER_IDX.get(letter) if letter else None, "explain": explain,
            "origin": re.sub(r"[—\-－]\s*天明考公|天明考公", "", origin).strip(" -—"),
            "year": int(year.group(0)) if year else 0,
            "crop": it["crop"], "explain_crop": it["exp_crop"],
        })
    return out, roles


# ---------------------------------------------------------------- 选哪些文件

def _version(rel):
    vs = [float(v) for v in re.findall(r"(\d+\.\d)", rel)]
    return max(vs) if vs else 1.0


def discover(catalog_files):
    """在资料里找千题册的“答案版”（含题目、答案、解析）。

    文字版每个版本都收（同版本有顺序版就不收乱序版，题目一样）；扫描版每种题型只收最新的完整版 + 各次“新增”，同版本顺序版优先，
    特制放大、快速对题等重复排版的不收。
    """
    cands = []
    for f in catalog_files:
        rel = f["rel"]
        if f["ext"] != "pdf" or "千题册" not in rel or "答案" not in os.path.basename(rel):
            continue
        if re.search(r"特制|快速对题|纯答案|放大|横版|打印|无框|紧凑", rel):
            continue
        btype = next((t for t in BOOK_TYPES if t[0] in rel), None)
        if not btype:
            continue
        cands.append({**f, "btype": btype, "ver": _version(rel), "added": "新增" in rel,
                      "order": "乱序" if "乱序" in rel else "顺序"})
    picked = []
    for t in BOOK_TYPES:
        group = [c for c in cands if c["btype"] == t]
        texts = [c for c in group if c["text"]]
        for v in sorted({c["ver"] for c in texts}):
            same = [c for c in texts if c["ver"] == v]
            if any(c["order"] == "顺序" for c in same):
                same = [c for c in same if c["order"] == "顺序"]
            picked += same
        scanned = [c for c in group if not c["text"]]
        full = [c for c in scanned if not c["added"]]
        if full:
            top = max(c["ver"] for c in full)
            best = [c for c in full if c["ver"] == top]
            if any(c["order"] == "顺序" for c in best):
                best = [c for c in best if c["order"] == "顺序"]
            picked += best
        added = [c for c in scanned if c["added"]]
        for v in sorted({c["ver"] for c in added}):
            same = [c for c in added if c["ver"] == v]
            if any(c["order"] == "顺序" for c in same):
                same = [c for c in same if c["order"] == "顺序"]
            picked += same
    return picked


# ---------------------------------------------------------------- 汇总

def dedup_key(stem, explain=""):
    """题干的汉字指纹；题干几乎没有字（图形推理）时用解析开头代替。"""
    k = "".join(re.findall(r"[一-鿿]", stem or ""))
    if len(k) >= 12:
        return "s:" + k[:40]
    e = "".join(re.findall(r"[一-鿿]", explain or ""))
    return "e:" + e[:50] if len(e) >= 20 else None


def build_all(catalog_files, root, skip_keys=(), progress=None):
    """解析全部千题册，返回 (sources, questions)。文字版优先（文字更准），同一道题只留一份。"""
    picked = discover(catalog_files)
    picked.sort(key=lambda f: (not f["text"], -f["ver"]))
    seen = set(skip_keys)
    kept = {}  # 指纹 → 收下的那道题
    by_type = {}
    total_pages = sum(f["pages"] for f in picked) or 1
    done_pages = 0
    for f in picked:
        btype = f["btype"]

        def prog(i, n, f=f):
            if progress:
                progress(done_pages + i, total_pages, f["name"])

        try:
            items, _roles = parse_book(os.path.join(root, f["rel"]), f["id"], not f["text"], prog,
                                       figure=btype[2] == "图形推理")
        except Exception as e:  # noqa: BLE001
            print("题册解析失败", f["rel"], e)
            items = []
        done_pages += f["pages"]
        bucket = by_type.setdefault(btype[0], {"type": btype, "files": [], "qs": []})
        bucket["files"].append(f)
        used = set()
        for it in items:
            key = dedup_key(it["stem"], it["explain"])
            if key and key in seen:
                # 先收的那份没拆出选项（原书缺字、OCR 漏行），这份拆出来了：换成这份
                old = kept.get(key)
                def whole(opts):
                    return bool(opts) and not any("原书缺此项" in o for o in opts)

                if not (old and not whole(old["options"]) and whole(it["options"]) and btype[2] != "图形推理"):
                    continue
            if key:
                seen.add(key)
            qid = f"qc-{f['id']}-{it['num']:04d}"
            while qid in used:
                qid += "b"
            used.add(qid)
            # 扫描版填空题：找到了横线就按文字显示，找不到才只能看原卷截图
            fig = btype[2] == "图形推理" or (not f["text"] and btype[2] == "逻辑填空"
                                         and (not _blank_count(it["stem"]) or not it["options"]))
            q = {
                "id": qid, "num": it["num"], "module": btype[1], "sub": btype[2],
                "stem": it["stem"], "options": it["options"], "answer": it["answer"], "explain": it["explain"],
                "crop": it["crop"], "explain_crop": it["explain_crop"], "fig": fig,
                "year": it["year"], "origin": it["origin"], "src": "千题册", "fid": f["id"],
            }
            if key in kept:
                prev = kept[key]
                prev_bucket = by_type[prev["_type"]]["qs"]
                prev_bucket[prev_bucket.index(prev)] = q
                q["_type"] = prev["_type"]
            else:
                bucket["qs"].append(q)
                q["_type"] = btype[0]
            if key:
                kept[key] = q
    sources, questions = [], []
    for name, b in by_type.items():
        sid = "book-" + name
        qs = b["qs"]
        # 新题在前：按年份倒序，同年保持原书顺序
        qs.sort(key=lambda q: -(q["year"] or 0))
        for q in qs:
            q["source"] = sid
            q.pop("_type", None)
        newest = max(b["files"], key=lambda f: (f["ver"], f["text"]))
        sources.append({
            "id": sid, "title": f"{name}千题册", "exam": "千题册", "module": b["type"][1], "sub": b["type"][2],
            "file": newest["rel"], "fid": newest["id"], "count": len(qs),
            "answered": sum(1 for q in qs if q["answer"] is not None),
            "modules": {b["type"][1]: len(qs)},
            "year": max((q["year"] for q in qs), default=0),
            "note": "合并自 " + "、".join(sorted({f"{f['ver']:g}版" + ("（扫描）" if not f["text"] else "") for f in b["files"]})),
        })
        questions += qs
    return sources, questions
