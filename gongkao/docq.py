"""资料里的例题：把“题干 + 插图 + A/B/C/D 选项 + 答案 + 解析”这一串块并成一个可以作答的题块（kind = q）。

答案的来源，按可靠程度：
1. 题后紧跟的“正确答案：D”“【答案】D”，或解析里的“因此，选择 D 选项”；
2. 讲义里集中给的答案框“答案：1-5:BBDDC 6-7:CC”（按例题编号对回去，答案框本身不再显示）；
3. 纯计算题（如 23.2÷24.8%=）由软件按算式算出结果，选最接近的选项（标明是软件算的）。
都没有的，阅读器里提供“让 AI 解答”。

正文里的填空横线（50%=____、24/5=____）能算的也算出参考答案，放在块的 data.blanks 里。
"""

import re
from collections import Counter
from fractions import Fraction

from .pdftext import BLANK, FRAC_L, FRAC_R, FRAC_S, frac_plain

Q_LABEL_RE = re.compile(r"^\s*[※*]?\s*(?:[【\[]\s*(?:例\s*题?|练习|习题|真题|典型例题|拓展|巩固|变式)\s*(\d+)?\s*[】\]]|(?:例\s*题?|练习|习题)\s*(\d+)\s*[.．、:：]?|例题\s*[：:])\s*")
NUM_STEM_RE = re.compile(r"^\s*(\d{1,3}(?:\s*[-－]\s*\d{1,2}(?=\s*[.．]))?)\s*[.．、]\s*(?:(?!\d)|(?=(?:19|20)\d\d\s*(?:年|[-~—～－–至])))|^\s*[（(]\s*\d{4}\s*[^）)]{0,12}[）)]")
OPT_RE = re.compile(r"^\s*([A-H])\s*[.．、:：]\s*(.*)$", re.S)
INLINE_OPT_RE = re.compile(r"(?:(?<=\s)|(?<=[①-⑳])|^)([A-H])\s*[.．、]\s*")  # “C.①③④⑤D.①②③④⑤”粘在一起的也拆
ANS_RE = re.compile(r"^\s*[※*◎●○]?\s*(?:【\s*(?:正确)?答案\s*】|(?:正确|参考)?答案\s*(?:是|为)?\s*[:：]?)\s*[:：]?\s*([A-H](?:\s*[、,，]?\s*[A-H])*)\s*[。.；;]?\s*(.*)$", re.S)
PROSE_ANS_RE = re.compile(r"(?:正确答案|参考答案|答案)\s*(?:是|为|应选|选|应为)?\s*[:：]?\s*[【\[（(]?\s*([A-H]{1,4})(?![A-Za-z])"
                          r"|(?:故|因此|所以|即|则|综上)\s*[，,]?\s*(?:本题)?(?:应|正确答案)?(?:选|为|算)(?:择)?\s*[【\[]?\s*([A-H]{1,4})(?![A-Za-z])\s*(?:项|选项)?"
                          r"|秒\s*([A-H])(?![A-Za-z])"  # 状元笔记：“……60/500秒C。”
                          r"|(?:相加|相减|解|求|公式|即可|可以)得\s*([A-H])(?![A-Za-z])\s*(?:项|选项)?\s*(?:[。．.，,；;]|$)"
                          r"|(?:^|[。；;，,\s])选\s*([A-H]{1,4})(?![A-Za-z])\s*[，,]"
                          r"|(?:本题|此题|该题)(?:应|的答案)?(?:选|为)(?:择)?\s*[【\[]?\s*([A-H]{1,4})(?![A-Za-z])"
                          r"|(?<![A-Za-z])([A-H])\s*(?:项|选项)?\s*(?:最为|最)(?:契合|恰当|合适|准确|符合|贴切|正确)"
                          r"|(?<![A-Za-z、，,和与])([A-H])\s*(?:项|选项)\s*当选"
                          r"|(?:选|答案)\s*[【\[]\s*([A-H]{1,4})\s*[】\]]"
                          r"|(?:只有|仅有|唯有)\s*([A-H])\s*(?:选项|项)\s*(?:符合|正确|满足|当选|是|为)?"
                          r"|(?<![A-Za-z、和与])([A-H])\s*(?:选项|项)(?:[^。；;A-H]{0,70})[，,]\s*当选"
                          r"|对应\s*([A-H])\s*(?:选项|项)\s*[，,。]"
                          r"|(?:最优|最佳|正确)选项(?:为|是)\s*([A-H]{1,4})(?![A-Za-z])"
                          r"|答案[^。，,；;A-H]{1,6}(?:为|是)\s*([A-H]{1,4})(?![A-Za-z])"
                          r"|(?<![误不可难])(?<!容易)选(?:择)?\s*([A-H]{1,4})(?![A-Za-z])\s*(?:项|选项)?\s*(?:更恰当|更好|最恰当|最好|为宜)?\s*(?:[。．.!！;；]|$)")
BRACKET_ANS_RE = re.compile(r"^\s*[【\[]\s*([A-H]{1,4})\s*[】\]]\s*(.*)$", re.S)  # “正确答案”在上一行，这一行是“【A】……”
OPT_EXP_RE = re.compile(r"([A-H]{1,4})\s*[。.．]\s*【?\s*解\s*析\s*】?\s*[:：]?(.*)$", re.S)
FILLED_RE = re.compile(r"[（(]\s*([A-H]{1,4})\s*[）)]\s*[。.]?\s*$")  # 笔记里把答案填进了括号：“月食现象的成因是（B）”
OPT_ANS_RE = re.compile(r"\s*[※◎●○]?\s*(?:【\s*(?:参考|正确)?答案\s*】|(?:参考|正确)?答案)\s*[:：]?\s*([A-H]{1,4})\s*[。.]?\s*$")  # 答案粘在最后一个选项后面（“◎【答案】D”）
EXPLAIN_RE = re.compile(r"^\s*[※*）)]?\s*(?:【\s*[^】\s]{0,4}(?:解析|解答|详解|分析|思路|讲解)\s*】|\S{0,4}(?:解析|详解)\s*[:：]|例题讲解|题目分析|题型判定|解题思路|思路点拨|答案解析|题目精析|答案精析|考点判定|【\s*精析\s*】|精析\s*[:：]|选项辨析|内容结构分析|观察选项|※?\s*秒杀解法\s*[:：]?|【\s*秒杀解法\s*】)\s*")
STOP_RE = re.compile(r"^\s*(?:\S{0,4}点拨|【\s*(?:点拨|拓展|总结|小结|注意|技巧|方法)|小结|总结|知识拓展|技巧总结)")
KEY_RE = re.compile(r"答案\s*[:：]?\s*(\d{1,3}\s*[-~—–]\s*\d{1,3}\s*[:：].*)")
KEY_PART_RE = re.compile(r"(\d{1,3})(?:\s*[-~—–]\s*(\d{1,3}))?\s*[:：]\s*([A-H]+)(?![A-Za-z])")
KEY_CONT_RE = re.compile(r"^\s*\d{1,3}(?:\s*[-~—–]\s*\d{1,3})?\s*[:：]\s*[A-H]+")
LETTER_ANS_RE = re.compile(r"^\s*([A-H]{1,6})\s*(?:。|[．.](?!\d))\s*(.*)$", re.S)
JUDGE_HEAD_RE = re.compile(r"^\s*[A-H](?:\s*[、,，和与]\s*[A-H])*\s*(?:两|三|四)?\s*(?:项|选项)\s*(?:说法|表述)?\s*(?:正确|错误|有误|不正确|符合|不符合|属于|不属于|当选|排除)")
JUDGE_START_RE = re.compile(r"^\s*(?:[A-H](?:\s*[、,，和与]\s*[A-H])*\s*(?:两|三|四)?\s*(?:项|选项)|第[一二三四]项|题干|本题|根据|由题|解析|分析|故|因此)")
JUDGE_RE = re.compile(r"([A-H](?:\s*[、,，和与及/]\s*[A-H])*)\s*(?:两|三|四)?\s*(?:项|选项)\s*(?:的)?(?:说法|表述|内容|观点)?\s*(?:均|都|也)?\s*"
                      r"(不正确|正确|错误|有误|不符合|符合|不属于|属于|不当选|当选|排除|无误)")
NEG_STEM_RE = re.compile(r"错误|不正确|不属于|不符合|不包括|不是|有误|不能|不应|不得|不对|不准确|不恰当|不可能|不涉及|没有体现|未体现|无关")
RIGHT_WORDS = {"正确", "符合", "属于", "当选", "无误"}
FIG_HINT_RE = re.compile(r"选项|选择最|填入问号|分类|折成|拼合|视图|截面|立体|折线图|柱状图|饼图|图中|下图|哪个图|哪幅图|哪一幅")


def _is_head(b):
    return b["k"] == "h"


def _label(b):
    if b["k"] not in ("p", "box"):
        return None
    m = Q_LABEL_RE.match(b.get("t") or "")
    if not m:
        return None
    return m.group(1) or m.group(2) or ""


def _split_opts(t):
    m = OPT_RE.match(t)
    if not m:
        return []
    parts = INLINE_OPT_RE.split(t)
    # parts: ["", "A", "内容", "B", "内容", …]
    if len(parts) >= 5 and parts[0].strip() == "":
        return [(parts[k], parts[k + 1].strip()) for k in range(1, len(parts) - 1, 2)]
    return [(m.group(1), m.group(2).strip())]


def _judged_answer(q):
    """解析里逐项判断（“A项正确”“B、C两项错误”“D项排除”）：按题干问的是对的还是错的，推出答案。"""
    letters = [a for a, _o in q["d"]["opts"]]
    if len(letters) < 2:
        return
    right, wrong = set(), set()
    for e in q["d"]["exp"]:
        for grp, word in JUDGE_RE.findall(e.get("t") or ""):
            ls = set(re.findall(r"[A-H]", grp)) & set(letters)
            (right if word in RIGHT_WORDS else wrong).update(ls)
    if not right and not wrong:
        return
    neg = bool(NEG_STEM_RE.search(Q_LABEL_RE.sub("", q["d"]["stem"])[-60:]))
    if neg:
        ans = wrong if wrong else (set(letters) - right if len(right) == len(letters) - 1 else set())
    else:
        ans = right if right else (set(letters) - wrong if len(wrong) == len(letters) - 1 else set())
    if not ans or right & wrong:
        return
    q["d"]["ans"] = "".join(sorted(ans))
    q["d"]["how"] = "资料给出"


NEXT_OPT_RE = {c: re.compile(rf"(?<=[一-鿿）)》”\"。；;%\d])\s*{c}\s*[.．、]\s*") for c in "BCDEFGH"}


def _split_glued(opts):
    """OCR 把两个选项粘在一行（“C.社会舆论监督D.公民监督”）：按下一个字母拆开。"""
    out = []
    for a, o in opts:
        while True:
            nxt = chr(ord(a) + 1)
            rx = NEXT_OPT_RE.get(nxt)
            m = rx.search(o) if rx else None
            if not m or any(x == nxt for x, _o in opts):
                break
            out.append((a, o[:m.start()].strip()))
            a, o = nxt, o[m.end():].strip()
        out.append((a, o))
    return out


_lifted = []  # _options_from 跳过的、夹在选项中间的标题


def _options_from(blocks, j):
    """从第 j 块起取连续的选项块；也认一块里写在一起的“A.1 B.2 C.3 D.4”。
    两栏排版的选项读出来顺序会乱（D、C、A、B），按字母排好；字母要连续且不重复。返回 (选项列表, 下一块位置)。"""
    opts = []
    seen = set()
    _lifted.clear()
    while j < len(blocks) and len(opts) < 8:
        if blocks[j]["k"] == "h" and seen and j + 1 < len(blocks) and blocks[j + 1]["k"] == "p":
            # 跨页：C、D 之间夹着页眉章名（“第三章法律”），标题挪到题目前面，选项接着读
            nxt = _split_opts(blocks[j + 1].get("t") or "")
            if nxt and nxt[0][0] == chr(ord(max(seen)) + 1):
                _lifted.append(blocks[j])
                j += 1
                continue
        if blocks[j]["k"] != "p":
            break
        t = blocks[j].get("t") or ""
        if seen == {"A", "B", "C"} and re.match(r"^\s*0\s*[.．、]\s*\D", t):
            t = re.sub(r"^\s*0", "D", t, count=1)  # OCR 把“D.”认成了“0.”
        got = _split_opts(t)
        if not got or any(a in seen for a, _o in got):
            break
        got = _split_glued(got)
        if any(a in seen for a, _o in got):
            break
        opts += got
        seen.update(a for a, _o in got)
        j += 1
    opts.sort(key=lambda o: o[0])
    letters = [o[0] for o in opts]
    if len(opts) < 2 or letters != [chr(ord(letters[0]) + k) for k in range(len(letters))]:
        return [], j
    return opts, j


MARK_RE = re.compile(r"^\s*(?:注?\s*例\s*[：:]|【\s*(?:例|练习|习题)|例\s*题|例\s*\d|练习\s*\d)")  # “例：”“【例3】”“例题2”
PROMPT_RE = re.compile(r"[：:？?]\s*$|[（(]\s*[）)]\s*[。.]?\s*$")


def _is_marker(t):
    """题干的开头：例题标签、“例：”、题号/来源开头。"""
    return bool(Q_LABEL_RE.match(t) or MARK_RE.match(t) or NUM_STEM_RE.match(t))


def _is_opt_start(blocks, i):
    b = blocks[i]
    if b["k"] != "p":
        return False
    m = OPT_RE.match(b.get("t") or "")
    if not m:
        return False
    prev = blocks[i - 1] if i else None
    return not (prev and prev["k"] == "p" and OPT_RE.match(prev.get("t") or ""))


def _options_ahead(blocks, i, limit=4):
    """第 i 块后面几块内有没有选项（中间只隔题干续行、插图、表格）。"""
    for j in range(i + 1, min(i + 1 + limit, len(blocks))):
        b = blocks[j]
        if b["k"] == "p" and OPT_RE.match(b.get("t") or ""):
            return True
        if b["k"] not in ("p", "box", "img", "tbl") or (b["k"] == "p" and _is_marker(b.get("t") or "")):
            return False
    return False


def _expand_boxes(blocks):
    """带框的条目（文本框里写着例句和 A/B/C/D）拆成普通段落，选项才能识别出来。"""
    out = []
    for b in blocks:
        lines = (b.get("d") or {}).get("lines") if b["k"] == "box" else None
        if not lines or not any(OPT_RE.match(ln[0] or "") for ln in lines):
            out.append(b)
            continue
        seg = ""
        for ln in lines:
            t = (ln[0] or "").strip()
            if not t:
                continue
            if seg and (OPT_RE.match(t) or _is_marker(t) or re.match(r"^(拆解|解析|释义|填入|依次填入)", t) or OPT_RE.match(seg)):
                out.append({"k": "p", "t": seg, "pg": b.get("pg", 0)})
                seg = t
            else:
                seg = (seg + t) if seg else t
        if seg:
            out.append({"k": "p", "t": seg, "pg": b.get("pg", 0)})
    return out


INNER_MARK_RE = re.compile(r"(?<=[。！？!?）)”])\s*(?=注\s*例\s*[：:]|【\s*例\s*\d{1,3}\s*】)")


def _split_marks(blocks):
    """上一题的解析和下一题的“注例：/【例N】”排在同一段里：在标记处断开，下一题才认得出来。"""
    out = []
    for i, b in enumerate(blocks):
        t = b.get("t") or ""
        if b["k"] == "p" and t.strip() == "注" and i + 1 < len(blocks) and (blocks[i + 1].get("t") or "").lstrip().startswith("例"):
            continue
        if b["k"] != "p" or not INNER_MARK_RE.search(t):
            out.append(b)
            continue
        for part in INNER_MARK_RE.split(t):
            if part.strip():
                out.append(dict(b, t=part.strip()))
    return out


OPT_TAIL_HEAD_RE = re.compile(r"\s*(?:题目分析|例题讲解|选项辨析|解题思路|思路点拨)\s*$")  # 两栏排版：“D.高锰酸钾题目分析”


GLUED_TABLE_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?%?)\s*((?:19|20)\d{2}\s*(?:[~～—\-－至]\s*(?:19|20)?\d{2,4})?\s*年\S{2,40}?(?:情况|统计|数据|构成|变化)[^（(]{0,6}[（(]\s*单位.{20,})$", re.S)


def _trim_opt(o):
    """选项后面换行接着一大段图表数字（选项和统计图挤在同一块里）：只留第一行。"""
    o = OPT_TAIL_HEAD_RE.sub("", o or "") if o else o
    if "\n" not in (o or ""):
        return o
    first, rest = o.split("\n", 1)
    if len(re.findall(r"\d", rest)) > max(8, _cjk(rest)):
        return first.strip()
    return o


def _merge_split(blocks):
    """幻灯片、两栏排版把一道题的选项拆成两半（A、B 在图表上面，C、D 在下面），被认成了两道题：
    后一道的“题干”只是图表数字、没有像样的文字，选项字母正好接着前一道，就并回去。"""
    out = []
    last_q = None
    gap = 0
    for b in blocks:
        if b["k"] == "q":
            d = b["d"]
            if last_q is not None and gap <= 4 and d["opts"]:
                prev = last_q["d"]["opts"]
                nxt = chr(ord(prev[-1][0]) + 1) if prev else "A"
                st = Q_LABEL_RE.sub("", d["stem"])
                junk = _cjk(st) < 12 or len(re.findall(r"\d", st)) > _cjk(st)  # 只有图表数字
                junk = junk or _key(d["stem"]) == _key(last_q["d"]["stem"])  # 题干在两半上各印了一次
                if d["opts"][0][0] == nxt and junk and len(prev) + len(d["opts"]) <= 8:
                    last_q["d"]["opts"] = prev + d["opts"]
                    if not last_q["d"]["ans"] and d["ans"]:
                        last_q["d"]["ans"], last_q["d"]["how"] = d["ans"], d["how"]
                    last_q["d"]["exp"] = last_q["d"]["exp"] or d["exp"]
                    last_q["t"] += " " + " ".join(f"{a}.{o}" for a, o in d["opts"] if o)
                    gap = 0
                    continue
            last_q, gap = b, 0
        elif b["k"] == "h":
            last_q = None
        else:
            gap += 1
        out.append(b)
    return out


TICK_END_RE = re.compile(r"\s*([√✓✔×✗✘])\s*$")
CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩"


def _tick_answer(d):
    """讲义里批改过的题：选项或题干里的“①……√ ②……×”。勾叉去掉（不然一眼就看到答案），能推出答案的推出来：
    选项带勾叉 → 题干问“错误/不正确”选打叉的，否则选打勾的；题干里的①②③带勾叉 → 选组合相同的项，
    “有几项”数勾（问错误的数叉）。"""
    neg = bool(NEG_STEM_RE.search(d.get("stem") or ""))
    marks = {a: m.group(1) for a, o in d["opts"] if (m := TICK_END_RE.search(o or ""))}
    if marks:
        d["opts"] = [(a, TICK_END_RE.sub("", o or "")) for a, o in d["opts"]]
        if not d.get("ans"):
            want = "×✗✘" if neg else "√✓✔"
            ans = "".join(a for a, mk in marks.items() if mk in want)
            if len(marks) == 1 and not ans and next(iter(marks.values())) in "√✓✔":
                ans = next(iter(marks))  # 只勾了一个选项：那就是答案（题干里的“不是”“不能”多半是材料内容，不是在问错误项）
            if ans:
                d["ans"], d["how"] = ans, "资料给出"
    lines = (d.get("stem") or "").split("\n")
    st = {}
    for i, ln in enumerate(lines):
        m = TICK_END_RE.search(ln)
        c = ln.strip()[:1]
        if m and c in CIRCLED_NUMS:
            st[c] = m.group(1) in "√✓✔"
            lines[i] = TICK_END_RE.sub("", ln)
    if not st:
        return
    d["stem"] = "\n".join(lines)
    if d.get("ans"):
        return
    pick = {c for c, ok in st.items() if ok != neg}
    combo = {a: set(re.findall("[" + CIRCLED_NUMS + "]", o or "")) for a, o in d["opts"]}
    if all(combo.values()):
        hit = [a for a, s in combo.items() if s == pick]
    else:
        cnt = {a: int(m.group(1)) for a, o in d["opts"] if (m := re.match(r"\s*(\d)\s*(?:项|个)\s*$", o or ""))}
        hit = [a for a, v in cnt.items() if v == len(pick)] if len(cnt) == len(d["opts"]) else []
    if len(hit) == 1:
        d["ans"], d["how"] = hit[0], "资料给出"
        d.setdefault("exp", [])
        d["exp"] = [{"t": "资料批注：" + "　".join(f"{c}{'√' if ok else '×'}" for c, ok in sorted(st.items(), key=lambda x: CIRCLED_NUMS.index(x[0])))}] + d["exp"]


def _stem_before_opts(blocks, k):
    """blocks[k] 往下一两段（中间可以夹一串“①…… ②……”表述）就是一组新选项。"""
    j, plain = k, 0
    if prose_answer(blocks[k].get("t") or ""):
        return False  # “……故正确答案为B。”：是上一题的解析
    while j + 1 < len(blocks) and j - k < 14:
        t = (blocks[j].get("t") or "").strip()
        if blocks[j]["k"] not in ("p", "box") or ANS_RE.match(t) or (j > k and _is_marker(t)):
            return False  # 中间隔着“【例3】”：选项属于那道有题号的题
        if t[:1] not in CIRCLED_NUMS:
            plain += 1
            if plain > 2:
                return False
        j += 1
        if _is_opt_start(blocks, j):
            return True
    return False


def _take_stem(out):
    """从已输出的块末尾取题干：往上找最近的“例：/例N/题号”开头的一段，最多 5 块；找不到就取紧挨着的一两段。"""
    # 选项上面是一串“①…… ②……”（每条一段，长的折成两段）：整串跳过去，再往上找题号
    j, nstat, loose, heads = len(out), 0, 0, 0
    while j > 0 and len(out) - j < 16:
        x = out[j - 1]
        t = (x.get("t") or "").strip()
        if x["k"] == "h" and nstat and heads < 1 and j >= 2 and out[j - 2]["k"] == "p":
            heads += 1  # 两栏排版：另一栏的小标题夹在叙述中间
            j -= 1
            continue
        if x["k"] != "p" or x.get("q_end") or _is_marker(t):
            break
        if t[:1] in CIRCLED_NUMS:
            nstat, loose = nstat + 1, 0
        elif loose < 1 and not OPT_RE.match(t):
            loose += 1  # 上一条叙述折下来的半句
        else:
            break
        j -= 1
    j += loose
    if nstat >= 2:
        for back in range(1, 4):
            if j - back < 0:
                break
            x = out[j - back]
            if x["k"] not in ("p", "box") or x.get("q_end"):
                break
            if _is_marker(x.get("t") or ""):
                taken = out[j - back:]
                del out[j - back:]
                out.extend(y for y in taken if y["k"] == "h")  # 夹进来的小标题放回题目前面
                return [y for y in taken if y["k"] != "h"]
        # 没有题号的题（上面是小标题“诗与节日”）：整串表述都是题干
        if j < len(out) and (out[j].get("t") or "").strip()[:1] in CIRCLED_NUMS:
            taken = out[j:]
            del out[j:]
            out.extend(y for y in taken if y["k"] == "h")
            return [y for y in taken if y["k"] != "h"]
    cand = 0
    for back in range(1, 6):
        if len(out) < back:
            break
        x = out[-back]
        if x["k"] not in ("p", "box", "img", "tbl") or x.get("q_end"):
            break
        cand = back
        if x["k"] in ("p", "box") and _is_marker(x.get("t") or ""):
            taken = out[-back:]
            del out[-back:]
            return taken
    if not cand:
        return []
    take = 1
    if cand >= 2:
        last = out[-1]
        # 最后一段是“填入画横线部分最恰当的一项是：”这种提问句，或者是插图，再往上带一段
        if last["k"] in ("img", "tbl") or (len(last.get("t") or "") <= 40 and PROMPT_RE.search(last.get("t") or "")):
            take = 2
    taken = out[-take:]
    del out[-take:]
    return taken


ENTRY_RE = re.compile(r"^\s*\d{1,4}\s*[.．、]\s*(\S{2,12})\s*$")


def _entry_answer(q, out):
    """成语、实词这类词条资料：“4．因噎废食 / 拆解 / 例：……____ / A… B… C.因噎废食 D…”，
    本条讲的那个词就是答案。"""
    for x in reversed(out[-8:]):
        if x["k"] == "q":
            return
        t = ((x.get("t") or "").strip().splitlines() or [""])[0].split("拆解")[0].strip()
        m = ENTRY_RE.match(t) if x["k"] in ("h", "p") else None
        if m or x["k"] == "h":
            word = re.sub(r"[^\u4e00-\u9fff]", "", m.group(1) if m else t)
            hits = [a for a, o in q["d"]["opts"]
                    if o and word in [re.sub(r"[^\u4e00-\u9fff]", "", part) for part in re.split(r"[\s、，,/]+", o)]]
            if not hits and len(word) >= 3:
                hits = [a for a, o in q["d"]["opts"] if word in re.sub(r"[^\u4e00-\u9fff]", "", o or "")]
            if word and len(hits) == 1:
                q["d"]["ans"] = hits[0]
                q["d"]["how"] = "资料给出"
                q["d"]["exp"] = [{"t": f"这道例句练的就是本条词语“{word}”。对照上面的“拆解”体会它的意思和适用语境。"}]
            return


def group(blocks):
    """把例题并成 q 块：看到一串 A/B/C/D 选项就是一道题，题干取选项上面最近的“例：/例N/题号”那几段。
    图形题（选项画在图里）靠“例N + 插图”识别。答案框按编号回填后去掉。其余块原样保留。"""
    blocks = _split_marks(_expand_boxes(blocks))
    out = []
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        t0 = b.get("t") or ""
        if _is_opt_start(blocks, i):
            opts, k = _options_from(blocks, i)
            if not opts:
                out.append(b)
                i += 1
                continue
            lifted = list(_lifted)
            if opts[0][0] == "B":
                # A 项折成了两段，被当成了题干的一部分：从已输出的块里找回来
                for back in (1, 2):
                    if len(out) > back and out[-back]["k"] == "p" and OPT_RE.match(out[-back].get("t") or "")                             and OPT_RE.match(out[-back]["t"]).group(1) == "A":
                        parts = out[-back:]
                        del out[-back:]
                        a_text = "".join(x.get("t") or "" for x in parts)
                        opts = [("A", OPT_RE.match(a_text).group(2).strip())] + opts
                        break
            stem_blocks = _take_stem(out)
            out.extend(lifted)
        elif (_label(b) is not None or (b["k"] == "p" and NUM_STEM_RE.match(t0) and i + 1 < n and blocks[i + 1]["k"] == "img")) \
                and not _options_ahead(blocks, i, 6):
            # 图形题：例N（或题号）+ 插图，选项画在图里
            j = i + 1
            figs_ahead = []
            while j < n and j <= i + 3 and blocks[j]["k"] in ("img", "p", "box") and not _is_marker(blocks[j].get("t") or "")                     and not KEY_RE.search(blocks[j].get("t") or "") and not ANS_RE.match(blocks[j].get("t") or ""):
                figs_ahead.append(blocks[j])
                j += 1
            imgs = [x for x in figs_ahead if x["k"] == "img"]
            stem_txt = t0 + " " + " ".join(x.get("t") or "" for x in figs_ahead if x["k"] != "img")
            if not imgs or not FIG_HINT_RE.search(stem_txt + " " + (out[-1].get("t") or "" if out else "")):
                out.append(b)
                i += 1
                continue
            stem_blocks = [b] + figs_ahead
            if not Q_LABEL_RE.sub("", t0).strip() and out and out[-1]["k"] == "p" and not out[-1].get("q_end"):
                stem_blocks = [out.pop()] + stem_blocks  # 标签排在题干右边：题干在上一段
            opts = [(c, "") for c in "ABCD"]
            k = j
        else:
            out.append(b)
            i += 1
            continue

        # 词条标题、拆解和“例：”连在一起：标题和拆解留在正文，题干只从“例：”开始
        for si in range(len(stem_blocks) - 1, -1, -1):
            xb = stem_blocks[si]
            pos = (xb.get("t") or "").find("例：") if xb["k"] in ("p", "box") else -1
            if pos < 0:
                continue
            if pos > 0 or si > 0:
                for keep in stem_blocks[:si]:
                    out.append(keep)
                if pos > 0:
                    out.append(dict(xb, t=xb["t"][:pos].strip()))
                stem_blocks = [dict(xb, t=xb["t"][pos:])] + stem_blocks[si + 1:]
            break
        stem = [x.get("t") or "" for x in stem_blocks if x["k"] in ("p", "box") and x.get("t")]
        figs = [x for x in stem_blocks if x["k"] in ("img", "tbl")]
        stem_text = "\n".join(stem)
        # 两栏排版：题干第一行“（2020广东）某部门……需”排在“例5”标签上面，标签单独一行夹在题干中间
        if out and out[-1]["k"] == "p" and re.fullmatch(r"\s*例\s*\d{0,3}\s*", stem_text.split("\n")[0]) \
                and re.match(r"\s*[（(]\s*\d{4}", out[-1].get("t") or "") and not re.search(r"[。？?：:]\s*$", out[-1]["t"]):
            first, _sep, rest = stem_text.partition("\n")
            stem_text = first + " " + out.pop()["t"].strip() + rest.strip()
        elif out and out[-1]["k"] == "p" and not out[-1].get("q_end") and Q_LABEL_RE.match(stem_text) \
                and not Q_LABEL_RE.sub("", stem_text).strip() and len(out[-1].get("t") or "") <= 400 \
                and (re.match(r"\s*[（(]\s*\d{4}", out[-1]["t"]) or re.search(r"[？?：:]\s*$", out[-1]["t"])) \
                and not (Q_LABEL_RE.match(out[-1]["t"]) or MARK_RE.match(out[-1]["t"])):
            # 整句题干排在单独一行的“例5”上面
            stem_text = stem_text.strip() + " " + out.pop()["t"].strip()
        stem_text = re.sub(r"(?<=[一-鿿，、])\n\s*例\s*\d{0,3}\s*\n(?=[一-鿿])", "", stem_text)
        stem = stem_text.split("\n")
        label = next((_label(x) for x in stem_blocks if _label(x) is not None), None)
        lines = stem_text.split("\n")
        if label is None and len(lines) > 1 and not NUM_STEM_RE.match(lines[0]):
            # 统计图的数字和下面的“106.2019-2022年……”挤在同一块：图表数字留在正文，题干从题号开始
            for li in range(1, len(lines)):
                if re.match(r"\s*\d{1,3}\s*[.．]", lines[li]) and NUM_STEM_RE.match(lines[li]):
                    pre = "\n".join(lines[:li])
                    if len(re.findall(r"\d", pre)) > _cjk(pre):
                        out.append({"k": "p", "t": pre, "pg": (stem_blocks[0] if stem_blocks else b).get("pg", 0)})
                        stem_text = "\n".join(lines[li:])
                        stem = lines[li:]
                    break
        if label is None and not NUM_STEM_RE.match(stem_text) and out and out[-1]["k"] == "q":
            # 上一题解析的末尾和“127.2023年……”粘成了一段：题号前面的还给上一题的解析
            gm = next((g for g in re.finditer(r"[。；;”]\s*(?=\d{1,3}\s*[.．、])", stem_text)
                       if NUM_STEM_RE.match(stem_text[g.end():]) and len(stem_text) - g.end() >= 12), None)
            if gm:
                out[-1]["d"]["exp"].append({"t": stem_text[:gm.end()].strip()})
                stem_text = stem_text[gm.end():]
                stem = stem_text.split("\n")
        nm = NUM_STEM_RE.match(stem_text)
        head_glued =bool(opts and OPT_TAIL_HEAD_RE.search(opts[-1][1] or ""))  # “D.……题目分析”：解析从下一段开始
        opts = [(a, _trim_opt(o)) for a, o in opts]
        for oi, (a, o) in enumerate(opts):
            gm = GLUED_TABLE_RE.match(o or "")
            if gm:
                # “A.83.962020~2021年……情况（单位：亿元） 区域 2020年 ……”：材料表格粘在了选项后面，挪回题干
                opts[oi] = (a, gm.group(1))
                stem_text = stem_text + "\n" + gm.group(2).strip()
                stem = stem_text.split("\n")
        filled = FILLED_RE.search(stem_text)
        if filled and set(filled.group(1)) <= {a for a, _o in opts}:
            stem_text = stem_text[:filled.start()] + "（ ）"
            stem = stem_text.split("\n")
        last_stem = (stem[-1] if stem else "").strip()
        no_cue = not re.search(r"[？?（(）)_：:]|是|哪|下列|以下|下面|选|属于|正确|错误", stem_text)
        sentences = sum((o or "").rstrip().endswith(("。", "；", ";")) for _a, o in opts) >= max(2, len(opts) - 1)
        if (last_stem.endswith("。") and len(last_stem) <= 20 and not re.search(r"[？?（(）)_]|是|哪|下列|以下", last_stem)
                and label is None and not nm and all((o or "").rstrip().endswith("。") and len(o) >= 6 for _a, o in opts)) \
                or (no_cue and label is None and sentences and sum(len(o) for _a, o in opts) >= 15 * len(opts)):
            # “②答题技巧。A.直接摘抄…。B.借鉴…。”：讲义里用字母编号的要点列表，不是题
            out += stem_blocks
            out += [{"k": "p", "t": f"{a}. {o}", "pg": b.get("pg", 0)} for a, o in opts]
            i = k
            continue
        q = {"k": "q", "t": "", "pg": (stem_blocks[0] if stem_blocks else b).get("pg", 0), "d": {
            "num": label or (nm.group(1) if nm and nm.group(1) else "") or "",
            "stem": stem_text, "figs": [{"src": (f.get("d") or {}).get("src"), "alt": f.get("t", ""), "rows": (f.get("d") or {}).get("rows"),
                                         **{x: (f.get("d") or {})[x] for x in ("chart", "w", "h", "pw") if (f.get("d") or {}).get(x)}} for f in figs],
            "opts": opts, "ans": filled.group(1) if filled and set(filled.group(1)) <= {a for a, _o in opts} else "",
            "exp": [], "how": "资料给出" if filled and set(filled.group(1)) <= {a for a, _o in opts} else ""}}
        # 答案、解析
        exp = [{"t": ""}] if head_glued else []  # 空条目只是“解析已开始”的标记，最后会被滤掉
        while k < n and len(exp) < 16:
            nb = blocks[k]
            t = nb.get("t") or ""
            if _is_head(nb) or KEY_RE.search(t) or _is_opt_start(blocks, k) \
                    or (nb["k"] in ("p", "box") and _is_marker(t) and _options_ahead(blocks, k)) or _label(nb) is not None:
                break
            m = ANS_RE.match(t) if nb["k"] == "p" else None
            lm = LETTER_ANS_RE.match(t) if nb["k"] == "p" and not exp and not q["d"]["ans"] else None
            if lm and not m:
                # “C。先看尾句……”：解析开头就是答案
                q["d"]["ans"] = lm.group(1)
                q["d"]["how"] = "资料给出"
                if lm.group(2).strip():
                    exp.append({"t": lm.group(2).strip()})
                k += 1
                continue
            if m and not q["d"]["ans"]:
                q["d"]["ans"] = re.sub(r"[^A-H]", "", m.group(1))
                q["d"]["how"] = "资料给出"
                rest = m.group(2).strip()
                if rest and not re.fullmatch(r"[A-H]?\s*[。.．]?", rest):
                    exp.append({"t": EXPLAIN_RE.sub("", rest)})
                k += 1
                continue
            bm = BRACKET_ANS_RE.match(t) if nb["k"] == "p" and not q["d"]["ans"] else None
            if bm and (not exp or re.search(r"(?:答案|选)\s*[:：]?\s*$", exp[-1].get("t") or "")):
                q["d"]["ans"] = bm.group(1)
                q["d"]["how"] = "资料给出"
                if bm.group(2).strip():
                    exp.append({"t": EXPLAIN_RE.sub("", bm.group(2).strip())})
                k += 1
                continue
            if STOP_RE.match(t) or (nb["k"] == "img" and (nb.get("d") or {}).get("chart") and not (
                    exp and any(blocks[j]["k"] == "p" and (ANS_RE.match(blocks[j].get("t") or "") or prose_answer(blocks[j].get("t") or ""))
                                for j in range(k + 1, min(k + 3, n))))):
                break  # 统计图是下一篇材料，不是这题的解析（解析中间截成图的算式除外：后面紧跟着答案）
            if (exp or q["d"]["ans"]) and nb["k"] in ("p", "box") and not EXPLAIN_RE.match(t) and _stem_before_opts(blocks, k):
                break  # 紧接着又是一组选项：这段是下一道（没有题号的）题的题干，不是解析
            if EXPLAIN_RE.match(t) or (exp and nb["k"] in ("p", "img", "tbl", "box") and not t.startswith("【"))                     or (not exp and nb["k"] == "p" and (JUDGE_HEAD_RE.match(t) or q["d"]["ans"] and JUDGE_START_RE.match(t)
                                                         or not q["d"]["ans"] and len(t) <= 400 and prose_answer(t))):
                exp.append({"t": EXPLAIN_RE.sub("", t) if nb["k"] != "img" else "", "src": (nb.get("d") or {}).get("src") if nb["k"] == "img" else None,
                            "rows": (nb.get("d") or {}).get("rows") if nb["k"] == "tbl" else None,
                            **({x: nb["d"][x] for x in ("chart", "w", "h", "pw") if nb["d"].get(x)} if nb["k"] == "img" else {})})
                k += 1
                continue
            break
        if not exp and not q["d"]["ans"]:
            # 解析没有标题，答案在第二、三段（“题干认为……”“……故答案为A.”）：往后看三段，找到答案就连同前面几段收作解析
            look = []
            for j in range(k, min(k + 3, n)):
                nb = blocks[j]
                t = nb.get("t") or ""
                if nb["k"] != "p" or _is_head(nb) or _is_opt_start(blocks, j) or _is_marker(t) or STOP_RE.match(t) or len(t) > 500:
                    break
                look.append(t)
                if prose_answer(t):
                    exp = [{"t": x} for x in look]
                    k = j + 1
                    break
        q["d"]["exp"] = [e for e in exp if e.get("t") or e.get("src") or e.get("rows")]
        if q["d"]["ans"] and (len(set(q["d"]["ans"])) < len(q["d"]["ans"]) or not set(q["d"]["ans"]) <= {a for a, _o in q["d"]["opts"]}):
            q["d"]["ans"], q["d"]["how"] = "", ""
        _tick_answer(q["d"])
        if q["d"]["opts"] and q["d"]["opts"][-1][1]:
            gm = OPT_EXP_RE.search(q["d"]["opts"][-1][1])
            if gm:
                # “D.是……的会议ABC。解析：ABC项正确……”：答案和解析粘在最后一个选项后面
                a, o = q["d"]["opts"][-1]
                q["d"]["opts"][-1] = (a, o[:gm.start()].strip())
                if not q["d"]["ans"]:
                    q["d"]["ans"], q["d"]["how"] = gm.group(1), "资料给出"
                    q["d"]["exp"] = [{"t": gm.group(2).strip()}] + q["d"]["exp"]
            om = OPT_ANS_RE.search(q["d"]["opts"][-1][1])
            if om:
                a, o = q["d"]["opts"][-1]
                q["d"]["opts"][-1] = (a, o[:om.start()].strip())
                if not q["d"]["ans"]:
                    q["d"]["ans"] = om.group(1)
                    q["d"]["how"] = "资料给出"
        said = prose_answer("".join(e.get("t") or "" for e in q["d"]["exp"]))
        if not q["d"]["ans"] and said:
            q["d"]["ans"] = said
            q["d"]["how"] = "资料给出"
        elif q["d"]["ans"] and said and not (set(said) <= set(q["d"]["ans"])):
            q["d"]["exp"] = []
        if not q["d"]["ans"]:
            _judged_answer(q)
        if not q["d"]["ans"]:
            _entry_answer(q, out)
        q["t"] = frac_plain(stem_text + " " + " ".join(f"{a}.{o}" for a, o in opts if o))
        q["q_end"] = True
        out.append(q)
        i = k
    out = _merge_split(out)
    _realign(out)
    _apply_solutions(out)
    _apply_key_lists(out)
    _apply_pian_keys(out)
    _apply_keys(out)
    match_bank(out)
    for q in out:
        if q["k"] == "q" and (not q["d"]["ans"] or not q["d"]["exp"]):
            _compute_choice(q)
    match_extra(out)
    for b in out:
        b.pop("q_end", None)
        if b["k"] in ("p", "box") and BLANK[:3] in (b.get("t") or ""):
            b["t"] = _drop_underlines(b["t"])
            if b["k"] == "box" and (b.get("d") or {}).get("lines"):
                b["d"] = dict(b["d"], lines=[[_drop_underlines(t), a] for t, a in b["d"]["lines"]])
            bl = blank_answers(b["t"])
            if any(bl):
                b.setdefault("d", {})
                b["d"] = dict(b["d"] or {}, blanks=bl)
    return [b for b in out if not b.get("key_used")]


# ---------------------------------------------------------------- 解析和题目对不上

SIG_STOP = set("定位 资料 可知 判定 本题 问题 根据 题干 选项 正确 答案 因此 选择 可得 结合 公式 计算 已知 题目 文段 下列 以下 "
               "说法 表述 内容 符合 属于 排除 当选 故本 故正 确答 案为 项正 项错 错误 易错 错项 确率 正确率".split())


def _sig(text):
    t = re.sub(r"\s", "", frac_plain(text or ""))
    out = set()
    for seg in re.findall(r"[\u4e00-\u9fff]+", t):
        out.update(seg[i:i + 2] for i in range(len(seg) - 1))
    out.update(re.findall(r"\d+\.\d+|\d{3,}", t))
    return out - SIG_STOP


def _cjk(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def _realign(blocks):
    """有的讲义把解析集中排在别处（版面里和另一篇材料的题挨着），按顺序挂上去就张冠李戴：
    解析里的关键词（题干引语、数字、名词）和本题几乎没有重合、却和另一道题高度重合时，挪到那道题下面；
    完全对不上又找不到归属的长解析去掉（连同从它里面读出的答案）。"""
    qs = [b for b in blocks if b["k"] == "q"]
    if len(qs) < 2:
        return
    df = Counter()
    sq = []
    for q in qs:
        s0 = _sig(q["d"]["stem"] + "".join(o for _a, o in q["d"]["opts"]))
        sq.append(s0)
        df.update(s0)
    gen = {t for t, n in df.items() if n > max(3, len(qs) * 0.08)}
    sq = [x - gen for x in sq]

    def score(i, se):
        return len(sq[i] & se) / min(len(sq[i]), 15) if len(sq[i]) >= 6 else None

    exps = []
    for i, q in enumerate(qs):
        text = "".join(e.get("t") or "" for e in q["d"]["exp"])
        if _cjk(text) < 40 or len(sq[i]) < 6:
            exps.append(None)
            continue
        se = _sig(text) - gen
        exps.append((text, se, score(i, se)))
    flagged = [i for i, x in enumerate(exps) if x and x[2] < 0.15]
    if not flagged:
        return
    moves = []
    for i in flagged:
        text, se, own = exps[i]
        best = max(((score(j, se) or 0, j) for j in range(len(qs)) if j != i), default=(0, None))
        if best[1] is not None and best[0] >= 0.4 and best[0] >= own * 3 + 0.2:
            moves.append((best[0], i, best[1]))
    moves.sort(reverse=True)
    taken, given = set(), {}
    for sc, i, j in moves:
        if j in taken or i in given:
            continue
        cur = exps[j]
        if cur and cur[2] >= sc / 2 and j not in flagged:
            continue  # 那道题自己的解析对得上
        taken.add(j)
        given[i] = j
    old = {i: (qs[i]["d"]["exp"], qs[i]["d"]["ans"], qs[i]["d"]["how"]) for i in flagged}
    for i in flagged:
        exp, ans, _how = old[i]
        text = exps[i][0]
        from_exp = bool(ans) and prose_answer(text) == ans
        if i in given or (exps[i][2] == 0 and len(sq[i]) >= 8 and _cjk(text) >= 60):
            qs[i]["d"]["exp"] = []
            if from_exp:
                qs[i]["d"]["ans"], qs[i]["d"]["how"] = "", ""
    for i, j in given.items():
        exp, ans, how = old[i]
        qs[j]["d"]["exp"] = exp
        new = prose_answer(exps[i][0])
        if new and set(new) <= {a for a, _o in qs[j]["d"]["opts"]}:
            qs[j]["d"]["ans"], qs[j]["d"]["how"] = new, "资料给出"


def prose_answer(text):
    """解析文字里写出的答案（“故正确答案为B”“此题选D”“C选项当选”）；几处说法不一致的不认。"""
    found = []
    for m in PROSE_ANS_RE.finditer(text or ""):
        a = next((g for g in m.groups() if g), None)
        if a:
            found.append(a)
    lead = re.match(r"\s*([A-H]{1,4})\s*[。．](?!\d)", text or "")  # 解析开头就是答案：“B。清明、惊蛰……”
    if lead:
        return lead.group(1)
    # 取第一处结论：解析后面常常混进了下一道题的内容（“……故正确答案为D。28.一般手机……故正确答案为C”）
    return found[0] if found else ""


SOL_RE = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*(?:【\s*答\s*案\s*】\s*)?([A-H]{1,4})\s*(?:[。.．]\s*)?[【［\[]\s*(?:解\s*析|详\s*解|精\s*析)\s*[】］\]]\s*(.*)$", re.S)


def _apply_solutions(blocks):
    """一节题后面集中给“题目解析”：“1.B【解析】……”“2.【答案】C【解析】……”。按题号回填到前面还没有答案的题，
    解析内容要和题目对得上；用过的解析段落不再单独显示。"""
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        m = SOL_RE.match(b.get("t") or "") if b["k"] == "p" else None
        if not m:
            i += 1
            continue
        num, ans, first = m.group(1), m.group(2), m.group(3).strip()
        j = i + 1
        body = [first] if first else []
        while j < n and blocks[j]["k"] in ("p", "box") and not SOL_RE.match(blocks[j].get("t") or "") \
                and not _is_marker(blocks[j].get("t") or "") and len(body) < 12:
            body.append(blocks[j].get("t") or "")
            j += 1
        text = "".join(body)
        target = None
        last = None
        for back in range(i - 1, max(-1, i - 400), -1):
            q = blocks[back]
            if q["k"] != "q":
                continue
            qn = q["d"]["num"]
            if qn.isdigit() and last is not None and int(qn) > last and q["d"]["ans"]:
                break  # 进了上一节
            if qn.isdigit():
                last = int(qn)
            if qn == num and (not q["d"]["ans"] or q["d"]["how"] == "软件计算"):
                sq = _sig(q["d"]["stem"] + "".join(o for _a, o in q["d"]["opts"]))
                if _cjk(text) < 40 or len(sq) < 6 or len(sq & _sig(text)) >= 2:
                    target = q
                break
        if target is not None and set(ans) <= {a for a, _o in target["d"]["opts"]}:
            target["d"]["ans"], target["d"]["how"] = ans, "资料给出"
            target["d"]["exp"] = [{"t": t} for t in body if t.strip()]
            for k in range(i, j):
                blocks[k]["key_used"] = True
        i = j


KEYHEAD_RE = re.compile(r"^\s*【?\s*(?:参考)?答案(?:汇总|速查|速览|一览)?\s*】?\s*[:：]?\s*")
KEYLINE_RE = re.compile(r"^\s*(?:(单选|多选|不定项|判断)题?\s*[:：]?\s*)?\d{1,3}\s*[-~—–]\s*\d{1,3}\s*[:：]")
KEYSEG_RE = re.compile(r"(\d{1,3})\s*[-~—–]\s*(\d{1,3})\s*[:：]\s*([A-H/／]+)")
KEYDOT_RE = re.compile(r"(?<!\d)(\d{1,3})\s*[.．、]\s*([A-H]{1,5})(?![A-Za-z])")  # “1.C 2.B 3.AD”


def _dot_keys(t):
    """整行都是“1.C 2.B 3.A”这种题号+答案（至少两对）时返回 [(题号, 答案)]。"""
    pairs = KEYDOT_RE.findall(t or "")
    if len(pairs) < 2 or len(re.sub(r"[\s；;，,。]", "", KEYDOT_RE.sub("", t))) > 6:
        return []
    return [(int(a), x) for a, x in pairs]


def _apply_key_lists(blocks):
    """“【答案汇总】单选题1-5：DACAD；6-8：DCD  多选题1-2：ABCD/CD”：分题型、题号各自从 1 开始，多选用“/”隔开。
    从答案框往前按题号倒着对：最后一组对最后几道题，题号重新变大就换到前一组。"""
    start = 0
    for idx, b in enumerate(blocks):
        t = b.get("t") or ""
        if b["k"] not in ("p", "box", "h") or not KEYHEAD_RE.match(t):
            continue
        rest = KEYHEAD_RE.sub("", t, count=1)
        lines = [rest] if KEYLINE_RE.match(rest) or _dot_keys(rest) else []
        used = [b]
        for nb in blocks[idx + 1: idx + 10]:
            if nb["k"] in ("p", "box") and (KEYLINE_RE.match(nb.get("t") or "") or _dot_keys(nb.get("t") or "")):
                lines.append(nb["t"])
                used.append(nb)
            else:
                break
        if not lines:
            continue
        groups = []
        sect = None
        for ln in lines:
            for a, x in _dot_keys(ln):
                if not groups or (groups[-1] and a <= groups[-1][-1][0]):
                    groups.append([])
                groups[-1].append((a, x))
            m = KEYLINE_RE.match(ln)
            if not m:
                continue
            if m.group(1) and m.group(1) != sect:
                sect = m.group(1)
                groups.append([])
            for a, z, letters in KEYSEG_RE.findall(ln):
                a, z = int(a), int(z)
                parts = re.split(r"[/／]", letters) if re.search(r"[/／]", letters) else list(letters)
                if z - a + 1 != len(parts) or not all(parts):
                    continue
                if not groups or (groups[-1] and a <= groups[-1][-1][0]):
                    groups.append([])
                groups[-1] += [(a + k, x) for k, x in enumerate(parts)]
        expect = [x for g in groups for x in g]
        if not expect:
            continue
        e = len(expect) - 1
        hit = 0
        for back in range(idx - 1, start - 1, -1):
            q = blocks[back]
            if q["k"] != "q" or not q["d"]["num"].isdigit():
                continue
            num = int(q["d"]["num"])
            while e >= 0 and expect[e][0] != num and expect[e][0] > num:
                e -= 1  # 资料里少认了这道题
            if e < 0:
                break
            if expect[e][0] == num:
                ans = expect[e][1]
                if (not q["d"]["ans"] or q["d"]["how"] == "软件计算") and set(ans) <= {a for a, _o in q["d"]["opts"]}:
                    q["d"]["ans"], q["d"]["how"] = ans, "资料给出"
                    hit += 1
                e -= 1
        if hit:
            for x in used:
                x["key_used"] = True
        start = idx + len(used)


PIAN_KEY_RE = re.compile(r"^\s*第\s*\d{1,3}\s*篇\s*(?=\d{1,3}\s*[-－—–]\s*[A-H])")
PIAN_INNER_RE = re.compile(r"^[^\n。]{0,30}?[）)】\]]\s*(\d{1,3})\s*[.．]")
PIAN_PAIR_RE = re.compile(r"(?<![\d.A-Za-z])(\d{1,3})\s*[-－—–]\s*([A-H]{1,4})(?![A-Za-z])")


def _apply_pian_keys(blocks):
    """资料分析课堂讲义每篇材料后面的答案：“第81篇 101-D 现期比重：部分量=整体量×比重 102-D 排序题……”。
    按题号回填这一篇里（往前到上一篇的答案为止）还没有答案的题，题号后面的考点说明作解析；答案行不再单独显示。"""
    prev = 0
    for idx, b in enumerate(blocks):
        t = b.get("t") or ""
        if b["k"] not in ("p", "box", "tbl") or not PIAN_KEY_RE.match(t):
            continue
        body = PIAN_KEY_RE.sub("", t, count=1)
        ms = list(PIAN_PAIR_RE.finditer(body))
        if len(ms) < 2:
            prev = idx
            continue
        keys = {}
        for i, m in enumerate(ms):
            note = body[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(body)].strip()
            keys.setdefault(m.group(1), (m.group(2), note))
        hit = 0
        for back in range(idx - 1, prev, -1):
            q = blocks[back]
            if q["k"] != "q":
                continue
            # “【拓展41】（2024国考）129.……”：答案按原题号 129 给
            num = next((x for x in [q["d"]["num"]] + PIAN_INNER_RE.findall(q["d"]["stem"][:50]) if x in keys), None)
            if num is None:
                continue
            ans, note = keys.pop(num)
            if (q["d"]["ans"] and q["d"]["how"] != "软件计算") or not set(ans) <= {a for a, _o in q["d"]["opts"]}:
                continue
            q["d"]["ans"], q["d"]["how"] = ans, "资料给出"
            if note and not q["d"]["exp"]:
                q["d"]["exp"] = [{"t": "考点：" + note}]
            hit += 1
        if hit:
            b["key_used"] = True
        prev = idx


def _apply_keys(blocks):
    """答案框“答案：1-5:BBDDC 6-7:CC”：按编号往前找还没有答案的例题，填上答案；答案框不再显示。
    往前找时题号应该越来越小，遇到更大的题号说明进了上一节，就停。"""
    for idx, b in enumerate(blocks):
        if b["k"] not in ("p", "box", "tbl", "img") or b.get("key_used"):
            continue
        t = b.get("t") or ""
        m = KEY_RE.search(t)
        if not m:
            # “答案：”单独一行，下面几行才是“1-5：DBDBC；6-10：……”
            nxt = blocks[idx + 1] if idx + 1 < len(blocks) else None
            m = re.fullmatch(r"\s*(?:参考)?答案\s*[:：]?\s*", t)
            if not (m and nxt and nxt["k"] in ("p", "box") and KEY_CONT_RE.match(nxt.get("t") or "")):
                continue
        text = m.group(1) if m.groups() else ""
        follow = []
        for nb in blocks[idx + 1: idx + 12]:  # 答案框折成了好几行
            if nb["k"] in ("p", "box") and KEY_CONT_RE.match(nb.get("t") or ""):
                text += " " + nb["t"]
                follow.append(nb)
            else:
                break
        keys = {}
        for a, z, letters in KEY_PART_RE.findall(text):
            a = int(a)
            z = int(z) if z else a
            if z - a + 1 == len(letters):
                for k, c in zip(range(a, z + 1), letters):
                    keys[str(k)] = c
        if not keys:
            continue
        hit = 0
        last = None
        for back in range(idx - 1, max(-1, idx - 600), -1):
            q = blocks[back]
            if q["k"] != "q":
                continue
            num = int(q["d"]["num"]) if q["d"]["num"].isdigit() else None
            if num is not None and last is not None and num > last:
                break
            if num is not None:
                last = num
            if q["d"]["ans"] or q["d"]["num"] not in keys:
                continue
            q["d"]["ans"] = keys.pop(q["d"]["num"])
            q["d"]["how"] = "资料给出"
            hit += 1
            if not keys:
                break
        if hit:
            for nb in follow:
                nb["key_used"] = True
            # 答案框不再显示：去掉答案那一段，剩下的只是页眉噪声就整块不要
            rest = (t[:m.start()] + t[m.end():]).strip()
            if len(re.sub(r"\s", "", rest)) < 30:
                b["key_used"] = True
            else:
                b["t"] = rest
                if b.get("d") and b["d"].get("lines"):
                    b["d"]["lines"] = [ln for ln in b["d"]["lines"] if "答案" not in ln[0]]


# ---------------------------------------------------------------- 题库对照

_bank = None
_extra = None


def qkey(q):
    """例题指纹：题干 + 各选项开头（补充解答文件按它对应）。"""
    return _key(q["stem"])[:40] + "|" + "/".join(_key(o)[:6] for _a, o in q["opts"])


def _load_extra():
    """content/doc_answers.json：资料和题库里都没有答案的例题，人工补的答案和解析 {指纹: {"ans", "exp"}}。"""
    global _extra
    if _extra is None:
        import json
        from .paths import content_dir
        try:
            _extra = json.loads((content_dir() / "doc_answers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _extra = {}
    return _extra


def match_extra(blocks):
    extra = _load_extra()
    if not extra:
        return
    for q in blocks:
        if q["k"] != "q" or (q["d"]["ans"] and q["d"]["how"] != "软件计算"):
            continue
        hit = extra.get(qkey(q["d"]))
        if hit and hit.get("text"):
            q["d"]["notq"] = True  # 人工核对过：这是笔记里用字母编号的要点 / 残缺的题，不当题目显示
            continue
        if hit and set(hit["ans"]) <= {a for a, _o in q["d"]["opts"]}:
            q["d"]["ans"], q["d"]["how"] = hit["ans"], "补充解答"
            q["d"]["exp"] = [{"t": t} for t in hit.get("exp", "").split("\n") if t.strip()]


def _key(text):
    t = Q_LABEL_RE.sub("", text or "")
    t = re.sub(r"^\s*\d{1,3}\s*[.．、]\s*", "", t)
    t = re.sub(r"^\s*[（(][^）)]{0,20}[）)]\s*", "", t)
    t = re.sub(r"^\s*\d{1,3}\s*[.．、]\s*(?=\D|\d{4})", "", t)  # “（2022国考）118.2020年…”里的原题号
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", frac_plain(t))


def _bkey(text):
    """和题库比对用的题干指纹：OCR 把年份之间的“—”认成了“一”（“2014一2020年”），去掉年份间的连接号再比。"""
    return _key(re.sub(r"(?<=\d)\s*[一—–－~～-]\s*(?=\d)", "", text or ""))


def _load_bank():
    """真题卷和千题册里有答案的题，按题干开头建索引（整理一次资料只读一遍）。"""
    global _bank
    if _bank is not None:
        return _bank
    import json
    import sqlite3
    from .paths import data_dir
    path = data_dir() / "library" / "questions.db"
    _bank = {}
    if not path.exists():
        return _bank
    conn = sqlite3.connect(path)
    for qid, stem, opts, ans, exp, origin, src, source, module in conn.execute(
            "SELECT id, stem, options, answer, explain, origin, src, source, module FROM questions "
            "WHERE answer IS NOT NULL AND answer != '' AND answer >= 0"):
        k = _bkey(stem)
        if len(k) < 6:
            continue
        try:
            opts = json.loads(opts or "[]")
        except ValueError:
            continue
        _bank.setdefault(k[:22], []).append((qid, k, opts, int(ans), exp or "", origin or "", src or "", module or ""))
    conn.close()
    return _bank


def _same_opts(mine, theirs):
    if not mine or not theirs or not any(o for _a, o in mine):
        return not any(o for _a, o in mine)  # 图形题选项在图里：只能靠题干
    a = [re.sub(r"[^一-鿿A-Za-z0-9①-⑳]", "", o)[:8] for _l, o in mine]
    b = [re.sub(r"[^一-鿿A-Za-z0-9①-⑳]", "", o)[:8] for o in theirs]
    return sum(1 for x in a if x and x in b) >= max(2, len([x for x in a if x]) - 1)


def same_option(mine, text):
    """text 是另一份资料里的某个选项：返回 mine 里内容相同的那个字母。几个选项开头一样（“2022年末，平均每个……”）时比全文。"""
    want = re.sub(r"[^一-鿿A-Za-z0-9①-⑳]", "", text or "")
    if not want:
        return ""
    keys = [(a, re.sub(r"[^一-鿿A-Za-z0-9①-⑳]", "", o or "")) for a, o in mine]
    for n in (None, 16, 8):
        hits = [a for a, k in keys if k and (k == want if n is None else k[:n] == want[:n])]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return ""
    # 一边的选项后面粘了图表坐标数字（“2014年10000”对“2014年”）：一个是另一个的开头，且只有一个对得上
    hits = [a for a, k in keys if k and (k.startswith(want) or want.startswith(k))]
    return hits[0] if len(hits) == 1 else ""


def match_bank(blocks):
    """资料里没给答案的例题，如果是题库里的真题 / 千题册原题，用题库的答案和解析。"""
    bank = _load_bank()
    if not bank:
        return
    for q in blocks:
        if q["k"] != "q" or q["d"]["ans"]:
            continue
        # 题干开头；讲义把材料和问题写在一起的（资料分析），再试最后一两行的问题句
        lines = [x for x in q["d"]["stem"].split("\n") if x.strip()]
        keys = [_bkey(q["d"]["stem"])] + [_bkey("".join(lines[-n:])) for n in (1, 2) if len(lines) > n]
        cands = []
        for k in keys:
            if len(k) >= 12:
                cands += [(k, c) for c in bank.get(k[:22], [])]
        for k, (qid, full, opts, ans, exp, origin, src, module) in cands:
            if not (full.startswith(k[:40]) or k.startswith(full[:40])):
                continue
            if not _same_opts(q["d"]["opts"], opts):
                continue
            sq = _sig(q["d"]["stem"] + "".join(o for _a, o in q["d"]["opts"]))
            if exp and _cjk(exp) >= 60 and len(sq) >= 8 and len(sq & _sig(exp)) <= 1:
                continue  # 题库里这道题的解析讲的是别的题（解析册对错了位），答案也不可信
            mine = q["d"]["opts"]
            if ans >= len(opts) and opts:
                continue
            letter = "ABCDEFGH"[ans]
            if any(o for _a, o in mine) and opts:
                # 选项顺序可能不同：按内容对回资料里的字母；资料里缺了几个选项的，对不上就不用
                hit = same_option(mine, opts[ans])
                if not hit and len(mine) != len(opts):
                    continue
                letter = hit or letter
            if letter not in {a for a, _o in mine}:
                continue
            q["d"]["ans"] = letter
            q["d"]["how"] = "题库"
            q["d"]["bank"] = {"id": qid, "src": " ".join(x for x in (src, origin) if x), "module": module}
            if exp and not q["d"]["exp"]:
                q["d"]["exp"] = [{"t": t} for t in exp.splitlines() if t.strip()]
                orig = "ABCDEFGH"[ans]
                if orig != letter:
                    q["d"]["exp"].insert(0, {"t": f"注：解析按原题的选项顺序写，原题的 {orig} 项就是本题的 {letter} 项。"})
            break


# ---------------------------------------------------------------- 算式

UNIT = {"万亿": 1e12, "亿": 1e8, "万": 1e4, "千": 1e3}
NUM_RE = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*(%|万亿|亿|万|千)?\s*(?:元|人|个|件|吨|美元|亿元|万元)?\s*$")


def _expr_value(expr):
    """只认数字、小数、%、× ÷ + - 和括号、分数；能算出来就返回数值。"""
    e = frac_plain(expr).replace(" ", "").replace("（", "(").replace("）", ")")
    e = e.rstrip("=≈").strip()
    if not e or not re.fullmatch(r"[\d.%×÷*/+\-()]+", e) or not re.search(r"\d", e):
        return None
    if not re.search(r"[×÷*/+\-%]", e):
        return None
    py = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", e).replace("×", "*").replace("÷", "/")
    try:
        v = eval(py, {"__builtins__": {}}, {})  # noqa: S307 —— 上面已限定只含数字和运算符
    except Exception:  # noqa: BLE001
        return None
    return float(v) if isinstance(v, (int, float)) else None


def _opt_value(text):
    m = NUM_RE.match(text or "")
    if not m:
        return None
    num = float(re.match(r"\s*([-+]?\d+(?:\.\d+)?)", text).group(1))
    unit = m.group(1)
    if unit == "%":
        return num / 100
    return num * UNIT.get(unit, 1)


def _fmt(v):
    if abs(v) >= 1000:
        return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 or abs(v) >= 10000 else f"{v:,.1f}"
    return f"{v:.4g}" if abs(v) < 1 else (f"{v:.2f}".rstrip("0").rstrip("."))


def _compute_choice(q):
    """纯计算题：算出结果，选最接近的选项（差得明显才敢选）。资料给了答案但没解析的，补上计算过程。"""
    stem = Q_LABEL_RE.sub("", q["d"]["stem"]).strip()
    stem = re.sub(r"^[（(][^）)]{0,16}[）)]", "", stem).strip()
    m = re.match(r"^(.+?)\s*(?:[=≈]\s*(?:[（(]\s*[）)])?\s*[?？]?\s*)?$", stem, re.S)
    if not m:
        return
    v = _expr_value(m.group(1))
    shown = frac_plain(m.group(1)).replace("/", " ÷ ").replace("×", " × ")
    if v is None or v == 0:
        return
    vals = [(a, _opt_value(o)) for a, o in q["d"]["opts"]]
    if any(x is None for _a, x in vals) or len(vals) < 2:
        return
    errs = sorted((abs(x - v) / abs(v), a, x) for a, x in vals)
    if q["d"]["ans"]:
        if errs[0][1] == q["d"]["ans"] and errs[0][0] < 0.03:
            opt = dict(q["d"]["opts"])[q["d"]["ans"]]
            q["d"]["exp"] = [{"t": f"精确计算：{shown} ≈ {_fmt(v)}，对应 {q['d']['ans']} 项 {opt}。"
                                   f"选项之间差距{'较大，估算到前两三位即可' if errs[1][0] > 0.05 else '较小，需要算到第三位左右'}。"}]
        return
    if errs[0][0] < 0.03 and (errs[1][0] > errs[0][0] * 2.5):
        a = errs[0][1]
        q["d"]["ans"] = a
        q["d"]["how"] = "软件计算"
        opt = dict(q["d"]["opts"])[a]
        q["d"]["exp"] = [{"t": f"直接按算式计算：{shown} ≈ {_fmt(v)}，最接近 {a} 项 {opt}。"
                               "（这道题资料里没给答案，是软件按算式算的；考场上要用估算、截位直除等方法快速得到。）"}]


def _pct_fraction(p):
    """百分数 → 最接近的简单分数（百化分）：33.3% → 1/3，12.5% → 1/8。"""
    x = p / 100
    best = None
    for den in range(2, 21):
        num = round(x * den)
        if num <= 0:
            continue
        err = abs(num / den - x) / x
        if err < 0.012 and Fraction(num, den).denominator == den:
            if best is None or den < best[1]:
                best = (num, den)
    return f"{best[0]}/{best[1]}" if best else None


UNDERLINE_RE = re.compile(r"_{3,}\s*(?=[\u4e00-\u9fff“\"《（(\dA-Za-z])")


def _drop_underlines(text):
    """正文里给重点词加的下划线，取文字时变成了“____”紧贴在重点词前面（“号____‘东坡居士’”“____蔡伦改进了造纸术”）：
    这种不是填空，去掉。能算出答案的填空（“50%=____”）和后面是标点、空白的横线保留。"""
    def keep(m):
        left = text[:m.start()].rstrip()
        return m.group(0) if left.endswith(("=", "≈", "＝")) else ""
    return UNDERLINE_RE.sub(keep, text)


def blank_answers(text):
    """一行里每个填空横线的参考答案（算不出的为 None）。"""
    parts = re.split(r"_{3,}", text)
    answers = []
    for seg in parts[:-1]:
        left = re.split(r"[、，,；;：:\s]|(?<=[）)])", seg.rstrip())[-1] if seg.strip() else ""
        left = left.strip()
        if not left.endswith(("=", "≈")):
            answers.append(None)
            continue
        expr = left.rstrip("=≈").strip()
        pm = re.fullmatch(r"(\d+(?:\.\d+)?)%", expr)
        if pm:
            answers.append(_pct_fraction(float(pm.group(1))))
            continue
        v = _expr_value(expr)
        answers.append(_fmt(v) if v is not None else None)
    return answers


def plain(text):
    """存全文索引、给 AI 用的纯文字：分数写成 a/b。"""
    return frac_plain(text or "")


__all__ = ["group", "blank_answers", "plain", "FRAC_L", "FRAC_S", "FRAC_R"]
