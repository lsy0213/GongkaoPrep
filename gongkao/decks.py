"""从资料里的成语、常识、实词辨析等背诵材料生成闪卡卡组。

只认几种规整的写法，认不出的文件就跳过（宁缺毋滥）：
- “71、双管齐下：比喻做一件事……”        编号 + 词条 + 冒号 + 释义
- “76.纯羊绒的含绒量在：->95%以上,”       问题 -> 答案（常识 4600 问）
- “21．相辅相成”下一行“拆解：……”         词条 + 拆解
- “妨害：使受损害。妨碍：使不能顺利进行。”  词语辨析
"""

import os
import re

from .pdftext import AD_RE, join_text, load_any

CAND_RE = re.compile(r"成语|常识.{0,4}问|实词|词语辨析|高频词|口诀|易混|易错")
SKIP_RE = re.compile(r"真题|试卷|模拟|刷题|题本|千题|万题|规范词|规范表达|金句|范文")

ENTRY_RE = re.compile(r"^\s*(\d{1,4})\s*[、.．]\s*([一-鿿，、]{2,14})\s*[：:]\s*(.{2,})$")
HEAD_RE = re.compile(r"^\s*(\d{1,4})\s*[、.．]\s*([一-鿿]{3,8})\s*$")
WORD_RE = re.compile(r"(?:^|(?<=[。；;）)\s]))([一-鿿]{2,4})\s*[：:]")


def _qa_cards(paras):
    """“问题->答案,” 一段里可能连着好几条。"""
    cards = []
    for p in paras:
        if "->" not in p:
            continue
        pos = 0
        for m in re.finditer(r"->", p):
            q = p[pos:m.start()]
            rest = p[m.end():]
            a_m = re.match(r"\s*([^,，]{1,60})", rest)
            if not a_m:
                continue
            a = a_m.group(1).strip()
            pos = m.end() + a_m.end()
            q = re.sub(r"^[\s,，]*(\d{1,5}\s*[.．、])?\s*", "", q).strip()
            if 4 <= len(q) <= 160 and a:
                cards.append((q, a))
    return cards


def _entry_cards(paras):
    out = []
    for p in paras:
        m = ENTRY_RE.match(p)
        if m:
            out.append((m.group(2), m.group(3).strip()))
    return out


def _head_cards(paras):
    out = []
    for i, p in enumerate(paras):
        m = HEAD_RE.match(p)
        if not m:
            continue
        back = []
        for q in paras[i + 1:i + 4]:
            if HEAD_RE.match(q) or re.match(r"^\s*例\s*[：:]", q):
                break
            back.append(re.sub(r"^\s*(拆解|释义|解析|意思)\s*[：:]\s*", "", q))
        if back:
            out.append((m.group(2), " ".join(back)[:300]))
    return out


def _word_cards(paras):
    out = []
    for p in paras:
        ms = list(WORD_RE.finditer(p))
        for k, m in enumerate(ms):
            end = ms[k + 1].start() if k + 1 < len(ms) else len(p)
            back = p[m.end():end].strip()
            if 2 <= len(back) <= 200:
                out.append((m.group(1), back))
    return out


def parse_deck(path):
    doc = load_any(path)
    lines = [ln.text for ln in doc.all_lines() if ln.tag not in ("header", "footer", "ad") and not AD_RE.search(ln.text)]
    paras = join_text(lines).split("\n")
    best = []
    for fn in (_qa_cards, _entry_cards, _head_cards, _word_cards):
        cards = fn(paras)
        if len(cards) > len(best) * 1.15:
            best = cards
    # 去重
    seen, out = set(), []
    for f, b in best:
        f = re.sub(r"(拆解|释义|解析|意思)$", "", f)
        k = f + "|" + b[:20]
        if k not in seen:
            seen.add(k)
            out.append({"front": f, "back": b})
    return out


def build_all(catalog_files, root, progress=None):
    cands = [f for f in catalog_files if f.get("text") and f["ext"] in ("pdf", "docx")
             and CAND_RE.search(f["name"]) and not SKIP_RE.search(f["name"])]
    found = []
    for i, f in enumerate(cands):
        if progress:
            progress(i, len(cands), f["name"])
        try:
            cards = parse_deck(os.path.join(root, f["rel"]))
        except Exception:  # noqa: BLE001
            continue
        if len(cards) >= 30:
            found.append((f, cards))
    # 同一份资料常有多份拷贝或修订版：大卡组优先，与已收录卡组的词条重合过半就不再收
    found.sort(key=lambda fc: -len(fc[1]))
    decks, kept = [], []
    for f, cards in found:
        fronts = {c["front"] for c in cards}
        if any(len(fronts & k) > 0.5 * min(len(fronts), len(k)) for k in kept):
            continue
        kept.append(fronts)
        name = f["name"]
        for _ in range(2):  # 去掉括号后，末尾的“竖版”、开头的“言语”才露出来
            name = re.sub(r"[【】\[\]]|^\d+[.．、]|\(.*?\)|（.*?）|_\d+|^赠[：:-]?|\.pdf$|-?新$|word$|[横竖]版$|^言语", "",
                          name).strip()
        name = name or f["name"]
        did = "lib-" + f["id"]
        decks.append({
            "id": did, "name": name, "source": f["rel"], "fid": f["id"],
            "cards": [{"id": f"{did}-{k}", "front": c["front"], "back": c["back"]} for k, c in enumerate(cards)],
        })
    return decks
