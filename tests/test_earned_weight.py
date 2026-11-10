import random
from statistics import linear_regression

from tradehub.journal.scoring import earned_weight


def _rows(n=40, seed=1):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        m = rng.uniform(0.15, 0.85)
        p = min(0.99, max(0.01, m + rng.uniform(-0.2, 0.2)))
        out.append((p, m, 1 if rng.random() < 0.5 * p + 0.5 * m else 0))
    return out


def test_model_equals_market_is_none():
    assert earned_weight([(m, m, o) for _, m, o in _rows()]) is None


def test_slope_matches_independent_regression():
    rows = _rows()
    xs = [p - m for p, m, _ in rows]
    ys = [o - m for _, m, o in rows]
    res = earned_weight(rows)
    assert res["n_contested"] == 40
    assert res["weight"] == round(linear_regression(xs, ys).slope, 4)
    assert res["weight_first_half"] == round(linear_regression(xs[:20], ys[:20]).slope, 4)
    assert res["weight_second_half"] == round(linear_regression(xs[20:], ys[20:]).slope, 4)
    assert -1 <= res["info"] <= 1


def test_uncontested_rows_ignored():
    rows = _rows()
    extra = [(0.5, 0.05, 1), (0.2, 0.95, 0), (0.9, 0.0, 1), (0.1, 1.0, 0), (0.4, None, 1)]
    assert earned_weight(rows + extra) == earned_weight(rows)


def test_fewer_than_30_contested_is_none():
    assert earned_weight(_rows(29)) is None
    assert earned_weight(_rows(29) + [(0.5, 0.02, 1)] * 20) is None


def test_half_is_none_when_x_has_no_variance():
    # n >= 30 forces halves of >= 15 rows, so a half is None only through zero variance in x
    rows = _rows(30)
    rows = [(m, m, o) for _, m, o in rows[:15]] + rows[15:]
    res = earned_weight(rows)
    assert res["weight_first_half"] is None
    assert res["weight_second_half"] is not None
