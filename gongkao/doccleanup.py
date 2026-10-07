"""资料库文档的收尾清理（docs.save 在拼题之前调用）。

逐份看过全部资料后归纳出来的几类残渣：
- 图表、插图里认出的零碎字：坐标轴刻度（“250”“2012 2013 2014”）、单位（“亿元”“GWh”）、图注（“图2”“A B”）、
  页码（“-454-”“II”）、只有标点的行（“ “ “ ”），以及整块都是数字的统计图（“350000 332316 / 300931 …”）；
- 机构水印、推广语（“新途径资料库”“获取更多备考资料”“专业时政及公考事业题库网”“抖音关注追梦人超哥”…），
  以及在很多页上反复出现的单个水印字（“注”“理”）；
- 课件逐页重复的材料段落（一页讲一个选项，材料每页印一遍）；
- 分课讲义每份开头带着上一课的结尾、末尾带着下一课的开头。
另外 content/doc_fixes.json 里放逐份核对过的校正（手写笔记 OCR 错字、某份资料特有的残片）。
"""

import json
import re
from collections import Counter, defaultdict

from .paths import resource_dir

CJK_RE = re.compile(r"[一-鿿]")

# 整行就是水印、推广语、封面装饰（去掉空白后整行匹配）
BRAND_LINE_RE = re.compile(
    r"(?:Q|X)?新途[径泾]资料库(?:，海量资料助你上岸！?.*)?|(?:\S{0,6})?获取更多备考资料|全新教研[|｜]?紧贴大纲.*"
    r"|因为专注[，,]?所以专业|我负责专注[，,]?你负责上岸|高效实用·?通关必备！?|本资料来自必过.*|.*抖音关注追梦人超哥.*"
    r"|仅供超格内部学员使用|追梦人超哥编|粉笔公考·?官方微信|服务电话[：:][\d\-]+|讲师[：:]华图在线|学员专用讲义"
    r"|中公学员·?培训讲义|内部资料仅供参考|严禁外传违者必究|万份资料|免费领取|袁东老师(?:微信号?)?[：:]?.*|袁东Yuan.*"
    r"|[：:]?\s*Y?u?an?d?o?n?g?2234[：:]?|(?:dong|long|ong|ng|g)2234|上岸考资|klsa\d*.*|时政通网免费"
    r"|专?业?时?政?及?公考事[业亚重]?题?库?[网区]?|业?时政及?公?考?事?业?|政及公考事业题库网|业时政?|业时"
    r"|s?h?i?z?h?e?n?g?\.?\s*(?:ton|tong)?\.?\s*cn|shizh(?:eng?)?|izheng|ngton|zheng(?:tong)?"
    r"|C\s*H\s*A\s*O\s*G\s*E\s*J\s*I\s*A\s*O\s*Y\s*U|G超格|超格教育|四?海教育|版权声明[：:].*|您可以自由下载.*|编\s*著"
    r"|幻灯片编号\s*\d+|逢考|上岸|可口|口|码关注?|扫码关注|日码关注|更多资料请关注.*|.*橙子考公?资料站.*|状元笔记|mR公万"
    r"|步知公考|G\.BUZHI\.COM|公考核心十三册|时政公考|追梦人超哥|空白页面"
)

# 行里夹着的水印残片：去掉残片，留下正文
INLINE_WM_RE = re.compile(
    r"专业时政及公考事[业亚重]?题?库?[网区]?|政及公考事业题库网?|时政通网免费|shizhengtong\.\s*cn|ztong\.cn"
    r"|G超格教育\s*[「|｜I]?\s*抖音关注追梦人超哥，?听预测课|抖音关注追梦人超哥，?听预测课\s*[|｜「I]?\s*G超格教育"
    r"|本资料来自必过网?考?试?论?坛?[：:]?[！!『]?|【\s*考?资料站[^】]{0,6}】|(?:考资料)?站?更新\*\s*[)）]"
    r"|袁东老师微信号?[：:]?|Yuandong2234|上岸考资微信号公众"
)

# 分课讲义每份的课头：“申论 精讲精练10”“言语理解与表达 精讲精练2”
LESSON_HEAD_RE = re.compile(r"精讲精练\s*[-－]?\s*(\d{1,2})")

# 图注、刻度、页码、单独的标点
NUM_ONLY_RE = re.compile(r"[-–—~～\s\d.%％‰°/]*\d[-–—~～\s\d.%％‰°/]*")  # 不含逗号、顿号：数字推理的数列是题干
ROMAN_RE = re.compile(r"[IVXⅠⅡⅢⅣⅤ][IVXⅠⅡⅢⅣⅤ\s]{0,15}")  # 不能写成 (…{1,4}\s*)+：长串 I 会回溯到卡死
FIG_LABEL_RE = re.compile(r"(?:图\s*\d{1,2}[\s、，,]*)+|[A-Za-z](?:\s*[A-Za-z]){0,3}|[A-H][.．、]|\?|？")
UNIT_RE = re.compile(r"[（(]?(?:亿元|万元|千元|元|万人|万户|万吨|吨|亿美元|万辆|辆|件|个|家|公里|千米|GWh|MWh|%|‰|"
                     r"亿千瓦时|万千瓦|亿立方米|万公顷|亿件|万件|亿户|亿GB|万亩)[)）]?(?:\s+(?:亿元|万元|元|%|万人|万吨|亿美元|万公顷))?")
PUNCT_ONLY_RE = re.compile(r"[\s\W_]+")
LABEL_LIKE_RE = re.compile(r"【|】|^例\s*\d|[：:]$|^\d+题$|^\(?\d+\)?$|^[A-H]\s*[.．、]\s*\S")  # 选项“B.3”不是残片
# 只在很多页上反复出现的两字水印才去掉（“区分”“事迹”这类反复出现的小标题是正文，不动）
WM_WORDS = {"整理", "央视", "新闻", "码关", "关注", "业时", "时政", "教育", "逢考", "上岸", "可口", "编著", "公考", "粉笔", "扫码", "码"}


def _fixes():
    path = resource_dir() / "content" / "doc_fixes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fix_for(f):
    """content/doc_fixes.json 里按资料名（不含扩展名）登记的逐份校正。"""
    name = f.get("name") or ""
    fixes = _fixes()
    return fixes.get(name) or fixes.get(f.get("id") or "") or {}


def _texts(b):
    return b.get("t") or ""


def _map_text(b, fn):
    """对块里所有文字（正文、框线、提纲、表格）做同一处理。"""
    b = dict(b)
    if b.get("t"):
        b["t"] = fn(b["t"])
    d = b.get("d")
    if d:
        d = dict(d)
        if d.get("lines"):
            d["lines"] = [[fn(x), a] for x, a in d["lines"]]
        if d.get("items"):
            d["items"] = [[a, fn(x)] for a, x in d["items"]]
        if d.get("rows"):
            d["rows"] = [[fn(c or "") for c in r] for r in d["rows"]]
        b["d"] = d
    return b


def apply_fixes(blocks, f):
    """逐份校正：replace 文字替换（手写笔记的 OCR 错字），drop 整块去掉的正则，not_head 改回正文的标题，
    head 改成标题的正文，levels [[正则, 级别]] 统一标题级别（OCR 按字号猜的级别常常乱跳）。"""
    fix = _fix_for(f)
    if not fix:
        return blocks
    reps = fix.get("replace") or []
    drops = [re.compile(x) for x in fix.get("drop") or []]
    demote = [re.compile(x) for x in fix.get("not_head") or []]
    promote = [re.compile(x) for x in fix.get("head") or []]
    levels = [(re.compile(x), lv) for x, lv in fix.get("levels") or []]

    def rep(t):
        for a, z in reps:
            t = t.replace(a, z)
        return t

    out = []
    for b in blocks:
        if reps:
            b = _map_text(b, rep)
        t = _texts(b).strip()
        if b["k"] in ("p", "h", "box", "tree", "tbl") and any(rx.search(t) for rx in drops):
            continue
        if b["k"] == "h" and any(rx.search(t) for rx in demote):
            b = dict(b, k="p")
            b.pop("lv", None)
        elif b["k"] == "p" and any(rx.fullmatch(t) for rx in promote):
            b = dict(b, k="h", lv=b.get("lv") or 2)
        if b["k"] in ("p", "h") and len(t) <= 40:
            lv = next((lv for rx, lv in levels if rx.fullmatch(t)), None)
            if lv:
                b = dict(b, k="h", lv=lv)
        out.append(b)
    return out


def _is_noise_line(t):
    """无论在哪儿都没意义的零碎行。"""
    s = t.strip()
    if not s:
        return True
    if BRAND_LINE_RE.fullmatch(re.sub(r"\s+", "", s)) or BRAND_LINE_RE.fullmatch(s):
        return True
    if len(s) <= 24 and NUM_ONLY_RE.fullmatch(s):
        return True
    if PUNCT_ONLY_RE.fullmatch(s) and not re.search(r"[①-⑳]", s):
        return True
    if len(s) <= 24 and (ROMAN_RE.fullmatch(s) or FIG_LABEL_RE.fullmatch(s) or UNIT_RE.fullmatch(s)):
        return True
    return False


def _is_fragment(t):
    """很短、几乎没有汉字的零碎（“0上”“外”“QQO”“十☆O”）：前后也是零碎时才当残片。"""
    s = t.strip()
    return len(s) <= 4 and len(CJK_RE.findall(s)) <= 1 and not LABEL_LIKE_RE.search(s)


def _numeric_soup(t):
    """整块几乎全是数字的统计图（柱状图、折线图认出的刻度和数值）。"""
    cjk = len(CJK_RE.findall(t))
    toks = [x for x in re.split(r"[\s/　]+", t) if x]
    if not toks or cjk > 6:
        return False
    num = sum(1 for x in toks if re.fullmatch(r"[-–]?[\d.,%％()（）:：]+(?:年|月|日|季度)?|口?\d{4}年|[%％]", x))
    if num >= max(3, len(toks) * 0.6):
        return True
    # 粘成一串的年份 / 刻度轴：“2009年2010年2011年……”“%35.0038.22 38.62 …”
    flat = re.sub(r"\s", "", t)
    return bool(re.fullmatch(r"(?:\d{1,4}(?:年|月|季度)[~～\-—/]?){3,}", flat)) or (
        cjk <= 3 and len(re.findall(r"\d", flat)) >= max(12, len(flat) * 0.6))


def drop_noise(blocks):
    blocks = [_map_text(b, lambda t: INLINE_WM_RE.sub("", t).strip()) if INLINE_WM_RE.search(_texts(b)) else b
              for b in blocks]
    # 在很多页上出现的单字 / 两字水印
    pages = defaultdict(set)
    for b in blocks:
        if b["k"] in ("p", "h"):
            s = re.sub(r"\s", "", _texts(b))
            if s and len(s) <= 3:
                pages[s].add(b.get("pg", 0))
    wm = {s for s, ps in pages.items() if len(ps) >= 3 and (
        (len(CJK_RE.findall(s)) == 1 and len(s) == 1) or s in WM_WORDS)}
    keep = []
    n = len(blocks)
    for i, b in enumerate(blocks):
        k = b["k"]
        t = _texts(b)
        if k in ("p", "h"):
            s = re.sub(r"\s", "", t)
            # 数字推理的题干（“2 6 12 20 30 （ ）”）也几乎全是数字：带空括号、问号、横线的不当统计图
            blank = re.search(r"[（(]\s*[）)]|[?？]|_{2,}|[⦅⁄×÷=＝≈]|^\s*[【\[]?\s*(?:例|练习|拓展)", t)  # 速算例题“【例3】⦅1660⁄3480⦆”
            blank = blank or re.match(r"\s*\d{1,3}\s*(?:、|[.．](?!\d))", t) or re.search(r"\d\s*[,，、]\s*\d+\s*[,，、]\s*\d", t)  # 数字推理题干“9、1526,4769,2154,…”
            prev_opt = next((re.findall(r"(?<![A-Za-z])([A-H])\s*[.．、]", _texts(blocks[j]))[-1]
                             for j in range(i - 1, max(-1, i - 4), -1)
                             if re.match(r"\s*[A-H]\s*[.．、]", _texts(blocks[j]))), None)
            next_opt = next((m.group(1) for j in range(i + 1, min(n, i + 3))
                             if (m := re.match(r"\s*([A-H])\s*[.．、]", _texts(blocks[j])))), None)
            if re.fullmatch(r"[A-H]{1,4}", s) and prev_opt and not (next_opt and ord(next_opt) == ord(prev_opt) + 1):
                # 选项夹在中间的单个字母是 OCR 拆开的选项号（“B.21 / A / C.70√2”：前后选项接着排），不算答案；
                # 下一题从 A 重新开始的（“D.…… / D / 2.题干 / A.……”）是答案
                keep.append(b)  # 选项下面单独一行的“B”是答案（课件下一页揭晓），不是图注字母
                continue
            if s in wm or _is_noise_line(t) or (k == "p" and not blank and not re.match(r"\s*[A-H]\s*[.．、]", t)
                                                and _numeric_soup(t)):
                continue
            if _is_fragment(t):
                nb = [blocks[j] for j in (i - 1, i + 1) if 0 <= j < n and blocks[j]["k"] in ("p", "h", "img")]
                if any(x["k"] == "img" or _is_fragment(_texts(x)) or _is_noise_line(_texts(x)) for x in nb):
                    continue
        elif k in ("box", "tree") and (_numeric_soup(t) or not CJK_RE.search(t) and len(t) < 80):
            continue
        elif k == "tbl" and len(CJK_RE.findall(t)) <= 2 and _numeric_soup(t):
            continue
        keep.append(b)
    return keep


NOT_HEAD_RE = re.compile(r"^\d\s*[.．、]\s*对应讲义|^(?:\d\s*[.．、]\s*)?(?:课程内容|重点内容)[：:]|^学习任务[：:]")


def demote_heads(blocks):
    """被当成标题的说明行（“2.对应讲义：第464～470页”）改回正文；“华图点拨M”这类栏目名去掉 OCR 带上的尾巴。"""
    out = []
    for b in blocks:
        t = _texts(b)
        if b["k"] == "h" and NOT_HEAD_RE.search(t.strip()):
            b = dict(b, k="p")
            b.pop("lv", None)
        if b["k"] in ("p", "h") and re.fullmatch(r"\s*华图点拨\s*[MW]?\s*", t):
            b = dict(b, t="华图点拨")
        out.append(b)
    return out


QUESTIONISH_RE = re.compile(r"[（(]\s*[）)]|_{2,}|^\s*(?:\d{1,3}\s*[.．、]|[（(【]?\s*(?:例|练习)|[（(]\d{4}|[A-H]\s*[.．、])")


ANSWERISH_RE = re.compile(r"\s*[【\[]?\s*(?:解\s*析|答\s*案|正确答案|参考答案)")  # 同一道题印两遍，两遍各带解析：解析也不去


def dedupe_repeats(blocks):
    """课件一页讲一个选项，材料段落每页印一遍：同样的长材料段、表格只留第一次。
    题干、选项不去：同一道题印两遍时，后一遍往往带着答案和解析。"""
    seen = set()
    out = []
    for b in blocks:
        if b["k"] in ("p", "box", "tbl") and not (b["k"] != "tbl" and (QUESTIONISH_RE.search(_texts(b)) or ANSWERISH_RE.match(_texts(b)))):
            key = re.sub(r"[\s\W_]", "", _texts(b))
            if len(key) >= 80 or (b["k"] == "tbl" and len(key) >= 12):
                if key in seen:
                    continue
                seen.add(key)
        out.append(b)
    return out


GROUP_RE = re.compile(r"第[一二三四五六七八九十百零\d]+组")
PART_RE = re.compile(r"[一-鿿]{2,6}部分")  # 表格里单独一行的“实词部分”


def _tbl(b, rows):
    """换成新的行；只有表头、底下全空的栏（“打卡”）去掉。"""
    width = max(map(len, rows))
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any((r[j] or "").strip() for r in rows[1:])]
    if keep and len(keep) < width:
        rows = [[r[j] for j in keep] for r in rows]
    return dict(b, d=dict(b["d"], rows=rows), t=" ".join(" ".join(r) for r in rows))


PAGE_NO_RE = re.compile(r"第\s*\d{1,3}\s*页|\d{1,3}\s*/\s*\d{1,3}")


def tidy_tables(blocks, name):
    """表格：去掉每页表头上印的资料名、页码行和整列空白（“打卡”栏）；同一页上被另一张表包含的残表去掉；
    页面上单独认出来的、和表格里某格一模一样的短词（“审慎”“化为乌有”）和“第7页”去掉；
    按“第一组：××”分组的词表拆成一组一张表，组名做标题。"""
    title = re.sub(r"[\s()（）【】]", "", name or "")
    key = lambda t: re.sub(r"[\s()（）【】]", "", t or "")  # noqa: E731
    lone = lambda r: [key(c) for c in r if key(c)]  # noqa: E731
    cellset = lambda b: {key(c) for r in b["d"]["rows"] for c in r if key(c)}  # noqa: E731
    # 每页表格顶上都印的那一格（“花生十三800词(记忆版）”）
    tops = Counter(lone(r)[0] for b in blocks if b["k"] == "tbl" for r in (b.get("d") or {}).get("rows", [])[:3]
                   if len(lone(r)) == 1)
    ntbl = sum(1 for b in blocks if b["k"] == "tbl")
    running = {t for t, n in tops.items() if n >= max(4, ntbl * 0.3) and not re.match(r"[表图]\s*\d", t)}
    out = []
    for b in blocks:
        if b["k"] == "tbl" and (b.get("d") or {}).get("rows"):
            rows = [r for r in b["d"]["rows"]
                    if not (len(lone(r)) == 1 and (
                        (c := lone(r)[0]) == title or (len(c) >= 6 and c in title) or c in running
                        or PAGE_NO_RE.fullmatch(c) or c.isdigit()))]
            if not rows:
                continue
            b = _tbl(b, rows)
        out.append(b)

    cells = defaultdict(set)
    for b in out:
        if b["k"] == "tbl":
            cells[b.get("pg")] |= cellset(b)
    kept = []
    for i, b in enumerate(out):
        t = key(b.get("t"))
        if b["k"] in ("h", "p") and (PAGE_NO_RE.fullmatch(t) or (len(t) <= 8 and t in cells.get(b.get("pg"), ()))):
            continue
        if b["k"] == "tbl":
            mine = cellset(b)
            rank = lambda j, cs: (max(map(len, out[j]["d"]["rows"])), len(cs), -j)  # noqa: E731

            def covers(j):  # 另一张表里都有（OCR 把一格拆成两半的也算）
                theirs = cellset(out[j])
                text = "|".join(theirs)
                missing = sum(1 for c in mine - theirs if c not in text)
                return missing <= max(1, len(mine) * 0.1) and rank(j, theirs) > rank(i, mine)
            if any(j != i and o["k"] == "tbl" and o.get("pg") == b.get("pg") and covers(j) for j, o in enumerate(out)):
                continue
        kept.append(b)

    res = []
    for b in kept:
        rows = b["d"]["rows"] if b["k"] == "tbl" else []
        starts = [i for i, r in enumerate(rows) if GROUP_RE.match((r[0] or "").strip())
                  or (len(lone(r)) == 1 and PART_RE.fullmatch(lone(r)[0]))]
        if not starts:
            res.append(b)
            continue
        top = lone(rows[0])
        head = rows[:1] if starts[0] >= 1 and len(top) >= 2 and max(map(len, top)) <= 4 else []
        if starts[0] > len(head):
            res.append(_tbl(b, head + rows[len(head):starts[0]]))  # 接着上一页的那一组
        for i, j in zip(starts, starts[1:] + [len(rows)]):
            part = len(lone(rows[i])) == 1 and PART_RE.fullmatch(lone(rows[i])[0])
            res.append({"k": "h", "lv": 1 if part else 2, "pg": b.get("pg"),
                        "t": lone(rows[i])[0] if part else re.sub(r"\s+", "", rows[i][0])})
            body = rows[i + 1:j] if part else [[""] + list(rows[i][1:])] + rows[i + 1:j]
            if body:
                res.append(_tbl(b, head + body))
    return res


def trim_lesson(blocks):
    """分课讲义（“申论 精讲精练10”）：PDF 是按页切的，开头常带着上一课的最后一页、末尾带着下一课的第一页。
    只保留本课课头到下一课课头之间的内容（课头在开头 15% 内、下一课课头在末尾 30% 内才动）。"""
    n = len(blocks)
    heads = [(i, int(m.group(1))) for i, b in enumerate(blocks) if b["k"] in ("h", "p")
             and len(_texts(b)) <= 30 and (m := LESSON_HEAD_RE.search(_texts(b)))]
    if not heads or n < 10 or len({k for _i, k in heads}) > 2:
        return blocks  # 好几课合订在一起的不动
    start, num = heads[0]
    if start > max(3, n * 0.15):
        return blocks
    end = n
    for i, k in heads[1:]:
        if k != num and i >= n * 0.7:
            end = i
            break
    # 课头前面那条“第一章 …”这类章名是本课的，留着
    while start > 0 and blocks[start - 1]["k"] == "h" and blocks[start - 1].get("pg") == blocks[start].get("pg"):
        start -= 1
    return blocks[start:end]


def drop_title_repeats(blocks, name):
    """每页页眉都印一遍的资料名（OCR 认成标题）：只留开头那一次。"""
    key = lambda t: re.sub(r"[\s()（）【】《》]", "", t or "")  # noqa: E731
    title = key(name)
    if len(title) < 4:
        return blocks
    seen, out = False, []
    for i, b in enumerate(blocks):
        if b["k"] in ("h", "p") and key(b.get("t")) == title:
            if seen or i > 2:
                continue
            seen = True
        out.append(b)
    return out


SHENLUN_HEADS = [
    (re.compile(r"[（(]\d{1,2}[）)][一-鿿、]{2,12}类[。.]?"), 2),  # （2）经验启示类。
    (re.compile(r"[①-⑩][一-鿿]{2,8}[。.]?"), 3),  # ①题型识别。
    (re.compile(r"【例\s*\d{0,2}】\s*[（(][^）)]{2,20}[）)]"), 3),  # 【例1】（2022广西A）：一整套题的开头
]


def shenlun_examples(blocks):
    """申论讲义里的题型小节和单独一行的套题开头当小标题进目录（行测资料不动，那里“【例1】”是题号）。"""
    out = []
    for b in blocks:
        t = (b.get("t") or "").strip()
        lv = next((lv for rx, lv in SHENLUN_HEADS if rx.fullmatch(t)), None) if b["k"] == "p" else None
        out.append(dict(b, k="h", lv=lv) if lv else b)
    return out


PRINT_AD_RE = re.compile(r"网上打印店|彩色黑白同价|刺猬云印|\d+\s*分\s*/\s*页")


def drop_print_ads(blocks):
    """打印店夹在讲义里的广告页（“刺猬云印·网上打印店 / 彩色黑白同价 / 5分/页 / 刺猬 / 云印 / 百单”）：
    那一页的广告行和零碎短字都去掉。"""
    pages = {b.get("pg") for b in blocks if b["k"] in ("p", "h", "box") and PRINT_AD_RE.search(b.get("t") or "")}
    if not pages:
        return blocks
    return [b for b in blocks if not (b.get("pg") in pages and b["k"] in ("p", "h", "box")
                                      and (PRINT_AD_RE.search(b.get("t") or "") or len((b.get("t") or "").strip()) <= 8))]


def clean(blocks, f):
    blocks = drop_print_ads(blocks)
    blocks = drop_title_repeats(blocks, f.get("name") or "")
    blocks = apply_fixes(blocks, f)
    blocks = demote_heads(drop_noise(blocks))
    blocks = dedupe_repeats(tidy_tables(blocks, f.get("name") or ""))
    if LESSON_HEAD_RE.search(f.get("name") or "") or re.search(r"^(资料|数量)\d+$", f.get("name") or ""):
        blocks = trim_lesson(blocks)
    if "申论" in (f.get("name") or ""):
        blocks = shenlun_examples(blocks)
    return blocks
