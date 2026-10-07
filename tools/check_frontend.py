"""前端检查：JS 语法 + 拼 HTML 时没转义的文字。

界面用模板字符串拼 HTML，文字内容（题干、资料、笔记、导入的题目、AI 回答……）必须经过 esc() 或 mathText()/md() 再放进去，
否则内容里的 < > 会被当成标签（显示错乱，或者执行脚本）。这里把“直接插进模板、看起来是文字字段”的地方找出来：

    python tools/check_frontend.py

确实安全的（数字、已经是 HTML 的片段）在那一行末尾写注释 // html-ok 跳过。
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = sorted((ROOT / "web" / "js").rglob("*.js"))

# 插值里出现这些函数就认为已经处理过（转义或本身产出安全的 HTML）
SAFE_CALLS = re.compile(
    r"\b(esc|mathText|md|cropHTML|fmtClock|fmtMinutes|fmtBytes|fmtTok|ivl|Math\.\w+|encodeURIComponent|JSON\.stringify|"
    r"Number|String\(\d|toFixed|scoreTrend|jobProgressHTML|draftBannerHTML|\w+HTML|\w+Card|\w+Block|row|item|card|sheet|"
    r"questionCard|materialBlock|fixEditor|trendSVG|ring|barChart|lineChart|accuracyBars|heatmap|figHTML|reasonStats|metricsText)\s*\("
)
# 字段名是这些“文字”字段的才查：数字、布尔、id、序号之类不管
TEXTY = {
    "stem", "title", "name", "text", "content", "note", "notes", "answer", "explain", "question", "summary", "source", "msg",
    "message", "error", "reason", "front", "back", "label", "desc", "theme", "requirement", "guide", "snippet", "dept", "unit",
    "region", "major", "transcript", "ai_feedback", "feedback", "hint", "problem", "model", "provider_name", "exam", "level",
    "module", "sub", "type", "words", "caption", "edu", "politics", "years", "project", "code", "tags", "kind", "file", "rel",
    "nickname", "step", "focus", "use", "word", "meaning", "sentence", "pinyin", "quote", "author",
}
# 逐个核对过、确实安全的（文件, 插值）：值是数字、常量，或者调用方已经转义过
REVIEWED = {
    ("web/js/lib.js", "unit"): "图表单位，调用方传的常量",
    ("web/js/pages/essay.js", "h.words"): "字数，数字",
    ("web/js/pages/home.js", "name"): "上面已经 esc(s.nickname)",
    ("web/js/pages/library.js", "label"): "navBtn 的调用方传常量或 esc() 过的分组名",
    ("web/js/pages/news.js", "sub"): "年月数字拼成",
    ("web/js/pages/news.js", "label"): "navBtn 的调用方传常量或 esc() 过的专题名",
    ("web/js/pages/notes.js", "name"): "筛选组标题，常量",
    ("web/js/quiz.js", "text"): "md() 渲染过的材料",
    ("web/js/quiz.js", "label"): "里面是 esc(o)",
}
INTERP = re.compile(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
SIMPLE = re.compile(r"^[\w.$\[\]?'\"]+$")


def syntax():
    node = shutil.which("node")
    if not node:
        print("（没有 node，跳过 JS 语法检查）")
        return 0
    bad = 0
    for p in JS:
        r = subprocess.run([node, "--input-type=module", "--check"], input=p.read_bytes(), capture_output=True)
        if r.returncode:
            bad += 1
            print(f"语法错误：{p.relative_to(ROOT)}\n{r.stderr.decode('utf-8', 'replace')[:600]}")
    return bad


def unescaped():
    found = []
    for p in JS:
        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "html-ok" in line or "${" not in line or re.search(r"toast\(|querySelector|textContent\s*=|title\s*=\s*`", line):
                continue
            if not re.search(r"<[a-zA-Z/]", line):
                continue  # 这一行不是在拼 HTML（标题、路径、普通字符串）
            for m in INTERP.finditer(line):
                expr = m.group(1).strip()
                if re.match(r"^[A-Z_]{2,}\[", expr):
                    continue  # 常量表查值（LETTERS[i] 之类）
                if SAFE_CALLS.search(expr) or not SIMPLE.match(expr):
                    continue  # 调用了转义 / 产出 HTML 的函数，或者是表达式（条件、拼接）由人看
                last = re.split(r"[.\[]", expr.replace("?", ""))[-1].strip("]'\"")
                if last in TEXTY and (p.relative_to(ROOT).as_posix(), expr) not in REVIEWED:
                    found.append((p.relative_to(ROOT), no, expr, line.strip()[:140]))
    return found


def main():
    bad = syntax()
    found = unescaped()
    for path, no, expr, line in found:
        print(f"{path}:{no}  ${{{expr}}}  没有转义\n    {line}")
    print(f"\nJS 语法错误 {bad} 个；疑似没转义的插值 {len(found)} 处")
    return 1 if bad or found else 0


if __name__ == "__main__":
    sys.exit(main())
