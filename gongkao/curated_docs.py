"""少量逐页核对原件的文字校订稿；仅用于内容散列完全匹配的扫描件。"""

import hashlib


FORMULA_SHA256 = "1957a14f92b44e84089572165172e5a74ae129811dc99ac6e75001f35c3fbae2"


def inline(tex):
    """阅读器识别的离线数学公式标记。"""
    return "\\(" + tex + "\\)"


def display(tex):
    return "\\[" + tex + "\\]"


# 每一项为（页码、标题、该节的逐条文字）。分式用括号和 ÷ 表示，避免扫描 OCR 拆散上下标。
FORMULA_SECTIONS = [
    (0, "基础公式", [
        "① 完全平方：" + inline(r"(a\pm b)^2=a^2\pm2ab+b^2") + "。",
        "② 平方差：" + inline(r"a^2-b^2=(a+b)(a-b)") + "。",
        "③ 完全立方：" + inline(r"(a\pm b)^3=a^3\pm3a^2b+3ab^2\pm b^3") + "。",
        "④ 立方和与差：" + inline(r"a^3\pm b^3=(a\pm b)(a^2\mp ab+b^2)") + "。",
        "⑤ 裂项：" + inline(r"\frac{d}{n(n+d)}=\frac1n-\frac1{n+d}") + "。",
        "⑥ 一元二次方程：" + inline(r"ax^2+bx+c=a(x-x_1)(x-x_2)") + "；求根：" + inline(r"x_{1,2}=\frac{-b\pm\sqrt{b^2-4ac}}{2a}") + "，其中 b² − 4ac ≥ 0。",
        "韦达定理：" + inline(r"x_1+x_2=-\frac ba,\quad x_1x_2=\frac ca") + "。",
        "⑦ 均值不等式：" + inline(r"\frac{a_1+\cdots+a_n}{n}\ge\sqrt[n]{a_1\cdots a_n}") + "；各项非负，当 a₁ = … = aₙ 时取等号。",
    ]),
    (0, "排列组合问题", [
        "① 排列数：" + inline(r"A_n^m=n(n-1)\cdots(n-m+1)=\frac{n!}{(n-m)!}") + "。",
        "② 组合数：" + inline(r"C_n^m=\frac{A_n^m}{m!}=\frac{n!}{m!(n-m)!}=C_n^{n-m}") + "。",
    ]),
    (1, "等差数列", [
        "通项：aₙ = a₁ + (n − 1)d，其中 a₁ 为首项，d 为公差。",
        "前 n 项和：" + inline(r"S_n=na_1+\frac{n(n-1)d}{2}=\frac{(a_1+a_n)n}{2}") + "。",
        "若 a、A、b 成等差数列，则 2A = a + b。",
        "若 m + n = p + q，则 aₘ + aₙ = aₚ + aᵩ；若 m + n = 2p，则 aₘ + aₙ = 2aₚ。",
    ]),
    (1, "等比数列", [
        "通项：aₙ = a₁q⁽ⁿ⁻¹⁾，其中 a₁ 为首项，q 为公比。",
        "前 n 项和：q = 1 时，Sₙ = na₁；q ≠ 1 时，" + inline(r"S_n=\frac{a_1(1-q^n)}{1-q}") + "。",
        "若 a、G、b 成等比数列，则 G² = ab。",
        "若 m + n = p + q，则 aₘaₙ = aₚaᵩ；若 m + n = 2p，则 aₘaₙ = aₚ²。",
        "同一等比数列中，aₘ/aₙ = q⁽ᵐ⁻ⁿ⁾。",
    ]),
    (2, "几何问题", [
        "① 梯形面积 = (上底 + 下底) × 高 ÷ 2。",
        "② 扇形面积 " + inline(r"S=\frac{n\pi r^2}{360}=\frac{Lr}{2}") + "，其中 n 为圆心角度数，L 为弧长。",
        "③ 正方体表面积 = 6a²；体积 = a³，其中 a 为棱长。",
        "④ 长方体表面积 = 2(ab + bc + ac)；体积 = abc。",
        "球体表面积 " + inline(r"S=4\pi r^2") + "；体积 " + inline(r"V=\frac43\pi r^3") + "，其中 r 为半径。",
        "⑤ 圆柱体积 = Sh = πr²h，其中 S 为底面积。",
        "⑥ 圆锥体积 = Sh/3 = πr²h/3，其中 S 为底面积。",
    ]),
    (2, "利息问题", [
        "① 利息 = 本金 × 利率 × 时间。",
        "② 本利和 = 本金 + 利息 = 本金 × (1 + 利率 × 时间)。",
        "③ 本金 = 本利和 ÷ (1 + 利率 × 时间)。",
    ]),
    (3, "容斥公式", [
        "两集合：" + inline(r"|A\cup B|=|A|+|B|-|A\cap B|") + "。",
        "三集合：" + display(r"|A\cup B\cup C|=|A|+|B|+|C|-|A\cap B|-|B\cap C|-|C\cap A|+|A\cap B\cap C|") + "。",
    ]),
    (3, "盈亏问题", [
        "① 一盈一亏：对象数 = (盈数 + 亏数) ÷ 两次分配个数之差。",
        "② 两次皆盈：对象数 = (大盈数 − 小盈数) ÷ 两次分配个数之差。",
        "③ 两次皆亏：对象数 = (大亏数 − 小亏数) ÷ 两次分配个数之差。",
        "④ 一次盈、一次刚好：对象数 = 盈数 ÷ 两次分配个数之差。",
        "⑤ 一次亏、一次刚好：对象数 = 亏数 ÷ 两次分配个数之差。",
    ]),
    (3, "植树问题", [
        "① 不封闭道路、两端都植树：棵数 = 总路长 ÷ 间距 + 1。",
        "② 不封闭道路、只植一端：棵数 = 总路长 ÷ 间距。",
        "③ 不封闭道路、两端都不植树：棵数 = 总路长 ÷ 间距 − 1。",
        "④ 封闭道路（环形）：棵数 = 总路长 ÷ 间距。",
    ]),
    (3, "对折问题", [
        "绳子对折 N 次，从中剪 M 刀：对折后的层数为 " + inline(r"2^N") + "，段数为 " + inline(r"2^NM+1") + "。",
    ]),
    (4, "时钟问题", [
        "① 秒针每秒转 6°；分针每分钟转 6°；时针每分钟转 0.5°。",
        "② 钟面一圈 60 小格；时针每小时走 5 格，即 30°，每分钟走 0.5°。",
        "③ 时针与分针的角速度差为每分钟 5.5°；分针每小时转 360°。",
        "④ 时针与分针一昼夜重合 22 次、垂直 44 次、成 180° 22 次。",
    ]),
    (4, "方阵问题", [
        "① 实心方阵总人数 = 最外层每边人数²。",
        "空心方阵总人数 = (最外层每边人数 − 空心层数) × 空心方阵层数 × 4。",
        "② 方阵每层总人数 = (该层每边人数 − 1) × 4。",
        "③ 去掉一行一列：去掉人数 = 原来每行人数 × 2 − 1；去掉两行两列：去掉人数 = 原来每行人数 × 4 − 4。",
    ]),
    (5, "奇偶特性", [
        "奇数 ± 奇数 = 偶数；偶数 ± 偶数 = 偶数；偶数 ± 奇数 = 奇数。",
        "奇数 + 偶数 = 奇数。",
        "两个数的和为奇数，则两数奇偶相反；和为偶数，则两数奇偶相同。",
        "两个数的差为奇数，则两数奇偶相反；差为偶数，则两数奇偶相同。",
    ]),
    (5, "整除特性", [
        "能被 2 或 5 整除：看末位数字。",
        "能被 4 或 25 整除：看末两位数字。",
        "能被 8 或 125 整除：看末三位数字。",
        "能被 3 或 9 整除：看各位数字之和。",
        "若 a:b = m:n，且 m、n 互质，则 a 是 m 的倍数、b 是 n 的倍数。",
        "若 a:b = m:n，且 m、n 互质，则 a ± b 是 m ± n 的倍数。",
    ]),
    (6, "余数问题", [
        "口诀：余同取余，和同加和，差同减差，最小公倍加。",
        "① 不同除数、相同余数：被除数 = 除数公倍数 + 共同余数。",
        "② 不同除数，除数与余数之和相等：被除数 = 除数公倍数 + 共同的和。",
        "③ 不同除数，除数与余数之差相等：被除数 = 除数公倍数 − 共同的差。",
    ]),
    (6, "溶液问题", [
        "溶液 = 溶质 + 溶剂；浓度 = 溶质 ÷ 溶液。",
        "溶质 = 溶液 × 浓度；溶液 = 溶质 ÷ 浓度。",
    ]),
    (6, "工程问题", [
        "工作总量 = 工作效率 × 工作时间。",
    ]),
    (7, "路程问题", [
        "路程 = 速度 × 时间。",
        "相遇问题：总路程 = 速度和 × 相遇时间；速度和 = 总路程 ÷ 相遇时间。",
        "追及问题：路程差 = 速度差 × 追及时间；速度差 = 路程差 ÷ 追及时间。",
    ]),
    (7, "鸡兔同笼", [
        "① 鸡只数 = (兔脚数 × 总只数 − 总脚数) ÷ (兔脚数 − 鸡脚数)。",
        "② 兔只数 = (总脚数 − 鸡脚数 × 总只数) ÷ (兔脚数 − 鸡脚数)。",
        "③ 兔只数 = 总脚数 ÷ 2 − 总只数。",
    ]),
    (7, "牛吃草", [
        "草地原有草量 = (牛数 − 每天长草量) × 天数。",
    ]),
]


def matched_formula(path, name):
    if name != "【数量】秒杀公式总结" or not path.lower().endswith(".pdf"):
        return False
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == FORMULA_SHA256


def formula_blocks():
    blocks = []
    for page, title, lines in FORMULA_SECTIONS:
        blocks.append({"k": "h", "lv": 1, "t": title, "pg": page})
        blocks.extend({"k": "p", "t": line, "pg": page} for line in lines)
    return blocks, 8, True


# ---------------------------------------------------------------- 手写笔记转写稿
# content/curated/*.txt：头部 name/sha256/pages，"---" 之后是正文。
# "@N" 换到第 N 页（从 0 起），"#"…"####" 是 1–4 级标题，连续的 "| a | b |" 行是一张表，其余每行一段。

def _transcripts():
    from .paths import content_dir
    out = {}
    folder = content_dir() / "curated"
    for path in sorted(folder.glob("*.txt")) if folder.is_dir() else []:
        head, _, body = path.read_text(encoding="utf-8").partition("\n---\n")
        meta = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
        meta = {k.strip(): v.strip() for k, v in meta.items()}
        if meta.get("name") and meta.get("sha256"):
            out[meta["name"]] = (meta["sha256"], int(meta.get("pages") or 1), body)
    return out


def transcript_times():
    """{资料名: 转写稿修改时间 "YYYY-mm-dd HH:MM:SS"}：转写稿比上次整理新就要重做。"""
    import time
    from .paths import content_dir
    folder = content_dir() / "curated"
    names = _transcripts()
    out = {}
    for path in folder.glob("*.txt") if folder.is_dir() else []:
        if path.stem in names:
            out[path.stem] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
    return out


def transcript_blocks(path, name):
    """有逐页核对过的转写稿、且原件散列一致时，返回 (blocks, pages, scanned)，否则 None。"""
    entry = _transcripts().get(name)
    if not entry:
        return None
    sha, pages, body = entry
    with open(path, "rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != sha:
            return None
    blocks, page = [], 0
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("@") and line[1:].isdigit():
            page = int(line[1:])
            continue
        if line.startswith("|"):
            row = [c.strip() for c in line.strip("|").split("|")]
            if blocks and blocks[-1]["k"] == "tbl" and blocks[-1]["pg"] == page and blocks[-1].get("open"):
                blocks[-1]["d"]["rows"].append(row)
            else:
                blocks.append({"k": "tbl", "pg": page, "d": {"rows": [row]}, "open": True})
            continue
        if blocks and blocks[-1].get("open"):
            blocks[-1].pop("open")
        level = len(line) - len(line.lstrip("#"))
        if 1 <= level <= 4 and line[level:level + 1] == " ":
            blocks.append({"k": "h", "lv": level, "t": line[level:].strip(), "pg": page})
        else:
            blocks.append({"k": "p", "t": line, "pg": page})
    for b in blocks:
        if b["k"] == "tbl":
            b.pop("open", None)
            b["t"] = " ".join(" ".join(r) for r in b["d"]["rows"])
    return blocks, pages, True
