"""SQLite 公共设置：WAL 日志模式（读写互不阻塞：后台整理资料时界面照常读）、等锁超时。"""

import os
import sqlite3


def open_db(path, timeout=30, wal=True):
    conn = sqlite3.connect(str(path), timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    if wal:
        try:
            # WAL 是写在数据库文件里的持久设置，第一次切换后以后打开都是 WAL
            if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass  # 别的进程正占着库时切换不了，下次再切
    return conn


def stamp(path):
    """数据库内容的“版本戳”：WAL 模式下写入先进 -wal 文件，主文件修改时间要等检查点才变，所以两个都看。"""
    out = []
    for p in (str(path), str(path) + "-wal"):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)
