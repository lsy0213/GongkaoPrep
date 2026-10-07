"""选岗：导入国考 / 省考职位表（Excel），按自己的条件筛出能报的岗位，看招考人数和报录比。

职位表每年格式略有不同、各省也不一样：先在前几行里找“表头行”，再按别名把列对到统一的字段上，
原始的每一列都另外留着（详情里能看到全部内容）。报名人数表（职位代码 + 报名 / 过审人数）可以另外导入，用来算报录比。
"""

import io
import json
import re
import threading
import time

from .dbutil import open_db
from .paths import data_dir

DB_PATH = data_dir() / "positions.db"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, file TEXT, kind TEXT, imported_at TEXT, count INTEGER);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch INTEGER, code TEXT, dept TEXT, unit TEXT, title TEXT, level TEXT,
    region TEXT, count INTEGER, major TEXT, edu TEXT, degree TEXT, politics TEXT, years TEXT, project TEXT,
    notes TEXT, sheet TEXT, applicants INTEGER, raw TEXT);
CREATE INDEX IF NOT EXISTS positions_batch ON positions(batch);
CREATE INDEX IF NOT EXISTS positions_code ON positions(code);
"""

# 统一字段 → 职位表里可能的列名（按先后匹配；列名里去掉空白和换行后比较）
ALIASES = {
    "code": ["职位代码", "职位编码", "职位编号", "岗位代码", "岗位编码"],
    "dept": ["部门名称", "招录机关", "招考单位", "招录单位", "单位名称", "主管部门"],
    "unit": ["用人司局", "用人单位", "内设机构", "具体用人单位"],
    "title": ["招考职位", "职位名称", "岗位名称", "职位"],
    "level": ["机构层级", "职位层级", "单位层级"],
    "region": ["工作地点", "工作地区", "地区", "所在地"],
    "count": ["招考人数", "招录人数", "招录名额", "招考名额", "录用人数"],
    "major": ["专业", "专业条件", "专业要求", "所学专业"],
    "edu": ["学历", "学历要求", "学历（学位）", "学历(学位)"],
    "degree": ["学位", "学位要求"],
    "politics": ["政治面貌"],
    "years": ["基层工作最低年限", "工作经历", "基层工作经历", "工作年限"],
    "project": ["服务基层项目工作经历", "服务基层项目"],
    "notes": ["备注", "其他条件", "其它条件", "其他资格条件"],
}
APPLICANT_COLS = ["过审人数", "审核通过人数", "报名人数", "报考人数", "通过资格审查人数"]

EDU_LEVEL = {"大专": 1, "专科": 1, "本科": 2, "硕士": 3, "研究生": 3, "博士": 4}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def connect():
    conn = open_db(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_sheets(data, filename):
    """读 Excel 的所有工作表：返回 [(表名, [[单元格文本]])]。.xls 用 xlrd，.xlsx 用 openpyxl。"""
    name = filename.lower()
    if name.endswith(".xls"):
        import xlrd

        book = xlrd.open_workbook(file_contents=data)
        return [(sh.name, [[_cell(sh.cell_value(r, c)) for c in range(sh.ncols)] for r in range(sh.nrows)])
                for sh in book.sheets()]
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in book.worksheets:
            out.append((ws.title, [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]))
        book.close()
        return out
    raise ValueError("只支持 Excel 文件（.xls / .xlsx）")


def _header(rows):
    """在前 10 行里找表头行：认识的列名最多的那一行。返回 (行号, {字段: 列号}, 列名列表) 或 None。"""
    best = None
    for i, row in enumerate(rows[:10]):
        cells = [_norm(c) for c in row]
        cols = {}
        for field, names in ALIASES.items():
            for n in names:
                if n in cells:
                    cols[field] = cells.index(n)
                    break
            else:
                for j, c in enumerate(cells):  # 宽松：列名包含别名（如“招考人数（人）”）
                    if c and any(n in c for n in names) and j not in cols.values():
                        cols[field] = j
                        break
        if len(cols) >= 4 and (best is None or len(cols) > len(best[1])):
            best = (i, cols, cells)
    return best


def _int(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def parse_positions(data, filename):
    """解析职位表，返回岗位字典列表。"""
    out = []
    for sheet, rows in read_sheets(data, filename):
        h = _header(rows)
        if not h:
            continue
        hi, cols, names = h
        for row in rows[hi + 1:]:
            if not any(row):
                continue
            get = lambda f: row[cols[f]].strip() if f in cols and cols[f] < len(row) else ""  # noqa: E731
            if not (get("title") or get("dept")) or not (get("code") or get("count")):
                continue  # 合计行、说明行
            raw = {names[j]: v for j, v in enumerate(row) if j < len(names) and names[j] and v}
            out.append({
                "code": get("code"), "dept": get("dept"), "unit": get("unit"), "title": get("title"), "level": get("level"),
                "region": get("region"), "count": _int(get("count")) or 1, "major": get("major"), "edu": get("edu"),
                "degree": get("degree"), "politics": get("politics"), "years": get("years"), "project": get("project"),
                "notes": get("notes"), "sheet": sheet, "raw": raw,
            })
    if not out:
        raise ValueError("没有在这个文件里找到职位表（需要有“职位代码 / 招考职位 / 专业 / 学历”这类表头）")
    return out


def import_positions(data, filename, name=""):
    items = parse_positions(data, filename)
    with _lock:
        conn = connect()
        with conn:
            cur = conn.execute("INSERT INTO batches(name, file, kind, imported_at, count) VALUES (?, ?, 'positions', ?, ?)",
                               (name or re.sub(r"\.\w+$", "", filename), filename, time.strftime("%Y-%m-%d %H:%M:%S"), len(items)))
            bid = cur.lastrowid
            conn.executemany(
                "INSERT INTO positions(batch, code, dept, unit, title, level, region, count, major, edu, degree, politics, "
                "years, project, notes, sheet, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(bid, p["code"], p["dept"], p["unit"], p["title"], p["level"], p["region"], p["count"], p["major"], p["edu"],
                  p["degree"], p["politics"], p["years"], p["project"], p["notes"], p["sheet"],
                  json.dumps(p["raw"], ensure_ascii=False)) for p in items])
        conn.close()
    return {"batch": bid, "count": len(items)}


def import_applicants(data, filename, batch):
    """报名人数表：按职位代码把报名 / 过审人数挂到某次导入的岗位上。"""
    updates = {}
    for _sheet, rows in read_sheets(data, filename):
        for i, row in enumerate(rows[:10]):
            cells = [_norm(c) for c in row]
            ci = next((cells.index(n) for n in ALIASES["code"] if n in cells), None)
            ai = next((cells.index(n) for n in APPLICANT_COLS if n in cells), None)
            if ci is None or ai is None:
                continue
            for r in rows[i + 1:]:
                if ci < len(r) and ai < len(r) and r[ci].strip():
                    updates[r[ci].strip()] = _int(r[ai])
            break
    if not updates:
        raise ValueError("没有在这个文件里找到“职位代码”和“报名人数 / 过审人数”两列")
    with _lock:
        conn = connect()
        with conn:
            n = 0
            for code, num in updates.items():
                n += conn.execute("UPDATE positions SET applicants=? WHERE batch=? AND code=?", (num, batch, code)).rowcount
        conn.close()
    return {"matched": n, "rows": len(updates)}


# ---------------------------------------------------------------- 报考条件判断

def edu_ok(req, mine):
    """学历要求能不能报。req 如“本科及以上”“仅限硕士研究生”“本科或硕士研究生”；mine 如“本科”。"""
    req = req or ""
    mine_lv = EDU_LEVEL.get(next((k for k in EDU_LEVEL if k in (mine or "")), ""), 0)
    if not req or "不限" in req or not mine_lv:
        return True
    levels = sorted({lv for k, lv in EDU_LEVEL.items() if k in req})
    if not levels:
        return True
    if "仅限" in req:
        return mine_lv in levels
    if "以上" in req:
        return mine_lv >= min(levels)
    if "以下" in req:
        return mine_lv <= max(levels)
    return mine_lv in levels


def politics_ok(req, mine):
    req = req or ""
    if not req or "不限" in req:
        return True
    mine = mine or "群众"
    if "党员" in req and "团员" in req:
        return "党员" in mine or "团员" in mine
    if "党员" in req:
        return "党员" in mine
    if "团员" in req:
        return "团员" in mine
    return True


def years_required(req):
    req = req or ""
    if not req or "无限制" in req or "不限" in req or "无要求" in req:
        return 0
    m = re.search(r"(\d+)\s*年", req) or re.search(r"([一二两三四五六])\s*年", req)
    if not m:
        return 0
    return int(m.group(1)) if m.group(1).isdigit() else CN_NUM[m.group(1)]


def project_ok(req, has):
    req = req or ""
    if not req or "无限制" in req or "不限" in req:
        return True
    return bool(has)


def major_ok(req, keywords):
    """专业要求里出现了自己填的专业名、专业类或代码中的任意一个就算符合；“不限”都符合。"""
    req = req or ""
    if not req or re.search(r"不限|无限制", req):
        return True
    keys = [k.strip() for k in keywords if k and k.strip()]
    if not keys:
        return True  # 没填专业就不按专业筛
    return any(k in req for k in keys)


def eligible(p, prof):
    reasons = []
    if not edu_ok(p["edu"], prof.get("edu")):
        reasons.append("学历")
    if not politics_ok(p["politics"], prof.get("politics")):
        reasons.append("政治面貌")
    if years_required(p["years"]) > int(prof.get("years") or 0):
        reasons.append("基层年限")
    if not project_ok(p["project"], prof.get("project")):
        reasons.append("服务基层项目")
    if not major_ok(p["major"], prof.get("majors") or []):
        reasons.append("专业")
    return reasons


def search(f, prof):
    """按条件筛岗位，返回 {total, items(当前页), batches}。"""
    if not DB_PATH.exists():
        return {"total": 0, "items": [], "batches": []}
    conn = connect()
    try:
        batches = [dict(r) for r in conn.execute("SELECT * FROM batches ORDER BY id DESC")]
        bid = int(f.get("batch") or (batches[0]["id"] if batches else 0))
        sql, args = "SELECT * FROM positions WHERE batch=?", [bid]
        for kw in (f.get("q") or "").split():
            sql += " AND (dept LIKE ? OR unit LIKE ? OR title LIKE ? OR region LIKE ? OR code LIKE ? OR major LIKE ?)"
            args += [f"%{kw}%"] * 6
        if f.get("region"):
            sql += " AND region LIKE ?"
            args.append(f"%{f['region']}%")
        rows = [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()
    favs = set(f.get("favs") or [])
    out = []
    for p in rows:
        p["blocked"] = eligible(p, prof) if prof else []
        if f.get("mine") and p["blocked"]:
            continue
        if f.get("only_fav") and str(p["id"]) not in favs:
            continue
        p["ratio"] = round(p["applicants"] / p["count"], 1) if p.get("applicants") and p["count"] else None
        out.append(p)
    sort = f.get("sort") or ""
    if sort == "count":
        out.sort(key=lambda p: -p["count"])
    elif sort == "ratio":
        out.sort(key=lambda p: (p["ratio"] is None, p["ratio"] or 0))
    elif sort == "ratio_desc":
        out.sort(key=lambda p: -(p["ratio"] or 0))
    page, size = max(1, int(f.get("page") or 1)), 50
    items = out[(page - 1) * size: page * size]
    for p in items:
        p["raw"] = json.loads(p["raw"] or "{}")
    return {"total": len(out), "all": len(rows), "items": items, "batches": batches, "batch": bid, "page": page, "size": size}


def delete_batch(bid):
    with _lock:
        conn = connect()
        with conn:
            conn.execute("DELETE FROM positions WHERE batch=?", (bid,))
            conn.execute("DELETE FROM batches WHERE id=?", (bid,))
        conn.close()
