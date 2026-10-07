"""行测真题解析：把真题卷 PDF + 答案解析（PDF / Word）变成可以在软件里做的题。

每道题保存：题干和选项文字（尽量还原）、原卷截图位置（页码 + 区域，界面上按需渲染，图形推理、
图表类题目也能完整显示）、所属模块与题型、答案和解析。资料分析等共用材料的题，材料单独成一条。
"""

import os
import re
from collections import Counter
from dataclasses import replace

from .pdftext import AD_RE, join_text, load_any, load_pdf

CN_NUM = "一二三四五六七八九十"

MODULE_KEYS = [
    ("政治理论", ["政治理论"]),
    ("常识判断", ["常识判断", "常识应用", "常识"]),
    ("言语理解与表达", ["言语理解", "言语表达", "言语"]),
    ("数量关系", ["数量关系", "数字推理", "数学运算", "数理", "数量"]),
    ("资料分析", ["资料分析"]),
    ("判断推理", ["判断推理", "图形推理", "定义判断", "类比推理", "逻辑判断", "演绎推理", "事件排序",
              "逻辑推理", "科学推理"]),
]
SUB_KEYS = [
    ("数字推理", ["数字推理"]), ("数学运算", ["数学运算"]),
    ("图形推理", ["图形推理"]), ("定义判断", ["定义判断"]), ("类比推理", ["类比推理"]),
    ("逻辑判断", ["逻辑判断", "演绎推理", "逻辑推理"]), ("事件排序", ["事件排序"]), ("科学推理", ["科学推理"]),
    ("逻辑填空", ["选词填空", "逻辑填空", "词语填空"]), ("片段阅读", ["片段阅读", "阅读理解", "篇章阅读"]),
    ("语句表达", ["语句表达", "语句排序", "语句填空"]),
]

SECTION_RE = re.compile(
    rf"^(第[{CN_NUM}]+部分|[{CN_NUM}]+\s*[、\.．]|[（(][{CN_NUM}]+[)）]|[{CN_NUM}]+\s*[:：])"
)
ANCHOR_RE = re.compile(r"^\s*(\d{1,3})\s*(?:[\.．、:：]\s*(?![\d％%])|(?=[{｛【\[［(（]\s*(?:单选|多选|单项|不定项)))")
QTYPE_TAG_RE = re.compile(r"^\s*[{｛【\[［(（]\s*(?:单选|多选|单项选择|单项|不定项)题?\s*[}｝】\]］)）]\s*")
OPT_RE = {k: re.compile(rf"(?<![A-Za-z]){k}\s*[\.．、:：]") for k in "ABCD"}
OPT_LOOSE_RE = {k: re.compile(rf"(?:^|(?<=\s))({k})(?=[^\sA-Za-z\.．、:：,，])", re.M) for k in "ABCD"}
MATERIAL_START_RE = re.compile(
    rf"(根据.{{0,20}}(资料|材料|图|表|文字|下文|短文|内容).{{0,12}}回答)|"
    rf"(回答\s*\d+\s*[-~～—至到]+\s*\d+)|(^[（(][{CN_NUM}][)）])|(^[{CN_NUM}]、\s*根据)"
)
EXPLAIN_START_RE = re.compile(r"^\s*(【\s*(解析|答案|参考答案|正确答案|精析|点拨)\s*】|(解析|答案|参考答案|正确答案)\s*[:：]|故正确答案)")
RANGE_RE = re.compile(r"(\d{1,3})\s*[-~～—至到]+\s*(\d{1,3})\s*题")
INSTR_RE = re.compile(
    r"根据题目要求|最恰当的答案|本部分包括|参考时限|共\s*\d+\s*题|每道题|每题|请开始答题|所给出的图、表|"
    r"要你回答|要求你|选出一个|在这部分试题中|仔细观察|严格依据|你的任务|你需要|请你|例题|例：|【例】|"
    r"答案[：:是为]|正确答案|故选|应选|请从|作答时间|题量"
)


def detect_module(text):
    t = re.sub(r"\s+", "", text)
    for mod, keys in MODULE_KEYS:
        if any(k in t for k in keys):
            return mod
    return None


def detect_sub(text):
    """标题里只点名了一个题型时才算（“本部分包括图形推理、定义判断……”不算）。"""
    t = re.sub(r"\s+", "", text)
    found = [sub for sub, keys in SUB_KEYS if any(k in t for k in keys)]
    return found[0] if len(found) == 1 else None


def guess_sub(module, stem, options=None):
    """新卷子不再标题型，按题干特征推断，供按题型筛选。"""
    s = re.sub(r"\s+", "", stem or "")
    opts = options or []
    if module == "判断推理" and (re.search(r"相当于|对于[（(]", s) or (
            len(s) < 30 and sum(1 for o in opts if re.search(r"[：:]", o)) >= 3)):
        return "类比推理"
    if module == "言语理解与表达":
        if re.search(r"填入(画|划)?横线|填入括号|依次填入|横线(处|部分)", s):
            return "逻辑填空"
        if re.search(r"排序|重新排列|语序|衔接|填入.*(处|位置)|最恰当的一项是|下一段", s):
            return "语句表达"
        return "片段阅读"
    if module == "判断推理":
        if re.search(r"定义|是指|指的是", s):
            return "定义判断"
        if re.search(r"逻辑关系|最为贴近|相似或接近|对应关系", s):
            return "类比推理"
        if re.search(r"问号处|规律性|一定的规律|呈现|折叠|立体|视图|截面|展开图|图形", s) or len(s) < 45:
            return "图形推理"
        return "逻辑判断"
    if module == "数量关系":
        if len(s) < 60 and re.search(r"[（(]\s*[）)]|？", s) and re.search(r"\d+[，,、]\s*\d+[，,、]", s):
            return "数字推理"
        return "数学运算"
    return None


BARE_SECTION_RE = re.compile(
    r"^(政治理论|常识判断|言语理解与表达|言语理解|数量关系|判断推理|资料分析)([(（]?(共\s*\d+\s*题|\d+\s*题)[^)）]*[)）]?)?[。.:：]?$"
)


def section_of(line_text):
    """若是大题标题行（第一部分 常识判断 / 二、言语理解与表达 / 单独一行“常识判断”），返回模块名。"""
    t = re.sub(r"\s+", "", line_text)
    if BARE_SECTION_RE.match(t):
        return detect_module(t)
    if len(t) > 160 or not SECTION_RE.match(t):
        return None
    if MATERIAL_START_RE.search(t) and not re.search(r"资料分析", t):
        return None
    return detect_module(t[:40])


def paper_meta(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    m = re.search(r"(20\d\d)", name)
    year = int(m.group(1)) if m else 0
    level = ""
    for key, val in [("副省", "副省级"), ("省部", "副省级"), ("省级", "副省级"), ("地市", "地市级"), ("市地", "地市级"),
                     ("行政执法", "行政执法"), ("县乡", "县乡级"), ("乡镇", "乡镇卷"), ("省市", "省市卷"),
                     ("选调", "选调"), ("招警", "招警"), ("A卷", "A卷"), ("B卷", "B卷"), ("C卷", "C卷"),
                     ("（一）", "卷一"), ("（二）", "卷二"), ("上半年", "上半年"), ("下半年", "下半年")]:
        if key in name and val not in level:
            level = (level + " " + val).strip()
    d = re.search(r"20\d\d\s*年?\s*(\d{3,4})(?![\d年])", name)
    return {"name": name, "year": year, "level": level, "date": d.group(1) if d else ""}


# ---------------------------------------------------------------- 试卷

def _find_options(text):
    """从末尾往前依次找 D、C、B、A 选项标记，返回 (题干, [四个选项]) 或 None。

    先找带标点的“A.”“A、”，找不到再找不带标点、前面是空白或行首的“A总书记 B中央…”。
    """
    for table in (OPT_RE, OPT_LOOSE_RE):
        pos = {}
        end = len(text)
        for k in "DCBA":
            found = None
            for m in table[k].finditer(text, 0, end):
                found = m
            if not found:
                break
            pos[k] = found
            end = found.start()
        if len(pos) < 4:
            continue
        stem = text[: pos["A"].start()].strip()
        opts = []
        for i, k in enumerate("ABCD"):
            s = pos[k].end()
            e = pos["ABCD"[i + 1]].start() if i < 3 else len(text)
            opts.append(re.sub(r"\s+", " ", text[s:e]).strip())
        if all(opts) or table is OPT_RE:
            return stem, opts
    return None


def _has_opt_d(text):
    return (bool(OPT_RE["D"].search(text)) and bool(OPT_RE["A"].search(text))) or         (bool(OPT_LOOSE_RE["D"].search(text)) and bool(OPT_LOOSE_RE["A"].search(text)))


def _line_has_d(text):
    return bool(OPT_RE["D"].search(text) or OPT_LOOSE_RE["D"].search(text))


def _anchor_chain(cands):
    """在候选题号里挑出最可信的一串递增题号（动态规划）。

    cands: [(题号, 行号, 权重, 与上一候选之间是否出现过大题标题)]。允许缺号（整题是图片时没有文字题号）
    和分部分重新从 1 编号，但都要扣分；权重低的候选（缩进不对、题号后紧跟数字）只在顺得上时才会被选中。
    """
    n = len(cands)
    if not n:
        return []
    best = [0.0] * n
    prev = [-1] * n
    sec_prefix = [0] * (n + 1)
    for i, c in enumerate(cands):
        sec_prefix[i + 1] = sec_prefix[i] + (1 if c[3] else 0)
    for j in range(n):
        num_j, _, w_j, _ = cands[j]
        best[j] = w_j - 0.2 * (num_j - 1) - (0.5 if num_j > 1 else 0)
        for i in range(max(0, j - 400), j):
            num_i = cands[i][0]
            if num_i < num_j <= num_i + 15:
                s = best[i] + w_j - 0.2 * (num_j - num_i - 1)
            elif num_j == 1 and num_i >= 5 and sec_prefix[j + 1] - sec_prefix[i + 1] > 0:
                s = best[i] + w_j - 0.8
            else:
                continue
            if s > best[j]:
                best[j], prev[j] = s, i
    j = max(range(n), key=lambda k: best[k])
    chain = []
    while j >= 0:
        chain.append(cands[j][1])
        j = prev[j]
    return chain[::-1]


ANCHOR_ALONE_RE = re.compile(r"^\s*(\d{1,3})\s*[\.．、]?\s*$")
ANCHOR_WEAK_RE = re.compile(r"^\s*(\d{1,3})\s*[\.．、:：]")
ANCHOR_SPACE_RE = re.compile(r"^\s*(\d{1,3})\s+(?=[一-鿿（(“\"《A-Za-z\d])")


def _anchor_num(text):
    for rx in (ANCHOR_RE, ANCHOR_ALONE_RE, ANCHOR_WEAK_RE, ANCHOR_SPACE_RE):
        m = rx.match(text)
        if m:
            return int(m.group(1))
    return None


def _strip_anchor(text):
    for rx in (ANCHOR_RE, ANCHOR_ALONE_RE, ANCHOR_WEAK_RE, ANCHOR_SPACE_RE):
        if rx.match(text):
            return rx.sub("", text, count=1)
    return text


LINE_OPT_RE = {k: re.compile(rf"^\s*{k}(?:\s*[\.．、:：]|(?=[^\sA-Za-z]))") for k in "ABCD"}


def _fill_missing(lines, chain):
    """原卷漏印题号时（如 2023 地市卷第 5 题），在前一题区域里找第二组完整的 A–D 选项，从其后切出缺的题。"""
    out = []
    for ci, (start, num) in enumerate(chain):
        out.append((start, num))
        if ci + 1 >= len(chain):
            continue
        end, nxt = chain[ci + 1]
        missing = nxt - num - 1
        if missing <= 0 or missing > 3:
            continue
        splits = []
        seen = set()
        for k in range(start + 1, min(end, len(lines) - 1)):
            for letter in "ABCD":
                if LINE_OPT_RE[letter].match(lines[k].text) or OPT_RE[letter].search(lines[k].text):
                    seen.add(letter)
            if seen >= set("ABCD") and _line_has_d(lines[k].text):
                nxt_line = lines[k + 1]
                if not any(LINE_OPT_RE[x].match(nxt_line.text) for x in "ABCD"):
                    ok = nxt_line.tag != "ad" and not section_of(nxt_line.text)
                    splits.append((k + 1, ok))
                    seen = set()
        # 最后一组选项属于区域里最后一道题，前面每组之后才是漏号的题
        splits = [k for k, ok in splits[:-1] if ok]
        for j, k in enumerate(splits[:missing]):
            out.append((k, num + j + 1))
    return out


HEADER_GLUED_RE = re.compile(
    rf"^\s*((?:第[{CN_NUM}]+部分|[{CN_NUM}]+\s*[、\.．])\s*[:：]?\s*(?:政治理论|常识判断|言语理解与表达|数量关系|判断推理|资料分析)"
    rf"[^\d]{{0,40}}?)\s*(\d{{1,3}}\s*[\.．、].*)$"
)


def _split_glued(lines):
    """大题标题和第一题被排在同一行（“第三部分言语理解与表达36．……”）时拆成两行。"""
    out = []
    for ln in lines:
        m = HEADER_GLUED_RE.match(ln.text)
        if m:
            out.append(replace(ln, text=m.group(1)))
            out.append(replace(ln, text=m.group(2), y0=ln.y0 + 0.01))
        else:
            out.append(ln)
    return out


def parse_paper(path):
    doc = load_pdf(path)
    lines = _split_glued([ln for ln in doc.all_lines() if ln.tag not in ("header", "footer")])
    left = doc.content_x[0]
    raw = []
    seen_section = False
    for i, ln in enumerate(lines):
        if section_of(ln.text):
            seen_section = True
        if ln.x0 > left + 45:
            continue
        if ANCHOR_RE.match(ln.text):
            w = 1.0
        elif ANCHOR_ALONE_RE.match(ln.text):
            w = 0.9
        elif ANCHOR_WEAK_RE.match(ln.text):
            w = 0.6
        elif ANCHOR_SPACE_RE.match(ln.text):
            w = 0.7
        else:
            continue
        raw.append([_anchor_num(ln.text), i, w, seen_section, ln.x0])
        seen_section = False
    # 题号通常对齐在同一列：偏离主列的候选降权（右对齐的题号位数不同，留出余量）
    if raw:
        xs = sorted(round(c[4]) for c in raw if c[2] == 1.0) or sorted(round(c[4]) for c in raw)
        mode_x = xs[len(xs) // 2]
        for c in raw:
            if abs(c[4] - mode_x) > 14:
                c[2] *= 0.5
    cands = [tuple(c[:4]) for c in raw]
    chain = _anchor_chain(cands)
    if not chain:
        return {"doc": doc, "questions": [], "materials": []}
    chain = _fill_missing(lines, [(idx, _anchor_num(lines[idx].text)) for idx in chain])

    # 第一题之前的大题标题决定起始模块
    module, sub = None, None
    for ln in lines[: chain[0][0]]:
        mod = section_of(ln.text)
        if mod:
            module = mod
            sub = detect_sub(ln.text) or sub
    # “第一部分”单独一行、模块名在下一行的老卷子
    def section_at(k):
        mod = section_of(lines[k].text)
        if mod:
            return mod, detect_sub(lines[k].text)
        if re.match(rf"^第[{CN_NUM}]+部分$", lines[k].clean):
            for j in range(k + 1, min(k + 3, len(lines))):
                mod = detect_module(lines[j].text[:30])
                if mod:
                    return mod, detect_sub(lines[j].text)
        return None, None

    if module is None:
        for k in range(chain[0][0]):
            mod, sb = section_at(k)
            if mod:
                module, sub = mod, sb or sub

    line_pos = {id(ln): k for k, ln in enumerate(lines)}
    questions, materials = [], []
    current_mat = None
    mat_left = 0  # 当前材料还能覆盖几道题（未写明题号范围时）
    seq = 0
    for ci, (start, num) in enumerate(chain):
        end = chain[ci + 1][0] if ci + 1 < len(chain) else len(lines)
        region = lines[start:end]
        seq += 1
        # 题目+解析合在一起的卷子：解析段落单独拿出来
        inline = None
        for k in range(1, len(region)):
            if EXPLAIN_START_RE.match(region[k].text):
                stop = len(region)
                for j in range(k + 1, len(region)):
                    if section_at(start + j)[0] or MATERIAL_START_RE.search(region[j].clean):
                        stop = j
                        break
                inline = region[k:stop]
                region = region[:k] + region[stop:]
                break
        # 选项结束位置：最后一个含 D 选项的行
        d_idx = None
        body_end = len(region)
        for k in range(len(region) - 1, -1, -1):
            if region[k].tag != "ad" and _line_has_d(region[k].text) \
                    and _has_opt_d("\n".join(r.text for r in region[: k + 1])):
                d_idx = k
                break
        tail_start = None
        if d_idx is not None:
            # D 选项可能折行：紧跟着、行距正常的续行也算选项（解析、大题标题、材料开头除外）
            j = d_idx + 1
            while j < len(region):
                prev, cur = region[j - 1], region[j]
                lh = max(prev.y1 - prev.y0, 1)
                if cur.tag == "ad":
                    j += 1
                    continue
                if (cur.page != prev.page or cur.y0 - prev.y1 > lh * 0.9
                        or section_at(line_pos[id(cur)])[0] or MATERIAL_START_RE.search(cur.clean)
                        or EXPLAIN_START_RE.match(cur.text) or _anchor_num(cur.text)):
                    break
                j += 1
            d_idx = j - 1
            tail_start = j
        else:
            for k in range(1, len(region)):
                if section_at(line_pos[id(region[k])])[0] or MATERIAL_START_RE.search(region[k].clean):
                    tail_start = k
                    break
        if tail_start is not None:
            body_end = tail_start
        body = [r for r in region[:body_end] if r.tag != "ad"]
        tail = [r for r in region[body_end:] if r.tag != "ad"] if tail_start is not None else []

        text = join_text(body)
        text = QTYPE_TAG_RE.sub("", _strip_anchor(text))
        parsed = _find_options(text)
        stem, options = (parsed if parsed else (text, None))

        mod_here = module or "常识判断"
        q = {
            "num": num, "seq": seq, "module": mod_here,
            "sub": sub or guess_sub(mod_here, stem, options),
            "stem": re.sub(rf"^\s*{num}\s*[\.．、:：]?\s*", "", stem.strip()) if num else stem.strip(),
            "options": options,
            # 截图到下一题为止；卷子里题后紧跟着答案解析时，截到答案之前，不能把答案截进去
            "crop": _crop(doc, region[0], body[-1] if body else region[0],
                          inline[0] if inline else (lines[end] if end < len(lines) else None), d_idx is not None),
        }
        if inline:
            ex = join_text([r for r in inline if r.tag != "ad"])
            q["inline_answer"] = _answer_in(ex)
            ex = re.sub(r"^\s*[【\[]?(参考答案|正确答案|答案)[】\]]?\s*[:：]?\s*[A-D]{1,4}\s*", "", ex)
            ex = re.sub(r"^\s*【?解析】?\s*[:：]?\s*", "", ex).strip()
            # “暂无解析”之类的占位文字不算解析
            q["inline_explain"] = "" if re.fullmatch(r"[\s（(]*(暂无解析|无|略|暂无)?[)）\s]*", ex) else ex
        if current_mat and (current_mat["range"] and current_mat["range"][0] <= num <= current_mat["range"][1]
                            or not current_mat["range"] and mat_left > 0):
            q["material"] = current_mat["id"]
            mat_left -= 1
        questions.append(q)

        # 题目后面的内容：大题标题、说明、下一组题的共用材料
        mat_lines = []
        instructions_mode = False
        for k, r in enumerate(tail):
            mod, sb = section_at(line_pos[id(r)]) if tail_start is not None else (None, None)
            if mod:
                if mod != module:
                    current_mat, mat_left = None, 0
                module, sub = mod, sb
                instructions_mode = True
                mat_lines = []
                continue
            sb = detect_sub(r.text) if SECTION_RE.match(r.clean) and len(r.clean) < 120 else None
            if sb and not MATERIAL_START_RE.search(r.clean):
                sub = sb
                instructions_mode = True
                continue
            if MATERIAL_START_RE.search(r.clean):
                instructions_mode = False
                mat_lines.append(r)
                continue
            if instructions_mode and not mat_lines:
                continue
            if not mat_lines and INSTR_RE.search(r.text):
                continue
            mat_lines.append(r)
        mat_text = join_text(mat_lines)
        if mat_lines and (len(re.sub(r"\s+", "", mat_text)) >= 30 or MATERIAL_START_RE.search(mat_lines[0].clean)):
            rng = RANGE_RE.search(mat_text[:80])
            mid = f"m{len(materials) + 1}"
            nxt_line = lines[end] if end < len(lines) else None
            current_mat = {
                "id": mid, "text": mat_text, "module": module,
                "range": [int(rng.group(1)), int(rng.group(2))] if rng else None,
                "crop": _crop(doc, mat_lines[0], mat_lines[-1], nxt_line, False),
            }
            mat_left = 5
            materials.append(current_mat)
        elif current_mat and not current_mat["range"] and module != current_mat["module"]:
            current_mat = None
    for m in materials:
        m.pop("module", None)
    _fix_modules(questions, materials, paper_meta(path)["year"])
    return {"doc": doc, "questions": questions, "materials": materials}


def classify_content(q, mat_text=""):
    """没有大题标题的卷子，按题干内容推断模块。"""
    s = re.sub(r"\s+", "", q.get("stem") or "")
    opts = "".join(q.get("options") or [])
    if mat_text and re.search(r"增长|同比|比重|百分点|%|亿元|万元|万人|万吨|倍", s + mat_text[:400])             and len(re.findall(r"\d", mat_text)) > 20:
        return "资料分析"
    if re.search(r"填入(画|划)?横线|依次填入|这段文字|文段|意在|作者|主旨|标题|与原文|语句|排序|下一段|"
                 r"最恰当的一项|空缺处|衔接", s):
        return "言语理解与表达"
    if re.search(r"如果为真|削弱|加强|支持|反驳|前提|假设|推出|能够得出|结论|定义|是指|逻辑关系|问号处|"
                 r"规律|图形|折叠|立体|类比|对应|最为贴近|相似或接近|推理|说谎|真话|假话", s):
        return "判断推理"
    if len(re.findall(r"\d", s)) >= 2 and re.search(
            r"多少|几(个|人|天|种|次|元|米|分钟|小时|岁|名|辆|台|块|位)|概率|至少|最多|最少|平均|百分之|"
            r"[（(]\s*[）)]|？", s) and re.search(r"\d", opts or s):
        return "数量关系"
    if re.search(r"习近平|总书记|党的|二十大|二十届|十九大|马克思|中国特色社会主义|新时代|全会|党中央|中共中央", s):
        return "政治理论"
    return "常识判断"


def _fix_modules(questions, materials, year):
    """大题标题识别失败（只有一两个模块，或某模块题量离谱）时，改按题干内容推断，再做邻近平滑。"""
    from collections import Counter

    cnt = Counter(q["module"] for q in questions)
    if len(questions) < 20 or (len(cnt) >= 4 and max(cnt.values()) <= 60):
        return
    mats = {m["id"]: m["text"] for m in materials}
    labels = [classify_content(q, mats.get(q.get("material"), "")) for q in questions]
    if year and year < 2024:
        labels = ["常识判断" if x == "政治理论" else x for x in labels]
    # 模块成块出现：用前后各 3 题的多数票平滑两遍
    for _ in range(2):
        out = []
        for i in range(len(labels)):
            win = labels[max(0, i - 3): i + 4]
            top, n = Counter(win).most_common(1)[0]
            out.append(top if n >= 4 else labels[i])
        labels = out
    for q, lab in zip(questions, labels):
        if q["module"] != lab:
            q["module"] = lab
            q["sub"] = guess_sub(lab, q["stem"], q["options"])


def _crop(doc, first, last, next_line, tight):
    """题目在原卷上的区域：[(页, x0, y0, x1, y1), …]，可能跨页。"""
    x0, x1 = doc.content_x
    pad = 6
    segs = []
    p0, p1 = first.page, last.page
    if not tight and next_line is not None:
        p1 = next_line.page
    for p in range(p0, p1 + 1):
        w, h = doc.sizes[p]
        top_lim = max([l.y1 for l in doc.pages[p] if l.tag == "header"] + [h * 0.03]) + 2
        bot_lim = min([l.y0 for l in doc.pages[p] if l.tag == "footer"] + [h * 0.97]) - 2
        y0 = first.y0 - 3 if p == p0 else top_lim
        if p == p1:
            if tight or next_line is None:
                y1 = last.y1 + 4 if last.page == p else bot_lim
                if next_line is None and not tight:
                    y1 = bot_lim
            else:
                y1 = next_line.y0 - 2 if next_line.page == p else bot_lim
        else:
            y1 = bot_lim
        if y1 - y0 > 4:
            segs.append([p, round(max(0, x0 - pad), 1), round(max(0, y0), 1),
                         round(min(w, x1 + pad), 1), round(min(h, y1), 1)])
    return segs


# ---------------------------------------------------------------- 答案解析

ANS_PATTERNS = [
    re.compile(r"(?:正确答案|参考答案|本题答案|答案)\s*(?:为|是|：|:|应为|应选|选)?\s*[:：]?\s*[【\[［]?\s*([A-D])(?![A-Za-z])"),
    re.compile(r"【[^】]{0,8}答案】\s*([A-D])"),
    re.compile(r"【解析】\s*([A-D])[。.．，,\s]"),
    re.compile(r"选择\s*([A-D])\s*选?项"),
    re.compile(r"(?:故|因此|所以)?(?:本题)?(?:应)?选\s*([A-D])(?:项|选项)?(?:[。.，,；;\s]|$)"),
    re.compile(r"([A-D])\s*(?:项|选项)?\s*(?:当选|正确，?当选|为正确答案)"),
]
ANS_ANCHOR_RE = re.compile(
    r"^\s*(?:第\s*)?[【\[［]?\s*(?:题目|第)?\s*(\d{1,3})\s*(?:题)?\s*[】\]］]?\s*(?:[\.．、:：]|【|［|\[|解析|答案|\s|$|(?=[A-D](?![A-Za-z]))|(?=本题|正确答案|参考答案|故))"
)
INLINE_ANS_RE = re.compile(
    r"^\s*[【\[［]?\s*(?:题目|第)?\s*(\d{1,3})\s*(?:题)?\s*[】\]］]?\s*[\.．、:：]?\s*[【\[［]?\s*(?:答案|参考答案)?\s*[】\]］]?\s*[:：]?\s*"
    r"([A-D]{1,4})\s*[】\]］]?\s*(?:$|【|［|\[|解析|[。．.，,;；\s])"
)
QUICK_RE = re.compile(r"【?\s*(\d{1,3})\s*[-~～—–]\s*(\d{1,3})\s*】?\s*[:：]?\s*([A-D]{2,10})")
LEAD_ANS_RE = re.compile(r"^\s*[【\[［]?\s*\d{1,3}\s*[】\]］]?\s*[\.．、]?\s*【解析】\s*[A-D]")
EXPLAIN_HEAD_RE = re.compile(r"^\s*[【\[［]?\s*(解析|答案解析|参考解析)\s*[】\]］]?\s*[:：]?\s*$")


def _answer_in(text):
    best = None
    for pat in ANS_PATTERNS:
        for m in pat.finditer(text):
            if best is None or m.start() >= best[0]:
                best = (m.start(), m.group(1))
        if best:
            return best[1]
    return None


def _quick_answers(lines):
    out = {}
    for ln in lines[:400]:
        for m in QUICK_RE.finditer(ln.clean):
            a, b, letters = int(m.group(1)), int(m.group(2)), m.group(3)
            if b - a + 1 == len(letters):
                for i, ch in enumerate(letters):
                    out[a + i] = ch
    # 表格式：一行题号、一行答案
    for i in range(len(lines) - 1):
        nums = re.findall(r"\d{1,3}", lines[i].text)
        lets = re.findall(r"\b[A-D]\b", lines[i + 1].text)
        if len(nums) >= 5 and len(nums) == len(lets) and re.fullmatch(r"[\d\s]+", lines[i].text.strip()):
            ns = [int(n) for n in nums]
            if all(ns[k] + 1 == ns[k + 1] for k in range(len(ns) - 1)):
                for n, ch in zip(ns, lets):
                    out.setdefault(n, ch)
    return out


def _sequential_answers(lines, expected):
    """题号没有文字层（印成图片）时的兜底：按“故正确答案为X”逐段切分，段数与题量一致才采用。"""
    blocks, cur = [], []
    for ln in lines:
        cur.append(ln.text)
        if re.search(r"(正确答案|本题答案|答案)\s*(为|是)\s*[A-D]|选择\s*[A-D]\s*选?项", ln.text):
            blocks.append(cur)
            cur = []
    if not expected or len(blocks) != expected:
        return {}
    out = {}
    for i, b in enumerate(blocks, 1):
        text = join_text([t for t in b if not AD_RE.search(t)])
        text = re.sub(r"^\s*([A-D]\s*)+", "", text)
        text = re.sub(r"^\s*(【?解析】?|解析[:：]?)\s*", "", text)
        out[i] = {"answer": _answer_in("\n".join(b)), "explain": text.strip()}
    return out


def _anchor_sig(text):
    """锚点的书写格式：题号前后的符号（“12、”“【12】”“12．”…），用来区分真题号和解析里的编号。"""
    m = re.match(r"^\s*([【\[［]?)\s*(?:题目|第)?\s*\d{1,3}\s*(\S?)", text)
    if not m:
        return None
    tail = m.group(2) if m.group(2) and not re.match(r"[\u4e00-\u9fffA-D]", m.group(2)) else ""
    return m.group(1) + "|" + tail


def parse_answers(path, expected_max=0):
    doc = load_any(path)
    lines = [ln for ln in doc.all_lines() if ln.tag not in ("header", "footer", "ad")]
    quick = _quick_answers(lines)
    inline_style = sum(1 for ln in lines if INLINE_ANS_RE.match(ln.text)) >= 10
    cands = []
    for i, ln in enumerate(lines):
        m = ANS_ANCHOR_RE.match(ln.text)
        if m and (doc.content_x[1] == 0 or ln.x0 <= doc.content_x[0] + 40):
            cands.append((int(m.group(1)), i))
    # 逐题挑锚点：下一题的锚点必须出现在本题答案之后，避免把解析里的“1、2、3”当成题号
    chosen = []
    expected = 1
    sigs = Counter(_anchor_sig(lines[i].text) for _n, i in cands)
    major_sig = sigs.most_common(1)[0][0] if sigs else None

    def acceptable(num, idx):
        if inline_style and not (INLINE_ANS_RE.match(lines[idx].text) or LEAD_ANS_RE.match(lines[idx].text)):
            return False
        if not chosen:
            return True
        prev_num, prev_idx = chosen[-1]
        seg = "\n".join(l.text for l in lines[prev_idx:idx])
        if _answer_in(seg) or INLINE_ANS_RE.match(lines[prev_idx].text) or prev_num in quick:
            return True
        return num == prev_num + 1 and idx - prev_idx >= 2 and _anchor_sig(lines[idx].text) == major_sig

    ci = 0
    while ci < len(cands):
        # 在后面一小段候选里先找正好是下一题的；找不到再接受跳过几题的（个别题号没有文字层）
        wide = [(k, c) for k, c in enumerate(cands[ci: ci + 80], ci)]
        pick = next(((k, c) for k, c in wide if c[0] == expected and acceptable(*c)), None)
        if pick is None:
            gaps = [(k, c) for k, c in wide[:12] if expected < c[0] <= expected + 4 and acceptable(*c)]
            pick = min(gaps, key=lambda kc: (kc[1][0], kc[0])) if gaps else None
        if pick is None:
            ci += 1
            continue
        k, (num, idx) = pick
        chosen.append((num, idx))
        expected = num + 1
        ci = k + 1
    out = {}
    for k, (num, idx) in enumerate(chosen):
        end = chosen[k + 1][1] if k + 1 < len(chosen) else len(lines)
        seg_lines = lines[idx:end]
        seg_text = "\n".join(l.text for l in seg_lines)
        m = INLINE_ANS_RE.match(seg_lines[0].text)
        multi = m.group(2) if m and len(m.group(2)) > 1 else ""
        ans = None if multi else ((m.group(2) if m else None) or _answer_in(seg_text) or quick.get(num))
        first = ANS_ANCHOR_RE.sub("", seg_lines[0].text, count=1)
        if m:
            first = ""
        body = [first] + [l.text for l in seg_lines[1:]]
        explain = join_text([b for b in body if b.strip() and not AD_RE.search(b)])
        explain = re.sub(r"^\s*(【?解析】?|解析[:：]?)\s*", "", explain)
        if multi:
            explain = f"（多选题，参考答案：{multi}）\n" + explain
        out[num] = {"answer": ans, "explain": explain.strip(), "multi": multi}
    for num, ch in quick.items():
        out.setdefault(num, {"answer": ch, "explain": ""})
        if not out[num]["answer"]:
            out[num]["answer"] = ch
    got = sum(1 for v in out.values() if v.get("answer"))
    if expected_max and got < expected_max * 0.5:
        seq = _sequential_answers(lines, expected_max)
        if seq:
            return seq
    return out


# ---------------------------------------------------------------- 发现、配对、生成题库

LEVEL_SLUG = {"副省级": "fs", "地市级": "ds", "行政执法": "zf", "县乡级": "xx", "乡镇卷": "xz", "省市卷": "ss",
              "选调": "xd", "招警": "zj", "A卷": "a", "B卷": "b", "C卷": "c", "卷一": "j1", "卷二": "j2",
              "上半年": "sb", "下半年": "xb"}


def classify_file(rel):
    """按文件名和所在文件夹判断：行测真题卷 / 答案解析 / 题目+答案合订，及考试类别。返回 None 表示不是行测真题。"""
    parts = rel.replace("/", "\\").split("\\")
    name = os.path.splitext(parts[-1])[0]
    parent = parts[-2] if len(parts) > 1 else ""
    if not re.search(r"20\d\d", name) or "行测" not in name + parent or not re.search(r"\.(pdf|docx)$", rel, re.I):
        return None
    if re.search(r"申论|面试|模拟|预测|押题|笔记|讲义|千题|万题|题本", name):
        return None
    if "四川" in rel:
        exam = "四川"
    elif re.search(r"国考|国家", rel):
        exam = "国考"
    else:
        return None
    if re.search(r"答案|解析", parent):
        kind = "answer"
    elif re.search(r"(真题|试题|行测)及(参考)?答案", name):
        kind = "combined"
    elif re.search(r"答案|解析", name):
        kind = "answer"
    else:
        kind = "paper"
    meta = paper_meta(name)
    return {"rel": rel, "kind": kind, "exam": exam, **meta}


def _level_key(level):
    keep = [t for t in level.split() if t not in ("上半年", "下半年")]
    return " ".join(sorted(keep))


def pair_files(entries):
    """给每份试卷找对应的答案文件（同考试、同年份，卷别一致，再按文件名相似度）。"""
    from difflib import SequenceMatcher

    papers = [e for e in entries if e["kind"] in ("paper", "combined")]
    answers = [e for e in entries if e["kind"] == "answer"]
    used = set()
    out = []
    for p in sorted(papers, key=lambda e: e["rel"]):
        if p["kind"] == "combined":
            out.append((p, None))
            continue
        cands = [a for a in answers if a["exam"] == p["exam"] and a["year"] == p["year"] and a["rel"] not in used]

        def score(a):
            sc = SequenceMatcher(None, p["name"], a["name"]).ratio()
            if a["level"] == p["level"]:
                sc += 1
            elif _level_key(a["level"]) == _level_key(p["level"]):
                sc += 0.6
            if os.path.dirname(os.path.dirname(a["rel"])) == os.path.dirname(os.path.dirname(p["rel"])):
                sc += 0.3
            if a["rel"].lower().endswith(".pdf"):
                sc += 0.05
            return sc

        best = max(cands, key=score) if cands else None
        if best and score(best) >= 0.9:
            used.add(best["rel"])
        else:
            best = None
        out.append((p, best))
    return out


def paper_id(p):
    slug = "".join(LEVEL_SLUG.get(t, "") for t in p["level"].split())
    date = p.get("date") or ""
    return f"{'gk' if p['exam'] == '国考' else 'sc'}{p['year']}{('-' + date) if date else ''}{slug}"


def paper_title(p):
    name = re.sub(r"[（(](答案|解析).*?[）)]|--考生回忆版|_Password_Removed|_\d{8}_\d+", "", p["name"])
    name = re.sub(r"\s+", "", name)
    return name


LETTER_IDX = {"A": 0, "B": 1, "C": 2, "D": 3}


def figure_flags(path, crops):
    """判断每个截图区域里有没有图片、图表或表格（有的话界面默认显示原卷截图）。"""
    import pymupdf

    out = []
    pages = {}
    try:
        d = pymupdf.open(path)
    except Exception:  # noqa: BLE001
        return [False] * len(crops)

    # 每页同一位置都有的图片是页眉横幅、logo，不算插图
    repeat = Counter()
    for pg in d:
        for key in {tuple(round(v) for v in i["bbox"]) for i in pg.get_image_info()}:
            repeat[key] += 1

    def page_info(pno):
        if pno not in pages:
            pg = d[pno]
            page_area = pg.rect.get_area()
            # 铺满整页的图片是水印或扫描底图，不算插图；同一页上同样大小的图片出现 4 次以上，
            # 是拼贴成整页底纹的水印小图，也不算
            rects = [pymupdf.Rect(i["bbox"]) for i in pg.get_image_info()
                     if d.page_count < 4 or repeat[tuple(round(v) for v in i["bbox"])] < 3]
            same = Counter((round(r.width), round(r.height)) for r in rects)
            imgs = [r for r in rects if r.get_area() < page_area * 0.6 and same[(round(r.width), round(r.height))] < 4]
            boxes, lines = [], []
            try:
                for dr in pg.get_drawings():
                    r = dr["rect"]
                    fill, stroke = dr.get("fill"), dr.get("color")
                    # Word 导出的 PDF 在每段文字后面垫白色底块，不是图
                    if stroke is None and (fill is None or min(fill) > 0.93):
                        continue
                    (lines if (r.width < 2.5 or r.height < 2.5) else boxes).append(r)
            except Exception:  # noqa: BLE001
                pass
            pages[pno] = (imgs, boxes, lines)
        return pages[pno]

    for segs in crops:
        fig = False
        for pno, x0, y0, x1, y1 in segs:
            if pno < 0 or pno >= d.page_count:
                continue
            R = pymupdf.Rect(x0, y0, x1, y1)
            imgs, boxes, lines = page_info(pno)
            if any((R & r).get_area() > 1500 for r in imgs):
                fig = True
            elif sum(1 for r in boxes if R.contains(r) and r.width > 12 and r.height > 12) >= 1:
                fig = True
            elif sum(1 for r in lines if R.intersects(r)) >= 6:
                fig = True
            if fig:
                break
        out.append(fig)
    d.close()
    return out


def build_paper(root, p, a):
    """解析一份试卷（及答案），返回 (paper, questions, materials)。"""
    res = parse_paper(os.path.join(root, p["rel"]))
    qs = res["questions"]
    if not qs:
        return None
    ans = {}
    if a:
        try:
            ans = parse_answers(os.path.join(root, a["rel"]), expected_max=len(qs))
        except Exception:  # noqa: BLE001 —— 答案文件坏了也保留题目
            ans = {}
    pid = paper_id(p)
    out_q, out_m = [], []
    mat_ids = {}
    for m in res["materials"]:
        mid = f"{pid}-{m['id']}"
        mat_ids[m["id"]] = mid
        out_m.append({"id": mid, "paper": pid, "title": "", "text": m["text"], "crop": m["crop"]})
    for q in qs:
        info = ans.get(q["num"]) or {}
        letter = info.get("answer") or q.get("inline_answer")
        explain = info.get("explain") or q.get("inline_explain") or ""
        item = {
            "id": f"{pid}-{q['num']:03d}", "paper": pid, "num": q["num"], "module": q["module"],
            "sub": q["sub"] or "", "stem": q["stem"], "options": q["options"],
            "answer": LETTER_IDX.get(letter) if letter else None, "explain": explain,
            "crop": q["crop"],
        }
        if q.get("material"):
            item["material"] = mat_ids[q["material"]]
        out_q.append(item)
    flags = figure_flags(os.path.join(root, p["rel"]), [q["crop"] for q in out_q] + [m["crop"] for m in out_m])
    for item, fig in zip(out_q + out_m, flags):
        if fig:
            item["fig"] = True
    for m in out_m:
        n = [q["num"] for q in out_q if q.get("material") == m["id"]]
        m["title"] = f"第 {min(n)}–{max(n)} 题材料" if n else "材料"
    from collections import Counter

    paper = {
        "id": pid, "title": paper_title(p), "exam": p["exam"], "year": p["year"], "level": p["level"],
        "file": p["rel"], "answer_file": a["rel"] if a else "",
        "count": len(out_q), "answered": sum(1 for q in out_q if q["answer"] is not None),
        "modules": dict(Counter(q["module"] for q in out_q)),
    }
    return paper, out_q, out_m


def _stem_key(stem):
    return "".join(re.findall(r"[一-鿿]", stem or ""))[:18]


def build_all(root, progress=None):
    """扫描资料文件夹，解析全部行测真题。返回 {"papers": [...], "questions": [...], "materials": [...]}。"""
    entries = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root)
            e = classify_file(rel)
            if e:
                entries.append(e)
    pairs = pair_files(entries)
    built = {}
    for i, (p, a) in enumerate(pairs):
        if progress:
            progress(i, len(pairs), p["name"])
        try:
            r = build_paper(root, p, a)
        except Exception as e:  # noqa: BLE001 —— 个别文件损坏不影响其他
            print("解析失败", p["rel"], e)
            continue
        if r:
            built.setdefault(r[0]["id"], []).append(r)
    papers, questions, materials = [], [], []
    for pid, versions in built.items():
        # 同一份卷子在不同文件夹里有多份：以题目最全、答案最多的为准，缺的答案从其他版本按题干补
        versions.sort(key=lambda r: (r[0]["answered"], r[0]["count"]), reverse=True)
        paper, qs, ms = versions[0]
        for other in versions[1:]:
            by_key = {_stem_key(q["stem"]): q for q in other[1] if q["answer"] is not None}
            by_num = {q["num"]: q for q in other[1]}
            for q in qs:
                src = by_key.get(_stem_key(q["stem"])) if len(_stem_key(q["stem"])) >= 8 else None
                if src is None and other[0]["count"] == paper["count"]:
                    src = by_num.get(q["num"])
                if src and q["answer"] is None and src["answer"] is not None:
                    q["answer"] = src["answer"]
                if src and not q["explain"] and src["explain"]:
                    q["explain"] = src["explain"]
        paper["answered"] = sum(1 for q in qs if q["answer"] is not None)
        papers.append(paper)
        questions += qs
        materials += ms
    papers.sort(key=lambda p: (p["exam"] != "国考", -p["year"], p["id"]))
    return {"papers": papers, "questions": questions, "materials": materials}
