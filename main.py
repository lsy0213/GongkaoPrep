"""上岸备考 启动入口。

    python main.py            # 正常启动（桌面窗口）
    python main.py --debug    # 开启开发者工具（右键 → 检查），日志也打到控制台
    python main.py --browser  # 不开窗口，用系统浏览器打开（没装 pywebview 时也会自动这样做）
    python main.py --serve    # 只启动数据服务，供开发时在浏览器里调试界面
"""

import hashlib
import json
import logging
import os
import sys
import time
import urllib.request
import webbrowser

# 打包成无控制台的 exe 时 sys.stdout / sys.stderr 是 None，任何输出都会抛异常（接口请求会直接断开）
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115

from gongkao import APP_TITLE, paths  # noqa: E402

log = logging.getLogger("gongkao.main")
_mutex = None  # 进程活着就一直持有


class Api:
    """暴露给页面的少量桌面能力（window.pywebview.api.*）。"""

    def __init__(self):
        self._window = None

    def save_text(self, filename, text):
        """弹出“另存为”对话框保存文本，返回保存路径；取消返回空字符串。"""
        import webview

        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        result = self._window.create_file_dialog(kind, save_filename=filename)
        if not result:
            return ""
        path = result if isinstance(result, str) else result[0]
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def choose_folder(self):
        """弹出“选择文件夹”对话框，返回路径；取消返回空字符串。"""
        import webview

        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(kind)
        if not result:
            return ""
        return result if isinstance(result, str) else result[0]

    def choose_file(self, types=None):
        """弹出“打开文件”对话框（例如选职位表 Excel），返回路径；取消返回空字符串。"""
        import webview

        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        result = self._window.create_file_dialog(kind, file_types=tuple(types or ()))
        if not result:
            return ""
        return result if isinstance(result, str) else result[0]


def single_instance():
    """同一个数据目录只允许开一个窗口：Windows 命名互斥量，进程退出时系统自动释放。返回 True 表示可以继续启动。"""
    global _mutex
    if sys.platform != "win32":
        return True
    import ctypes

    key = hashlib.md5(str(paths.data_dir()).lower().encode("utf-8")).hexdigest()[:16]
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = kernel32.CreateMutexW(None, False, f"Local\\GongkaoPrep-{key}")
    ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def bring_to_front():
    """把已经打开的窗口调到最前面。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    except (AttributeError, OSError):
        pass
    return False


def already_running(port):
    """固定端口上已经有一个上岸备考在运行（--serve 开发模式下的补充检查）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:  # noqa: S310
            return json.load(r).get("app") == "gongkao-prep"
    except (OSError, ValueError):
        return False


def notify(text):
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, 0x40)
    except (AttributeError, OSError):
        print(text)


def run_in_browser(url, open_browser=True):
    print(f"{APP_TITLE} 已启动：{url}")
    print("关闭这个窗口即可退出。")
    if open_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main():
    debug = "--debug" in sys.argv
    # 1. 上次在设置里改了数据位置：趁还没打开任何数据库，先把数据搬过去
    move_error = paths.apply_pending_move()
    from gongkao import logs

    logs.setup(debug=debug)
    if move_error:
        notify("搬移数据目录没有成功，仍使用原来的位置。\n" + move_error)

    # --serve 是开发调试用的只读服务（可以和正在用的窗口同时开，端口不同），不占单实例锁
    if "--serve" not in sys.argv and not single_instance():
        if not bring_to_front():
            notify("上岸备考已经打开了，请在任务栏里找到它的窗口。")
        return

    from gongkao.server import PREFERRED_PORT, start_server

    if already_running(PREFERRED_PORT):
        notify("上岸备考已经打开了，请在任务栏里找到它的窗口。")
        return
    port = start_server()
    url = f"http://127.0.0.1:{port}/"
    log.info("本地服务：%s", url)
    if "--browser" in sys.argv or "--serve" in sys.argv:
        return run_in_browser(url, open_browser="--browser" in sys.argv)
    try:
        import webview
    except ImportError:
        print("没有安装 pywebview，改用浏览器打开。安装方法：pip install pywebview")
        return run_in_browser(url)

    api = Api()
    api._window = webview.create_window(
        APP_TITLE,
        url=url,
        js_api=api,
        width=1240,
        height=820,
        min_size=(960, 640),
        background_color="#ECE6DB",
        text_select=True,
    )
    icon = paths.resource_dir() / "assets" / "icon.ico"
    webview.start(
        debug=debug,
        private_mode=False,
        storage_path=str(paths.data_dir() / "webview"),
        icon=str(icon) if icon.exists() else None,
    )
    log.info("窗口已关闭，退出")


if __name__ == "__main__":
    main()
