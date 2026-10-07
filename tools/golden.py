"""资料整理的“黄金样本”回归检查：改了 docs.py / docq.py / doccleanup.py 等整理规则后，先跑一遍看有没有误伤。

挑一批有代表性的资料（文字版 PDF、Word，不需要 OCR，几秒钟一份），在临时数据目录里按当前代码整理，
和登记的结果比较：块数、各类块数、标题数、例题数、有答案的例题数、目录条数、正文指纹。

    python tools/golden.py pick 12      # 从本机资料目录里挑样本，写 tests/golden/samples.json（只记文件 id）
    python tools/golden.py update       # 用当前代码整理样本，登记为基准（tests/golden/expected.json）
    python tools/golden.py check        # 用当前代码整理样本，和基准比较；有差异时退出码为 1

仓库里只存文件 id 和统计数字（不含资料原文）；完整整理结果存在 tests/golden_local/（不进 git），
check 发现差异时会把新旧结果逐块比较，打印前几处不同。
需要本机有资料文件夹（默认 E:\\aaaaaaaa\\gongkao，可用环境变量 GONGKAO_LIBRARY_ROOT 指定）和整理过的目录 catalog.json。
"""

import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"
LOCAL = ROOT / "tests" / "golden_local"
SAMPLES = GOLDEN / "samples.json"
EXPECTED = GOLDEN / "expected.json"


def _real_data_dir():
    """真正的数据目录（读 catalog.json 用），在切换到临时目录之前取。"""
    sys.path.insert(0, str(ROOT))
    from gongkao import paths

    loc = paths.read_location()
    return Path(loc.get("data_dir") or paths.home_dir())


def library_root():
    env = os.environ.get("GONGKAO_LIBRARY_ROOT")
    if env:
        return env
    return r"E:\aaaaaaaa\gongkao"


def load_catalog(real_dir):
    path = real_dir / "library" / "catalog.json"
    if not path.exists():
        return None
    return {f["id"]: f for f in json.loads(path.read_text(encoding="utf-8"))["files"]}


def isolate():
    """之后导入的 gongkao 模块把整理结果写到临时目录，不碰本机的 docs.db。"""
    tmp = tempfile.mkdtemp(prefix="gongkao-golden-")
    os.environ["GONGKAO_DATA_DIR"] = tmp
    os.environ.pop("GONGKAO_DOCS_DB", None)
    return tmp


def digest(blocks, toc):
    kinds = {}
    for b in blocks:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    qs = [json.loads(b["data"]) for b in blocks if b["kind"] == "q" and b["data"]]
    text = "\n".join(f"{b['kind']}|{b['level']}|{b['text']}" for b in blocks)
    return {
        "blocks": len(blocks), "kinds": kinds, "chars": sum(len(b["text"] or "") for b in blocks),
        "questions": len(qs), "answered": sum(1 for q in qs if q.get("ans")), "toc": len(toc),
        "sha": hashlib.sha1(text.encode("utf-8")).hexdigest()[:16],
    }


def build(files, root):
    """按当前代码整理这些资料，返回 {fid: (摘要, 完整块列表)}。"""
    from gongkao import docs

    conn = docs.connect()
    out = {}
    for f in files:
        try:
            blocks, pages, scanned = docs.build_one(root, f)
            docs.save(conn, f, blocks, pages, scanned)
        except Exception as e:  # noqa: BLE001
            out[f["id"]] = ({"error": str(e)[:200]}, [])
            continue
        rows = [dict(r) for r in conn.execute("SELECT kind, level, text, data FROM blocks WHERE doc=? ORDER BY seq", (f["id"],))]
        toc = json.loads(conn.execute("SELECT toc FROM docs WHERE id=?", (f["id"],)).fetchone()[0] or "[]")
        out[f["id"]] = (digest(rows, toc), rows)
    conn.close()
    return out


def pick(n):
    real = _real_data_dir()
    cat = load_catalog(real)
    if not cat:
        sys.exit("没有找到 catalog.json：先在软件里整理一遍资料")
    import sqlite3

    live = real / "library" / "docs.db"
    scanned = {}
    if live.exists():
        c = sqlite3.connect(live)
        scanned = {r[0]: r[1] for r in c.execute("SELECT id, scanned FROM docs")}
        c.close()
    pool = [f for f in cat.values() if f["id"] in scanned and not scanned[f["id"]] and f["ext"] in ("pdf", "docx")
            and 1 <= (f.get("pages") or 1) <= 40]
    rnd = random.Random(20261007)
    by_cat = {}
    for f in pool:
        by_cat.setdefault((f.get("cat"), f["ext"]), []).append(f)
    picked = []
    while len(picked) < n and any(by_cat.values()):
        for k in sorted(by_cat, key=str):
            if by_cat[k] and len(picked) < n:
                picked.append(by_cat[k].pop(rnd.randrange(len(by_cat[k]))))
    GOLDEN.mkdir(parents=True, exist_ok=True)
    SAMPLES.write_text(json.dumps({"files": sorted(f["id"] for f in picked)}, indent=1), encoding="utf-8")
    print(f"挑了 {len(picked)} 份样本，写入 {SAMPLES}")


def _files():
    real = _real_data_dir()
    cat = load_catalog(real)
    if not cat or not SAMPLES.exists():
        return None, None
    root = library_root()
    ids = json.loads(SAMPLES.read_text(encoding="utf-8"))["files"]
    files = [cat[i] for i in ids if i in cat and os.path.exists(os.path.join(root, cat[i]["rel"]))]
    return files, root


def update():
    files, root = _files()
    if files is None:
        sys.exit("没有样本：先运行 python tools/golden.py pick")
    isolate()
    res = build(files, root)
    EXPECTED.write_text(json.dumps({k: v[0] for k, v in sorted(res.items())}, ensure_ascii=False, indent=1), encoding="utf-8")
    LOCAL.mkdir(parents=True, exist_ok=True)
    for fid, (_d, rows) in res.items():
        (LOCAL / f"{fid}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"已登记 {len(res)} 份样本的基准结果")


def compare(files, root):
    """返回差异说明列表（空 = 和基准一致）。"""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    res = build(files, root)
    problems = []
    for fid, (dig, rows) in sorted(res.items()):
        exp = expected.get(fid)
        if exp is None or exp == dig:
            continue
        name = next((f["name"] for f in files if f["id"] == fid), fid)
        lines = [f"{name}（{fid}）"]
        for k in ("blocks", "chars", "questions", "answered", "toc", "kinds", "error"):
            if exp.get(k) != dig.get(k):
                lines.append(f"    {k}: {exp.get(k)} → {dig.get(k)}")
        old_path = LOCAL / f"{fid}.json"
        if old_path.exists():
            old = json.loads(old_path.read_text(encoding="utf-8"))
            shown = 0
            for i in range(max(len(old), len(rows))):
                a = old[i] if i < len(old) else None
                b = rows[i] if i < len(rows) else None
                if a != b:
                    fmt = lambda x: "（无）" if x is None else f"[{x['kind']}{x['level'] or ''}] {(x['text'] or '')[:70]}"  # noqa: E731
                    lines.append(f"    第 {i} 块：{fmt(a)}\n           → {fmt(b)}")
                    shown += 1
                    if shown >= 3:
                        break
        problems.append("\n".join(lines))
    return problems


def check():
    files, root = _files()
    if files is None:
        sys.exit("没有样本或基准：先运行 pick 和 update")
    isolate()
    problems = compare(files, root)
    if problems:
        print(f"{len(problems)} 份样本的整理结果变了：\n")
        print("\n\n".join(problems))
        print("\n如果是有意的改进，运行 python tools/golden.py update 更新基准。")
        sys.exit(1)
    print(f"{len(files)} 份样本和基准一致")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "pick":
        pick(int(sys.argv[2]) if len(sys.argv) > 2 else 12)
    elif cmd == "update":
        update()
    elif cmd == "check":
        check()
    else:
        sys.exit(__doc__)
