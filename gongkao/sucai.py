"""素材库：从资料库里的申论素材（金句、名言、人物、典故、规范表述、热点、开头结尾、范文）逐条拆出来，
按“类型 × 主题”整理，再加上软件内置的精选素材（content/sucai_builtin.json），存成 library/sucai.json。

每条素材：{"id", "type", "theme", "title", "text", "note", "src", "doc", "seq"}
- note：名句的释义 / 出处、规范表述对应的“材料原话”、人物的颁奖词等补充；
- doc、seq：来自哪份资料哪一段，素材库里可以点回去看上下文。
"""

import json
import re
import time
from collections import Counter

from . import docs as docmod
from .paths import data_dir, resource_dir

OUT = data_dir() / "library" / "sucai.json"

TYPES = ["规范表述", "金句", "名言古句", "人物事例", "典故", "论据", "开头结尾", "热点素材", "范文"]

THEMES = [
    ("民生保障", r"民生|就业|养老|住房|社保|收入|获得感|幸福感|托育|一老一小|弱有所扶|老有所|病有所|学有所|共同富裕|兜底"),
    ("乡村振兴", r"乡村|农村|农业|农民|三农|粮食|耕地|脱贫|扶贫|种业|村民|驻村|田"),
    ("基层治理", r"基层|社区|网格|减负|形式主义|官僚主义|枫桥|村干部|乡镇|街道|接诉即办"),
    ("生态文明", r"生态|绿色|环保|碳|污染|绿水青山|美丽中国|节能|低碳|垃圾分类|河长|森林|湿地|自然"),
    ("科技创新", r"科技|创新|人工智能|芯片|新质生产力|研发|核心技术|科学家|航天|卡脖子|创造"),
    ("数字经济", r"数字|互联网|网络|平台经济|数据|电商|直播|算法|智慧|信息化|5G"),
    ("文化自信", r"文化|传统|文明|非遗|文物|传承|中华优秀|文艺|阅读|典籍|汉字|博物馆|诗词"),
    ("法治建设", r"法治|法律|执法|司法|依法|规则|守法|普法|宪法|公平正义|法规"),
    ("营商环境", r"营商|民营|市场主体|放管服|政务服务|一网通办|企业家|中小企业|最多跑一次"),
    ("经济发展", r"经济|高质量发展|消费|内需|产业|制造|新发展格局|实体|金融|供给侧|市场"),
    ("教育人才", r"教育|学校|学生|教师|双减|职业教育|育人|人才|高校|立德树人"),
    ("医疗健康", r"医疗|医院|医生|健康|医保|卫生|疫情|公共卫生|中医|药"),
    ("青年担当", r"青年|青春|年轻|后浪|少年|新时代青年"),
    ("党建作风", r"党|作风|廉|初心|使命|为民|公仆|自我革命|腐|干部担当|担当作为|调查研究|群众路线"),
    ("安全应急", r"安全|应急|风险|防灾|减灾|消防|安全生产|国家安全|食品安全"),
    ("精神品质", r"精神|品格|坚守|奉献|工匠|劳模|奋斗|自强|诚信|家风|实干|责任|担当|坚持|毅力|初心"),
    ("对外开放", r"开放|一带一路|人类命运共同体|全球|国际|合作共赢|世界|外交"),
    ("社会治理", r"社会治理|治理|老龄|网络空间|志愿|公益|社会组织|共建共治共享|矛盾纠纷"),
]
_THEME_RX = [(n, re.compile(rx)) for n, rx in THEMES]

NOISE_RE = re.compile(r"版权|著作权|仅供个人|免费下载|本资料|资料来自|关注|公众号|微信|淘宝|店铺|扫码|二维码|www\.|http|"
                      r"更多资料|资料站|上岸|祝你|加油|目录|Contents|Preface|序言|前言|第\s*\d+\s*页|^\d+$|花木君|小编|老师说|同学们|"
                      r"^(分析|点评|解析|批注|注意|提示|说明|技巧|方法|思路)[:：]")
PREFIX_RE = re.compile(r"^\s*(?:每日(?:论据|金句|素材)\s*\d+|理论论述[一二三四五六七八九十\d]*|事例论述[一二三四五六七八九十\d]*|"
                       r"经典论证文段[（(]背诵[)）]|【\s*\d+\s*】|【[^】]{1,4}】|例\s*\d+|素材\s*\d+|金句\s*\d+|名言\s*\d+)\s*[:：.．、]?\s*")
WM_RE = re.compile(r"送给最?\s*努\s*_*力\s*_*的?\s*_*你_*|考公资料站|资料站|新途径资料库|料站|公考上岸小铺")
TECH_RE = re.compile(r"备考|积累时|大家|同学|考场|题目|给定资料|资料\d|材料中|材料里|作答|答题|得分|采分|踩分|本题|题干|考生|阅卷|字数|分值|审题|结构[:：]")
END_RE = re.compile(r"[。！？!?”」』…；;]$")
NUM_RE = re.compile(r"^\s*(?:[（(]?\d{1,3}[)）.．、]|[①-⑳]|[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十]+[）)]|[●•·▲■◆★☆※-])\s*")
QUOTE_SRC_RE = re.compile(r"^(.*?[”」』。！？!?])\s*[—–-]{1,2}\s*(.{1,40})$")
PERSON_HEAD_RE = re.compile(r"人物\s*\d*\s*[:：]|——|[:：]\s*\S{2,4}$|^\S{2,4}[:：]")


def theme_of(*texts, default="综合"):
    score = Counter()
    for w, t in zip((3, 1, 1), texts):
        for name, rx in _THEME_RX:
            n = len(rx.findall(t or ""))
            if n:
                score[name] += n * w
    return score.most_common(1)[0][0] if score else default


def _clean(t):
    t = WM_RE.sub("", t or "")
    t = re.sub(r"\s+", " ", (t or "").replace("⦅", "").replace("⦆", "").replace("⁄", "/")).strip()
    t = NUM_RE.sub("", t).strip()
    return PREFIX_RE.sub("", t).strip()


def _good(t, lo=8, hi=320, sentence=False):
    if not (lo <= len(t) <= hi) or NOISE_RE.search(t):
        return False
    if sentence and not END_RE.search(t):
        return False  # 段落被分页截断了半句，不要
    if re.match(r"^[\u4e00-\u9fff][，、。；：）”]|^[，、。；：）”」』]", t):
        return False  # 从上一页接过来的半句
    if TECH_RE.search(t):
        return False  # 答题技巧的讲解，不是素材
    cjk = sum(1 for ch in t if "一" <= ch <= "鿿")
    if cjk < len(t) * 0.5:
        return False
    # OCR 碎片：很短又没有标点
    if len(t) < 16 and not re.search(r"[，。；！？、：“”]", t):
        return False
    return True


def _doc_kind(title, sub):
    """按标题判断这份资料该怎么拆。"""
    if sub == "范文":
        return "范文"
    if re.search(r"人物|感动中国|颁奖词|事迹|楷模", title):
        return "人物事例"
    if re.search(r"典故", title):
        return "典故"
    if re.search(r"规范词|规范表达|规范表述|规范化表达", title):
        return "规范表述"
    if re.search(r"名言|名句|四书五经|用典|古诗|诗词", title):
        return "名言古句"
    if re.search(r"开头|结尾", title):
        return "开头结尾"
    if re.search(r"论据", title):
        return "论据"
    if re.search(r"金句|金词|排比|段旨|句型|句式|贺词|讲话", title):
        return "金句"
    return "热点素材"


def _para_type(default, heads):
    """段落型素材：按所在小标题细分类型。"""
    h = " ".join(heads[-2:])
    if re.search(r"名言|名句|用典|古语|诗词|经典", h):
        return "名言古句"
    if re.search(r"金句|好句|妙语|句子|排比", h):
        return "金句"
    if re.search(r"规范|表述|提法|术语|关键词|对策词", h):
        return "规范表述"
    if re.search(r"论据|事例|案例|数据", h):
        return "论据"
    if re.search(r"开头|结尾|标题", h):
        return "开头结尾"
    if re.search(r"人物", h):
        return "人物事例"
    return default


class _Out:
    def __init__(self):
        self.items = []
        self.seen = set()

    def add(self, typ, text, title="", note="", src="", doc="", seq=0, theme=None, heads=()):
        text = text.strip()
        key = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)[:60]
        if len(key) < 6 or key in self.seen:
            return None
        self.seen.add(key)
        item = {"type": typ, "theme": theme or theme_of(" ".join(heads[-2:]) + " " + title, text, note),
                "title": title.strip()[:60], "text": text, "note": note.strip()[:600], "src": src, "doc": doc, "seq": seq}
        self.items.append(item)
        return item


def _sections(blocks):
    """按标题切段：[(标题, 标题所在的块号, [正文块…], 标题路径)]。"""
    out = []
    heads = []
    cur = None
    for b in blocks:
        seq, kind, lv, text = b["seq"], b["kind"], b["level"], b["text"] or ""
        if kind == "h":
            while heads and heads[-1][0] >= lv:
                heads.pop()
            heads.append((lv, _clean(text)))
            cur = (_clean(text), seq, [], [h for _l, h in heads])
            out.append(cur)
        elif cur is None:
            cur = ("", seq, [], [])
            out.append(cur)
            cur[2].append(b)
        else:
            cur[2].append(b)
    return out


def _from_doc(out, d, blocks):
    kind = _doc_kind(d["title"], d["sub"])
    src = d["title"]
    did = d["id"]
    topic = re.sub(r"[（(].*?[）)]|^\d+[.．、]", "", d["title"])  # “3.乡村振兴（县乡类岗位必看）”→ 乡村振兴

    if kind == "典故":
        # “8.天下之事，因循则无一事可为……”标题 +【例文】+【典故】，标题可能是小标题也可能是普通段落
        cur = None
        for blk in blocks:
            t = (blk["text"] or "").strip()
            if not t or blk["kind"] not in ("h", "p"):
                continue
            m = re.match(r"^\d{1,3}\s*[.．、]\s*(.{2,48})$", t)
            if m and not t.startswith("【") and blk["kind"] in ("h", "p"):
                cur = {"title": _clean(m.group(1)), "seq": blk["seq"], "dg": "", "lw": ""}
                cur["item"] = None
                continue
            if cur is None:
                continue
            if t.startswith("【典故】"):
                cur["dg"] = _clean(t[4:])
            elif t.startswith("【例文】"):
                cur["lw"] = _clean(t[4:])
            else:
                continue
            note = cur["dg"] + (("\n例文：" + cur["lw"][:300]) if cur["lw"] else "")
            if cur["item"] is None:
                cur["item"] = out.add("典故", cur["title"], note=note[:600], src=src, doc=did, seq=cur["seq"], heads=[topic])
            elif cur["item"]:
                cur["item"]["note"] = note[:600]
        return

    if kind in ("人物事例", "典故", "范文"):
        for title, hseq, body, heads in _sections(blocks):
            paras = [_clean(b["text"]) for b in body if b["kind"] in ("p", "box") and b["text"]]
            paras = [p for p in paras if p and not NOISE_RE.search(p[:20])]
            if not title or not paras or len("".join(paras)) < 40:
                continue
            if kind == "人物事例":
                # 感动中国：标题下面的“颁奖词”“事迹”小节合到人物名下
                if re.fullmatch(r"颁奖词|事迹|人物简介|简介|素材运用|运用角度|适用主题", title) and out.items and out.items[-1]["doc"] == did:
                    last = out.items[-1]
                    if title == "颁奖词":
                        last["note"] = ("颁奖词：" + "".join(paras))[:600]
                    else:
                        last["text"] = (last["text"] + "\n" + "\n".join(paras))[:900]
                    continue
                name = re.sub(r"^人物\s*\d*\s*[:：]\s*|^【#?|】$", "", title)
                whole = [p for p in paras if len(p) >= 12]
                if not whole or sum(1 for p in whole if END_RE.search(p)) < len(whole) * 0.5 or len(name) > 30:
                    continue
                out.add("人物事例", "\n".join(paras)[:900], title=name, src=src, doc=did, seq=hseq, heads=heads)
            elif kind == "典故":
                text = " ".join(paras)
                m = re.search(r"【典故】(.*?)(?=【|$)", text)
                use = re.search(r"【例文】(.*?)(?=【|$)", text)
                out.add("典故", title, title="", note=((m.group(1).strip() if m else text[:300])
                                                     + (("\n例文：" + use.group(1).strip()[:300]) if use else ""))[:600],
                        src=src, doc=did, seq=hseq, heads=heads)
            else:  # 范文：题目 + 开头两段，点开看全文
                if not (6 <= len(title) <= 40) or len(paras) < 3 or len("".join(paras)) < 600 \
                        or re.search(r"热点词|第.{1,3}[章节篇]|真题|^\d+$|目录|题$", title):
                    continue
                out.add("范文", "\n".join(paras[:2])[:400], title=title, note=f"全文约 {len(''.join(paras))} 字",
                        src=src, doc=did, seq=hseq, heads=heads)
        return

    if kind == "规范表述":
        # “材料语言 | 规范表达”两列表格：规范表达是素材，材料原话放在补充里
        heads = []
        for b in blocks:
            if b["kind"] == "h" or (b["kind"] == "p" and len(b["text"] or "") <= 12 and re.search(r"类$|篇$", b["text"] or "")):
                heads = (heads + [_clean(b["text"])])[-2:]
                continue
            if b["kind"] == "tbl" and b["data"]:
                rows = json.loads(b["data"]).get("rows") or []
                for r in rows:
                    cells = [_clean(c) for c in r if c and c.strip()]
                    if len(cells) < 2 or re.search(r"材料语言|规范表达|原文", cells[0] + cells[-1]):
                        continue
                    raw, std = cells[0], cells[-1]
                    if len(std) > len(raw) * 1.5 and len(raw) <= 30:
                        raw, std = std, raw  # 两列顺序反了
                    std = re.sub(r"^\d+[.．、]?|\d+[.．、]?$", "", std).strip()
                    if 2 <= len(std) <= 60 and not re.fullmatch(r"[\d.]+", raw):
                        out.add("规范表述", std, note=f"材料原话：{raw}"[:300], src=src, doc=did, seq=b["seq"], heads=heads)
            elif b["kind"] == "p":
                t = _clean(b["text"])
                m = re.match(r"^(.{4,80}?)\s*[—–-]{1,2}\s*(.{2,40})$", t)
                if m and not re.search(r"\d{2,}[.．]", m.group(2)):
                    out.add("规范表述", m.group(2).strip(), note=f"材料原话：{m.group(1).strip()}", src=src, doc=did, seq=b["seq"], heads=[topic] + heads)
                elif _good(t, lo=4, hi=90):
                    out.add("规范表述", t, src=src, doc=did, seq=b["seq"], heads=[topic] + heads)
        return

    # 段落型：金句、名言、开头结尾、论据、热点素材
    blocks = _join_broken(blocks)
    heads = []
    last = None
    for b in blocks:
        if b["kind"] == "h":
            heads = (heads + [_clean(b["text"])])[-3:]
            last = None
            continue
        if b["kind"] not in ("p", "box"):
            continue
        t = _clean(b["text"])
        if not t:
            continue
        if re.match(r"^(释义|译文|解读|出处|用法|运用|点评|【释义】|【出处】|【译文】)\s*[:：]?", t):
            if last is not None:
                last["note"] = (last["note"] + " " + t)[:600].strip()
            continue
        typ = _para_type(kind, heads)
        hi = 420 if typ in ("论据", "热点素材") else 260
        lo = 25 if typ in ("论据", "热点素材") else 8
        if not _good(t, lo=lo, hi=hi, sentence=typ in ("论据", "热点素材", "金句", "开头结尾")):
            continue
        if typ == "名言古句" and not (re.search(r"[“「]", t) or len(t) <= 60):
            typ = "论据"  # 名言后面展开的论述
        note = ""
        m = QUOTE_SRC_RE.match(t)
        if m and typ in ("名言古句", "金句") and len(m.group(2)) <= 40:
            t, note = m.group(1).strip(), "——" + m.group(2).strip()
        last = out.add(typ, t, note=note, src=src, doc=did, seq=b["seq"], heads=[topic] + heads)


def _join_broken(blocks):
    """上一段没说完（结尾不是句号等）、这一段也不是新的编号条目：说明是跨页断开的，接回去。"""
    out = []
    for b in blocks:
        t = (b.get("text") or "").strip()
        if out and b["kind"] == "p" and out[-1]["kind"] == "p" and t:
            prev = (out[-1].get("text") or "").strip()
            if prev and not END_RE.search(prev) and not re.search(r"[:：]$", prev) and not NUM_RE.match(t) \
                    and not re.match(r"^[【“「(（]", t) and len(prev) >= 12:
                out[-1] = dict(out[-1], text=prev + t)
                continue
        out.append(dict(b))
    return out


RENAME = {"文化传承": "文化自信", "法治与营商环境": "法治建设"}


def _builtin():
    """软件内置的精选素材：content/sucai_builtin_*.json，以及早先的 materials.json。"""
    items = []
    paths = sorted((resource_dir() / "content").glob("sucai_builtin*.json")) + [resource_dir() / "content" / "materials.json"]
    themes = []
    for path in paths:
        if path.exists():
            themes += json.loads(path.read_text(encoding="utf-8")).get("themes", [])
    for theme in themes:
        name = RENAME.get(theme["name"], theme["name"])
        for p in theme.get("phrases", []):
            items.append({"type": "规范表述", "theme": name, "title": "", "text": p, "note": "", "src": "内置精选"})
        for q in theme.get("quotes", []):
            items.append({"type": "名言古句", "theme": name, "title": "", "text": q["text"],
                          "note": "——" + q["source"] + (f"　用法：{q['use']}" if q.get("use") else ""), "src": "内置精选"})
        for p in theme.get("people", []):
            items.append({"type": "人物事例", "theme": name, "title": p["name"], "text": p["story"],
                          "note": ("可用于：" + p["use"]) if p.get("use") else "", "src": "内置精选"})
        for a in theme.get("angles", []):
            items.append({"type": "论据", "theme": name, "title": "分论点角度", "text": a, "note": "", "src": "内置精选"})
        for s_ in theme.get("sentences", []):
            items.append({"type": "金句", "theme": name, "title": "", "text": s_, "note": "", "src": "内置精选"})
        for s_ in theme.get("openings", []):
            items.append({"type": "开头结尾", "theme": name, "title": "", "text": s_, "note": "", "src": "内置精选"})
    return items


POLICY_VERB_RE = re.compile(r"^(推进|推动|加快|深化|健全|完善|实施|坚持|加强|促进|扩大|提高|提升|持续|着力|全面|大力|"
                            r"积极|稳步|统筹|强化|落实|优化|培育|发展|支持|建设|构建|打造|保障|巩固|守住|坚决|深入|筑牢|增强|激发|做好|办好)")


def _reports():
    """content/reports/ 里的政府工作报告等官方文件：拆成一句句规范表述（新提法）和金句。"""
    items = []
    folder = resource_dir() / "content" / "reports"
    if not folder.exists():
        return items
    for path in sorted(folder.glob("*.txt")):
        name = path.stem
        for para in path.read_text(encoding="utf-8").splitlines():
            for sent in re.split(r"(?<=[。；！])", para):
                t = re.sub(r"^[（(][一二三四五六七八九十]+[）)]|^[一二三四五六七八九十]是", "", sent.strip()).rstrip("；;").strip()
                if not (10 <= len(t) <= 90) or len(re.findall(r"\d", t)) > 4 \
                        or re.search(r"各位代表|过去一年|今年|去年|亿元|万人|%|％|方面|指标|取得|成效|增长|下降|达到", t):
                    continue
                parts = [x for x in re.split(r"[，,]", t.rstrip("。！")) if x]
                if POLICY_VERB_RE.match(t):
                    typ = "规范表述"
                elif len(t) <= 26 and len(parts) == 2 and abs(len(parts[0]) - len(parts[1])) <= 2:
                    typ = "金句"  # “蓝图已经绘就，奋进正当其时”这类对仗短句
                else:
                    continue
                items.append({"type": typ, "theme": theme_of(t, ""), "title": "", "text": t, "note": f"——{name}", "src": name})
    return items


def build(progress=None):
    """从资料库文档拆出素材，加上内置精选，写到 library/sucai.json。"""
    out = _Out()
    for it in _builtin() + _reports():
        out.add(it["type"], it["text"], title=it["title"], note=it["note"], src=it["src"], theme=it["theme"])
    conn = docmod.connect()
    targets = [d for d in docmod.doc_list() if d["grp"] == "申论" and not d.get("error")
               and (d["sub"] in ("素材积累", "范文") or re.search(r"规范|开头|结尾|句型|句式|金句", d["title"]))]
    for i, d in enumerate(targets):
        if progress:
            progress(i, len(targets), d["title"])
        blocks = [dict(r) for r in conn.execute("SELECT seq, kind, level, text, data FROM blocks WHERE doc=? ORDER BY seq", (d["id"],))]
        try:
            _from_doc(out, d, blocks)
        except Exception:  # noqa: BLE001 —— 个别资料版式特殊，跳过不影响其他
            continue
    conn.close()
    for n, it in enumerate(out.items):
        it["id"] = n + 1
    data = {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "types": TYPES, "themes": [t for t, _r in THEMES] + ["综合"],
            "items": out.items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    return len(out.items)


def load():
    if not OUT.exists():
        return {"items": [], "types": TYPES, "themes": [t for t, _r in THEMES] + ["综合"], "built_at": ""}
    return json.loads(OUT.read_text(encoding="utf-8"))
