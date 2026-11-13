"""Step A0 replay: the probability is read_window's own output, the quote
is the candle ending at the entry minute, volume-0 minutes are unfillable,
and the golden comparator measures prob fidelity separately from quote
agreement."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradehub.backtest.fifteen_replay import golden_compare, replay_window
from tradehub.backtest.kalshi_history import Candle
from tradehub.journal.forecasters.fifteen_min import read_window

OPEN = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
CLOSE = OPEN + timedelta(minutes=15)


def tape(open_price: float = 100.0, drift: float = 0.001) -> list:
    """Three hours of 1-minute closes ending after the window: a steady
    drift up, so sigma is defined and prob_up > 0.5."""
    out = []
    price = open_price
    t = OPEN - timedelta(minutes=180)
    while t <= CLOSE + timedelta(minutes=61):
        out.append((t, price))
        price *= (1 + drift)
        t += timedelta(minutes=1)
    return out


def candles(volume: float = 25.0) -> list[Candle]:
    return [Candle(end_ts=OPEN + timedelta(minutes=m), yes_bid=0.60, yes_ask=0.63,
                   volume=volume)
            for m in range(0, 17)]


def test_replay_prob_is_read_windows_own_number():
    rows = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=candles())
    assert [r["offset_min"] for r in rows] == list(range(1, 15))
    for r in rows:
        read = read_window(CLOSE, tape(), OPEN + timedelta(minutes=r["offset_min"]))
        assert r["prob_up"] == read["prob_up"]
        assert r["source"] == "replay" and r["prob_source"] == "replay"


def test_replay_quote_is_the_candle_ending_at_the_entry_minute():
    cs = candles()
    cs[5] = Candle(end_ts=OPEN + timedelta(minutes=5), yes_bid=0.40, yes_ask=0.44, volume=9.0)
    rows = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=cs)
    row5 = rows[4]
    assert row5["offset_min"] == 5
    assert row5["yes_bid"] == 0.40 and row5["yes_ask"] == 0.44
    assert abs(row5["spread"] - 0.04) < 1e-9
    assert row5["candle_volume"] == 9.0 and row5["fillable"] is True


def test_volume_zero_minutes_are_unfillable():
    rows = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=candles(volume=0.0))
    assert all(r["fillable"] is False for r in rows)
    assert all(r["candle_volume"] == 0.0 for r in rows)


def test_replay_pnl_follows_the_rule_for_a_winning_yes():
    rows = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=candles())
    traded = [r for r in rows if r["side"] is not None]
    assert traded, "the drift tape against a 0.63 ask should clear the bar somewhere"
    for r in traded:
        if r["side"] == "yes":
            assert r["pnl"] is not None and r["pnl"] > 0


def test_golden_compare_separates_prob_fidelity_from_quotes():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.5000005,
               "side": "yes", "side_cost": 0.60, "edge_net": 0.12,
               "yes_bid": 0.58, "yes_ask": 0.60},
              {"series": "S", "target": "T", "offset_min": 6, "prob_up": 0.40,
               "side": None, "side_cost": None, "edge_net": 0.05,
               "yes_bid": None, "yes_ask": None}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.50,
               "prob_source": "tick", "side": "no", "side_cost": 0.41, "edge_net": 0.11},
              {"series": "S", "target": "T", "offset_min": 6, "prob_up": 0.400004,
               "prob_source": "tape", "side": None, "side_cost": None, "edge_net": 0.05}]
    out = golden_compare(replay, stored)
    assert out["matched"] == 2 and out["prob_compared"] == 2
    assert out["prob_within_tolerance"] == 2  # both within the 5dp rounding bound
    assert out["prob_within_1e-6"] == 1
    assert out["side_compared"] == 1 and out["side_agree"] == 0
    assert out["by_source"]["tape"]["prob_within_tolerance"] == 1
    assert out["prob_within_material"] == 2
    assert out["by_source"]["tick"]["prob_within_material"] == 1
    # (a) and (b) pass on these rows; (c) fails on the side disagreement.
    assert out["gate"]["a_tape"]["pass"] is True
    assert out["gate"]["b_tick"]["pass"] is True
    assert out["gate"]["b_tick"]["within_material_share"] == 1.0
    assert out["gate"]["c_quotes_sides"]["side_share"] == 0.0
    assert out["gate"]["c_quotes_sides"]["pass"] is False
    assert out["gate"]["pass"] is False


def test_golden_gate_fails_when_tape_rows_do_not_reproduce():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.55,
               "side": None, "side_cost": None, "edge_net": None}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.50,
               "prob_source": "tape", "side": None, "side_cost": None, "edge_net": None}]
    out = golden_compare(replay, stored)
    assert out["tape_by_offset"][5]["share"] == 0.0
    assert out["gate"]["a_tape"]["pass"] is False and out["gate"]["pass"] is False


def test_golden_gate_fails_when_tick_rows_disagree_materially():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.55,
               "side": None, "side_cost": None, "edge_net": None}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.50,
               "prob_source": "tick", "side": None, "side_cost": None, "edge_net": None}]
    out = golden_compare(replay, stored)
    assert out["gate"]["b_tick"]["within_material_share"] == 0.0
    assert out["gate"]["b_tick"]["pass"] is False and out["gate"]["pass"] is False


def test_golden_side_agreement_counts_the_side_not_the_cost():
    # Regression: the first comparator required the trade cost to match
    # exactly as well, and reported 18.6% "side agreement" on the real
    # Nov 6-12 run when sides alone agreed 99.2% of the time.
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.60,
               "side": "yes", "side_cost": 0.44, "edge_net": 0.12,
               "yes_bid": 0.42, "yes_ask": 0.44}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.600001,
               "prob_source": "tick", "side": "yes", "side_cost": 0.40, "edge_net": 0.13}]
    out = golden_compare(replay, stored)
    assert out["side_compared"] == 1 and out["side_agree"] == 1
    assert out["side_share"] == 1.0
    assert out["edge_compared"] == 1 and out["edge_share"] == 1.0


def test_golden_gate_c_reports_quote_divergence_without_failing():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.60,
               "side": "yes", "side_cost": 0.60, "edge_net": 0.12,
               "yes_bid": 0.58, "yes_ask": 0.60}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.600001,
               "prob_source": "tick", "side": "yes", "side_cost": 0.40, "edge_net": 0.12}]
    out = golden_compare(replay, stored)
    assert out["side_share"] == 1.0  # same side, honestly counted
    assert abs(out["quote_median_abs_diff"] - 0.20) < 1e-9
    # 2026-11-13 ruling: the quote gap is a stated limit, side is the gate.
    assert out["gate"]["c_quotes_sides"]["quote_edge_within_limits"] is False
    assert out["gate"]["c_quotes_sides"]["pass"] is True
    assert out["gate"]["pass"] is True


def test_haircut_fills_at_ask_plus_a_cent_and_drops_thin_edges():
    from tradehub.backtest.fifteen_replay import REPLAY_HAIRCUT, haircut_quote
    from tradehub import oil_fifteen_rule as rule
    assert REPLAY_HAIRCUT == 0.01
    assert haircut_quote(0.60, 0.63, 0.01) == (0.59, 0.64)
    assert haircut_quote(None, 0.63, 0.01) == (None, 0.63)
    raw = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                        close_time=CLOSE, outcome=1, tape=tape(), candles=candles())
    cut = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                        close_time=CLOSE, outcome=1, tape=tape(), candles=candles(),
                        haircut=0.01)
    for r, c in zip(raw, cut):
        assert (c["yes_bid"], c["yes_ask"]) == (r["yes_bid"], r["yes_ask"])  # raw quote kept
        assert c["haircut"] == 0.01 and r["haircut"] == 0.0
        if c["side"] == "yes":
            assert c["side_cost"] == 0.64 and c["pnl"] == rule.pnl("yes", 0.64, 1)
            assert c["edge_net"] >= rule.MIN_EDGE - 1e-9
        if r["side"] is None:
            assert c["side"] is None  # the haircut never adds a trade
    # An edge that clears the bar raw (ask 0.89 vs prob ~1: +10.3 points
    # after the fee) but not after the cent is dropped.
    thin = [Candle(end_ts=OPEN + timedelta(minutes=m), yes_bid=0.87, yes_ask=0.89,
                   volume=5.0) for m in range(0, 17)]
    raw5 = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=thin)[4]
    cut5 = replay_window(series="KXNATGAS15M", target="kalshi:X-1", ticker="X-1",
                         close_time=CLOSE, outcome=1, tape=tape(), candles=thin,
                         haircut=0.01)[4]
    assert raw5["side"] == "yes" and raw5["edge_net"] < rule.MIN_EDGE + 0.01
    assert cut5["side"] is None and cut5["pnl"] is None


def test_golden_gate_passes_when_all_three_parts_pass():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.500001,
               "side": None, "side_cost": None, "edge_net": None,
               "yes_bid": None, "yes_ask": None},
              {"series": "S", "target": "T", "offset_min": 6, "prob_up": 0.60,
               "side": "yes", "side_cost": 0.605, "edge_net": 0.12,
               "yes_bid": 0.585, "yes_ask": 0.605}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.50,
               "prob_source": "tape", "side": None, "side_cost": None, "edge_net": None},
              {"series": "S", "target": "T", "offset_min": 6, "prob_up": 0.6005,
               "prob_source": "tick", "side": "yes", "side_cost": 0.60, "edge_net": 0.11}]
    out = golden_compare(replay, stored)
    assert out["gate"]["a_tape"]["pass"] is True
    assert out["gate"]["b_tick"]["pass"] is True
    assert out["gate"]["c_quotes_sides"]["pass"] is True
    assert out["gate"]["pass"] is True


def test_golden_uncomparable_rows_are_counted_not_dropped():
    replay = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": None,
               "side": None, "side_cost": None, "edge_net": None,
               "yes_bid": None, "yes_ask": None}]
    stored = [{"series": "S", "target": "T", "offset_min": 5, "prob_up": 0.50,
               "prob_source": "tick", "side": "yes", "side_cost": 0.40, "edge_net": 0.12}]
    out = golden_compare(replay, stored)
    assert out["matched"] == 1 and out["prob_compared"] == 0
    assert out["uncomparable"] == {"prob": 1, "quote": 1}
