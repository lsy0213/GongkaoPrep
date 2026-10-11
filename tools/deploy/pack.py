"""在自己电脑上把要传到服务器的东西打成几个包（见 tools/deploy/部署说明.md）。

    python tools/deploy/pack.py <输出文件夹> [code] [library] [materials] [userdata]

不写后面的名字就四个都打：
- code       代码 + 内置内容（包括不进 git 仓库的购买资料整理稿 content/curated 等、白瓷星轨的天使图）→ app.tar.gz
- library    资料库整理结果：题库、资料库文档、时政、全文索引、插图（数据目录 library/ 里，不含 OCR、分页缓存）→ library.tar.gz
             其他考试（软考等）的整理结果在 exams/<考试 id>/library/，一起打进去
- materials  真题卷原文件：只打题目截图要用的那些 PDF（全部资料几十 GB 传不动；别的资料在服务器上看整理好的文字版）→ materials.tar
             其他考试的原文件放在包里的 exams/<考试 id>/ 下（服务器上 GONGKAO_LIBRARY_ROOT/exams/<考试 id>/）
- userdata   学习记录 app.db、职位库 positions.db，以及各考试自己的 exams/<考试 id>/app.db → userdata.tar.gz
             注意：服务器上的学习记录和电脑上是分开的两份，以后再传 userdata 会覆盖服务器上做过的题、打过的卡；
             电脑上的 AI Key 是用 Windows DPAPI 加密的，服务器上解不开，要在网页的设置里重新填

数据库用 SQLite 的在线备份拷出来，电脑上的软件开着也没关系。
"""

import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gongkao import paths  # noqa: E402

# 不进 git、但服务器上要有的文件（.gitignore 里列着的购买资料整理稿、私有图片）
EXTRA = ["content/curated", "content/doc_answers.json", "content/shizheng_answers.json", "content/speed_bank.json",
         "web/img/skin/private"]
LIB_FILES = ["catalog.json", "decks.json", "real_essays.json", "sucai.json", "shizheng_files.json"]
LIB_DBS = ["questions.db", "docs.db", "shizheng.db", "fulltext.db"]
# 其他考试的 library/ 里要传的（github/ 是下载的开源题库原文件，整理后用不到）
EXAM_LIB_FILES = ["catalog.json", "decks.json", "cases.json", "essays.json", "videos.json"]
EXAM_LIB_DBS = ["questions.db", "docs.db", "fulltext.db"]


def exam_dirs():
    """数据目录里其他考试的文件夹 [(考试 id, 路径)]。"""
    root = paths.data_dir() / "exams"
    return sorted((p.name, p) for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def mb(p):
    return f"{os.path.getsize(p) / 1e6:.0f} MB"


def add_db(tar, src, arcname):
    """SQLite 在线备份到临时文件再放进包里（直接拷正在用的 WAL 数据库可能拷到一半的状态）。"""
    if not src.exists():
        print("  跳过（没有）", src)
        return
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / src.name
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        d = sqlite3.connect(dst)
        with d:
            s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")
        s.close()
        d.close()
        tar.add(dst, arcname)


def pack_code(out):
    files = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    files = [f for f in files if f and not f.startswith(("tests/", ".github/", "installer/"))]
    for e in EXTRA:
        p = ROOT / e
        if p.is_dir():
            files += [str(x.relative_to(ROOT)).replace("\\", "/") for x in p.rglob("*") if x.is_file()]
        elif p.is_file():
            files.append(e)
    dst = out / "app.tar.gz"
    with tarfile.open(dst, "w:gz") as tar:
        for f in sorted(set(files)):
            if (ROOT / f).is_file():
                tar.add(ROOT / f, f)
    print(f"app.tar.gz：{len(files)} 个文件，{mb(dst)}")


def pack_library(out):
    lib = paths.data_dir() / "library"
    dst = out / "library.tar.gz"
    with tarfile.open(dst, "w:gz", compresslevel=6) as tar:
        for f in LIB_FILES:
            if (lib / f).exists():
                tar.add(lib / f, f"library/{f}")
        for f in LIB_DBS:
            print("  备份", f)
            add_db(tar, lib / f, f"library/{f}")
        print("  插图 docimg/")
        tar.add(lib / "docimg", "library/docimg")
        for eid, d in exam_dirs():
            elib, arc = d / "library", f"exams/{eid}/library"
            for f in EXAM_LIB_FILES:
                if (elib / f).exists():
                    tar.add(elib / f, f"{arc}/{f}")
            for f in EXAM_LIB_DBS:
                if (elib / f).exists():
                    print(f"  备份 {eid}/{f}")
                    add_db(tar, elib / f, f"{arc}/{f}")
            if (elib / "docimg").is_dir():
                tar.add(elib / "docimg", f"{arc}/docimg")
    print(f"library.tar.gz：{mb(dst)}")


def needed_fids(qdb_path=None):
    """题目截图（原卷上的位置）和真题卷原文件用到的文件 id。"""
    conn = sqlite3.connect(f"file:{qdb_path or paths.data_dir() / 'library' / 'questions.db'}?mode=ro", uri=True)
    fids = set()
    for sql in ("SELECT fid FROM questions WHERE crop != '' OR explain_crop != ''", "SELECT fid FROM materials WHERE crop != ''",
                "SELECT fid FROM sources", "SELECT answer_fid FROM sources"):
        fids.update(v for (v,) in conn.execute(sql) if v)
    conn.close()
    return fids


def pack_materials(out):
    libs = [("", paths.data_dir() / "library")] + [(f"exams/{eid}/", d / "library") for eid, d in exam_dirs()]
    dst = out / "materials.tar"
    n = size = 0
    with tarfile.open(dst, "w") as tar:
        for prefix, lib in libs:
            if not (lib / "catalog.json").exists() or not (lib / "questions.db").exists():
                continue
            cat = json.loads((lib / "catalog.json").read_text(encoding="utf-8"))
            want = needed_fids(lib / "questions.db")
            for f in cat["files"]:
                if f["id"] not in want:
                    continue
                src = Path(cat["root"]) / f["rel"]
                if not src.is_file():
                    print("  找不到", src)
                    continue
                tar.add(src, prefix + f["rel"].replace("\\", "/"))
                n += 1
                size += src.stat().st_size
    print(f"materials.tar：{n} 个文件，{size / 1e9:.2f} GB")


def pack_userdata(out):
    dst = out / "userdata.tar.gz"
    with tarfile.open(dst, "w:gz") as tar:
        for f in ("app.db", "positions.db"):
            add_db(tar, paths.data_dir() / f, f)
        for eid, d in exam_dirs():
            add_db(tar, d / "app.db", f"exams/{eid}/app.db")
    print(f"userdata.tar.gz：{mb(dst)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    what = set(sys.argv[2:]) or {"code", "library", "materials", "userdata"}
    bad = what - {"code", "library", "materials", "userdata"}
    if bad:
        print("不认识：", ", ".join(bad))
        return 1
    print("数据目录：", paths.data_dir())
    for name, fn in (("code", pack_code), ("library", pack_library), ("materials", pack_materials), ("userdata", pack_userdata)):
        if name in what:
            fn(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
