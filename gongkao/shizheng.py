"""时政晨读：资料文件夹里的「时政合集 + 每日晨读」整理成软件里的文字内容。

分五块：
- 月度时政：超格、小黑、粉笔的每月 / 半月时政讲义、热点汇总、月度刷题，按年 → 月排好；
- 时政专题：两会与政府工作报告、中央一号文件、全会与“十五五”、重要会议、新年贺词、法律、党建、纪念活动……；
- 时政题库：时政 300 / 600 / 1900 题、公基题本，题目可以直接点选作答；
- 人民日报精读：每天一篇评论，原文 + 结构笔记（论点、论据、金句、对策）+ 思维导图提纲 + 拆解报告 / 仿写范文；
- 成语积累：人民日报原句里的成语，按天整理成“例句 + 释义”，可以挖空自测；每月的成语随堂演练（逻辑填空题）。

讲义、精读走资料库同一套整理流程（docs.build_one：文字层还原 / 扫描页 OCR、标题和目录、例题合成可作答的题块），
存进单独的 library/shizheng.db（表结构和 docs.db 一样，阅读器通用）；成语积累按天拆成词条，存 library/chengyu.json。
同一内容的 PPT 版（横版课件）、旧版、题本 / 纯净版、默写纸、重复拷贝只收一份。
"""

import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict

from .dbutil import open_db
from .paths import data_dir

LIB = data_dir() / "library"
DB_PATH = LIB / "shizheng.db"
CY_PATH = LIB / "chengyu.json"
FILES_PATH = LIB / "shizheng_files.json"
VERSION = 12  # 整理规则有变化时加一，旧结果会自动重做

MARK_RE = re.compile(r"时政合集|每日晨读")
SECTIONS = ("月度时政", "时政专题", "时政题库", "人民日报精读", "成语演练")

_lock = threading.Lock()


def is_shizheng(rel):
    return bool(MARK_RE.search(rel or ""))


def fid_of(rel):
    from .library import fid_of as f
    return f(rel)


# ---------------------------------------------------------------- 扫描

def scan(root, progress=None):
    """找出资料文件夹里时政、晨读目录下的 PDF，记下页数、横版（PPT 课件）还是竖版。没变的文件沿用上次结果。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    old = {}
    try:
        old = {f["rel"]: f for f in json.loads(FILES_PATH.read_text(encoding="utf-8")).get("files", [])}
    except (OSError, ValueError):
        pass
    rels = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root)
            if is_shizheng(rel) and f.lower().endswith(".pdf"):
                rels.append(rel)
    rels.sort()
    out = []
    for i, rel in enumerate(rels):
        if progress and i % 25 == 0:
            progress(i, len(rels), os.path.basename(rel))
        try:
            st = os.stat(os.path.join(root, rel))
        except OSError:
            continue
        prev = old.get(rel)
        if prev and prev["size"] == st.st_size and prev["mtime"] == int(st.st_mtime):
            out.append(prev)
            continue
        item = {"id": fid_of(rel), "rel": rel, "name": os.path.splitext(os.path.basename(rel))[0], "ext": "pdf",
                "size": st.st_size, "mtime": int(st.st_mtime), "pages": 0, "land": False, "text": False}
        try:
            d = pymupdf.open(os.path.join(root, rel))
            n = d.page_count
            idx = list(range(0, n, max(1, n // 6)))
            item["pages"] = n
            item["land"] = sum(1 for k in idx if d[k].rect.width > d[k].rect.height * 1.1) * 2 > len(idx)
            m = min(n, 4)
            item["text"] = sum(len(d[k].get_text().strip()) for k in range(m)) // max(m, 1) >= 120
            d.close()
        except Exception:  # noqa: BLE001
            item["broken"] = True
        out.append(item)
    LIB.mkdir(parents=True, exist_ok=True)
    FILES_PATH.write_text(json.dumps({"root": root, "files": out}, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------- 分类

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}

TOPICS = [
    ("省情与地方", r"省情|山东"),
    ("两会与政府工作报告", r"政府工作报告|ZF工作报告|两会"),
    ("中央一号文件与三农", r"一号文件|农业|农村|乡村|三农"),
    ("全会与“十五五”规划", r"全会|十五五|二十大|20大|党的.{0,2}大"),
    ("经济与金融工作会议", r"经济工作会议|经济会议|金融工作会议|金融热点|经济"),
    ("新年贺词与重要讲话", r"新年贺词|团拜会|春晚|讲话|总工会"),
    ("法律热点", r"法律|刑法|民法|诉讼法|处罚法|新法|公安"),
    ("党建与理论", r"党建|D建|求是|思想|党史"),
    ("外交与“一带一路”", r"一带一路|外交|峰会"),
    ("纪念日与体育文化", r"抗日战争|抗战|周年|奥运|春晚"),
    ("城市、基层与民生", r"城市|基层|社区|医疗|教育|会计|科技|国防|军队"),
]


def _ym(name, rel):
    """从文件名、所在文件夹里认出年、月、上下半月。"""
    t = name
    folders = rel.replace("/", "\\").split("\\")[:-1]
    y = m = 0
    half = ""
    mm = re.search(r"(20\d\d)\s*年\s*(\d{1,2})\s*(?:月|时政)", t) or re.search(r"(?<!\d)(2\d)\s*年\s*(\d{1,2})\s*月", t) \
        or re.search(r"(?<![\d.])(20\d\d)\.(\d{1,2})(?![\d.])", t)  # “2023.03”
    if mm:
        y, m = int(mm.group(1)), int(mm.group(2))
        y = y + 2000 if y < 100 else y
    else:
        mm = re.search(r"(?<![\d.])(\d{1,2})\s*月", t)
        if mm:
            m = int(mm.group(1))
        mm = re.search(r"(20\d\d)", t)
        if mm:
            y = int(mm.group(1))
    # 按月编号的串讲文件夹：“05、月时政串讲”
    if not m and re.search(r"串讲", "".join(folders[-1:])):
        pm = re.match(r"\s*(\d{2})[、.]", t)
        if pm:
            m = int(pm.group(1))
    # 粉笔讲师笔记：“2024.11.05+2024时政热点：10月串讲” —— 讲的是 10 月
    lec = re.search(r"(20\d\d)\s*时政热点\s*[:：]?\s*(\d{1,2})\s*月", t)
    if lec:
        y, m = int(lec.group(1)), int(lec.group(2))
    for f in reversed(folders):
        if not y:
            fy = re.search(r"(20\d\d)\s*年", f) or re.search(r"(?<!\d)(2\d)年\d", f) \
                or re.search(r"(?<![\d\-–])(20\d\d)(?![\d\-–])", f)  # “【时政】2026超格时政讲练班”
            if fy:
                y = int(fy.group(1)) + (2000 if len(fy.group(1)) == 2 else 0)
        if not m:
            fm = re.search(r"(?<!\d)(\d{1,2})\s*月", f)
            if fm and not re.search(r"\d{1,2}\s*[-–]\s*\d{1,2}\s*月", f):
                m = int(fm.group(1))
    if re.search(r"[（(]\s*上\s*[）)]|[-－]\s*上(?!\S*下)|上半月|\d月上|月\s*时政上|上\s*讲义", t):
        half = "上"
    elif re.search(r"[（(]\s*下\s*[）)]|[-－]\s*下|下半月|\d月下|月\s*时政下|下\s*讲义", t):
        half = "下"
    q = re.search(r"第([一二三四])季度", t)
    if q:
        half = f"第{q.group(1)}季度"
    if not (1 <= m <= 12):
        m = 0
    return y, m, half


def _src(rel):
    if "必胜哥" in rel:
        return "必胜哥"
    if "超格" in rel:
        return "超格"
    if "小黑" in rel:
        return "小黑"
    if "FB时政" in rel:
        return "粉笔"
    if "人民日报" in rel:
        return "人民日报"
    return "其他"


def _topic(t):
    for name, rx in TOPICS:
        if re.search(rx, t):
            return name
    return "其他专题"


QBOOK_RE = re.compile(r"\d{2,4}\s*题|题本|刷题本|题目|套卷|必刷|题库|押题")
SKIP_NAME_RE = re.compile(r"默写|勘误|历年真题(?!成语)")


def describe(f):
    """一份文件归到哪一块、显示成什么标题。返回 dict；不收录的给出 skip 原因。"""
    rel, name = f["rel"], f["name"]
    y, m, half = _ym(name, rel)
    src = _src(rel)
    info = {"y": y, "m": m, "half": half, "src": src, "date": "", "topic": "", "kind": ""}
    if f.get("broken"):
        return dict(info, skip="文件损坏")
    if SKIP_NAME_RE.search(name):
        return dict(info, skip="默写纸 / 勘误 / 非时政真题")
    if "文件夹只保存本期与上期" in rel:
        return dict(info, skip="旧版本（同一套题已有更新版）")
    # 顶层文件夹名“时政合集+每日晨读”两个词都有，按下一层分：每日晨读 / 时政课程
    if any("每日晨读" in p and "时政合集" not in p for p in rel.replace("/", "\\").split("\\")[:-1]):
        if "随堂演练" in name:
            return dict(info, sec="成语演练", kind="随堂演练")
        if "成语积累" in rel:
            if "合集" in name:
                return dict(info, skip="月合集（和每天的内容相同）")
            if re.search(r"逻辑成语|成语积累", name) and re.search(r"\d{1,2}\.\d{1,2}", name):
                dm = re.search(r"(\d{1,2})\.(\d{1,2})", name)
                return dict(info, sec="成语", m=int(dm.group(1)), date=f"{y:04d}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}")
            if "成语" in name:
                return dict(info, sec="成语演练", kind="成语手册")
            return dict(info, sec="时政专题", topic="申论素材与范文")
        # 人民日报精读：日期、标题、栏目
        d = re.match(r"\s*(20\d\d)\.(\d{1,2})\.(\d{1,2})\s*(.*)$", name)
        if d:
            y, m, day, title = int(d.group(1)), int(d.group(2)), int(d.group(3)), d.group(4)
        else:
            d = re.match(r"\s*(\d{1,2})日\s*[-－]\s*(.*)$", name) or re.search(r"(\d{1,2})月(\d{1,2})日", name)
            if not d:
                return dict(info, skip="认不出日期")
            if d.re.pattern.startswith(r"\s*(\d{1,2})日"):
                day, title = int(d.group(1)), d.group(2)
            else:
                m, day, title = int(d.group(1)), int(d.group(2)), ""
        col = re.search(r"[（(]([^（）()]{2,8})[）)]\s*$", title or "")
        if col:
            title = title[: col.start()].strip()
        return dict(info, sec="人民日报精读", y=y, m=m, date=f"{y:04d}-{m:02d}-{day:02d}", title=title.strip(),
                    kind=col.group(1) if col else "")
    # 时政课程
    if "山东事业单位" in name:
        return dict(info, skip="山东事业单位真题（不是时政内容）")
    if re.search(r"押题作文|范文|基层话题素材", name):
        return dict(info, sec="时政专题", topic="申论素材与范文")
    if re.search(r"季度|早自习|前瞻课|时政知识合集|思维导图", name) and not re.search(r"政府工作报告", name):
        return dict(info, sec="时政专题", topic="阶段梳理与早自习")
    qbook = bool(QBOOK_RE.search(name)) and not re.search(r"讲义\s*\+\s*60题|时政\s*\+\s*刷题|刷题\s*[+（(]|讲练", name)
    monthly = bool(m) and re.search(r"时政|热点|串讲|梳理|讲练|刷题|题目|答案", name + rel) \
        and not re.search(r"一号文件|政府工作报告|全会|两会|新年贺词|经济工作会议|冲刺|核心|上半年|1-4月|\d+题(?!\s*$)", name)
    if m and (re.search(r"答案|解析", name) and re.search(r"时政", name)
              or re.search(r"时政热点汇总|热点时政汇总|时事政治热点", name)):
        monthly = True
    if monthly and not re.search(r"\d{3,}题", name):
        return dict(info, sec="月度时政", kind=_kind(name, rel))
    if qbook:
        return dict(info, sec="时政题库", topic=_bank_topic(name))
    return dict(info, sec="时政专题", topic=_topic(name + " " + rel.split("\\")[-2]))


def _kind(name, rel):
    if re.search(r"题目|刷题|答案|题本", name):
        return "刷题"
    if re.search(r"时政热点汇总|热点时政汇总|时事政治热点", name):
        return "热点汇总"
    if re.search(r"季度", name):
        return "季度梳理"
    return "讲义"


def _bank_topic(name):
    if re.search(r"公基|公共基础|六套卷", name):
        return "公基综合"
    if re.search(r"一号文件|政府工作报告|二十大|20大|新年贺词|D建|山东", name):
        return "专题题"
    return "时政题"


def plan(files):
    """决定收哪些文件、怎么组：PPT 课件有同月讲义的不收；题目和答案分开的两份合成一份；内容相同的拷贝只收一份。
    返回 [(unit, [文件...])]，unit 是 describe() 的结果加上 id、标题。"""
    infos = []
    for f in files:
        d = describe(f)
        d["f"] = f
        infos.append(d)
    keep = [d for d in infos if not d.get("skip")]
    # 同一文件放了好几份（“(1)”“(2)”拷贝、两个文件夹各放一份）：大小、页数都一样只留一份
    seen = {}
    for d in sorted(keep, key=lambda d: (len(d["f"]["name"]), d["f"]["rel"])):
        k = (d["f"]["size"], d["f"]["pages"])
        if k in seen:
            d["skip"] = "重复拷贝"
        else:
            seen[k] = d
    keep = [d for d in keep if not d.get("skip")]
    # 同一文件夹里“7月随堂演练.pdf”和“7月随堂演练(1).pdf”：一份是月中的旧版（只到 7.6），留页数多的
    groups = defaultdict(list)
    for d in keep:
        base = re.sub(r"\s*[（(]\d[）)]\s*$", "", d["f"]["name"]).strip()
        groups[(d.get("sec") if d.get("sec") == "成语演练" else os.path.dirname(d["f"]["rel"]), base)].append(d)
    for g in groups.values():
        if len(g) > 1:
            best = max(g, key=lambda d: d["f"]["pages"])
            for d in g:
                if d is not best:
                    d["skip"] = "同一份的旧版（页数少）"
    keep = [d for d in keep if not d.get("skip")]
    # 横版 PPT 课件：同一套课（同一文件夹 / ppt 与讲义两个子文件夹）有同月同半月的竖版讲义时不收
    def course_dir(rel):
        parts = rel.split("\\")[:-1]
        if parts and re.fullmatch(r"(?i)ppt|讲义|课件", parts[-1]):
            parts = parts[:-1]
        return "\\".join(parts)

    # 超格的课都有竖版讲义，同一课同一个月的横版课件不收（别家的横版没有对应讲义，照收）
    port = {(course_dir(d["f"]["rel"]), d["y"], d["m"]) for d in keep if not d["f"].get("land")}
    for d in keep:
        if d["f"].get("land") and d["src"] == "超格" and (course_dir(d["f"]["rel"]), d["y"], d["m"]) in port:
            d["skip"] = "PPT 课件（同一课有讲义）"
    keep = [d for d in keep if not d.get("skip")]
    # 题本 / 纯题本 / 刷题本：同名的完整版（带答案）在就不收
    clean = lambda s: re.sub(r"[\s《》]", "", s)  # noqa: E731
    names = {clean(d["f"]["name"]) for d in keep}
    for d in keep:
        n = clean(d["f"]["name"])
        base = re.sub(r"[-—_]?(纯题本|刷题本|题本)$", "", n)
        if base != n and (base in names or base.replace("题本", "答案解析") in names
                          or any(x != n and x.startswith(base[:12]) and re.search(r"答案|解析", x) for x in names)):
            d["skip"] = "题本（有带答案的完整版）"
    keep = [d for d in keep if not d.get("skip")]
    # 题目、答案分成两个文件的（2024 年超格月度刷题）：合成一份，题后接答案解析
    units = []
    used = set()
    by_dir = defaultdict(list)
    for d in keep:
        by_dir[os.path.dirname(d["f"]["rel"])].append(d)
    for d in keep:
        if id(d) in used:
            continue
        parts = [d]
        if re.search(r"题目", d["f"]["name"]) and not re.search(r"答案", d["f"]["name"]):
            mate = next((o for o in by_dir[os.path.dirname(d["f"]["rel"])] if o is not d and id(o) not in used
                         and re.search(r"答案", o["f"]["name"]) and o["m"] == d["m"]), None)
            if mate:
                parts.append(mate)
                used.add(id(mate))
        elif re.search(r"答案", d["f"]["name"]) and not re.search(r"题目|刷题", d["f"]["name"]):
            mate = next((o for o in by_dir[os.path.dirname(d["f"]["rel"])] if o is not d and id(o) not in used
                         and re.search(r"题目", o["f"]["name"]) and o["m"] == d["m"]), None)
            if mate:
                continue  # 等题目那份来合并
        used.add(id(d))
        units.append(d)
        d["parts"] = [p["f"] for p in parts]
        d["id"] = d["f"]["id"]
        d["title"] = unit_title(d)
    skipped = [d for d in infos if d.get("skip")]
    return units, skipped


def _unmask(t):
    """机构讲义为了躲平台审核故意写的“Z央”“国w院”“D建思想”：还原。"""
    return re.sub(r"[Zz]\s*央", "中央", re.sub(r"国\s*[Ww]\s*院", "国务院",
                                              re.sub(r"(?<![A-Z.．])D建(?=思想|工作|引领)", "党建", t or "")))


def unit_title(d):
    return _unmask(_unit_title(d))


def _unit_title(d):
    f = d["f"]
    if d["sec"] == "人民日报精读":
        return (d.get("title") or "").strip(" _-")
    if d["sec"] == "成语":
        return d["date"]
    raw = f["name"]
    name = re.sub(r"[_\-]?\d{8,}$|\(\d\)$", "", raw).strip(" _-")
    teacher = re.search(r"[+＋\s]([一-鿿]{2,3})\s*[+＋\s]*[（(]\s*(?:讲义|笔记)", raw)
    name = re.sub(r"【公众号[^】]*】|[（(][^（）()]*(?:元课|大礼包|系统班|公众号|福利|合集|精品)[^（）()]*(?:[）)]|$)|❤", "", name)
    name = re.sub(r"[（(]\s*(?:讲义)?\s*[+＋ ]*\s*(?:笔记)?\s*[）)]", "", name)
    name = re.sub(r"^\d{1,2}[、.]\s*", "", name)
    name = re.sub(r"^20\d\d[.．]\d{1,2}[.．]\d{1,2}\s*[+＋]?\s*", "", name)
    name = re.sub(r"[+＋]\s*", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    if d["sec"] == "月度时政":
        base = {"超格": "超格", "小黑": "小黑", "粉笔": "粉笔"}.get(d["src"], d["src"])
        k = d.get("kind")
        half = f"（{d['half']}半月）" if d["half"] in ("上", "下") else ""
        if k == "热点汇总":
            return f"{base} · 热点汇总" + ("（附新年贺词）" if "新年贺词" in raw else "（附三中全会公报）" if "三中全会" in raw
                                         else "（附春节团拜会讲话）" if "团拜会" in raw else "")
        if d["src"] == "粉笔":
            who = f"（{teacher.group(1)}）" if teacher else ""
            if "笔记" in raw:
                return f"粉笔 · {'刷题课' if '刷题' in raw else '串讲课'}笔记{who}"
            if re.search(r"时政\s*[+＋]\s*刷题", raw):
                return "粉笔 · 月度时政 + 刷题"
            if re.search(r"年\d{1,2}月时政热点$", raw):
                return "粉笔 · 时政热点"
            return "粉笔 · 月度串讲讲义" + who
        if k == "刷题":
            return f"{base} · 月度刷题" + ("（题目 + 答案解析）" if len(d.get("parts") or []) > 1 else "")
        if d["src"] == "小黑":
            return f"小黑 · 月半时政{half}"
        if re.search(r"讲义\s*\+\s*60题", raw):
            return "超格 · 月度讲义 + 60题"
        if re.search(r"梳理", raw) and not half:
            return "超格 · 月度时政梳理讲义"
        if re.search(r"讲练|时政上|时政下|时政-|梳理|时政讲义|^\d+月时政|月时政$", name):
            return f"{base} · 时政讲练{half}"
        return f"{base} · {name}"
    return name


def dry_run(root):
    files = scan(root)
    units, skipped = plan(files)
    return units, skipped


# ---------------------------------------------------------------- 整理成文字

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS sz_meta (
    id TEXT PRIMARY KEY, sec TEXT, src TEXT, y INTEGER, m INTEGER, half TEXT, date TEXT, title TEXT,
    topic TEXT, kind TEXT, parts TEXT, sig TEXT, version INTEGER, built_at TEXT);
CREATE TABLE IF NOT EXISTS cy_days (
    date TEXT PRIMARY KEY, id TEXT, rel TEXT, sents TEXT, words TEXT, sig TEXT, version INTEGER);
"""


def connect(path=None):
    from . import docs

    LIB.mkdir(parents=True, exist_ok=True)
    conn = open_db(path or DB_PATH)
    conn.executescript(docs.SCHEMA + META_SCHEMA)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5("
                     "text, doc UNINDEXED, seq UNINDEXED, tokenize='trigram')")
    except sqlite3.OperationalError:
        pass
    return conn


# 每页都印着的、和内容无关的字样
JUNK_LINE_RE = re.compile(
    r"^\s*(?:★+|每早\s*7\s*点直播|申论\s*/\s*面试\s*PDF\s*合集|Presented with xmind|超格学员专用|@?公考小黑老师|"
    r"Hey[，,]\s*上岸吧[！!]?|抖音关注公考小黑老师|时政要点即时学|马达成语|[马达成语\s]{2,}|↑|[\]/\d\s]{1,3}|"
    r"上岸村[，,]?\s*不辜负每一次相遇[！!]?|第\s*\d+\s*页\s*共\s*\d+\s*页|[一人E]?\s*民\s*日\s*[報报款][\s\S]{0,12}|RENMIN\s*RIBAO|"
    r"\d{1,2}月\d{1,2}日\s*文章精读笔记|E?上岸村\s*·\s*不辜负每一次相遇)\s*$")
JUNK_IN_RE = re.compile(r"每早\s*7\s*点直播|申论\s*/\s*面试\s*PDF\s*合集|Presented with xmind|添加\s*vx[:：]?\s*\d+\s*获取更多备考资料|"
                        r"公众号[:：]\s*叛逆小樱桃资料|第\s*\d+\s*页\s*共\s*\d+\s*页|RENMIN\s*RIBAO|\d{1,2}月\d{1,2}日\s*文章精读笔记")
AD_WORDS = ("上岸村", "扫码", "二维码", "公众号", "微信", "下载", "APP", "名师", "官网", "小程序", "抖音", "直播",
            "关注", "课程", "督学", "私人", "笔面试", "状元", "VIP", "全程", "报名", "小红书", "微博", "哔哩", "联合创始人",
            "学员", "教学经验", "免费获取", "备考资料", "加微")
# CJK 部首补充区的字（⺠⻋⻅⻔）NFKC 换不回来，逐个对照
RADICALS = str.maketrans("⺠⻋⻅⻔⻓⻢⻝⻜⻛⻚⻣⻰⻆⻬⻮⻦⻥⺟⺩⻄⻙⻉⻊⻩⻨⻤⻁⻈⻌⻍⻏⻖⻗⺀⺁⺈⺊⺍⺧⺮⺶⺷⻢",
                         "民车见门长马食飞风页骨龙角齐齿鸟鱼母王西韦贝足黄麦鬼虎钅辶辶阝阝雨冫厂刀卜小牛竹羊羊马")
# 着重号被拆成一串“．”夹在字中间（“第．12．．．届世界运动会”）：只在这样的资料里清，题号、选项后的“．”留着
EMPH_RE = re.compile(r"．{2,}|(?<![0-9A-H\s])．|(?<=[0-9])．(?=[^\d\s])(?<!^\d．)(?<!^\d\d．)(?<!^\d\d\d．)")


# 封面、封底、页眉里机构的套话（讲师、授课时间、口号、免责声明、打印店广告）：整行不要
BOILER_RE = re.compile(
    r"^\s*(?:[（(]\s*(?:讲义|笔记|讲义\s*[+＋]\s*笔记)\s*[）)]|(?:主讲|授课)(?:教师|老师)?\s*[:：].{0,12}|授课时间\s*[:：].{0,16}|"
    r"主讲\s*[:：].{0,8}|\S{0,4}粉笔\S{0,2}\s*[·•]\s*官方微信|凡?粉笔|遇见不一样的自己.*|Be\s*your\s*better\s*self|"
    r"come\s*to\s*meet\s*a\s*different\s*you|内部资料\s*请勿外传|20\d\d\s*年全国公职考试笔试|小黑月半时政班|小黑公益课|专题|"
    r"@超格\S{0,6}|【公考学长】\S*|国考、省考、事业编.*必备资料|涉及[:：]历史人文常识.*|公考学长合作机构.*|"
    r"高效实用\s*[·•]\s*通关必备.*|\S{0,6}出品|[(（]?关注逢考必胜公众号.*|送给最努力的你|免费获取更多备考资料|更多免费资料.{0,3}|"
    r"因为专注[，,]\s*所以专业|全新教研.*重点突出|逐题本|考前突击\s*[·•]\s*时政冲刺|免费咨询指导|彩色黑白同价|\d+\s*分\s*/\s*页|"
    r"\d大\S{0,4}工厂.*|A提取文字|微信码.*|\S{0,8}小程序印.*|白天|\d{2}年省考\s*/\s*事业编\s*[·•].{0,12}大纲分析与系统备考指导.{0,12}|更多内容尽在@?公考小黑老师.*|\W?上岸村\s*[·•]?\s*不辜负每一次相遇.*|每月基础考点、每月试题.*|[(（]?20\d\d\.\d{1,2}\s*[-—~]\s*20\d\d\.\d{1,2}[)）]?|HHM|粉笔app购课.*|[，。,.]*[A-Za-z][A-Za-z\s]{5,}|[^\w（）()_]{1,3}|津仕教育)\s*$", re.I)
# 扫描件上的水印“微信公众号：橙子考公资料站”，OCR 认成零碎的“微信”“橙子”“言公众”“瓷料站”
WM_CHARS = set("微信公众号橙子考公资料站言么瓷专材")
WM_IN_RE = re.compile(r"微信公众号?\s*(?:[:：.。]\s*(?:橙子\S{0,2}考公资料站)?|$)|橙子\s*考公\s*资料站|考公资料站")


def _watermark_line(t):
    s = re.sub(r"[\W\d_A-Za-z]", "", t or "")
    if 3 <= len(s) <= 16 and "教育" in s and set(s) <= set("津仕土士教育") and set(s) & set("津仕土士"):
        return True  # 扫描件角上的“津仕教育”水印（OCR 成“土教育教育”）
    inset = sum(ch in WM_CHARS for ch in s)
    return 0 < len(s) <= 8 and inset >= max(1, len(s) * 0.75) \
        and (bool(re.search(r"微信|信公|公众|橙子|资料站|考公|众号|料站", s)) or (len(s) >= 3 and inset == len(s)))


def _clean_lines(t):
    """块里的一行行：套话、水印碎片整行去掉；“【答案】A 众号”去掉后面的水印。"""
    if not t:
        return ""
    out = []
    for ln in t.split("\n"):
        if BOILER_RE.match(ln) or _watermark_line(ln):
            continue
        ln = WM_IN_RE.sub("", ln)
        ln = re.sub(r"^\s*[津仕]\s+(?=\d{1,3}\s*[.．、])", "", ln)  # 水印残字粘在题号前
        m = re.match(r"^(\s*【\s*答\s*案\s*】\s*[A-H]{1,6})([^【]*)$", ln)
        if m and _watermark_line(m.group(2)) or (m and not re.sub(r"[\W\d_]", "", m.group(2))):
            ln = m.group(1)
        out.append(ln)
    return "\n".join(out)


def _cover_pages(blocks, pages):
    """第一页是封面（几行字、没有题、没有成段的正文）：不要。"""
    if pages < 3:
        return set()
    p0 = [b for b in blocks if b.get("pg", 0) == 0]
    if not p0 or any(b["k"] == "q" for b in p0):
        return set()
    text = [b.get("t") or "" for b in p0 if b["k"] != "img"]
    cjk = sum(len(re.findall(r"[一-鿿]", t)) for t in text)
    if cjk < 100 and not any(len(re.findall(r"[一-鿿]", t)) > 40 for t in text):
        return {0}
    return set()


def _clean_text(t, emph=False, cell=False):
    t = (t or "").replace("\u200b", "")
    t = _unmask(t)
    t = WM_IN_RE.sub("", t) if cell else _clean_lines(t)
    if emph:
        t = EMPH_RE.sub("", t)
    t = JUNK_IN_RE.sub("", t).translate(RADICALS)
    t = re.sub(r"_{2,}(?=\*\*)", "", t).replace("**", "")  # AI 笔记导出的 Markdown 记号“____**源流发展**”
    t = re.sub(r"\s*★\s+★\s*$", "", t.replace("✎", ""))
    # “179.2023年3月16日……”：题号后紧跟年份，例题识别会当成小数认不出题号；中间加个空格
    t = re.sub(r"^(\s*\d{1,3}\s*[.．])(?=(?:19|20)\d\d\s*年|\d{1,2}\s*月\s*\d{1,2}\s*日)", r"\1 ", t)
    # “42.【答案】D。解析：……” → 资料库例题识别认得的“42.【答案】D【解析】……”
    t = re.sub(r"^(\s*\d{1,3}\s*[.．、]\s*【\s*答\s*案\s*】\s*[A-H]{1,4})\s*[。.．]?\s*(?:【\s*)?解\s*析\s*(?:】|[:：])\s*",
               r"\1【解析】", t)
    return t.strip()


def _page_text(blocks):
    by = defaultdict(list)
    for b in blocks:
        by[b.get("pg", 0)].append(b.get("t") or "")
        d = b.get("d") or {}
        for _dp, it in d.get("items") or []:
            by[b.get("pg", 0)].append(it)
        for ln in d.get("lines") or []:
            by[b.get("pg", 0)].append(ln[0])
    return {p: "\n".join(v) for p, v in by.items()}


def _ad_pages(blocks):
    """整页是机构广告（师资介绍、扫码下载、课程推荐）的页。"""
    out = set()
    for p, text in _page_text(blocks).items():
        hits = sum(1 for w in AD_WORDS if w in text)
        if hits >= 5 or (hits >= 3 and len(re.sub(r"\s", "", text)) < 200):
            out.add(p)
    return out


def _drop_pages(blocks, pages):
    return [b for b in blocks if b.get("pg", 0) not in pages]


# “D.①③④1-3.【小黑政治理论】……”：选项和下一题题干在同一行
NEXT_STEM_RE = re.compile(r"(?<=[^\d\s\-－])\s*(?=\d{1,3}(?:-\d{1,2})?\s*[.．]\s*【[^】]{2,12}】)")


def _split_stems(blocks):
    out = []
    for b in blocks:
        t = b.get("t") or ""
        if b["k"] == "p" and "\n" not in t and NEXT_STEM_RE.search(t):
            parts = [x for x in NEXT_STEM_RE.split(t) if x.strip()]
            out += [dict(b, t=x.strip()) for x in parts]
        else:
            out.append(b)
    return out


def _clean_blocks(blocks):
    emph = sum((b.get("t") or "").count("．．") for b in blocks) >= 20
    ct = lambda t: _clean_text(t, emph)  # noqa: E731
    out = []
    for b in blocks:
        if len(re.findall(r"[￥¥]\s*\d", b.get("t") or "")) >= 2:
            continue  # 课程价目表（“冲刺班 ￥99 …”）
        if b["k"] in ("p", "h"):
            if JUNK_LINE_RE.match(b.get("t") or "") or re.fullmatch(r"\s*[一-鿿]\s*", b.get("t") or ""):
                continue  # 单独一个字的段落：logo、印章认出的残字（“川”）
            b["t"] = ct(b["t"])
            if not b["t"]:
                continue
        elif b.get("t"):
            b["t"] = ct(b["t"])
        d = b.get("d") or {}
        if d.get("items"):
            d["items"] = [[a, ct(t)] for a, t in d["items"] if not JUNK_LINE_RE.match(t) and ct(t)]
        if d.get("lines"):
            d["lines"] = [[ct(t), a] for t, a in d["lines"] if not JUNK_LINE_RE.match(t) and ct(t)]
        if d.get("rows"):
            d["rows"] = [[_clean_text(c, emph, cell=True) for c in r] for r in d["rows"]]
        out.append(b)
    return out


def _drop_plain_versions(blocks):
    """成语随堂演练：每天先是“纯净版”（只有题），后面是“答案版 / 解析版”（同样的题带答案）。纯净版的页不要。"""
    texts = _page_text(blocks)
    drop, on = set(), False
    for p in sorted(texts):
        head = texts[p][:120]
        if re.search(r"纯\s*净\s*版", head):
            on = True
        elif re.search(r"答\s*案\s*版|解\s*析\s*版|答案及解析", head):
            on = False
        if on:
            drop.add(p)
    if drop and len(drop) < len(texts):
        return _drop_pages(blocks, drop)
    return blocks


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
QSTART_RE = re.compile(r"^\s*(?:\d{1,3}\s*[.．、]|[（(]\s*(?:单选|多选|不定项|判断)\s*[）)]|【[^】]{1,8}】\s*[（(])")


def _merge_statements(blocks):
    """题干后面一行一条的“①……②……”是题干的一部分：并进题干（例题识别只取选项上面最近的一段当题干）。"""
    out = []
    chain = False  # 上一块是题干或者已经并进来的说法
    for b in blocks:
        t = (b.get("t") or "").strip()
        if b["k"] == "p" and t[:1] in CIRCLED and out and out[-1]["k"] == "p" and chain \
                and not re.match(r"^\s*[A-H]\s*[.．、]", t):
            out[-1]["t"] = out[-1]["t"].rstrip() + "\n" + t
            continue
        if b["k"] == "p":
            chain = bool(QSTART_RE.match(t)) or (t[:1] in CIRCLED and chain)
        else:
            chain = False
        out.append(b)
    return out


PARA_START_RE = re.compile(r"^\s*(?:[" + CIRCLED + r"]|[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|\d{1,2}\s*[.．、]|"
                           r"[A-H]\s*[.．、]|【|“[^”]{0,12}”[:：]|\S{2,8}[:：])")
SENT_END_RE = re.compile(r"[。！？!?；;：:”」）)】…]$")


def _rejoin(blocks, demote=False):
    """被换行拆开的句子接回来（上一段没有句末标点、下一段也不像新段落的开头）。
    demote：评论文章窄栏排版，一行常被当成标题，太长、带逗号顿号的“标题”改回正文。"""
    out = []
    for b in blocks:
        t = (b.get("t") or "").strip()
        if demote and b["k"] == "h" and (len(t) > 26 or (len(t) > 8 and re.search(r"[，。；、：]", t)
                                                         and not re.match(r"^\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[）)])", t))):
            b = dict(b, k="p")
            b.pop("lv", None)
        prev = out[-1] if out else None
        if b["k"] == "p" and prev is not None and prev["k"] == "p" and abs(prev.get("pg", 0) - b.get("pg", 0)) <= 1 \
                and not SENT_END_RE.search(prev["t"]) and len(prev["t"]) >= 10 \
                and (not PARA_START_RE.match(t) or (t.startswith("一、") and len(prev["t"]) >= 30)) \
                and not (prev.get("d") or {}).get("b") and not (b.get("d") or {}).get("b") \
                and not QSTART_RE.match(t) and "\n" not in prev["t"]:
            prev["t"] = prev["t"].rstrip() + t
            continue
        out.append(b)
    return out


# 像目录项的标题：编号、【小节】、关键词、考点、第几部分、几月……
STRUCT_HEAD_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十百]+\s*[、.．]|[（(]\s*[一二三四五六七八九十百\d]+\s*[）)]|第\s*[一二三四五六七八九十百\d]+\s*[部分章节篇讲课套期]|"
    r"\d{1,2}\s*[.．、](?!\d)|【[^】]{1,16}】|关键词|考点|押题点|热点|专题|附[录件]|[一二三四五六七八九十]+月|\d{1,2}\s*月|"
    r"(?:19|20)\d\d\s*年|\S{0,20}(?:编|章|节|篇|部分)$)")
# 标题里只有这些词也算小节（随堂练习、经典母题、题目答案……）
SECTION_WORD_RE = re.compile(r"母题|答案|演练|练习|总结|巩固|导图|框架|小结|预测|示例|素材|真题|解析|题本|金卷|清单|讲义|笔记|"
                             r"单选|多选|判断|不定项|材料|原文|解读|梳理|回顾|积累")
# 不像标题：答案、选项、批注符号、题干片段
NOISE_HEAD_RE = re.compile(r"[" + CIRCLED + r"~&ˇ√×]|【\s*答\s*案|参考答案\s*[:：]|->|挖坑|下列|[A-H]\s*[.．、].*[B-H]\s*[.．、]|"
                           r"[:：？?]\s*[A-H]{1,4}\s*$|^\s*[-~、，。）)》”]|^[^一-鿿]*$")


def _lv(b):
    return 1 if b.get("lv") is None else b["lv"]


def _norm(t):
    return re.sub(r"[\s\W_]", "", t or "")


LIST_MARK_RE = re.compile(r"^\s*(?:\d{1,2}\s*[.．、]|[（(]?[一二三四五六七八九十\d]+[）)、]|[" + CIRCLED + "])")


def _join_wrapped_nodes(items):
    """导图里一个框折成两行，常被拆成两个同级节点（“新疆维吾尔自治区成” / “立70周” / “年”）：接回去。
    后一个是紧挨着的同级节点，且是很短的残字，或在一串编号节点里唯独它没编号、前一个也没写完。"""
    out = []
    for dep, t in items:
        prev = out[-1] if out else None
        if prev is not None and prev[0] == dep and not LIST_MARK_RE.match(t):
            sibs = [x for d, x in items if d == dep]
            numbered = sum(1 for x in sibs if LIST_MARK_RE.match(x)) >= max(2, len(sibs) * 0.4)
            cjk = len(re.findall(r"[一-鿿]", t))
            short = (cjk <= 1 or (cjk <= 4 and re.search(r"\d", t))) and not re.search(r"[。！？；]$", prev[1])
            if short or (numbered and LIST_MARK_RE.match(prev[1]) and not re.search(r"[。！？；：:]$", prev[1])):
                prev[1] = prev[1] + t.strip()
                continue
        out.append([dep, t])
    return out


def _in_numbered_list(blocks, b, n):
    """b 的前一段是“n-1.”开头、或后一段是“n+1.”开头（正文或同样被当成标题的条目）。"""
    i = next((j for j, x in enumerate(blocks) if x is b), None)
    if i is None:
        return False

    def num(x):
        m = re.match(r"\s*(\d{1,2})\s*[.．、]", x.get("t") or "") if x and x["k"] in ("p", "h") else None
        return int(m.group(1)) if m else None

    prev = blocks[i - 1] if i > 0 else None
    nxt = blocks[i + 1] if i + 1 < len(blocks) else None
    return num(prev) == n - 1 or num(nxt) == n + 1


def _letter_answers(blocks):
    """幻灯片讲解：题目下一页只写着答案字母（“B”）。挂到上面那道还没有答案的题上，这一行去掉。"""
    out = []
    for b in blocks:
        m = re.fullmatch(r"\s*(?:答案\s*[:：]?\s*)?([A-H]{1,4})\s*", b.get("t") or "") if b["k"] in ("p", "h") else None
        prev = next((x for x in reversed(out) if x["k"] != "h"), None)
        if m and prev is not None and prev["k"] == "q" and not prev["d"].get("ans") \
                and set(m.group(1)) <= {a for a, _o in prev["d"].get("opts") or []}:
            prev["d"]["ans"], prev["d"]["how"] = m.group(1), "资料给出"
            continue
        out.append(b)
    return out


def manual_key(q):
    """补答案文件的指纹：题干头尾 + 选项原文开头（“①②④⑤”这类选项不能像 docq.qkey 那样去掉符号，否则组合题撞车）。"""
    from .docq import _key
    k = _key(q["stem"])
    return k[:40] + "|" + k[-16:] + "|" + "/".join(re.sub(r"\s", "", o)[:8] for _a, o in q.get("opts") or [])


def fill_answers(conn):
    """全部整理完、各种对答案都做过之后，还空着答案的题：
    1. 解析里写着“【选D】”、答案栏却空着（讲义解析和题分开排）——取解析里第一个【选X】；
    2. content/shizheng_answers.json 里人工补的答案和解析 {指纹: {"ans", "exp"} | {"text": 1}}（粉笔串讲等讲义不给答案）。"""
    from .paths import content_dir
    try:
        manual = json.loads((content_dir() / "shizheng_answers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manual = {}
    upd = []
    for r in conn.execute("SELECT doc, seq, data FROM blocks WHERE kind='q'").fetchall():
        q = json.loads(r["data"])
        if q.get("ans") or q.get("notq"):
            continue
        letters = {a for a, _o in q.get("opts") or []}
        m = re.search(r"【选\s*([A-H]{1,6})\s*】", " ".join(e.get("t") or "" for e in q.get("exp") or []))
        hit = manual.get(manual_key(q))
        if m and set(m.group(1)) <= letters:
            q["ans"], q["how"] = m.group(1), "资料给出"
        elif hit and hit.get("text"):
            q["notq"] = True  # 人工核对过：讲义正文 / 图片说明被认成了题
        elif hit and letters and set(hit["ans"]) <= letters:
            q["ans"], q["how"] = hit["ans"], "补充解答"
            q["exp"] = [{"t": hit["exp"]}] + [e for e in q.get("exp") or [] if (e.get("t") or "").strip()]
        else:
            continue
        upd.append((json.dumps(q, ensure_ascii=False), r["doc"], r["seq"]))
    if upd:
        with _lock, conn:
            conn.executemany("UPDATE blocks SET data=? WHERE doc=? AND seq=?", upd)
    return len(upd)


def _tidy_headings(blocks, title, ocr_pages=frozenset(), img_pages=frozenset()):
    """整理标题：封面上的书名、批注碎片、答案行、重复的幻灯片标题不进目录；层级重新排成 1、2、3……"""
    for b in blocks:
        if b["k"] == "tree" and b.get("d"):
            items = _join_wrapped_nodes(b["d"].get("items") or [])
            if len(items) != len(b["d"].get("items") or []):
                b["d"]["items"] = items
                b["t"] = ("\n" if "\n" in (b.get("t") or "") else " ").join(t for _d, t in items)
            roots = [t.strip() for dep, t in b["d"].get("items") or [] if dep == 0]
            # 导图主干是残字（“8月时”“之举”“自由贸易试验区22”）、标题被拆成几个主干的，不补进目录
            if len(roots) > 1 or any(len(re.findall(r"[一-鿿]", t)) < 4 or re.search(r"\d", t) or NOISE_HEAD_RE.search(t) for t in roots):
                b["d"]["notoc"] = 1
    heads = [b for b in blocks if b["k"] == "h"]
    if not heads:
        return blocks
    if sum(1 for b in blocks if b["k"] == "q") >= 50:
        ocr_pages = set(ocr_pages) | set(img_pages)
    noisy = sum(1 for b in heads if NOISE_HEAD_RE.search(b["t"]))
    # 手写批注版：只认像目录项的标题；扫描页（OCR 按字号猜的标题）更严
    notes = noisy >= 5 and noisy >= len(heads) * 0.15
    tnorm = _norm(re.sub(r"[（(][^）)]*[）)]", "", title or ""))
    parts = sum(1 for b in heads if re.search(r"[（(]\s*(?:讲义|笔记)\s*[）)]\s*$", b["t"]))
    out, last_head, seen_body, drop_to = [], None, False, None
    for b in blocks:
        if drop_to is not None:
            if b["k"] == "h" and b.get("lv", 1) <= drop_to:
                drop_to = None
            else:
                continue
        if b["k"] != "h":
            if b["k"] != "img":
                seen_body = True
            out.append(b)
            continue
        t = b["t"].strip()
        n = _norm(t)
        cjk = len(re.findall(r"[一-鿿]", t))
        struct = bool(STRUCT_HEAD_RE.match(t))
        if re.match(r"^\s*免责声明\s*$", t):
            drop_to = b.get("lv", 1)
            continue
        # 开头重复书名的标题、只有一份讲义 / 笔记时的“××（笔记）”
        bare = _norm(re.sub(r"[（(]\s*(?:讲义|笔记|讲义\s*[+＋]\s*笔记)\s*[）)]\s*$", "", t))
        is_part = bool(re.search(r"[（(]\s*(?:讲义|笔记)\s*[）)]\s*$", t))
        if not (is_part and parts >= 2) and not seen_body and len(bare) >= 4 and tnorm and (bare in tnorm or tnorm in bare
                                                           or (not struct and sum(ch in tnorm for ch in bare) >= len(bare) * 0.7)):
            continue
        if parts == 1 and re.search(r"[（(]\s*(?:讲义|笔记)\s*[）)]\s*$", t):
            continue
        # 和上一个标题一样（每页幻灯片都印一遍）
        if last_head is not None and n == _norm(last_head["t"]):
            continue
        # 句中有句号、末尾是页码样的数字：是正文或批注被认成了标题
        # 两段话中间空格、汉字间夹着短横（批注、导图拼在一行），整句法条（“……的。”）也不是标题
        demote = bool(NOISE_HEAD_RE.search(t)) or bool(re.search(r"。”?\s*$", t) and cjk > 20) or bool(
            not struct and re.search(r"。.|[:：]\s*\d{1,3}\s*$|[一-鿿]{2}[：:，]?\s+\S*[一-鿿]{2}|[一-鿿][-—][一-鿿]|^“", t)) or (
            not struct and any(t.count(a) != t.count(z) for a, z in ("《》", "（）", "“”")))  # 半截书名、括号：残句
        nm = re.match(r"\s*(\d{1,2})\s*[.．、]", t)
        if not demote and nm and (_in_numbered_list(blocks, b, int(nm.group(1))) or (cjk > 30 and "。" in t.rstrip("。 "))):
            demote = True  # 一串“5. 6. 7.”里字号大一点的那条，不是标题
        if not demote and not struct and not SECTION_WORD_RE.search(t):
            demote = cjk <= 2 or (cjk <= 5 and not seen_body) or (notes and cjk <= 12) or b.get("pg", 0) in ocr_pages
        if demote:
            b = dict(b, k="p")
            b.pop("lv", None)
            if b.get("d"):
                b["d"] = {k: v for k, v in b["d"].items() if k != "b"}  # 加粗也去掉，免得又被当成目录项
            out.append(b)
            continue
        last_head = b
        out.append(b)
    # 讲义 + 笔记两部分：“××（讲义）”“××（笔记）”做最上一级
    if parts >= 2:
        top = min((_lv(b) for b in out if b["k"] == "h"), default=1)
        for b in out:
            if b["k"] == "h" and re.search(r"[（(]\s*(?:讲义|笔记)\s*[）)]\s*$", b["t"]):
                b["lv"] = top - 1
    # 同一个样子的标题（“2023年5月1-4日时事政治考点”“……5-6日……”）同级：OCR 估的字号有大有小，取最高的那级
    shape = lambda b: re.sub(r"[\d一二三四五六七八九十]+", "#", _norm(b["t"]))  # noqa: E731
    same = Counter(shape(b) for b in out if b["k"] == "h")
    top_of = {}
    for b in out:
        if b["k"] == "h" and same[shape(b)] >= 3:
            top_of[shape(b)] = min(top_of.get(shape(b), 99), _lv(b))
    for b in out:
        if b["k"] == "h" and shape(b) in top_of:
            b["lv"] = top_of[shape(b)]
    # 层级重排成 1、2、3：挂到前面最近一个级别更高的标题下面，同级的仍然同级，不会隔级
    stack = []  # [(原级别, 新级别)]
    for b in out:
        if b["k"] == "h":
            orig = _lv(b)
            while stack and stack[-1][0] >= orig:
                stack.pop()
            b["lv"] = stack[-1][1] + 1 if stack else 1
            stack.append((orig, b["lv"]))
    return out


def _drop_outline_dump(blocks):
    """有的 PDF 书签没有页码，整理时整串书签被当成标题堆在最前面（后面正文里还会再出现一次）：去掉。"""
    i = 0
    while i < len(blocks) and blocks[i]["k"] == "h":
        i += 1
    if i < 3:
        return blocks
    later = {re.sub(r"\s", "", b.get("t") or "") for b in blocks[i:] if b["k"] in ("h", "p")}
    lead = blocks[:i]
    if sum(1 for b in lead if re.sub(r"\s", "", b.get("t") or "") in later) >= len(lead) * 0.6:
        return blocks[i:]
    return blocks


def _nodes_from_items(items):
    """导图上的文字（x0, y0, x1, y1, 文字）→ 节点：同一个框里折行的几行并成一个节点。"""
    items = sorted(items, key=lambda i: (round(i[0] / 6), i[1]))
    nodes = []
    for it in sorted(items, key=lambda i: (i[1], i[0])):
        h = it[3] - it[1]
        for nd in reversed(nodes[-12:]):
            if abs(nd["x0"] - it[0]) < max(6, h * 0.6) and 0 <= it[1] - nd["y1"] < h * 0.8 and abs((nd["h"]) - h) < h * 0.35:
                nd["t"] += it[4]
                nd["y1"] = it[3]
                nd["x1"] = max(nd["x1"], it[2])
                break
        else:
            nodes.append({"x0": it[0], "y0": it[1], "x1": it[2], "y1": it[3], "h": h, "t": it[4]})
    return nodes


def mindmap_tree(items, title=""):
    """把一页思维导图还原成提纲 [(层级, 文字)]：按横坐标分层，每个节点挂到左边一层里纵向离它最近的节点下。"""
    nodes = [n for n in _nodes_from_items(items) if re.sub(r"[\s\"“”'·•*]", "", n["t"])]
    if len(nodes) < 5:
        return []
    # 竖排的大标题（一字一行）是根，不进提纲
    width = max(n["x1"] for n in nodes) - min(n["x0"] for n in nodes)
    left = min(n["x0"] for n in nodes)
    nodes = [n for n in nodes if not (len(re.sub(r"\s", "", n["t"])) <= 2 and n["x0"] - left < width * 0.12)]
    for n in nodes:
        n["t"] = re.sub(r"\*+", "", n["t"]).strip()
    # 根节点（文章标题）折成了几块：标题里的片段都不要，下一层直接当根
    tkey = re.sub(r"\W", "", title)
    if tkey:
        nodes = [n for n in nodes if not (n["x0"] - left < width * 0.2 and re.sub(r"\W", "", n["t"])
                                          and re.sub(r"\W", "", n["t"]) in tkey)]
    xs = sorted(n["x0"] for n in nodes)
    levels, cur = [], None
    for x in xs:
        if cur is None or x - cur > max(18, width * 0.04):
            levels.append(x)
        cur = x
    lv = lambda x: max(i for i, lx in enumerate(levels) if x >= lx - max(18, width * 0.04))  # noqa: E731
    for n in nodes:
        n["lv"] = lv(n["x0"])
        n["cy"] = (n["y0"] + n["y1"]) / 2
        n["kids"] = []
    roots = []
    for n in sorted(nodes, key=lambda n: n["cy"]):
        cands = [p for p in nodes if p["lv"] < n["lv"] and p["x1"] <= n["x0"] + 4]
        if not cands:
            roots.append(n)
            continue
        top = max(p["lv"] for p in cands)
        p = min((p for p in cands if p["lv"] == top), key=lambda p: abs(p["cy"] - n["cy"]))
        p["kids"].append(n)
    out = []

    def walk(n, d):
        out.append([d, n["t"]])
        for k in sorted(n["kids"], key=lambda k: k["cy"]):
            walk(k, d + 1)

    for r in sorted(roots, key=lambda r: r["cy"]):
        walk(r, 0)
    if title and out and re.sub(r"\W", "", out[0][1]) == re.sub(r"\W", "", title):
        out = [[d - 1, t] for d, t in out[1:]]
    return out


def _unreadable(text):
    """文字层取出来读不通：字体映射坏了（“⭩䇰㿺㤹”“ⴻլн䎧”这种生僻字、外文字母一串），或资料库认得的乱码。"""
    from . import docs

    if docs.garbled(text):
        return True
    cjk = re.findall(r"[一-鿿]", text)
    odd = len(re.findall(r"[԰-῿Ⰰ-ⷿ㐀-䶿ꀀ-퟿]", text))
    if len(cjk) + odd < 40:
        return False
    common = sum(1 for ch in cjk if ch in docs.COMMON_CHARS)
    return odd > (len(cjk) + odd) * 0.1 or common < len(cjk) * 0.03


def _page_items(root, f, pno, raw=False):
    """一页上的文字块：有文字层用文字层，没有用 OCR（结果有缓存）。raw：页眉、导图水印这些也留着（认版式用）。"""
    import pymupdf

    from . import docs

    d = pymupdf.open(os.path.join(root, f["rel"]))
    try:
        page = d[pno]
        items = []
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if t:
                    x0, y0, x1, y1 = ln["bbox"]
                    items.append((x0, y0, x1, y1, t))
        if sum(len(i[4]) for i in items) < 30 or _unreadable("".join(i[4] for i in items)):
            boxes = docs._ocr_boxes(f["id"], pno, page) or []  # 扫描页、字体映射坏了的页（“⭩䇰㿺㤹”）
            items = [(b[0], b[1], b[2], b[3], str(b[4]).strip()) for b in boxes if str(b[4]).strip()]
        from .pdftext import ORNAMENT_RE, fix_chars
        items = [(a, b, c, e, fix_chars(t).translate(RADICALS)) for a, b, c, e, t in items if not ORNAMENT_RE.fullmatch(t)]
        if raw:
            return items
        return [i for i in items if not JUNK_LINE_RE.match(i[4]) and not re.search(r"xmind|公众号|叛逆小樱桃|樱桃资料", i[4])]
    finally:
        d.close()


def _article_column(items):
    """批注版第 1 页：左边一栏是笔记（导图里都有），右边是原文。只取右栏，按缩进分段。"""
    if not items:
        return []
    W = max(i[2] for i in items)
    col = sorted([i for i in items if i[0] >= W * 0.27], key=lambda i: (i[1], i[0]))
    if not col:
        return []
    h = sorted(i[3] - i[1] for i in col)[len(col) // 2]
    left = sorted(i[0] for i in col)[len(col) // 5]
    right = sorted(i[2] for i in col)[len(col) * 4 // 5]
    paras, prev = [], None
    for it in col:
        t = it[4].strip()
        if prev is not None and abs(it[1] - prev[1]) < h * 0.5:  # 同一行被拆成两块
            paras[-1] += t
            prev = it
            continue
        new = prev is None or it[0] > left + h * 1.2 or prev[2] < right - h * 2.5 or it[1] - prev[3] > h * 1.2
        if new:
            paras.append(t)
        else:
            paras[-1] += t
        prev = it
    return [p for p in paras if len(p) >= 2]


def _jd_page_kind(items, W, H, image):
    """2025.6—2026.4 精读讲义一页是什么：
    A 批注版原文（左栏“×月×日文章精读笔记”、右栏原文夹手写批注）；C 干净原文（也印着“精读笔记”抬头，正文通栏）；
    O 末尾附的人民网原文（“2026年03月13日 06:14 | 人民网－人民日报”）；M 思维导图（xmind 导出、扫描图、横版）；T 其他文字页。"""
    txt = "".join(i[4] for i in items)
    if re.search(r"精读笔记", txt):
        wide = sum(1 for i in items if i[0] < 0.2 * W and i[2] - i[0] > 0.5 * W)
        right = sum(1 for i in items if i[0] > 0.25 * W and i[2] - i[0] > 0.4 * W)
        if wide >= 5:
            return "C"
        if right >= 5:
            return "A"
    if re.search(r"20\d\d\s*年\s*\d{1,2}\s*月\s*\S{0,2}\d{1,2}\s*日\S{0,3}\s*\d{1,2}\s*[:：]\s*\d{2}.{0,4}人民[网網]", txt[:300]):
        return "O"
    if re.search(r"(?i)xmind", txt) or W > H * 1.1 or image:
        return "M"
    return "T"


def _jd_layout(root, f, blocks, title):
    """2025.6—2026.4 的精读讲义：一份里有批注版原文、干净原文、导图、金句和范文页，版式每月不一样。
    按页认出来：原文取干净的那份（没有就从批注版取右栏），放最前面；导图页还原成提纲；批注版不要。"""
    import pymupdf


    d = pymupdf.open(os.path.join(root, f["rel"]))
    try:
        pages = [(d[i].rect.width, d[i].rect.height, len(d[i].get_text().strip()) < 30)
                 for i in range(d.page_count)]
    finally:
        d.close()
    kinds, items = [], []
    for pno, (W, H, image) in enumerate(pages):
        its = _page_items(root, f, pno, raw=True)
        items.append(its)
        kinds.append(_jd_page_kind(its, W, H, image))
    has_n = any(k in "AC" for k in kinds)
    article, drop = [], set()
    if "C" in kinds:
        cp = [i for i, k in enumerate(kinds) if k == "C"]
        article = [b for b in blocks if b.get("pg", 0) in cp]
        drop |= {i for i, k in enumerate(kinds) if k == "A"} | set(cp)
    elif "A" in kinds:
        cols = [(i, _article_column([x for x in items[i] if not re.search(r"精读笔记|xmind|公众号", x[4])]))
                for i, k in enumerate(kinds) if k == "A"]
        # 有的讲义两页原文排反了：开头带“——编者”按语的那页才是第一页
        lead = next((j for j, (_i, ps) in enumerate(cols) if j and any(re.search(r"[—一－]{1,2}\s*编\s*者", p) for p in ps[:8])), None)
        if lead is not None:
            cols = [cols[lead]] + cols[:lead] + cols[lead + 1:]
        for i, paras in cols:
            if article and paras and not SENT_END_RE.search(article[-1]["t"]):
                article[-1]["t"] += paras.pop(0)  # 一段跨了两页
            article += [{"k": "p", "t": p, "pg": i} for p in paras]
            drop.add(i)
    elif "O" in kinds:
        # 末尾附的干净原文；第 1 页的批注版也印着同样的人民网抬头，不要
        op = max(i for i, k in enumerate(kinds) if k == "O")
        article = [b for b in blocks if b.get("pg", 0) == op]
        drop |= {i for i, k in enumerate(kinds) if k == "O"} | {0}
    rest = []
    for pno in range(len(pages)):
        if pno in drop:
            continue
        pb = [b for b in blocks if b.get("pg", 0) == pno]
        if kinds[pno] == "M" or (has_n and kinds[pno] == "T"):
            tree = mindmap_tree([x for x in items[pno] if not re.search(r"(?i)xmind|公众号|樱桃资料", x[4])], title)
            if len(tree) >= 5:
                pb = [{"k": "h", "lv": 1, "t": "思维导图", "pg": pno},
                      {"k": "tree", "t": "\n".join(t for _d, t in tree), "pg": pno, "d": {"items": tree}}]
            elif pages[pno][2] and article:
                pb = []  # 扫描的导图图片还原不出层级，认出的是一堆零散节点：原文、笔记里都有，不要
        rest += pb
    return article + rest


# 精读讲义里的板块（每页页眉也印一遍“拆解报告”）
JD_SEC_RE = re.compile(r"^\s*(拆解报告|金句积累|金句摘录|金句|申论规范词|规范词积累|申论对策题\s*\d*|仿写申论作文|仿写范文|思维导图|"
                       r"写作框架|结构笔记|文章结构)\s*[:：]?\s*(.*)$", re.S)
JD_AD_RE = re.compile(r"\s*(?:人民日报\s*[:：]?\s*)?(?:PDF\s*合集|(?:更多)?公考资料(?:免费)?(?:更新)?|资料免费)\s*加\s*[:：]?\s*(?:shgk\d*)?|"
                      r"\s*shgk\d{3,}|"
                      r"\s*公众号\s*[:：]?\s*叛逆小樱桃资\S?|(?<![一-鿿])(?:叛逆)?小?樱桃资料(?![一-鿿])")
JD_LOGO_RE = re.compile(r"^[人民日報报款阳旧E一\s]{2,5}$")  # 报头“人民日報”认成的“民阳款”“人民旧款”
JD_TEMPLATE_RE = re.compile(r"^\s*(?:每日|积累|正文|拆解报告|解读\s*[:：].{0,10}|由示例引出主题)\s*$")
BYLINE_RE = re.compile(r"^\s*(?:[（(]\s*20\d\d\s*年|作者\s*[:：]|《人民日报》|.{0,12}[|｜]\s*《?人民日报》?\s*[（(]?20\d\d)")


def _essay_titles(root, f):
    """仿写范文的题目（“仿写范文：  标题：以优质公共服务 兜底幸福民生”单独一行、字号大）。
    整理时它和范文第一段拼成了一段，这里从文字层取出题目，好在目录里单列。"""
    import pymupdf

    out = []
    d = pymupdf.open(os.path.join(root, f["rel"]))
    try:
        for page in d:
            for blk in page.get_text("dict")["blocks"]:
                for ln in blk.get("lines", []):
                    t = "".join(s["text"] for s in ln["spans"]).strip()
                    m = re.match(r"^(?:仿写\S{0,4}[:：]\s*)?标\s*题\s*[:：]\s*(\S.{2,40})$", t)
                    if m:
                        out.append(m.group(1).strip())
    except Exception:  # noqa: BLE001
        pass
    finally:
        d.close()
    return out


def _strip_title(t, tnorm):
    """段落开头印着文章标题（批注版每页页眉、原文第一行）：去掉。OCR 会认错一两个字，按字逐个对。"""
    if not tnorm or len(tnorm) < 4:
        return t
    i = j = miss = 0
    while i < len(t) and j < len(tnorm):
        ch = t[i]
        if not re.match(r"[\w]", ch):
            i += 1
            continue
        if ch == tnorm[j]:
            j += 1
        elif j + 1 < len(tnorm) and ch == tnorm[j + 1]:
            j += 2  # 漏认了一个字
        else:
            miss += 1
            j += 1
            if miss > 2:
                return t
        i += 1
    if j >= len(tnorm) and miss <= max(1, len(tnorm) // 8):
        return t[i:].lstrip("”\"' ，,")
    return t


# 署名行：“作者：何娟|来源：人民日报|版面：第05版|日期：2025年09月29日”“申少铁|《人民日报》（2025年05月08日第09版）”
BYLINE_SPLIT_RE = re.compile(r"^(.{0,90}?(?:日期\s*[:：]\s*20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
                             r"《?人民日报》?\s*[（(]\s*20\d\d\s*年[^）)]{0,20}[）)]|作者\s*[:：]\s*《人民日报》|"
                             r"20\d\d\s*年\s*\d{1,2}\s*月\S{0,2}\d{1,2}\s*日\S{0,3}\s*\d{1,2}\s*[:：]\s*\d{2}\s*\S{0,2}\s*人民[网網]\S{0,2}人民日报))"
                             r"\s*(.*)$", re.S)
# 批注版原文里手写的板块记号（“案例”“分论点：”），夹在正文段落之间
NOTE_LABEL_RE = re.compile(r"^\s*(?:案例|总论点|分论点\s*[\d一二三四五甲乙丙丁]?|论点|金句|对策|启示|现实启示|历史启示|背景|结论|开头|结尾)\s*[:：=]?\s*$")


# 超格热点汇总扫描件上的水印“公务员·选调生·事业编”，OCR 成“公务质选调士·事业编”“广洗调牛·事训编”，粘在标题、段落里
EXAM_WM_RE = re.compile(r"[公务员质]{1,3}\s*[·•，,.。:：]?\s*[选洗][调华小]{0,3}[生牛士]\s*[·•，,.。:：]?\s*[事重]?\s*[业训]\s*编|"
                        r"[选洗]\s*[调华小]{1,3}\s*[生牛士]\s*[·•，,.。:：]\s*[事重]?\s*[业训]\s*编")
EXAM_WM_HEAD_RE = re.compile(r"^\W*(?:[事重]\s*[业训]\s*编|[训业]编|仕教育?|[津聿律]仕教育?)\W*$")
# 热点汇总里按日期分段的小标题：“2023年1月5-6日时事政治考点”“2022年6月2日-6日”
DATE_HEAD_RE = re.compile(r"^\s*(?:20\d\d\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日?\s*(?:[-—–~～至]\s*(?:\d{1,2}\s*月\s*)?\d{1,2}\s*日?)?\s*"
                          r"(?:时事政治考点|时政热点考点|时政考点|时政热点)\s*$|^\s*20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?\s*[-—–~～至]\s*"
                          r"(?:\d{1,2}\s*月\s*)?\d{1,2}\s*日?\s*$")
# 题本里按月分的小标题：“1月时政题汇总”“二月重点时政题汇总”
MONTH_HEAD_RE = re.compile(r"^\s*(?:20\d\d\s*年\s*)?(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*月\s*(?:重点|核心)?\s*时政\s*题?\s*"
                           r"(?:汇总|梳理|刷题|题目)\s*$")
DATE_LEAD_RE = re.compile(r"^\s*(20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?\s*[-—–~～至]\s*(?:\d{1,2}\s*月\s*)?\d{1,2}\s*日)\s*([★☆●◆■].{8,})$", re.S)
JUNK_HEAD_RE = re.compile(r"合作推荐机构|感谢(?:您的|大家的)?观看|^\s*CONTENTS?\b|公众号|扫码|关注我们|^\s*THANKS?\s*$", re.I)
SUB_HEAD_RE = re.compile(r"^\s*【\s*(?:知识链接|相关时政|随堂点睛|延[申伸]补充|拓展|补充)\s*】")


def _polish_heads(blocks):
    """月度时政、专题、题库的标题收尾：水印残字、标题上的重要度星号、被当成标题的新闻条目 / 批注、
    导图里重复的节点、“【知识链接】”的层级；热点汇总里按日期分段的行补成标题。"""
    out, last_lv = [], 0
    for b in blocks:
        if b["k"] in ("p", "h") and b.get("t"):
            t = EXAM_WM_RE.sub("", b["t"]).strip()
            if b["k"] == "h":
                t = re.sub(r"\s+[津聿律]?仕教育?\s*$", "", t)
            if not t or (b["k"] == "h" and (EXAM_WM_HEAD_RE.match(t) or len(_norm(t)) <= 1)) \
                    or (re.fullmatch(r"[津仕土士聿教育\s]{1,6}", t) and "教" in t):
                continue  # 角上水印“津仕教育”认成的“教教”“仕教”
            if b["k"] == "h" and t != b["t"].strip() and not DATE_HEAD_RE.match(t):
                b = dict(b, k="p")  # 是水印的大字让这一行成了标题，剩下的是正文残句
                b.pop("lv", None)
            b = dict(b, t=t)
        if b["k"] == "p" and (DATE_HEAD_RE.match(b["t"]) or MONTH_HEAD_RE.match(b["t"])):
            b = dict(b, k="h", lv=1)
        elif b["k"] == "p" and (m := DATE_LEAD_RE.match(b["t"])):
            # “2022年5月1-5日★5月1日出版的……”：日期小标题和第一条新闻排在一行
            out.append(dict(b, k="h", lv=1, t=m.group(1).strip(), d=None))
            b = dict(b, t=m.group(2).strip())
        if b["k"] != "h":
            out.append(b)
            continue
        t = b["t"].strip()
        if JUNK_HEAD_RE.search(t):
            continue
        stars = ""
        m = re.search(r"\s*([★☆]{1,5})\s*\d{0,3}\s*[”\"]?\s*$", t)
        if m and len(t) > len(m.group(0)) + 1 and not t.startswith(("★", "☆")):
            stars, t = m.group(1), t[: m.start()].rstrip(" \"”")
        t = re.sub(r"^[（(](?=[^）)]*$)", "", t)  # “(经典母题”：半个括号
        t = re.sub(r"(?<=[一-鿿）)》”])\s*[，,.。、]$", "", t) if len(t) <= 24 else t
        demote = bool(re.match(r"^\s*[★☆✕✓✔✗✘×√]", t)) or (len(t) > 30 and re.search(r"[，。；]", t)) \
            or (re.search(r"：$", t) and "，" in t) or bool(re.match(r"^\s*\d{1,3}\s*[.．、]\s*\S.{20,}[，。]", t))
        if demote:
            nb = dict(b, k="p", t=t)
            nb.pop("lv", None)
            out.append(nb)
            continue
        # 导图、课件里同一个小标题紧接着又出现一遍（“（五）农业强省迈出新步伐” / “农业强省迈出新步伐”）
        core = _norm(re.sub(r"^\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|\d{1,2}\s*[.．、])", "", t))
        prev = [x for x in out[-4:] if x["k"] == "h"]
        if core and any(_norm(re.sub(r"^\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|\d{1,2}\s*[.．、])", "", x["t"])) == core
                        for x in prev):
            continue
        lv = b.get("lv") or 1
        if SUB_HEAD_RE.match(t):
            lv = last_lv + 1 if last_lv else lv  # “【知识链接】”挂在当前小节下面
        else:
            last_lv = lv
        out.append(dict(b, t=t, lv=lv))
        if stars:
            out.append({"k": "p", "t": f"重要程度：{stars}", "pg": b.get("pg", 0)})
    stack = []  # 去掉、降级了一些标题后层级会隔级：重新排成 1、2、3
    for b in out:
        if b["k"] == "h":
            orig = _lv(b)
            while stack and stack[-1][0] >= orig:
                stack.pop()
            b["lv"] = stack[-1][1] + 1 if stack else 1
            stack.append((orig, b["lv"]))
    return out


KEY_MARK_RE = re.compile(r"^\W{0,3}参\s*考\s*答\s*案\W{0,3}$")
KEY_LINE_RE = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*([A-H]{1,8})\s*[。.]?\s*$")


def _answer_keys(root, parts):
    """粉笔题本：每 5 道题后面一个“参考答案”，下面一行一个“1.D”“2.ABCD”。整理时这些短行常被并掉、丢掉，
    “参考答案”标记也常被当成标题去重掉，这里直接从文字层按顺序读出每一组答案 [(页, {题号: 答案})]。"""
    import pymupdf

    groups, off = [], 0
    for f in parts:
        n = f.get("pages") or 0
        if not f.get("text"):
            off += n
            continue
        try:
            d = pymupdf.open(os.path.join(root, f["rel"]))
        except Exception:  # noqa: BLE001
            off += n
            continue
        try:
            cur = None
            for pno, page in enumerate(d):
                for ln in page.get_text("text").splitlines():
                    t = ln.strip()
                    if not t:
                        continue
                    if KEY_MARK_RE.match(t) or re.search(r"参\s*考\s*答\s*案\s*$", t):
                        cur = (off + pno, {})
                        groups.append(cur)
                        continue
                    m = KEY_LINE_RE.match(t)
                    if cur is not None and m:
                        cur[1].setdefault(m.group(1), m.group(2))
                    elif cur is not None and cur[1] and (len(t) > 12 or re.match(r"\d{1,3}\s*[.．、]\s*[（(【]", t)):
                        cur = None  # 答案行结束（翻页时的页码、页眉这些短行不算）
            off += d.page_count
        finally:
            d.close()
    return [g for g in groups if g[1]]


def _apply_keys(blocks, keys):
    """题按编号分成一组组（编号从 1 重新开始就是新的一组），每组配它后面最近的那份答案：
    答案和这组最后一题在同一页或下一页、题号对得上、答案字母都在选项里。挂上答案后，答案行和“参考答案”标记不再单独显示。"""
    if not keys:
        return blocks

    def qnum(q):
        n = str(q.get("num") or "")
        if not n:
            m = re.match(r"^\s*(\d{1,3})\s*[.．、]", q.get("stem") or "")
            n = m.group(1) if m else ""
        return n

    runs, prev = [], None
    for b in blocks:
        if b["k"] != "q":
            continue
        d = b["d"]
        opts = d.get("opts") or []
        if opts and re.search(r"参\s*考\s*答\s*案\s*$", opts[-1][1] or ""):
            opts[-1] = [opts[-1][0], re.sub(r"\s*参\s*考\s*答\s*案\s*$", "", opts[-1][1])]
        n = qnum(d)
        if not n.isdigit():
            prev = None
            continue
        if prev is None or int(n) <= prev:
            runs.append([])
        runs[-1].append((b.get("pg", 0), d))
        prev = int(n)
    gi, used = 0, 0
    for run in runs:
        last_pg = run[-1][0]
        best = None
        for j in range(gi, len(keys)):
            pg, key = keys[j]
            if pg > last_pg + 1:
                break
            if pg < last_pg:
                continue
            nums = {qnum(q) for _p, q in run}
            ok = sum(1 for _p, q in run if key.get(qnum(q)) and set(key[qnum(q)]) <= {a for a, _o in q.get("opts") or []})
            if len(nums & set(key)) >= max(1, len(run) // 2) and ok >= len(run) * 0.6:
                best = j
                break
        if best is None:
            continue
        gi = best + 1
        for _p, q in run:
            letters = keys[best][1].get(qnum(q))
            if letters and not q.get("ans") and set(letters) <= {a for a, _o in q.get("opts") or []}:
                q["ans"], q["how"] = letters, "资料给出"
                used += 1
    if not used:
        return blocks
    return [b for b in blocks if not (b["k"] in ("p", "h") and (KEY_MARK_RE.match(b.get("t") or "")
                                                               or KEY_LINE_RE.match(b.get("t") or "")))]


REPORT_HEAD_RE = re.compile(r"^\s*一\s*、\s*(?:考试话题|核心命题|核心话题|话题|政策考点|考点)")


def _jd_sections(blocks, title, essays=(), chendu=False):
    """人民日报精读：整理成“原文 → 拆解报告（一、二……）→ 金句 → 仿写范文 → 思维导图”这样的目录，
    去掉页眉广告、报头残字、空白模板页、和书名重复的标题、每页重复的署名；原文里被当成标题的长句改回正文、断开的段落接上。"""
    tnorm = _norm(re.sub(r"[（(][^）)]*[）)]\s*$", "", title or ""))
    by_pg = defaultdict(list)
    for b in blocks:
        by_pg[b.get("pg", 0)].append(b)
    tpl = {p for p, bs in by_pg.items() if any(re.match(r"\s*解读\s*[:：]", b.get("t") or "") for b in bs)
           and all(b["k"] in ("p", "h", "tree") and (b["k"] == "tree" or JD_TEMPLATE_RE.match(b.get("t") or "")) for b in bs)}
    essays = {_norm(e): e for e in essays if len(_norm(e)) >= 4}
    out, sec, byline, body = [], None, False, 0  # body：原文里已经有几段正文

    def head(label, pg):
        nonlocal sec
        if label != sec:
            out.append({"k": "h", "lv": 1, "t": label, "pg": pg})
            sec = label

    for b in blocks:
        pg = b.get("pg", 0)
        if pg in tpl:
            continue  # 每份最后那页没填的“正文 / 每日积累 / 解读：”模板
        if b["k"] == "tree" and sec != "思维导图" and chendu:
            continue  # 晨读讲义没有导图：报纸版面截图、模板页被当成导图认出的乱字
        if b["k"] in ("p", "h", "box"):
            t = JD_AD_RE.sub("", b.get("t") or "").strip()
            t = re.sub(r"\s*[★☆]+\s*", " ", t).strip() if b["k"] == "h" or len(t) < 40 else t
            if not t or JD_LOGO_RE.match(t) or re.fullmatch(r"\W*", t):
                continue
            b = dict(b, t=t)
            if b["k"] == "box" and sec is None and len(t) < 60 and BYLINE_RE.match(t):
                b["k"] = "p"  # 署名行画了框
        if b["k"] in ("p", "h"):
            t = b["t"]
            if sec == "原文" and b["k"] == "p" and NOTE_LABEL_RE.match(t):
                continue
            m = JD_SEC_RE.match(t)
            if m and (len(t) <= 14 or m.group(1) in ("仿写范文", "仿写申论作文")):
                head(re.sub(r"\s+", "", m.group(1)), pg)
                t = m.group(2).strip()
                if not t:
                    continue
                b = dict(b, k="p", t=t)
                b.pop("lv", None)
            if sec in ("仿写范文", "仿写申论作文"):
                # “标题：以优质公共服务 兜底幸福民生公共服务是否优质……”：题目单列成小标题
                tm = re.match(r"^\s*标\s*题\s*[:：]\s*(.*)$", t, re.S)
                if tm:
                    rest = tm.group(1)
                    key = next((k for k in sorted(essays, key=len, reverse=True) if _norm(rest).startswith(k)), None)
                    if key:
                        cut, j = 0, 0
                        while cut < len(rest) and j < len(key):
                            if _norm(rest[cut]):
                                j += 1
                            cut += 1
                        out.append({"k": "h", "lv": 2, "t": essays[key], "pg": pg})
                        t = rest[cut:].strip()
                        if not t:
                            continue
                        b = dict(b, t=t)
            if sec in (None, "原文") and body <= 2:
                # 原文开头：标题（含折行的半截）、署名行
                t2 = _strip_title(t, tnorm)
                n = _norm(t2)
                if not n or (len(n) <= 12 and n in tnorm):
                    continue
                bm = BYLINE_SPLIT_RE.match(t2) if len(t2) < 400 else None
                if bm or (BYLINE_RE.match(t2) and len(t2) < 60):
                    if not byline:
                        out.append({"k": "p", "t": bm.group(1).strip() if bm else t2, "pg": pg})
                    byline = True
                    t2 = bm.group(2).strip() if bm else ""
                    if not t2:
                        continue
                if t2 != t:
                    b = dict(b, k="p", t=t2)
                    b.pop("lv", None)
            elif sec == "原文" and b["k"] == "p":
                # 批注版第 2 页起每页页眉又印一遍标题、署名
                t2 = _strip_title(t, tnorm)
                bm = BYLINE_SPLIT_RE.match(t2) if len(t2) < 2000 else None
                if t2 != t or (bm and re.search(r"作者|来源|人民日报》\s*[（(]", bm.group(1))):
                    t2 = bm.group(2).strip() if bm else t2
                    if not t2:
                        continue
                    b = dict(b, t=t2)
            n = _norm(b["t"])
            if len(n) >= 4 and tnorm and (n == tnorm or (b["k"] == "h" and (n in tnorm or tnorm in n) and abs(len(n) - len(tnorm)) <= 8)):
                continue  # 和书名一样的标题
            if b["k"] == "h" and sec == "原文" and REPORT_HEAD_RE.match(b["t"]):
                head("拆解报告", pg)  # 2026 版“拆解报告”页眉被当成重复标题去掉了，从“一、考试话题”接上
        if sec is None and b["k"] in ("p", "h", "box"):
            head("原文", pg)
        if b["k"] == "h" and sec == "原文":
            if len(b["t"]) > 16 or re.search(r"[，。；：！？,;]", b["t"]):
                b = dict(b, k="p")
                b.pop("lv", None)
            else:
                b = dict(b, lv=2)
        elif b["k"] == "h":  # 板块里自带的小标题：一、 → 2 级，（一） → 3 级
            b = dict(b, lv=3 if re.match(r"\s*[（(][一二三四五六七八九十\d]+[）)]", b["t"]) else 2)
        elif b["k"] == "p" and sec == "拆解报告" and re.match(r"\s*[一二三四五六七八九十]、\S{2,16}$", b["t"]):
            b = dict(b, k="h", lv=2)  # “一、考试话题（核心命题）”加粗没认出来
        prev = out[-1] if out else None
        if b["k"] == "p" and prev is not None and prev["k"] == "p" and sec == "原文" and not SENT_END_RE.search(prev["t"]) \
                and len(prev["t"]) >= 10 and not re.match(r"\s*[" + CIRCLED + r"]", b["t"]) and not BYLINE_SPLIT_RE.match(prev["t"]) \
                and not BYLINE_RE.match(prev["t"]):
            prev["t"] = prev["t"].rstrip() + b["t"].lstrip()  # 跨页、跨行断开的一段
            continue
        if b["k"] == "p" and prev is not None and prev["k"] == "p" and re.fullmatch(r"\s*[—－一-]{1,2}\s*编\s*者\s*", b["t"]):
            prev["t"] = prev["t"].rstrip() + "——编者"
            continue
        if b["k"] == "p" and prev is not None and prev["k"] == "p" and re.match(r"\s*[，。、；：！？”」』）)】]", b["t"]):
            prev["t"] = prev["t"].rstrip() + b["t"].strip()  # 换页时句末标点、后引号落到了下一行
            continue
        if sec == "原文" and b["k"] == "p" and len(b["t"]) <= 60 and any(
                x["k"] == "p" and _norm(x["t"]) == _norm(b["t"]) for x in out[-40:]):
            continue  # 批注版第 2 页的页眉（副标题）又印一遍
        if sec == "原文" and b["k"] in ("p", "box"):
            body += 1
        out.append(b)
    while out and out[-1]["k"] == "h":
        out.pop()  # 板块标题后面什么都没有
    for b in out:
        if b["k"] == "h":
            b["d"] = dict(b.get("d") or {}, lvfix=1)  # 阅读器照这里排好的层级显示（板块 → 一、 → （一））
    return out


def build_unit(root, u, progress=None):
    """一个单元（一份资料，或题目 + 答案两份）→ 块列表。"""
    from . import docs

    blocks, pages, scanned, off, ocr_pages, img_pages = [], 0, 0, 0, set(), set()
    for f in u["parts"]:
        b, n, sc = docs.build_one(root, f, progress)
        for x in b:
            x["pg"] = x.get("pg", 0) + off  # 两份拼在一起时页码接着排
        if sc:
            ocr_pages |= {int(m.group(1)) + off for p in (docs.OCR_DIR / f["id"]).glob("*.json")
                          if (m := re.match(r"(\d+)\.[gzwr]\.json$", p.name))}
        # 页里的图片单独 OCR 过的页（r<页>_<序号>.json）：题本里多半是水印、截图，认出的字也会被当成标题
        img_pages |= {int(m.group(1)) + off for p in (docs.OCR_DIR / f["id"]).glob("r*_*.json")
                      if (m := re.match(r"r(\d+)_\d+\.json$", p.name))}
        blocks += b
        pages += n
        scanned += sc
        off += n
    f0 = u["parts"][0]
    name = f0["name"]
    if u["sec"] == "人民日报精读":
        if not u.get("title"):
            u["title"] = guess_title(root, f0) or u["date"]
        if not re.match(r"人民日报(?:晨读|预习讲义)", name):
            blocks = _jd_layout(root, f0, blocks, u["title"])
        u["_essay"] = _essay_titles(root, f0)
    elif u["sec"] in ("时政题库", "月度时政", "时政专题"):
        u["_keys"] = _answer_keys(root, u["parts"])
    blocks = _drop_pages(blocks, _ad_pages(blocks) | _cover_pages(blocks, pages))
    if u["sec"] == "成语演练":
        blocks = _drop_plain_versions(blocks)
    blocks = _clean_blocks(blocks)
    blocks = _drop_outline_dump(blocks)
    blocks = _rejoin(blocks, demote=u["sec"] == "人民日报精读")
    blocks = _merge_statements(blocks)
    blocks = _split_stems(blocks)
    # 先清一遍标题：批注成标题的“①……√”会把题干和选项隔开，例题识别前就要改回正文
    blocks = _tidy_headings(blocks, u["title"], ocr_pages, img_pages)
    u["_ocr"], u["_img_ocr"] = ocr_pages, img_pages  # 存库时 _tidy_headings 用
    return blocks, pages, scanned


def guess_title(root, f):
    """文件名里没有标题（“人民日报晨读-7月10日”）：取第一页字号最大的一行。"""
    import pymupdf

    d = pymupdf.open(os.path.join(root, f["rel"]))
    try:
        from .pdftext import ORNAMENT_RE
        best, lines = (0, ""), []
        for blk in d[0].get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                spans = [s for s in ln["spans"] if not ORNAMENT_RE.fullmatch(s["text"].strip() or "x")]
                t = "".join(s["text"] for s in spans).strip()
                size = max((s["size"] for s in spans), default=0)
                if t and not re.search(r"人民日报|人民日報|RENMIN|直播|合集|shgk", t):
                    lines.append((ln["bbox"][1], ln["bbox"][3], size, t))
                if len(re.findall(r"[一-鿿]", t)) >= 4 and not re.search(r"人民日报|人民日報|RENMIN|直播|合集", t) \
                        and size > best[0]:
                    best = (size, t)
        if best[1]:
            # 标题折成两行（“让城市发展与文脉传承” / “‘双向奔赴’”）：同字号、紧挨着的下一行接上
            same = sorted((ln for ln in lines if abs(ln[2] - best[0]) < 0.5), key=lambda ln: ln[0])
            i = next((k for k, ln in enumerate(same) if ln[3] == best[1]), None)
            if i is not None:
                text, y1 = same[i][3], same[i][1]
                for ln in same[i + 1:]:
                    if ln[0] - y1 > best[0] * 0.9:
                        break
                    text, y1 = text + ln[3], ln[1]
                best = (best[0], text)
        if not best[1]:
            from . import docs
            boxes = docs._ocr_boxes(f["id"], 0, d[0]) or []
            cands = [(b[3] - b[1], str(b[4])) for b in boxes if len(re.findall(r"[一-鿿]", str(b[4]))) >= 4
                     and not re.search(r"人民日报|人民日報|直播|合集", str(b[4]))]
            best = max(cands, default=(0, ""))
        return re.sub(r"\s*[★☆]+\s*", " ", best[1].translate(RADICALS)).strip()
    finally:
        d.close()


def save_unit(conn, u, blocks, pages, scanned, error=""):
    from . import docs

    f = {"id": u["id"], "name": u["title"], "cat": u["sec"], "subj": ["常识"] if u["sec"] != "人民日报精读" else ["申论"],
         "rel": u["parts"][0]["rel"], "ext": "pdf", "mtime": max(p["mtime"] for p in u["parts"]),
         "size": sum(p["size"] for p in u["parts"])}
    def post(bs):
        bs = _letter_answers(_tidy_headings(bs, u["title"], u.get("_ocr") or set(), u.get("_img_ocr") or set()))
        if u["sec"] == "人民日报精读":
            return _jd_sections(bs, u["title"], u.get("_essay") or (), bool(re.match(r"人民日报(?:晨读|预习讲义)", u["parts"][0]["name"])))
        return _polish_heads(_apply_keys(bs, u.get("_keys")))

    docs.save(conn, f, blocks, pages, scanned, error=error, post=post)
    _attach_answers(conn, u["id"])
    _fill_same_doc(conn, u["id"])
    with _lock, conn:
        conn.execute("INSERT OR REPLACE INTO sz_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (u["id"], u["sec"], u["src"], u["y"], u["m"], u["half"], u.get("date") or "", u["title"],
                      u.get("topic") or "", u.get("kind") or "", json.dumps([p["rel"] for p in u["parts"]], ensure_ascii=False),
                      _sig(u), VERSION, time.strftime("%Y-%m-%d %H:%M:%S")))


# ---------------------------------------------------------------- 成语积累

SENT_RE = re.compile(r"(?:^|\n)\s*(\d{1,2})\s*[、.．]\s*(?=\S)")
WORD_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[）)]\s*([一-鿿，,·]{2,12}?)\s*[:：]\s*")
CY_JUNK_RE = re.compile(r"成语积累\s*逻辑填空|人民日[報报]|PEOPLE'?S\s*DAILY|REN\s*MIN\s*RI\s*BAO|马达成语|马达向前冲|^\s*20\d\d\.\d{1,2}\.\d{1,2}\s*$|^\s*释\s*义\s*$")


def chengyu_lines(root, f):
    """成语积累一天的文字，逐页：两栏版式（左边例句、右边释义）先左栏再右栏，每栏按行从上到下。"""
    import pymupdf

    d = pymupdf.open(os.path.join(root, f["rel"]))
    n = d.page_count
    d.close()
    out = []
    for pno in range(n):
        items = [i for i in _page_items(root, f, pno) if not re.fullmatch(r"[马达成语向前冲\s]+", i[4])]  # 水印碎片
        if not items:
            continue
        W = max(i[2] for i in items)
        left = [i for i in items if i[2] <= W * 0.56]
        right = [i for i in items if i[0] >= W * 0.44 and i not in left]
        two = len(left) >= 4 and len(right) >= 4 and sum(1 for i in items if i[0] < W * 0.4 and i[2] > W * 0.6) <= 2
        cols = [left, [i for i in items if i not in left]] if two else [items]
        for col in cols:
            col = sorted(col, key=lambda i: (i[1] + i[3]) / 2)
            rows = []
            for it in col:
                h = it[3] - it[1]
                if rows and abs((rows[-1][1] + rows[-1][3]) / 2 - (it[1] + it[3]) / 2) < h * 0.45:
                    r = rows[-1]
                    rows[-1] = (min(r[0], it[0]), min(r[1], it[1]), max(r[2], it[2]), max(r[3], it[3]),
                                (r[4] + it[4]) if it[0] >= r[0] else (it[4] + r[4]))
                else:
                    rows.append(it)
            out += [r[4] for r in rows]
    return out


def parse_chengyu(raw_lines):
    """一天的成语积累：编号例句（成语在句中）+ “(n) 成语：释义”。成语和例句靠“例句里出现了这个成语”对上。"""
    lines = []
    for ln in raw_lines:
        ln = _clean_text(ln)
        if ln and not CY_JUNK_RE.search(ln):
            lines.append(ln)
    text = "\n".join(lines)
    # 例句“N、”和释义“(n) 成语：”是两种标记；一段文字归它前面最近的标记（两栏交替出现也能分开）
    marks = [(m.start(), m.end(), "s", m) for m in SENT_RE.finditer(text)]
    marks += [(m.start(), m.end(), "w", m) for m in WORD_RE.finditer(text)]
    marks.sort(key=lambda x: x[0])
    words, sents = [], []
    for i, (_a, z, kind, m) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        seg = re.sub(r"\s*\n\s*", "", text[z:end]).strip()
        if kind == "w":
            if seg:
                words.append({"n": int(m.group(1)), "w": re.sub(r"[，,]", "，", m.group(2)), "m": seg})
        elif len(seg) >= 6:
            sents.append({"n": int(m.group(1)), "t": seg})
    # 去掉编号重复（页眉日期被认成“10.”之类）
    seen, uniq = set(), []
    for s in sents:
        if s["n"] in seen:
            continue
        seen.add(s["n"])
        uniq.append(s)
    sents = uniq
    for s in sents:
        s["w"] = [w["w"] for w in words if w["w"].replace("，", "") in s["t"].replace("，", "").replace(",", "")]
    return {"sents": sents, "words": words}


ANS_ANY_RE = re.compile(r"(?<![\d.．])(\d{1,4})\s*[.．、]\s*【\s*答\s*案\s*】\s*[:：]?\s*([A-H]{1,6})(?![A-Za-z])")
ANS_LINE_RE = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*【\s*答\s*案\s*】\s*[:：]?\s*([A-H]{1,6})\s*[。.．]?\s*(?:【\s*解\s*析\s*】|解\s*析\s*[:：])?\s*(.*)$", re.S)


def _attach_answers(conn, doc_id):
    """讲义最后集中给的“12.【答案】B【解析】……”：按题号挂到前面最近的、还没有答案的同号题上，答案段落不再单独显示。
    （资料库通用的识别只往回找 400 块，月度刷题这种一百多道题的答案对不全。）"""
    rows = conn.execute("SELECT seq, kind, text, data FROM blocks WHERE doc=? ORDER BY seq", (doc_id,)).fetchall()
    qpos = []  # (行号, seq, 题号, 题)
    ans = []   # (行号, 题号, 答案, 解析段落 seq 列表, 解析文字)
    pure = []  # (ans 里的下标, 块 seq)：只有答案的答案表
    i = 0
    while i < len(rows):
        r = rows[i]
        if r["kind"] == "q":
            q = json.loads(r["data"])
            num = str(q.get("num") or "")
            if not num:  # “5.2024年……”：题号后面紧跟数字，通用识别没认出题号
                m = re.match(r"^\s*(\d{1,3})\s*[.．、]", q.get("stem") or "")
                num = m.group(1) if m else ""
            qpos.append((i, r["seq"], num, q))
        elif r["kind"] in ("p", "tbl", "box", "tree") and len(ANS_ANY_RE.findall(r["text"] or "")) >= (2 if r["kind"] == "p" else 1):
            # “1.【答案】A。 2.【答案】ACD。……”被认成表格 / 文本框 / 导图，或几道题的答案挤在一段里：
            # 逐个拆出来挂到题上；块里还夹着正文的（导图后半截是下一节新闻）保留，纯答案表全挂上后去掉
            t = r["text"] or ""
            hits = list(ANS_ANY_RE.finditer(t))
            group = []
            for k, m in enumerate(hits):
                body = t[m.end():hits[k + 1].start() if k + 1 < len(hits) else len(t)]
                body = re.split(r"\s[一二三四五六七八九十]+、|【知识(?:拓展|链接)】|【相关时政】", body)[0].strip(" 。.．\n")
                group.append(len(ans))
                # 导图块里答案后面接的多是下一节的正文，不当解析
                ans.append((i, m.group(1), m.group(2), [], [body[:600]] if len(body) > 4 and r["kind"] != "tree" else []))
            rest = ANS_ANY_RE.sub("", t)
            if len(re.findall(r"[一-鿿]", rest)) < 8:
                pure.append((group, r["seq"]))
        elif r["kind"] == "p":
            m = ANS_LINE_RE.match(r["text"] or "")
            if m:
                seqs, body = [r["seq"]], [m.group(3).strip()] if m.group(3).strip() else []
                j = i + 1
                while j < len(rows) and rows[j]["kind"] == "p" and not ANS_LINE_RE.match(rows[j]["text"] or "") \
                        and not re.match(r"^\s*[一二三四五六七八九十]+、", rows[j]["text"] or "") and len(body) < 8:
                    seqs.append(rows[j]["seq"])
                    body.append(rows[j]["text"])
                    j += 1
                ans.append((i, m.group(1), m.group(2), seqs, body))
                i = j
                continue
        i += 1
    if not ans:
        return
    upd, used, done = [], [], set()
    for n, (pos, num, letters, seqs, body) in enumerate(ans):
        for qi, qseq, qn, q in reversed(qpos):
            if qi >= pos or qn != num:
                continue
            near = not seqs and pos - qi <= 12
            if q.get("ans") and q.get("how") != "软件计算":
                if not near:
                    continue
                if q["ans"] == letters:  # 紧跟在题后的答案表：和已有答案一致
                    done.add(n)
                    break
                # 不一致时以紧跟在题后的答案表为准（通用识别会把别处同号的答案挂错）
            if not set(letters) <= {a for a, _o in q.get("opts") or []} or (not seqs and pos - qi > 120):
                break  # 表格里拆出来的答案只挂到附近的题上
            q.update(ans=letters, how="资料给出", exp=[{"t": t} for t in body if t.strip()])
            upd.append((json.dumps(q, ensure_ascii=False), doc_id, qseq))
            used += seqs
            done.add(n)
            break
    used += [s for group, s in pure if group and all(n in done for n in group)]
    with _lock, conn:
        conn.executemany("UPDATE blocks SET data=? WHERE doc=? AND seq=?", upd)
        for s in used:
            conn.execute("DELETE FROM blocks WHERE doc=? AND seq=?", (doc_id, s))
            try:
                conn.execute("DELETE FROM blocks_fts WHERE doc=? AND seq=?", (doc_id, s))
            except sqlite3.OperationalError:
                pass


def _fill_same_doc(conn, doc_id):
    """同一份讲义里一道题出现两次（课上讲一遍、后面金卷再考一遍，答案只附在金卷后）：没答案的那份借有答案的。"""
    from . import docq

    rows = conn.execute("SELECT seq, data FROM blocks WHERE doc=? AND kind='q'", (doc_id,)).fetchall()
    qs = [(r["seq"], json.loads(r["data"])) for r in rows]
    have = {}
    for _s, q in qs:
        if q.get("ans") and q.get("how") != "软件计算":
            have.setdefault(docq._key(q["stem"])[:40], q)
    upd = []
    for s, q in qs:
        if q.get("ans"):
            continue
        k = docq._key(q["stem"])[:40]
        o = have.get(k)
        if len(k) >= 12 and o and [a for a, _ in o["opts"]] == [a for a, _ in q["opts"]] \
                and docq._same_opts(q["opts"], [x for _a, x in o["opts"]]):
            q.update(ans=o["ans"], how=o.get("how") or "资料给出", exp=o.get("exp") or [])
            upd.append((json.dumps(q, ensure_ascii=False), doc_id, s))
    if upd:
        with _lock, conn:
            conn.executemany("UPDATE blocks SET data=? WHERE doc=? AND seq=?", upd)


def _sig(u):
    return "|".join(f"{p['rel']}:{p['size']}:{p['mtime']}" for p in u["parts"])


# ---------------------------------------------------------------- 整理全部

def build(root, progress=None):
    """整理全部时政、晨读资料：没变化的跳过；先做有文字层的（快），再做要 OCR 的扫描件。"""
    def prog(i, n, msg):
        if progress:
            progress(i, n, msg)

    files = scan(root, lambda i, n, name: prog(i, n, f"扫描：{name}"))
    units, _skipped = plan(files)
    conn = connect()
    have = {r["id"]: (r["sig"], r["version"]) for r in conn.execute("SELECT id, sig, version FROM sz_meta")}
    cy_have = {r["date"]: (r["sig"], r["version"]) for r in conn.execute("SELECT date, sig, version FROM cy_days")}
    docs_u = [u for u in units if u["sec"] in SECTIONS]
    cy_u = [u for u in units if u["sec"] == "成语"]
    # 已经不在资料里的（文件删了、改成不收）从库里去掉
    keep = {u["id"] for u in docs_u}
    with _lock, conn:
        for fid in set(have) - keep:
            for t in ("sz_meta WHERE id", "docs WHERE id", "blocks WHERE doc", "blocks_fts WHERE doc"):
                try:
                    conn.execute(f"DELETE FROM {t}=?", (fid,))
                except sqlite3.OperationalError:
                    pass
        for d in set(cy_have) - {u["date"] for u in cy_u}:
            conn.execute("DELETE FROM cy_days WHERE date=?", (d,))
    todo = [u for u in docs_u if have.get(u["id"]) != (_sig(u), VERSION)]
    # 内容没变的：分类、标题规则可能改过，直接更新（不用重新识别）
    with _lock, conn:
        for u in docs_u:
            if u in todo or u["id"] not in have:
                continue
            title = u["title"] or (conn.execute("SELECT title FROM sz_meta WHERE id=?", (u["id"],)).fetchone() or [""])[0]
            conn.execute("UPDATE sz_meta SET sec=?, src=?, y=?, m=?, half=?, date=?, title=?, topic=?, kind=? WHERE id=?",
                         (u["sec"], u["src"], u["y"], u["m"], u["half"], u.get("date") or "", title, u.get("topic") or "",
                          u.get("kind") or "", u["id"]))
            conn.execute("UPDATE docs SET title=?, cat=? WHERE id=?", (title, u["sec"], u["id"]))
    todo_cy = [u for u in cy_u if cy_have.get(u["date"]) != (_sig(u), VERSION)]
    scan_pages = lambda u: sum(p["pages"] for p in u["parts"] if not p.get("text"))  # noqa: E731
    jobs = [("cy", u) for u in todo_cy] + [("doc", u) for u in todo]
    jobs.sort(key=lambda j: (scan_pages(j[1]) > 0, j[0] == "doc", scan_pages(j[1]), j[1].get("date") or ""))
    total = sum(max(1, sum(p["pages"] for p in u["parts"])) for _k, u in jobs) or 1
    done = 0
    for kind, u in jobs:
        n = max(1, sum(p["pages"] for p in u["parts"]))
        label = (u["title"] or u.get("date") or "") if kind == "doc" else f"成语积累 {u['date']}"
        prog(done, total, label)
        try:
            if kind == "cy":
                r = parse_chengyu(chengyu_lines(root, u["parts"][0]))
                old = conn.execute("SELECT id, words FROM cy_days WHERE date=?", (u["date"],)).fetchone()
                # 同一天有两份文件时留词条多的那份
                if not (old and old["id"] != u["id"] and len(json.loads(old["words"] or "[]")) > len(r["words"])):
                    with _lock, conn:
                        conn.execute("INSERT OR REPLACE INTO cy_days VALUES (?,?,?,?,?,?,?)",
                                     (u["date"], u["id"], u["parts"][0]["rel"], json.dumps(r["sents"], ensure_ascii=False),
                                      json.dumps(r["words"], ensure_ascii=False), _sig(u), VERSION))
            else:
                def p2(i, nn, done=done, label=label):
                    prog(done + i, total, f"{label}（{i + 1}/{nn} 页）")
                blocks, pages, scanned = build_unit(root, u, p2)
                save_unit(conn, u, blocks, pages, scanned)
        except Exception as e:  # noqa: BLE001 —— 个别文件坏了不影响其他
            import logging
            logging.getLogger("gongkao.shizheng").exception("整理失败：%s", u.get("rel") or u.get("id"))
            if kind == "doc":
                save_unit(conn, u, [], 0, 0, error=str(e)[:200])
        done += n
    from . import docs
    prog(total, total, "查重、补答案")
    docs.find_duplicates(conn)
    docs.fill_from_docs(conn)
    fill_answers(conn)
    conn.close()


# ---------------------------------------------------------------- 读取（界面用）

def overview():
    """时政晨读首页：各块的资料列表（不含正文）、成语积累的日历。"""
    if not DB_PATH.exists():
        return {"items": [], "days": [], "built": False}
    conn = connect()
    hidden = {r[0] for r in conn.execute("SELECT doc FROM doc_dups")}
    nq = dict(conn.execute("SELECT doc, COUNT(*) FROM blocks WHERE kind='q' GROUP BY doc").fetchall())
    items = []
    for r in conn.execute("SELECT m.*, d.chars, d.pages, d.error, d.toc FROM sz_meta m JOIN docs d ON d.id = m.id"):
        if r["id"] in hidden or not r["chars"]:
            continue
        it = {k: r[k] for k in ("id", "sec", "src", "y", "m", "half", "date", "title", "topic", "kind", "chars", "pages")}
        it["nq"] = nq.get(r["id"], 0)
        it["toc_n"] = len(json.loads(r["toc"] or "[]"))
        items.append(it)
    days = [{"date": r["date"], "n": len(json.loads(r["words"] or "[]")), "s": len(json.loads(r["sents"] or "[]"))}
            for r in conn.execute("SELECT date, words, sents FROM cy_days ORDER BY date")]
    conn.close()
    return {"items": items, "days": days, "built": True}


def chengyu(month=None, dates=None):
    """成语积累：某个月（“2026-09”）或指定几天的例句和释义。"""
    if not DB_PATH.exists():
        return {"days": []}
    conn = connect()
    if dates:
        rows = conn.execute(f"SELECT * FROM cy_days WHERE date IN ({','.join('?' * len(dates))}) ORDER BY date", dates).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cy_days WHERE date LIKE ? ORDER BY date", ((month or "") + "%",)).fetchall()
    conn.close()
    return {"days": [{"date": r["date"], "sents": json.loads(r["sents"]), "words": json.loads(r["words"])} for r in rows]}


def chengyu_all():
    """全部成语去重：出现过几天、释义和一个例句（成语总表、随机抽背用）。"""
    if not DB_PATH.exists():
        return {"words": []}
    conn = connect()
    out = {}
    for r in conn.execute("SELECT date, sents, words FROM cy_days ORDER BY date DESC"):
        sents = json.loads(r["sents"])
        for w in json.loads(r["words"]):
            k = w["w"]
            if k not in out:
                ex = next((s["t"] for s in sents if k in s.get("w", [])), "")
                out[k] = {"w": k, "m": w["m"], "ex": ex, "dates": [r["date"]]}
            else:
                out[k]["dates"].append(r["date"])
    conn.close()
    return {"words": sorted(out.values(), key=lambda e: (-len(e["dates"]), e["w"]))}


def chengyu_deck():
    """成语积累做成一个闪卡卡组（正面成语，背面释义 + 人民日报例句）。卡片 id 按成语生成，重新整理后复习记录不丢。"""
    import hashlib

    words = chengyu_all()["words"]
    cards = [{"id": "cy-" + hashlib.md5(w["w"].encode("utf-8")).hexdigest()[:10], "front": w["w"],
              "back": w["m"] + (f"\n例：{w['ex']}" if w.get("ex") else "")} for w in words]
    return {"id": "news-chengyu", "name": "人民日报成语积累", "cards": cards,
            "desc": "时政晨读里每日成语积累的全部词条（去重），背面是释义和人民日报原句"} if cards else None


def doc_get(doc_id):
    """阅读器取一份时政资料（格式和资料库 docs.doc_get 一样，多一个返回时政页的链接）。"""
    if not DB_PATH.exists():
        return None
    conn = connect()
    d = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not d:
        conn.close()
        return None
    d = dict(d)
    m = conn.execute("SELECT * FROM sz_meta WHERE id=?", (doc_id,)).fetchone()
    d["toc"] = json.loads(d["toc"] or "[]")
    d["subj"] = [s for s in (d["subj"] or "").split(",") if s]
    d["blocks"] = [[r["seq"], r["kind"], r["level"], r["text"], r["page"], json.loads(r["data"]) if r["data"] else None]
                   for r in conn.execute("SELECT * FROM blocks WHERE doc=? ORDER BY seq", (doc_id,))]
    d["sz"] = {k: m[k] for k in m.keys() if k not in ("parts", "sig")} if m else None
    d["back"] = {"href": "#/news", "label": "时政晨读"}
    conn.close()
    return d


def quiz(n=20, since="", src=""):
    """随机抽时政题（有答案的）：since 是“2026-04”这种月份，只抽这个月及以后的讲义里的题。"""
    import random

    if not DB_PATH.exists():
        return {"items": [], "total": 0}
    conn = connect()
    hidden = {r[0] for r in conn.execute("SELECT doc FROM doc_dups")}
    sql = ("SELECT b.doc, b.seq, b.data, m.title, m.sec, m.y, m.m, m.src FROM blocks b JOIN sz_meta m ON m.id = b.doc "
           "WHERE b.kind='q' AND m.sec IN ('月度时政', '时政专题', '时政题库')")
    args = []
    if since:
        sql += " AND (m.y * 100 + m.m) >= ?"
        args.append(int(since[:4]) * 100 + int(since[5:7]))
    if src:
        sql += " AND m.src=?"
        args.append(src)
    pool = []
    seen = set()
    for r in conn.execute(sql, args):
        if r["doc"] in hidden:
            continue
        q = json.loads(r["data"])
        if not q.get("ans") or q.get("how") == "软件计算":
            continue
        key = re.sub(r"\W", "", q.get("stem") or "")[:40]
        if key in seen:
            continue
        seen.add(key)
        pool.append((r, q))
    conn.close()
    pick = random.sample(pool, min(n, len(pool)))
    return {"total": len(pool), "items": [{
        "doc": r["doc"], "seq": r["seq"], "title": r["title"], "ym": f"{r['y']}-{r['m']:02d}" if r["y"] and r["m"] else "",
        "stem": q["stem"], "opts": q["opts"], "ans": q["ans"], "exp": [e.get("t", "") for e in q.get("exp") or []]}
        for r, q in pick]}


def titles():
    if not DB_PATH.exists():
        return {}
    conn = connect()
    out = {r[0]: r[1] for r in conn.execute("SELECT id, title FROM sz_meta")}
    conn.close()
    return out


def search(q, doc=None, limit=200):
    """全文搜索（时政资料 + 成语积累）。"""
    terms = [t for t in (q or "").split() if t]
    if not terms or not DB_PATH.exists():
        return []
    conn = connect()
    longest = max(terms, key=len)
    like = ("SELECT doc, seq, text FROM blocks WHERE text LIKE ?" + (" AND doc=?" if doc else ""), [f"%{longest}%"] + ([doc] if doc else []))
    rows = []
    if len(longest) >= 3:
        try:
            rows = conn.execute("SELECT doc, seq, text FROM blocks_fts WHERE blocks_fts MATCH ?" + (" AND doc=?" if doc else "") + " LIMIT 3000",
                                ['"' + longest.replace('"', '""') + '"'] + ([doc] if doc else [])).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(like[0] + " LIMIT 3000", like[1]).fetchall()
    else:
        rows = conn.execute(like[0] + " LIMIT 3000", like[1]).fetchall()
    hidden = {r[0] for r in conn.execute("SELECT doc FROM doc_dups")}
    hits = []
    for r in rows:
        text = r["text"] or ""
        if (r["doc"] in hidden and not doc) or not all(t in text for t in terms):
            continue
        pos = text.find(terms[0])
        a = max(0, pos - 50)
        hits.append({"doc": r["doc"], "seq": r["seq"], "snippet": ("…" if a else "") + text[a: pos + 90]})
        if len(hits) >= limit:
            break
    if not doc:
        for r in conn.execute("SELECT date, words FROM cy_days ORDER BY date DESC"):
            for w in json.loads(r["words"]):
                if all(t in w["w"] + w["m"] for t in terms):
                    hits.append({"cy": r["date"], "w": w["w"], "snippet": f"{w['w']}：{w['m'][:80]}"})
    conn.close()
    return hits
