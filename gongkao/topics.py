"""考点：把每道题按题干关键词归到比“题型”更细的考点，并对应到教程里讲这个考点的课。

题库里只有“模块 / 题型”两级（比如 资料分析 / 资料分析、数量关系 / 数学运算），做弱项诊断不够细：
“资料分析正确率 60%”不知道该补哪一块，“隔年增长率正确率 30%”就知道去学哪一课、练哪类题。
规则是按真题题干的常见问法写的关键词，归不进任何规则的题落到该题型的“其他”考点。
"""

import re
from functools import lru_cache

# (考点 id, 模块, 题型（None = 不限）, 考点名, 题干正则, 教程课 id)。同一模块内按顺序匹配，先匹配到的算。
RULES = [
    # ---- 资料分析
    ("data-gap", "资料分析", None, "间隔增长", r"隔年|间隔|比\s*20\d\d\s*年(同期)?(增长|下降|提高)", "data-08"),
    ("data-annual", "资料分析", None, "年均增长", r"年均(增长|增速|增长率)?|平均每年", "data-08"),
    ("data-mixed", "资料分析", None, "混合增长", r"(上半年|全年|一季度|前.季度).*(增速|增长率).*(下半年|二季度|后)", "data-08"),
    ("data-share", "资料分析", None, "比重", r"比重|占比|所占|占.{0,12}(的|比例)|百分点", "data-05"),
    ("data-rate", "资料分析", None, "增长率", r"增长率|增速|增幅|同比(增长|下降)了?\s*(约|大约)?\s*(多少|百分之)|降幅", "data-04"),
    ("data-amount", "资料分析", None, "增长量", r"增长量|增加量|(增加|增长|减少|下降)了?\s*(约|大约)?\s*多少(?!%|个百分)", "data-04"),
    ("data-base", "资料分析", None, "基期量", r"上年(同期)?|去年(同期)?|20\d\d\s*年.{0,20}(约|大约)?(为|是)多少", "data-04"),
    ("data-avg", "资料分析", None, "平均数", r"平均|人均|户均|每(个|家|人|户|名)", "data-05"),
    ("data-times", "资料分析", None, "倍数", r"倍", "data-05"),
    ("data-judge", "资料分析", None, "综合分析", r"(能够|可以).{0,8}推出|说法正确|正确的(是|有)|不正确|错误的是|下列说法", "data-06"),
    ("data-other", "资料分析", None, "资料分析·其他", r"", "data-06"),
    # ---- 数量关系
    ("math-seq", "数量关系", "数字推理", "数字推理", r"", "math-18"),
    ("math-prob", "数量关系", None, "概率", r"概率|可能性", "math-14"),
    ("math-perm", "数量关系", None, "排列组合", r"排列|组合|(多少|几)种|不同的(方案|选法|排法|安排)", "math-06"),
    ("math-work", "数量关系", None, "工程问题", r"工程|完工|合作|单独(做|完成)|效率|工期", "math-03"),
    ("math-travel", "数量关系", None, "行程问题", r"速度|相遇|追及|追上|行驶|千米|公里|米/秒|顺流|逆流|跑道|出发", "math-04"),
    ("math-profit", "数量关系", None, "经济利润", r"利润|成本|售价|进价|定价|打.折|折扣|盈利|亏损|促销", "math-05"),
    ("math-solution", "数量关系", None, "溶液问题", r"浓度|溶液|盐水|糖水|酒精", "math-12"),
    ("math-geo", "数量关系", None, "几何问题", r"面积|体积|周长|半径|直径|三角形|正方形|长方形|长方体|正方体|圆|棱|角度", "math-07"),
    ("math-set", "数量关系", None, "容斥问题", r"都不|都(会|喜欢|参加)|既.{1,12}又|两项都|三项都|只.{1,6}一项", "math-08"),
    ("math-extreme", "数量关系", None, "最值问题", r"至少|最多|最少|最大|最小", "math-16"),
    ("math-misc", "数量关系", None, "年龄日期周期", r"年龄|岁|星期|日期|钟|植树|周期|牛吃草", "math-17"),
    ("math-other", "数量关系", None, "数学运算·其他", r"", "math-02"),
    # ---- 判断推理
    ("reason-fig", "判断推理", "图形推理", "图形推理", r"", "reason-01"),
    ("reason-def", "判断推理", "定义判断", "定义判断", r"", "reason-04"),
    ("reason-ana", "判断推理", "类比推理", "类比推理", r"", "reason-05"),
    ("reason-weaken", "判断推理", "逻辑判断", "削弱型论证", r"削弱|质疑|反驳|不能支持|动摇", "reason-16"),
    ("reason-strengthen", "判断推理", "逻辑判断", "加强型论证", r"加强|支持|前提|假设|解释|论证.{0,4}(成立|有效)", "reason-16"),
    ("reason-truth", "判断推理", "逻辑判断", "真假推理", r"(只有|仅有).{0,4}(一|两)(句|个|人).{0,6}(真|假)|说了真话|说了假话|为真.*为假", "reason-07"),
    ("reason-trans", "判断推理", "逻辑判断", "翻译推理", r"如果|只有.{1,20}才|除非|那么|推出|必然", "reason-06"),
    ("reason-arrange", "判断推理", "逻辑判断", "分析推理", r"", "reason-15"),
    ("reason-other", "判断推理", None, "判断推理·其他", r"", "reason-08"),
    # ---- 言语理解与表达
    ("verbal-idiom", "言语理解与表达", "逻辑填空", "成语辨析", r"__IDIOM__", "verbal-04"),
    ("verbal-word", "言语理解与表达", "逻辑填空", "实词辨析", r"", "verbal-03"),
    ("verbal-order", "言语理解与表达", "语句表达", "语句排序", r"重新排列|排序|语序正确|排列.{0,4}(最|正确)|①", "verbal-12"),
    ("verbal-fillsent", "言语理解与表达", "语句表达", "语句填空", r"", "verbal-07"),
    ("verbal-intent", "言语理解与表达", "片段阅读", "意图判断", r"意在|旨在|意图|想要(说明|表达)|用意|目的是", "verbal-11"),
    ("verbal-title", "言语理解与表达", "片段阅读", "标题与接语", r"标题|接下来|后文|下文|文段(之后|后面)", "verbal-06"),
    ("verbal-detail", "言语理解与表达", "片段阅读", "细节理解", r"(符合|不符合|理解(正确|错误)|说法(正确|错误)|不正确|错误)", "verbal-06"),
    ("verbal-main", "言语理解与表达", "片段阅读", "中心理解", r"", "verbal-05"),
    ("verbal-other", "言语理解与表达", None, "言语·其他", r"", "verbal-01"),
    # ---- 常识判断
    ("common-law", "常识判断", None, "法律常识", r"法|宪法|刑|罪|民事|合同|诉讼|行政(处罚|许可|复议)|侵权|继承|物权|仲裁|犯罪", "common-02"),
    ("common-econ", "常识判断", None, "经济常识", r"经济|市场|通货|货币|GDP|财政|税|利率|汇率|供求|价格|金融|股", "common-05"),
    ("common-hist", "常识判断", None, "历史常识", r"朝|皇帝|战争|战役|历史|古代|革命|起义|条约|运动|变法|王朝", "common-06"),
    ("common-geo", "常识判断", None, "地理常识", r"气候|河流|山脉|地形|高原|盆地|海拔|季风|洋流|板块|地震|火山|纬度", "common-07"),
    ("common-sci", "常识判断", None, "科技常识", r"科学|物理|化学|生物|技术|卫星|航天|细胞|基因|病毒|能源|电|光|声|原理|反应", "common-08"),
    ("common-hum", "常识判断", None, "人文常识", r"诗|词|作者|文学|小说|成语|节日|戏|书法|绘画|典故|称谓|乐", "common-09"),
    ("common-other", "常识判断", None, "常识·其他", r"", "common-01"),
    # ---- 政治理论
    ("pol-xi", "政治理论", None, "习近平新时代中国特色社会主义思想", r"习近平|新时代|新思想", "politics-02"),
    ("pol-20th", "政治理论", None, "二十大与中国式现代化", r"二十大|中国式现代化|二十届", "politics-03"),
    ("pol-phil", "政治理论", None, "马克思主义哲学", r"哲学|矛盾|辩证|唯物|唯心|意识|实践|认识|规律|量变|质变", "politics-05"),
    ("pol-party", "政治理论", None, "党史党建", r"党史|党的建设|从严治党|会议|决议|党章|纪律", "politics-08"),
    ("pol-econ", "政治理论", None, "经济思想与发展理念", r"新发展理念|新发展格局|新质生产力|高质量发展|共同富裕", "politics-10"),
    ("pol-other", "政治理论", None, "时政与其他", r"", "politics-13"),
]

_COMPILED = [(tid, mod, sub, name, re.compile(rx) if rx and rx != "__IDIOM__" else rx, lesson)
             for tid, mod, sub, name, rx, lesson in RULES]
BY_ID = {tid: {"id": tid, "module": mod, "sub": sub, "name": name, "lesson": lesson} for tid, mod, sub, name, _rx, lesson in RULES}
IDIOM_RE = re.compile(r"^[一-鿿]{4}$")


def _idiom_options(options):
    """逻辑填空的选项里大多是四字成语（多空题按“、”拆开看）。"""
    if not options:
        return False
    words = [w for o in options for w in re.split(r"[，,、\s]+", o or "") if w]
    return bool(words) and sum(1 for w in words if IDIOM_RE.match(w)) >= len(words) * 0.6


def classify(module, sub, stem, options=None):
    """返回考点 id；不认识的模块返回空串。"""
    stem = stem or ""
    for tid, mod, rsub, _name, rx, _lesson in _COMPILED:
        if mod != module or (rsub and rsub != sub):
            continue
        if rx == "__IDIOM__":
            if _idiom_options(options):
                return tid
            continue
        if not rx or rx.search(stem):
            return tid
    return ""


def info(tid):
    return BY_ID.get(tid)


@lru_cache(maxsize=1)
def _lesson_titles():
    import json

    from .paths import content_dir

    try:
        index = json.loads((content_dir() / "course" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {lesson["id"]: lesson["title"] for c in index.get("courses", []) for lesson in c.get("lessons", [])}


def lesson_title(lesson_id):
    return _lesson_titles().get(lesson_id, "")


def all_topics():
    return [{**BY_ID[tid], "lesson_title": lesson_title(BY_ID[tid]["lesson"])} for tid, *_ in RULES]
