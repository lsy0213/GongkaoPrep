"""FSRS 调度的基本性质。"""

from datetime import date, timedelta

import pytest

from gongkao import fsrs
from gongkao.fsrs import AGAIN, EASY, GOOD, HARD, Memory

D0 = date(2026, 10, 1)


def test_new_card_intervals_follow_default_parameters():
    p = fsrs.preview(Memory(), D0)
    assert p[AGAIN] == 0
    assert p[HARD] == 1          # S0(困难) ≈ 1.18 天
    assert p[GOOD] == 3          # S0(良好) ≈ 3.17 天
    assert 14 <= p[EASY] <= 17   # S0(简单) ≈ 15.7 天（带 ±5% 抖动）


def test_monotonic_buttons():
    m = Memory(stability=10, difficulty=6, last_review="2026-09-21")
    p = fsrs.preview(m, D0)
    assert p[AGAIN] == 0 < p[HARD] <= p[GOOD] < p[EASY]


def test_retrievability_is_90_percent_at_stability():
    assert fsrs.retrievability(7, 7) == pytest.approx(0.9)
    assert fsrs.interval(7) == 7
    assert fsrs.interval(7, retention=0.8) > 7


def test_good_reviews_grow_and_again_shrinks():
    m, due, days = fsrs.review(Memory(), GOOD, D0)
    s_hist = [m.stability]
    day = due
    for _ in range(4):
        m, due, days = fsrs.review(m, GOOD, day)
        s_hist.append(m.stability)
        day = due
    assert all(b > a for a, b in zip(s_hist, s_hist[1:]))
    assert days > 30
    before = m.stability
    m2, due2, days2 = fsrs.review(m, AGAIN, day)
    assert m2.stability < before and m2.lapses == 1 and days2 == 0 and due2 == day
    assert m2.difficulty > m.difficulty


def test_review_matches_preview():
    m = Memory(stability=5, difficulty=5, last_review=(D0 - timedelta(days=5)).isoformat())
    p = fsrs.preview(m, D0, seed="x")
    for g in (HARD, GOOD, EASY):
        _m, due, days = fsrs.review(m, g, D0, seed="x")
        assert days == p[g] and due == D0 + timedelta(days=days)


def test_bad_rating():
    with pytest.raises(ValueError):
        fsrs.review(Memory(), 5, D0)


def test_from_leitner():
    m = fsrs.from_leitner(box=4, due="2026-10-10", updated_at="2026-09-26 10:00:00", reps=4, lapses=1)
    assert m.stability == 14 and m.last_review == "2026-09-26" and not m.is_new
