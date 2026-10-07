"""路径工具：兼容源码运行和 PyInstaller 打包后的运行。"""

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME


def resource_dir() -> Path:
    """静态资源根目录（web/、content/ 所在目录）。打包后位于 PyInstaller 的临时解压目录。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def web_dir() -> Path:
    return resource_dir() / "web"


def content_dir() -> Path:
    return resource_dir() / "content"


def data_dir() -> Path:
    """用户数据目录：%APPDATA%/GongkaoPrep，保存学习记录、导入的题目和设置。"""
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy(path)
    return path


def _migrate_legacy(path: Path) -> None:
    """早期版本把数据放在项目下的 data/，第一次启动新版时搬过来（只复制，不删除原文件）。"""
    legacy = Path(__file__).resolve().parent.parent / "data"
    for name in ("app.db", "custom_questions.json"):
        src, dst = legacy / name, path / name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)
