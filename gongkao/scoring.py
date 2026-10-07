"""行测估分：官方不公布每题分值，这里用常见的估分口径——各模块每题分值的相对比例，按满分 100 折算。

只用来看自己的分数走势、和目标分比较，不代表真实考试的计分。
"""

SCORE_WEIGHTS = {"政治理论": 0.7, "常识判断": 0.6, "言语理解与表达": 0.8, "数量关系": 0.9, "判断推理": 0.8, "资料分析": 1.0}


def estimate_score(per_module):
    """per_module: {模块: (做对, 题数)} → 百分制估分（只按这套卷里出现的模块折算）。"""
    full = sum(SCORE_WEIGHTS.get(m, 0.8) * n for m, (_ok, n) in per_module.items())
    got = sum(SCORE_WEIGHTS.get(m, 0.8) * ok for m, (ok, _n) in per_module.items())
    return round(got / full * 100, 1) if full else 0.0
