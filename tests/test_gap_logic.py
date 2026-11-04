import math

import pytest

from tradehub.gaps.logic import (
    MAX_POSITIONS,
    evidence_status,
    executable_gap,
    exit_decision,
    exit_slippage,
    fee_dollars,
    gate,
    grade,
    half_kelly_contracts,
    settled_pnl,
    summarize_ledger,
)


def test_gap_uses_the_ask_of_the_better_side_not_the_mid():
    assert executable_gap(0.70, yes_ask=0.60, no_ask=0.42) == ("yes", pytest.approx(10.0))
    assert executable_gap(0.30, yes_ask=0.40, no_ask=0.60) == ("no", pytest.approx(10.0))


def test_gap_without_any_ask_is_unknown():
    assert executable_gap(0.70, yes_ask=None, no_ask=None) == (None, None)
    assert executable_gap(None, yes_ask=0.5, no_ask=0.5) == (None, None)


def test_half_kelly_sizes_on_the_entry_price_and_caps_at_six_percent():
    # edge 5 points at 50c: full Kelly 10%, half 5%, $500 buys 1000 contracts
    assert half_kelly_contracts(0.55, 0.50, 10_000) == 1000
    # edge 40 points: half Kelly 40%, capped at 6%: $600 at 50c
    assert half_kelly_contracts(0.90, 0.50, 10_000) == 1200
    assert half_kelly_contracts(0.40, 0.50, 10_000) == 0
    assert half_kelly_contracts(0.90, 0.50, 0) == 0


def test_exit_slippage_walks_the_bids_best_first():
    levels = [[0.48, 100], [0.50, 100]]  # Kalshi lists best last
    assert exit_slippage(levels, 100) == pytest.approx(0.0)
    assert exit_slippage(levels, 200) == pytest.approx((0.50 - 0.49) / 0.50)


def test_exit_slippage_is_unknown_without_a_book_and_infinite_without_depth():
    assert exit_slippage(None, 100) is None
    assert exit_slippage([[0.50, 10]], 100) == math.inf
    assert exit_slippage([], 100) == math.inf


GOOD = dict(gap_pts=8.0, hours_to_settle=2.5, source="CF Benchmarks", slippage=0.03)


def test_all_gates_pass_at_their_edges():
    assert gate(**GOOD) == []


@pytest.mark.parametrize("change, reason", [
    ({"gap_pts": 7.99}, "gap"),
    ({"gap_pts": None}, "model_or_market_unknown"),
    ({"hours_to_settle": 2.0}, "too_close_to_settlement"),
    ({"source": None}, "resolution_source_unknown"),
    ({"slippage": 0.031}, "exit_slippage"),
    ({"slippage": None}, "liquidity_unknown"),
    ({"slippage": math.inf}, "not_enough_depth"),
])
def test_each_gate_names_why_it_failed(change, reason):
    assert gate(**{**GOOD, **change}) == [reason]


def test_a_failed_gate_still_lists_every_other_failure():
    assert gate(gap_pts=1.0, hours_to_settle=1.0, source=None, slippage=None) == [
        "gap", "too_close_to_settlement", "resolution_source_unknown", "liquidity_unknown"]


POS = dict(side="yes", model_at_entry=0.70, hours_to_settle=5.0)


def test_exits_fire_on_each_mechanical_rule():
    assert exit_decision(**POS, model_prob=0.70, side_ask=0.60)["reason"] is None
    assert exit_decision(**POS, model_prob=0.70, side_ask=0.69)["reason"] == "gap_closed"
    assert exit_decision(**POS, model_prob=0.70, side_ask=0.75)["reason"] == "gap_closed"  # sign flip
    assert exit_decision(**POS, model_prob=0.76, side_ask=0.60)["reason"] == "model_moved"
    assert exit_decision(**{**POS, "hours_to_settle": 0.9}, model_prob=0.70, side_ask=0.60)["reason"] == "near_settlement"


def test_a_no_position_reads_the_model_from_its_own_side():
    out = exit_decision(side="no", model_at_entry=0.30, hours_to_settle=5.0, model_prob=0.30, side_ask=0.69)
    assert out["reason"] == "gap_closed"  # NO worth 70c, ask 69c: one point left


def test_unknown_model_or_quote_makes_no_gap_or_model_call():
    assert exit_decision(**POS, model_prob=None, side_ask=0.60)["reason"] is None
    assert exit_decision(**POS, model_prob=0.70, side_ask=None)["reason"] is None


def test_fees_are_the_taker_formula_and_settlement_pays_none():
    assert fee_dollars(0.50, 100) == pytest.approx(1.75)
    assert settled_pnl(side="yes", outcome=1, contracts=100, entry_price=0.40, entry_fee=1.68) == pytest.approx(58.32)
    assert settled_pnl(side="no", outcome=1, contracts=100, entry_price=0.40, entry_fee=1.68) == pytest.approx(-41.68)


def test_brier_and_log_loss_on_known_values():
    pairs = [{"model": 0.8, "market": 0.5, "outcome": 1, "category": "crypto"},
             {"model": 0.2, "market": 0.5, "outcome": 0, "category": "oil"}]
    out = grade(pairs)
    assert out["all"]["n"] == 2
    assert out["all"]["model_brier"] == pytest.approx(0.04)
    assert out["all"]["market_brier"] == pytest.approx(0.25)
    assert out["all"]["brier_delta"] == pytest.approx(-0.21)
    assert out["all"]["model_log_loss"] == pytest.approx(-math.log(0.8))
    assert out["crypto"]["n"] == 1 and out["oil"]["n"] == 1


def test_a_certain_wrong_forecast_has_a_finite_log_loss():
    out = grade([{"model": 1.0, "market": 0.5, "outcome": 0, "category": "oil"}])
    assert math.isfinite(out["all"]["model_log_loss"])


def test_calibration_buckets():
    pairs = [{"model": 0.82, "market": 0.5, "outcome": 1, "category": "oil"},
             {"model": 0.88, "market": 0.5, "outcome": 0, "category": "oil"}]
    bucket = next(b for b in grade(pairs)["all"]["calibration"] if b["bucket"] == "80-90")
    assert bucket["n"] == 2 and bucket["hit_rate"] == 0.5 and bucket["mean_model"] == pytest.approx(0.85)


def test_no_pairs_is_unknown_not_zero():
    assert grade([])["all"] == {"n": 0, "model_brier": None, "market_brier": None, "brier_delta": None,
                                "model_log_loss": None, "market_log_loss": None, "calibration": []}


def test_evidence_needs_both_the_weeks_and_the_pairs():
    assert evidence_status(days=27.9, pairs=500)["status"] == "NOT ENOUGH EVIDENCE"
    assert evidence_status(days=40, pairs=149)["status"] == "NOT ENOUGH EVIDENCE"
    assert evidence_status(days=28, pairs=150)["status"] == "ENOUGH TO READ"


def test_ledger_summary_returns_and_drawdown_from_closed_trades_only():
    rows = [{"status": "closed", "pnl": 100.0, "gap_pts": 10.0, "exit_at": "2"},
            {"status": "closed", "pnl": -300.0, "gap_pts": 8.0, "exit_at": "3"},
            {"status": "open", "pnl": None, "gap_pts": 9.0, "exit_at": None}]
    out = summarize_ledger(rows)
    assert out["bankroll"] == 9800 and out["return_pct"] == pytest.approx(-2.0)
    assert out["max_drawdown_pct"] == pytest.approx(300 / 10100 * 100)
    assert out["resolved"] == 2 and out["win_rate"] == 0.5 and out["open"] == 1
    assert out["avg_entry_gap_pts"] == pytest.approx(9.0)


def test_position_limit_is_five():
    assert MAX_POSITIONS == 5
