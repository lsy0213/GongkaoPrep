"""学习记录数据库 app.db：连接、表结构版本迁移、自动备份与恢复、导出导入。

表结构用 PRAGMA user_version 记版本，MIGRATIONS 按顺序执行没跑过的步骤；
以后要加表、加列、加索引，就在末尾追加一步，老用户的库升级时自动补上。
"""

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from . import VERSION, library, secret
from .dbutil import open_db
from .paths import data_dir

DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "app.db"
BACKUP_DIR = DATA_DIR / "backups"
DAILY_KEEP = 7       # 每天自动备份，保留最近 7 份
SNAPSHOT_KEEP = 10   # 导入、恢复前的快照，保留最近 10 份

# 写操作串行：SQLite 同一时间只有一个写事务，先在 Python 这边排队，避免“读了再写”时撞上别的写入
write_lock = threading.RLock()

DEFAULT_SETTINGS = {
    "guokao_date": "2026-11-29",
    "shengkao_date": "2027-03-13",
    "start_date": "",
    "daily_hours": "4",
    "paper_level": "地市级",
    "nickname": "",
    "ai_provider": "",  # 空 = 老版本升级上来，按有没有 Key 推断（见 ai.config）
    "ai_model": "",
    "ai_base_url": "",
    "ai_api_key": "",
    # 资料文件夹：真题、讲义、题册放在这里，软件只读取不修改
    "library_root": library.DEFAULT_ROOT if os.path.isdir(library.DEFAULT_ROOT) else "",
    # 复习（FSRS）：期望记忆率、每天新卡上限、每天复习上限、错题间隔到多少天算掌握
    "review_retention": "0.9",
    "new_cards_per_day": "30",
    "review_cap": "300",
    "wrong_master_days": "30",
    # 行测目标分（估分走势图上画一条线）
    "target_score": "70",
    # AI 用量：每月 token 上限（0 = 不限）；单价（元 / 百万 tokens，按服务商价目表自己填，空 = 不估算费用）
    "ai_monthly_tokens": "0",
    "ai_price_in": "",
    "ai_price_out": "",
    # 面试录音转文字（可选，需要 faster-whisper）：模型名（如 small）或本机模型文件夹
    "asr_model": "",
}

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, title TEXT, total INTEGER,
    correct INTEGER, duration INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, qid TEXT, module TEXT,
    chosen INTEGER, correct INTEGER, seconds INTEGER, mode TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS wrongbook (
    qid TEXT PRIMARY KEY, module TEXT, wrong_count INTEGER DEFAULT 0,
    last_wrong_at TEXT, stage INTEGER DEFAULT 0, next_review TEXT,
    mastered INTEGER DEFAULT 0, reason TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS favorites (qid TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE IF NOT EXISTS qnotes (qid TEXT PRIMARY KEY, text TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, title TEXT, module TEXT,
    link TEXT, minutes INTEGER DEFAULT 0, done INTEGER DEFAULT 0, source TEXT);
CREATE TABLE IF NOT EXISTS checkins (day TEXT PRIMARY KEY, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS study_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, module TEXT, minutes INTEGER,
    source TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS essays (
    id INTEGER PRIMARY KEY AUTOINCREMENT, set_id TEXT, q_index INTEGER, answer TEXT,
    words INTEGER, seconds INTEGER, self_score REAL, checked TEXT, ai_feedback TEXT,
    created_at TEXT);
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, qid TEXT, answer TEXT, seconds INTEGER,
    ai_feedback TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, content TEXT,
    tags TEXT, source TEXT, created_at TEXT, box INTEGER DEFAULT 1, due TEXT);
CREATE TABLE IF NOT EXISTS cards (
    card_id TEXT PRIMARY KEY, deck TEXT, box INTEGER DEFAULT 1, due TEXT,
    reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS speed_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, total INTEGER, correct INTEGER,
    seconds INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS reading_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, title TEXT, source TEXT,
    summary TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS lib_progress (
    fid TEXT PRIMARY KEY, rel TEXT, page INTEGER DEFAULT 0, done INTEGER DEFAULT 0, fav INTEGER DEFAULT 0,
    note TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS doc_progress (
    doc TEXT PRIMARY KEY, seq INTEGER DEFAULT 0, pct REAL DEFAULT 0, done INTEGER DEFAULT 0,
    fav INTEGER DEFAULT 0, opened_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS doc_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT, seq INTEGER, start INTEGER, end_seq INTEGER,
    end INTEGER, text TEXT, color TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS doc_quiz (
    doc TEXT, qkey TEXT, choice TEXT, correct INTEGER, created_at TEXT, PRIMARY KEY (doc, qkey));
CREATE TABLE IF NOT EXISTS memo_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, sort INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS memo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, book INTEGER, title TEXT DEFAULT '', content TEXT,
    note TEXT DEFAULT '', source TEXT DEFAULT '', doc TEXT DEFAULT '', seq INTEGER,
    star INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
"""

SCHEMA_V2_INDEXES = """
CREATE INDEX IF NOT EXISTS attempts_created ON attempts(created_at);
CREATE INDEX IF NOT EXISTS attempts_qid ON attempts(qid);
CREATE INDEX IF NOT EXISTS study_logs_day ON study_logs(day);
CREATE INDEX IF NOT EXISTS wrongbook_review ON wrongbook(mastered, next_review);
CREATE INDEX IF NOT EXISTS cards_due ON cards(due);
CREATE INDEX IF NOT EXISTS doc_marks_doc ON doc_marks(doc);
"""


def _add_columns(conn, table, cols):
    """给老表补列（已有就跳过）。cols: [(列名, 类型和默认值)]"""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in cols:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _v3_fsrs(conn):
    """闪卡、错题本改用 FSRS：记忆稳定性、难度、上次复习日；老数据在第一次复习时按原来的盒子/阶段折算。"""
    _add_columns(conn, "cards", [("stability", "REAL"), ("difficulty", "REAL"), ("last_review", "TEXT"),
                                 ("first_review", "TEXT")])
    _add_columns(conn, "wrongbook", [("stability", "REAL"), ("difficulty", "REAL"), ("last_review", "TEXT"),
                                     ("reps", "INTEGER DEFAULT 0")])
    conn.execute("UPDATE cards SET first_review=substr(updated_at,1,10) WHERE first_review IS NULL")


def _v4_ai(conn):
    """AI 用量记录（看每月用了多少、设上限、估算费用）；申论批改的 AI 估分单独存一列，用来画走势。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ai_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, provider TEXT, model TEXT, kind TEXT,
        input_tokens INTEGER, output_tokens INTEGER, estimated INTEGER, created_at TEXT);
    CREATE INDEX IF NOT EXISTS ai_usage_day ON ai_usage(day);
    """)
    _add_columns(conn, "essays", [("ai_score", "REAL"), ("ai_full", "REAL")])


def _v5_interview_audio(conn):
    """面试练习的录音文件名、语音指标（时长、停顿、语速、口头禅）、语音转写的文字。"""
    _add_columns(conn, "interviews", [("audio", "TEXT DEFAULT ''"), ("metrics", "TEXT DEFAULT ''"),
                                      ("transcript", "TEXT DEFAULT ''")])


def _v6_qfixes(conn):
    """自己改过的题目（OCR 错字、答案错了）：存在学习记录里，重新整理资料也不会丢，取题时盖在原题上。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS qfixes (
        qid TEXT PRIMARY KEY, stem TEXT, options TEXT, answer INTEGER, explain TEXT, note TEXT, updated_at TEXT);
    """)


# (版本号, 说明, 执行函数)。只能往后追加，不要改已有的步骤。
MIGRATIONS = [
    (1, "初始表结构", lambda c: c.executescript(SCHEMA_V1)),
    (2, "统计、复习用的索引", lambda c: c.executescript(SCHEMA_V2_INDEXES)),
    (3, "闪卡、错题本改用 FSRS", _v3_fsrs),
    (4, "AI 用量记录、申论 AI 估分", _v4_ai),
    (5, "面试录音与语音指标", _v5_interview_audio),
    (6, "题目纠错", _v6_qfixes),
]


def migrate(conn):
    """执行还没跑过的迁移步骤，返回执行了的版本号列表。"""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    done = []
    for ver, _desc, step in MIGRATIONS:
        if ver <= current:
            continue
        step(conn)
        conn.execute(f"PRAGMA user_version={ver}")
        conn.commit()
        done.append(ver)
    return done


def schema_version():
    return MIGRATIONS[-1][0]


# ---------------------------------------------------------------- 连接

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return date.today()


def today_str():
    return today().isoformat()


def connect():
    return open_db(DB_PATH, timeout=15)


@contextmanager
def db():
    """打开连接，结束时提交（出错则回滚）并关闭。"""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fresh = not DB_PATH.exists()
    if not fresh:
        auto_backup()  # 升级表结构之前先备份
    conn = connect()
    try:
        migrate(conn)
    finally:
        conn.close()
    with db() as conn:
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        conn.execute("UPDATE settings SET value=? WHERE key='start_date' AND value=''", (today_str(),))
        # 老版本明文保存的 API Key：加密后存回
        row = conn.execute("SELECT value FROM settings WHERE key='ai_api_key'").fetchone()
        if row and row[0] and not secret.is_protected(row[0]):
            conn.execute("UPDATE settings SET value=? WHERE key='ai_api_key'", (secret.protect(row[0]),))


def get_settings(conn, include_secret=False):
    s = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    s["ai_api_key"] = secret.unprotect(s.get("ai_api_key") or "")
    s["app_version"] = VERSION
    if not include_secret:
        key = s.get("ai_api_key") or ""
        s["ai_api_key"] = ""  # 完整 Key 不回传给界面，只给一个掩码提示
        s["ai_key_saved"] = bool(key)
        s["ai_key_hint"] = f"{key[:3]}****{key[-4:]}" if len(key) > 8 else ("****" if key else "")
    return s


# ---------------------------------------------------------------- 备份与恢复

def backup_to(path):
    """用 SQLite 在线备份接口复制一份 app.db（包括还在 -wal 里没合并的写入），写到 path。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    src = sqlite3.connect(str(DB_PATH), timeout=15)
    dst = sqlite3.connect(str(tmp))
    try:
        with write_lock:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, path)
    return path


def _prune(prefix, keep):
    files = sorted(BACKUP_DIR.glob(prefix + "*.db"), key=lambda p: p.name, reverse=True)
    for p in files[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def auto_backup():
    """每天第一次启动时备份一次，保留最近 DAILY_KEEP 天。返回备份文件（今天已备份过返回 None）。"""
    if not DB_PATH.exists():
        return None
    target = BACKUP_DIR / f"daily-{today_str()}.db"
    if target.exists():
        return None
    try:
        backup_to(target)
    except (OSError, sqlite3.Error):
        return None
    _prune("daily-", DAILY_KEEP)
    return target


def snapshot(reason):
    """导入、恢复这类会覆盖数据的操作之前，先留一份快照。"""
    safe = "".join(ch for ch in reason if ch.isalnum())[:12] or "snapshot"
    target = BACKUP_DIR / f"snap-{datetime.now():%Y%m%d-%H%M%S}-{safe}.db"
    backup_to(target)
    _prune("snap-", SNAPSHOT_KEEP)
    return target


def list_backups():
    out = []
    for p in sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        kind = "每日自动" if p.name.startswith("daily-") else "操作前快照"
        out.append({"name": p.name, "kind": kind, "size": p.stat().st_size,
                    "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return out


def restore_backup(name):
    """用一份备份覆盖当前学习记录（先给当前数据留快照）。"""
    src_path = BACKUP_DIR / name
    if "/" in name or "\\" in name or not src_path.is_file():
        raise ValueError("找不到这份备份")
    snapshot("恢复前")
    src = sqlite3.connect(str(src_path))
    try:
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError("这份备份已损坏，不能用来恢复")
        with write_lock:
            dst = sqlite3.connect(str(DB_PATH), timeout=15)
            try:
                src.backup(dst)
            finally:
                dst.close()
    finally:
        src.close()
    conn = connect()
    try:
        migrate(conn)  # 旧备份的表结构补到最新
    finally:
        conn.close()
    return {"ok": True}


def backup_file_copy(dest_dir):
    """把一份完整的 app.db 拷到别的文件夹（迁移数据目录、手动备份用）。"""
    dest = Path(dest_dir) / f"GongkaoPrep-app-{datetime.now():%Y%m%d-%H%M%S}.db"
    return backup_to(dest)


# ---------------------------------------------------------------- 导出 / 导入（JSON）

# 导出/导入时包含的表
USER_TABLES = [
    "settings", "sessions", "attempts", "wrongbook", "favorites", "qnotes", "tasks",
    "checkins", "study_logs", "essays", "interviews", "notebook", "cards",
    "speed_records", "reading_logs", "chats", "prefs", "lib_progress", "doc_progress", "doc_marks",
    "doc_quiz", "memo_books", "memo_items", "ai_usage", "qfixes",
]


def export_all(conn):
    out = {"app": "gongkao-prep", "version": VERSION, "schema": schema_version(),
           "exported_at": now_str(), "tables": {}}
    for t in USER_TABLES:
        out["tables"][t] = rows(conn, f"SELECT * FROM {t}")
    for r in out["tables"]["settings"]:
        if r["key"] == "ai_api_key":
            r["value"] = ""  # 备份文件里不带密钥
    return out


def import_all(conn, data):
    if not isinstance(data, dict) or data.get("app") != "gongkao-prep" or not isinstance(data.get("tables"), dict):
        raise ValueError("这不是上岸备考导出的备份文件")
    tables = data["tables"]
    conn.commit()
    snap = snapshot("导入前")
    for t in USER_TABLES:
        if t not in tables:
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if t == "settings":
            for r in tables[t]:
                if r.get("key") == "ai_api_key":
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    (r.get("key"), r.get("value")),
                )
            continue
        conn.execute(f"DELETE FROM {t}")
        for r in tables[t]:
            keys = [k for k in r if k in cols]
            if not keys:
                continue
            conn.execute(
                f"INSERT INTO {t}({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                [r[k] for k in keys],
            )
    return {"ok": True, "snapshot": snap.name}


def disk_usage(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for n in files:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return total
