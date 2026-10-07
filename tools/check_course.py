"""检查教程课文的格式：块是否闭合、测验答案是否有效、真题演练/计算器/速算参数是否正确等；
以及知识导图（content/course/maps/*.txt）：缩进是否正确、@链接是否存在、每门课的每一课是否都出现在导图里。

用法：python tools/check_course.py
"""

import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "content", "course")
BLOCKS = {"tip", "warn", "key", "note", "quiz", "example", "reveal", "cards", "fill", "order", "match",
          "drill", "calc", "practice", "write", "speak", "check", "flow", "tabs", "figure"}
CALCS = {"growth", "annual", "interval", "share", "average", "perm", "score"}
DRILLS = {"mul", "div", "base", "inc", "share", "frac"}
MODULES = {"政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"}
SUBS = {"全部", "", "图形推理", "定义判断", "类比推理", "逻辑判断", "逻辑填空", "片段阅读", "语句表达",
        "数学运算", "数字推理"}


def sections(body):
    out = [[]]
    for line in body.split("\n"):
        if re.match(r"^---+", line):
            out.append([])
        else:
            out[-1].append(line)
    return ["\n".join(s).strip() for s in out]


def check_lesson(lid, text):
    errs = []
    lines = text.replace("\r", "").split("\n")
    i = 0
    blocks = []
    while i < len(lines):
        m = re.match(r"^:::\s*([a-z]+)\s*(.*)$", lines[i])
        if m:
            start = i
            body = []
            i += 1
            while i < len(lines) and not re.match(r"^:::\s*$", lines[i]):
                if re.match(r"^:::\s*[a-z]+", lines[i]):
                    errs.append(f"第 {i + 1} 行：块 {m.group(1)}（第 {start + 1} 行开始）没有闭合就开始了新块")
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                errs.append(f"第 {start + 1} 行：块 {m.group(1)} 没有闭合")
            blocks.append((start + 1, m.group(1), m.group(2).strip(), "\n".join(body)))
        i += 1
    for ln, typ, arg, body in blocks:
        where = f"第 {ln} 行 {typ}"
        if typ not in BLOCKS:
            errs.append(f"{where}：未知块类型")
            continue
        if typ == "quiz":
            for k, sec in enumerate(s for s in sections(body) if s):
                opts = re.findall(r"^([A-H])[.．、]", sec, re.M)
                ans = re.search(r"^答案[:：]\s*([A-H]+)", sec, re.M)
                if not ans:
                    errs.append(f"{where} 第 {k + 1} 题：没有答案")
                    continue
                if len(opts) < 2:
                    errs.append(f"{where} 第 {k + 1} 题：选项少于 2 个")
                for c in ans.group(1):
                    if c not in opts:
                        errs.append(f"{where} 第 {k + 1} 题：答案 {c} 不在选项中")
                if opts != [chr(65 + j) for j in range(len(opts))]:
                    errs.append(f"{where} 第 {k + 1} 题：选项字母不连续 {opts}")
        elif typ in ("cards", "match"):
            pairs = [l for l in body.split("\n") if "::" in l]
            if not pairs:
                errs.append(f"{where}：没有“正面 :: 背面”行")
            if typ == "match":
                rights = [l.split("::", 1)[1].strip() for l in pairs]
                if len(rights) != len(set(rights)) and len(set(rights)) < 2:
                    errs.append(f"{where}：右侧选项都相同")
        elif typ == "fill":
            if not re.search(r"\[\[[^\]]+\]\]", body):
                errs.append(f"{where}：没有 [[答案]]")
            for a in re.findall(r"\[\[([^\]]+)\]\]", body):
                if not re.sub(r"[\s，,。.、；;：:“”\"'‘’（）()]", "", a.split("|")[0]):
                    errs.append(f"{where}：答案“{a}”去掉标点后为空，无法判分")
        elif typ == "order":
            if len(re.findall(r"^\s*[-*]\s+", body, re.M)) < 3:
                errs.append(f"{where}：排序项少于 3 个")
        elif typ == "calc":
            if arg not in CALCS:
                errs.append(f"{where}：未知计算器 {arg}")
        elif typ == "drill":
            kind = arg.split("|")[0].strip()
            if kind not in DRILLS:
                errs.append(f"{where}：未知速算类型 {kind}")
        elif typ == "practice":
            parts = [p.strip() for p in arg.split("|")]
            if parts[0] not in MODULES:
                errs.append(f"{where}：模块“{parts[0]}”不存在")
            if len(parts) > 1 and parts[1] not in SUBS:
                errs.append(f"{where}：题型“{parts[1]}”在题库中不存在")
            if len(parts) > 2 and not parts[2].isdigit():
                errs.append(f"{where}：题数“{parts[2]}”不是数字")
        elif typ == "example":
            if len([s for s in sections(body)]) < 2:
                errs.append(f"{where}：例题没有步骤（用 --- 分隔）")
        elif typ == "tabs":
            if not re.search(r"^---+\s*\S", body, re.M):
                errs.append(f"{where}：标签页没有“--- 标签名”")
        elif typ == "write":
            secs = re.findall(r"^---+\s*(.*)$", body, re.M)
            if not any("要点" in s for s in secs):
                errs.append(f"{where}：没有“--- 要点”")
    return errs, blocks


def check_map(name, text, index):
    """导图：“# 标题” + “- 节点”（每级缩进两格），节点末尾“@课 id / @课程 id”是链接。"""
    errs, refs = [], []
    lessons = {l["id"] for c in index["courses"] for l in c["lessons"]}
    courses = {c["id"] for c in index["courses"]}
    prev = -1
    if not re.match(r"^#\s+\S", text):
        errs.append("第 1 行应该是“# 标题”")
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        m = re.match(r"^( *)- (.+)$", line)
        if not m or len(m.group(1)) % 2:
            errs.append(f"第 {n} 行：应该是“- 节点”，每级缩进两个空格")
            continue
        depth = len(m.group(1)) // 2
        if depth > prev + 1:
            errs.append(f"第 {n} 行：缩进跳级了")
        prev = depth
        for r in re.findall(r"\s@([\w-]+)", m.group(2)):
            refs.append(r)
            if r not in lessons and r not in courses:
                errs.append(f"第 {n} 行：@{r} 不是课或课程的 id")
        if not re.sub(r"\s+@[\w-]+", "", m.group(2)).strip():
            errs.append(f"第 {n} 行：节点没有文字")
    if name.startswith("lessons/"):  # 本课导图：不要求链接
        return errs
    course = next((c for c in index["courses"] if c["id"] == name), None)
    want = [l["id"] for l in course["lessons"]] if course else [c["id"] for c in index["courses"]]
    miss = [x for x in want if x not in refs]
    if miss:
        errs.append("导图里没有链接到：" + "、".join(miss))
    return errs


def check_maps(index):
    bad = 0
    mdir = os.path.join(ROOT, "maps")
    names = ["all"] + [c["id"] for c in index["courses"]]
    lids = [l["id"] for c in index["courses"] for l in c["lessons"]]
    for name in names + ["lessons/" + x for x in lids]:
        path = os.path.join(mdir, name + ".txt")
        if not os.path.exists(path):
            print(f"[导图缺失] maps/{name}.txt")
            bad += 1
            continue
        with open(path, encoding="utf-8") as f:
            for e in check_map(name, f.read(), index):
                print(f"[导图 {name}] {e}")
                bad += 1
    for n in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        if n.endswith(".txt") and n[:-4] not in names:
            print(f"[导图多余] maps/{n} 不对应任何课程")
            bad += 1
    ldir = os.path.join(mdir, "lessons")
    for n in sorted(os.listdir(ldir)) if os.path.isdir(ldir) else []:
        if n.endswith(".txt") and n[:-4] not in lids:
            print(f"[导图多余] maps/lessons/{n} 不对应任何课")
            bad += 1
    return bad, len(names) + len(lids)


def main():
    with open(os.path.join(ROOT, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    ids = [l["id"] for c in index["courses"] for l in c["lessons"]]
    total, bad = 0, 0
    counts = {}
    for lid in ids:
        path = os.path.join(ROOT, lid + ".md")
        if not os.path.exists(path):
            print(f"[缺失] {lid}.md")
            bad += 1
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        errs, blocks = check_lesson(lid, text)
        total += 1
        for _ln, typ, _a, _b in blocks:
            counts[typ] = counts.get(typ, 0) + 1
        for e in errs:
            print(f"[{lid}] {e}")
            bad += 1
    extra = sorted(set(n[:-3] for n in os.listdir(ROOT) if n.endswith(".md")) - set(ids))
    for e in extra:
        print(f"[多余] {e}.md 不在 index.json 里")
    mbad, mn = check_maps(index)
    bad += mbad
    print(f"\n检查了 {total} 课、{mn} 张导图，问题 {bad} 个。互动块统计：",
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
