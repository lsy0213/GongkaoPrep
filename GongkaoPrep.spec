# -*- mode: python ; coding: utf-8 -*-
# 打包配置（build.bat 调用）：onedir 目录版——启动快（不用每次解压到临时目录），也不容易被杀毒软件误报。
# 输出 dist\GongkaoPrep\GongkaoPrep.exe；装了 Inno Setup 时 build.bat 再做成安装包。
import os
import re
import sys
from pathlib import Path

# conda 环境的 DLL（libexpat 等）在 Library\bin。没有先 conda activate 就直接用环境里的 python 打包时，
# PATH 里排在前面的可能是 base 环境的同名 DLL，版本对不上，打出来的 exe 里 pyexpat 加载失败（读不了 xlsx）。
_lib_bin = Path(sys.prefix) / "Library" / "bin"
if _lib_bin.is_dir():
    os.environ["PATH"] = str(_lib_bin) + os.pathsep + os.environ.get("PATH", "")

from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH)
VERSION = re.search(r'VERSION = "([\d.]+)"', (ROOT / "gongkao" / "__init__.py").read_text(encoding="utf-8")).group(1)
nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("080404B0", [
            StringStruct("CompanyName", "GongkaoPrep"),
            StringStruct("FileDescription", "上岸备考 · 公考小窝"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "GongkaoPrep"),
            StringStruct("OriginalFilename", "GongkaoPrep.exe"),
            StringStruct("ProductName", "上岸备考"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0804, 1200])]),
    ],
)

datas = [("web", "web"), ("content", "content"), ("assets/icon.ico", "assets")]
binaries = []
hiddenimports = []
datas += collect_data_files("docx")
for pkg in ("pymupdf", "rapidocr_onnxruntime", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
# 职位表（xls/xlsx）读取、手机扫码的二维码
hiddenimports += ["openpyxl", "xlrd", "qrcode", "qrcode.image.svg"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "ruff", "IPython", "matplotlib"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GongkaoPrep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩过的 exe 更容易被误报，目录版也不需要压缩
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/icon.ico"],
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GongkaoPrep",
)
