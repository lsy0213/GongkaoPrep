"""FSRS-5 间隔复习调度（Anki 23.10 起默认的算法，开源实现见 open-spaced-repetition）。

每张卡（或每道错题）记三样东西：
  stability 记忆稳定性 S —— 回忆概率降到 90% 要多少天；
  difficulty 难度 D —— 1~10；
  last_review 上次复习日期。
复习时按 1 重来 / 2 困难 / 3 良好 / 4 简单 打分，算出新的 S、D，下次间隔 = 让回忆概率正好降到“期望记忆率”的天数。
参数用 FSRS-5 的默认值（在几亿条复习记录上训练），按天调度，不做分钟级的学习步骤。
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timedelta

W = (0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
     1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # = 19/81，使 R(S, S) = 90%
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATING_NAMES = {AGAIN: "重来", HARD: "困难", GOOD: "良好", EASY: "简单"}
MAX_INTERVAL = 3650


@dataclass
class Memory:
    stability: float = 0.0
    difficulty: float = 0.0
    last_review: str = ""   # YYYY-MM-DD；空 = 新卡
    reps: int = 0
    lapses: int = 0

    @property
    def is_new(self):
        return not self.last_review or self.stability <= 0


def _clamp_d(d):
    return min(10.0, max(1.0, d))


def init_difficulty(g):
    return _clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)


def init_stability(g):
    return max(W[g - 1], 0.1)


def retrievability(elapsed_days, s):
    if s <= 0:
        return 0.0
    return (1 + FACTOR * max(0.0, elapsed_days) / s) ** DECAY


def next_difficulty(d, g):
    delta = -W[6] * (g - 3)
    d2 = d + delta * (10 - d) / 9  # 越接近 10 变化越小
    return _clamp_d(W[7] * init_difficulty(EASY) + (1 - W[7]) * d2)  # 向“默认难度”轻微回归


def stability_after_recall(d, s, r, g):
    hard = W[15] if g == HARD else 1.0
    easy = W[16] if g == EASY else 1.0
    return s * (1 + math.exp(W[8]) * (11 - d) * s ** (-W[9]) * (math.exp(W[10] * (1 - r)) - 1) * hard * easy)


def stability_after_forget(d, s, r):
    long_term = W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
    short_term = s / math.exp(W[17] * W[18])
    return min(long_term, short_term)


def stability_same_day(s, g):
    return s * math.exp(W[17] * (g - 3 + W[18]))


def interval(s, retention=0.9):
    """回忆概率从 100% 降到 retention 需要的天数。"""
    days = s / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(MAX_INTERVAL, max(1, round(days))))


def _fuzz(days, seed):
    """间隔加一点确定性的抖动（±5%），同一天学的一批卡不会永远挤在同一天到期。"""
    if days < 3:
        return days
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    delta = max(1, round(days * 0.05))
    return int(days - delta + round(h * 2 * delta))


def _step(m: Memory, g: int, today: date):
    """打分 g 之后的新记忆状态（不含间隔）。"""
    if m.is_new:
        s, d = init_stability(g), init_difficulty(g)
    else:
        elapsed = (today - date.fromisoformat(m.last_review)).days
        d = next_difficulty(m.difficulty, g)
        if elapsed < 1:
            s = stability_same_day(m.stability, g)
        else:
            r = retrievability(elapsed, m.stability)
            s = stability_after_forget(m.difficulty, m.stability, r) if g == AGAIN else \
                stability_after_recall(m.difficulty, m.stability, r, g)
    return Memory(stability=max(0.1, s), difficulty=d, last_review=today.isoformat(), reps=m.reps + 1,
                  lapses=m.lapses + (1 if g == AGAIN else 0))


def preview(m: Memory, today: date, retention=0.9, seed=""):
    """四个打分各自的下次间隔（天），按钮上显示“3 天后”之类；复习时用的就是这里算出的间隔。

    重来的间隔为 0：今天之内再看一遍（闪卡本轮末尾会再出现；错题本由调用方改成明天）。
    """
    t = today.isoformat()
    out = {AGAIN: 0}
    for g in (HARD, GOOD, EASY):
        out[g] = _fuzz(interval(_step(m, g, today).stability, retention), seed + t + str(g))
    # 打分越高，间隔不会比低一档短
    out[GOOD] = max(out[GOOD], out[HARD])
    out[EASY] = max(out[EASY], min(MAX_INTERVAL, out[GOOD] + 1))
    return out


def review(m: Memory, g: int, today: date, retention=0.9, seed=""):
    """按打分 g 复习一次，返回 (新的 Memory, 下次到期日 date, 间隔天数)。"""
    if g not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError("评分只能是 1–4")
    days = preview(m, today, retention, seed)[g]
    return _step(m, g, today), today + timedelta(days=days), days


def from_leitner(box, due, updated_at, reps=0, lapses=0, intervals=(0, 1, 3, 7, 14, 30)):
    """老版本盒子制的卡转成 FSRS 状态：稳定性取当前盒子的间隔，上次复习日取更新日期。"""
    box = max(1, min(int(box or 1), len(intervals) - 1))
    s = float(max(1, intervals[box]))
    d = _clamp_d(5.0 + 0.6 * (lapses or 0) - 0.3 * max(0, box - 2))
    last = (updated_at or "")[:10] or (due or "")[:10]
    return Memory(stability=s, difficulty=d, last_review=last, reps=reps or 0, lapses=lapses or 0)
