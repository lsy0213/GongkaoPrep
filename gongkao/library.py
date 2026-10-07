"""资料库：扫描用户的资料文件夹，建目录、提取全文、渲染页面截图，并在后台生成真题题库。

所有生成的数据都放在数据目录的 library/ 下；原始资料文件只读不改。
"""

import hashlib
import json
import os
import re
import threading
import logging
import time
import zlib

from .dbutil import open_db
from .paths import data_dir

log = logging.getLogger("gongkao.library")

LIB_DIR = data_dir() / "library"
CATALOG_PATH = LIB_DIR / "catalog.json"
TEXT_DB = LIB_DIR / "fulltext.db"
CACHE_DIR = LIB_DIR / "cache"
REAL_BANK_PATH = LIB_DIR / "real_bank.json"
REAL_ESSAYS_PATH = LIB_DIR / "real_essays.json"
DECKS_PATH = LIB_DIR / "decks.json"

DEFAULT_ROOT = r"E:\aaaaaaaa\gongkao"
DOC_EXT = {"pdf", "docx", "doc", "txt", "jpg", "jpeg", "png"}


def fid_of(rel):
    return hashlib.md5(rel.replace("/", "\\").encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- 分类

SUBJECTS = [
    ("言语", r"言语|片段阅读|逻辑填空|语句|成语|词语|实词"),
    ("数量", r"数量|数学|数资|数推|蒙题"),
    ("判断", r"判断|图推|图形|类比|逻辑|定义"),
    ("资料", r"资料分析|资料-|资料刷|数资|高照|速算"),
    ("常识", r"常识|省情|时政|政治理论|政治-"),
    ("申论", r"申论|范文|公文|金句|规范词|热点"),
    ("面试", r"面试|结构化"),
]


def classify(rel):
    """按路径和文件名给资料分类：真题 / 题册 / 笔记讲义 / 申论素材 / 常识积累 / 其他。"""
    t = rel.replace("\\", "/")
    name = os.path.basename(t)
    if re.search(r"时政合集|每日晨读", t):
        # 时政合集、每日晨读另走 shizheng.py（软件里的“时政晨读”），资料库、闪卡、题库都不收
        m = re.search(r"(20\d\d)", name)
        return {"cat": "时政", "subj": ["常识"], "exam": "", "year": int(m.group(1)) if m else 0}
    if re.search(r"答题纸|答题卡", t):
        cat = "答题卡"
    elif re.search(r"真题|珍题|试题", t) and re.search(r"国考|国家|四川|联考|省考", t) and re.search(r"20\d\d", name):
        cat = "真题"
    elif re.search(r"千题|万题|刷题|必刷|5000题|题集|题本|题组|100题|套题|专项刷题|4600问|4000题|600题|速算|行测题目|行测/答案/", t):
        cat = "题册"
    elif re.search(r"申论", t) and re.search(r"范文|素材|模板|金句|规范词|热点|话题|典故|论据|人物|公文|贺词|会议", t):
        cat = "申论素材"
    elif re.search(r"常识|省情|时政|口诀", t):
        cat = "常识积累"
    elif re.search(r"笔记|讲义|宝典|思维导图|导图|手册|技巧|总结|课|班|要点|公式|秒杀", t):
        cat = "笔记讲义"
    else:
        cat = "其他"
    subj = [s for s, rx in SUBJECTS if re.search(rx, t)]
    exam = "四川" if "四川" in t else ("国考" if re.search(r"国考|国家", t) else "")
    m = re.search(r"(20\d\d)", name)
    return {"cat": cat, "subj": subj, "exam": exam, "year": int(m.group(1)) if m else 0}


# ---------------------------------------------------------------- 后台任务

class Cancelled(BaseException):
    """用户取消了后台任务。继承 BaseException：整理代码里“个别文件出错跳过”的 except Exception 不会吞掉它。"""


class Jobs:
    """后台整理任务（扫描、生成题库、整理文档……）：同一时间跑一个，后来的排队；可以取消。

    取消在下一次进度更新时生效（整理代码每处理一个文件或一页就报一次进度），已经整理好的部分会保留，
    下次再整理只做剩下的。界面轮询 status()。
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.cancel_flag = threading.Event()
        self.queue = []      # [(名字, 函数)]
        self.history = []    # 最近完成的任务
        self.state = self._fresh("")
        self.state["running"] = False

    @staticmethod
    def _fresh(name):
        return {"running": True, "name": name, "step": "", "done": 0, "total": 0, "msg": "", "error": "",
                "cancelled": False, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "finished_at": ""}

    def status(self):
        with self.lock:
            out = dict(self.state)
            out["queue"] = [name for name, _fn in self.queue]
            out["history"] = list(self.history)
            out["cancelling"] = self.cancel_flag.is_set() and self.state["running"]
            return out

    def progress(self, step, done, total, msg=""):
        with self.lock:
            self.state.update(step=step, done=done, total=total, msg=msg)
        self.check()

    def check(self):
        if self.cancel_flag.is_set():
            raise Cancelled()

    def start(self, name, fn):
        """开始任务；已有任务在跑时排到队尾。返回 "started" / "queued"；同名任务已在跑或已在队里返回 ""。"""
        with self.lock:
            if self.state["running"]:
                if name == self.state["name"] or any(n == name for n, _f in self.queue):
                    return ""
                self.queue.append((name, fn))
                return "queued"
            self.state = self._fresh(name)
            self.cancel_flag.clear()
        threading.Thread(target=self._run, args=(name, fn), name="job", daemon=True).start()
        return "started"

    def cancel(self, clear_queue=True):
        with self.lock:
            if clear_queue:
                self.queue.clear()
            if self.state["running"]:
                self.cancel_flag.set()
                return True
        return False

    def _run(self, name, fn):
        while True:
            err, cancelled = "", False
            log.info("开始后台任务：%s", name)
            try:
                fn(self)
            except Cancelled:
                cancelled = True
                log.info("后台任务已取消：%s", name)
            except Exception as e:  # noqa: BLE001
                log.exception("后台任务出错：%s", name)
                err = str(e)
            else:
                log.info("后台任务完成：%s", name)
            with self.lock:
                finished = time.strftime("%Y-%m-%d %H:%M:%S")
                self.history = ([{"name": name, "finished_at": finished, "error": err, "cancelled": cancelled}]
                                + self.history)[:10]
                self.cancel_flag.clear()
                if self.queue:
                    # 接着跑排队的任务：中间不把 running 置成 False，界面的轮询不会以为全部做完了
                    name, fn = self.queue.pop(0)
                    self.state = self._fresh(name)
                    continue
                self.state.update(running=False, error=err, cancelled=cancelled, finished_at=finished)
                return


jobs = Jobs()


# ---------------------------------------------------------------- 目录

_catalog_cache = {"mtime": None, "data": None}


def load_catalog():
    try:
        mt = CATALOG_PATH.stat().st_mtime
    except OSError:
        return {"root": "", "files": [], "scanned_at": ""}
    if _catalog_cache["mtime"] != mt:
        with open(CATALOG_PATH, encoding="utf-8") as f:
            _catalog_cache["data"] = json.load(f)
        _catalog_cache["mtime"] = mt
    return _catalog_cache["data"]


def catalog_index():
    return {f["id"]: f for f in load_catalog().get("files", [])}


def scan(root, job=None):
    """遍历资料文件夹，记录每个文件的页数、有没有文字层（扫描件没有）、分类。未变化的文件沿用上次结果。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    old = {f["rel"]: f for f in load_catalog().get("files", [])} if load_catalog().get("root") == root else {}
    paths = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in DOC_EXT:
                paths.append(os.path.relpath(os.path.join(dp, f), root))
    paths.sort()
    files = []
    for i, rel in enumerate(paths):
        if job and i % 20 == 0:
            job.progress("扫描资料文件", i, len(paths), os.path.basename(rel))
        full = os.path.join(root, rel)
        try:
            st = os.stat(full)
        except OSError:
            continue
        prev = old.get(rel)
        if prev and prev.get("size") == st.st_size and prev.get("mtime") == int(st.st_mtime):
            files.append({**prev, **classify(rel)})  # 分类规则可能更新过，重新算一遍（很快）
            continue
        ext = rel.rsplit(".", 1)[-1].lower()
        name = os.path.splitext(os.path.basename(rel))[0]
        # 卖家塞的广告图片不收录
        if ext in ("jpg", "jpeg", "png") and re.search(r"打印|首单|微信|加微|反馈|交流群|收货|5星|公众号", name):
            continue
        item = {"id": fid_of(rel), "rel": rel, "name": name, "ext": ext, "size": st.st_size,
                "mtime": int(st.st_mtime), "pages": 0, "text": False, **classify(rel)}
        if ext == "pdf":
            try:
                d = pymupdf.open(full)
                item["pages"] = d.page_count
                if not d.needs_pass:
                    n = min(d.page_count, 4)
                    chars = sum(len(d[k].get_text().strip()) for k in range(n))
                    item["text"] = chars // max(n, 1) >= 120
                d.close()
            except Exception:  # noqa: BLE001
                item["broken"] = True
        elif ext in ("docx", "txt"):
            item["text"] = st.st_size > 200
        files.append(item)
    data = {"root": root, "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CATALOG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, CATALOG_PATH)
    return data


def resolve(fid):
    """文件 id → 绝对路径（只允许目录里登记过的文件）。"""
    cat = load_catalog()
    f = catalog_index().get(fid)
    if not f or not cat.get("root"):
        return None, None
    path = os.path.join(cat["root"], f["rel"])
    return (path, f) if os.path.isfile(path) else (None, f)


def resolve_rel(rel):
    root = load_catalog().get("root") or ""
    path = os.path.normpath(os.path.join(root, rel))
    if not root or not path.startswith(os.path.normpath(root)) or not os.path.isfile(path):
        return None
    return path


# ---------------------------------------------------------------- 全文

def _text_db():
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    conn = open_db(TEXT_DB)
    conn.row_factory = None
    conn.execute("CREATE TABLE IF NOT EXISTS texts (fid TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, "
                 "offsets TEXT, body BLOB)")
    return conn


def _extract_pages(path, ext):
    if ext == "pdf":
        import pymupdf

        pymupdf.TOOLS.mupdf_display_errors(False)
        d = pymupdf.open(path)
        pages = [d[k].get_text() for k in range(d.page_count)]
        d.close()
        return pages
    if ext == "docx":
        import docx

        doc = docx.Document(path)
        return ["\n".join(p.text for p in doc.paragraphs)]
    if ext == "txt":
        for enc in ("utf-8", "gbk"):
            try:
                with open(path, encoding=enc) as f:
                    return [f.read()]
            except UnicodeDecodeError:
                continue
    return []


def build_text_index(job=None):
    """把每个有文字层的文件逐页提取文字，压缩后存进 fulltext.db（只处理新增或改动过的文件）。"""
    cat = load_catalog()
    root = cat.get("root")
    files = [f for f in cat.get("files", []) if f.get("text")]
    conn = _text_db()
    have = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT fid, mtime, size FROM texts")}
    keep = {f["id"] for f in files}
    for fid in set(have) - keep:
        conn.execute("DELETE FROM texts WHERE fid=?", (fid,))
    for i, f in enumerate(files):
        if job and i % 5 == 0:
            job.progress("提取全文", i, len(files), f["name"])
        if have.get(f["id"]) == (f["mtime"], f["size"]):
            continue
        try:
            pages = _extract_pages(os.path.join(root, f["rel"]), f["ext"])
        except Exception:  # noqa: BLE001
            continue
        offsets, buf, pos = [], [], 0
        for t in pages:
            t = re.sub(r"[ \t\r\f\v]+", " ", t)
            b = t.encode("utf-8")
            offsets.append(pos)
            buf.append(b)
            pos += len(b) + 1
        body = zlib.compress(b"\x00".join(buf), 6)
        conn.execute("INSERT OR REPLACE INTO texts(fid, mtime, size, offsets, body) VALUES (?, ?, ?, ?, ?)",
                     (f["id"], f["mtime"], f["size"], json.dumps(offsets), body))
        if i % 20 == 0:
            conn.commit()
    conn.commit()
    conn.close()


def text_index_info():
    if not TEXT_DB.exists():
        return {"files": 0, "mb": 0}
    conn = _text_db()
    n = conn.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
    conn.close()
    return {"files": n, "mb": round(TEXT_DB.stat().st_size / 1e6, 1)}


def search(q, fids=None, limit=300, per_file=8):
    """在全文里找关键词（逐个文件解压后直接查找，精确匹配任意长度的中文）。

    多个词用空格隔开时，要求同一页里都出现。
    """
    terms = [t for t in (q or "").split() if t]
    if not terms or not TEXT_DB.exists():
        return {"hits": [], "files": 0}
    anchor = max(terms, key=len).encode("utf-8")
    others = [t.encode("utf-8") for t in terms if t.encode("utf-8") != anchor]
    idx = catalog_index()
    conn = _text_db()
    hits, nfiles = [], 0
    for fid, offsets, body in conn.execute("SELECT fid, offsets, body FROM texts"):
        if (fids and fid not in fids) or fid not in idx:
            continue
        data = zlib.decompress(body)
        pos = data.find(anchor)
        if pos < 0 or any(data.find(o) < 0 for o in others):
            continue
        offs = json.loads(offsets)
        found, seen_pages = 0, set()
        while pos >= 0 and found < per_file:
            page = _page_of(offs, pos)
            if page not in seen_pages:
                seen_pages.add(page)
                start = offs[page]
                stop = offs[page + 1] if page + 1 < len(offs) else len(data)
                text = data[start:stop]
                if all(o in text for o in others):
                    a, b = max(0, pos - 90), pos + len(anchor) + 90
                    snippet = data[a:b].decode("utf-8", "ignore").replace("\x00", " ")
                    hits.append({"fid": fid, "page": page, "snippet": re.sub(r"\s+", " ", snippet)})
                    found += 1
            pos = data.find(anchor, pos + len(anchor))
        if found:
            nfiles += 1
        if len(hits) >= limit:
            break
    conn.close()
    return {"hits": hits[:limit], "files": nfiles}


def _page_of(offsets, pos):
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------- 页面截图

def render_png(path, page, clip=None, zoom=2.0):
    """渲染某页（或页内一块区域）为 PNG，结果缓存到磁盘。"""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    key = hashlib.md5(f"{path}|{os.path.getmtime(path)}|{page}|{clip}|{zoom}".encode("utf-8")).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / (key + ".png")
    if cached.exists():
        return cached.read_bytes()
    d = pymupdf.open(path)
    pg = d[max(0, min(page, d.page_count - 1))]
    rect = pymupdf.Rect(*clip) & pg.rect if clip else None
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, alpha=False)
    data = pix.tobytes("png")
    d.close()
    tmp = cached.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, cached)
    return data


# ---------------------------------------------------------------- 真题题库

def write_papers(bank):
    """真题卷解析结果写进题库数据库。"""
    from . import qdb

    sources, questions, materials = [], [], []
    for p in bank["papers"]:
        sources.append({**p, "fid": fid_of(p["file"]),
                        "answer_fid": fid_of(p["answer_file"]) if p.get("answer_file") else ""})
    pfid = {s["id"]: s["fid"] for s in sources}
    pinfo = {s["id"]: s for s in sources}
    for q in bank["questions"]:
        p = pinfo[q["paper"]]
        questions.append({**q, "source": q["paper"], "src": p["exam"], "year": p["year"], "fid": pfid[q["paper"]],
                          "sub": q.get("sub") or "其他"})
    for m in bank["materials"]:
        materials.append({**m, "source": m["paper"], "fid": pfid[m["paper"]]})
    qdb.replace_kind("paper", sources, questions, materials)


def real_keys():
    """真题卷里每道题的题干指纹，题册里遇到同一道题就不重复收。"""
    from . import books, qdb

    if not qdb.DB_PATH.exists():
        return set()
    conn = qdb.connect()
    keys = {books.dedup_key(r[0], r[1]) for r in conn.execute("SELECT stem, explain FROM questions WHERE kind='paper'")}
    conn.close()
    keys.discard(None)
    return keys


def build_books(root, job=None):
    """题册：千题册（版式识别 + 扫描版 OCR）和《决战行测5000题》（上册文字 + 下册解析 OCR），写进题库数据库。"""
    from . import books, qdb, wq5000

    files = load_catalog().get("files", [])

    def prog(i, n, name):
        if job:
            job.progress("识别千题册（扫描版需要 OCR，较慢）", i, n, name)

    def prog5k(i, n, name):
        if job:
            job.progress("识别5000题（解析册需要 OCR，第一次较慢）", i, n, name)

    keys = real_keys()
    sources, questions = books.build_all(files, root, keys, prog)
    keys |= {books.dedup_key(q["stem"], q["explain"]) for q in questions}
    s2, q2, m2 = wq5000.build_all(files, root, prog5k, keys)
    qdb.replace_kind("book", sources + s2, questions + q2, m2)


def build_real(root, job=None):
    from . import realexam, shenlun

    def p1(i, n, name):
        if job:
            job.progress("解析行测真题", i, n, name)

    def p2(i, n, name):
        if job:
            job.progress("解析申论真题", i, n, name)

    bank = realexam.build_all(root, p1)
    write_papers(bank)
    essays = shenlun.build_all(root, p2)

    def p3(i, n, name):
        if job:
            job.progress("生成闪卡卡组", i, n, name)

    from . import decks as decks_mod

    decks = decks_mod.build_all(load_catalog().get("files", []), root, p3)
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in ((REAL_ESSAYS_PATH, {"sets": essays, "root": root}), (DECKS_PATH, {"decks": decks})):
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    # 旧版的真题 JSON 已经并进数据库
    if REAL_BANK_PATH.exists():
        REAL_BANK_PATH.unlink()


_json_cache = {}


def load_json_cached(path, default):
    try:
        mt = path.stat().st_mtime
    except OSError:
        return default
    c = _json_cache.get(str(path))
    if not c or c[0] != mt:
        with open(path, encoding="utf-8") as f:
            c = (mt, json.load(f))
        _json_cache[str(path)] = c
    return c[1]


def real_essays():
    return load_json_cached(REAL_ESSAYS_PATH, {"sets": []})


def lib_decks():
    return load_json_cached(DECKS_PATH, {"decks": []})


def build_docs(root, job=None):
    """讲义、笔记、素材 → 带目录的结构化文档（扫描件要 OCR，第一次较慢）。"""
    from . import docs

    def prog(i, n, name):
        if job:
            job.progress("整理资料库文档（扫描件需要识别文字）", i, n, name)

    docs.build_all(root, load_catalog().get("files", []), prog)
    build_sucai(job)


def build_sucai(job=None):
    """从申论素材类资料里拆出金句、名言、人物、规范表述……加上内置精选，生成素材库。"""
    from . import sucai

    def prog(i, n, name):
        if job:
            job.progress("整理素材库", i, n, name)

    sucai.build(prog)


def build_shizheng(root, job=None):
    """时政合集 + 每日晨读 → 时政晨读（月度时政、专题、题库、人民日报精读、成语积累）。"""
    from . import shizheng

    def prog(i, n, name):
        if job:
            job.progress("整理时政晨读（扫描件需要识别文字）", i, n, name)

    shizheng.build(root, prog)


def full_rebuild(root, job):
    """一键整理：扫描目录 → 真题卷、申论、闪卡 → 千题册 → 资料库文档 → 时政晨读（扫描件 OCR，最慢，放最后）。"""
    scan(root, job)
    build_real(root, job)
    build_books(root, job)
    build_docs(root, job)
    build_shizheng(root, job)
