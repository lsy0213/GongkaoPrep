"""上岸备考 启动入口。

    python main.py            # 正常启动（桌面窗口）
    python main.py --debug    # 开启开发者工具（右键 → 检查）
    python main.py --browser  # 不开窗口，用系统浏览器打开（没装 pywebview 时也会自动这样做）
    python main.py --serve    # 只启动数据服务，供开发时在浏览器里调试界面
"""

import json
import os
import sys
import time
import urllib.request
import webbrowser

# 打包成无控制台的 exe 时 sys.stdout / sys.stderr 是 None，任何日志输出都会抛异常（接口请求会直接断开）
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from gongkao import APP_TITLE  # noqa: E402
from gongkao.paths import data_dir, resource_dir  # noqa: E402
from gongkao.server import PREFERRED_PORT, start_server  # noqa: E402


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


def already_running():
    """固定端口上已经有一个上岸备考在运行（同一个数据目录只能开一个窗口）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PREFERRED_PORT}/api/ping", timeout=1) as r:
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
    if already_running():
        notify("上岸备考已经打开了，请在任务栏里找到它的窗口。")
        return
    port = start_server()
    url = f"http://127.0.0.1:{port}/"
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
    icon = resource_dir() / "assets" / "icon.ico"
    webview.start(
        debug="--debug" in sys.argv,
        private_mode=False,
        storage_path=str(data_dir() / "webview"),
        icon=str(icon) if icon.exists() else None,
    )


if __name__ == "__main__":
    main()
