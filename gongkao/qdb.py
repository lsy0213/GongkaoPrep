"""题库数据库：真题卷、题册（千题册）的题目都存进 library/questions.db（SQLite）。

界面不再一次拿到全部题目，而是：
- /api/bank/summary 看各模块有多少题、做过多少；
- /api/bank/pick 按条件让服务器选出题目 id；
- /api/bank/get 按 id 取题目详情（含材料、出处）。
内置题和用户导入的题量很小，仍然放在内存里，和数据库里的题合在一起查。
"""

import json
import random
import threading

from .dbutil import open_db, stamp
from .paths import data_dir

DB_PATH = data_dir() / "library" / "questions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, exam TEXT, year INTEGER, level TEXT,
    module TEXT, sub TEXT, file TEXT, fid TEXT, answer_file TEXT, answer_fid TEXT,
    count INTEGER, answered INTEGER, modules TEXT, note TEXT, sort INTEGER);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, source TEXT, kind TEXT, num INTEGER, seq INTEGER, module TEXT, sub TEXT,
    stem TEXT, options TEXT, answer INTEGER, explain TEXT, material TEXT, crop TEXT, explain_crop TEXT,
    fig INTEGER, year INTEGER, origin TEXT, src TEXT, fid TEXT);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY, source TEXT, kind TEXT, title TEXT, text TEXT, crop TEXT, fig INTEGER, fid TEXT);
CREATE INDEX IF NOT EXISTS q_source ON questions(source);
CREATE INDEX IF NOT EXISTS q_kind ON questions(kind);
"""

_lock = threading.Lock()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def replace_kind(kind, sources, questions, materials):
    """整体替换某一类（paper=真题卷，book=题册）的数据。"""
    with _lock:
        conn = connect()
        with conn:
            for t in ("sources", "questions", "materials"):
                conn.execute(f"DELETE FROM {t} WHERE kind=?", (kind,))
            for i, s in enumerate(sources):
                conn.execute(
                    "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s["id"], kind, s.get("title", ""), s.get("exam", ""), s.get("year", 0), s.get("level", ""),
                     s.get("module", ""), s.get("sub", ""), s.get("file", ""), s.get("fid", ""),
                     s.get("answer_file", ""), s.get("answer_fid", ""), s.get("count", 0), s.get("answered", 0),
                     json.dumps(s.get("modules") or {}, ensure_ascii=False), s.get("note", ""), i),
                )
            for i, q in enumerate(questions):
                conn.execute(
                    "INSERT OR REPLACE INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (q["id"], q["source"], kind, q.get("num", 0), i, q["module"], q.get("sub") or "",
                     q.get("stem", ""), json.dumps(q.get("options"), ensure_ascii=False) if q.get("options") else None,
                     q.get("answer"), q.get("explain", ""), q.get("material"),
                     json.dumps(q.get("crop") or [], ensure_ascii=False),
                     json.dumps(q.get("explain_crop") or [], ensure_ascii=False),
                     1 if q.get("fig") else 0, q.get("year", 0), q.get("origin", ""), q.get("src", ""), q.get("fid", "")),
                )
            for m in materials:
                conn.execute(
                    "INSERT OR REPLACE INTO materials VALUES (?,?,?,?,?,?,?,?)",
                    (m["id"], m["source"], kind, m.get("title", ""), m.get("text", ""),
                     json.dumps(m.get("crop") or [], ensure_ascii=False), 1 if m.get("fig") else 0, m.get("fid", "")),
                )
        conn.close()


def replace_series(kind, prefixes, sources, questions, materials):
    """只替换某一套书（id 以 prefixes = (题源前缀, 题目前缀, 材料前缀) 开头）的数据，同类的其他书不动。"""
    with _lock:
        conn = connect()
        with conn:
            for t, p in zip(("sources", "questions", "materials"), prefixes):
                conn.execute(f"DELETE FROM {t} WHERE kind=? AND id LIKE ?", (kind, p + "%"))
            seq0 = (conn.execute("SELECT MAX(seq) FROM questions").fetchone()[0] or 0) + 1
            sort0 = (conn.execute("SELECT MAX(sort) FROM sources").fetchone()[0] or 0) + 1
        conn.close()
    # 复用 replace_kind 的插入逻辑：先插到临时种类，再改成目标种类并接在已有题目后面
    tmp = kind + "-tmp"
    replace_kind(tmp, sources, questions, materials)
    with _lock:
        conn = connect()
        with conn:
            conn.execute("UPDATE questions SET kind=?, seq=seq+? WHERE kind=?", (kind, seq0, tmp))
            conn.execute("UPDATE sources SET kind=?, sort=sort+? WHERE kind=?", (kind, sort0, tmp))
            conn.execute("UPDATE materials SET kind=? WHERE kind=?", (kind, tmp))
        conn.close()


def _row_q(r):
    q = dict(r)
    q["options"] = json.loads(q["options"]) if q["options"] else None
    q["crop"] = json.loads(q["crop"] or "[]")
    q["explain_crop"] = json.loads(q["explain_crop"] or "[]")
    q["fig"] = bool(q["fig"])
    q["real"] = True
    q.pop("seq", None)
    return q


def _row_s(r):
    s = dict(r)
    s["modules"] = json.loads(s["modules"] or "{}")
    return s


class Bank:
    """内置/导入题（内存）+ 数据库题的统一入口。索引只放选题需要的几列，近十万题也很轻。"""

    def __init__(self, load_builtin):
        self.load_builtin = load_builtin  # () -> {"questions": [...], "materials": [...], "custom_count": n}
        self.key = None
        self.index = []      # [(id, module, sub, src, year, source, material, num)]
        self.mem = {}        # 内置/导入题 id -> 题
        self.mem_mats = {}
        self.sources = []
        self.custom_count = 0

    def _key(self, extra):
        return (stamp(DB_PATH), extra)

    def refresh(self, extra_key):
        key = self._key(extra_key)
        if key == self.key:
            return
        builtin = self.load_builtin()
        self.custom_count = builtin.get("custom_count", 0)
        self.mem = {}
        index = []
        for q in builtin["questions"]:
            q = dict(q)
            q["src"] = "导入" if q.get("custom") else "内置"
            q.setdefault("sub", "")
            self.mem[q["id"]] = q
            if q.get("answer") is not None:
                index.append((q["id"], q["module"], q["sub"], q["src"], 0, q["src"], q.get("material"), 0))
        self.mem_mats = {m["id"]: m for m in builtin["materials"]}
        self.sources = []
        if DB_PATH.exists():
            conn = connect()
            for r in conn.execute("SELECT id, module, sub, src, year, source, material, num FROM questions "
                                  "WHERE answer IS NOT NULL ORDER BY kind DESC, seq"):
                index.append(tuple(r))
            self.sources = [_row_s(r) for r in conn.execute("SELECT * FROM sources ORDER BY kind DESC, sort")]
            conn.close()
        self.index = index
        self.key = key

    # ---- 统计
    def filtered(self, f):
        src, years, module, sub, source = (f.get("src") or "all", f.get("years") or "all", f.get("module") or "全部",
                                           f.get("sub") or "全部", f.get("source") or "")
        max_year = max((r[4] for r in self.index if r[4]), default=0)
        out = []
        for r in self.index:
            if source and r[5] != source:
                continue
            if src == "builtin" and r[3] not in ("内置", "导入"):
                continue
            if src in ("国考", "四川", "千题册") and r[3] != src:
                continue
            if src == "real" and r[3] not in ("国考", "四川"):
                continue
            if years != "all" and r[4] and r[4] <= max_year - int(years):
                continue
            if module != "全部" and r[1] != module:
                continue
            if sub != "全部" and r[2] != sub:
                continue
            out.append(r)
        return out

    def counts(self):
        c = {"total": len(self.index), "内置": 0, "导入": 0, "国考": 0, "四川": 0, "千题册": 0}
        for r in self.index:
            c[r[3]] = c.get(r[3], 0) + 1
        return c

    # ---- 选题
    def pick(self, f, progress):
        """按出题方式选题，资料分析等共用材料的题保持成组。"""
        rows = self.filtered(f)
        order = f.get("order") or "new"
        count = int(f["count"]) if f.get("count") is not None else 15  # 0 = 不限
        done, wrong, favs = progress["done"], progress["wrong"], progress["favorites"]
        if order == "wrong":
            rows = [r for r in rows if r[0] in wrong]
        elif order == "fav":
            rows = [r for r in rows if r[0] in favs]
        if order == "seq":
            # 顺序做：从第一道没做过的题开始
            start = next((i for i, r in enumerate(rows) if r[0] not in done), 0)
            rows = rows[start:]
        elif order == "all":
            pass
        else:
            random.shuffle(rows)
            if order == "new":
                fresh = [r for r in rows if r[0] not in done]
                old = sorted((r for r in rows if r[0] in done), key=lambda r: done[r[0]])
                rows = fresh + old
        # 同一材料的题挨在一起
        by_mat = {}
        for r in self.index:
            if r[6]:
                by_mat.setdefault(r[6], []).append(r)
        allowed = {r[0] for r in rows}
        out, seen = [], set()
        for r in rows:
            if r[0] in seen:
                continue
            if count and len(out) >= count:
                break
            group = [x for x in by_mat.get(r[6], [r]) if x[0] in allowed] if r[6] else [r]
            for x in group:
                if x[0] not in seen:
                    seen.add(x[0])
                    out.append(x[0])
        return out

    # ---- 取题
    def get(self, ids):
        qs, mats, srcs = {}, {}, {}
        db_ids = []
        for i in ids:
            if i in self.mem:
                q = self.mem[i]
                qs[i] = q
                if q.get("material") and q["material"] in self.mem_mats:
                    mats[q["material"]] = self.mem_mats[q["material"]]
            else:
                db_ids.append(i)
        if db_ids and DB_PATH.exists():
            conn = connect()
            for k in range(0, len(db_ids), 500):
                chunk = db_ids[k:k + 500]
                for r in conn.execute(f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                    qs[r["id"]] = _row_q(r)
            mids = {q["material"] for q in qs.values() if q.get("material") and q["material"] not in mats}
            if mids:
                ml = list(mids)
                for r in conn.execute(f"SELECT * FROM materials WHERE id IN ({','.join('?' * len(ml))})", ml):
                    m = dict(r)
                    m["crop"] = json.loads(m["crop"] or "[]")
                    m["fig"] = bool(m["fig"])
                    mats[m["id"]] = m
            sids = list({q.get("source") for q in qs.values() if q.get("source")})
            if sids:
                for r in conn.execute(f"SELECT * FROM sources WHERE id IN ({','.join('?' * len(sids))})", sids):
                    srcs[r["id"]] = _row_s(r)
            conn.close()
        return {"questions": [qs[i] for i in ids if i in qs], "materials": list(mats.values()), "sources": srcs}

    def source_rows(self, source_id):
        return [r for r in self.index if r[5] == source_id]
