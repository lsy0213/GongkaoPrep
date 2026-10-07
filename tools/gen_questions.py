"""生成内置题库里的数量关系、资料分析计算题 → content/questions_more/gen_*.json。

每个题型一个模板：随机取一组“能算出整齐答案”的数，答案由程序算出（不会错），
干扰项取常见错误做法的结果（漏加、乘除颠倒、多算一次……），解析写出完整步骤和这类题的通用方法。
随机种子固定，重复运行生成的题目不变；改了模板再运行即可。

    python tools/gen_questions.py
"""

import json
import math
import sys
import os
import random
from fractions import Fraction
from itertools import permutations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "content", "questions_more")
WEEK = "一二三四五六日"
NAMES = [("甲", "乙"), ("小王", "小李"), ("A 队", "B 队"), ("甲车间", "乙车间"), ("老张", "老刘")]


def fmt(x, nd=2):
    """数字显示：整数不带小数点，否则保留 nd 位并去掉末尾 0。"""
    if isinstance(x, Fraction):
        x = float(x)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s


def options(rng, ans, wrongs, unit="", nd=2, spread=None):
    """答案 + 干扰项 → (四个选项文字, 正确下标)。干扰项不够时按答案上下浮动补齐。"""
    a = fmt(ans, nd) + unit
    seen = {a}
    opts = []
    for w in wrongs:
        if w is None or (isinstance(w, (int, float, Fraction)) and w <= 0):
            continue
        s = fmt(w, nd) + unit if not isinstance(w, str) else w
        if s not in seen:
            seen.add(s)
            opts.append(s)
        if len(opts) == 3:
            break
    step = spread or max(1, abs(float(ans)) * 0.1)
    k = 1
    while len(opts) < 3:
        for cand in (ans + step * k, ans - step * k):
            if cand > 0 and len(opts) < 3:
                s = fmt(cand, nd) + unit
                if s not in seen:
                    seen.add(s)
                    opts.append(s)
        k += 1
    allv = opts + [a]
    # 数值选项按大小排（真题习惯），非数值随机
    try:
        allv.sort(key=lambda s: float("".join(c for c in s if c.isdigit() or c in ".-") or 0))
    except ValueError:
        rng.shuffle(allv)
    return allv, allv.index(a)


# ================================================================ 数量关系

def t_work_together(rng):
    while True:
        a, b = rng.randint(6, 40), rng.randint(6, 40)
        if a != b and (a * b) % (a + b) == 0:
            break
    x, y = rng.choice(NAMES)
    t = a * b // (a + b)
    total = a * b // math.gcd(a, b)
    stem = f"一项工程，{x}单独做需要 {a} 天完成，{y}单独做需要 {b} 天完成。两人合作，完成这项工程需要多少天？"
    o, k = options(rng, t, [(a + b) / 2, abs(a - b), t + 2, t - 1], " 天")
    exp = (f"赋值工作总量为 {a} 和 {b} 的最小公倍数 {total}，则{x}效率 = {total}÷{a} = {total // a}，{y}效率 = {total}÷{b} = {total // b}。\n"
           f"合作时间 = {total}÷({total // a}+{total // b}) = {t}（天）。\n\n"
           "方法：给完工时间型工程问题，赋值总量为各时间的公倍数，再求效率。易错：直接取两个时间的平均数。")
    return dict(sub="工程问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_work_leave(rng):
    while True:
        a, b = rng.randint(8, 30), rng.randint(8, 30)
        L = a * b // math.gcd(a, b)
        ea, eb = L // a, L // b
        k = rng.randint(2, min(a, b) - 2)
        rest = L - (ea + eb) * k
        if a != b and rest > 0 and rest % eb == 0:
            break
    x, y = rng.choice(NAMES)
    t = k + rest // eb
    stem = (f"一项工作，{x}单独完成需要 {a} 天，{y}单独完成需要 {b} 天。两人合作 {k} 天后，{x}因故离开，"
            f"剩下的由{y}单独完成。完成这项工作一共用了多少天？")
    o, ki = options(rng, t, [rest // eb, t + 1, t - 1, k + rest // ea], " 天")
    exp = (f"赋值总量 = {L}（{a} 与 {b} 的最小公倍数），{x}效率 {ea}，{y}效率 {eb}。\n"
           f"合作 {k} 天完成 ({ea}+{eb})×{k} = {(ea + eb) * k}，剩下 {L}-{(ea + eb) * k} = {rest}。\n"
           f"{y}单独做剩下的需要 {rest}÷{eb} = {rest // eb} 天，共 {k}+{rest // eb} = {t} 天。\n\n"
           f"易错：问的是“一共用了多少天”，要把合作的 {k} 天加上。")
    return dict(sub="工程问题", stem=stem, options=o, answer=ki, explain=exp, level=2)


def t_work_ratio(rng):
    while True:
        p, q = rng.randint(2, 6), rng.randint(2, 6)
        days = rng.randint(6, 30)
        if p != q and math.gcd(p, q) == 1 and (p + q) * days % p == 0:
            break
    x, y = rng.choice(NAMES)
    total = (p + q) * days
    t = total // p
    stem = (f"{x}、{y}两队的工作效率之比为 {p}∶{q}，两队合作 {days} 天可以完成某项工程。"
            f"若由{x}队单独完成，需要多少天？")
    o, k = options(rng, t, [total // q if total % q == 0 else None, days * 2, t + days // 2, days + p])
    o = [s + " 天" for s in o]
    exp = (f"给效率比例型：设{x}效率 {p}、{y}效率 {q}，总量 = ({p}+{q})×{days} = {total}。\n"
           f"{x}单独完成需要 {total}÷{p} = {t} 天。")
    return dict(sub="工程问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_meet(rng):
    while True:
        v1, v2 = rng.randint(3, 15) * 5, rng.randint(3, 15) * 5
        t = rng.choice([1.5, 2, 2.5, 3, 4, 5])
        d = (v1 + v2) * t
        if v1 != v2 and d == int(d):
            break
    x, y = rng.choice([("甲车", "乙车"), ("客车", "货车"), ("小王", "小李")])
    stem = (f"A、B 两地相距 {fmt(d)} 千米，{x}从 A 地、{y}从 B 地同时出发相向而行，{x}每小时行 {v1} 千米，"
            f"{y}每小时行 {v2} 千米。出发后多少小时两车相遇？")
    o, k = options(rng, t, [d / abs(v1 - v2), d / v1, d / v2, t * 2], " 小时", spread=0.5)
    exp = f"相遇时间 = 路程和 ÷ 速度和 = {fmt(d)}÷({v1}+{v2}) = {fmt(t)}（小时）。\n\n易错：用速度差是追及问题的做法。"
    return dict(sub="行程问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_chase(rng):
    while True:
        v1, v2 = rng.randint(40, 90), rng.randint(40, 90)
        if v1 > v2 + 5:
            break
    t = rng.choice([2, 3, 4, 5, 6])
    gap = (v1 - v2) * t
    stem = (f"一辆货车以每小时 {v2} 千米的速度从某地出发，一段时间后，一辆轿车以每小时 {v1} 千米的速度从同一地点出发沿同一路线追赶。"
            f"轿车出发时两车相距 {gap} 千米，轿车需要多少小时才能追上货车？")
    o, k = options(rng, t, [gap / (v1 + v2), gap / v2, t + 1, gap / v1], " 小时", spread=1)
    exp = f"追及时间 = 路程差 ÷ 速度差 = {gap}÷({v1}-{v2}) = {t}（小时）。"
    return dict(sub="行程问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_river(rng):
    while True:
        vb, vw = rng.randint(10, 30), rng.randint(2, 6)
        d = (vb + vw) * (vb - vw)
        t1, t2 = d // (vb + vw), d // (vb - vw)
        if d <= 400:
            break
    stem = f"一艘船在两港口之间航行，两港相距 {d} 千米，顺水航行需要 {t1} 小时，逆水航行需要 {t2} 小时。则水流速度是每小时多少千米？"
    o, k = options(rng, vw, [vb, vw * 2, (d / t1 + d / t2) / 2 - vw, vw + 1], " 千米")
    exp = (f"顺水速度 = {d}÷{t1} = {vb + vw}，逆水速度 = {d}÷{t2} = {vb - vw}。\n"
           f"水速 = (顺水速度 - 逆水速度)÷2 = ({vb + vw}-{vb - vw})÷2 = {vw}（千米/时）；船速 = ({vb + vw}+{vb - vw})÷2 = {vb}。\n\n"
           "公式：顺水速度 = 船速 + 水速，逆水速度 = 船速 - 水速。")
    return dict(sub="行程问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_avg_speed(rng):
    pairs = [(30, 60, 40), (40, 60, 48), (20, 30, 24), (60, 90, 72), (12, 24, 16), (15, 10, 12), (45, 90, 60), (35, 140, 56),
             (20, 80, 32), (60, 40, 48), (28, 70, 40), (36, 45, 40)]
    v1, v2, ans = rng.choice(pairs)
    stem = f"小张开车从甲地到乙地，去时平均速度为每小时 {v1} 千米，返回时沿原路平均速度为每小时 {v2} 千米。小张往返全程的平均速度是每小时多少千米？"
    o, k = options(rng, ans, [(v1 + v2) / 2, ans + 2, ans - 2], " 千米")
    exp = (f"等距离往返的平均速度 = 2v₁v₂÷(v₁+v₂) = 2×{v1}×{v2}÷({v1}+{v2}) = {ans}（千米/时）。\n\n"
           f"易错：直接求 ({v1}+{v2})÷2 = {fmt((v1 + v2) / 2)}。平均速度是总路程÷总时间，慢速走的时间更长，所以平均速度偏向慢速。")
    return dict(sub="行程问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_profit(rng):
    cost = rng.choice([80, 100, 120, 150, 160, 200, 240, 250, 300, 400])
    up = rng.choice([20, 25, 30, 40, 50, 60])
    disc = rng.choice([7, 7.5, 8, 8.5, 9])
    price = cost * (1 + up / 100)
    sell = price * disc / 10
    prof = sell - cost
    if abs(prof - round(prof, 1)) > 1e-9 or prof == 0:
        return None
    stem = (f"某商品的进价为 {cost} 元，商家按进价提高 {up}% 定价，后来打 {fmt(disc)} 折出售。"
            f"每件商品{'盈利' if prof > 0 else '亏损'}多少元？")
    ans = abs(prof)
    o, k = options(rng, ans, [abs(price - cost), abs(cost * (up / 100 - (10 - disc) / 10)) + 1, price * (10 - disc) / 10, ans * 2], " 元")
    exp = (f"定价 = {cost}×(1+{up}%) = {fmt(price)} 元；售价 = {fmt(price)}×{fmt(disc / 10)} = {fmt(sell)} 元。\n"
           f"利润 = 售价 - 进价 = {fmt(sell)}-{cost} = {fmt(prof)} 元，即{'盈利' if prof > 0 else '亏损'} {fmt(ans)} 元。\n\n"
           "经济利润问题按“进价 → 定价 → 售价 → 利润”一步步写清楚，不要把“提高 a% 再打折”简单相减。")
    return dict(sub="经济利润", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_profit_rate(rng):
    r1 = rng.choice([20, 25, 40, 50, 60, 80, 100])
    d = rng.choice([7, 7.5, 8, 9])
    rate = (1 + r1 / 100) * d / 10 - 1
    if rate <= 0:
        return None
    ans = rate * 100
    if abs(ans - round(ans, 1)) > 1e-9:
        return None
    stem = f"某商店按照 {r1}% 的预期利润率给商品定价，促销时打 {fmt(d)} 折销售。此时该商品的实际利润率是多少？"
    o, k = options(rng, ans, [r1 - (10 - d) * 10, r1 * d / 10, ans + 5, ans - 5], "%", nd=1, spread=5)
    exp = (f"设成本为 1，定价 = 1×(1+{r1}%) = {fmt(1 + r1 / 100)}，售价 = {fmt(1 + r1 / 100)}×{fmt(d / 10)} = {fmt((1 + r1 / 100) * d / 10, 3)}。\n"
           f"实际利润率 = (售价 - 成本)÷成本 = {fmt(ans, 1)}%。\n\n赋值成本为 1（或 100）是利润率题的通用方法。")
    return dict(sub="经济利润", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_solution(rng):
    while True:
        m1, m2 = rng.choice([100, 200, 300, 400, 500]), rng.choice([100, 200, 300, 400, 500, 600])
        c1, c2 = rng.choice([5, 10, 15, 20, 25, 30]), rng.choice([10, 20, 30, 40, 50])
        c = (m1 * c1 + m2 * c2) / (m1 + m2)
        if c1 != c2 and abs(c - round(c, 1)) < 1e-9:
            break
    stem = f"将浓度为 {c1}% 的盐水 {m1} 克与浓度为 {c2}% 的盐水 {m2} 克混合，得到的盐水浓度是多少？"
    o, k = options(rng, c, [(c1 + c2) / 2, c + 2, c - 2, c1 + c2], "%", nd=1, spread=2)
    exp = (f"溶质：{m1}×{c1}% + {m2}×{c2}% = {fmt(m1 * c1 / 100)} + {fmt(m2 * c2 / 100)} = {fmt((m1 * c1 + m2 * c2) / 100)}（克）；"
           f"溶液：{m1}+{m2} = {m1 + m2}（克）。\n浓度 = {fmt((m1 * c1 + m2 * c2) / 100)}÷{m1 + m2} = {fmt(c, 1)}%。\n\n"
           f"也可用十字交叉：混合浓度一定在 {min(c1, c2)}% 和 {max(c1, c2)}% 之间，且偏向质量大的一方。")
    return dict(sub="溶液问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_evaporate(rng):
    while True:
        m = rng.choice([200, 300, 400, 500, 600, 800, 1000])
        c1 = rng.choice([5, 8, 10, 12, 15, 20])
        c2 = rng.choice([10, 12, 15, 16, 20, 25, 30, 40])
        if c2 > c1:
            salt = m * c1 / 100
            m2 = salt / (c2 / 100)
            if abs(m2 - round(m2)) < 1e-9:
                break
    water = m - m2
    stem = f"有浓度为 {c1}% 的盐水 {m} 克，要使其浓度变为 {c2}%，需要蒸发掉多少克水？"
    o, k = options(rng, water, [m2, m * (c2 - c1) / 100, water / 2, water + 50], " 克")
    exp = (f"蒸发前后溶质不变：盐 = {m}×{c1}% = {fmt(salt)} 克。\n浓度变为 {c2}% 时，溶液 = {fmt(salt)}÷{c2}% = {fmt(m2)} 克。\n"
           f"蒸发水 = {m}-{fmt(m2)} = {fmt(water)} 克。")
    return dict(sub="溶液问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def comb(n, k):
    return math.comb(n, k)


def t_comb_select(rng):
    m, f = rng.randint(4, 8), rng.randint(3, 6)
    km, kf = rng.randint(1, 3), rng.randint(1, 2)
    if km > m or kf > f:
        return None
    ans = comb(m, km) * comb(f, kf)
    stem = f"某单位有男职工 {m} 人、女职工 {f} 人，现要选派 {km} 名男职工和 {kf} 名女职工参加培训，共有多少种不同的选法？"
    o, k = options(rng, ans, [comb(m, km) + comb(f, kf), comb(m + f, km + kf), math.perm(m, km) * math.perm(f, kf)], " 种")
    exp = (f"分步完成用乘法：选男职工 C({m},{km}) = {comb(m, km)} 种，选女职工 C({f},{kf}) = {comb(f, kf)} 种，"
           f"共 {comb(m, km)}×{comb(f, kf)} = {ans} 种。\n\n易错：分步要相乘，分类才相加；选人不讲顺序用组合 C，不用排列 A。")
    return dict(sub="排列组合", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_perm_adjacent(rng):
    n = rng.randint(5, 7)
    ans = 2 * math.factorial(n - 1)
    stem = f"{n} 名同学站成一排照相，其中甲、乙两人必须相邻，共有多少种不同的站法？"
    o, k = options(rng, ans, [math.factorial(n - 1), math.factorial(n), math.factorial(n) - ans], " 种")
    exp = (f"捆绑法：把甲、乙看成一个整体，与其余 {n - 2} 人共 {n - 1} 个元素全排列，有 A({n - 1},{n - 1}) = {math.factorial(n - 1)} 种；"
           f"甲乙内部还可以交换位置，×2。共 {math.factorial(n - 1)}×2 = {ans} 种。\n\n口诀：相邻问题捆绑法，不相邻问题插空法。")
    return dict(sub="排列组合", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_perm_apart(rng):
    n = rng.randint(3, 5)  # 其他人数
    ans = math.factorial(n) * math.perm(n + 1, 2)
    stem = f"{n} 个歌唱节目和 2 个舞蹈节目排成一个节目单，要求 2 个舞蹈节目不能相邻，共有多少种不同的排法？"
    o, k = options(rng, ans, [math.factorial(n + 2) - 2 * math.factorial(n + 1), math.factorial(n) * comb(n + 1, 2), math.factorial(n + 2)], " 种")
    exp = (f"插空法：先排 {n} 个歌唱节目，有 {math.factorial(n)} 种；它们之间和两端形成 {n + 1} 个空，"
           f"把 2 个舞蹈节目插进不同的空，有 A({n + 1},2) = {math.perm(n + 1, 2)} 种。共 {math.factorial(n)}×{math.perm(n + 1, 2)} = {ans} 种。\n\n"
           f"验证：总排法 {math.factorial(n + 2)} 减去相邻的 {2 * math.factorial(n + 1)}，也等于 {ans}。")
    return dict(sub="排列组合", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_prob_balls(rng):
    r, w = rng.randint(2, 6), rng.randint(2, 6)
    n = r + w
    p = Fraction(comb(r, 2), comb(n, 2))
    stem = f"一个盒子里有 {r} 个红球和 {w} 个白球，除颜色外完全相同。从中随机取出 2 个球，两个都是红球的概率是多少？"
    wrongs = [Fraction(r, n) ** 2, Fraction(r, n), Fraction(comb(r, 2) + comb(w, 2), comb(n, 2)), Fraction(r * w, comb(n, 2))]
    ans_s = f"{p.numerator}/{p.denominator}" if p.denominator != 1 else "1"
    seen = {ans_s}
    opts = []
    for x in wrongs:
        s = f"{x.numerator}/{x.denominator}"
        if s not in seen:
            seen.add(s)
            opts.append(s)
    while len(opts) < 3:
        x = p * Fraction(len(opts) + 2, len(opts) + 3)
        s = f"{x.numerator}/{x.denominator}"
        if s not in seen:
            seen.add(s)
            opts.append(s)
    allv = opts[:3] + [ans_s]
    rng.shuffle(allv)
    exp = (f"总取法 C({n},2) = {comb(n, 2)}，两个都是红球的取法 C({r},2) = {comb(r, 2)}。\n"
           f"概率 = {comb(r, 2)}/{comb(n, 2)} = {ans_s}。\n\n易错：不放回地取两次，第二次的概率会变化，不能直接用 ({r}/{n})²。")
    return dict(sub="概率问题", stem=stem, options=allv, answer=allv.index(ans_s), explain=exp, level=2)


def t_prob_indep(rng):
    p1, p2 = rng.choice([0.6, 0.7, 0.8, 0.9, 0.5]), rng.choice([0.5, 0.6, 0.7, 0.8])
    ans = 1 - (1 - p1) * (1 - p2)
    stem = f"甲、乙两人独立地破译一个密码，甲能破译的概率是 {fmt(p1)}，乙能破译的概率是 {fmt(p2)}。这个密码被破译的概率是多少？"
    o, k = options(rng, ans, [p1 * p2, (p1 + p2) / 2, min(0.99, p1 + p2 - 0.1), (1 - p1) * (1 - p2)], nd=2, spread=0.05)
    exp = (f"“至少一人破译”的反面是“两人都没破译”，概率 = (1-{fmt(p1)})×(1-{fmt(p2)}) = {fmt((1 - p1) * (1 - p2), 2)}。\n"
           f"所以密码被破译的概率 = 1-{fmt((1 - p1) * (1 - p2), 2)} = {fmt(ans, 2)}。\n\n“至少……”的概率题，用 1 减去反面情况最快。")
    return dict(sub="概率问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_set2(rng):
    n = rng.choice([40, 45, 50, 60, 80, 100])
    a, b = rng.randint(n // 3, n * 3 // 4), rng.randint(n // 3, n * 3 // 4)
    both = rng.randint(max(1, a + b - n + 1), min(a, b) - 1)
    neither = n - (a + b - both)
    if neither <= 0:
        return None
    stem = (f"某班有 {n} 名学生，参加数学兴趣小组的有 {a} 人，参加英语兴趣小组的有 {b} 人，两个小组都参加的有 {both} 人。"
            f"两个小组都没有参加的有多少人？")
    o, k = options(rng, neither, [n - a - b + 2 * both, n - (a + b), n - a - b + both + 1, both], " 人")
    exp = (f"两集合容斥：参加至少一个小组的人数 = {a}+{b}-{both} = {a + b - both}。\n"
           f"都没参加的 = {n}-{a + b - both} = {neither}（人）。\n\n公式：A∪B = A + B - A∩B；总数 = A∪B + 都不。")
    return dict(sub="容斥问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_set3(rng):
    while True:
        a, b, c = rng.randint(20, 40), rng.randint(20, 40), rng.randint(20, 40)
        ab, bc, ac = rng.randint(5, 12), rng.randint(5, 12), rng.randint(5, 12)
        abc = rng.randint(2, 4)
        union = a + b + c - ab - bc - ac + abc
        only = (a - ab - ac + abc, b - ab - bc + abc, c - bc - ac + abc)
        if union > 0 and abc < min(ab, bc, ac) and min(only) > 0:
            break
    stem = (f"某单位组织三项培训，参加 A 项的有 {a} 人，B 项 {b} 人，C 项 {c} 人；同时参加 A、B 两项的有 {ab} 人，"
            f"同时参加 B、C 两项的有 {bc} 人，同时参加 A、C 两项的有 {ac} 人，三项都参加的有 {abc} 人。至少参加一项培训的有多少人？")
    o, k = options(rng, union, [a + b + c - ab - bc - ac, a + b + c - ab - bc - ac - abc, a + b + c - ab - bc - ac + 2 * abc], " 人")
    exp = (f"三集合标准公式：A∪B∪C = A+B+C - (A∩B + B∩C + A∩C) + A∩B∩C\n"
           f"= {a}+{b}+{c} - ({ab}+{bc}+{ac}) + {abc} = {union}（人）。\n\n"
           "注意：这里给的“同时参加两项”包含了三项都参加的人，用标准公式；若给的是“只参加两项”，要用非标准公式。")
    return dict(sub="容斥问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_age(rng):
    while True:
        child = rng.randint(4, 15)
        k = rng.randint(3, 7)
        parent = child * k
        n = rng.randint(2, 12)
        if (parent + n) % (child + n) == 0 and (parent + n) // (child + n) >= 2 and parent < 60:
            m = (parent + n) // (child + n)
            break
    stem = f"今年父亲的年龄是儿子的 {k} 倍，{n} 年后父亲的年龄是儿子的 {m} 倍。今年儿子多少岁？"
    o, k2 = options(rng, child, [child + n, child + 2, child - 2, parent // m], " 岁")
    exp = (f"设今年儿子 x 岁，父亲 {k}x 岁。{n} 年后：{k}x+{n} = {m}(x+{n})，解得 x = {child}。\n"
           f"验证：今年父亲 {parent} 岁；{n} 年后父亲 {parent + n} 岁、儿子 {child + n} 岁，正好 {m} 倍。\n\n"
           "年龄问题也可以直接代入选项验证：年龄差始终不变。")
    return dict(sub="年龄问题", stem=stem, options=o, answer=k2, explain=exp, level=1)


def t_chicken(rng):
    while True:
        x, y = rng.randint(5, 30), rng.randint(5, 30)
        p, q = rng.choice([(2, 4), (3, 5), (5, 8), (10, 6)])
        if p != q:
            break
    kinds = {(2, 4): ("鸡", "兔", "只", "条腿"), (3, 5): ("三人桌", "五人桌", "张", "个座位"),
             (5, 8): ("小盒", "大盒", "个", "块月饼"), (10, 6): ("答对", "答错", "道", "分")}
    a, b, u, w = kinds[(p, q)]
    if (p, q) == (10, 6):
        # 答对得 10 分，答错扣 6 分
        n = x + y
        score = 10 * x - 6 * y
        if score <= 0:
            return None
        stem = f"某知识竞赛共 {n} 道题，答对一题得 10 分，答错或不答一题扣 6 分。小王共得了 {score} 分，他答对了多少道题？"
        o, k = options(rng, x, [y, x + 2, x - 2, score // 10], " 道")
        exp = (f"假设全部答对，应得 {n}×10 = {n * 10} 分，实际少了 {n * 10}-{score} = {n * 10 - score} 分。\n"
               f"每答错一题比答对少 10+6 = 16 分，所以答错 {n * 10 - score}÷16 = {y} 道，答对 {n}-{y} = {x} 道。")
        return dict(sub="鸡兔同笼", stem=stem, options=o, answer=k, explain=exp, level=2)
    heads = x + y
    legs = p * x + q * y
    stem = f"{a}和{b}共有 {heads} {u}，一共有 {legs} {w}。{b}有多少{u}？"
    o, k = options(rng, y, [x, heads - y + 1, (legs - p * heads) // 2 if q - p != 2 else y + 3, y + 2], " " + u)
    exp = (f"假设全是{a}，共 {heads}×{p} = {p * heads}，比实际少 {legs}-{p * heads} = {legs - p * heads}。\n"
           f"每把一{u}{a}换成{b}，多 {q}-{p} = {q - p}，所以{b}有 {legs - p * heads}÷{q - p} = {y} {u}。\n\n"
           "假设法（鸡兔同笼）：先假设全是一种，再用差额 ÷ 单个差。")
    return dict(sub="鸡兔同笼", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_tree(rng):
    kind = rng.choice(["两端", "环形", "一端"])
    d = rng.choice([4, 5, 6, 8, 10, 12, 15, 20, 25])
    n = rng.randint(10, 60)
    L = d * n
    if kind == "两端":
        ans, wr = n + 1, [n, n - 1, n + 2]
        stem = f"在一条长 {L} 米的道路一侧植树，两端都要种，每隔 {d} 米种一棵，一共需要多少棵树？"
        f = f"两端都种：棵数 = 段数 + 1 = {L}÷{d} + 1 = {ans}（棵）。"
    elif kind == "环形":
        ans, wr = n, [n + 1, n - 1, n * 2]
        stem = f"在一个周长为 {L} 米的圆形花坛四周摆放花盆，每隔 {d} 米放一盆，一共要放多少盆？"
        f = f"环形植树：棵数 = 段数 = {L}÷{d} = {ans}（盆）。"
    else:
        ans, wr = n, [n + 1, n - 1, n + 2]
        stem = f"从路口起沿一条长 {L} 米的马路一侧安装路灯，路口处不装、路的尽头要装，每隔 {d} 米装一盏，共需多少盏？"
        f = f"只种一端：棵数 = 段数 = {L}÷{d} = {ans}（盏）。"
    o, k = options(rng, ans, wr, " 棵" if "树" in stem else (" 盆" if "盆" in stem else " 盏"))
    exp = f + "\n\n植树问题口诀：两端都种 +1，只种一端不加不减，两端都不种 -1，环形 = 段数。"
    return dict(sub="植树问题", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_remainder(rng):
    while True:
        a, b = rng.choice([3, 4, 5, 6, 7]), rng.choice([4, 5, 6, 7, 8, 9])
        if a != b and math.gcd(a, b) == 1:
            break
    ra, rb = rng.randint(1, a - 1), rng.randint(1, b - 1)
    lo = rng.choice([0, 50, 100])
    x = next(n for n in range(lo + 1, lo + a * b * 3) if n % a == ra and n % b == rb)
    stem = f"一个大于 {lo} 的自然数，除以 {a} 余 {ra}，除以 {b} 余 {rb}。满足条件的最小自然数是多少？"
    o, k = options(rng, x, [x + a * b, x - 1 if x - 1 > lo else x + 2, x + a, x + b])
    exp = (f"逐步满足：先找除以 {b} 余 {rb} 的数 {', '.join(str(n) for n in range(lo + 1, x + 1) if n % b == rb)}……\n"
           f"其中除以 {a} 余 {ra} 的第一个是 {x}。\n\n通解：满足两个条件的数每隔 {a}×{b} = {a * b} 出现一次，即 {x} + {a * b}n。"
           "\n若余数相同（余同取余）、和相同（和同加和）、差相同（差同减差）可以直接套口诀。")
    return dict(sub="余数问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_drawer(rng):
    colors = rng.randint(3, 5)
    need = rng.randint(2, 4)
    each = [rng.randint(need + 1, 12) for _ in range(colors)]
    ans = colors * (need - 1) + 1
    cols = "红黄蓝绿白"[:colors]
    desc = "、".join(f"{c}色 {n} 个" for c, n in zip(cols, each))
    stem = f"一个不透明的袋子里有{desc}的球。至少要摸出多少个球，才能保证有 {need} 个球颜色相同？"
    o, k = options(rng, ans, [colors * need, ans - 1, colors * (need - 1), ans + colors], " 个")
    exp = (f"最不利原则：先每种颜色都摸 {need - 1} 个（都差一个凑齐），共 {colors}×{need - 1} = {colors * (need - 1)} 个，"
           f"再摸 1 个必定有一种颜色达到 {need} 个。答案 {colors * (need - 1)}+1 = {ans}。\n\n“至少……才能保证……”就是最不利构造 + 1。")
    return dict(sub="最值问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_max_min(rng):
    n = rng.randint(5, 8)
    total = rng.randint(n * 10, n * 25)
    # n 人分 total，各不相同，最多的人至少多少
    base = n * (n - 1) // 2
    ans = math.ceil((total - base) / n) + n - 1
    stem = f"{total} 本书分给 {n} 个班，每个班分到的数量都不相同。分得最多的班至少分到多少本？"
    o, k = options(rng, ans, [math.ceil(total / n), ans - 1, ans + 1, total // n + n], " 本")
    exp = (f"要让最多的尽量少，其他班就要尽量多，且各不相同 → 构造成连续的自然数。\n"
           f"设最多的为 x，则 {n} 个班最多分到 x+(x-1)+…+(x-{n - 1}) = {n}x-{base} ≥ {total}，x ≥ {fmt(Fraction(total + base, n))}，"
           f"取整得 x = {ans}。\n\n数列构造：求“最多的至少”，让其他的尽量接近它。")
    return dict(sub="最值问题", stem=stem, options=o, answer=k, explain=exp, level=3)


def t_weekday(rng):
    w0 = rng.randint(0, 6)
    n = rng.randint(30, 400)
    ans = (w0 + n) % 7
    stem = f"某年的 3 月 1 日是星期{WEEK[w0]}，那么从这一天起再过 {n} 天是星期几？"
    allv = [f"星期{WEEK[(ans + d) % 7]}" for d in (0, 1, -1, 2)]
    a = allv[0]
    rng.shuffle(allv)
    exp = (f"一周 7 天循环：{n}÷7 = {n // 7} 余 {n % 7}，所以往后推 {n % 7} 天：星期{WEEK[w0]} + {n % 7} → 星期{WEEK[ans]}。\n\n"
           "“再过 n 天”只看 n 除以 7 的余数；“第 n 天”要先减 1。")
    return dict(sub="日期问题", stem=stem, options=allv, answer=allv.index(a), explain=exp, level=1)


def t_rect(rng):
    a, b = rng.randint(5, 30), rng.randint(5, 30)
    if a == b:
        return None
    p = rng.choice([10, 20, 25, 50])
    area1 = a * b
    area2 = a * (1 + p / 100) * b * (1 - p / 100)
    ch = (area2 - area1) / area1 * 100
    stem = f"一个长方形的长增加 {p}%，宽减少 {p}%，它的面积会怎样变化？"
    ans = f"减少 {fmt(-ch, 2)}%"
    allv = [ans, "不变", f"增加 {fmt(-ch, 2)}%", f"减少 {p}%"]
    rng.shuffle(allv)
    exp = (f"设原长为 1、宽为 1，新面积 = (1+{p}%)×(1-{p}%) = 1-{p}%² = {fmt(1 - (p / 100) ** 2, 4)}，"
           f"比原来减少 {fmt(-ch, 2)}%。\n\n规律：先增 a% 再减 a%（或反过来），结果一定比原来小 a%²。")
    return dict(sub="几何问题", stem=stem, options=allv, answer=allv.index(ans), explain=exp, level=1)


def t_cube(rng):
    n = rng.randint(3, 6)
    which = rng.choice([3, 2, 1, 0])
    vals = {3: 8, 2: 12 * (n - 2), 1: 6 * (n - 2) ** 2, 0: (n - 2) ** 3}
    ans = vals[which]
    word = {3: "三个面", 2: "恰好两个面", 1: "恰好一个面", 0: "没有一个面"}[which]
    stem = f"把一个表面涂满红色的大正方体切成 {n ** 3} 个同样大小的小正方体（每条棱 {n} 等分）。{word}涂有红色的小正方体有多少个？"
    wr = [v for k2, v in vals.items() if k2 != which] + [ans + 4]
    o, k = options(rng, ans, wr, " 个")
    exp = (f"每条棱分成 {n} 份：三面涂色的在 8 个顶点，共 8 个；两面涂色的在 12 条棱上（去掉顶点），12×({n}-2) = {vals[2]} 个；"
           f"一面涂色的在 6 个面的中间，6×({n}-2)² = {vals[1]} 个；不涂色的在内部，({n}-2)³ = {vals[0]} 个。\n"
           f"所以{word}涂色的有 {ans} 个。（检验：{vals[3]}+{vals[2]}+{vals[1]}+{vals[0]} = {n ** 3}）")
    return dict(sub="几何问题", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_indef(rng):
    a, b = rng.choice([(3, 5), (4, 7), (5, 7), (3, 7), (6, 11), (5, 9)])
    N = rng.randint(40, 120)
    sols = [(x, (N - a * x) // b) for x in range(1, N // a + 1) if (N - a * x) > 0 and (N - a * x) % b == 0]
    if not sols:
        return None
    ans = len(sols)
    stem = f"用面值 {a} 元和 {b} 元的两种购物券（每种至少用一张）恰好支付 {N} 元，共有多少种不同的组合方式？"
    o, k = options(rng, ans, [ans + 1, ans - 1, ans + 2, N // (a * b)], " 种", spread=1)
    exp = (f"设用 {a} 元券 x 张、{b} 元券 y 张：{a}x+{b}y = {N}（x、y 为正整数）。\n"
           f"逐一验证，满足条件的有：" + "、".join(f"x={x}, y={y}" for x, y in sols) + f"，共 {ans} 种。\n\n"
           "不定方程先用奇偶性、尾数或整除特性缩小范围，再找出一组解后按系数周期递推。")
    return dict(sub="不定方程", stem=stem, options=o, answer=k, explain=exp, level=2)


def t_ratio(rng):
    a, b = rng.randint(2, 7), rng.randint(2, 7)
    if a == b or math.gcd(a, b) != 1:
        return None
    unit = rng.randint(5, 20)
    x, y = a * unit, b * unit
    t = rng.randint(3, 15)
    if x <= t:
        return None
    # 甲给乙 t 后之比
    stem = f"甲、乙两个仓库的存粮之比为 {a}∶{b}，两仓共有粮食 {x + y} 吨。甲仓库原有粮食多少吨？"
    o, k = options(rng, x, [y, (x + y) // 2, x + unit, (x + y) * a // (a + b + 1)], " 吨")
    exp = f"按比例分配：甲占 {a}/({a}+{b})，甲仓 = {x + y}×{a}/{a + b} = {x}（吨）。"
    return dict(sub="和差倍比", stem=stem, options=o, answer=k, explain=exp, level=1)


def t_cycle(rng):
    pat = rng.choice(["红黄蓝", "红红黄蓝", "红黄黄蓝绿", "甲乙丙丁"])
    n = rng.randint(30, 200)
    ans = pat[(n - 1) % len(pat)]
    stem = f"一串彩灯按“{'、'.join(pat)}”的顺序循环排列，第 {n} 盏灯是什么颜色？" if pat[0] != "甲" else \
        f"甲、乙、丙、丁四人轮流值班，从甲开始依次循环，第 {n} 天由谁值班？"
    choices = sorted(set(pat))
    while len(choices) < 4:
        choices.append({"红": "紫", "甲": "戊"}.get(pat[0], "白") if "紫" not in choices else "白")
    choices = choices[:4]
    if ans not in choices:
        choices[-1] = ans
    rng.shuffle(choices)
    exp = (f"周期为 {len(pat)}：{n}÷{len(pat)} = {(n - 1) // len(pat) if n % len(pat) else n // len(pat)} … 余 {n % len(pat)}。\n"
           f"余数为 {n % len(pat)}，对应周期中第 {n % len(pat) or len(pat)} 个，即“{ans}”。\n\n余数为 0 时取周期的最后一个。")
    return dict(sub="周期问题", stem=stem, options=choices, answer=choices.index(ans), explain=exp, level=1)


def seq_options(rng, ans, wrongs):
    return options(rng, ans, wrongs)


def t_seq(rng):
    kind = rng.choice(["arith2", "geo", "fib", "square", "cube", "diffgeo", "prod"])
    if kind == "arith2":
        a, d, dd = rng.randint(1, 20), rng.randint(1, 6), rng.randint(1, 4)
        s, diffs = [a], [d + dd * i for i in range(6)]
        for x in diffs:
            s.append(s[-1] + x)
        why = f"两两作差得 {', '.join(map(str, diffs[:5]))}，是公差为 {dd} 的等差数列，下一个差是 {diffs[5]}。"
    elif kind == "geo":
        a, q = rng.randint(1, 5), rng.choice([2, 3])
        s = [a * q ** i for i in range(7)]
        why = f"后一项是前一项的 {q} 倍（等比数列）。"
    elif kind == "fib":
        a, b = rng.randint(1, 6), rng.randint(1, 8)
        s = [a, b]
        while len(s) < 7:
            s.append(s[-1] + s[-2])
        why = "从第三项起，每一项等于前两项之和（递推和数列）。"
    elif kind == "square":
        st, c = rng.randint(1, 6), rng.choice([0, 1, -1, 2])
        s = [(st + i) ** 2 + c for i in range(7)]
        why = f"各项依次为 {st}²、{st + 1}²、{st + 2}²……再{'加' if c >= 0 else '减'} {abs(c)}（幂次修正数列）。" if c else f"各项依次是 {st}、{st + 1}、{st + 2}……的平方。"
    elif kind == "cube":
        st, c = rng.randint(1, 4), rng.choice([0, 1, -1])
        s = [(st + i) ** 3 + c for i in range(7)]
        why = f"各项依次为 {st}³、{st + 1}³……" + (f"再{'加' if c > 0 else '减'} 1。" if c else "")
    elif kind == "diffgeo":
        a, d0, q = rng.randint(1, 10), rng.randint(1, 3), 2
        s, diffs = [a], [d0 * q ** i for i in range(6)]
        for x in diffs:
            s.append(s[-1] + x)
        why = f"两两作差得 {', '.join(map(str, diffs[:5]))}，是公比为 2 的等比数列，下一个差是 {diffs[5]}。"
    else:
        a, b = rng.randint(1, 3), rng.randint(1, 3)
        s = [a, b]
        while len(s) < 6:
            s.append(s[-1] * s[-2])
        if s[-1] > 5000:
            return None
        why = "从第三项起，每一项等于前两项之积（递推积数列）。"
    n_show = 5 if kind != "prod" else 4
    shown, ans = s[:n_show], s[n_show]
    if ans > 100000:
        return None
    stem = f"{'，'.join(map(str, shown))}，（  ）"
    o, k = options(rng, ans, [ans + 1, ans - 2, 2 * shown[-1] - shown[-2], shown[-1] + (shown[-1] - shown[-2]) + 1])
    return dict(sub="数字推理", stem=stem, options=o, answer=k, explain=f"{why}\n所以括号里是 {ans}。", level=1 if kind in ("geo", "arith2") else 2)


MATH_TEMPLATES = [
    (t_work_together, 14), (t_work_leave, 12), (t_work_ratio, 10), (t_meet, 12), (t_chase, 10), (t_river, 10),
    (t_avg_speed, 8), (t_profit, 14), (t_profit_rate, 10), (t_solution, 12), (t_evaporate, 10), (t_comb_select, 12),
    (t_perm_adjacent, 6), (t_perm_apart, 6), (t_prob_balls, 12), (t_prob_indep, 8), (t_set2, 12), (t_set3, 10),
    (t_age, 12), (t_chicken, 14), (t_tree, 14), (t_remainder, 12), (t_drawer, 12), (t_max_min, 10), (t_weekday, 10),
    (t_rect, 6), (t_cube, 10), (t_indef, 10), (t_ratio, 8), (t_cycle, 8), (t_seq, 40),
]


# ================================================================ 资料分析

REGIONS = ["某省", "某市", "A 省", "B 市", "某自治区", "某经济区"]
INDICATORS = [
    ("地区生产总值", "亿元"), ("社会消费品零售总额", "亿元"), ("一般公共预算收入", "亿元"), ("固定资产投资", "亿元"),
    ("货物进出口总额", "亿元"), ("规模以上工业增加值", "亿元"), ("快递业务量", "亿件"), ("旅游总收入", "亿元"),
    ("粮食产量", "万吨"), ("全社会用电量", "亿千瓦时"), ("移动互联网接入流量", "亿 GB"), ("研发经费投入", "亿元"),
]
PARTS = {
    "地区生产总值": ["第一产业增加值", "第二产业增加值", "第三产业增加值"],
    "社会消费品零售总额": ["城镇消费品零售额", "乡村消费品零售额"],
    "货物进出口总额": ["出口额", "进口额"],
    "全社会用电量": ["第一产业用电量", "第二产业用电量", "第三产业用电量", "城乡居民生活用电量"],
    "一般公共预算收入": ["税收收入", "非税收入"],
    "旅游总收入": ["国内旅游收入", "入境旅游收入"],
    "固定资产投资": ["第一产业投资", "第二产业投资", "第三产业投资"],
    "快递业务量": ["同城业务量", "异地业务量", "国际及港澳台业务量"],
}


def r1(x):
    return round(x, 1)


def make_material(rng, idx):
    region = rng.choice(REGIONS)
    year = rng.randint(2021, 2025)
    total_name, unit = rng.choice([x for x in INDICATORS if x[0] in PARTS])
    parts = PARTS[total_name]
    total = rng.randint(800, 60000) if unit == "亿元" else rng.randint(100, 9000)
    g_total = r1(rng.uniform(2.0, 12.0))
    shares = [rng.uniform(0.5, 3) for _ in parts]
    s = sum(shares)
    vals = [round(total * x / s, 1) for x in shares]
    vals[-1] = round(total - sum(vals[:-1]), 1)
    growths = [r1(rng.uniform(-3, 18)) for _ in parts]
    # 另一个指标（用于倍数、比较）
    other_name, other_unit = rng.choice([x for x in INDICATORS if x[0] != total_name])
    # 同单位的另一个指标按总量的一定比例取，数量级才像真的统计公报
    other = round(total * rng.uniform(0.08, 0.7)) if other_unit == unit else rng.randint(200, 9000)
    g_other = r1(rng.uniform(-2, 15))
    text_mode = rng.random() < 0.5
    title = f"{region} {year} 年{total_name}情况"
    if text_mode:
        segs = [f"{year} 年，{region}{total_name} {fmt(total)} {unit}，比上年增长 {g_total}%。其中，"]
        segs.append("；".join(f"{p} {fmt(v)} {unit}，{'增长' if g >= 0 else '下降'} {abs(g)}%" for p, v, g in zip(parts, vals, growths)) + "。")
        segs.append(f"\n\n全年{other_name} {fmt(other)} {other_unit}，比上年{'增长' if g_other >= 0 else '下降'} {abs(g_other)}%。")
        text = "".join(segs)
    else:
        rows = [f"| 指标 | 数值（{unit}） | 比上年增长（%） |", "|---|---|---|", f"| {total_name} | {fmt(total)} | {g_total} |"]
        rows += [f"| 其中：{p} | {fmt(v)} | {g} |" for p, v, g in zip(parts, vals, growths)]
        rows.append(f"| {other_name}（{other_unit}） | {fmt(other)} | {g_other} |")
        title = f"{region} {year} 年主要经济指标"
        text = "\n".join(rows)
    return dict(id=f"gm-{idx:03d}", title=title, text=text), dict(
        region=region, year=year, total_name=total_name, unit=unit, total=total, g_total=g_total, parts=parts, vals=vals,
        growths=growths, other_name=other_name, other_unit=other_unit, other=other, g_other=g_other)


def zl_questions(rng, mid, d):
    """一篇材料出 5 道题：基期量、增长量、比重、比重变化/倍数、综合判断。"""
    qs = []
    Y, U = d["year"], d["unit"]
    # 1 基期量
    i = rng.randrange(len(d["parts"]))
    p, v, g = d["parts"][i], d["vals"][i], d["growths"][i]
    base = v / (1 + g / 100)
    o, k = options(rng, base, [v * (1 - g / 100), v / (1 - g / 100), v - g, base * 1.08], "", nd=0 if base > 100 else 1,
                   spread=max(1, base * 0.06))
    o = [x + f" {U}" for x in o]
    qs.append(dict(sub="基期量", stem=f"{Y - 1} 年，{d['region']}{p}约为多少{U}？", options=o, answer=k,
                   explain=f"基期量 = 现期量÷(1+增长率) = {fmt(v)}÷(1{'+' if g >= 0 else '-'}{abs(g)}%) ≈ {fmt(base, 0 if base > 100 else 1)}（{U}）。\n\n"
                           f"估算技巧：增长率较小时可用 现期×(1-r) 近似，但 r 超过 5% 误差变大，选项接近时要精算。"))
    # 2 增长量
    T, gt = d["total"], d["g_total"]
    inc = T / (1 + gt / 100) * gt / 100
    o, k = options(rng, inc, [T * gt / 100, inc * 1.15, inc * 0.85], "", nd=0 if inc > 100 else 1, spread=max(0.5, inc * 0.1))
    o = [x + f" {U}" for x in o]
    qs.append(dict(sub="增长量", stem=f"{Y} 年，{d['region']}{d['total_name']}比上年增加了约多少{U}？", options=o, answer=k,
                   explain=f"增长量 = 现期量÷(1+r)×r = {fmt(T)}÷(1+{gt}%)×{gt}% ≈ {fmt(inc, 1)}（{U}）。\n\n"
                           f"速算：r = {gt}% ≈ 1/{round(100 / gt) if gt else '∞'}，增长量 ≈ 现期量÷(n+1)。易错：直接用 现期×r = {fmt(T * gt / 100, 1)}。"))
    # 3 比重
    sh = v / T * 100
    o, k = options(rng, sh, [sh * 1.1, sh * 0.9, 100 - sh if abs(100 - 2 * sh) > 5 else sh + 8], "%", nd=1, spread=2)
    qs.append(dict(sub="比重", stem=f"{Y} 年，{p}占{d['total_name']}的比重约为：", options=o, answer=k,
                   explain=f"比重 = 部分÷整体 = {fmt(v)}÷{fmt(T)} ≈ {fmt(sh, 1)}%。"))
    # 4 比重变化（方向 + 大小）
    if g == gt:
        g += 0.3
    sh0 = (v / (1 + g / 100)) / (T / (1 + gt / 100)) * 100
    diff = sh - sh0
    dir_ = "上升" if diff > 0 else "下降"
    ans = f"{dir_}了约 {fmt(abs(diff), 1)} 个百分点"
    alt = "下降" if dir_ == "上升" else "上升"
    allv = [ans, f"{alt}了约 {fmt(abs(diff), 1)} 个百分点", f"{dir_}了约 {fmt(abs(diff) * 3 + 0.5, 1)} 个百分点", "基本不变"]
    if abs(diff) < 0.05:
        return qs
    rng.shuffle(allv)
    qs.append(dict(sub="比重变化", stem=f"与上年相比，{Y} 年{p}占{d['total_name']}的比重：", options=allv, answer=allv.index(ans),
                   explain=f"判断方向：部分增长率 {g}% {'>' if g > gt else '<'} 整体增长率 {gt}%，比重{dir_}。\n"
                           f"计算：现期比重 {fmt(sh, 2)}%，基期比重 = {fmt(v / (1 + g / 100), 1)}÷{fmt(T / (1 + gt / 100), 1)} ≈ {fmt(sh0, 2)}%，"
                           f"相差约 {fmt(abs(diff), 1)} 个百分点。\n\n公式：比重差 = 现期比重×(a-b)/(1+a)，a 为部分增长率、b 为整体增长率。"))
    # 5 倍数 / 平均
    ratio = T / d["other"] if d["unit"] == d["other_unit"] else None
    if ratio and 0.2 < ratio < 30:
        o, k = options(rng, ratio, [ratio * 1.2, ratio * 0.8, d["other"] / T], " 倍", nd=2 if ratio < 10 else 1, spread=max(0.1, ratio * 0.1))
        qs.append(dict(sub="倍数", stem=f"{Y} 年，{d['region']}{d['total_name']}约是{d['other_name']}的多少倍？", options=o, answer=k,
                       explain=f"倍数 = A÷B = {fmt(T)}÷{fmt(d['other'])} ≈ {fmt(ratio, 2)}（倍）。"))
    else:
        # 增长最快的部分
        j = max(range(len(d["parts"])), key=lambda x: d["growths"][x])
        opts = list(d["parts"])
        while len(opts) < 4:
            opts.append(d["total_name"])
        opts = opts[:4]
        if d["parts"][j] not in opts:
            opts[0] = d["parts"][j]
        rng.shuffle(opts)
        qs.append(dict(sub="增长率", stem=f"{Y} 年，下列指标中比上年增长最快的是：", options=opts, answer=opts.index(d["parts"][j]),
                       explain="比较增长快慢就是比较增长率：" + "，".join(f"{p} {g}%" for p, g in zip(d["parts"], d["growths"]))
                               + f"，最高的是{d['parts'][j]}。" + (f"（{d['total_name']}整体增长 {d['g_total']}%）" if d["total_name"] in opts else "")))
    for q in qs:
        q["material"] = mid
        q["level"] = 2
    return qs


# ================================================================ 输出

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(20261004)
    out, seen = [], set()
    for fn, n in MATH_TEMPLATES:
        made, tries = 0, 0
        while made < n and tries < n * 60:
            tries += 1
            q = fn(rng)
            if not q or q["stem"] in seen or len(set(q["options"])) != 4:
                continue
            seen.add(q["stem"])
            made += 1
            q.update(id=f"gs-{fn.__name__[2:]}-{made:02d}", module="数量关系")
            out.append(q)
    with open(os.path.join(OUT, "gen_shuliang.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "tools/gen_questions.py 生成", "materials": [], "questions": out}, f, ensure_ascii=False, indent=1)
    print("数量关系", len(out))

    mats, zl = [], []
    for i in range(48):
        m, d = make_material(rng, i + 1)
        qs = zl_questions(rng, m["id"], d)
        if len(qs) < 4 or any(len(set(q["options"])) != 4 for q in qs):
            continue
        mats.append(m)
        for j, q in enumerate(qs):
            q.update(id=f"gz-{i + 1:03d}-{j + 1}", module="资料分析")
            zl.append(q)
    with open(os.path.join(OUT, "gen_ziliao.json"), "w", encoding="utf-8") as f:
        json.dump({"note": "tools/gen_questions.py 生成", "materials": mats, "questions": zl}, f, ensure_ascii=False, indent=1)
    print("资料分析", len(mats), "篇", len(zl), "题")


if __name__ == "__main__":
    main()
