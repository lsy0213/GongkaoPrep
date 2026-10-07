"""把资料目录里的《新速算》练习册（答案版 PDF）整理成速算题库 content/speed_bank.json。

每期 5 页：①两位×一位 40 组 + 两位数加减 20 组（答案页）；②三位数加减 / 多位数÷两位（商首位）/
多位数÷三位（商前两位）各 20 组（答案页，页尾附第③页的选项答案）；③四位数除法 20 题，四选一。
只读答案版：按坐标把文字拼成表格行，逐行用算式校验，对不上的行丢掉。

用法：python tools/build_speed.py [速算目录]
"""

import glob
import json
import os
import re
import sys
from collections import defaultdict

import pymupdf

SRC = sys.argv[1] if len(sys.argv) > 1 else r"E:\aaaaaaaa\gongkao\速算"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "speed_bank.json")
NUM = re.compile(r"^-?\d+(\.\d+)?$")


def ocr_words(page):
    """有几期的数字是矢量图形（没有文字层），只能识别。一个框里有多个数时按字符宽度切开。"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gongkao import ocr

    out = []
    for x0, y0, x1, y1, text, _ in ocr.recognize(ocr.page_image(page, 3.0), 3.0):
        parts = text.replace("一", "-").split()
        cw = (x1 - x0) / max(1, len(text))
        pos = 0
        for t in parts:
            i = text.find(t, pos)
            out.append((x0 + i * cw, y0, x0 + (i + len(t)) * cw, y1, t))
            pos = i + len(t)
    # “1. 36” 这样被拆开的小数拼回去
    merged = []
    for w in out:
        if merged and merged[-1][4].endswith(".") and abs(merged[-1][1] - w[1]) < 3:
            p = merged.pop()
            w = (p[0], p[1], w[2], w[3], p[4] + w[4])
        merged.append(w)
    return merged


def rows(page):
    """按纵坐标把单词聚成行，行内按横坐标排序。"""
    words = page.get_text("words")
    if sum(bool(re.fullmatch(r"-?\d{2,}", w[4])) for w in words) < 30 and len(page.get_drawings()) > 300:
        words = ocr_words(page)
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    out, cur, y = [], [], None
    for w in words:
        cy = (w[1] + w[3]) / 2
        if y is not None and abs(cy - y) > 3:
            out.append(cur)
            cur = []
        cur.append(w)
        y = cy if not cur[:-1] else y
    if cur:
        out.append(cur)
    return [[w[4] for w in sorted(r, key=lambda w: w[0])] for r in out]


def first_digits(a, b, n):
    return str(a // b)[:n]


def parse_day(pages):
    """一期的几页 → 各题型条目。pages: [(rows, text)]"""
    got = defaultdict(list)
    opts, letters = [], []
    for rs, text in pages:
        for r in rs:
            if all(re.fullmatch(r"[ABCD]", t) for t in r) and len(r) >= 5:
                letters += r
                continue
            if not r or not all(NUM.match(t) for t in r):
                continue
            # 行首是题号（1–20）；识别出来的页偶尔漏认题号，靠后面的算式校验兜底
            v = r[1:] if len(r) in (7, 11) and r[0].isdigit() and 1 <= int(r[0]) <= 20 else r
            if len(v) == 10 and "." not in "".join(v):
                # 一行三组题，每组单独校验
                if "乘法" in text:
                    if g := fix(v[0:3], lambda a, b, p: a * b == p and b < 10):
                        got["m21"].append(g[:2])
                    if g := fix(v[3:6], lambda a, b, p: a * b == p and b < 10):
                        got["m21"].append(g[:2])
                    if g := fix(v[6:10], lambda a, b, s, m: a + b == s and a - b == m):
                        got["as2"] += [[g[0], g[1], 1], [g[0], g[1], -1]]
                else:
                    if g := fix(v[0:4], lambda a, b, s, m: a + b == s and a - b == m):
                        got["as3"] += [[g[0], g[1], 1], [g[0], g[1], -1]]
                    if g := fix(v[4:7], lambda a, b, q: first_digits(a, b, 1) == str(q)):
                        got["d2"].append(g[:2])
                    if g := fix(v[7:10], lambda a, b, q: first_digits(a, b, 2) == str(q)):
                        got["d3"].append(g[:2])
                continue
            if len(v) == 6 and v[0].isdigit() and v[1].isdigit() and sum("." in t for t in v[2:]) >= 3:
                # 个别选项印成了“78”（漏了“0.”）：按其他选项的整数部分补上
                ref = next(t for t in v[2:] if "." in t).split(".")[0]
                opts.append([int(v[0]), int(v[1])] + [t if "." in t else f"{ref}.{t}" for t in v[2:]])
    if len(opts) == 20 and len(letters) >= 20:
        for o, L in zip(opts, letters[:20]):
            # 最接近真实值的选项应当就是册子给的答案；对不上说明识别错了，这题不要
            near = min(range(4), key=lambda i: abs(float(o[2 + i]) - o[0] / o[1]))
            if near == "ABCD".index(L):
                got["d4"].append(o + [near])
            else:
                got["_d4_mismatch"].append(o)
    return got


def fix(vals, check):
    """校验一组数；不通过时试着把某一位的 6/9 互换（识别常把这两个认反），返回通过的那组或 None。"""
    x = [int(t) for t in vals]
    if check(*x):
        return x
    for i, t in enumerate(vals):
        for j, ch in enumerate(t):
            if ch in "69":
                y = list(x)
                y[i] = int(t[:j] + "96"["69".index(ch)] + t[j + 1:])
                if check(*y):
                    return y
    return None


def main():
    files = sorted(f for f in glob.glob(os.path.join(SRC, "*.pdf")) if "答案" in os.path.basename(f) and "无" not in os.path.basename(f))
    days = {}
    for f in files:
        doc = pymupdf.open(f)
        cur, buf = None, defaultdict(list)
        lo, hi = map(int, re.search(r"(\d{4})\s*-\s*(\d{4})", os.path.basename(f)).groups())
        for p in doc:
            text = p.get_text()
            m = re.search(r"练习\s*(1\d{3})", text)
            if m:
                cur = int(m.group(1))
                # 页眉期号偶有笔误（1140 印成 1040），按文件名的期号范围纠正
                if not lo <= cur <= hi:
                    cur = next((c for c in (cur + 100, cur - 100, cur + 10, cur - 10) if lo <= c <= hi), cur)
            if cur:
                buf[cur].append((rows(p), text))
        for d, pages in buf.items():
            if d not in days:
                days[d] = parse_day(pages)
    bank = {k: [] for k in ("m21", "as2", "as3", "d2", "d3", "d4")}
    index = {k: [] for k in bank}
    short, mism = [], 0
    for d in sorted(days):
        g = days[d]
        mism += len(g.get("_d4_mismatch", []))
        for k in bank:
            index[k].append([d, len(bank[k])])
            bank[k] += g.get(k, [])
        want = {"m21": 40, "as2": 40, "as3": 40, "d2": 20, "d3": 20, "d4": 20}
        miss = {k: want[k] - len(g.get(k, [])) for k in want if len(g.get(k, [])) != want[k]}
        if miss:
            short.append((d, miss))
    out = {
        "source": f"新速算 {min(days)}–{max(days)}（{len(days)} 期）",
        "kinds": {k: {"items": bank[k], "days": index[k]} for k in bank},
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, separators=(",", ":"))
    print(out["source"], {k: len(v) for k, v in bank.items()}, f"{os.path.getsize(OUT) / 1e6:.1f} MB")
    print("选项答案与计算不符：", mism)
    print("不完整的期：", len(short), [(d, sorted(m)) for d, m in short])


if __name__ == "__main__":
    main()
