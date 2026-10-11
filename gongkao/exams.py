"""考试包：每种考试（公考、软考·系统架构设计师……）是 content/exams/<id>/ 下的一个包，exam.json 是清单。

清单写这门考试的名字、科目和分值、侧栏菜单、页面路由、手机底栏、计时科目、自己的设置项（考试日期、资料文件夹……）。
以后加考试：复制一个包改 exam.json，需要专属页面就在 web/js/pages/<包>/ 下写，需要整理资料就在 gongkao/<包>/ 下写。

学习记录按考试分开：
- 公考（gongkao）用原来的 app.db 和 library\\，老数据原地不动；
- 其他考试的学习记录在 <数据目录>/exams/<id>/app.db，整理好的资料在 <数据目录>/exams/<id>/library\\。
  打开连接时把公考的 app.db 以 shared 的名义挂上（见 userdb.connect）：所有考试共用的表（设置、打卡、笔记本、
  AI 用量和对话）只在 app.db 里有，SQL 里不写库名也会落到 app.db；做题、错题、闪卡、计划、资料进度这些表
  两边都有，SQLite 先找当前库，所以落到这门考试自己的库。

当前考试跟着请求走：界面把选中的考试写进 Cookie（gk_exam），服务端每个请求开始时设进 contextvar
（没带 Cookie 的请求用上次在界面里选的考试）；同一台电脑的窗口和手机可以各看各的考试。
后台线程（整理资料、预热）没有请求，一律当作公考 —— 不能跟着“上次选的考试”走，否则公考的整理任务会读到
别的考试的设置；整理其他考试的资料时显式传 exam。
"""

import contextvars
import json
import logging
import threading

from .paths import content_dir, data_dir

log = logging.getLogger("gongkao.exams")

DEFAULT = "gongkao"
COOKIE = "gk_exam"

# 所有考试共用、只放在公考 app.db 里的表（其他考试的库里没有这些表）
SHARED_TABLES = ("settings", "checkins", "memo_books", "memo_items", "ai_usage", "chats")
# 所有考试共用的界面偏好（外观、阅读器、笔记本）；其余偏好（教程进度、刷题设置、草稿……）各考试分开
GLOBAL_PREFS = frozenset({
    "theme", "skin", "nav-collapsed", "reader-font", "reader-toc", "reader-tree-view",
    "memo-book", "memo-last-book", "memo-cover", "lessonMap",
})

_lock = threading.Lock()
_registry = None
_default = None
_current = contextvars.ContextVar("gongkao_exam", default=None)


def _load():
    global _registry
    with _lock:
        if _registry is not None:
            return _registry
        reg = {}
        root = content_dir() / "exams"
        for p in sorted(root.glob("*/exam.json")):
            try:
                ex = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning("考试包清单读不了：%s（%s）", p, e)
                continue
            ex.setdefault("id", p.parent.name)
            ex.setdefault("settings", {})
            reg[ex["id"]] = ex
        if DEFAULT not in reg:  # 清单丢了也要能用公考
            reg[DEFAULT] = {"id": DEFAULT, "name": "公考", "short": "公考", "settings": {}}
        _registry = reg
        return reg


def reload():
    """清单改了以后重新读（测试、开发用）。"""
    global _registry
    with _lock:
        _registry = None
    return _load()


def all_exams():
    return sorted(_load().values(), key=lambda e: (e.get("order", 99), e["id"]))


def get(exam_id=None):
    return _load().get(exam_id or current_id()) or _load()[DEFAULT]


def valid(exam_id):
    return bool(exam_id) and exam_id in _load()


# ---------------------------------------------------------------- 当前考试

def set_request(exam_id):
    """每个请求开始时调用：Cookie 里的考试（没带或不认识的，用上次在界面里选的考试）。"""
    _current.set(exam_id if valid(exam_id) else default_id())


def current_id():
    """这个请求在哪门考试；不在请求里（后台线程）就是公考。"""
    return _current.get() or DEFAULT


def is_default(exam_id=None):
    return (exam_id or current_id()) == DEFAULT


def default_id():
    """没带 Cookie 时用的考试：上次在界面里选的（存在公考 app.db 的 settings.last_exam），没有就是公考。"""
    global _default
    if _default is None:
        _default = DEFAULT
        try:
            from .dbutil import open_db

            path = data_dir() / "app.db"
            if path.exists():
                conn = open_db(path, timeout=5, wal=False)
                try:
                    row = conn.execute("SELECT value FROM settings WHERE key='last_exam'").fetchone()
                finally:
                    conn.close()
                if row and valid(row[0]):
                    _default = row[0]
        except Exception:  # noqa: BLE001 —— 表还没建好之类：用公考
            _default = DEFAULT
    return _default


def remember(conn, exam_id):
    """记住界面选的考试，下次打开（还没有 Cookie 时）默认进这门。conn 是任意考试的连接（settings 是共用表）。"""
    global _default
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('last_exam', ?)", (exam_id,))
    _default = exam_id


# ---------------------------------------------------------------- 路径

def data_root(exam_id=None):
    """这门考试的数据放在哪：公考是数据目录本身（老结构），其他考试是 exams/<id>/。"""
    ex = exam_id or current_id()
    return data_dir() if ex == DEFAULT else data_dir() / "exams" / ex


def library_dir(exam_id=None):
    return data_root(exam_id) / "library"


def app_db(exam_id=None):
    return data_root(exam_id) / "app.db"


def backup_dir(exam_id=None):
    return data_root(exam_id) / "backups"


def content_path(exam_id=None):
    """考试包自己的内置内容：content/exams/<id>/。"""
    return content_dir() / "exams" / (exam_id or current_id())


def exam_settings(exam_id=None):
    """这门考试自己的设置项和默认值（公考的设置都在共用的 settings 表里，这里是空的）。"""
    ex = exam_id or current_id()
    return {} if ex == DEFAULT else dict(get(ex).get("settings") or {})


def pack_decks(exam_id=None):
    """考试包的闪卡卡组：内置的 content/exams/<id>/cards/*.json + 整理资料生成的 library/decks.json。"""
    out = []
    files = sorted((content_path(exam_id) / "cards").glob("*.json"))
    gen = library_dir(exam_id) / "decks.json"
    for p in files + ([gen] if gen.exists() else []):
        try:
            out += json.loads(p.read_text(encoding="utf-8")).get("decks", [])
        except (OSError, ValueError) as e:
            log.warning("卡组文件读不了：%s（%s）", p, e)
    return out


def public(ex):
    """给界面的清单（去掉只在服务端用的字段）。"""
    return {k: v for k, v in ex.items() if not k.startswith("_")}
