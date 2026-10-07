"""数据目录：位置（可以搬到别的盘）、各部分占用的空间、清理可以重新生成的缓存、压缩数据库。"""

import os
import shutil
import sqlite3
from pathlib import Path

from .. import library, paths, userdb
from ..dbutil import open_db
from . import route

# (键, 名称, 相对数据目录的路径, 说明, 能否清理)
PARTS = [
    ("app", "学习记录", "app.db", "做题、错题、笔记、设置等，最重要", False),
    ("backups", "自动备份", "backups", "每天一份，保留 7 天；导入、恢复前的快照", False),
    ("recordings", "面试录音", "recordings", "面试练习的录音", False),
    ("positions", "职位表", "positions.db", "导入的国考 / 省考职位表", False),
    ("docs", "资料库文档", "library/docs.db", "讲义、笔记整理成的文字", False),
    ("shizheng", "时政晨读", "library/shizheng.db", "时政合集整理成的文字", False),
    ("questions", "真题题库", "library/questions.db", "真题卷、千题册", False),
    ("fulltext", "全文索引", "library/fulltext.db", "资料全文搜索", False),
    ("ocr", "文字识别缓存", "library/ocr", "扫描件识别结果；删了重新整理要再识别几个小时，不建议清理", False),
    ("pages", "题册版面缓存", "library/pages", "千题册表格和识别结果", False),
    ("docimg", "资料插图", "library/docimg", "资料库里的统计图、插图", False),
    ("cache", "截图缓存", "library/cache", "原卷题目截图，用到时会自动重新生成", True),
    ("convert", "Word 转换缓存", "library/convert", ".doc 转成的 .docx，需要时会重新转换", True),
    ("webview", "窗口缓存", "webview", "界面浏览器内核的缓存", False),
    ("logs", "日志", "logs", "出错时帮助排查问题", True),
]


_size_cache = {}  # 目录 → (时间, 大小)：几万个缓存文件逐个统计要好几秒，5 分钟内复用


def _size(p: Path):
    import time

    if p.is_dir():
        hit = _size_cache.get(str(p))
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        n = userdb.disk_usage(p)
        _size_cache[str(p)] = (time.time(), n)
        return n
    if p.is_file():
        total = p.stat().st_size
        for extra in ("-wal", "-shm"):
            q = Path(str(p) + extra)
            if q.exists():
                total += q.stat().st_size
        return total
    if p.is_dir():
        return userdb.disk_usage(p)
    return 0


def _stale_files(base: Path):
    """以前整理资料时留下的旧版本备份（*.bak.db）和中断的临时文件，可以删除。"""
    out = []
    for pattern in ("library/*.bak.db", "library/*.tmp", "*.tmp", "library/*.db.tmp"):
        out += [p for p in base.glob(pattern) if p.is_file()]
    return out


@route("GET", "/api/storage")
def storage(ctx):
    base = paths.data_dir()
    parts = [{"key": k, "name": n, "path": str(base / rel), "size": _size(base / rel), "desc": d, "clean": c}
             for k, n, rel, d, c in PARTS]
    stale = _stale_files(base)
    total = _size(base)
    try:
        free = shutil.disk_usage(base).free
    except OSError:
        free = 0
    loc = paths.read_location()
    return {
        "dir": str(base), "default_dir": str(paths.home_dir()), "env_override": bool(os.environ.get("GONGKAO_DATA_DIR")),
        "pending_move": loc.get("pending_move", ""), "move_error": loc.get("move_error", ""),
        "total": total, "free": free, "parts": parts,
        "stale": [{"name": p.name, "size": p.stat().st_size} for p in stale],
        "stale_size": sum(p.stat().st_size for p in stale),
    }


def warm_up():
    """启动后在后台先把空间统计、网卡地址算好，打开设置页时不用等。"""
    from .. import lan

    for _k, _n, rel, _d, _c in PARTS:
        _size(paths.data_dir() / rel)
    _size(paths.data_dir())
    lan.candidate_ips()


@route("POST", "/api/storage/clean", write=False)
def storage_clean(ctx):
    _size_cache.clear()
    what = ctx.body.get("what")
    base = paths.data_dir()
    freed = 0
    if what == "stale":
        for p in _stale_files(base):
            freed += p.stat().st_size
            p.unlink()
    else:
        part = next((x for x in PARTS if x[0] == what and x[4]), None)
        if not part:
            raise ValueError("这一项不能清理")
        target = base / part[2]
        freed = _size(target)
        if what == "logs":
            from .. import logs

            for p in logs.LOG_DIR.glob("app.log.*"):  # 当前正在写的 app.log 保留
                p.unlink(missing_ok=True)
            freed -= _size(logs.LOG_DIR)
        elif target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "freed": max(0, freed)}


def _vacuum(job):
    """压缩各个数据库，回收删除内容后留下的空闲页。"""
    base = paths.data_dir()
    dbs = [base / "app.db"] + [base / "library" / n for n in ("questions.db", "docs.db", "shizheng.db", "fulltext.db")]
    dbs = [p for p in dbs if p.exists()]
    for i, p in enumerate(dbs):
        job.progress("压缩数据库", i, len(dbs), p.name)
        conn = open_db(p, timeout=60)
        try:
            if p.name == "app.db":
                with userdb.write_lock:
                    conn.execute("VACUUM")
            else:
                conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass  # 正被整理任务占用：跳过，下次再压缩
        finally:
            conn.close()
    _size_cache.clear()
    job.progress("压缩数据库", len(dbs), len(dbs), "完成")


@route("POST", "/api/storage/vacuum", write=False)
def storage_vacuum(ctx):
    started = library.jobs.start("压缩数据库", _vacuum)
    return {"ok": True, "queued": started == "queued"} if started else {"error": "已经在压缩了"}


@route("GET", "/api/lan/status")
def lan_status(ctx):
    from .. import lan

    st = lan.status()
    st["autostart"] = (ctx.conn.execute("SELECT value FROM settings WHERE key='lan_autostart'").fetchone() or ["0"])[0] == "1"
    st["candidates"] = lan.candidate_ips()
    if st["running"]:
        st["qr"] = lan.qr_svg(st["url"])
    return st


@route("POST", "/api/lan/start", write=True)
def lan_start(ctx):
    from .. import lan
    from ..server import Handler

    ip = (ctx.body.get("ip") or "").strip()
    if ip and ip not in lan.candidate_ips():
        raise ValueError("这个地址不是本机的局域网地址")
    lan.start(Handler, ip=ip)
    ctx.conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('lan_autostart', ?)",
                     ("1" if ctx.body.get("autostart") else "0",))
    ctx.conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('lan_ip', ?)", (ip,))
    return lan_status(ctx)


@route("POST", "/api/lan/stop", write=True)
def lan_stop(ctx):
    from .. import lan

    lan.stop()
    ctx.conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('lan_autostart', '0')")
    return lan_status(ctx)


@route("POST", "/api/lan/reset", write=False)
def lan_reset(ctx):
    from .. import lan

    lan.reset_token()
    return lan_status(ctx)


@route("POST", "/api/datadir/move", write=False)
def datadir_move(ctx):
    """登记“下次启动时把数据搬到新位置”。搬移在启动时、打开任何数据库之前进行（运行中文件被占用，搬不了）。"""
    if os.environ.get("GONGKAO_DATA_DIR"):
        raise ValueError("当前用环境变量 GONGKAO_DATA_DIR 指定了数据目录，不能在这里修改")
    target = (ctx.body.get("target") or "").strip().strip('"')
    if ctx.body.get("cancel"):
        loc = paths.read_location()
        loc.pop("pending_move", None)
        loc.pop("move_error", None)
        paths.write_location(loc)
        return {"ok": True}
    if not target:
        raise ValueError("请选择新的数据文件夹")
    dst = Path(target)
    if not dst.is_absolute():
        raise ValueError("请填写完整路径，例如 E:\\AppData\\GongkaoPrep")
    cur = paths.data_dir().resolve()
    try:
        dst_r = dst.resolve()
    except OSError as e:
        raise ValueError(f"路径不可用：{e}") from e
    if dst_r == cur:
        raise ValueError("这就是现在的数据位置")
    if cur in dst_r.parents or dst_r in cur.parents:
        raise ValueError("新位置不能在现在的数据目录里面，也不能是它的上级目录")
    try:
        dst.mkdir(parents=True, exist_ok=True)
        probe = dst / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"无法写入这个文件夹：{e}") from e
    if (dst / "app.db").exists():
        raise ValueError("这个文件夹里已经有一份学习数据，为避免覆盖，请换一个空文件夹")
    need = userdb.disk_usage(cur)
    free = shutil.disk_usage(dst).free
    if free < need * 1.1:
        raise ValueError(f"目标盘空间不够：需要约 {need / 2**30:.1f} GB，只剩 {free / 2**30:.1f} GB")
    loc = paths.read_location()
    loc.update({"data_dir": str(cur), "pending_move": str(dst)})
    loc.pop("move_error", None)
    paths.write_location(loc)
    return {"ok": True, "need": need}
