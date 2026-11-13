"""Step 9 (scoreboard): earned weight on the scorecard, and the paired
gap's error bar counted in days, not rows.

Earned weight is the fifteen blend's own slope -- the share of the model
you would mix with the baseline price to get the best forecast --
computed by tradehub.fifteen_blend.earned_weight on contested rows
only (baseline between 10% and 90%), once for the whole settled set and
once for each chronological half. The gap's standard error clusters
per-contract differences by the ET day they were frozen: same-day
forecasts move together, so rows are not independent evidence.
"""

from tradehub.journal.scoring import score


def _rows(specs):
    """specs: (probability, market_prob, frozen_at) per forecast row."""
    return [
        {"target": f"t-{i}", "probability": p, "market_prob": m,
         "frozen_at": ts, "rebuilt": False}
        for i, (p, m, ts) in enumerate(specs)
    ]


def _settled(rows, outcomes):
    return {r["target"]: o for r, o in zip(rows, outcomes)}


D1 = "2026-10-01T13:00:00+00:00"
D2 = "2026-10-02T13:00:00+00:00"
D3 = "2026-10-03T13:00:00+00:00"


def test_earned_weight_is_the_blend_slope_on_contested_rows():
    # Triples (model, market, outcome): (0.8, 0.5, 1) and (0.2, 0.5, 0)
    # give slope (0.3*0.5 + -0.3*-0.5) / (0.09 + 0.09) = 0.30/0.18 = 5/3.
    # The third row's market (0.97) is uncontested: it must not count.
    rows = _rows([(0.8, 0.5, D1), (0.2, 0.5, D2), (0.9, 0.97, D3)])
    card = score(rows, _settled(rows, [1, 0, 1]), {}, "daily", "test_model")
    ew = card["earned_weight"]
    assert ew["n"] == 2
    assert abs(ew["weight"] - 5 / 3) < 1e-4


def test_earned_weight_halves_split_in_freeze_order():
    # Four contested triples: the first two slope 5/3 (see above); the
    # last two mirror them to slope -5/3 ((0.2,0.5,1): x=-0.3, y=0.5 ->
    # -0.15; (0.8,0.5,0): x=0.3, y=-0.5 -> -0.15; den 0.18). Each half
    # reports its own contested count beside its slope.
    rows = _rows([(0.8, 0.5, D1), (0.2, 0.5, D1),
                  (0.2, 0.5, D2), (0.8, 0.5, D2)])
    card = score(rows, _settled(rows, [1, 0, 1, 0]), {}, "daily", "test_model")
    ew = card["earned_weight"]
    assert abs(ew["first_half"] - 5 / 3) < 1e-4
    assert abs(ew["second_half"] + 5 / 3) < 1e-4
    assert ew["first_half_n"] == 2 and ew["second_half_n"] == 2


def test_earned_weight_halves_follow_freeze_order_not_input_order():
    # The same four triples handed over latest-first: score() sorts by
    # frozen_at itself, so the halves are still the chronological ones.
    # (The runner's row order is a database detail; the scorecard cannot
    # depend on it, or the halves swap whenever the query plan changes.)
    rows = _rows([(0.2, 0.5, D2), (0.8, 0.5, D2),
                  (0.8, 0.5, D1), (0.2, 0.5, D1)])
    card = score(rows, _settled(rows, [1, 0, 1, 0]), {}, "daily", "test_model")
    ew = card["earned_weight"]
    assert abs(ew["first_half"] - 5 / 3) < 1e-4
    assert abs(ew["second_half"] + 5 / 3) < 1e-4


def test_earned_weight_absent_rather_than_zero_without_a_baseline():
    rows = [{"target": f"t-{i}", "probability": 0.6, "rebuilt": False}
            for i in range(3)]
    card = score(rows, _settled(rows, [1, 1, 0]), {}, "daily", "test_model")
    assert card["earned_weight"] == {"weight": None, "n": 0,
                                     "first_half": None, "second_half": None,
                                     "first_half_n": 0, "second_half_n": 0}


def test_gap_se_clusters_by_frozen_day_not_by_row():
    # Six matched contracts over three days, identical within each day:
    # a per-row SE would treat them as six independent draws; the
    # day-clustered SE must be the wider, honest one.
    rows = _rows([(0.9, 0.5, D1), (0.9, 0.5, D1),
                  (0.5, 0.5, D2), (0.5, 0.5, D2),
                  (0.1, 0.5, D3), (0.1, 0.5, D3)])
    card = score(rows, _settled(rows, [1, 1, 1, 1, 0, 0]), {}, "daily", "test_model")
    # diffs per contract: day1 -0.24 x2, day2 0.0 x2, day3 -0.24 x2
    # (our Brier minus baseline Brier: (0.9-1)^2-0.25 = -0.24, etc.)
    # mean = -0.16; cluster totals -0.48, 0.0, -0.48 with n_c = 2 each.
    # var = 3/2 * [(-0.48+0.32)^2 + (0.32)^2 + (-0.48+0.32)^2]
    #     = 1.5 * (0.0256 + 0.1024 + 0.0256) = 0.2304; se = sqrt(var)/6 = 0.08.
    assert card["gap"] is not None and abs(card["gap"] + 0.16) < 1e-6
    assert card["gap_se"] is not None and abs(card["gap_se"] - 0.08) < 1e-6


def test_gap_se_is_none_when_everything_was_frozen_on_one_day():
    # One day of evidence is one cluster: no honest interval exists,
    # and a missing figure is None, never a too-narrow per-row number.
    rows = _rows([(0.9, 0.5, D1), (0.1, 0.5, D1), (0.7, 0.5, D1)])
    card = score(rows, _settled(rows, [1, 0, 1]), {}, "daily", "test_model")
    assert card["gap"] is not None
    assert card["gap_se"] is None
