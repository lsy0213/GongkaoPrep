"""给还没有导图的课起草“本课思维导图”：content/course/maps/lessons/<课 id>.txt。

按课文的 ## / ### 标题搭骨架，再从表格、加粗的列表项、要记住 / 易错框、记忆卡里摘知识点。
起草出来只是草稿，要人工删改成精炼的导图；已经存在的导图不会覆盖。

用法：python tools/draft_lesson_maps.py [课 id ...]
"""

import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "content", "course")
OUT = os.path.join(ROOT, "maps", "lessons")
SKIP_BLOCKS = {"quiz", "example", "reveal", "fill", "order", "match", "drill", "calc", "practice",
               "write", "speak", "check", "figure"}
MAXLEN = 46


def plain(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\*\*|==|`", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ；;。")
    return s


def short(s):
    s = plain(s)
    return s if len(s) <= MAXLEN else s[:MAXLEN - 1] + "…"


def points(lines):
    """一段课文里的知识点：表格行、加粗开头的列表项、“A :: B”卡片。"""
    out = []
    header = None
    for ln in lines:
        t = ln.strip()
        if t.startswith("|"):
            cells = [plain(c) for c in t.strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            if header is None:
                header = cells
                continue
            if len(cells) >= 2 and cells[0]:
                out.append(short(f"{cells[0]}：{'；'.join(c for c in cells[1:3] if c)}"))
            continue
        header = None
        m = re.match(r"^(?:[-*]|\d+[.、])\s+(.*)", t)
        if m and "**" in m.group(1):
            out.append(short(m.group(1)))
            continue
        m = re.match(r"^(.+?)\s+::\s+(.+)$", t)
        if m:
            out.append(short(f"{m.group(1)}：{m.group(2)}"))
    return out


def draft(lid, title):
    with open(os.path.join(ROOT, lid + ".md"), encoding="utf-8") as f:
        lines = f.read().replace("\r", "").split("\n")
    tree = [f"# {title}"]
    cur = []  # 当前小节的正文行
    block = None
    level = 0

    def flush():
        for p in points(cur)[:8]:
            tree.append("  " * (level + 1) + "- " + p)
        cur.clear()

    for ln in lines:
        m = re.match(r"^:::\s*([a-z]+)\s*(.*)$", ln)
        if m:
            block = m.group(1)
            if block in ("key", "warn", "tip") and m.group(2).strip():
                cur.append(f"- **{m.group(2).strip()}**")
            if block == "cards" and "本课" in m.group(2):
                flush()
                level = 0
                tree.append("- 记忆要点")
            continue
        if re.match(r"^:::\s*$", ln):
            block = None
            continue
        if block in SKIP_BLOCKS:
            continue
        h = re.match(r"^(##+)\s+(.*)$", ln)
        if h:
            flush()
            if "随堂练习" in h.group(2):
                level = -1
                continue
            level = 0 if len(h.group(1)) == 2 else 1
            tree.append("  " * level + "- " + plain(h.group(2)))
            continue
        if level >= 0:
            cur.append(ln)
    flush()
    return "\n".join(tree) + "\n"


def main():
    with open(os.path.join(ROOT, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    lessons = [l for c in index["courses"] for l in c["lessons"]]
    want = set(sys.argv[1:])
    os.makedirs(OUT, exist_ok=True)
    n = 0
    for l in lessons:
        path = os.path.join(OUT, l["id"] + ".txt")
        if (want and l["id"] not in want) or os.path.exists(path):
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(draft(l["id"], l["title"]))
        n += 1
    print(f"起草了 {n} 张导图，在 {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
