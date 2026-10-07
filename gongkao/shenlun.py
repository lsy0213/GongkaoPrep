"""申论真题解析：给定资料、作答要求（逐题）、参考答案，转成申论练习的题组。"""

import os
import re

from .pdftext import AD_RE, join_text, load_any
from .realexam import paper_meta

CN = "一二三四五六七八九十"
CN_VAL = {c: i + 1 for i, c in enumerate(CN)}

MAT_HEAD_RE = re.compile(r"^\s*(?:[0-9一二三四五六]\s*[、.．]\s*)?【?\s*给定(?:资料|材料)\s*】?\s*[:：]?\s*$")
REQ_HEAD_RE = re.compile(r"^\s*(?:[0-9一二三四五六]\s*[、.．]\s*)?【?\s*(?:作答要求|申论要求)\s*】?\s*[:：]?\s*$")
Q_PAREN_RE = re.compile(r"^\s*[（(]\s*(\d{1,2})\s*[)）]")
Q_ARABIC_RE = re.compile(r"^\s*(?:第\s*)?(\d{1,2})\s*(?:题)?\s*[、.．:：](?!\d)")
ANS_MARK_RE = re.compile(r"^\s*【?\s*(?:参考答案|参考范文|答案|参考解析|解析|参考思路)\s*】?\s*[:：]?\s*$")
ANS_ARABIC_RE = re.compile(r"^\s*【?\s*(?:第\s*)?(\d{1,2})\s*(?:题)?\s*[、.．:：]?\s*(?:参考答案|答案|参考解析|解析)\s*】?")
ANS_HEAD_RE = re.compile(r"参考答案|答案及解析|参考解析|【解析】|参考范文|参考思路")
MAT_SPLIT_RE = re.compile(r"^\s*(?:【)?\s*(?:给定)?(?:资料|材料)\s*([0-9０-９]+|[一二三四五六七八九十]+)\s*(?:】)?\s*$")
MAT_INLINE_RE = re.compile(r"^\s*【?\s*(?:给定)?(?:资料|材料)\s*([0-9]{1,2}|[一二三四五六七八九十]{1,2})\s*】?\s*[.．、:：]\s*")
MAT_NUM_RE = re.compile(r"^\s*([0-9]{1,2})\s*[.．、]\s*(?=\S)")
Q_TOP_RE = re.compile(
    rf"^\s*(?:第\s*)?([{CN}]+)\s*(?:题)?\s*[、.．:：]|^\s*[（(]\s*([{CN}]+)\s*[)）]"
    rf"|^\s*【\s*(?:问题|题目|第)\s*([{CN}]+)\s*(?:题)?\s*】\s*$"
)
ANS_SPLIT_RE = re.compile(
    rf"^\s*(?:【\s*(?:问题|题目|第)?\s*([{CN}0-9]+)\s*(?:题)?\s*(?:参考答案|答案|解析)?\s*】"
    rf"|(?:第\s*)?([{CN}]+)\s*(?:题)?\s*[、.．:：]?\s*(?:参考答案|答案|参考解析|题目解析|解析)"
    rf"|[（(]\s*([{CN}]+)\s*[)）]\s*(?:参考答案|答案|参考解析|解析)?)"
)


def classify(question, words):
    q = question
    if re.search(r"文章|议论文|作文|自拟题目|自选角度", q) or (words and words >= 800):
        return "大作文"
    if re.search(r"拟写|起草|撰写|写一篇|写一份|讲话稿|发言稿|倡议书|提案|简报|编者按|宣传稿|短评|公开信|"
                 r"导言|讲解稿|说明|提纲|报告|建议书|方案|材料|稿", q) and re.search(r"假如你是|假设你是|作为|请你|以.{0,10}身份", q):
        return "贯彻执行"
    if re.search(r"建议|对策|措施|怎么办|如何解决|解决.{0,6}问题|做法.{0,4}借鉴", q):
        return "提出对策"
    if re.search(r"分析|理解|谈谈你对|解释|评价|看法|含义|启示|为什么|原因", q):
        return "综合分析"
    return "归纳概括"


def _num(tok):
    if not tok:
        return None
    tok = tok.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if tok.isdigit():
        return int(tok)
    if tok == "十":
        return 10
    if tok.startswith("十"):
        return 10 + CN_VAL.get(tok[1:], 0)
    return CN_VAL.get(tok[0])


def parse_shenlun(path):
    doc = load_any(path)
    lines = [ln for ln in doc.all_lines() if ln.tag not in ("header", "footer", "ad")]
    texts = [ln.text.strip() for ln in lines]
    mat_i = next((i for i, t in enumerate(texts) if MAT_HEAD_RE.match(t)), None)
    req_i = next((i for i, t in enumerate(texts) if REQ_HEAD_RE.match(t) and (mat_i is None or i > mat_i)), None)
    if req_i is None:
        # 没有“作答要求”标题：第一道带分值的题就是作答要求的开始
        heads, _rx = _top_heads(texts, need_score=True)
        if not heads or heads[0] < len(texts) * 0.25:
            return None
        req_i = heads[0] - 1
    if mat_i is None:
        # 没有“给定资料”标题：注意事项之后到作答要求之前都算资料
        note_end = 0
        for i, t in enumerate(texts[:req_i]):
            if re.search(r"注意事项|作答参考时限|答题纸|钢笔|满分", t):
                note_end = i + 1
        mat_i = note_end - 1
    ans_i = None
    for i in range(req_i + 1, len(texts)):
        t = texts[i]
        if ANS_HEAD_RE.search(t) and (len(t) < 40 or t.startswith("【")) and not re.search(r"作答|要求[:：]", t):
            ans_i = i
            break
    mat_lines = texts[mat_i + 1: req_i]
    req_lines = texts[req_i + 1: ans_i if ans_i else len(texts)]
    ans_lines = texts[ans_i:] if ans_i else []

    materials = _split_materials(mat_lines)
    questions = _split_questions(req_lines)
    if not questions or not materials:
        return None
    answers = _split_answers(ans_lines, questions)
    for i, q in enumerate(questions):
        q["reference"] = answers[i] if i < len(answers) else ""
    meta = paper_meta(path)
    return {"materials": materials, "questions": questions, **meta}


def _split_materials(lines):
    lines = [t for t in lines if t and not AD_RE.search(t)]
    heads = [i for i, t in enumerate(lines) if MAT_SPLIT_RE.match(t)]
    out = []
    if len(heads) >= 2:
        for k, h in enumerate(heads):
            end = heads[k + 1] if k + 1 < len(heads) else len(lines)
            n = _num(MAT_SPLIT_RE.match(lines[h]).group(1)) or k + 1
            out.append({"title": f"资料 {n}", "text": join_text(lines[h + 1:end])})
        pre = join_text(lines[:heads[0]]).strip()
        # 第一个标题前的短文字多半是试卷标题，长的才是资料的引言
        if heads[0] > 0 and len(pre) > 80:
            out[0]["text"] = pre + "\n" + out[0]["text"]
        return out
    # “材料1. 1.……”这种行首带“材料N”前缀的写法
    marks, expect = [], 1
    for i, t in enumerate(lines):
        m = MAT_INLINE_RE.match(t)
        if m and _num(m.group(1)) == expect:
            marks.append(i)
            expect += 1
    if len(marks) >= 2:
        for k, h in enumerate(marks):
            end = marks[k + 1] if k + 1 < len(marks) else len(lines)
            first = MAT_INLINE_RE.sub("", lines[h], count=1)
            first = re.sub(r"^\s*\d{1,2}\s*[.．、]\s*", "", first)
            out.append({"title": f"资料 {k + 1}", "text": join_text([first] + lines[h + 1:end])})
        return out
    # 资料以“1.”“2.”开头分段：只认从 1 开始连续递增的编号
    marks, expect = [], 1
    for i, t in enumerate(lines):
        m = MAT_NUM_RE.match(t)
        if m and int(m.group(1)) == expect:
            marks.append(i)
            expect += 1
    if len(marks) >= 2 and marks[0] <= 2:
        for k, h in enumerate(marks):
            end = marks[k + 1] if k + 1 < len(marks) else len(lines)
            body = [MAT_NUM_RE.sub("", lines[h], count=1)] + lines[h + 1:end]
            out.append({"title": f"资料 {k + 1}", "text": join_text(body)})
        return out
    text = join_text(lines)
    return [{"title": "给定资料", "text": text}] if text.strip() else []


SCORE_RE = re.compile(r"[（(]\s*\d+\s*分\s*[)）]")


def _has_score(lines, i):
    return bool(SCORE_RE.search("".join(lines[i:i + 4])))


def _top_heads(lines, need_score=False):
    """顶格题号：先认“一、”“（一）”，再认“1、”，最后认“（1）”。只取从 1 开始连续递增的。

    “（1）”也常用于作答要求里的小条目，所以这种写法要求题目附近写着分值。
    """
    styles = ((Q_TOP_RE, lambda m: _num(m.group(1) or m.group(2) or m.group(3)), need_score),
              (Q_ARABIC_RE, lambda m: int(m.group(1)), need_score),
              (Q_PAREN_RE, lambda m: int(m.group(1)), True))
    for rx, conv, scored in styles:
        heads, expect = [], 1
        for i, t in enumerate(lines):
            m = rx.match(t)
            if m and conv(m) == expect and (not scored or _has_score(lines, i)):
                heads.append(i)
                expect += 1
        if len(heads) >= 2 or (rx is not Q_TOP_RE and heads):
            return heads, rx
    return [], None


def _split_questions(lines):
    lines = [t for t in lines if t and not AD_RE.search(t)]
    heads, rx = _top_heads(lines)
    out = []
    for k, h in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        body = lines[h:end]
        text = join_text(body)
        text = rx.sub("", text, count=1).strip()
        text = re.sub(r"^【[^】]{1,10}】\s*", "", text)
        req = ""
        m = re.search(r"要求\s*[:：]", text)
        if m:
            text, req = text[: m.start()].strip(), text[m.end():].strip()
        full = text + req
        sc = re.search(r"[（(]\s*(\d+)\s*分\s*[)）]", full)
        wm = re.search(r"(?:不超过|不多于|字数在|总字数|篇幅)?\s*(\d{2,4})\s*(?:[-~～—至到]\s*(\d{3,4}))?\s*字", full)
        words = int(wm.group(2) or wm.group(1)) if wm else 0
        out.append({
            "question": re.sub(r"[（(]\s*\d+\s*分\s*[)）]", "", text).strip(),
            "requirement": req,
            "score": int(sc.group(1)) if sc else 0,
            "words": wm.group(0).strip() if wm else "",
            "type": classify(text, words),
        })
    return out


def _key(text):
    return re.sub(r"[^\u4e00-\u9fff]", "", text)[:10]


def _split_answers(lines, questions):
    lines = [t for t in lines if t and not AD_RE.search(t)]
    n = len(questions)
    if not lines:
        return []

    def cut(heads, strip_rx=None):
        out = []
        for k, h in enumerate(heads):
            end = heads[k + 1] if k + 1 < len(heads) else len(lines)
            body = list(lines[h:end])
            if strip_rx is not None:
                body[0] = strip_rx.sub("", body[0], count=1).strip()
            out.append(body)
        return out

    def clean(body):
        # 答案段落里重复抄写的下一题题目去掉
        keys = {_key(q["question"]) for q in questions if _key(q["question"])}
        out = []
        for t in body:
            if _key(re.sub(r"^\s*([一二三四五六七八九十]+|\d{1,2})\s*[、.．]", "", t)) in keys:
                break
            out.append(t)
        return join_text([t for t in out if t]).strip()

    # 1) 带题号的答案标题：【题目一参考答案】/ 一、参考答案 / 1、参考答案
    for rx, conv in ((ANS_SPLIT_RE, lambda m: _num(m.group(1) or m.group(2) or m.group(3))),
                     (ANS_ARABIC_RE, lambda m: int(m.group(1)))):
        heads, expect = [], 1
        for i, t in enumerate(lines):
            m = rx.match(t)
            if m and conv(m) == expect:
                heads.append(i)
                expect += 1
        if len(heads) >= max(2, n - 1) or (n == 1 and heads):
            return [clean(b) for b in cut(heads, rx)]
    # 2) 每题重抄题目、后跟单独一行“参考答案”
    marks = [i for i, t in enumerate(lines) if ANS_MARK_RE.match(t)]
    if len(marks) >= n:
        return [clean(lines[m + 1:(marks[k + 1] if k + 1 < len(marks) else len(lines))]) for k, m in enumerate(marks[-n:])]
    # 3) 顶格编号
    heads, rx = _top_heads(lines)
    if heads:
        return [clean(b) for b in cut(heads, rx)]
    return [join_text(lines[1:])] if n == 1 else []


SL_SLUG = {"副省级": "fs", "地市级": "ds", "行政执法": "zf", "县乡级": "xx", "乡镇卷": "xz", "省市卷": "ss",
           "选调": "xd", "上半年": "sb", "下半年": "xb", "A卷": "a", "B卷": "b", "C卷": "c"}


def discover(root):
    """找出全部申论真题文件，按卷子分组：{卷子 id: [候选文件, …]}（同一份卷子常有多份拷贝）。"""
    groups = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if not re.search(r"\.(pdf|docx)$", f, re.I) or "申论" not in f or not re.search(r"20\d\d", f):
                continue
            if re.search(r"范文|素材|模板|押题|预测|热点|笔记|技巧|讲义|规范词|金句|100题|答题纸", f):
                continue
            rel = os.path.relpath(os.path.join(dp, f), root)
            exam = "四川" if "四川" in rel else ("国考" if re.search(r"国考|国家", rel) else None)
            if not exam:
                continue
            meta = paper_meta(f)
            date = meta.get("date") or ""
            slug = "".join(SL_SLUG.get(t, "") for t in meta["level"].split())
            sid = f"sl-{'gk' if exam == '国考' else 'sc'}{meta['year']}{('-' + date) if date else ''}{slug}"
            groups.setdefault(sid, []).append({"id": sid, "rel": rel, "exam": exam, **meta})
    return groups


def _quality(r):
    qs = r["questions"]
    return (sum(1 for q in qs if q["reference"]), len(qs), sum(1 for q in qs if q["score"]), len(r["materials"]))


def build_all(root, progress=None):
    groups = discover(root)
    sets = []
    for i, (sid, cands) in enumerate(sorted(groups.items())):
        if progress:
            progress(i, len(groups), cands[0]["name"])
        best, best_it = None, None
        # PDF 优先，其次 Word
        for it in sorted(cands, key=lambda c: (not c["rel"].lower().endswith(".pdf"), c["rel"])):
            try:
                r = parse_shenlun(os.path.join(root, it["rel"]))
            except Exception as e:  # noqa: BLE001
                print("申论解析失败", it["rel"], e)
                continue
            if r and (best is None or _quality(r) > _quality(best)):
                best, best_it = r, it
        if not best:
            continue
        it = best_it
        title = re.sub(r"\s+", "", it["name"])
        title = re.sub(r"^\d+、", "", title)
        title = re.sub(r"(真题)?(卷)?(及|和|\+)?(参考)?答案(解析)?|\(两套答案\)|（含解析.*?）|_\d{8}_\d+|-?试题-?完整版", "", title)
        for q in best["questions"]:
            q.setdefault("minutes", 0)
            q["points"] = []
        sets.append({
            "id": sid, "title": title, "theme": f"{it['exam']} {it['year']}", "level": it["level"] or it["exam"],
            "exam": it["exam"], "year": it["year"], "file": it["rel"], "real": True,
            "materials": best["materials"], "questions": best["questions"],
        })
    sets.sort(key=lambda s: (s["exam"] != "国考", -s["year"], s["id"]))
    return sets
