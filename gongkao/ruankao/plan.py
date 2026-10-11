"""软考复习计划：开始备考 → 考试日切成四个阶段，再按星期几排每天的任务。

阶段和每周节奏与教程《备考路线：从零到三科过线》(rk-start-04) 一致：
基础（约 40%）→ 真题（约 25%）→ 案例 + 论文（约 25%）→ 冲刺（最后 2～3 周），考后是成绩与证书。
函数名和返回结构与 gongkao.planner 相同，首页、复习计划页按当前考试选用。
"""

from datetime import date, timedelta
from urllib.parse import quote

PHASE_INFO = {
    "base": {
        "name": "基础学习",
        "goal": "按系统教程的顺序学完综合知识各门课，每课学完做对应的章节题；计算题天天练。",
        "focus": ["每天 1 节教程 + 章节刷题", "计算题专练每天 10 道", "周五练 1 道案例，周日准备论文项目素材"],
    },
    "real": {
        "name": "真题强化",
        "goal": "综合知识真题按年份限时做，错题按遗忘曲线复习；案例和论文同步推进。",
        "focus": ["每周 2～3 套真题卷（限时 150 分钟）", "案例课程一课一练", "每周写 1 篇论文"],
    },
    "case": {
        "name": "案例与论文",
        "goal": "按题型集中练案例，每周 2 篇论文；综合知识靠错题本和闪卡保持手感。",
        "focus": ["每天 1 道案例题，限时 25 分钟", "每周 2 篇论文，请 AI 按评分维度批改", "错题本、闪卡不断"],
    },
    "sprint": {
        "name": "考前冲刺",
        "goal": "按机考节奏全真模拟，高频知识点过三遍，论文高频主题各备一份提纲。",
        "focus": ["每周 1 次 240 分钟整场机考模拟", "案例高频清单、易混知识点反复过", "考前 3 天只复习、不刷新题"],
    },
    "after": {
        "name": "成绩与证书",
        "goal": "考完先放松，记下估分；关注成绩公布和证书领取通知。",
        "focus": ["趁记忆清楚记下三科估分和论文题目", "成绩一般在考后 1～2 个月公布", "通过后按考区通知领取证书"],
    },
}

# 综合知识课程按教程顺序学；案例、论文单独排
ZH_COURSES = ["rk-start", "rk-hw", "rk-db", "rk-se", "rk-arch", "rk-new", "rk-sec", "rk-pm", "rk-law"]
COURSE_MODULE = {
    "rk-hw": "计算机系统", "rk-db": "信息系统与数据库", "rk-se": "软件工程", "rk-arch": "系统架构设计",
    "rk-new": "架构实践与新技术", "rk-sec": "信息安全", "rk-pm": "项目管理与数学", "rk-law": "知识产权与标准化",
}

RHYTHM = {
    "base": [("一", "教程 + 刷题"), ("二", "教程 + 刷题"), ("三", "教程 + 刷题"), ("四", "教程 + 刷题"),
             ("五", "案例 1 道"), ("六", "真题半套"), ("日", "论文 · 复盘")],
    "real": [("一", "真题整套"), ("二", "教程 · 专项"), ("三", "真题整套"), ("四", "教程 · 专项"),
             ("五", "案例 1 道"), ("六", "真题整套"), ("日", "论文 · 复盘")],
    "case": [("一", "案例"), ("二", "案例 · 论文课"), ("三", "案例 · 刷题"), ("四", "案例 · 论文课"),
             ("五", "案例"), ("六", "真题整套"), ("日", "论文 · 复盘")],
    "sprint": [("一", "模考 · 案例"), ("二", "模考 · 案例"), ("三", "论文限时"), ("四", "模考 · 案例"),
               ("五", "模考 · 案例"), ("六", "整场机考"), ("日", "论文提纲 · 复盘")],
    "after": [("一", "休息"), ("二", "休息"), ("三", "休息"), ("四", "休息"), ("五", "休息"), ("六", "休息"), ("日", "休息")],
}

FORM = [
    {"key": "exam_date", "label": "考试日期", "type": "date"},
    {"key": "start_date", "label": "开始备考日期", "type": "date"},
    {"key": "daily_hours", "label": "每天学习时长（小时）", "type": "number"},
]


def _d(s, fallback):
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return fallback


def _dates(settings, today):
    start = _d(settings.get("start_date"), today)
    exam = _d(settings.get("exam_date"), None)
    if exam is None:
        exam = max(start, today) + timedelta(days=180)
    return min(start, exam), exam


def _split(start, end, keys, ratios):
    """把 [start, end] 按比例切成若干段，每段至少 1 天；最后一段吃掉剩余天数。"""
    total = (end - start).days + 1
    out, cursor = [], start
    if total <= 0:
        return out
    for i, (k, r) in enumerate(zip(keys, ratios)):
        if cursor > end:
            break
        seg_end = end if i == len(keys) - 1 else min(end, cursor + timedelta(days=max(1, round(total * r)) - 1))
        out.append({"key": k, "start": cursor, "end": seg_end})
        cursor = seg_end + timedelta(days=1)
    return out


def phases(settings, today):
    start, exam = _dates(settings, today)
    last = exam - timedelta(days=1)
    total = (last - start).days + 1
    if total >= 28:
        # 冲刺固定为最后 2～3 周（总时长的 10%，14～21 天），其余按 40 : 25 : 25 分
        sprint = min(21, max(14, round(total * 0.1)))
        segs = _split(start, last - timedelta(days=sprint), ["base", "real", "case"], [0.45, 0.28, 0.27])
        segs.append({"key": "sprint", "start": last - timedelta(days=sprint - 1), "end": last})
    elif total > 0:
        segs = _split(start, last, ["real", "sprint"], [0.5, 0.5])
    else:
        segs = []
    segs.append({"key": "after", "start": exam, "end": exam + timedelta(days=60)})
    out = []
    for s in segs:
        info = PHASE_INFO[s["key"]]
        out.append({
            "key": s["key"], "name": info["name"], "goal": info["goal"], "focus": info["focus"],
            "exam": "软考",
            "start": s["start"].isoformat(), "end": s["end"].isoformat(),
            "days": (s["end"] - s["start"]).days + 1,
            "status": "done" if s["end"] < today else ("now" if s["start"] <= today else "next"),
        })
    return out


def current_phase(settings, today):
    ps = phases(settings, today)
    p = next((x for x in ps if x["status"] == "now"), None) or next((x for x in ps if x["status"] == "next"), ps[-1])
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    return dict(p, day_index=max(0, (today - start).days) + 1, days_left=max(0, (end - today).days))


def milestones(settings, today):
    _, exam = _dates(settings, today)
    items = [
        (exam - timedelta(days=70), "报名", "上半年考试一般 3～4 月由各省分别报名，时间不统一，以本省人事考试网为准", False),
        (exam - timedelta(days=7), "打印准考证", "考前一周左右开放，确认机考批次、场次和考点", False),
        (exam, "考试", "上午综合知识 + 案例分析 240 分钟，下午论文 120 分钟，机考", True),
        (exam + timedelta(days=50), "成绩公布", "一般在考后 1～2 个月，在中国计算机技术职业资格网查询", False),
        (exam + timedelta(days=150), "证书领取", "合格名单公示后，按考区通知领取纸质证书或下载电子证书", False),
    ]
    return [{"date": d.isoformat(), "title": t, "note": n, "days_left": (d - today).days, "exam_day": e}
            for d, t, n, e in items]


def rhythm(settings, today):
    key = current_phase(settings, today)["key"]
    return [{"day": d, "label": t} for d, t in RHYTHM[key]]


def _n(base, factor):
    return max(5, int(round(base * factor / 5.0)) * 5)


def _practice(module, n):
    return f"#/practice?module={quote(module)}&count={n}"


def _next(next_lessons, courses):
    """courses 里按顺序第一节还没学的课。"""
    for cid in courses:
        nl = (next_lessons or {}).get(cid)
        if nl:
            return cid, nl
    return None, None


def tasks_for_day(settings, d, next_lessons=None):
    """根据所处阶段和星期几生成当天任务。next_lessons 为 None 时（预览未来几天）不指向具体的课。"""
    ps = phases(settings, d)
    p = next((x for x in ps if date.fromisoformat(x["start"]) <= d <= date.fromisoformat(x["end"])), None)
    key = p["key"] if p else "base"
    try:
        hours = float(settings.get("daily_hours") or 3)
    except ValueError:
        hours = 3
    f = max(0.5, min(2.5, hours / 3))
    wd = d.weekday()
    _, exam = _dates(settings, d)
    t = []

    def add(title, module, link, minutes):
        t.append({"title": title, "module": module, "link": link, "minutes": minutes})

    def lesson(courses, fallback_title, fallback_link, module="教程"):
        cid, nl = _next(next_lessons, courses)
        if nl:
            add(f"学习教程：{nl['title']}", module, f"#/learn/{nl['id']}", nl.get("min", 20))
            return cid
        if next_lessons is None:
            add(fallback_title, module, fallback_link, 25)
        return None

    def real_paper(full):
        if full:
            add("综合知识真题整套（限时 150 分钟）+ 订正", "综合知识", "#/real", 180)
        else:
            add("综合知识真题半套（前 38 题，限时 75 分钟）+ 订正", "综合知识", "#/real", 90)

    full = f >= 1
    if d == _d(settings.get("start_date"), d) and key != "after":
        # 备考第一天：先弄清考什么、怎么学
        lesson(["rk-start"], "学习教程：软考全景", "#/learn/rk-start-01", "综合")
        add("在设置里确认考试日期和每天学习时长", "综合", "#/settings", 5)
        add(f"闪卡复习 {_n(20, f)} 张", "教程", "#/cards", 15)
        return t
    if key == "after":
        if d == exam:
            add("考试日：带好身份证和准考证，提前到考点", "综合", "#/plan", 0)
        elif (d - exam).days <= 3:
            add("趁记忆清楚，记下三科估分和论文题目", "综合", "#/memo", 15)
        return t

    if key == "base":
        if wd <= 3:
            cid = lesson(ZH_COURSES, "学习教程：综合知识下一节", "#/learn")
            mod = COURSE_MODULE.get(cid or "", "")
            n = _n(20, f)
            add(f"{mod or '综合知识'} 章节刷题 {n} 题", mod or "综合知识", _practice(mod or "全部", n), 30)
            add("计算题专练 10 道", "综合知识", "#/calc", 15)
        elif wd == 4:
            lesson(["rk-case"], "学习教程：案例分析", "#/learn/rk-case", "案例分析")
            add("案例练习 1 道（限时 40 分钟）+ 对照参考答案", "案例分析", "#/case", 50)
        elif wd == 5:
            real_paper(False)
        else:
            started = (d - _d(settings.get("start_date"), d)).days
            if started >= 21:
                add("论文 1 篇（限时 120 分钟打字）", "论文", "#/paper", 120)
            else:
                lesson(["rk-paper"], "学习教程：论文写作", "#/learn/rk-paper", "论文")
                add("论文：整理“我的项目素材”", "论文", "#/paper", 30)
            add("复盘本周错题", "综合知识", "#/wrong", 20)
    elif key == "real":
        if wd in (0, 2, 5):
            real_paper(full)
        elif wd in (1, 3):
            cid = lesson(ZH_COURSES, "学习教程：综合知识下一节", "#/learn")
            mod = COURSE_MODULE.get(cid or "", "")
            n = _n(30, f)
            add(f"{mod or '薄弱模块'} 专项刷题 {n} 题", mod or "综合知识", _practice(mod or "全部", n), 40)
            add("计算题专练 10 道", "综合知识", "#/calc", 15)
        elif wd == 4:
            lesson(["rk-case"], "学习教程：案例分析", "#/learn/rk-case", "案例分析")
            add("案例练习 1 道（限时 25 分钟）", "案例分析", "#/case", 40)
        else:
            add("论文 1 篇（限时 120 分钟打字）", "论文", "#/paper", 120)
            add("复盘本周错题", "综合知识", "#/wrong", 20)
    elif key == "case":
        if wd <= 4:
            if wd in (1, 3):
                lesson(["rk-paper", "rk-case"], "学习教程：论文写作", "#/learn/rk-paper", "论文")
            else:
                lesson(["rk-case"], "学习教程：案例分析", "#/learn/rk-case", "案例分析")
            add("案例练习 1 道（限时 25 分钟）+ 对照参考答案", "案例分析", "#/case", 40)
            if wd == 2:
                add(f"综合知识专项刷题 {_n(20, f)} 题", "综合知识", _practice("全部", _n(20, f)), 30)
            if wd == 0 and full:
                add("论文 1 篇（限时 120 分钟打字）", "论文", "#/paper", 120)
        elif wd == 5:
            real_paper(full)
        else:
            add("论文 1 篇（限时 120 分钟打字），请 AI 批改", "论文", "#/paper", 130)
            add("复盘本周错题", "综合知识", "#/wrong", 20)
    else:  # sprint
        left = (exam - d).days
        if left <= 3:
            add("只复习不刷新题：错题本过一遍", "综合知识", "#/wrong", 40)
            add("学习教程：案例冲刺高频知识点清单", "案例分析", "#/learn/rk-case-10", 30)
            add("看一遍论文高频主题提纲", "论文", "#/learn/rk-paper-10", 20)
            if left == 1:
                add("准备好身份证、准考证，确认考点和交通", "综合", "#/plan", 10)
        elif wd == 5:
            add("整场机考模拟（240 分钟：综合知识 + 案例）", "综合知识", "#/exam", 250)
        elif wd == 2:
            add("论文限时 120 分钟", "论文", "#/paper", 120)
        elif wd == 6:
            add("论文高频主题提纲各写一份", "论文", "#/learn/rk-paper-10", 40)
            add("复盘本周错题", "综合知识", "#/wrong", 30)
        else:
            add("限时模考（综合知识）", "综合知识", "#/mock", 45)
            add("案例练习 1 道（限时 25 分钟）", "案例分析", "#/case", 40)
            if wd == 0:
                add("学习教程：案例冲刺高频知识点清单", "案例分析", "#/learn/rk-case-10", 30)
    add(f"闪卡复习 {_n(20, f)} 张", "教程", "#/cards", 15)
    return t


def week_preview(settings, today):
    out = []
    for i in range(7):
        d = today + timedelta(days=i)
        r = dict(rhythm(settings, d)[d.weekday()])
        out.append({"date": d.isoformat(), "weekday": "一二三四五六日"[d.weekday()], "focus": r["label"],
                    "tasks": [x["title"] for x in tasks_for_day(settings, d)]})
    return out
