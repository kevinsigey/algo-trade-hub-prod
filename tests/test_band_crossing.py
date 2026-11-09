"""Spec C band-crossing engine (log-only): zone logic, the candidate rules,
the crossing state machine, and the frozen falsifier grading.

The CEG numbers are the spec's own worked example (bands from the Nov 9
sheet): base $215.54 vs price $249.95 must produce NO long crossing.
"""
from datetime import UTC, datetime

import pandas as pd
import pytest
from workshop_fake import DB

from tradehub.valuation import band_crossing as bc

NOW = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
CEG_BANDS = {"bear": 185.90, "base": 215.54, "bull": 224.52}


def sheet(ticker="CEG", *, price=249.95, bands=None, direction="raised",
          stale=False, status="banded", basis="eps", computed_at="2026-11-07T21:00:00Z"):
    metric = "revenue" if basis == "revenue" else "eps_adjusted"
    return {"ticker": ticker, "status": status, "bands": bands if bands is not None else dict(CEG_BANDS),
            "band_basis": basis, "price": price, "price_as_of": "2026-11-07",
            "stale": stale, "peer_group": "sector:Utilities",
            "anchor": {"metric": metric, "period": "FY2026"},
            "directions": {metric: {"direction": direction, "period": "FY2026"}},
            "computed_at": computed_at}


def cand(**kw):
    base = dict(zone="base", guide_status="intact", t1=None, held_mv=0.0, equity=100_000.0)
    base.update(kw)
    return bc.candidate(**base)


# ── zones ────────────────────────────────────────────────────────────────────

def test_zone_boundaries():
    assert bc.zone_of(185.90, CEG_BANDS) == "bear"      # at bear = bear zone
    assert bc.zone_of(200.0, CEG_BANDS) == "base"
    assert bc.zone_of(215.54, CEG_BANDS) == "base"      # at base = base zone
    assert bc.zone_of(220.0, CEG_BANDS) == "bull"
    assert bc.zone_of(224.52, CEG_BANDS) == "bull"      # at bull = still in band
    assert bc.zone_of(224.53, CEG_BANDS) == "above_bull"


def test_guide_status_mapping():
    assert bc.guide_status_of(sheet(direction="raised")) == ("raised", "raised")
    assert bc.guide_status_of(sheet(direction="held")) == ("intact", "held")
    assert bc.guide_status_of(sheet(direction="first")) == ("intact", "first")
    assert bc.guide_status_of(sheet(direction="cut")) == ("cut", "cut")
    s = sheet()
    s["directions"] = {}
    assert bc.guide_status_of(s) == ("unknown", None)


# ── the candidate rules ──────────────────────────────────────────────────────

def test_ceg_worked_example_no_long_crossing():
    # Price above the bull band: not a long zone, whatever the file says.
    zone = bc.zone_of(249.95, CEG_BANDS)
    assert zone == "above_bull"
    out = cand(zone=zone, guide_status="raised", held_mv=0.0)
    assert out["action"] is None
    assert out["suppress_reason"] == "no_t1_classification"  # short gated on T1


def test_starter_at_base_zone_two_percent():
    out = cand(zone="base")
    assert out["action"] == "starter" and out["target_pct"] == 2.0
    assert out["delta_usd"] == pytest.approx(2_000.0)


def test_bear_zone_targets_four_percent_and_adds():
    out = cand(zone="bear", held_mv=1_000.0)
    assert out["action"] == "add" and out["target_pct"] == 4.0
    assert out["delta_usd"] == pytest.approx(3_000.0)
    fresh = cand(zone="bear", held_mv=0.0)
    assert fresh["action"] == "starter" and fresh["target_pct"] == 4.0


def test_guide_cut_suppresses_long():
    out = cand(zone="base", guide_status="cut")
    assert out["action"] is None and out["suppress_reason"] == "guide_cut"
    out = cand(zone="bear", guide_status="unknown")
    assert out["action"] is None and out["suppress_reason"] == "guide_status_unknown"


def test_long_at_target_is_none():
    out = cand(zone="base", held_mv=2_500.0)
    assert out["action"] is None and out["suppress_reason"] == "target_reached"


def test_trim_and_review_and_short_above_bull():
    held = cand(zone="above_bull", held_mv=10_000.0)
    assert held["action"] == "trim_half" and held["delta_usd"] == pytest.approx(-5_000.0)
    review = cand(zone="above_bull", held_mv=10_000.0, t1="deteriorated")
    assert review["action"] == "review_full_exit"
    short = cand(zone="above_bull", held_mv=0.0, t1="deteriorated")
    assert short["action"] == "short_put_spread" and short["delta_usd"] == pytest.approx(-1_500.0)
    intact = cand(zone="above_bull", held_mv=0.0, t1="intact")
    assert intact["action"] is None and intact["suppress_reason"] is None


def test_bull_zone_no_rule():
    assert cand(zone="bull", held_mv=5_000.0)["action"] is None


# ── the scan + state machine ─────────────────────────────────────────────────

class Rig:
    """A scan wired to fakes: sheets in the DB, positions/equity/T1 stubbed."""

    def __init__(self, sheets, *, positions=None, equity=100_000.0, t1=None, pc=None):
        self.db = DB()
        self.db.db["valuation_fact_sheets"] = sheets
        self.db.db["band_crossing_controls"] = [
            {"scope": "global", "orders_enabled": False, "note": "log-only"}]
        self.positions = positions or {}
        self.equity = equity
        self.t1 = t1 or {}
        self.pc = pc or (lambda book, ticker, delta: ("would_pass", "passes"))

    def scan(self, kind="weekly"):
        return bc.run_scan(
            self.db, kind=kind, now=NOW,
            positions_reader=lambda book: self.positions.get(book, {}),
            equity_reader=lambda book: self.equity,
            t1_reader=lambda client, ticker: self.t1.get(ticker),
            pc_runner=self.pc)

    def crossings(self):
        return self.db.db.get("band_crossings", [])


def test_baseline_scan_establishes_state_and_logs_nothing():
    rig = Rig([sheet(price=200.0)])  # base zone, guide raised
    out = rig.scan()
    assert out["kind"] == "baseline" and out["crossings_written"] == 0
    assert rig.crossings() == []
    states = rig.db.db["band_crossing_state"]
    assert {(s["ticker"], s["book"]) for s in states} == {("CEG", "main"), ("CEG", "big")}
    assert all(s["action"] == "starter" for s in states)


def test_transition_into_actionable_zone_logs_one_crossing_then_silence():
    rig = Rig([sheet(price=220.0)])  # bull zone: no candidate
    rig.scan()  # baseline
    rig.db.db["valuation_fact_sheets"] = [sheet(price=200.0)]  # drops to base
    out = rig.scan()
    assert out["crossings_written"] == 2  # one per book
    rows = rig.crossings()
    assert all(r["action"] == "starter" and r["zone"] == "base" for r in rows)
    assert all(r["mode"] == "log_only" and r["pc_outcome"] == "would_pass" for r in rows)
    assert all(r["industry"] == "Utilities" for r in rows)
    out = rig.scan()  # still in the zone, unchanged candidate: nothing new
    assert out["crossings_written"] == 0 and len(rig.crossings()) == 2


def test_zone_exit_logs_a_none_row_once():
    rig = Rig([sheet(price=200.0)])
    rig.scan()  # baseline with starter candidate in state
    rig.db.db["valuation_fact_sheets"] = [sheet(price=220.0)]  # back inside the band
    out = rig.scan()
    assert out["crossings_written"] == 2
    rows = rig.crossings()
    assert all(r["action"] == "none" and r["suppress_reason"] == "zone_exit" for r in rows)
    assert all(r["prev_action"] == "starter" for r in rows)


def test_guide_cut_after_candidate_logs_none_with_reason():
    rig = Rig([sheet(price=200.0, direction="raised")])
    rig.scan()
    rig.db.db["valuation_fact_sheets"] = [sheet(price=200.0, direction="cut")]
    out = rig.scan()
    assert out["crossings_written"] == 2
    assert all(r["suppress_reason"] == "guide_cut" for r in rig.crossings())


def test_gated_zone_transition_logs_the_gate_behaving():
    # Baseline sits in the bull zone; price falls into the base zone but the
    # guide was cut: one 'none' row naming the gate, no long crossing.
    rig = Rig([sheet(price=220.0)])
    rig.scan()
    rig.db.db["valuation_fact_sheets"] = [sheet(price=200.0, direction="cut")]
    out = rig.scan()
    assert out["crossings_written"] == 2
    rows = rig.crossings()
    assert all(r["action"] == "none" and r["suppress_reason"] == "guide_cut" for r in rows)


def test_stale_sheet_is_skipped_and_state_untouched():
    rig = Rig([sheet(price=200.0)])
    rig.scan()
    rig.db.db["valuation_fact_sheets"] = [sheet(price=150.0, stale=True)]
    out = rig.scan()
    assert out["crossings_written"] == 0
    assert out["skipped"] == [{"ticker": "CEG", "reason": "stale_sheet"}]
    states = rig.db.db["band_crossing_state"]
    assert all(s["zone"] == "base" for s in states)  # frozen, not re-zoned


def test_unbanded_names_never_enter_state():
    rig = Rig([sheet(status="no_full_year_guide", bands=None)])
    out = rig.scan()
    assert out["banded_names"] == 0 and rig.db.db.get("band_crossing_state", []) == []


def test_trim_crossing_for_held_name_and_pc_block_recorded():
    pc = lambda book, ticker, delta: ("would_block", "CEG would be 9.0% of invested")  # noqa: E731
    rig = Rig([sheet(price=220.0)], positions={"main": {"CEG": {"qty": 40.0, "mv": 10_000.0}}}, pc=pc)
    rig.scan()  # baseline: bull zone, no candidate
    rig.db.db["valuation_fact_sheets"] = [sheet(price=260.0)]  # above bull
    out = rig.scan()
    # Two rows: main's trim, and big's gated short evaluation (no T1 on
    # file) — the gate behaving is part of the record, per the freeze.
    assert out["crossings_written"] == 2
    row = next(r for r in rig.crossings() if r["book"] == "main")
    assert row["action"] == "trim_half"
    assert row["pc_outcome"] == "would_block"
    assert row["pc_detail"] == "CEG would be 9.0% of invested"
    assert row["held_mv"] == 10_000.0
    big = next(r for r in rig.crossings() if r["book"] == "big")
    assert big["action"] == "none" and big["suppress_reason"] == "no_t1_classification"


def test_orders_enabled_defaults_off_and_reads_the_row():
    db = DB()
    assert bc.orders_enabled(db) is False  # no table yet: born log-only
    db.db["band_crossing_controls"] = [{"scope": "global", "orders_enabled": False}]
    assert bc.orders_enabled(db) is False
    db.db["band_crossing_controls"] = [{"scope": "global", "orders_enabled": True}]
    assert bc.orders_enabled(db) is True  # the row is honored (a future build's switch)


# ── grading: the frozen falsifier math ───────────────────────────────────────

def _closes(prices):
    idx = pd.bdate_range("2024-01-02", periods=len(prices))
    return pd.Series(prices, index=idx, dtype=float)


def test_outcome_scores_a_timed_entry_above_the_unconditional_control():
    # Flat for 300 sessions, then +1%/day: an entry at the turn beats the
    # unconditional control (which mostly sat in the flat stretch).
    prices = [100.0] * 300 + [100.0 * 1.01 ** k for k in range(1, 41)]
    closes = _closes(prices)
    entry_date = str(closes.index[300].date())
    out = bc.compute_outcome(closes, entry_date, 20, +1)
    assert out is not None and out["ret_pct"] > 15.0
    assert out["excess_pct"] > 10.0 and out["score"] > 0
    short = bc.compute_outcome(closes, entry_date, 20, -1)
    assert short["score"] == pytest.approx(-out["score"])


def test_outcome_none_when_window_immature_or_control_thin():
    closes = _closes([100.0] * 30)
    assert bc.compute_outcome(closes, str(closes.index[10].date()), 20, +1) is None
    closes = _closes([100.0] * 400)
    # Flat series: sigma is zero, so the score is ungradeable, honestly None.
    assert bc.compute_outcome(closes, str(closes.index[300].date()), 20, +1) is None


def test_falsifier_summary_counts_and_verdicts():
    rows = [{"action": "starter", "score_20": 0.5}] * 19
    out = bc.falsifier_summary(rows)
    assert out["graded"] == 19 and out["status"] == "accruing"
    rows.append({"action": "add", "score_20": -0.4})
    out = bc.falsifier_summary(rows)
    assert out["graded"] == 20 and out["status"] == "survived"  # mean > 0
    out = bc.falsifier_summary([{"action": "starter", "score_20": -0.1}] * 20)
    assert out["status"] == "shelved"
    out = bc.falsifier_summary([{"action": "trim_half", "score_20": 9.9}])
    assert out["graded"] == 0  # trims are not entries
