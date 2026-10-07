"""把 content/essays_src/*.txt 里的原创申论套题编译成 content/essays_more.json，并做格式校验。

用法：python tools/build_essays.py

源文件格式（纯文本，UTF-8）：
    === o001                         一套题开始，后面是唯一 id
    标题：……
    主题：大类 · 小类                  大类用于列表页筛选，取值见 DOMAINS
    级别：地市级
    --- 材料 1                        材料标题；正文每段一行，空行忽略
    ……
    --- 题 归纳概括 | 15 | 20 | 不超过 200 字     题型 | 分值 | 建议分钟 | 字数
    问：……
    要求：……
    要点：
    - ……
    参考：
    ……（直到下一个 --- 或 ===）
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "content", "essays_src")
OUT = os.path.join(ROOT, "content", "essays_more.json")

DOMAINS = ["乡村振兴", "生态文明", "民生保障", "基层治理", "经济发展", "科技创新", "文化建设",
           "社会治理", "教育发展", "城市治理", "法治建设", "安全应急", "青年人才", "政务服务"]
TYPES = ["归纳概括", "综合分析", "提出对策", "贯彻执行", "文章写作"]


def parse(path):
    sets, cur, block, field = [], None, None, None
    errs = []

    def where(i):
        return f"{os.path.basename(path)}:{i}"

    for i, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        line = raw.strip()
        if line.startswith("=== "):
            cur = {"id": line[4:].strip(), "title": "", "theme": "", "level": "", "materials": [], "questions": []}
            sets.append(cur)
            block = field = None
            continue
        if cur is None:
            if line:
                errs.append(f"{where(i)} 套题开始前有内容")
            continue
        if line.startswith("--- 材料"):
            block = {"title": line[4:].strip(), "text": []}
            cur["materials"].append(block)
            field = "text"
            continue
        if line.startswith("--- 题"):
            parts = [p.strip() for p in line[len("--- 题"):].split("|")]
            if len(parts) != 4:
                errs.append(f"{where(i)} 题头应为 题型|分值|分钟|字数")
                parts += [""] * 4
            block = {"type": parts[0], "question": "", "requirement": "", "words": parts[3],
                     "score": int(parts[1] or 0), "minutes": int(parts[2] or 0), "points": [], "reference": []}
            cur["questions"].append(block)
            field = None
            continue
        if not line:
            continue
        if block is None:
            m = re.match(r"(标题|主题|级别)：(.*)", line)
            if not m:
                errs.append(f"{where(i)} 无法识别：{line[:20]}")
                continue
            cur[{"标题": "title", "主题": "theme", "级别": "level"}[m.group(1)]] = m.group(2).strip()
            continue
        if "type" not in block:  # 材料正文
            block["text"].append(line)
            continue
        m = re.match(r"(问|要求|要点|参考)：(.*)", line)
        if m and field != "reference":  # 参考答案放在最后，其中的“要求：”之类不当作字段
            field = {"问": "question", "要求": "requirement", "要点": "points", "参考": "reference"}[m.group(1)]
            rest = m.group(2).strip()
            if field in ("question", "requirement"):
                block[field] = rest
            elif rest:
                block[field].append(rest)
            continue
        if field == "points":
            if not line.startswith("- "):
                errs.append(f"{where(i)} 要点应以“- ”开头")
            block["points"].append(line[2:].strip())
        elif field == "reference":
            block["reference"].append(line)
        elif field == "requirement":
            block["requirement"] += line
        else:
            errs.append(f"{where(i)} 多余内容：{line[:20]}")

    for s in sets:
        for m in s["materials"]:
            m["text"] = "\n\n".join(m["text"])
        for q in s["questions"]:
            q["reference"] = "\n".join(q["reference"])
    return sets, errs


def check(s):
    e = []
    sid = s["id"]
    for k in ("title", "theme", "level"):
        if not s[k]:
            e.append(f"{sid} 缺少 {k}")
    if s["theme"].split(" · ")[0] not in DOMAINS:
        e.append(f"{sid} 主题大类不在 DOMAINS：{s['theme']}")
    if not 2 <= len(s["materials"]) <= 8:
        e.append(f"{sid} 材料数 {len(s['materials'])}")
    for m in s["materials"]:
        if len(m["text"]) < 80:
            e.append(f"{sid} {m['title']} 太短")
    if not 3 <= len(s["questions"]) <= 5:
        e.append(f"{sid} 题数 {len(s['questions'])}")
    for j, q in enumerate(s["questions"], 1):
        if q["type"] not in TYPES:
            e.append(f"{sid} 第{j}题 题型 {q['type']}")
        if not q["question"] or not q["requirement"] or not q["words"]:
            e.append(f"{sid} 第{j}题 问/要求/字数不全")
        if len(q["points"]) < 3 or not q["reference"]:
            e.append(f"{sid} 第{j}题 要点或参考缺失")
    return e


def main():
    sets, errs = [], []
    for path in sorted(glob.glob(os.path.join(SRC, "*.txt"))):
        got, e = parse(path)
        sets += got
        errs += e
    ids = set()
    for s in sets:
        if s["id"] in ids:
            errs.append(f"重复 id {s['id']}")
        ids.add(s["id"])
        errs += check(s)
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"sets": sets}, f, ensure_ascii=False, indent=1)
    by = {}
    for s in sets:
        d = s["theme"].split(" · ")[0]
        by[d] = by.get(d, 0) + 1
    print(f"OK {len(sets)} 套 → {os.path.relpath(OUT, ROOT)}")
    print("  ".join(f"{k}{v}" for k, v in sorted(by.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
