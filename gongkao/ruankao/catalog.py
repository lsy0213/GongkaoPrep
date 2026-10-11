"""软考资料目录：扫描资料文件夹，按 真题 / 模拟题 / 教材 / 讲义 / 知识点 / 论文 / 案例 / 视频 / 报名与机考 分类。

目录文件和公考的 library/catalog.json 同一个格式（root + files），原卷截图（/api/crop）、原文件按它找文件。
文件 id 加了 rk 前缀，和公考资料的 id 不会撞（OCR 缓存、插图按 id 存在同一个地方）。
"""

import hashlib
import json
import os
import re
import time

from . import lib_dir

VIDEO_EXT = {"mp4", "ts", "flv", "mkv", "avi", "mov", "m4v", "wmv"}
DOC_EXT = {"pdf", "docx", "doc", "txt", "jpg", "jpeg", "png"}
SKIP_RE = re.compile(r"\.qkdownloading$|限时福利|网盘|领取|\.zip$|\.rar$|\.7z$", re.I)


def fid_of(rel):
    return "rk" + hashlib.md5(rel.replace("/", "\\").encode("utf-8")).hexdigest()[:10]


def catalog_path():
    return lib_dir() / "catalog.json"


def load():
    try:
        return json.loads(catalog_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"root": "", "files": [], "scanned_at": ""}


def _year_half(t):
    """年份和上 / 下半年：“2012年下半年”“2022.11”“2019年11月”“2024上”……"""
    name = os.path.basename(t)
    m = re.search(r"(20[012]\d)\s*年?\s*[.．]?\s*(上半年|下半年|上|下|11月?|5月?|05|\.11|11)?", name) or \
        re.search(r"(20[012]\d)\s*年?\s*(上半年|下半年)?", t)
    if not m:
        return 0, ""
    year = int(m.group(1))
    h = m.group(2) or ""
    if re.search(r"上", h) or h.startswith("5") or h == "05":
        half = "上半年"
    elif h:
        half = "下半年"
    else:
        half = "下半年" if year <= 2023 else ""  # 2023 年以前架构师一年只考一次（下半年）
    return year, half


def classify(rel):
    """按路径和文件名分类：cat（大类）+ part（真题、模拟题的哪一科：zh 综合知识 / al 案例 / lw 论文 / ans 答案详解 / all 整卷含解析）。"""
    t = rel.replace("\\", "/")
    name = os.path.basename(t)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    year, half = _year_half(t)
    out = {"cat": "其他", "part": "", "year": year, "half": half}
    if ext in VIDEO_EXT:
        out["cat"] = "视频"
        return out
    if re.search(r"答题卡|答题纸", t):
        out["cat"] = "答题卡"
    elif re.search(r"报名|报考|考试时间|考试科目|机考|模拟练习系统|在线模拟系统|绘图指南", t):
        out["cat"] = "报名机考"
    elif re.search(r"试题分析与解答", name):
        out.update(cat="真题", part="book")
    elif re.search(r"历年真题", t) and year and not re.search(r"视频讲解|直播", t):
        out["cat"] = "真题"
        if re.search(r"答案详解|答案解析", name):
            out["part"] = "ans"
        elif re.search(r"真题及解析|真题及答案|真题\+?解析", name):
            out["part"] = "all"
        elif re.search(r"综合知识|上午|科目一", name):
            out["part"] = "zh"
        elif re.search(r"案例|下午试卷\s*I(?!I)|科目二", name):
            out["part"] = "al"
        elif re.search(r"论文|下午试卷\s*II|科目三", name):
            out["part"] = "lw"
        elif re.search(r"无答", name):
            out["part"] = "noans"
    elif re.search(r"模拟|预测|押题", t):
        out["cat"] = "模拟题"
        if re.search(r"上午|综合知识", name):
            out["part"] = "zh"
        elif re.search(r"下午试题\s*[（(]\s*(?:Ⅱ|II)|论文|押题", name):
            out["part"] = "lw"
        elif re.search(r"下午|案例", name) or re.search(r"案例分析模拟题", t):
            out["part"] = "al"
    elif re.search(r"论文", t) and (re.match(r"(知网参考-)?论", name) or re.search(r"范文", name)):
        out["cat"] = "论文范文"
    elif re.search(r"论文", t):
        out["cat"] = "论文指导"
    elif re.search(r"案例", t):
        out["cat"] = "案例"
    elif re.search(r"教材|教程|32小时|体系结构原理", t):
        out["cat"] = "教材"
    elif re.search(r"导图|脑图", t) or ext in ("png", "jpg", "jpeg"):
        out["cat"] = "思维导图"
    elif re.search(r"知识点|背诵|易混淆|精华|集锦|笔记|错题集|计算题|考点|特点总结|经验|三色|设计模式|速记", t):
        out["cat"] = "知识点"
    elif re.search(r"课件|讲义|直播|精讲|视频课程|培训", t):
        out["cat"] = "讲义"
    elif ext in DOC_EXT:
        out["cat"] = "参考书"
    return out


def _pdf_info(path):
    import pymupdf

    d = pymupdf.open(path)
    try:
        n = d.page_count
        sample = list(range(0, n, max(1, n // 8)))[:10]
        chars = sum(len(d[i].get_text().strip()) for i in sample)
        # 只有水印字（每页几十个字）的扫描件也当作没有文字层
        return n, (chars / max(1, len(sample))) >= 120, len(d.get_toc())
    finally:
        d.close()


def scan(root, job=None):
    """遍历资料文件夹，写 catalog.json。没变的文件沿用上次的页数、文字层结果。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    prev = load()
    old = {f["rel"]: f for f in prev.get("files", [])} if prev.get("root") == root else {}
    paths = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root)
            if SKIP_RE.search(rel):
                continue
            paths.append((full, rel))
    paths.sort(key=lambda x: x[1])
    files = []
    for i, (full, rel) in enumerate(paths):
        if job:
            job.progress("扫描软考资料", i, len(paths), os.path.basename(rel))
        try:
            st = os.stat(full)
        except OSError:
            continue
        name = os.path.basename(rel)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        o = old.get(rel)
        if o and o.get("mtime") == int(st.st_mtime) and o.get("size") == st.st_size:
            f = dict(o)
            f.update(classify(rel))
            files.append(f)
            continue
        f = {"id": fid_of(rel), "rel": rel, "name": name, "ext": ext, "size": st.st_size, "mtime": int(st.st_mtime),
             "pages": 0, "text": True, "toc": 0}
        f.update(classify(rel))
        if ext == "pdf":
            try:
                f["pages"], f["text"], f["toc"] = _pdf_info(full)
            except Exception as e:  # noqa: BLE001 —— 坏文件记下原因跳过
                f["error"] = str(e)[:200]
        files.append(f)
    data = {"root": root, "files": files, "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return data
