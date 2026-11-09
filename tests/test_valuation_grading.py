"""Relative grading (spec section 6) on hand-checkable windows.

The canonical case: over exactly 20 trading days the name returns +10%, its
frozen peers return +2% and +6% (median +4%), SPY returns +6%. A long call
therefore beat its peers by +6 points and the index by +4; the peer-median
basket (the counterfactual) returned +4%. Path: the name dips to -8% on day 5
and first reaches the 120 target on day 15, peaking at +21%."""
import pandas as pd

from tradehub.valuation import grading

RENDER = "2026-10-01"  # a Thursday; business days from here


def _closes(points: dict[int, float], start: float = 100.0, days: int = 70):
    idx = pd.bdate_range(RENDER, periods=days)
    vals, cur = [], start
    for i in range(days):
        cur = points.get(i, cur)
        vals.append(cur)
    return pd.Series(vals, index=idx, dtype=float)


def _case(**over):
    case = dict(
        direction="long", probability=0.7, entry_price=100.0,
        target_price=120.0, render_date=RENDER,
        name_closes=_closes({5: 92.0, 12: 115.0, 15: 121.0, 20: 110.0}),
        peer_entry={"P1": 50.0, "P2": 200.0},
        peer_closes={"P1": _closes({20: 51.0}, start=50.0),
                     "P2": _closes({20: 212.0}, start=200.0)},
        spy_closes=_closes({20: 106.0}),
        horizon=20,
    )
    case.update(over)
    return case


def test_long_beats_peers_hand_case():
    g = grading.grade_call(**_case())
    assert g is not None
    assert abs(g["name_ret_pct"] - 10.0) < 1e-9
    assert abs(g["peer_median_ret_pct"] - 4.0) < 1e-9
    assert abs(g["peer_excess_pct"] - 6.0) < 1e-9       # PRIMARY
    assert abs(g["index_excess_pct"] - 4.0) < 1e-9
    assert abs(g["basket_ret_pct"] - 4.0) < 1e-9        # counterfactual basket
    assert g["relative_pass"] is True
    assert abs(g["brier"] - 0.09) < 1e-9                # (0.7 - 1)^2


def test_entry_path_quality():
    g = grading.grade_call(**_case())
    assert abs(g["mfe_pct"] - 21.0) < 1e-9   # peaked at 121 on day 15
    assert abs(g["mae_pct"] - (-8.0)) < 1e-9  # dipped to 92 on day 5
    assert g["time_to_target_days"] == 15


def test_short_mirror_passes_when_name_underperforms_peers():
    g = grading.grade_call(**_case(
        direction="short", probability=0.6,
        name_closes=_closes({20: 90.0}),
        peer_closes={"P1": _closes({20: 49.0}, start=50.0),
                     "P2": _closes({20: 196.0}, start=200.0)},
        spy_closes=_closes({20: 97.0})))
    assert abs(g["peer_excess_pct"] - (-8.0)) < 1e-9
    assert g["relative_pass"] is True       # short: underperforming peers wins
    assert abs(g["brier"] - 0.16) < 1e-9     # (0.6 - 1)^2


def test_long_fails_when_peers_beat_the_name():
    g = grading.grade_call(**_case(
        peer_closes={"P1": _closes({20: 56.0}, start=50.0),
                     "P2": _closes({20: 224.0}, start=200.0)}))
    assert g["peer_excess_pct"] < 0
    assert g["relative_pass"] is False
    assert abs(g["brier"] - 0.49) < 1e-9     # (0.7 - 0)^2


def test_no_direction_is_a_no_call_not_a_grade():
    g = grading.grade_call(**_case(direction="none", probability=None,
                                   target_price=None))
    assert g["relative_pass"] is None and g["brier"] is None
    assert g["time_to_target_days"] is None


def test_immature_horizon_returns_none():
    assert grading.grade_call(**_case(horizon=60,
                                      name_closes=_closes({}, days=30))) is None


def test_zone_direction_mapping_for_the_baseline_control():
    assert grading.direction_of_zone("buy_zone_strong") == "long"
    assert grading.direction_of_zone("buy_zone") == "long"
    assert grading.direction_of_zone("short_zone") == "short"
    assert grading.direction_of_zone("short_zone_strong") == "short"
    assert grading.direction_of_zone("neutral") == "none"
    assert grading.direction_of_zone("no_chase_long") == "none"


def test_grading_job_grades_a_stored_verdict_and_both_controls():
    from tests.test_valuation_verdicts import FakeClient

    client = FakeClient()
    client.tables["valuation_verdicts"] = [{
        "id": 7, "ticker": "AMGN", "status": "rendered",
        "rendered_at": "2026-10-01T15:00:00+00:00", "price": 100.0,
        "target_price": 120.0, "baseline_verdict": "buy_zone",
        "verdict": {"direction": "long", "probability": 0.7},
        "proposer_pick": {"direction": "short", "probability": 0.6},
        "frozen_peers": {"members": [{"ticker": "P1", "price": 50.0},
                                     {"ticker": "P2", "price": 200.0}]}}]

    idx = pd.bdate_range(RENDER, periods=70)
    frame = pd.DataFrame({
        "AMGN": _closes({5: 92.0, 12: 115.0, 15: 121.0, 20: 110.0}),
        "P1": _closes({20: 51.0}, start=50.0),
        "P2": _closes({20: 212.0}, start=200.0),
        "SPY": _closes({20: 106.0}),
    }, index=idx)

    class _DS:
        def prices(self, _tickers, years=3):
            return frame

    out = grading.run_grading(client, _DS())
    assert out["grades_written"] == 2  # +20 and +60 both mature on 70 days
    rows = {(g["verdict_id"], g["horizon"]): g
            for g in client.tables["valuation_verdict_grades"]}
    g20 = rows[(7, 20)]
    assert g20["verdict_relative_pass"] is True
    assert abs(g20["peer_excess_pct"] - 6.0) < 1e-9
    assert abs(g20["verdict_brier"] - 0.09) < 1e-9
    assert g20["baseline_relative_pass"] is True   # buy_zone = long, same win
    assert g20["proposer_relative_pass"] is False  # the short pick loses it
    # idempotent: a second pass writes nothing new
    assert grading.run_grading(client, _DS())["grades_written"] == 0


def test_authority_summary_counts_relative_passes_at_best_horizon():
    rows = [
        {"verdict_id": 1, "horizon": 20, "verdict_relative_pass": True},
        {"verdict_id": 1, "horizon": 60, "verdict_relative_pass": False},
        {"verdict_id": 2, "horizon": 20, "verdict_relative_pass": True},
        {"verdict_id": 3, "horizon": 20, "verdict_relative_pass": None},
    ]
    out = grading.authority_summary(rows, gate=40)
    assert out["graded_verdicts"] == 2       # verdict 3 is a no-call, not graded
    assert out["relative_passes"] == 1       # verdict 1's +60 grade governs
    assert out["gate"] == 40 and out["status"] == "display_only"
