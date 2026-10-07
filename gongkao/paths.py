"""路径工具：兼容源码运行和 PyInstaller 打包后的运行。

用户数据目录可以放在任意盘：
  1. 环境变量 GONGKAO_DATA_DIR（开发调试用）；
  2. %APPDATA%/GongkaoPrep/location.json 里登记的位置（「设置 → 数据位置」修改，C 盘只留这个小文件）；
  3. 默认 %APPDATA%/GongkaoPrep。
"""

import json
import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME

_resolved = None


def resource_dir() -> Path:
    """静态资源根目录（web/、content/ 所在目录）。打包后位于 PyInstaller 的解压目录。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def web_dir() -> Path:
    return resource_dir() / "web"


def content_dir() -> Path:
    return resource_dir() / "content"


def home_dir() -> Path:
    """%APPDATA%/GongkaoPrep：固定位置，只放 location.json（数据目录挪走以后也一样）。"""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def location_file() -> Path:
    return home_dir() / "location.json"


def read_location() -> dict:
    try:
        return json.loads(location_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_location(info: dict) -> None:
    home_dir().mkdir(parents=True, exist_ok=True)
    tmp = location_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, location_file())


def data_dir() -> Path:
    """用户数据目录：保存学习记录、整理好的资料库、导入的题目和设置。"""
    global _resolved
    if _resolved is None:
        env = os.environ.get("GONGKAO_DATA_DIR")
        if env:
            path = Path(env)
        else:
            path = Path(read_location().get("data_dir") or home_dir())
        path.mkdir(parents=True, exist_ok=True)
        _migrate_legacy(path)
        _resolved = path
    return _resolved


def apply_pending_move(log=print) -> str:
    """启动时（还没打开任何数据库）执行上次在设置里登记的“搬数据目录”。返回出错信息，成功或没有任务时返回空串。"""
    if os.environ.get("GONGKAO_DATA_DIR"):
        return ""
    info = read_location()
    target = info.get("pending_move")
    if not target:
        return ""
    src = Path(info.get("data_dir") or home_dir())
    dst = Path(target)
    try:
        if src.resolve() == dst.resolve():
            raise ValueError("新位置和现在的位置相同")
        move_tree(src, dst, skip={location_file().name, "location.tmp"})
    except (OSError, ValueError) as e:
        info.pop("pending_move", None)
        info["move_error"] = str(e)
        write_location(info)
        log(f"搬移数据目录失败：{e}")
        return str(e)
    info = {"data_dir": str(dst)}
    write_location(info)
    return ""


def move_tree(src: Path, dst: Path, skip=()) -> None:
    """把 src 下的所有内容搬到 dst（先复制、核对大小，再删除原文件）。dst 里已有的同名文件会被覆盖。"""
    dst.mkdir(parents=True, exist_ok=True)
    if any(dst.iterdir()) and (dst / "app.db").exists() and (src / "app.db").exists():
        raise ValueError(f"{dst} 里已经有一份学习数据，为避免覆盖，请换一个空文件夹")
    moved = []
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        for name in files:
            if rel == Path(".") and name in skip:
                continue
            a = Path(root) / name
            b = dst / rel / name
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, b)
            if b.stat().st_size != a.stat().st_size:
                raise OSError(f"复制 {a} 时大小不一致")
            moved.append(a)
    for a in moved:
        try:
            a.unlink()
        except OSError:
            pass
    # 删掉搬空的子目录（保留 src 本身：location.json 在里面）
    for root, dirs, _files in os.walk(src, topdown=False):
        for d in dirs:
            try:
                (Path(root) / d).rmdir()
            except OSError:
                pass


def _migrate_legacy(path: Path) -> None:
    """早期版本把数据放在项目下的 data/，第一次启动新版时搬过来（只复制，不删除原文件）。"""
    legacy = Path(__file__).resolve().parent.parent / "data"
    for name in ("app.db", "custom_questions.json"):
        src, dst = legacy / name, path / name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)
