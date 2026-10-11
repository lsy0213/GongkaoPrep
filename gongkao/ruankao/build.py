"""软考资料整理的各个步骤（后台任务里跑）：扫描目录 → 题库（综合知识）→ 案例 → 论文 → 资料库文档 → 视频。

来源和优先级：
- 2009–2018 真题：资料文件夹里的文字版试卷 + 答案详解（有原卷截图）；
- 2020 年至今的真题（多为回忆版）和 2026 年模拟卷：开源题库（library/github/，先“下载开源题库”）；
- 资料文件夹里的模拟题（希赛模拟卷）：见 mocks.py。
同一道题出现在几处时，保留有原卷截图的那份，其次是解析最长的。
"""

import json
import logging
import os
import re
import time

from .. import qdb
from . import catalog, lib_dir, mdimport, papers, topics
from .pdflines import norm

log = logging.getLogger("gongkao.ruankao")


def bank_path():
    return lib_dir() / "questions.db"


def _save_json(name, data):
    p = lib_dir() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def load_json(name, default=None):
    try:
        return json.loads((lib_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def _hcode(half):
    return "a" if half == "上半年" else "b"


def _label(year, half):
    return f"{year}年{half}" if half else f"{year}年"


def _classify(q):
    mod, tid = topics.classify_text(q.get("stem"), q.get("options"), q.get("explain"), q.get("num") or 0)
    q["module"], q["sub"] = mod, topics.topic_name(tid)
    return q


# ---------------------------------------------------------------- 题库

def _local_papers(cat, job=None):
    """资料文件夹里 2009–2018 的文字版真题：→ (sources, questions, materials, cases, essays)。"""
    root = cat.get("root") or ""
    by_year = {}
    for f in cat.get("files", []):
        if f.get("cat") == "真题" and f.get("year") and f.get("part") in ("zh", "ans", "al", "lw"):
            by_year.setdefault((f["year"], f.get("half") or "下半年"), {})[f["part"]] = f
    sources, qs, mats, cases, essays = [], [], [], [], []
    keys = sorted(by_year)
    for i, (year, half) in enumerate(keys):
        parts = by_year[(year, half)]
        if job:
            job.progress("解析真题", i, len(keys), _label(year, half))
        if "zh" not in parts or "ans" not in parts:
            continue
        try:
            path = lambda part: os.path.join(root, parts[part]["rel"])  # noqa: E731
            groups = papers.parse_paper(path("zh"))
            groups, pm, ans_text = papers.attach_answers(groups, path("ans"))
        except Exception as e:  # noqa: BLE001 —— 个别文件坏了跳过，别的年份照常
            log.warning("真题解析失败 %s：%s", _label(year, half), e)
            continue
        sid = f"rk-{year}{_hcode(half)}"
        title = f"{_label(year, half)} 系统架构设计师 综合知识"
        q, m = papers.to_bank(groups, sid, parts["zh"]["id"], year, half, title)
        qs += [_classify(x) for x in q]
        mats += m
        sources.append({"id": sid, "title": title, "exam": "软考", "year": year, "level": half, "module": "综合知识",
                        "file": parts["zh"]["rel"], "fid": parts["zh"]["id"], "answer_file": parts["ans"]["rel"],
                        "answer_fid": parts["ans"]["id"], "count": len(q),
                        "answered": sum(1 for x in q if x["answer"] is not None), "note": "资料文件夹 · 文字版试卷 + 答案详解"})
        if "al" in parts:
            try:
                for c in papers.attach_case_answers(papers.parse_case_paper(path("al")), ans_text, pm):
                    cases.append({**c, "id": f"{sid}-c{c['no']}", "year": year, "half": half, "kind": "paper",
                                  "source": f"{_label(year, half)}真题", "fid": parts["al"]["id"], "required": c["no"] == 1})
            except Exception as e:  # noqa: BLE001
                log.warning("案例解析失败 %s：%s", _label(year, half), e)
        if "lw" in parts:
            try:
                for e in papers.attach_essay_guides(papers.parse_essay_paper(path("lw")), ans_text, pm):
                    essays.append({**e, "id": f"{sid}-e{e['no']}", "year": year, "half": half, "kind": "paper",
                                   "source": f"{_label(year, half)}真题", "fid": parts["lw"]["id"]})
            except Exception as e:  # noqa: BLE001
                log.warning("论文解析失败 %s：%s", _label(year, half), e)
    return sources, qs, mats, cases, essays


def _gh_items(data, kind):
    """开源题库的真题 / 模拟卷 → (sources, questions, cases, essays)。"""
    sources, qs, cases, essays = [], [], [], []
    for k, it in enumerate(data):
        year, half = it["year"], it["half"]
        if kind == "paper":
            sid = f"rkg-{year}{_hcode(half)}"
            title = f"{_label(year, half)} 系统架构设计师 综合知识（回忆版）"
            src_label, src = f"{_label(year, half)}真题", "真题"
        else:
            m = re.search(r"(\d+)\s*月.*?模拟卷\s*(\d+)", it["label"])
            tag = f"{year}{int(m.group(1)):02d}-{m.group(2)}" if m else f"{year}-{k}"
            sid = f"rkm-{tag}"
            title = f"开源模拟卷 · {it['label']}"
            src_label, src = f"模拟卷 {it['label']}", "模拟"
        q = []
        for x in it["choice"]:
            q.append(_classify({"id": f"{sid}-{x['num']:02d}", "source": sid, "num": x["num"], "stem": x["stem"],
                                "options": x["options"], "answer": x["answer"], "explain": x["explain"],
                                "material": None, "crop": [], "fig": 0, "year": year, "src": src, "origin": title, "fid": ""}))
        if q:
            qs += q
            sources.append({"id": sid, "title": title, "exam": "软考", "year": year, "level": half, "module": "综合知识",
                            "file": it["dir"], "count": len(q), "answered": sum(1 for x in q if x["answer"] is not None),
                            "note": mdimport.SOURCE_NOTE})
        for c in it["cases"]:
            cases.append({**c, "id": f"{sid}-c{c['no']}-{len(cases)}", "year": year, "half": half, "kind": kind,
                          "source": src_label, "fid": "", "required": c["no"] == 1, "license": mdimport.SOURCE_NOTE})
        for e in it["essays"]:
            essays.append({**e, "id": f"{sid}-e{e['no']}", "year": year, "half": half, "kind": kind,
                           "source": src_label, "fid": "", "license": mdimport.SOURCE_NOTE})
    return sources, qs, cases, essays


def _dedupe_questions(qs):
    """同一道题（题干 + 选项一样）只留一份：有原卷截图的优先，其次解析长的。"""
    best = {}
    for q in qs:
        k = norm(q["stem"])[:60] + "|" + "|".join(norm(o)[:20] for o in (q.get("options") or []))
        cur = best.get(k)
        score = (1 if q.get("fid") else 0, len(q.get("explain") or ""))
        if cur is None or score > cur[0]:
            best[k] = (score, q)
    keep = {id(v[1]) for v in best.values()}
    return [q for q in qs if id(q) in keep]


def _dedupe_texts(items, key):
    seen, out = set(), []
    for it in items:
        k = norm(key(it))[:80]
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def build_bank(job=None):
    """题库 + 案例 + 论文。"""
    cat = catalog.load()
    sources, qs, mats, cases, essays = _local_papers(cat, job)
    if job:
        job.progress("读开源题库", 0, 1)
    gh = mdimport.collect() if mdimport.available() else {"papers": [], "mocks": []}
    s2, q2, c2, e2 = _gh_items(gh["papers"], "paper")
    s3, q3, c3, e3 = _gh_items(gh["mocks"], "mock")
    from . import mocks

    s4, q4, m4, c4, e4 = mocks.collect(cat, job)
    paper_qs = _dedupe_questions(qs + q2)
    mock_qs = _dedupe_questions(q3 + q4)
    seen_paper = {norm(q["stem"])[:60] for q in paper_qs}
    mock_qs = [q for q in mock_qs if norm(q["stem"])[:60] not in seen_paper]  # 模拟卷里收的真题原题，以真题为准
    for group, qlist in ((sources + s2, paper_qs), (s3 + s4, mock_qs)):
        for s in group:
            mine = [q for q in qlist if q["source"] == s["id"]]
            s["count"] = len(mine)
            s["answered"] = sum(1 for q in mine if q["answer"] is not None)
            s["modules"] = {}
            for q in mine:
                s["modules"][q["module"]] = s["modules"].get(q["module"], 0) + 1
    if job:
        job.progress("写题库", 0, 1, f"真题 {len(paper_qs)} 题，模拟题 {len(mock_qs)} 题")
    path = bank_path()
    qdb.replace_kind("paper", [s for s in sources + s2 if s["count"]], paper_qs, mats, path=path)
    used = {q.get("material") for q in mock_qs}
    qdb.replace_kind("mock", [s for s in s3 + s4 if s["count"]], mock_qs, [m for m in m4 if m["id"] in used], path=path)
    all_cases = _dedupe_texts(cases + c2 + c3 + c4, lambda c: c["material"][:120] + (c["questions"][0]["text"] if c["questions"] else ""))
    all_essays = _dedupe_texts(essays + e2 + e3 + e4, lambda e: e["title"] + e.get("background", "")[:40])
    _save_json("cases.json", {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "sets": all_cases})
    _save_json("essays.json", {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "topics": all_essays})
    return {"paper": len(paper_qs), "mock": len(mock_qs), "cases": len(all_cases), "essays": len(all_essays)}


# ---------------------------------------------------------------- 资料库文档

DOC_CATS = ("教材", "讲义", "知识点", "论文范文", "论文指导", "案例", "思维导图", "参考书", "报名机考")


TITLE_NOISE_RE = re.compile(r"【[^】]*】|[（(][^）)]*[）)]|^\s*[\d_、.\s]+|可搜索|带搜索|搜索版?|官方|彩色|高清|完整版|书签|版本|最新|[\s+＋_\-—·.]")


BOOK_FAMILIES = [(r"32\s*小时", "32小时通关"), (r"范文\s*50\s*篇", "论文范文50篇"), (r"学习笔记", "系统架构师学习笔记"),
                 (r"教程.{0,4}第\s*4\s*版.*重点|划了重点", "教程第4版划重点")]


def _title_key(name):
    """同一本书的不同拷贝（“【带搜索】系统架构设计师第二版”“系统架构设计师教程第二版可搜索”）归成一个键。"""
    for rx, key in BOOK_FAMILIES:
        if re.search(rx, name):
            return key
    t = TITLE_NOISE_RE.sub("", re.sub(r"\.\w+$", "", name))
    t = t.replace("系统架构师", "系统架构设计师").replace("教程第", "第").replace("考试", "")
    return t


def doc_files(cat):
    """要整理成文档的资料：同一份资料只收一份——优先有文字层的、目录书签多的、页数多的。"""
    from .. import docs

    best = {}
    for f in cat.get("files", []):
        if f.get("cat") not in DOC_CATS or f.get("ext") not in docs.EXTS or f.get("error"):
            continue
        key = _title_key(f["name"]) or f["rel"]
        rank = (0 if f.get("text", True) else 1, -(f.get("toc") or 0), -(f.get("pages") or 0), len(f["rel"]))
        if key not in best or rank < best[key][0]:
            best[key] = (rank, f)
    return [v[1] for v in best.values()]


def docs_path():
    return lib_dir() / "docs.db"


# 软考资料每份开头都夹着的一页平台广告（“软考资料免费获取 / 1、最新软考题库 / 微信扫一扫，立马获取”）：
# 一行一块，OCR 常把“软考达人”认成“欧身达人”之类
AD_BLOCK_RE = re.compile(
    r"【?[一-鿿]{0,2}[达逃]人】?|软考资料免费获取|\d[、.]\s*(?:最新软考题库|软考备考资料|考前压轴题)|"
    r"微信扫一扫[，,]?|扫一扫|立马获取|6[Ww万]\+?免费题库|免费备考资料")
AD_PREFIX_RE = re.compile(r"^(?:免费备考资料|立马获取)\s*")


def drop_ad_blocks(blocks):
    """去掉广告页：同一页上有 3 块以上整块都是广告词的，这些块不要（同一页的书签标题、正文照留）。"""
    hits = {}
    for b in blocks:
        if b.get("k") in ("p", "h") and AD_BLOCK_RE.fullmatch(re.sub(r"\s+", "", b.get("t") or "")):
            hits[b.get("pg")] = hits.get(b.get("pg"), 0) + 1
    pages = {pg for pg, n in hits.items() if n >= 3}
    out = []
    for b in blocks:
        if b.get("pg") in pages and b.get("k") in ("p", "h"):
            t = re.sub(r"\s+", "", b.get("t") or "")
            if AD_BLOCK_RE.fullmatch(t):
                continue
            if AD_PREFIX_RE.match(b.get("t") or ""):
                b = {**b, "t": AD_PREFIX_RE.sub("", b["t"])}
        out.append(b)
    return out


def build_docs(job=None):
    """讲义、教材、笔记、范文 → docs.db（和公考资料库同一套：文字层 / OCR、书签目录、例题可作答）。先做文字版，扫描版最后。"""
    from .. import docs, ocr

    cat = catalog.load()
    root = cat.get("root") or ""
    sel = doc_files(cat)
    conn = docs.connect(docs_path())
    try:
        have = {r["id"]: (r["mtime"], r["size"], r["version"], r["error"]) for r in conn.execute("SELECT * FROM docs")}
        keep = {f["id"] for f in sel}
        with conn:
            for fid in set(have) - keep:
                conn.execute("DELETE FROM docs WHERE id=?", (fid,))
                conn.execute("DELETE FROM blocks WHERE doc=?", (fid,))
                if docs.has_fts(conn):
                    conn.execute("DELETE FROM blocks_fts WHERE doc=?", (fid,))
        todo = [f for f in sel if have.get(f["id"], (None,) * 4)[:3] != (f["mtime"], f["size"], docs.VERSION)
                or (have[f["id"]][3] and ocr.available())]
        todo.sort(key=lambda f: (f["ext"] in ("jpg", "jpeg", "png") or (f["ext"] == "pdf" and not f.get("text")), f.get("pages") or 0))
        total = sum(max(1, f.get("pages") or 1) for f in todo) or 1
        done = 0
        for f in todo:
            f = {**f, "subj": []}
            name = f["name"]

            def prog(i, n, done=done, name=name):
                if job:
                    job.progress("整理软考资料库", done + i, total, f"{name}（{i + 1}/{n} 页）")

            if job:
                job.progress("整理软考资料库", done, total, name)
            try:
                blocks, pages, scanned = docs.build_one(root, f, prog)
                blocks = drop_ad_blocks(blocks)
                docs.save(conn, f, blocks, pages, scanned)
            except Exception as e:  # noqa: BLE001 —— 个别文件坏了不影响其他
                if type(e).__name__ == "Cancelled":
                    raise
                docs.save(conn, f, [], 0, False, error=str(e)[:200])
            done += max(1, f.get("pages") or 1)
        docs.find_duplicates(conn)
    finally:
        conn.close()
    return len(todo)


# ---------------------------------------------------------------- 视频课

# 视频文件名里的章节关键词 → 教程课程 id（和 topics.py 的课程一样）
VIDEO_COURSE = [
    (r"计算机硬件|计算机组成|硬件|性能评价|系统配置", "rk-hw"), (r"操作系统", "rk-hw"), (r"嵌入式", "rk-hw"), (r"网络", "rk-hw"),
    (r"数据库", "rk-db"), (r"信息系统", "rk-db"), (r"软件工程|面向对象|UML|设计模式|需求|测试", "rk-se"),
    (r"架构设计|体系结构|架构评估|质量属性|架构风格|演化|可靠性", "rk-arch"), (r"云原生|微服务|大数据|未来信息|新技术|SOA", "rk-new"),
    (r"安全", "rk-sec"), (r"项目管理|数学|经济", "rk-pm"), (r"知识产权|标准化|英语", "rk-law"),
    (r"案例", "rk-case"), (r"论文", "rk-paper"),
]


def build_videos(job=None):
    """资料文件夹里的视频 → videos.json：按文件夹分组，按文件名里的数字排顺序，猜它讲的是哪门课。"""
    cat = catalog.load()
    vids = [f for f in cat.get("files", []) if f.get("cat") == "视频"]
    groups = {}
    for f in vids:
        folder = os.path.dirname(f["rel"])
        course = next((cid for rx, cid in VIDEO_COURSE if re.search(rx, f["name"])), "")
        m = re.match(r"^\D*?(\d{1,3})", f["name"])
        groups.setdefault(folder, []).append({"id": f["id"], "name": re.sub(r"\.\w+$", "", f["name"]), "size": f["size"],
                                              "order": int(m.group(1)) if m else 999, "course": course})
    out = []
    for folder, items in sorted(groups.items()):
        items.sort(key=lambda x: (x["order"], x["name"]))
        title = re.sub(r"^[\d、.\s]+", "", os.path.basename(folder)) or os.path.basename(folder)
        out.append({"folder": folder, "title": title, "items": items})
    _save_json("videos.json", {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "groups": out})
    return len(vids)


def build_all(job=None, download=False):
    """一键整理：扫描目录 →（下载开源题库）→ 题库、案例、论文 → 视频 → 资料库文档（扫描件 OCR 最慢，放最后）。"""
    from ..userdb import db

    with db(exam="ruankao-arch") as conn:
        from ..userdb import get_settings

        root = get_settings(conn).get("library_root") or ""
    if root and os.path.isdir(root):
        catalog.scan(root, job)
    if download or not mdimport.available():
        try:
            mdimport.download(job)
        except OSError as e:
            log.warning("下载开源题库失败：%s", e)
    build_bank(job)
    build_videos(job)
    build_docs(job)
