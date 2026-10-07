"""日志：写到数据目录的 logs/app.log（滚动保存，最多 5 份 × 1 MB）。

打包成无控制台的 exe 后看不到任何输出，出问题全靠这份日志；未捕获的异常（主线程、后台线程）也记进去。
"""

import logging
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import VERSION
from .paths import data_dir

LOG_DIR = data_dir() / "logs"
LOG_FILE = LOG_DIR / "app.log"
_done = False


def setup(debug=False):
    global _done
    if _done:
        return
    _done = True
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=1 << 20, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr and getattr(sys.stderr, "isatty", lambda: False)() or debug:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        root.addHandler(sh)

    def excepthook(tp, value, tb):
        logging.getLogger("gongkao").critical("未捕获的异常", exc_info=(tp, value, tb))
        sys.__excepthook__(tp, value, tb)

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        logging.getLogger("gongkao").error("后台线程 %s 出错", args.thread.name if args.thread else "?",
                                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    logging.getLogger("gongkao").info("启动 上岸备考 %s，Python %s，%s，数据目录 %s",
                                      VERSION, platform.python_version(), platform.platform(), data_dir())


def tail(n=400):
    """日志最后 n 行（诊断信息用）。"""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]
