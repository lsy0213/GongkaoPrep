"""资料库文档：把讲义、笔记、素材整理成带目录的结构化文字，存进 library/docs.db。

每份资料变成一串“块”：标题 h（带级别，组成目录）、段落 p、表格 tbl、导图提纲 tree、框 box、例题 q。
资料库只显示文字，不放图片：存库前去掉所有插图，离不开图的例题（图形推理、选项画在图里）不收。
- 文字版 PDF：按版面还原行 → 合并成段落 → 按字号、粗细、编号格式（第一章 / 一、/（一）/ 1、）识别标题；
  PDF 自带书签时用书签做目录。表格转成文字表格；插图里的文字 OCR 后并进正文。
- 扫描版 PDF、图片：逐页 OCR（结果缓存，只识别一次），同样合并段落、识别标题；思维导图还原成提纲，
  超大的长图切块识别。
- Word：按样式识别标题，表格照搬；.doc 先用本机 Word 转成 .docx。
每份资料都有目录（标题不够时从导图主干、加粗短句、编号句、例题里补）。
答案、答题卡类文件不收（题目和答案在真题卷、刷题里）。
"""

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import unicodedata
from collections import Counter, defaultdict

from . import doccleanup, docq, layout, ocr, pdftext
from .dbutil import open_db
from .paths import data_dir

LIB = data_dir() / "library"
DB_PATH = LIB / "docs.db"
if os.environ.get("GONGKAO_DOCS_DB"):
    from pathlib import Path
    DB_PATH = Path(os.environ["GONGKAO_DOCS_DB"])  # 开发时用试整理的库预览，不动正式的 docs.db
IMG_DIR = LIB / "docimg"
OCR_DIR = LIB / "ocr"
CONV_DIR = LIB / "convert"
VERSION = 17  # 整理规则有变化时加一，旧结果会自动重做
BAD_FONT_GLYPH = chr(0x100A8B)  # 一批讲义错误字体映射形成的方框占位字

DOC_CATS = ("笔记讲义", "常识积累", "申论素材", "其他")
SKIP_RE = re.compile(r"答案|答题卡|答题纸|解析版|解析册|参考答案|课表|更新情况|解密|密码|售后|使用说明|下载说明|(?:^|[\\/])必看"
                     r"|公务员考试真题pdf")  # 真题卷放在“真题”里，资料库不再收一份
EXTS = {"pdf", "docx", "doc", "txt", "jpg", "jpeg", "png"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY, title TEXT, cat TEXT, subj TEXT, rel TEXT, ext TEXT, pages INTEGER,
    chars INTEGER, nblocks INTEGER, toc TEXT, scanned INTEGER, mtime INTEGER, size INTEGER,
    version INTEGER, built_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS doc_dups (doc TEXT PRIMARY KEY, keep TEXT);
CREATE TABLE IF NOT EXISTS blocks (
    doc TEXT, seq INTEGER, kind TEXT, level INTEGER, text TEXT, page INTEGER, data TEXT,
    PRIMARY KEY (doc, seq));
"""

_lock = threading.Lock()


def connect():
    LIB.mkdir(parents=True, exist_ok=True)
    conn = open_db(DB_PATH)
    conn.executescript(SCHEMA)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5("
                     "text, doc UNINDEXED, seq UNINDEXED, tokenize='trigram')")
    except sqlite3.OperationalError:
        pass  # 没有 FTS5 时搜索退回逐条匹配
    return conn


def has_fts(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='blocks_fts'").fetchone())


def selected(files):
    """要整理成文档的资料：讲义、常识、申论素材、其他；答案、答题卡类不收。
    同一个文件放在两个文件夹里（大小、页数都一样）只收一份，留放在更细分文件夹里的那份。"""
    sel = [f for f in files if f.get("cat") in DOC_CATS and f.get("ext") in EXTS and not f.get("broken")
           and not SKIP_RE.search(f["rel"])]
    best = {}
    for f in sel:
        key = (f.get("size"), f.get("ext"), f.get("pages"))
        rank = (-len(re.split(r"[\\/]", f["rel"])), len(f["name"]), f["rel"])
        if key not in best or rank < best[key][0]:
            best[key] = (rank, f["id"])
    keep = {v[1] for v in best.values()}
    return [f for f in sel if f["id"] in keep]


# 字体编码坏掉的 PDF：复制出来的字整体错位（“的”变“癿”、“人”变“乲”、“不”变“丌”），看着像汉字其实读不通。
# 这种文件的文字层不能用，整份按扫描件走 OCR。
BAD_CH = chr(0xFFFD)  # 文字层里取不出来的字
GARBLE_CHARS = set("癿乲丌戒迚丏乊孜庣斱厐乀丐乢収孖仹幵仸朹刜敁廸")
COMMON_CHARS = set("的是不了在人一有和这中为大国以上我们会个")


def _unmapped(ch):
    """PDF 字体映射失败时也会返回私用区字形，而不一定是 U+FFFD。"""
    return ch == BAD_CH or unicodedata.category(ch) in ("Co", "Cn", "Cs")


def garbled(text):
    visible = [ch for ch in text if not ch.isspace()]
    if len(visible) >= 40 and sum(map(_unmapped, visible)) >= len(visible) * 0.2:
        return True
    cjk = [ch for ch in text if "一" <= ch <= "鿿"]
    if len(cjk) < 200:
        return False
    if len(cjk) >= 800 and "一" not in cjk:
        return True  # 字体丢了“一”字（其道一也 → 其道 也），整份 OCR
    bad = sum(1 for ch in cjk if ch in GARBLE_CHARS)
    good = sum(1 for ch in cjk if ch in COMMON_CHARS)
    if bad >= 12 and len({ch for ch in cjk if ch in GARBLE_CHARS}) >= 5:
        return True  # 只错了一部分字（“収展”“廸设”“孖”）：常用字还对，但整份读不通
    return bad > len(cjk) * 0.02 and bad > good * 0.5


# ---------------------------------------------------------------- 标题识别

CN = "一二三四五六七八九十百零〇两"
HEAD_PATTERNS = [
    (0, re.compile(rf"^第[{CN}\d]+(篇|部分|编|模块)")),
    (1, re.compile(rf"^(第[{CN}\d]+(章|讲|课|单元)|专题[{CN}\d]+|模块[{CN}\d]+)")),
    (2, re.compile(rf"^(第[{CN}\d]+节|热点[{CN}\d]+|(考点|知识点归纳|知识点|材料归纳|题型|技巧|方法|秒杀)[{CN}\d]+)")),
    (3, re.compile(rf"^[{CN}]+\s*(?:[、.．]|，(?=\S{{2}}))")),
    (4, re.compile(rf"^[（(]\s*[{CN}]+\s*[）)]")),
    (5, re.compile(r"^\d{1,2}\s*[、.．](?!\d)")),
]
END_PUNCT_RE = re.compile(r"[，,。；;：:？?！!、…]$")
MARKER_RE = re.compile(
    rf"^([①-⑳]|[（(]\d{{1,2}}[）)]|\d{{1,2}}\s*[、.．](?!\d)|[{CN}]+\s*[、.．]|[（(][{CN}]+[）)]|"
    r"[A-H]\s*[.．、:：]|【|※|●|■|▲|◆|★|☆|►|▶|→|·|•|-\s|例\s*\d|第[一二三四五六七八九十\d]+)"
)
NOT_HEAD_RE = re.compile(r"^(?:解\s*析|答\s*案|点\s*评|批\s*注|旁\s*批)$|^[（(]\s*来源|^[（(](?![一二三四五六七八九十\d]+\s*[）)])[^）)]{1,8}[）)]\s*\S{2,4}$|^来源[:：]")
EXAMPLE_LABEL_RE = re.compile(r"^【(?:开头|结尾|事迹|金句|观点|素材|例句|解析)】")
DOT_LEADER_RE = re.compile(r"[.．·…]{5,}\s*\d*\s*$")
WATERMARK_RE = re.compile(r"^(天明考公|考公小镇|公考上岸小铺|樱有尽有|夜尽天明|微信公(?:众(?:号)?)?|[各资]料站|料站|登子|子考)$")


def head_rank(text, size, bold, body, all_bold=False, scanned=False, centered=False):
    """段落像不像标题：返回 (模式级别, 字号) 或 None。扫描件（OCR）的字号估计不准，要求更严。
    centered：单独一行、居中排（范文、文章的题目）。"""
    t = text.strip()
    n = len(t)
    if not n or n > 40 or DOT_LEADER_RE.search(t):
        return None
    if docq.Q_LABEL_RE.match(t) or re.search(r"[=＝≈]|_{3}|^[A-H]\s*[.．、]|^[A-H]{1,6}\s*。", t):
        return None  # 例题、算式、填空、选项都不是标题
    if docq.ANS_RE.match(t) or len(re.findall(r"[①-⑩]", t)) >= 2:
        return None  # “◎【答案】D”、折下来的一串“③养老；④社保”（OCR 框高，字号估大）
    if NOT_HEAD_RE.search(t) or EXAMPLE_LABEL_RE.match(t):
        return None  # “解析”栏头、“（来源：××）”“（人民观察）张翼”这类署名
    if END_PUNCT_RE.search(t) and not HEAD_PATTERNS[0][1].match(t) and not HEAD_PATTERNS[1][1].match(t):
        return None
    if size >= body * 3 and n <= 8:
        return None  # 封面上的装饰大字
    pat = next((rank for rank, rx in HEAD_PATTERNS if rx.match(t)), None)
    big = size >= body * 1.35 and n <= 24 if scanned else size >= body + 1.5
    if centered and 4 <= n <= 32 and not END_PUNCT_RE.search(t) and size >= body * 0.95:
        return (pat if pat is not None else 6, max(size, body + 0.6))
    if scanned and not big and (pat is None or pat > 4):
        return None
    if big:
        return (pat if pat is not None else 9, size)
    if pat is not None and (pat <= 4 and n <= 30 or pat == 2 and t.startswith("热点")):
        return (pat, size)
    if pat == 5 and n <= 18 and (bold or size >= body + 0.5):
        return (pat, size)
    if bold and not all_bold and n <= 24:
        return (6, size)
    return None


def assign_levels(blocks, body):
    """候选标题（k="h?"）→ 定级别。字号越大级别越高；同字号按编号格式（第一章 > 一、>（一）> 1、）。"""
    cands = [b for b in blocks if b["k"] == "h?"]
    if not cands:
        return
    paras = sum(1 for b in blocks if b["k"] in ("p", "h?"))
    # 标题太多（大多是把编号列表误认成标题），从最弱的一类开始去掉
    for weakest in (6, 5, 4):
        if len(cands) <= max(12, paras * 0.22):
            break
        for b in cands:
            if b["rank"][0] == weakest and b["rank"][1] < body + 1.5:
                b["k"] = "p"
                b.setdefault("d", {})["b"] = 1
        cands = [b for b in cands if b["k"] == "h?"]
    big_sizes = sorted({round(b["rank"][1] * 2) / 2 for b in cands if b["rank"][1] >= body + 1.5}, reverse=True)
    small_pats = sorted({b["rank"][0] for b in cands if b["rank"][1] < body + 1.5})
    for b in cands:
        s = round(b["rank"][1] * 2) / 2
        if s in big_sizes:
            lv = big_sizes.index(s)
        else:
            lv = len(big_sizes) + small_pats.index(b["rank"][0])
        b["lv"] = lv
    used = sorted({b["lv"] for b in cands})
    for b in cands:
        b["k"] = "h"
        b["lv"] = min(4, used.index(b["lv"]) + 1)
        b.pop("rank", None)
    # 相邻重复的标题（每页都印的章节名）只留第一个
    prev = None
    for b in blocks:
        if b["k"] == "h":
            if prev is not None and prev["t"] == b["t"]:
                b["k"] = "drop"
            prev = b
        elif b["k"] == "p":
            prev = None


# ---------------------------------------------------------------- 段落合并

def _percentile(vals, q):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, max(0, int(len(vals) * q)))] if vals else 0


def _columns(lines, width):
    """两栏排版：先左栏后右栏；否则按从上到下。"""
    if len(lines) < 10:
        return [lines]
    mid = width / 2
    left = [l for l in lines if l.x1 < mid + width * 0.02]
    right = [l for l in lines if l.x0 > mid - width * 0.02]
    cross = [l for l in lines if l.x0 < mid - width * 0.05 and l.x1 > mid + width * 0.05]
    if len(left) >= 5 and len(right) >= 5 and len(cross) <= len(lines) * 0.15:
        taken = {id(l) for l in left} | {id(l) for l in right}
        rest = [l for l in lines if id(l) not in taken]
        return [sorted(left + rest, key=lambda l: (l.y0, l.x0)), sorted(right, key=lambda l: (l.y0, l.x0))]
    return [lines]


def join_line(a, b):
    """拼接两行：中文直接接；英文、数字之间留空格。"""
    if a and b and re.match(r"[A-Za-z0-9]", a[-1]) and re.match(r"[A-Za-z0-9]", b[0]):
        return a + " " + b
    return a + b


def _centered(lines):
    """一行字居中排：左右两边空白差不多，而且左边空得明显（不是顶格的短行）。"""
    if len(lines) != 1:
        return False
    ln = lines[0]
    left, right = getattr(ln, "left", None), getattr(ln, "right", None)
    if left is None or right is None or right - left < ln.size * 12:
        return False
    sz = max(ln.size, 4)
    return ln.x0 - left > sz * 2.5 and abs((ln.x0 + ln.x1) / 2 - (left + right) / 2) < sz * 1.5


def build_paragraphs(items, body):
    """items：按阅读顺序排好的行（Line）和非文字块（dict）。返回块列表。"""
    out = []
    cur = None  # 正在拼的段落 {"lines": [...], "page":, "size":}

    def flush():
        nonlocal cur
        if cur:
            text = ""
            for ln in cur["lines"]:
                text = join_line(text, ln.text.strip())
            text = re.sub(r"\s{2,}", " ", text).strip()
            if text:
                ln0 = cur["lines"][0]
                blk = {"k": "p", "t": text, "pg": ln0.page, "_y0": ln0.y0, "_y1": cur["lines"][-1].y1}
                if len(cur["lines"]) <= 2:
                    rk = head_rank(text, max(l.size for l in cur["lines"]), all(l.bold for l in cur["lines"]),
                                   body, body_bold, getattr(ln0, "ocr", False), _centered(cur["lines"]))
                    if rk:
                        blk["k"], blk["rank"] = "h?", rk
                if blk["k"] == "p" and all(l.bold for l in cur["lines"]) and not body_bold:
                    blk["d"] = {"b": 1}
                out.append(blk)
        cur = None

    lines_only = [i for i in items if not isinstance(i, dict)]
    bold_chars = sum(len(i.clean) for i in lines_only if i.bold)
    all_chars = sum(len(i.clean) for i in lines_only) or 1
    body_bold = bold_chars / all_chars > 0.6
    # 这份资料正常的行距（折行的两行之间的空隙，以字号为单位）；比它大很多的才是段落间距
    gaps = []
    for a, b in zip(lines_only, lines_only[1:]):
        if a.page == b.page and getattr(a, "col", 0) == getattr(b, "col", 0) and b.y0 > a.y0 \
                and len(a.clean) >= 12 and a.x1 >= getattr(a, "right", a.x1) - a.size * 1.8:
            gaps.append((b.y0 - a.y1) / max(a.size, 1))
    g = sorted(gaps)[len(gaps) // 2] if len(gaps) >= 5 else 0.5
    gap_limit = max(g * 1.45, g + 0.35, 0.6)

    for it in items:
        if isinstance(it, dict):
            flush()
            out.append(it)
            continue
        ln = it
        if cur:
            last = cur["lines"][-1]
            size = max(ln.size, 1)
            new = False
            ocr_line = getattr(ln, "ocr", False)
            tol_size = max(1.0, last.size * 0.3) if ocr_line else 1.0
            tol_end = 2.6 if ocr_line else 1.8
            if abs(ln.size - last.size) > tol_size or ln.bold != last.bold and len(ln.clean) < 30:
                new = True
            elif MARKER_RE.match(ln.text.strip()):
                new = True
            elif ln.page == last.page and ln.col == last.col:
                if (ln.y0 - last.y1) / max(last.size, 1) > (max(gap_limit, 1.05) if ocr_line else gap_limit) or ln.y0 < last.y0:
                    new = True
                elif last.x1 < last.right - size * tol_end:
                    new = True  # 上一行没写满：段落结束
                elif ln.x0 > ln.left + size * 1.2 and not (
                        abs(ln.x0 - last.x0) < size * 0.8 and len(cur["lines"]) > 1
                        or MARKER_RE.match(cur["lines"][0].text.strip()) and ln.x0 < cur["lines"][0].x0 + size * 4):
                    new = True  # 首行缩进：新段落（编号后面悬挂缩进的续行不算）
            else:
                # 换页 / 换栏：上一行写满且这一行没缩进才接着拼
                if last.x1 < last.right - size * tol_end or ln.x0 > ln.left + size * 1.2 \
                        or re.search(r"[。！？”」]$", last.text.strip()):
                    new = True
            if new:
                flush()
        if not cur:
            cur = {"lines": []}
        cur["lines"].append(ln)
    flush()
    return out


def body_size(lines):
    c = Counter()
    for l in lines:
        c[round(l.size * 2) / 2] += len(l.clean)
    return c.most_common(1)[0][0] if c else 12


# ---------------------------------------------------------------- PDF

def _area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def _inside(line, rect, pad=2):
    cx, cy = (line.x0 + line.x1) / 2, (line.y0 + line.y1) / 2
    return rect[0] - pad <= cx <= rect[2] + pad and rect[1] - pad <= cy <= rect[3] + pad


def _inside_box(p, rect, pad=2):
    cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
    return rect[0] - pad <= cx <= rect[2] + pad and rect[1] - pad <= cy <= rect[3] + pad


def _band(blk):
    b = blk["_box"]
    return b[1], b[3]


def _ocr_page_images(d, page, fid, pno):
    """整页渲染失败（MuPDF 不支持的 JPEG 编码）：把页面上的图片取出来用 PIL / OpenCV 解码，再 OCR。"""
    import numpy as np

    path = OCR_DIR / fid / f"{pno}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if not ocr.available():
        return []
    out = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref")
        if not xref:
            continue
        try:
            raw = d.extract_image(xref)["image"]
        except Exception:  # noqa: BLE001
            continue
        img = None
        try:
            import io
            from PIL import Image
            img = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        except Exception:  # noqa: BLE001
            try:
                import cv2
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                img = None if img is None else img[:, :, ::-1].copy()
            except Exception:  # noqa: BLE001
                img = None
        if img is None:
            continue
        x0, y0, x1, y1 = info["bbox"]
        scale = img.shape[1] / max(1, x1 - x0)
        for b in ocr.recognize_upright(img, scale):
            if b[5] >= 0.6:
                out.append((b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0, b[4], b[5]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _save_render(page, rect, fid, name, zoom=1.8):
    import pymupdf

    out = IMG_DIR / fid
    out.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=pymupdf.Rect(rect), alpha=False)
    path = out / f"{name}.jpg"
    path.write_bytes(pix.tobytes("jpg", jpg_quality=82))
    return {"src": f"{fid}/{name}.jpg", "w": pix.width, "h": pix.height, "pw": round(rect[2] - rect[0])}  # pw：原资料里的宽度（点）


def _chart_img(page, rect, fid, name, pno, alt=""):
    """统计图截成清晰的图片（文字还原只剩零散数字）；文字留在 t 里供搜索。"""
    w = max(1.0, rect[2] - rect[0])
    zoom = max(2.0, min(3.5, 1300 / w))
    blk = _graphic(page, rect, fid, name, pno, re.sub(r"\s+", " ", alt or "").strip(), zoom=zoom)
    if blk["k"] == "img":
        blk["d"].pop("graphic", None)
        blk["d"]["chart"] = 1
    return blk


_YM = r"(?:(?:19|20)?\d{2}\s*年(?:\s*\d{1,2}\s*月份?)?|\d{1,2}\s*月份?|[一二三四1-4]\s*季度)"
_NUM = r"[-+−]?\d{1,7}(?:\.\d+)?\s*[%‰]?"
FIG_LABEL_RE = re.compile(rf"^\s*(?:[A-H]\s*[.．、:：]?|[①-⑩]|{_NUM}|[一-鿿]{{1,4}}|{_YM}(?:\s*{_YM})*|{_NUM}(?:\s+{_NUM})+)\s*$")  # 选项字母、刻度、单位、横轴的年份月份


LEGEND_RE = re.compile(r"[→□■▲●◆]|^\s*[(（]?\s*(?:%|单位|亿元|万元|万吨|万人|个|元)\s*[)）]?\s*$")  # 图例“□进口量 —进口额”、单位


def _grow(rect, items, h, W, H):
    """图片四周紧挨着的短标注（选项字母、刻度数字、单位）算进图里。items: [x0, y0, x1, y1, 文字, …]"""
    r = list(rect)
    for _ in range(3):
        grown = False
        for it in items:
            t = str(it[4])
            if not (FIG_LABEL_RE.match(t) or LEGEND_RE.search(t) and len(t) <= 24) or _inside_box(it, r):
                continue
            if it[0] < r[2] + h * 1.2 and it[2] > r[0] - h * 1.2 and it[1] < r[3] + h * 1.2 and it[3] > r[1] - h * 1.2:
                r = [min(r[0], it[0]), min(r[1], it[1]), max(r[2], it[2]), max(r[3], it[3])]
                grown = True
        if not grown:
            break
    return (max(0, r[0] - 3), max(0, r[1] - 3), min(W, r[2] + 3), min(H, r[3] + 3))


def _merge_charts(rects, items):
    """统计图的截图范围（已吸收四周标注）：重叠的（上下两张图共用标注）并成一张；
    再收一收边，不把旁边没吸收的正文（图题、题干）切掉半行。"""
    out = []
    for r in map(list, rects):
        merged = True
        while merged:
            merged = False
            for o in out:
                if r[0] < o[2] and o[0] < r[2] and r[1] < o[3] + 2 and o[1] < r[3] + 2:
                    r = [min(r[0], o[0]), min(r[1], o[1]), max(r[2], o[2]), max(r[3], o[3])]
                    out.remove(o)
                    merged = True
                    break
        out.append(r)
    for r in out:
        cy = (r[1] + r[3]) / 2
        for it in items:
            ov = _area((max(r[0], it[0]), max(r[1], it[1]), min(r[2], it[2]), min(r[3], it[3])))
            if not ov or ov >= _area(it[:4]) * 0.5:
                continue  # 大半在图里的字（图里的表格、标注）不收边
            if (it[1] + it[3]) / 2 > cy:
                r[3] = max(r[1] + 10, min(r[3], it[1] - 1))
            else:
                r[1] = min(r[3] - 10, max(r[1], it[3] + 1))
    return [tuple(r) for r in out]


def _image_rects(info, W, H, n, repeat):
    """页面上要当插图处理的图片：不是整页底图、不是同尺寸的底纹小图、不是每页同一位置的 logo。
    返回 (插图, 小图组)：挨在一起的几张小图（选项 A–D 各画一个小折线图）拼成的组单独给出——
    插图的序号要跟以前一样（插图 OCR 的缓存按序号存）。"""
    same = Counter((round(i["bbox"][2] - i["bbox"][0]), round(i["bbox"][3] - i["bbox"][1])) for i in info)
    figs, small = [], []
    for i in info:
        r = tuple(i["bbox"])
        w, h = r[2] - r[0], r[3] - r[1]
        if min(w, h) < 36 or _area(r) >= W * H * 0.55:
            continue
        if n >= 4 and repeat[tuple(round(v) for v in r)] >= 3:
            continue
        r = (max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3]))
        if _area(r) < W * H * 0.025:
            if _area(r) >= W * H * 0.006:
                small.append(r)
            continue
        if same[(round(w), round(h))] >= 4:
            continue
        if any(_area(r) and _area((max(r[0], f[0]), max(r[1], f[1]), min(r[2], f[2]), min(r[3], f[3]))) > _area(r) * 0.5 for f in figs):
            continue
        figs.append(r)
    groups = []
    for r in small:
        g = [r[0], r[1], r[2], r[3], 1]
        merged = True
        while merged:
            merged = False
            for o in groups:
                if g[0] - 90 <= o[2] and o[0] - 90 <= g[2] and g[1] - 60 <= o[3] and o[1] - 60 <= g[3]:
                    g = [min(g[0], o[0]), min(g[1], o[1]), max(g[2], o[2]), max(g[3], o[3]), g[4] + o[4]]
                    groups.remove(o)
                    merged = True
                    break
        groups.append(g)
    clusters = []
    for g in groups:
        r = tuple(g[:4])
        if g[4] >= 2 and _area(r) >= W * H * 0.025 and not any(
                _area((max(r[0], f[0]), max(r[1], f[1]), min(r[2], f[2]), min(r[3], f[3]))) > 0 for f in figs):
            clusters.append(r)
    return figs, clusters


def _chart_regs(page, regs, others, fid, pno, W, H):
    """版面分析出来的统计图区域（扫描页、文字层画的图）：按文字范围外扩一点截图，不压到旁边的正文。"""
    out = []
    for k, (y0, x0, blk) in enumerate(regs):
        if blk["k"] != "chart":
            out.append((y0, x0, blk))
            continue
        bx = blk.get("_box")
        h = 12
        if bx:
            ys = [o for o in others if o[0] < bx[2] and o[2] > bx[0]]
            h = max(8.0, min(24.0, (bx[3] - bx[1]) / 12))
            top = max([o[3] for o in ys if o[3] <= bx[1] + 1] or [bx[1] - h * 2])
            bot = min([o[1] for o in ys if o[1] >= bx[3] - 1] or [bx[3] + h * 2])
            rect = (max(0, bx[0] - h * 1.5), max(0, top + 1, bx[1] - h * 1.5), min(W, bx[2] + h * 1.5), min(H, bot - 1, bx[3] + h * 1.5))
            img = _chart_img(page, rect, fid, f"c{pno}_{k}", pno, blk.get("t", ""))
        else:
            img = {"k": "drop"}
        if img["k"] != "img":
            img = {"k": "box", "t": blk.get("t", ""), "pg": pno, "d": {"lines": [[t, 0] for t in (blk.get("t") or "").split("\n")]}}
        if bx:
            img["_box"] = bx
        out.append((y0, x0, img))
    return out


def _vector_figures(page, W, H, lines, exclude):
    """矢量画出来的图（流程图、坐标图）：大量线条、色块聚在一起，而且里面不是成段的文字。"""
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        return []
    rects = []
    for dr in drawings:
        r = dr["rect"]
        ra = (r.x0, r.y0, r.x1, r.y1)
        if _area(ra) > W * H * 0.5 or (r.width > W * 0.8 and r.height < 3):
            continue
        fill, stroke = dr.get("fill"), dr.get("color")
        if stroke is None and (fill is None or min(fill) > 0.93):
            continue
        if (dr.get("fill_opacity") or 1) < 0.4 and (stroke is None or (dr.get("stroke_opacity") or 1) < 0.4):
            continue  # 半透明的水印（整页斜着铺的“××资料站”）
        if any(_area((max(ra[0], e[0]), max(ra[1], e[1]), min(ra[2], e[2]), min(ra[3], e[3]))) > 0 for e in exclude):
            continue
        rects.append([ra[0] - 8, ra[1] - 8, ra[2] + 8, ra[3] + 8, 1])
    # 相互重叠的合成一组
    groups = []
    for r in rects:
        merged = True
        while merged:
            merged = False
            for g in groups:
                if r[0] <= g[2] and g[0] <= r[2] and r[1] <= g[3] and g[1] <= r[3]:
                    r = [min(r[0], g[0]), min(r[1], g[1]), max(r[2], g[2]), max(r[3], g[3]), r[4] + g[4]]
                    groups.remove(g)
                    merged = True
                    break
        groups.append(r)
    figs = []
    for g in groups:
        rect = (max(0, g[0]), max(0, g[1]), min(W, g[2]), min(H, g[3]))
        if g[4] < 12 or _area(rect) < W * H * 0.04 or _area(rect) > W * H * 0.75:
            continue
        inside = [l for l in lines if _inside(l, rect)]
        long_chars = sum(len(l.clean) for l in inside if len(l.clean) >= 22)
        all_chars = sum(len(l.clean) for l in inside) or 1
        if long_chars / all_chars > 0.55:
            continue  # 带边框的文字框，不是图
        figs.append(rect)
    return figs


def _clean_rows(rows):
    """表格去掉全空的行和列（合并单元格留下的空位）。"""
    rows = [[(c or "").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    # 合并单元格造成的错位：相邻两列从来不同时有内容，就并成一列
    j = 0
    while rows and j < len(rows[0]) - 1:
        if not any(r[j] and r[j + 1] for r in rows):
            rows = [r[:j] + [r[j] or r[j + 1]] + r[j + 2:] for r in rows]
        else:
            j += 1
    return rows


def _frame_like(rows):
    """其实不是表格：版面外框、文本框——几乎全部文字都在同一列里，别的列只在一两行有零星字（水印碎片）。"""
    if not rows:
        return True
    width = len(rows[0])
    if width <= 1:
        return True
    per = [sum(len(r[j]) for r in rows) for j in range(width)]
    main = per.index(max(per))
    other = sum(1 for r in rows if any(c for j, c in enumerate(r) if j != main))
    return len(rows) >= 6 and max(per) >= sum(per) * 0.92 and other <= max(2, len(rows) * 0.15)


def _texty(lines):
    """图片里的内容主要是成句的文字（格式模板、文字截图），而不是图表、导图。"""
    text = "".join(l.clean for l in lines)
    if len(text) < 12 or _is_poster(lines):
        return False
    cjk = len(re.findall(r"[一-鿿]", text))
    digits = len(re.findall(r"\d", text))
    lens = sorted(len(l.clean) for l in lines)
    return cjk >= len(text) * 0.5 and digits <= len(text) * 0.25 and lens[len(lens) // 2] >= 4


def _figure_block(page, rect, inside, pieces, fid, pno, k, ocred=False):
    """插图区域 → 块列表。主要是成段文字的，变成保留排版的文字框；导图、表格、框图按位置还原成提纲、表格；
    几乎没有字的纯图形（图形推理的图、几何图、照片）截成图片并标上 graphic——只有例题要用到它时才保留。"""
    W, H = page.rect.width, page.rect.height
    rr = (max(0, rect[0] - 4), max(0, rect[1] - 4), min(W, rect[2] + 4), min(H, rect[3] + 4))
    lines = inside
    raw = [list(p[:5]) for p in pieces]
    # 图片四周吸收进来的短标注（选项字母、刻度、单位）不算图里的字：图里几乎没字时照旧 OCR 一遍
    if sum(len(l.clean) for l in lines if not (FIG_LABEL_RE.match(l.text) or LEGEND_RE.search(l.text) and len(l.text) <= 24)) < 15             and not ocred:
        cache = OCR_DIR / fid / f"r{pno}_{k}.json"
        boxes = None
        if cache.exists():
            try:
                boxes = json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                boxes = None
        if boxes is None and ocr.available():
            try:
                boxes = [b for b in ocr.recognize_clip(page, rr) if b[5] >= 0.6]
            except Exception:  # noqa: BLE001
                boxes = []
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(boxes, ensure_ascii=False), encoding="utf-8")
        # 盖在正文上的半透明水印图：截下来认出的是底下正文的半行（“B. ①③”“68页”），文字层里都有，去掉
        layer = re.sub(r"\s", "", page.get_text())
        boxes = [b for b in boxes or [] if re.sub(r"\s", "", str(b[4])) not in layer]
        raw = _clean_boxes(boxes)
        lines = _boxes_to_lines(boxes or [], pno)
    fw = max(1, rr[2] - rr[0])
    wide = sum(len(l.clean) for l in lines if l.x1 - l.x0 >= fw * 0.55)
    if _texty(lines) and wide >= sum(len(l.clean) for l in lines) * 0.5:
        lines = sorted(lines, key=lambda l: (l.y0, l.x0))
        x_min = min(l.x0 for l in lines)
        w = max(1, rr[2] - rr[0])
        mid = (rr[0] + rr[2]) / 2
        out = []
        right = max(l.x1 for l in lines)
        prev_full = False
        for l in lines:
            c = (l.x0 + l.x1) / 2
            if abs(c - mid) < w * 0.08 and l.x0 > rr[0] + w * 0.15:
                align = "c"
            elif l.x0 > rr[0] + w * 0.5:
                align = "r"
            else:
                align = min(3, int((l.x0 - x_min) / max(l.size * 1.6, 1)))
            if out and prev_full and align == 0 and isinstance(out[-1][1], int):
                out[-1][0] = join_line(out[-1][0], l.text.strip())  # 框里折行的续行
            else:
                out.append([l.text.strip(), align])
            prev_full = l.x1 >= right - l.size * 1.5
        return [{"k": "box", "t": "\n".join(t for t, _a in out), "pg": pno, "d": {"lines": out}}]
    alt = " ".join(l.text for l in lines)
    if _meaningful(raw) or len(raw) >= 4:
        blks = layout.convert(layout.to_boxes(raw), pno)
        if any(b["k"] == "chart" for b in blks):
            return [_chart_img(page, rr, fid, f"p{pno}_{k}", pno, alt)]
        if _meaningful(raw):
            return blks
    return [_graphic(page, rr, fid, f"p{pno}_{k}", pno, alt)]


def _meaningful(raw):
    """图里的字够不够成内容：照片、海报上零星几个字（“央视 新闻”、人名）不算，当纯图形处理。"""
    lens = [len(re.sub(r"\s", "", str(r[4]))) for r in raw]
    return sum(lens) >= 30 or any(n >= 10 for n in lens)


def _graphic(page, rect, fid, name, pno, alt="", zoom=1.8):
    try:
        d = _save_render(page, rect, fid, name, zoom)
    except Exception:  # noqa: BLE001 —— 图片解码失败（个别 JPEG 格式 MuPDF 不支持）
        return {"k": "drop"}
    d["graphic"] = 1
    return {"k": "img", "t": alt, "pg": pno, "d": d}


def _ocr_norm(t):
    t = re.sub(r"\s", "", t)
    return "".join(str(ord(c) - 0x245F) if "①" <= c <= "⑨" else "0" if c == "⑩" else c for c in t)


def _prefer_layer(boxes, pieces):
    """文字层只缺了一部分字（转成曲线的页）：OCR 框里的字跟它下面的文字层对得上时，
    用文字层的字（OCR 常把“⑤⑩”认成“5”“0”），文字层缺的开头（“C.”“11、”）留 OCR 的。"""
    out = []
    for b in boxes:
        o = str(b[4])
        inside = sorted((p for p in pieces if _inside_box(p, b[:4])), key=lambda p: p[0])
        lt = re.sub(r"\s", "", "".join(p[4] for p in inside))
        o2 = re.sub(r"\s", "", o)
        if lt and lt != o2 and len(lt) >= 2:
            # 只认逐字对应的误认（长度相同）：文字层缺字的地方不能拿它顶替 OCR
            nl = _ocr_norm(lt)
            ks = [k for k in range(0, 5) if len(_ocr_norm(o2[k:])) == len(nl)
                  and re.fullmatch(r"(?:[A-H][.．、]?|\d{1,3}[、.．])?", o2[:k])]
            on = _ocr_norm(o2[ks[0]:]) if ks else ""
            if ks and on[:2] == nl[:2] and sum(x == y for x, y in zip(on, nl)) >= len(nl) * 0.7:
                b = list(b[:4]) + [o2[:ks[0]] + lt] + list(b[5:])
        out.append(b)
    return out


def _translucent_marks(page):
    """页面上有大块半透明填充（斜铺的水印字、印章）。"""
    try:
        drawings = page.get_cdrawings()
    except Exception:  # noqa: BLE001
        return False
    for dr in drawings:
        x0, y0, x1, y1 = dr["rect"]
        if dr.get("fill") is not None and (dr.get("fill_opacity") or 1) < 0.4 and (x1 - x0) * (y1 - y0) > 2000:
            return True
    return False


def _red_grid(img):
    """红色方格稿纸（作文纸）的格线：一行/一列里一半以上是红色的那些行列。"""
    px = img.astype("int16")
    red = (px[..., 0] > 140) & (px[..., 0] - px[..., 1] > 60) & (px[..., 0] - px[..., 2] > 60)
    return red, red.mean(axis=1) > 0.5, red.mean(axis=0) > 0.5


def _grid_paper(page):
    """整页印在红方格稿纸上：格线把每个字切开，OCR 认出来的全是半句。"""
    red, rows, cols = _red_grid(ocr.page_image(page, 0.5))
    return red.mean() < 0.2 and rows.sum() >= 15 and cols.sum() >= 10


def _erase_grid(img):
    """把格线所在的行列（含两侧各 2 像素）里偏红的和浅色的像素刷白；格子里的字（深色、红字）不动。"""
    import numpy as np
    _, rows, cols = _red_grid(img)
    band = lambda m: np.convolve(m.astype(int), np.ones(5, dtype=int), "same") > 0  # noqa: E731
    px = img.astype("int16")
    reddish = ((px[..., 0] - px[..., 1] > 25) & (px[..., 0] - px[..., 2] > 25)) | (px.min(axis=2) > 160)
    img[reddish & (band(rows)[:, None] | band(cols)[None, :])] = 255


def _ocr_boxes(fid, pno, page=None, img=None):
    """整页 OCR，结果缓存到 library/ocr/<文件>/<页>.g.json。横着放的页面转正后再识别，漏认的行再补认。
    旧版缓存（<页>.json，没补漏行）还在的，只做补漏，不整页重认。"""
    big = page is not None and img is None and ocr.page_zoom(page) < ocr.ZOOM
    # 盖着半透明水印的页：浅色像素先刷白再认，不然水印字（“橙子考公”）会混进正文
    wm = page is not None and img is None and _translucent_marks(page)
    # 红方格稿纸：先擦掉格线再认，缓存另起名字
    grid = page is not None and img is None and not wm and _grid_paper(page)
    # 超大页面按缩小倍数整页识别，缓存另起名字（旧的 .g.json 是切块认的，行中间有漏字）
    path = OCR_DIR / fid / (f"{pno}.r.json" if grid else f"{pno}.z.json" if big else f"{pno}.w.json" if wm
                            else f"{pno}.g.json")
    old = OCR_DIR / fid / f"{pno}.json"
    if big or wm or grid:
        old = path
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    boxes = None
    if old.exists():
        try:
            boxes = json.loads(old.read_text(encoding="utf-8"))
        except ValueError:
            boxes = None
    if not ocr.available():
        return boxes
    if img is None:
        zoom = ocr.page_zoom(page)
        img = ocr.page_image(page, zoom)
        if wm:
            img[img.min(axis=2) > 190] = 255
        if grid:
            _erase_grid(img)
    else:
        zoom = 1.0
    if boxes is not None and not ocr.sideways(boxes):
        boxes = boxes + [b for b in ocr.fill_gaps(img, boxes, zoom) if b[5] >= 0.6]
    else:
        boxes = [b for b in ocr.recognize_upright(img, zoom) if b[5] >= 0.6]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(boxes, ensure_ascii=False), encoding="utf-8")
    return boxes


AD_BRACKET_RE = re.compile(r"[【\[（(][^】\]）)]{0,24}(?:公众号|微信|淘宝|店铺|小铺|小镇|[Qq]{2}群?|[Vv][Xx])[^】\]）)]{0,24}[】\]）)]")


AD_SITE_RE = re.compile(r"【[^】]{0,16}资料站[^】]{0,8}】")
AD_INLINE_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{0,10}(?:公众号|资料站)+(?=解析)")
AD_TAIL_RE = re.compile(r"(?<=[）)])\s*(?:微信)?公众号\s*[:：]\s*[一-鿿A-Za-z0-9_]{2,12}\s*$")  # 标题后面跟着的“公众号：考公之子”
AD_FRAG_RE = re.compile(r"[:：]?\s*橙子考公?\s*微?|公?资料站|夜尽天明|樱有尽有")  # 水印残片夹在正文里


def strip_ad(t):
    """行里夹带的“【微信公众号：××】”“××资料站公众号解析：”去掉，剩下的正文留着（答案常跟在广告后面）；
    整行是广告就返回空。"""
    t = AD_TAIL_RE.sub("", AD_BRACKET_RE.sub("", t or ""))
    t = AD_INLINE_RE.sub("", AD_SITE_RE.sub("", t)).strip()
    t = re.sub(r"\s{2,}", " ", AD_FRAG_RE.sub("", t)).strip()
    if pdftext.AD_RE.search(t) and len(t) < 60:
        return ""
    return t


def _clean_ocr(t):
    t = pdftext.fix_chars((t or "").strip()).replace("自已", "自己")  # OCR 常把“己”认成“已”
    if not t or WATERMARK_RE.match(t):
        return ""
    t = strip_ad(t)
    # 圈码组合里的 ⑤ 常认成 5（“①②③5”）：紧跟在圈码后面、后面不再接数字和汉字的单个数字还原成圈码
    t = re.sub(r"(?<=[①-⑨])([1-9]+)(?=$|[\s；;，,。)）]|[①-⑩])",
               lambda m: "".join(chr(0x245F + int(c)) for c in m.group(1))
               if list(m.group(1)) == sorted(set(m.group(1))) else m.group(1), t)
    t = re.sub(r"[1-9](?=[②-⑩])", lambda m: chr(0x245F + int(m.group())) if t[m.end()] == chr(0x2460 + int(m.group())) else m.group(), t)
    # 一串表述里“④政协协商：5人民团体协商：6基层协商”：前面已经有上一个圈码的，分隔号后面的数字也是圈码
    while (m := next((m for m in re.finditer(r"(?<=[；;：:，,])\s*([2-9])(?=[一-鿿])", t)
                      if chr(0x245E + int(m.group(1))) in t[:m.start()]), None)):
        t = t[:m.start(1)] + chr(0x245F + int(m.group(1))) + t[m.end(1):]
    # 选项“D.①②③④⑤”的 D 常认成 1：整块只有圈码组合的“1.”是 D 选项
    t = re.sub(r"^[1lI|]\s*[.．]\s*(?=[①-⑩]{2,}\s*$)", "D.", t)
    return re.sub(rf"^(热点[{CN}\d]+)\s*[「」|｜]\s*", r"\1｜", t)


LOGO_RE = re.compile(r"EDUCAT|EDUOAT|SIHAI|四海教育")


def _clean_boxes(boxes):
    """OCR 文字块去掉广告、水印：同一页反复出现的英文大写字样（机构 logo）、零星的单个大写字母。"""
    out = []
    rep = Counter(re.sub(r"\s", "", str(b[4])).upper() for b in boxes or [])
    for b in boxes or []:
        t = _clean_ocr(b[4])
        if not t:
            continue
        key = re.sub(r"\s", "", t).upper()
        if LOGO_RE.search(key) and (rep[key] >= 2 or len(key) >= 5) and not re.search(r"[\u4e00-\u9fff]", t.replace("四海教育", "")):
            continue
        if re.fullmatch(r"[A-Z ]{4,}", t) and rep[key] >= 2:
            continue
        out.append([b[0], b[1], b[2], b[3], t])
    return out


def _boxes_to_lines(boxes, pno):
    """OCR 文字块 → 行。同一高度但隔得远的（两栏、并排的框）不拼在一起，交给分栏处理。"""
    items = []
    for b in boxes:
        t = _clean_ocr(b[4])
        if not t:
            continue
        items.append([b[0], b[1], b[2], b[3], t])
    items.sort(key=lambda b: ((b[1] + b[3]) / 2, b[0]))
    rows = []
    for b in items:
        h = b[3] - b[1]
        cy = (b[1] + b[3]) / 2
        for r in rows[-4:]:
            rh = r[3] - r[1]
            blank = re.search(r"[（(]\s*$", r[4]) and re.match(r"\s*[）)]", b[4]) and 0 <= b[0] - r[2] < max(h, rh) * 8
            if abs(cy - (r[1] + r[3]) / 2) < min(h, rh) * 0.5 and (-h < b[0] - r[2] < max(h, rh) * 1.5 or blank):
                # 题干里留空的括号“86.（　　）广东……”，OCR 把括号两边认成了隔得很远的两块
                r[4] = r[4] + "　　" + b[4] if blank else join_line(r[4], b[4]) if b[0] - r[2] < h * 0.6 else r[4] + " " + b[4]
                r[2], r[1], r[3] = b[2], min(r[1], b[1]), max(r[3], b[3])
                break
            blank = re.search(r"[（(]\s*$", b[4]) and re.match(r"\s*[）)]", r[4]) and 0 <= r[0] - b[2] < max(h, rh) * 8
            if abs(cy - (r[1] + r[3]) / 2) < min(h, rh) * 0.5 and blank:
                # “86.（”的中线略低，排序时落在了“）广东……”后面
                r[4] = b[4] + "　　" + r[4]
                r[0], r[1], r[3] = b[0], min(r[1], b[1]), max(r[3], b[3])
                break
        else:
            rows.append(list(b))
    lines = []
    for r in sorted(rows, key=lambda r: (r[1], r[0])):
        ln = pdftext.Line(pno, r[0], r[1], r[2], r[3], r[4], size=round((r[3] - r[1]) * 0.82, 1), bold=False)
        ln.ocr = True
        lines.append(ln)
    return lines


def _is_diagram(boxes):
    """图表式笔记（框图、表格式排版）：OCR 出来的文字块很多是并排在同一行、中间隔得很远。"""
    bs = [b for b in boxes if b[4].strip()]
    if len(bs) < 10:
        return False
    bs.sort(key=lambda b: b[1])
    side = 0
    for i, b in enumerate(bs):
        h = b[3] - b[1]
        for o in bs[max(0, i - 8): i + 9]:
            if o is b:
                continue
            if min(b[3], o[3]) - max(b[1], o[1]) > h * 0.5 and (o[0] - b[2] > h * 1.5 or b[0] - o[2] > h * 1.5):
                side += 1
                break
    return side >= len(bs) * 0.35


def _is_poster(lines):
    """思维导图、海报：大量零碎短词，几乎没有成句的长行。"""
    if len(lines) < 18:
        return False
    lens = sorted(len(l.clean) for l in lines)
    longish = sum(1 for n in lens if n >= 16)
    return lens[len(lens) // 2] <= 7 and longish <= len(lines) * 0.15


def _page_has_ink(page):
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.3, 0.3), alpha=False, colorspace=pymupdf.csGRAY)
    data = pix.samples
    if not data:
        return False
    mean = sum(data) / len(data)
    var = sum((v - mean) ** 2 for v in data[:: max(1, len(data) // 4000)]) / max(1, len(data[:: max(1, len(data) // 4000)]))
    return var > 300


MANGLED_FONT_RE = re.compile("[ÃÂµ]")  # 字体名是乱码（ËÎÌå 之类）的 PDF 常把部分文字转成曲线


def _outlined_pages(d):
    """文字被转成曲线画出来的页（复制不出来：选项 C、D，题号，题干开头整段缺）。
    只查字体名乱码的文件（这类导出工具才这样）；每页数一数字形大小的填充曲线，
    各页同一位置都有的（logo、水印）不算。"""
    try:
        fonts = {x[3] for pg in d for x in pg.get_fonts()}
    except Exception:  # noqa: BLE001
        return set()
    if not any(MANGLED_FONT_RE.search(f) for f in fonts):
        return set()
    per = []
    for pg in d:
        keys = []
        try:
            drawings = pg.get_cdrawings()
        except Exception:  # noqa: BLE001
            drawings = []
        for dr in drawings:
            x0, y0, x1, y1 = dr["rect"]
            items = dr["items"]
            if dr["type"] in ("f", "fs") and 3 <= y1 - y0 <= 24 and x1 - x0 <= 24 and len(items) >= 4                     and (dr.get("fill_opacity") or 1) >= 0.4 and any(it[0] == "c" for it in items):
                keys.append((round(x0), round(y0), round(x1), round(y1)))
        per.append(keys)
    rep = Counter(k for keys in per for k in set(keys))
    many = max(3, len(per) * 0.3)
    return {i for i, keys in enumerate(per) if sum(1 for k in keys if rep[k] < many) >= 8}


def _incomplete_text_layer(d, fid):
    """部分 PDF 的损坏字库把整行文字漏出文字层；抽样 OCR 与文字层比对。"""
    if not ocr.available() or not len(d):
        return False
    sample_pages = sorted({min(i, len(d) - 1) for i in (1, 3)})
    for pno in sample_pages:
        page = d[pno]
        fonts = {s["font"] for b in page.get_text("dict")["blocks"] if "lines" in b
                 for line in b["lines"] for s in line["spans"]}
        if not any(any(mark in font for mark in ("Ã", "Â", "µ")) for font in fonts):
            continue
        native = "".join(strip_ad(t) for t in page.get_text().splitlines())
        native_cjk = len(re.findall(r"[一-鿿]", native))
        if native_cjk < 80:
            continue  # 封面、目录页的字数差异不可靠
        try:
            boxes = _ocr_boxes(fid, pno, page) or []
        except Exception:  # noqa: BLE001 —— OCR 失败时仍可用文字层
            continue
        recognized = "".join(strip_ad(b[4]) for b in boxes if b[5] >= 0.6)
        ocr_cjk = len(re.findall(r"[一-鿿]", recognized))
        if ocr_cjk >= native_cjk * 1.18 and ocr_cjk - native_cjk >= 40:
            return True
    return False


def _normalize_ocr_hierarchy(blocks):
    """OCR 字号波动大；用明确的部分/小节编号恢复目录层级。"""
    if not any(b["k"] == "h" and HEAD_PATTERNS[0][1].match(b["t"]) for b in blocks):
        return
    for b in blocks:
        if b["k"] != "h":
            continue
        t = b["t"].strip()
        if EXAMPLE_LABEL_RE.match(t) or re.search(r"橙子考?|微信|资料站", t) or (
                len(t) < 5 and not any(rx.match(t) for _, rx in HEAD_PATTERNS)):
            b["k"] = "p"
        elif HEAD_PATTERNS[0][1].match(t):
            b["lv"] = 1
        elif re.match(rf"^第[{CN}\d]+(章|节|讲|课|单元)", t) or re.match(rf"^热点[{CN}\d]+", t):
            b["lv"] = 2
        elif HEAD_PATTERNS[3][1].match(t) or HEAD_PATTERNS[4][1].match(t):
            b["lv"] = 3


def from_pdf(path, fid, progress=None):
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    d = pymupdf.open(path)
    n = d.page_count
    infos = []
    repeat = Counter()
    for pg in d:
        info = pg.get_image_info()
        infos.append(info)
        for key in {tuple(round(v) for v in i["bbox"]) for i in info}:
            repeat[key] += 1

    sample = "".join(d[i].get_text() for i in range(0, n, max(1, n // 20)))
    force_ocr = ocr.available() and (garbled(sample) or _incomplete_text_layer(d, fid))
    bfont = pdftext.body_font(d, range(0, n, max(1, n // 12)))
    outlined = set() if force_ocr or not ocr.available() else _outlined_pages(d)

    doc = pdftext.Doc(path)
    extras = []  # 每页的非文字块 [(y0, x0, 块)]
    scanned_pages = 0
    for pno in range(n):
        page = d[pno]
        W, H = page.rect.width, page.rect.height
        doc.sizes.append((W, H))
        if progress:
            progress(pno, n)
        try:
            pieces = pdftext.page_pieces(page, math=True, body=bfont)
        except Exception:  # noqa: BLE001
            pieces = []
        pieces = [p[:4] + (strip_ad(p[4]),) + p[5:] for p in pieces]
        pieces = [p for p in pieces if p[4]]
        lines = pdftext.lines_from_pieces(pieces, pno)
        info = infos[pno]
        chars = sum(len(l.clean) for l in lines)
        big = [i for i in info if _area(i["bbox"]) >= W * H * 0.55]
        page_extra = []
        # 文字层里有不少字取不出来（复制出来是 U+FFFD）：这一页也用 OCR
        unmapped = sum(sum(map(_unmapped, l.text)) for l in lines)
        partial = (unmapped >= 8 and unmapped > sum(len(l.text) for l in lines) * 0.03 and ocr.available())             or pno in outlined
        if force_ocr or (chars < 25 and (big or not lines)) or partial:
            # 扫描页（整页是一张图）：OCR；导图、表格、框图区域按位置还原，其余按行拼段落
            scanned_pages += 1
            try:
                boxes = _ocr_boxes(fid, pno, page)
            except Exception:  # noqa: BLE001 —— 页面图片解码失败
                boxes = _ocr_page_images(d, page, fid, pno)
            if partial and boxes:
                boxes = _prefer_layer(boxes, pieces)
            raw = _clean_boxes(boxes)
            layer = lines
            lines = _boxes_to_lines(boxes or [], pno)
            whole = _is_poster(lines)
            if len(lines) < 3 and not raw:
                if big and _page_has_ink(page):
                    page_extra.append((0, 0, _graphic(page, (0, 0, W, H), fid, f"p{pno}", pno, zoom=1.4)))
                lines = []
            else:
                if not big:
                    # 文字转成曲线、文字层不全的页：页面上的统计图按图片范围截出来，其余照旧按文字处理
                    h0 = layout.char_h(layout.to_boxes(raw)) if raw else 12
                    ims, _cl = _image_rects(info, W, H, n, repeat)
                    grown = []
                    for r in ims:
                        ib = layout.to_boxes([x for x in raw if _inside_box(x, r)])
                        if len(ib) >= 4 and layout.is_chart(ib, layout.char_h(ib)):
                            grown.append(_grow(r, raw, h0, W, H))
                    for k, r in enumerate(_merge_charts(grown, raw)):
                        inside_r = [x for x in raw if _inside_box(x, r)]
                        raw = [x for x in raw if not _inside_box(x, r)]
                        blk = _chart_img(page, r, fid, f"c{pno}_i{k}", pno, " ".join(str(x[4]) for x in inside_r))
                        if blk["k"] == "img":
                            blk["_box"] = r
                            page_extra.append((r[1], r[0], blk))
                if whole and page_extra:
                    whole = False  # 统计图的刻度数字让整页看着像导图；图截走以后其余部分照常按版面分析，图才能排在原来的位置
                regs, rest = layout.analyse(raw, W, pno, whole=whole)
                regs = _chart_regs(page, regs, rest, fid, pno, W, H)
                page_extra += regs
                lines = _boxes_to_lines(rest, pno)
                bands = [_band(b) for _y, _x, b in page_extra if b.get("_box")]
                if partial and not force_ocr:
                    # OCR 偶尔整行漏检；文字层里完好的行，落在 OCR 没认出东西的位置就补上
                    for l in layer:
                        if BAD_CH in l.text or len(l.clean) < 2:
                            continue
                        cy = (l.y0 + l.y1) / 2
                        if any(a <= cy <= z for a, z in bands):
                            continue
                        if not any(o.y0 - 1 <= cy <= o.y1 + 1 and o.x0 < l.x1 and l.x0 < o.x1 for o in lines):
                            l.size = round((l.y1 - l.y0) * 0.82, 1)
                            lines.append(l)
                    lines.sort(key=lambda l: (l.y0, l.x0))
            for l in lines:
                l.ocr = True
        else:
            # 插图：不是整页底图、不是同尺寸的底纹小图、不是每页同一位置的 logo
            figs, clusters = _image_rects(info, W, H, n, repeat)
            # 表格
            tables = []
            try:
                has_lines = sum(1 for dr in page.get_drawings()
                                if dr["rect"].width < 2.5 or dr["rect"].height < 2.5) >= 8
            except Exception:  # noqa: BLE001
                has_lines = False
            if has_lines:
                try:
                    for t in page.find_tables().tables:
                        rows = [[(c or "").replace("\n", "") for c in row] for row in t.extract()]
                        cells = sum(1 for row in rows for c in row if c.strip())
                        if len(rows) >= 2 and max(len(r) for r in rows) >= 2 and cells >= 3 \
                                and not _frame_like(_clean_rows(rows)):
                            tables.append((tuple(t.bbox), rows))
                except Exception:  # noqa: BLE001
                    pass
            figs += _vector_figures(page, W, H, lines, [t[0] for t in tables] + figs)
            clusters = [c for c in clusters if not any(_area((max(c[0], f[0]), max(c[1], f[1]), min(c[2], f[2]), min(c[3], f[3]))) > 0
                                                       for f in figs + [t[0] for t in tables])]
            hb = body_size(lines) if lines else 12
            ltup = [(l.x0, l.y0, l.x1, l.y1, l.text) for l in lines]  # 按整行判断标注（文字片段常是半句话）
            charts = []
            for k, r in enumerate(figs + clusters):
                kk = k if k < len(figs) else 100 + k - len(figs)  # 小图组另起缓存名，不占插图的序号
                inside_p = [p for p in pieces if _inside_box(p, r)]
                blks = _figure_block(page, r, [l for l in lines if _inside(l, r)], inside_p, fid, pno, kk)
                if any((b.get("d") or {}).get("chart") for b in blks):
                    charts.append((_grow(r, ltup, hb, W, H), blks[0].get("t", "")))
                    continue
                for blk in blks:
                    page_extra.append((r[1], r[0], blk))
            chart_rects = _merge_charts([c for c, _t in charts], ltup)
            for k, r in enumerate(chart_rects):
                alt = " ".join(t for c, t in charts if _inside_box(c, r, pad=8))
                blk = _chart_img(page, r, fid, f"p{pno}_c{k}", pno, alt)
                if blk["k"] == "img":
                    page_extra.append((r[1], r[0], blk))
            figs = [r for r in figs if not any(_inside_box(r, c, pad=8) for c in chart_rects)] + chart_rects \
                + [c for c in clusters if not any(_inside_box(c, x, pad=8) for x in chart_rects)]
            for r, rows in tables:
                rows = _clean_rows(rows)
                if rows:
                    page_extra.append((r[1], r[0], {"k": "tbl", "t": " ".join(" ".join(row) for row in rows),
                                                    "pg": pno, "d": {"rows": rows}}))
            drop = [r for r, _rows in tables] + figs
            pieces = [p for p in pieces if not any(_inside_box(p, r) for r in drop)]
            # 文字层画出来的思维导图、无框线的表格、旁批：按位置还原
            regs, rest = layout.analyse(pieces, W, pno)
            regs = _chart_regs(page, regs, rest, fid, pno, W, H)
            page_extra += regs
            lines = pdftext.lines_from_pieces(rest, pno) if regs else \
                [l for l in lines if not any(_inside(l, r) for r in drop)]
        doc.pages.append(lines)
        extras.append(page_extra)
    toc = d.get_toc(simple=True)
    d.close()

    pdftext.mark_header_footer(doc)
    # 版面区域（框图、OCR 页上卷进来的那几行）里夹着的页眉页脚行也去掉：跟别处认出的页眉页脚同一行字
    hf = Counter(pdftext._norm_hf(l.text) for ls in doc.pages for l in ls if l.tag in ("header", "footer"))
    hkeys = {k for k, c in hf.items() if c >= 3 and len(k) >= 5}
    if hkeys:
        is_hf = lambda t: all(pdftext._norm_hf(x) in hkeys or (pdftext.AD_RE.search(x) and len(x) < 30)  # noqa: E731
                              for x in re.split(r"　{2,}|\s{3,}", t.strip()) if x.strip())
        for page_extra in extras:
            for _y, _x, blk in page_extra:
                lines_ = (blk.get("d") or {}).get("lines") if blk["k"] == "box" else None
                if lines_ and any(is_hf(ln[0] or "") for ln in lines_):
                    blk["d"]["lines"] = [ln for ln in lines_ if not is_hf(ln[0] or "")]
                    blk["t"] = "\n".join(ln[0] for ln in blk["d"]["lines"])
    items = []
    all_lines = []
    notes = []  # 旁批 (页, y, 块)：段落拼好后再放到对应段落前面
    for pno, lines in enumerate(doc.pages):
        W, H = doc.sizes[pno]
        if _toc_page(lines, extras[pno]):
            continue  # 资料自带的目录页（目录在侧栏）
        keep = [l for l in lines if not l.tag and not DOT_LEADER_RE.search(l.text) and not WATERMARK_RE.match(l.clean)
                and not ((l.y1 < H * 0.08 or l.y0 > H * 0.92) and pdftext.PAGE_NO_RE.match(l.text))
                and not (pdftext.AD_RE.search(l.text) and len(l.clean) < 60)]
        cols = _columns(keep, W)
        page_items = []
        for ci, col in enumerate(cols):
            long = [l for l in col if len(l.clean) >= 8] or col
            left = _percentile([l.x0 for l in long], 0.1)
            right = _percentile([l.x1 for l in long], 0.9)
            for l in col:
                l.col, l.left, l.right = ci, left, right
            page_items += [(ci, l.y0, l.x0, l) for l in col]
        for y0, x0, blk in extras[pno]:
            if (blk.get("d") or {}).get("side"):
                notes.append((pno, y0, blk))
                continue
            ci = 1 if len(cols) == 2 and x0 > W / 2 else 0
            page_items.append((ci, y0 - 0.5, x0, blk))
        page_items.sort(key=lambda t: (t[0], t[1], t[2]))
        items += [t[3] for t in page_items]
        all_lines += keep
    body = body_size(all_lines)
    blocks = _place_notes(build_paragraphs(items, body), notes)
    if len(toc) >= 3:
        _apply_outline(blocks, toc)
    else:
        assign_levels(blocks, body)
        if force_ocr:
            _normalize_ocr_hierarchy(blocks)
    return blocks, n, scanned_pages


TOC_LINE_RE = re.compile(r"[一-鿿].*?(?:[.．·…\s]\s*|[）)】”\"])\s*\d{1,4}\s*$")
TOC_DOT_RE = re.compile(r"[一-鿿].*?[.．·…]+\s*\d{1,4}\s*$")


# 两栏目录 OCR 后标题和页码分开：标题只剩尾巴上的引导点（“中心理解题·.”），页码单独一项（“·13...22”“..5959.64”“49”）
TOC_TAIL_RE = re.compile(r"[一-鿿][^一-鿿]*?[.．·…]{2,}[\s.．·…]*$|[一-鿿]\s*[.．·…]\s*[.．·…]\s*$")
TOC_PAGENO_RE = re.compile(r"""^[\s.．·…"“”'‘’:：\-—~～]*(?:\d{1,3}(?:[\s.．·…\-—~～]+\d{1,4})?|\d{4,12})[\s.．·…/]*$""")  # 粘在一起的页码“226226227”
TOC_SECT_RE = re.compile(r"^第[一二三四五六七八九十百\d]+[章节部分讲篇]")


def _toc_page(lines, extra):
    """资料自带的目录页：大半行是“标题 …… 页码”（导图样式的两栏目录：标题带引导点、页码单独成项）。"""
    texts = [l.text.strip() for l in lines if len(l.clean) >= 4]
    heads = [l.clean for l in lines[:6]]
    if any((b.get("d") or {}).get("chart") for _y, _x, b in extra) or any(re.match(r"\s*【\s*(?:例|练习)", t) for t in texts):
        return False  # 有统计图、有例题的页不是目录页（表格里“农业 6206.5 4.7”这种行很像“标题 页码”）
    for _y, _x, b in extra:
        d = b.get("d") or {}
        items = [t for _a, t in d.get("items") or []]
        heads += [re.sub(r"\s+", "", t) for t in items[:2]]
        texts += [" ".join(r) for r in d.get("rows") or []] + items + [t for t, _a in d.get("lines") or []]
    if len(texts) < 6:
        return False
    tails = sum(1 for t in texts if TOC_TAIL_RE.search(t))
    pagenos = sum(1 for t in texts if TOC_PAGENO_RE.match(t))
    if any(re.match(r"目\s*录|CONTENTS?", h or "", re.I) for h in heads):
        return sum(1 for t in texts if TOC_LINE_RE.search(t) or TOC_TAIL_RE.search(t) or TOC_PAGENO_RE.match(t)
                   or TOC_SECT_RE.match(t)) >= len(texts) * 0.35
    dotted = sum(1 for t in texts if TOC_DOT_RE.search(t) or DOT_LEADER_RE.search(t))
    return dotted >= len(texts) * 0.4 or (tails >= 5 and pagenos >= 3 and tails + pagenos + dotted >= len(texts) * 0.5)


def _place_notes(blocks, notes):
    """旁批放到它旁边那段正文的前面。"""
    if not notes:
        return blocks
    out = list(blocks)
    for pno, y, note in sorted(notes, key=lambda t: (t[0], t[1])):
        pos = None
        for i, b in enumerate(out):
            if b.get("pg") != pno or "_y0" not in b:
                continue
            if b["_y0"] - 2 <= y <= b["_y1"] + 2 or b["_y0"] > y:
                pos = i
                break
        if pos is None:
            pos = max((i + 1 for i, b in enumerate(out) if b.get("pg") == pno), default=len(out))
        out.insert(pos, note)
    # 同一段旁边的几条批注并成一条
    merged = []
    for b in out:
        if merged and (b.get("d") or {}).get("side") and (merged[-1].get("d") or {}).get("side"):
            merged[-1] = dict(merged[-1], t=merged[-1]["t"] + "；" + b["t"])
        else:
            merged.append(b)
    return merged


def _norm(t):
    return re.sub(r"[\s\W_]+", "", t or "")


def _apply_outline(blocks, toc):
    """PDF 自带书签：书签就是上层目录。找到书签对应的段落标成标题，找不到就在那一页开头插一个标题。
    书签下面用“一、”“（一）”这类编号的小标题，接在书签级别后面；其他候选标题降为加粗段落。"""
    first_of_page = {}
    for i, b in enumerate(blocks):
        first_of_page.setdefault(b.get("pg", 0), i)
    inserts = []
    matched_pats = set()
    # 书签页码坏了（全指向同一页，超哥各省时政补充资料就是这样）：按顺序在全文里找，找不到的不插
    pages_used = Counter(max(0, t[2] - 1) for t in toc)
    broken = len(toc) >= 4 and len(first_of_page) >= 5 and pages_used.most_common(1)[0][1] >= len(toc) * 0.6
    pos = 0

    def _core(t, title=False):
        # OCR 常丢掉开头的“一”（“、习近平在……”），比较时去掉编号
        t = re.sub(rf"^[{CN}\d]{'+' if title else '*'}\s*[、.．]|^[（(][{CN}\d]+[）)]", "", (t or "").strip())
        return _norm(t)[:10] if title else _norm(t)

    if broken:
        # 资料自带的目录页（一页上列着好几条书签标题）：去掉，从正文里找标题
        cores = [c for c in (_core(t[1], True) for t in toc) if c]
        per_page = defaultdict(set)
        for i, b in enumerate(blocks):
            bt = _core(b.get("t"))
            if b["k"] in ("p", "h?", "h") and len(b.get("t") or "") <= 80:
                for c in cores:
                    if bt.startswith(c):
                        per_page[b.get("pg", 0)].add(c)
        long_paras = Counter(b.get("pg", 0) for b in blocks if len(b.get("t") or "") > 60)
        for i, b in enumerate(blocks):
            pgi = b.get("pg", 0)
            if pgi <= 3 and len(per_page.get(pgi, ())) >= 3 and long_paras[pgi] <= 2 and b["k"] in ("p", "h?", "h") \
                    and any(_core(b.get("t")).startswith(c) for c in cores):
                b["k"] = "drop"
                pos = i + 1
    for lvl, title, page in toc:
        key = _norm(title)[:12]
        if not key:
            continue
        pg = max(0, page - 1)
        hit = None
        if broken:
            core = _core(title, True)
            for i in range(pos, len(blocks)):
                b = blocks[i]
                bt = _core(b.get("t"))
                if b["k"] in ("p", "h?", "h") and len(b.get("t") or "") <= max(80, len(title) + 10) and core and bt.startswith(core):
                    hit, pos = b, i + 1
                    break
            if not hit:
                continue
        for b in [] if broken else blocks:
            if b.get("pg") in (pg, pg + 1) and b["k"] in ("p", "h?") and len(b["t"]) <= 60 and (
                    _norm(b["t"]).startswith(key) or key.startswith(_norm(b["t"])[:12] or "#")):
                hit = b
                break
        if hit:
            if broken and len(hit["t"]) <= len(title.strip()) + 4 and not _norm(hit["t"]).startswith(_norm(title)[:4]):
                hit["t"] = title.strip()  # 补回 OCR 丢的编号
            if hit.get("rank"):
                matched_pats.add(hit["rank"][0])
            hit["k"], hit["lv"] = "h", min(4, lvl)
            hit.pop("d", None)
            hit.pop("rank", None)
        else:
            pos = first_of_page.get(pg, len(blocks))
            inserts.append((pos, {"k": "h", "lv": min(4, lvl), "t": title.strip(), "pg": pg}))
    for pos, blk in sorted(inserts, key=lambda x: -x[0]):
        blocks.insert(pos, blk)
    deepest = max((min(4, t[0]) for t in toc), default=1)
    pats = sorted({b["rank"][0] for b in blocks if b["k"] == "h?" and b["rank"][0] in (3, 4, 5)} - matched_pats)
    for b in blocks:
        if b["k"] != "h?":
            continue
        if b["rank"][0] in pats and deepest < 4:
            b["k"], b["lv"] = "h", min(4, deepest + 1 + pats.index(b["rank"][0]))
        else:
            b["k"] = "p"
            b.setdefault("d", {})["b"] = 1
        b.pop("rank", None)


# ---------------------------------------------------------------- Word / 文本 / 图片

def _convert_doc(path, fid):
    """.doc → .docx（用本机安装的 Word），结果缓存。"""
    out = CONV_DIR / f"{fid}.docx"
    if out.exists() and out.stat().st_mtime >= os.path.getmtime(path):
        return str(out)
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    src = path.replace("'", "''")
    dst = str(out).replace("'", "''")
    script = ("$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
              f"try{{$d=$w.Documents.Open('{src}',$false,$true);$d.SaveAs2('{dst}',16);$d.Close(0)}}finally{{$w.Quit()}}")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=180,
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not out.exists():
        raise RuntimeError("无法转换 .doc（需要本机安装 Microsoft Word）")
    return str(out)


def from_docx(path, fid):
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    blocks = []
    img_n = 0
    sizes = Counter()
    paras = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = pdftext.fix_chars(para.text.strip())
            style = (para.style.name if para.style is not None else "") or ""
            m = re.match(r"(?:Heading|标题)\s*(\d)", style)
            lv = int(m.group(1)) if m else (1 if style in ("Title", "标题") else None)
            runs = [r for r in para.runs if r.text.strip()]
            size = max((r.font.size.pt for r in runs if r.font.size), default=0)
            bold = bool(runs) and all(r.bold for r in runs)
            for r in runs:
                if r.font.size:
                    sizes[round(r.font.size.pt)] += len(r.text)
            for blip in child.iter(qn("a:blip")):
                rid = blip.get(qn("r:embed"))
                part = document.part.related_parts.get(rid) if rid else None
                if part is None:
                    continue
                ext = os.path.splitext(part.partname)[1].lower() or ".png"
                if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                    continue
                paras += _docx_image(part.blob, fid, img_n)
                img_n += 1
            if text and not (pdftext.AD_RE.search(text) and len(text) < 60):
                paras.append({"k": "p", "t": text, "pg": 0, "lv": lv, "size": size, "bold": bold})
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = [[c.text.strip() for c in row.cells] for row in table.rows]
            # 合并单元格会重复出现，相邻重复的去掉
            rows = [[c for i, c in enumerate(r) if i == 0 or c != r[i - 1]] for r in rows]
            if rows:
                paras.append({"k": "tbl", "t": " ".join(" ".join(r) for r in rows), "pg": 0, "d": {"rows": rows}})
    body = sizes.most_common(1)[0][0] if sizes else 12
    styled = any(p.get("lv") for p in paras)
    for p in paras:
        if p["k"] == "p" and not p.get("_img"):
            if p.get("lv"):
                p["k"] = "h"
            elif not styled:
                rk = head_rank(p["t"], p.get("size") or body, p.get("bold"), body)
                if rk:
                    p["k"], p["rank"] = "h?", rk
            for k in ("size", "bold"):
                p.pop(k, None)
            if p["k"] != "h":
                p.pop("lv", None)
        blocks.append(p)
    if not styled:
        assign_levels(blocks, body)
    else:
        for b in blocks:
            if b["k"] == "h":
                b["lv"] = min(4, b["lv"])
    return blocks, 1, 0


def _docx_image(blob, fid, n):
    """Word 里的图片：识别出文字就按版面还原成文字块（图里的标题当加粗段落，不进目录）；纯图形存成图片。"""
    import io

    import numpy as np
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(blob))
        img.load()
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001
        return []
    if min(img.size) < 24:
        return []
    arr = np.array(img)
    try:
        boxes = _ocr_boxes(fid, f"w{n}", img=arr) or []
    except Exception:  # noqa: BLE001
        boxes = []
    raw = _clean_boxes(boxes)
    if len(raw) >= 4 and layout.is_chart(layout.to_boxes(raw), layout.char_h(layout.to_boxes(raw))):
        return [_chart_file(img, fid, f"w{n}", raw)]
    blocks = _image_blocks(boxes, arr.shape[1], 0)
    if not blocks:
        return [_graphic_file(img, fid, f"w{n}")]
    texts = [b.get("t") or "" for b in blocks]
    if max(map(len, texts)) <= 14 and sum(map(len, texts)) <= 60:
        return []  # 照片上零星认出的台标、横幅、人名（“央视”“新闻”“感动中国2O22年度人物”），不是正文
    for b in blocks:
        b["_img"] = 1
        if b["k"] == "h?":
            b["k"] = "p"
            b.pop("rank", None)
            b["d"] = dict(b.get("d") or {}, b=1)
    return blocks


def from_txt(path):
    text = None
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            with open(path, encoding=enc) as f:
                text = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    blocks = []
    for line in (text or "").splitlines():
        t = line.strip()
        if not t or (pdftext.AD_RE.search(t) and len(t) < 60):
            continue
        blk = {"k": "p", "t": t, "pg": 0}
        rk = head_rank(t, 12, False, 12)
        if rk and rk[0] <= 4:
            blk["k"], blk["rank"] = "h?", rk
        blocks.append(blk)
    assign_levels(blocks, 12)
    return blocks, 1, 0


def from_image(path, fid):
    import numpy as np
    from PIL import Image

    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    boxes = _ocr_boxes(fid, 0, img=arr) or []
    raw = _clean_boxes(boxes)
    if len(raw) >= 4 and layout.is_chart(layout.to_boxes(raw), layout.char_h(layout.to_boxes(raw))):
        return [_chart_file(img, fid, "img", raw)], 1, 1
    blocks = _image_blocks(boxes, arr.shape[1], 0)
    if not blocks:
        return [_graphic_file(img, fid, "img")], 1, 1
    body = _percentile([b["_size"] for b in blocks if b.get("_size")], 0.5) or 12
    assign_levels(blocks, body)
    return blocks, 1, 1


def _image_blocks(boxes, W, pno):
    """一张图（整张图片文件、Word 里的图）的 OCR 结果 → 块：成段的文字拼段落，导图、表格、框图按位置还原。
    字太少（纯图形）返回空列表。"""
    raw = _clean_boxes(boxes)
    if not _meaningful(raw):
        return []
    lines = _boxes_to_lines(raw, pno)
    regs, rest = layout.analyse(raw, W, pno, whole=_is_poster(lines) or _is_diagram(boxes or []))
    lines = _boxes_to_lines(rest, pno)
    notes = []
    items = []
    if lines:
        left = _percentile([x.x0 for x in lines], 0.1)
        right = _percentile([x.x1 for x in lines], 0.9)
        for l in lines:
            l.ocr = True
            l.col, l.left, l.right = 0, left, right
            items.append((l.y0, l.x0, l))
    for y0, x0, blk in regs:
        if (blk.get("d") or {}).get("side"):
            notes.append((pno, y0, blk))
        else:
            items.append((y0 - 0.5, x0, blk))
    items.sort(key=lambda t: (t[0], t[1]))
    body = body_size(lines) if lines else 12
    blocks = _place_notes(build_paragraphs([t[2] for t in items], body), notes)
    for b in blocks:
        b["_size"] = body
    return blocks


def _chart_file(img, fid, name, raw):
    blk = _graphic_file(img, fid, name)
    blk["d"].pop("graphic", None)
    blk["d"]["chart"] = 1
    blk["t"] = " ".join(str(r[4]) for r in raw)
    return blk


def _graphic_file(img, fid, name):
    """纯图形保存成图片（只在例题要用、或图形推理资料里保留）。"""
    out = IMG_DIR / fid
    out.mkdir(parents=True, exist_ok=True)
    w, h = img.size
    scale = min(1.0, 1800 / max(w, h))
    shown = img.resize((int(w * scale), int(h * scale))) if scale < 1 else img
    shown.convert("RGB").save(out / f"{name}.jpg", quality=85)
    return {"k": "img", "t": "", "pg": 0, "d": {"src": f"{fid}/{name}.jpg", "graphic": 1}}


# ---------------------------------------------------------------- 整理

def build_one(root, f, progress=None):
    path = os.path.join(root, f["rel"])
    ext = f["ext"]
    from .curated_docs import transcript_blocks
    curated = transcript_blocks(path, f["name"])  # 手写笔记：用逐页核对的转写稿
    if curated:
        return curated
    if ext == "pdf":
        from .curated_docs import formula_blocks, matched_formula
        if matched_formula(path, f["name"]):
            return formula_blocks()
        return from_pdf(path, f["id"], progress)
    if ext == "docx":
        return from_docx(path, f["id"])
    if ext == "doc":
        return from_docx(_convert_doc(path, f["id"]), f["id"])
    if ext == "txt":
        return from_txt(path)
    return from_image(path, f["id"])


BAD_RE = re.compile("[�\ud800-\udfff]")  # 取不出来的字、落单的代理字符（存不进数据库）


def _strip_unmapped(text):
    text = text or ""
    if not any(map(_unmapped, text)):
        return text
    return re.sub(r" {2,}", " ", "".join(ch for ch in text if not _unmapped(ch))).strip()


def _strip_bad(b):
    """去掉没能识别的字，去完是空的块不要。"""
    b["t"] = _strip_unmapped(b.get("t"))
    d = b.get("d")
    if d and d.get("rows"):
        d["rows"] = [[_strip_unmapped(c) for c in r] for r in d["rows"]]
    if d and d.get("lines"):
        d["lines"] = [[clean, a] for t, a in d["lines"] if (clean := _strip_unmapped(t))]
    if d and d.get("items"):
        d["items"] = [[a, clean] for a, t in d["items"] if (clean := _strip_unmapped(t))]
    return b["k"] == "img" or bool(b.get("t"))


ENTRY_HEAD_RE = re.compile(r"^\s*\d{1,4}\s*[.．、]\s*\S.{0,15}$")
ENTRY_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*[.．、]\s*\S.{0,15}$")


def _tidy_entries(blocks):
    """连续编号的词条统一为同级标题；PDF 字号不稳定时也不能漏掉词条。"""
    entries = [(b, ENTRY_NUMBER_RE.match(b.get("t") or "")) for b in blocks if b["k"] in ("h", "p")]
    entries = [(b, m) for b, m in entries if m]
    nums = [int(m.group(1)) for _b, m in entries]
    if len(nums) < 30 or len(set(nums)) < len(nums) * 0.8 or \
            sum(b == a + 1 for a, b in zip(nums, nums[1:])) < (len(nums) - 1) * 0.75:
        return blocks
    entry_ids = {id(b) for b, _m in entries}
    others = [b for b in blocks if b["k"] == "h" and id(b) not in entry_ids]
    lv = min(4, max((b.get("lv") or 1 for b in others), default=0) + 1)
    for b, _m in entries:
        b["k"], b["lv"], b["d"] = "h", lv, {"entry": 1}
    return blocks


PUBLISHER_RE = re.compile(r"出版社|Publishing House of|CIP\s*数据", re.I)
BOOK_META_RE = re.compile(r"图书在版编目|\bCIP\b|\bISBN\b|版权所有|版权页", re.I)
TOC_ENTRY_RE = re.compile(r"^\s*\d{1,3}\s*[.．、]\s*[^\d\W]", re.U)


def _printed_toc_table(b):
    """只识别开头几页带“编号词条 + 页码”的原书目录表。"""
    if b["k"] != "tbl" or b.get("pg", 99) > 5:
        return False
    rows = (b.get("d") or {}).get("rows") or []
    hits = sum(any(TOC_ENTRY_RE.match(c or "") for c in row)
               and any(re.fullmatch(r"\s*\d{1,3}\s*", c or "") for c in row) for row in rows)
    return hits >= 8 and hits >= len(rows) * 0.6


def _drop_front_matter(blocks):
    """资料库已有导航，封面出版社和原书的页码目录不再作为学习正文。"""
    first = [b for b in blocks if b.get("pg") == 0]
    cover = (first and len(first) <= 12 and any(PUBLISHER_RE.search(b.get("t") or "") for b in first)
             and not any(ENTRY_HEAD_RE.match(b.get("t") or "") or HEAD_PATTERNS[0][1].match(b.get("t") or "") for b in first))
    skip_pages = {0} if cover else set()
    if cover:
        for pg in range(1, 4):
            page = [b for b in blocks if b.get("pg") == pg]
            if page and any(BOOK_META_RE.search(b.get("t") or "") for b in page) and not any(
                    b["k"] == "q" or ENTRY_HEAD_RE.match(b.get("t") or "")
                    or CHAPTER_RE.match(b.get("t") or "") for b in page):
                skip_pages.add(pg)
    return [b for b in blocks if b.get("pg") not in skip_pages and not _printed_toc_table(b)]


PART_ONLY_RE = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+(?:篇|部分|编|模块)$")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+章")


META_HEAD_RE = re.compile(r"^\s*(?:话题|来源|出处|原标题)\s*[:：]|《[^》]{2,12}》\s*(?:第?\d+版)?\s*\d{4}[.\-年]\d")  # “话题：调查研究 《人民日报》05版2023.01.31”
FRAG_HEAD_RE = re.compile(r"^\s*(?:【解】|[=＝|)）×÷])|^\s*[A-D]\s*[.．、]\s*\S+\s+[B-D]\s*[.．、]")  # 解题步骤、算式断片、一行选项
YEAR_HEAD_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*年?\s*$")


def _demote_heads(blocks):
    """明显不是标题的“标题”改回正文：文章出处行、解题步骤、算式断片、一行选项、以句号结尾的①②条目；
    单独一个年份当标题的，只有全文按年份分节（三处以上）时才留着。"""
    years = sum(1 for b in blocks if b["k"] == "h" and YEAR_HEAD_RE.match(b.get("t") or ""))
    for b in blocks:
        if b["k"] != "h":
            continue
        t = (b.get("t") or "").strip()
        opened = t.count("(") + t.count("（")
        closed = t.count(")") + t.count("）")
        if META_HEAD_RE.search(t) or FRAG_HEAD_RE.search(t) or closed > opened \
                or (YEAR_HEAD_RE.match(t) and years < 3) or re.match(r"^\s*[①-⑳].{9,}[。；]$", t):
            b["k"] = "p"
            b.pop("lv", None)
    return blocks


def _normalize_heads(blocks):
    """“第二部分 / 言语理解与表达”合成一个标题，章级稳定排在部分之下。"""
    out = []
    i = 0
    has_part = any(b["k"] == "h" and PART_ONLY_RE.match((b.get("t") or "").strip()) for b in blocks)
    while i < len(blocks):
        b = blocks[i]
        if b["k"] == "h" and PART_ONLY_RE.match((b.get("t") or "").strip()):
            b["lv"] = 1
            if i + 1 < len(blocks):
                nxt = blocks[i + 1]
                title = (nxt.get("t") or "").strip()
                if nxt["k"] == "h" and nxt.get("pg") == b.get("pg") and 2 <= len(title) <= 20 \
                        and not any(rx.match(title) for _rank, rx in HEAD_PATTERNS) and not ENTRY_HEAD_RE.match(title):
                    b["t"] = f"{b['t'].strip()} {title}"
                    i += 1
        elif has_part and b["k"] == "h" and CHAPTER_RE.match((b.get("t") or "").strip()):
            b["lv"] = 2
        out.append(b)
        i += 1
    return out


PREFIX_HEAD_RE = re.compile(r"^\s*【([^】]{1,6})】\s*(\S.{1,38})$")
NOT_PREFIX_RE = re.compile(r"例|答案|解析|点拨|注意|拓展|总结|练习|小结|技巧|方法|真题|题|提示|备注|注|口诀|速记|开头|结尾|事迹|金句|观点|素材")
END_RE = re.compile(r"[，,。；;：:！!？?、]$")


def _prefix_heads(blocks):
    """同一个【前缀】反复出现在短行开头（“【常识】‘最低刑事责任年龄’考点汇总”）：这些行是各篇的标题。"""
    cnt = Counter()
    for b in blocks:
        if b["k"] in ("p", "h?", "h"):
            m = PREFIX_HEAD_RE.match(b.get("t") or "")
            if m and not END_RE.search(b["t"]) and not NOT_PREFIX_RE.search(m.group(1)):
                cnt[m.group(1)] += 1
    tags = {t for t, n in cnt.items() if n >= 3}
    if not tags:
        return blocks
    others = [b for b in blocks if b["k"] == "h"]
    shift = 1 if any((b.get("lv") or 1) <= 1 for b in others) else 0
    for b in others:
        b["lv"] = min(4, (b.get("lv") or 1) + shift)
    for b in blocks:
        if b["k"] in ("p", "h?", "h"):
            m = PREFIX_HEAD_RE.match(b.get("t") or "")
            if m and m.group(1) in tags and not END_RE.search(b["t"]):
                b["k"], b["lv"] = "h", 1
                b.pop("rank", None)
                if b.get("d"):
                    b["d"].pop("b", None)
    return blocks


def _toc_title(t, n=30):
    t = re.sub(r"\s+", " ", docq.plain(t or "")).strip()
    return t if len(t) <= n else t[:n] + "…"


TOC_SKIP_RE = re.compile(r"^\s*【\s*(?:答\s*案|解\s*析)|[①②③④⑤⑥⑦⑧⑨⑩]|参考答案\s*[:：]")  # 答案行、选项组合不当目录项


def make_toc(blocks, name):
    """目录（连着重复的项只留第一个：每页幻灯片都印一遍的标题、同名导图）。"""
    toc = [e for e in _make_toc(blocks, name) if not doccleanup.NOT_HEAD_RE.search(e[1].strip())]  # 课前说明行不进目录
    return [e for j, e in enumerate(toc) if j == 0 or re.sub(r"\s", "", e[1]) != re.sub(r"\s", "", toc[j - 1][1])]


def _make_toc(blocks, name):
    """目录：标题块。标题太少（扫描件、模板、素材汇编）时，从导图的主干、加粗短句、编号短句、
    单独成行的小标题、例题里补；还没有就按内容分段，取每段开头做目录项。每份资料都有目录。"""
    toc = [[b.get("lv") or 1, _toc_title(b["t"], 60), i] for i, b in enumerate(blocks) if b["k"] == "h"]
    if toc:
        # 章节内的单主题导图也是可跳转的小节；只收中文主干，避免公式碎片变成目录。
        subheads = []
        parent_lv = toc[0][0]
        for i, b in enumerate(blocks):
            if b["k"] == "h":
                parent_lv = b.get("lv") or 1
            elif b["k"] == "tree" and not (b.get("d") or {}).get("notoc"):
                roots = [t.strip() for dep, t in (b.get("d") or {}).get("items", [])
                         if dep == 0 and 2 <= len(t.strip()) <= 18 and re.search(r"[\u4e00-\u9fff]", t)]
                if len(roots) == 1:
                    if not subheads or subheads[-1][1] != roots[0] or subheads[-1][2] != i - 1:
                        subheads.append([min(5, parent_lv + 1), roots[0], i])
        if 1 <= len(subheads) <= 30:
            toc = sorted(toc + subheads, key=lambda x: x[2])
    if len(toc) >= 3 or (toc and len(blocks) <= 30) \
            or (len(toc) >= 2 and sum(1 for b in blocks if b["k"] == "q") >= 20):  # 题本：“一、单选题”“二、多选题”就够了
        return toc
    cand = []
    qstems = []
    nq = 0
    for i, b in enumerate(blocks):
        t = (b.get("t") or "").strip()
        k = b["k"]
        if k == "tree" and not (b.get("d") or {}).get("notoc"):
            items = (b.get("d") or {}).get("items") or []
            roots = [x for x in items if x[0] == 0]
            for dep, it in items:
                # 只有一个主干时第一层分支也进目录，但成句的分支（“九一八事变成为……的序幕”）不算小标题
                if dep == 0 or (len(roots) == 1 and dep == 1 and len(it.strip()) <= 16 and not re.search(r"[，,。；;]", it)):
                    cand.append(("tree", dep + 1, _toc_title(it), i))
        elif k == "p" and t and len(t) <= 30 and not END_RE.search(t) and not TOC_SKIP_RE.search(t) \
                and len(re.findall(r"[\u4e00-\u9fff]", t)) >= 3:
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            pat = next((r for r, rx in HEAD_PATTERNS if rx.match(t)), None)
            if (b.get("d") or {}).get("b"):
                cand.append(("bold", 1 if pat is None or pat <= 3 else 2, _toc_title(t), i))
            elif pat is not None:
                cand.append(("num", 1 if pat <= 3 else 2 if pat == 4 else 3, _toc_title(t), i))
            elif len(t) <= 16 and nxt is not None and nxt["k"] in ("p", "box", "tbl", "tree", "q") \
                    and len(nxt.get("t") or "") > max(30, len(t) * 2):
                cand.append(("short", 1, _toc_title(t), i))
        elif k == "q":
            nq += 1
            q = b.get("d") or {}
            stem = re.sub(r"^\s*[【\[]?\s*(?:例\s*题?|练习|习题)?\s*\d*(?:\s*[-－]\s*\d+)?\s*[】\]]?\s*[.．、:：]?\s*", "",
                          q.get("stem") or "")
            stem = re.sub(r"^\s*【[^】]{1,12}】\s*", "", stem)  # 题目来源标签（【小黑政治理论】）
            qstems.append((len(cand), stem))
            cand.append(("q", 2, f"例{q.get('num') or nq}", i))
    # 各题共同的开头（“2026年中央一号文件《……》发布。”）不进目录，只留各题不同的部分
    common = os.path.commonprefix([st for _j, st in qstems]) if len(qstems) >= 3 else ""
    cut = len(common) if len(common) >= 8 else 0
    for j, st in qstems:
        kind, lv, label, i = cand[j]
        cand[j] = (kind, lv, _toc_title(f"{label}　{st[cut:].strip() or st}", 26), i)
    order = (("tree", "bold", "num"), ("tree", "bold", "num", "short"), ("q",))
    if nq >= 10:
        order = (("q",),) + order  # 题本、刷题课：目录按题走，别把讲解里的编号短句当目录
    for kinds in order:
        got = [c for c in cand if c[0] in kinds]
        if kinds != ("q",) and len(got) > max(60, len(blocks) * 0.4):
            got = [c for c in got if c[0] in ("tree", "bold")] or got[: max(60, len(blocks) // 10)]
        if len(got) >= 2 or (got and len(blocks) <= 30):
            have = {s for _lv, _t, s in toc}
            extra = [[max(2, lv) if toc and kinds == ("q",) else lv, t, s] for _k, lv, t, s in got if s not in have]
            return sorted(toc + extra, key=lambda x: x[2])
    if toc:
        return toc
    # 按内容分段：每段开头的文字做目录项
    texts = [(i, b) for i, b in enumerate(blocks) if b.get("t")]
    if not texts:
        return [[1, _toc_title(name), 0]] if blocks else []
    step = max(6, len(texts) // 12)
    out = []
    for j in range(0, len(texts), step):
        i, b = texts[j]
        first = re.split(r"(?<=[。；！？])", b["t"].strip())[0]
        out.append([1, _toc_title(first, 24), i])
    if len(out) == 1:
        out[0][1] = _toc_title(name)
    return out


def _fragment(d):
    """版面拆散后剩下的残题：选项字母不从 A 起或不连续、不到两个选项（数字推理这类题干本来就没几个字，不按题干判断）。"""
    letters = [a for a, _o in d.get("opts") or []]
    return len(letters) < 2 or letters != [chr(ord("A") + i) for i in range(len(letters))]


def _unquiz(blocks, only=None):
    """申论资料里用 A、B、C 编号的要点（“答题技巧：A.直接摘抄 B.借鉴他人做法”）被认成了选择题：
    没有答案的这类“题”还原成普通段落。only：只还原满足条件的（行测资料里的残题）。d["plain"] 的不管有没有答案都还原。"""
    out = []
    for b in blocks:
        if b["k"] == "q" and (b["d"].pop("plain", None) or not b["d"].get("ans") and (only is None or only(b["d"]))):
            pg = b.get("pg", 0)
            out += [{"k": "p", "t": t, "pg": pg} for t in b["d"]["stem"].split("\n") if t.strip()]
            out += [{"k": "tbl", "t": f.get("alt") or "", "pg": pg, "d": {"rows": f["rows"]}} if f.get("rows")
                    else {"k": "img", "t": f.get("alt") or "", "pg": pg, "d": {x: f[x] for x in ("src", "chart", "w", "h", "pw") if f.get(x)}}
                    for f in b["d"].get("figs") or [] if f.get("rows") or f.get("chart")]
            out += [{"k": "p", "t": f"{a}. {o}", "pg": pg} for a, o in b["d"]["opts"] if o]
            out += [{"k": "p", "t": e["t"], "pg": pg} for e in b["d"].get("exp") or [] if e.get("t")]
        else:
            out.append(b)
    return out


def _text_only(b):
    """插图只留统计图（d.chart）；题目里的图（材料图、画在图里的选项）跟着题目保留。
    选项没有文字、也没有图的题没法作答，返回 None。"""
    if b["k"] == "img":
        return b if (b.get("d") or {}).get("chart") and (b["d"].get("src")) else None
    if b["k"] != "q":
        return b
    d = b["d"]
    figs = [f for f in d.get("figs") or [] if f.get("rows") or f.get("src")]
    if not any(o for _a, o in d.get("opts") or []) and not any(f.get("src") for f in figs):
        return None
    if len(docq._key(d.get("stem") or "")) < 4 and not figs:
        d["plain"] = True  # 题干没取到（公式在图里、排版拆散），只剩选项的“题”没法作答：选项和解析当正文留着
        d["figs"] = []
        return b
    d["figs"] = figs
    d["exp"] = [e for e in d.get("exp") or [] if not e.get("src") or e.get("chart")]
    return b



BRAND_RE = re.compile(r"网|教育|公众号|抖音|微信|淘宝|讲数资|超大杯|祝|上岸|题库|资料站|小铺|店铺|[Qq]{2}|群|课堂|学院|^[\x00-\x7f]+$")
STRONG_BRAND_RE = re.compile(r"抖音|公众号|淘宝|微信号|讲数资|小铺|店铺|祝.{0,6}上岸")
FRAG_SPLIT_RE = re.compile(r"\n|　{2,}|\s{3,}")


def _strip_boilerplate(blocks):
    """页眉页脚、水印没被版面分析认出来、混进了正文（“抖音：公考高照讲数资”“公考事业题库网”）：
    在很多页反复出现的短片段，带机构名、网址这类字样的，从所有块里删掉。"""
    pages = {b.get("pg", 0) for b in blocks}
    if len(pages) < 6:
        return blocks
    seen = {}
    for b in blocks:
        for fr in FRAG_SPLIT_RE.split(b.get("t") or ""):
            fr = re.sub(r"\s*\d{1,4}\s*$|^\s*\d{1,4}\s*", "", fr).strip()
            if 4 <= len(fr) <= 40 and BRAND_RE.search(fr):
                seen.setdefault(fr, set()).add(b.get("pg", 0))
    # 明显是推广语的（抖音号、店铺名、“祝小可爱成功上岸”）出现三页以上就算；其余要在很多页上反复出现
    junk = sorted((fr for fr, ps in seen.items()
                   if len(ps) >= max(4, len(pages) * 0.12) or (len(ps) >= 3 and STRONG_BRAND_RE.search(fr))), key=len, reverse=True)
    if not junk:
        return blocks
    rx = re.compile(r"\s*\d{0,4}\s*(?:" + "|".join(re.escape(j) for j in junk) + r")\s*\d{0,4}(?=\s|$)|(?:" + "|".join(re.escape(j) for j in junk) + ")")
    out = []
    for b in blocks:
        t = b.get("t") or ""
        if t and rx.search(t):
            t2 = re.sub(r"\n{2,}", "\n", rx.sub(" ", t)).strip()
            if not re.sub(r"[\s\d　]", "", t2):
                if b["k"] in ("p", "h"):
                    continue  # 整块都是页眉页脚
            b = dict(b, t=t2)
            if b.get("d") and b["d"].get("lines"):
                b["d"] = dict(b["d"], lines=[[rx.sub(" ", x).strip(), a] for x, a in b["d"]["lines"] if rx.sub("", x).strip()])
        out.append(b)
    return out


def _drop_running_heads(blocks):
    """每页页眉印着的章名（“第一章片段阅读”）被认成了标题、夹在题目中间：同一标题出现在很多页上的，只留第一次。"""
    pages = {b.get("pg", 0) for b in blocks}
    where = {}
    for b in blocks:
        if b["k"] == "h":
            where.setdefault(re.sub(r"\s", "", b.get("t") or ""), set()).add(b.get("pg", 0))
    run = {t for t, ps in where.items() if t and len(ps) >= max(4, len(pages) * 0.12)}
    if not run:
        return blocks
    out, seen = [], set()
    for b in blocks:
        k = re.sub(r"\s", "", b.get("t") or "") if b["k"] == "h" else None
        if k in run:
            if k in seen:
                continue
            seen.add(k)
        out.append(b)
    return out


JUNK_HEAD_RE = re.compile(r"^[\x00-\x7f]{1,15}$|^\S$")  # 水印残片（“cn”“heng”“公”）被认成了标题
SLIDE_NO_RE = re.compile(r"^\s*幻灯片\s*\d+\s*$|^\s*默认节\s*$")  # 课件转 PDF 留下的“幻灯片 6”和 PowerPoint 的“默认节”
SLIDE_PREFIX_RE = re.compile(r"^\s*幻灯片\s*\d+\s*[:：]\s*")  # “幻灯片 1: 2025资料分析超大杯 第10节课”


GUINA_HEAD_RE = re.compile(r"^\s*知识点归纳\s*\d{1,3}\s*[:：]\s*\S.{0,24}$")  # 超大杯讲义的“知识点归纳29：给图找主体”
PIAN_HEAD_RE = re.compile(r"^\s*第\s*\d{1,3}\s*篇\s*[（(][^）)]{2,20}[）)]\s*$")  # 资料分析讲义每篇材料的标题“第65篇（2023国考）”


def _unslide(b):
    if b["k"] in ("h", "p") and SLIDE_PREFIX_RE.match(b.get("t") or ""):
        b = dict(b, t=SLIDE_PREFIX_RE.sub("", b["t"], count=1))
    if b["k"] == "p" and PIAN_HEAD_RE.match(b.get("t") or ""):
        b = dict(b, k="h", lv=3)
    elif b["k"] == "p" and GUINA_HEAD_RE.match(b.get("t") or ""):
        b = dict(b, k="h", lv=4)
    return b


FRAC_RE = re.compile("⦅([^⁄⦆]*)⁄([^⦆]*)⦆")
MATHY_RE = re.compile(r"^[\s\d.,+\-−×÷*/()（）%a-zA-Z√π]*$")


def _unfrac(t):
    return FRAC_RE.sub(lambda m: m.group(0) if MATHY_RE.match(m.group(1)) and MATHY_RE.match(m.group(2))
                       and m.group(1).strip() and m.group(2).strip() else m.group(1) + m.group(2), t)


def _fix_fracs(b):
    if "⦅" in (b.get("t") or ""):
        b["t"] = _unfrac(b["t"])
    d = b.get("d")
    if b["k"] == "q" and d:
        d["stem"] = _unfrac(d.get("stem") or "")
        d["opts"] = [(a, _unfrac(o or "")) for a, o in d.get("opts") or []]
        for e in d.get("exp") or []:
            e["t"] = _unfrac(e.get("t") or "")
    elif d and d.get("lines"):
        d["lines"] = [[_unfrac(x), a] for x, a in d["lines"]]
    elif d and d.get("items"):
        d["items"] = [[a, _unfrac(x)] for a, x in d["items"]]
    return b


def save(conn, f, blocks, pages, scanned, error="", post=None):
    blocks = _drop_front_matter([b for b in blocks if _strip_bad(b)])
    blocks = _tidy_entries(_prefix_heads(blocks))
    blocks = [b for b in _strip_boilerplate(blocks) if not (b["k"] == "h" and JUNK_HEAD_RE.match((b.get("t") or "").strip()))]
    blocks = _demote_heads(_normalize_heads(_drop_running_heads([_unslide(b) for b in blocks if not SLIDE_NO_RE.match(b.get("t") or "")])))
    blocks = doccleanup.clean(blocks, f)  # 图表刻度、图注、水印残片、课件重复段落、分课讲义串课
    blocks = docq.group(blocks)  # 例题并成可作答的题块
    # 插图只留统计图（文字还原不了，截成图显示）和例题里要用到的图（材料图、画在图里的选项）；
    # 照片、装饰图、导图截图不要（导图、表格已经还原成文字）
    blocks = [_fix_fracs(b) for b in (_text_only(b) for b in blocks) if b]
    name = f.get("name") or ""
    if "申论" in name or "面试" in name or (f.get("cat") == "申论素材" and "行测" not in name):
        blocks = _unquiz(blocks)
    else:
        # plain（没题干）的在这里一并还原
        # 没答案、又残缺的“题”（选项从 C 开始、只剩一个选项、题干只有图表数字）不当题目显示，还原成正文
        blocks = _unquiz(blocks, only=lambda d: d.get("notq") or _fragment(d))
    # 资料自带的“目录”页已经去掉了页码行，标题也不要（目录在侧栏）
    blocks = [b for b in blocks if b["k"] in ("h", "p", "tbl", "box", "tree", "q", "img")]
    blocks = [b for b in blocks if not (b["k"] in ("h", "p") and re.fullmatch(r"目\s*录|CONTENTS?|Contents?", b.get("t", "").strip()))]
    if post:
        blocks = post(blocks)  # 调用方自己的最后一道整理（时政晨读：清理标题）
    toc = make_toc(blocks, f.get("name") or "")
    fts = has_fts(conn)
    with _lock, conn:
        conn.execute("DELETE FROM blocks WHERE doc=?", (f["id"],))
        if fts:
            conn.execute("DELETE FROM blocks_fts WHERE doc=?", (f["id"],))
        chars = 0
        for seq, b in enumerate(blocks):
            conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                         (f["id"], seq, b["k"], b.get("lv") or 0, b.get("t", ""), b.get("pg", 0),
                          json.dumps(b["d"], ensure_ascii=False) if b.get("d") else None))
            if fts and b.get("t"):
                conn.execute("INSERT INTO blocks_fts(text, doc, seq) VALUES (?,?,?)", (docq.plain(b["t"]), f["id"], seq))
            if b["k"] != "img":
                chars += len(b.get("t", ""))
        conn.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (f["id"], f["name"], f["cat"], ",".join(f.get("subj") or []), f["rel"], f["ext"], pages, chars,
                      len(blocks), json.dumps(toc, ensure_ascii=False), int(scanned or 0), f["mtime"], f["size"],
                      VERSION, time.strftime("%Y-%m-%d %H:%M:%S"), error))


def build_all(root, files, progress=None):
    """整理全部文档：没变化的跳过；先做文字版（快），再做需要 OCR 的扫描版。"""
    sel = selected(files)
    conn = connect()
    have = {r["id"]: (r["mtime"], r["size"], r["version"], r["error"]) for r in conn.execute("SELECT * FROM docs")}
    curated_outdated = {r["id"] for r in conn.execute(
        "SELECT id FROM docs WHERE title='【数量】秒杀公式总结' AND toc NOT LIKE '%基础公式%' ")}
    from .curated_docs import transcript_times
    edited = transcript_times()
    curated_outdated |= {r["id"] for r in conn.execute("SELECT id, title, built_at FROM docs")
                         if r["title"] in edited and (r["built_at"] or "") < edited[r["title"]]}
    bad_docs = {r[0] for r in conn.execute("SELECT DISTINCT doc FROM blocks WHERE instr(text, ?) > 0", (BAD_FONT_GLYPH,))}
    keep = {f["id"] for f in sel}
    with _lock, conn:
        for fid in set(have) - keep:
            conn.execute("DELETE FROM docs WHERE id=?", (fid,))
            conn.execute("DELETE FROM blocks WHERE doc=?", (fid,))
            if has_fts(conn):
                conn.execute("DELETE FROM blocks_fts WHERE doc=?", (fid,))
    todo = [f for f in sel if have.get(f["id"], (None,) * 4)[:3] != (f["mtime"], f["size"], VERSION)
            or f["id"] in curated_outdated
            or f["id"] in bad_docs or (have[f["id"]][3] and ocr.available())]
    todo.sort(key=lambda f: (f["ext"] in ("jpg", "jpeg", "png") or (f["ext"] == "pdf" and not f.get("text")), f["pages"]))
    total = sum(max(1, f.get("pages") or 1) for f in todo) or 1
    done = 0
    for f in todo:
        name = f["name"]

        def prog(i, n, done=done, name=name):
            if progress:
                progress(done + i, total, f"{name}（{i + 1}/{n} 页）")

        if progress:
            progress(done, total, name)
        try:
            blocks, pages, scanned = build_one(root, f, prog)
            save(conn, f, blocks, pages, scanned)
        except Exception as e:  # noqa: BLE001 —— 个别文件损坏不影响其他
            save(conn, f, [], 0, False, error=str(e)[:200])
        done += max(1, f.get("pages") or 1)
    find_duplicates(conn)
    fill_from_docs(conn)
    conn.close()


def fill_from_docs(conn):
    """同一道例题常出现在好几份资料里，有的给了答案、有的没给：没给的借用别的资料里的答案和解析（题干、选项都要对得上）。"""
    rows = conn.execute("SELECT b.doc, b.seq, b.data, d.title FROM blocks b JOIN docs d ON d.id = b.doc WHERE b.kind='q'").fetchall()
    have = {}
    for r in rows:
        q = json.loads(r["data"])
        if q.get("ans") and q.get("how") in ("资料给出", "题库", "补充解答"):
            k = docq._key(q["stem"])
            if len(k) >= 12:
                have.setdefault(k[:30], []).append((k, q, r["doc"], clean_title(r["title"])))
    upd = []
    for r in rows:
        q = json.loads(r["data"])
        if q.get("ans") and q.get("how") != "软件计算":
            continue
        k = docq._key(q["stem"])
        if len(k) < 12:
            continue
        for k2, other, doc, title in have.get(k[:30], []):
            if doc == r["doc"] or not (k2.startswith(k[:40]) or k.startswith(k2[:40])):
                continue
            mine = [o for _a, o in q["opts"]]
            if not docq._same_opts(q["opts"], [o for _a, o in other["opts"]]) or len(mine) != len(other["opts"]):
                continue
            ans = "".join(sorted(docq.same_option(q["opts"], o2) for a2, o2 in other["opts"] if a2 in other["ans"]))
            if len(ans) != len(other["ans"]):
                continue
            q.update(ans=ans, how="其他资料", exp=other.get("exp") or [], bank={"src": title})
            upd.append((json.dumps(q, ensure_ascii=False), r["doc"], r["seq"]))
            break
    if upd:
        with _lock, conn:
            conn.executemany("UPDATE blocks SET data=? WHERE doc=? AND seq=?", upd)
    return len(upd)


def _shingles(conn, doc_id):
    """内容指纹：取文字里的 8 字片段，按哈希抽样（和排版、分页无关，同一份内容不同版式抽到的片段一样）。"""
    import zlib
    text = "".join(r[0] or "" for r in conn.execute(
        "SELECT text FROM blocks WHERE doc=? AND kind != 'img' ORDER BY seq", (doc_id,)))
    text = re.sub(r"[^\u4e00-\u9fff]", "", text)
    out = set()
    for i in range(len(text) - 8):
        g = text[i:i + 8]
        h = zlib.crc32(g.encode("utf-8"))
        if h % 16 == 0:
            out.add(h)
    return out, len(text)


def find_duplicates(conn):
    """内容几乎一样的资料（同一本书的横版 / 竖版、换了名字放在两个文件夹里）只显示一份：
    留目录更完整、可作答例题更多的那份，其余记进 doc_dups。"""
    rows = [dict(r) for r in conn.execute("SELECT id, title, toc, chars FROM docs WHERE chars > 500 AND (error IS NULL OR error = '')")]
    nq = dict(conn.execute("SELECT doc, COUNT(*) FROM blocks WHERE kind='q' GROUP BY doc").fetchall())
    sig = {r["id"]: _shingles(conn, r["id"]) for r in rows}
    score = {r["id"]: (len(json.loads(r["toc"] or "[]")) + 3 * nq.get(r["id"], 0), r["chars"]) for r in rows}
    ids = sorted(sig, key=lambda i: sig[i][1])
    dup = {}
    for i, a in enumerate(ids):
        sa, na = sig[a]
        if len(sa) < 20:
            continue
        for b in ids[i + 1:]:
            sb, nb = sig[b]
            if nb > na * 1.12:
                break
            if len(sa & sb) >= 0.9 * min(len(sa), len(sb)):
                keep, drop = (a, b) if score[a] >= score[b] else (b, a)
                while keep in dup:
                    keep = dup[keep]
                if keep != drop:
                    dup[drop] = keep
    with _lock, conn:
        conn.execute("DELETE FROM doc_dups")
        conn.executemany("INSERT OR REPLACE INTO doc_dups(doc, keep) VALUES (?, ?)", list(dup.items()))
    return dup


# ---------------------------------------------------------------- 读取

def doc_list():
    if not DB_PATH.exists():
        return []
    conn = connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, title, cat, subj, rel, ext, pages, chars, nblocks, toc, scanned, error FROM docs "
        "WHERE id NOT IN (SELECT doc FROM doc_dups) ORDER BY rel")]
    nq = dict(conn.execute("SELECT doc, COUNT(*) FROM blocks WHERE kind='q' GROUP BY doc").fetchall())
    conn.close()
    for r in rows:
        toc = json.loads(r.pop("toc") or "[]")
        r["toc_n"] = len(toc)
        r["subj"] = [s for s in (r["subj"] or "").split(",") if s]
        r["nq"] = nq.get(r["id"], 0)
        r["grp"], r["sub"] = classify(r)
        r["title"] = clean_title(r["title"])
    return rows


def clean_title(t):
    """去掉标题里的店铺广告、时间戳尾巴。"""
    t = re.sub(r"[（(][^（）()]*(淘宝|店铺|公众号|微信|小铺)[^（）()]*[）)]", "", t or "")
    t = re.sub(r"[_\-]\d{8,}$", "", t)
    return t.strip(" _-") or t


def doc_get(doc_id):
    conn = connect()
    d = conn.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not d:
        conn.close()
        return None
    d = dict(d)
    d["toc"] = json.loads(d["toc"] or "[]")
    d["subj"] = [s for s in (d["subj"] or "").split(",") if s]
    d["blocks"] = [[r["seq"], r["kind"], r["level"], r["text"], r["page"], json.loads(r["data"]) if r["data"] else None]
                   for r in conn.execute("SELECT * FROM blocks WHERE doc=? ORDER BY seq", (doc_id,))]
    conn.close()
    return d


def search(q, doc=None, limit=200):
    """全文搜索：三个字以上走全文索引；更短的逐条匹配。多个词用空格隔开，要求同一段里都有。"""
    terms = [t for t in (q or "").split() if t]
    if not terms or not DB_PATH.exists():
        return []
    conn = connect()
    hits = []
    longest = max(terms, key=len)
    if has_fts(conn) and len(longest) >= 3:
        sql = "SELECT doc, seq, text FROM blocks_fts WHERE blocks_fts MATCH ?"
        args = ['"' + longest.replace('"', '""') + '"']
        if doc:
            sql += " AND doc=?"
            args.append(doc)
        rows = conn.execute(sql + " LIMIT 2000", args).fetchall()
    else:
        sql = "SELECT doc, seq, text FROM blocks WHERE text LIKE ?"
        args = [f"%{longest}%"]
        if doc:
            sql += " AND doc=?"
            args.append(doc)
        rows = conn.execute(sql + " LIMIT 2000", args).fetchall()
    hidden = {r[0] for r in conn.execute("SELECT doc FROM doc_dups")}
    for r in rows:
        if r["doc"] in hidden and not doc:
            continue  # 内容重复、只显示另一份的资料
        text = r["text"] or ""
        if not all(t in text for t in terms):
            continue
        pos = text.find(terms[0])
        a = max(0, pos - 50)
        hits.append({"doc": r["doc"], "seq": r["seq"], "snippet": ("…" if a else "") + text[a: pos + 90]})
        if len(hits) >= limit:
            break
    conn.close()
    return hits


def outdated():
    """有按旧整理规则生成的文档（需要重新整理）。"""
    if not DB_PATH.exists():
        return False
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM docs WHERE version IS NULL OR version < ?", (VERSION,)).fetchone()[0]
    if not n:
        n = int(conn.execute("SELECT 1 FROM blocks WHERE instr(text, ?) > 0 LIMIT 1", (BAD_FONT_GLYPH,)).fetchone() is not None)
    conn.close()
    return n > 0


def status():
    if not DB_PATH.exists():
        return {"docs": 0, "pending": 0}
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM docs WHERE error IS NULL OR error=''").fetchone()[0]
    conn.close()
    return {"docs": n}


# ---------------------------------------------------------------- 分类（资料库首页用）

PROVINCES = ("北京 天津 上海 重庆 河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 海南 "
             "四川 贵州 云南 陕西 甘肃 青海 台湾 内蒙古 广西 西藏 宁夏 新疆 香港 澳门").split()
GROUPS = [
    ("行测", ["言语理解", "数量关系", "判断推理", "资料分析", "常识判断", "行测综合"]),
    ("申论", ["素材积累", "范文", "方法技巧"]),
    ("省情", []),
    ("面试", []),
    ("其他", []),
]
_KW = [
    ("言语理解", r"言语|成语|实词|词语|高频.{0,4}词|逻辑填空|片段阅读|语句|阅读理解"),
    ("数量关系", r"数量|数学运算|数推|行程|工程问题|排列组合"),
    ("判断推理", r"判断|图形|图推|类比|定义|逻辑判断|翻译推理|削弱|加强"),
    ("资料分析", r"资料分析|资分|增长率|速算|^资料|【资料】"),
    ("常识判断", r"常识|政治|法律|历史|地理|科技|人文|时政|经济|马克思|党史|宪法|民法"),
]


def classify(d):
    """一份资料只归一类，侧栏的数字和点开后的列表才对得上。返回 (大类, 小类)。
    先看标题，标题看不出来再看所在文件夹和资料目录里标的科目。"""
    title = d.get("title") or ""
    rel = d.get("rel") or ""
    subj = d.get("subj") or []
    if re.search(r"省情|区情|市情|省况|区况|省考.{0,4}时政", title + rel):
        prov = next((p for p in PROVINCES if p in title), "") or next((p for p in PROVINCES if p in rel), "")
        return "省情", prov or "综合"
    if "面试" in subj or "面试" in title:
        return "面试", ""
    full = [m for m in ("言语理解", "数量关系", "判断推理", "资料分析", "常识判断") if m in title]
    hits = full or [name for name, rx in _KW if re.search(rx, title)]
    shenlun_title = re.search(SHENLUN_RE, title)
    weak = not full and hits == ["常识判断"] and ("申论" in rel or "素材" in rel)  # 申论专题里的“科技创新”“数字经济”
    if "行测" not in title and ((shenlun_title and not hits) or weak):
        return "申论", _shenlun_sub(title, rel)
    if len(hits) == 1:
        return "行测", hits[0]
    if len(hits) > 1 or re.search(r"行测", title):
        return "行测", "行测综合"
    mods = [m for s_, m in (("言语", "言语理解"), ("数量", "数量关系"), ("判断", "判断推理"), ("资料", "资料分析"),
                            ("常识", "常识判断")) if s_ in subj]
    if subj == ["申论"] or (not mods and (re.search(r"申论", rel) or d.get("cat") == "申论素材")):
        return "申论", _shenlun_sub(title, rel)
    if len(mods) == 1:
        return "行测", mods[0]
    if mods or d.get("cat") in ("笔记讲义", "常识积累"):
        return "行测", "常识判断" if d.get("cat") == "常识积累" and not mods else "行测综合"
    return "其他", ""


SHENLUN_RE = (r"申论|范文|作文|金句|名言|名句|\d+句|颁奖词|感动中国|典故|规范表述|规范词|规范表达|热点|模板|公文|素材|"
              r"人物|论据|排比|段旨|会议|贺词|二十大|两会|全会|开头|结尾|对策|写作")


def _shenlun_sub(title, rel):
    if re.search(r"范文|作文.{0,4}\d+篇|押题.{0,6}\d+篇|时评|佳作|精读", title) and not re.search(r"模板|技巧|公式|方法", title):
        return "范文"
    if re.search(r"素材|金句|名言|名句|\d+句|人物|事例|典故|热点|颁奖词|感动中国|论据|排比|比喻|段旨|时政|事迹|讲话|贺词|"
                 r"会议|报告|二十大|两会|全会", title) \
            or (re.search(r"素材", rel) and not re.search(r"模板|技巧|格式|方法|笔记|精讲|思维导图|规范", title)):
        return "素材积累"
    return "方法技巧"
