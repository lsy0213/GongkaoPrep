"""复习计划：按考试日期把备考期切成阶段，并给每天生成任务。

国考段：基础入门 → 专项突破 → 模考冲刺
省考段：查漏补缺 → 强化提升 → 省考冲刺
最后是面试准备。
"""

from datetime import date, timedelta

# 一周内的模块轮换：周一到周日
WEEK_ROTATION = ["言语理解与表达", "数量关系", "判断推理", "资料分析", "政治理论+常识判断", "申论", "复盘"]

# 计划里的科目 → 教程课程 id（content/course/index.json）
COURSE_ID = {
    "政治理论": "politics",
    "常识判断": "common",
    "政治理论+常识判断": "politics",
    "言语理解与表达": "verbal",
    "数量关系": "math",
    "判断推理": "reason",
    "资料分析": "data",
    "申论": "essay",
    "面试": "interview",
    "复盘": "strategy",
}


def _lesson_task(next_lessons, mod):
    """“学习教程”任务：指向该课程里下一节没学的课；没有进度信息时指向课程目录。"""
    cid = COURSE_ID[mod]
    nl = (next_lessons or {}).get(cid)
    if nl:
        return f"学习教程：{nl['title']}", f"#/learn/{nl['id']}", nl["min"]
    return f"学习教程：{mod}", f"#/learn/{cid}", 40

PHASE_INFO = {
    "base": {
        "name": "基础入门",
        "goal": "认识每种题型，学会基本解法，建立做题的时间感。",
        "focus": ["每个模块先读教程再做入门题", "资料分析公式和速算每天练", "开始积累申论素材和规范表述"],
    },
    "special": {
        "name": "专项突破",
        "goal": "按模块集中刷题，弄清每类题的常考套路，把正确率稳住。",
        "focus": ["优先提分快的资料分析、判断推理", "每天整理错题并写错因", "申论按题型逐个练"],
    },
    "sprint": {
        "name": "模考冲刺",
        "goal": "限时套题训练，固定做题顺序和时间分配，查漏补缺。",
        "focus": ["每周至少 2 次限时模考", "大作文完整成稿", "时政和政治理论集中复习"],
    },
    "review": {
        "name": "查漏补缺",
        "goal": "复盘国考，把暴露出的薄弱模块补上，熟悉本省省考题型差异。",
        "focus": ["国考后先休息 1–2 天再复盘", "研究报考省份的题型和题量", "错题本全部过一遍"],
    },
    "boost": {
        "name": "强化提升",
        "goal": "提高做题速度和难题处理能力，申论向省考风格靠拢。",
        "focus": ["数量关系挑会做的题型练", "资料分析追求 1 分钟 1 题", "关注本省政策和新闻"],
    },
    "final": {
        "name": "省考冲刺",
        "goal": "按省考真实结构模考，调整状态迎考。",
        "focus": ["严格按考试时间模考", "考前一周以回顾为主，不再刷新题", "准备好证件和考场物品"],
    },
    "interview": {
        "name": "面试准备",
        "goal": "笔试结束后转入结构化面试训练。",
        "focus": ["每天练 2 道题并计时作答", "找人模拟或录音回听", "关注成绩和面试名单公告"],
    },
}


def _d(s, fallback):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback


def _split(start, end, keys, ratios):
    """把 [start, end] 按比例切成若干段，每段至少 1 天。"""
    total = (end - start).days + 1
    out = []
    if total <= 0:
        return out
    cursor = start
    for i, (k, r) in enumerate(zip(keys, ratios)):
        if i == len(keys) - 1:
            seg_end = end
        else:
            n = max(1, round(total * r))
            seg_end = min(end, cursor + timedelta(days=n - 1))
        if cursor > end:
            break
        out.append({"key": k, "start": cursor, "end": seg_end})
        cursor = seg_end + timedelta(days=1)
    return out


def phases(settings, today):
    start = _d(settings.get("start_date"), today)
    gk = _d(settings.get("guokao_date"), date(today.year, 11, 29))
    sk = _d(settings.get("shengkao_date"), gk + timedelta(days=105))
    segs = []
    if start < gk:
        segs += [dict(s, exam="国考") for s in _split(start, gk - timedelta(days=1),
                                                      ["base", "special", "sprint"], [0.35, 0.4, 0.25])]
    s2_start = max(start, gk + timedelta(days=1))
    if s2_start < sk:
        # 如果国考前没有备考期，省考段就从基础开始
        gap = (sk - s2_start).days
        if start < gk and gap < 21:
            # 单独命题省份的省考往往紧跟国考，中间只安排一个冲刺阶段
            keys, ratios = ["final"], [1]
        elif start < gk:
            keys, ratios = ["review", "boost", "final"], [0.3, 0.45, 0.25]
        else:
            keys, ratios = ["base", "special", "sprint"], [0.35, 0.4, 0.25]
        segs += [dict(s, exam="省考") for s in _split(s2_start, sk - timedelta(days=1), keys, ratios)]
    segs.append({"key": "interview", "start": sk + timedelta(days=1), "end": sk + timedelta(days=60), "exam": "面试"})
    out = []
    for s in segs:
        info = PHASE_INFO[s["key"]]
        out.append({
            "key": s["key"],
            "name": info["name"],
            "goal": info["goal"],
            "focus": info["focus"],
            "exam": s["exam"],
            "start": s["start"].isoformat(),
            "end": s["end"].isoformat(),
            "days": (s["end"] - s["start"]).days + 1,
            "status": "done" if s["end"] < today else ("now" if s["start"] <= today else "next"),
        })
    return out


def current_phase(settings, today):
    ps = phases(settings, today)
    for p in ps:
        if p["status"] == "now":
            break
    else:
        p = next((x for x in ps if x["status"] == "next"), ps[-1])
    end = date.fromisoformat(p["end"])
    start = date.fromisoformat(p["start"])
    p = dict(p)
    p["day_index"] = max(0, (today - start).days) + 1
    p["days_left"] = max(0, (end - today).days)
    return p


def milestones(settings, today):
    gk = _d(settings.get("guokao_date"), date(today.year, 11, 29))
    sk = _d(settings.get("shengkao_date"), gk + timedelta(days=105))
    items = [
        (gk - timedelta(days=45), "国考公告、报名", "一般在笔试前 6 周左右，报名约 10 天，以国家公务员局公告为准"),
        (gk, "国考笔试", "行测 120 分钟 + 申论 180 分钟，以准考证为准"),
        (gk + timedelta(days=40), "国考成绩公布", "通常在次年 1 月上中旬"),
        (gk + timedelta(days=80), "国考面试", "一般在次年 2–3 月，各招录机关分别组织"),
        (sk - timedelta(days=55), "省考公告、报名", "多省联考通常在 1 月发公告；单独命题省份时间不同"),
        (sk, "省考笔试", "以报考省份人事考试网公告为准"),
        (sk + timedelta(days=50), "省考面试", "通常在笔试后 1–2 个月"),
    ]
    out = []
    for d, title, note in sorted(items, key=lambda x: x[0]):
        out.append({
            "date": d.isoformat(),
            "title": title,
            "note": note,
            "days_left": (d - today).days,
            "exam_day": title.endswith("笔试"),
        })
    return out


def _n(base, factor):
    return max(5, int(round(base * factor / 5.0)) * 5)


def _practice(module, n):
    from urllib.parse import quote
    return f"#/practice?module={quote(module)}&count={n}"


def tasks_for_day(settings, d, next_lessons=None):
    """根据所处阶段和星期几生成当天任务。"""
    p = None
    for ph in phases(settings, d):
        if date.fromisoformat(ph["start"]) <= d <= date.fromisoformat(ph["end"]):
            p = ph
            break
    key = p["key"] if p else "base"
    try:
        hours = float(settings.get("daily_hours") or 4)
    except ValueError:
        hours = 4
    f = max(0.5, min(2.5, hours / 4))
    mod = WEEK_ROTATION[d.weekday()]
    t = []

    def add(title, module, link, minutes):
        t.append({"title": title, "module": module, "link": link, "minutes": minutes})

    if d == _d(settings.get("start_date"), d):
        add("备考第一天：学教程《公考全景》，了解考什么、怎么学", "综合", "#/learn/start-01", 15)

    if key == "interview":
        title, link, mins = _lesson_task(next_lessons, "面试")
        add(title, "面试", link, mins)
        add(f"面试真题限时作答 {2 if f < 1.5 else 3} 道（每题 3 分钟）", "面试", "#/interview", 40)
        add("读 1 篇评论文章，提炼观点用于综合分析题", "阅读积累", "#/notes?tab=read", 25)
        add("把今天的作答录音回听并改进", "面试", "#/interview", 20)
        return t

    practice_mod = {"政治理论+常识判断": "常识判断", "申论": None, "复盘": None}.get(mod, mod)

    if key == "base" or key == "review":
        if mod == "申论":
            title, link, mins = _lesson_task(next_lessons, "申论")
            add(title, "申论", link, mins)
            add("申论练习：完成 1 道归纳概括题", "申论", "#/essay", 40)
            add("阅读积累：读 1 篇评论文章，摘抄 3 句", "阅读积累", "#/notes?tab=read", 30)
        elif mod == "复盘":
            add("复习到期错题，写下错因", "错题", "#/wrong", 30)
            add("学习教程：行测做题顺序与时间分配", "综合", "#/learn/strategy-01", 15)
            add("迷你模考 1 套（限时）", "综合", "#/mock", 40)
            add("写本周小结并打卡", "综合", "#/plan", 10)
        else:
            title, link, mins = _lesson_task(next_lessons, mod)
            add(title, mod, link, mins)
            if mod == "政治理论+常识判断":
                add(f"政治理论练习 {_n(10, f)} 题", "政治理论", _practice("政治理论", _n(10, f)), 15)
            add(f"{practice_mod} 专项练习 {_n(15, f)} 题", practice_mod, _practice(practice_mod, _n(15, f)), 30)
            add("资料分析速算 10 分钟", "资料分析", "#/speed", 10)
            add("阅读积累：读 1 篇评论文章，摘抄 3 句", "阅读积累", "#/notes?tab=read", 25)
        add(f"闪卡复习 {_n(20, f)} 张（常识 / 政治 / 成语）", "积累", "#/cards", 15)
        return t

    if key in ("special", "boost"):
        if mod == "申论":
            add("申论练习：综合分析或提出对策 1 题", "申论", "#/essay", 45)
            add("申论练习：贯彻执行（公文）1 题", "申论", "#/essay", 45)
            add("大作文：列 1 个提纲（标题 + 分论点）", "申论", "#/essay", 30)
        elif mod == "复盘":
            add("迷你模考 1 套（限时）", "综合", "#/mock", 40)
            add("本周错题全部重做", "错题", "#/wrong", 40)
            add("写本周小结并打卡", "综合", "#/plan", 10)
        else:
            if mod == "政治理论+常识判断":
                add(f"政治理论专项 {_n(20, f)} 题", "政治理论", _practice("政治理论", _n(20, f)), 25)
            add(f"{practice_mod} 专项练习 {_n(30, f)} 题", practice_mod, _practice(practice_mod, _n(30, f)), 45)
            second = "资料分析" if practice_mod != "资料分析" else "判断推理"
            add(f"{second} 巩固练习 {_n(10, f)} 题", second, _practice(second, _n(10, f)), 20)
            add("资料分析速算 10 分钟", "资料分析", "#/speed", 10)
        add("复习到期错题", "错题", "#/wrong", 20)
        add(f"闪卡复习 {_n(20, f)} 张", "积累", "#/cards", 15)
        add("阅读积累：读 1 篇评论文章", "阅读积累", "#/notes?tab=read", 20)
        return t

    # sprint / final
    if mod == "申论":
        add("申论限时套题：大作文完整成稿（60 分钟）", "申论", "#/essay", 70)
        add("对照参考要点自评，补充素材", "申论", "#/essay", 20)
    elif mod == "复盘":
        add("限时模考 1 套并复盘", "综合", "#/mock", 60)
        add("错题本全部过一遍", "错题", "#/wrong", 40)
        add("写本周小结并打卡", "综合", "#/plan", 10)
    elif d.weekday() in (0, 2, 4):
        add("迷你模考 1 套（严格计时）", "综合", "#/mock", 45)
        add("模考复盘：每道错题写错因", "错题", "#/wrong", 30)
        add(f"{practice_mod} 查漏练习 {_n(15, f)} 题", practice_mod, _practice(practice_mod, _n(15, f)), 20)
    else:
        add(f"{practice_mod} 限时专项 {_n(20, f)} 题", practice_mod, _practice(practice_mod, _n(20, f)), 30)
        add("申论：1 道小题限时作答", "申论", "#/essay", 40)
    add("政治理论 / 时政闪卡", "政治理论", "#/cards", 15)
    add("资料分析速算 10 分钟", "资料分析", "#/speed", 10)
    return t


def week_preview(settings, today):
    out = []
    for i in range(7):
        d = today + timedelta(days=i)
        out.append({
            "date": d.isoformat(),
            "weekday": "一二三四五六日"[d.weekday()],
            "focus": WEEK_ROTATION[d.weekday()],
            "tasks": [x["title"] for x in tasks_for_day(settings, d)],
        })
    return out
