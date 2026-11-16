"""Thesis tracker PR 4: the pure grading math.

Conventions under test (design docs/superpowers/specs/
2026-11-16-thesis-tracker-design.md, spec Section 3/5): the reaction
session is the first session whose close reflects the print (same day
for a pre-open print, next session for an at/after-close or weekend
print); ret_1d is the reaction return off the pre-print close and
ret_3d/ret_5d are cumulative to the 3rd/5th session counting the
reaction session as day 1; SPY is measured over the same dates; an
outcome exists only when EVERY horizon is computable (no partial
outcomes). Hits are sign agreement on the reaction return; a flat
whisper / intact classification hits inside a 1% band; a mixed money
flow makes no directional call and is never graded.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from tradehub.tracker import grading

# Trading days around a Friday Nov 20, 2026 after-hours print
# (Thanksgiving Thu Nov 26 is not a session).
DAYS = [date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 23),
        date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27),
        date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2)]
TICKER = [(date(2026, 11, 19), 98.0), (date(2026, 11, 20), 100.0),
          (date(2026, 11, 23), 110.0), (date(2026, 11, 24), 105.0),
          (date(2026, 11, 25), 99.0), (date(2026, 11, 27), 115.0),
          (date(2026, 11, 30), 121.0), (date(2026, 12, 1), 120.0),
          (date(2026, 12, 2), 118.0)]
SPY = [(date(2026, 11, 19), 498.0), (date(2026, 11, 20), 500.0),
       (date(2026, 11, 23), 505.0), (date(2026, 11, 24), 502.0),
       (date(2026, 11, 25), 495.0), (date(2026, 11, 27), 508.0),
       (date(2026, 11, 30), 510.0), (date(2026, 12, 1), 511.0),
       (date(2026, 12, 2), 512.0)]

AFTER_HOURS = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)  # 16:00 ET


def _card(**over):
    card = {"ticker": "NVDA", "print_at": AFTER_HOURS.isoformat(),
            "whisper_sign": "positive", "money_flow_direction": "inflow",
            "classification": "improved"}
    card.update(over)
    return card


# -- the reaction session -------------------------------------------------------


def test_after_hours_print_reacts_next_session():
    out = grading.grade_outcome(_card(), TICKER, SPY)
    assert out is not None
    assert out["reaction_close"] == 110.0          # Mon Nov 23 close
    assert abs(out["ret_1d"] - 0.10) < 1e-12       # off Fri's 100 base


def test_preopen_print_reacts_the_same_session():
    card = _card(print_at=datetime(2026, 11, 25, 12, 0,
                                   tzinfo=timezone.utc).isoformat())
    out = grading.grade_outcome(card, TICKER, SPY)
    # Reaction = Wed Nov 25 off Tue Nov 24's close (105 -> 99).
    assert out["reaction_close"] == 99.0
    assert abs(out["ret_1d"] - (99.0 / 105.0 - 1)) < 1e-12


def test_weekend_print_reacts_monday():
    card = _card(print_at=datetime(2026, 11, 21, 15, 0,
                                   tzinfo=timezone.utc).isoformat())
    out = grading.grade_outcome(card, TICKER, SPY)
    assert out["reaction_close"] == 110.0
    assert abs(out["ret_1d"] - 0.10) < 1e-12


# -- horizons, SPY, excess -------------------------------------------------------


def test_horizons_are_cumulative_off_the_preprint_close():
    out = grading.grade_outcome(_card(), TICKER, SPY)
    assert abs(out["ret_1d"] - 0.10) < 1e-12        # Nov 23: 110/100
    assert abs(out["ret_3d"] - (99.0 / 100.0 - 1)) < 1e-12    # Nov 25
    assert abs(out["ret_5d"] - (121.0 / 100.0 - 1)) < 1e-12   # Nov 30
    assert abs(out["spy_1d"] - (505.0 / 500.0 - 1)) < 1e-12
    assert abs(out["spy_3d"] - (495.0 / 500.0 - 1)) < 1e-12
    assert abs(out["spy_5d"] - (510.0 / 500.0 - 1)) < 1e-12
    assert abs(out["excess_1d"] - (out["ret_1d"] - out["spy_1d"])) < 1e-12
    assert abs(out["excess_5d"] - (out["ret_5d"] - out["spy_5d"])) < 1e-12


def test_no_partial_outcome_when_the_5d_bar_is_missing():
    assert grading.grade_outcome(_card(), TICKER[:6], SPY) is None
    assert grading.grade_outcome(_card(), TICKER, SPY[:6]) is None


def test_no_outcome_without_a_preprint_base_close():
    assert grading.grade_outcome(_card(), TICKER[2:], SPY) is None


# -- the three hits, graded separately -------------------------------------------


def test_hits_agree_with_an_up_reaction():
    out = grading.grade_outcome(_card(), TICKER, SPY)
    assert out["whisper_hit"] is True
    assert out["money_flow_hit"] is True
    assert out["classification_hit"] is True


def test_hits_disagree_when_the_signs_flip():
    card = _card(whisper_sign="negative", money_flow_direction="outflow",
                 classification="deteriorated")
    out = grading.grade_outcome(card, TICKER, SPY)   # reaction is +10%
    assert out["whisper_hit"] is False
    assert out["money_flow_hit"] is False
    assert out["classification_hit"] is False


def test_mixed_money_flow_and_missing_signals_are_never_graded():
    card = _card(whisper_sign=None, money_flow_direction="mixed",
                 classification=None)
    out = grading.grade_outcome(card, TICKER, SPY)
    assert out["whisper_hit"] is None
    assert out["money_flow_hit"] is None
    assert out["classification_hit"] is None


def test_flat_whisper_and_intact_grade_inside_the_band():
    flat = [(d, 100.0) for d in DAYS]
    flat[2] = (date(2026, 11, 23), 100.5)            # +0.5% reaction
    card = _card(whisper_sign="flat", classification="intact",
                 money_flow_direction="mixed")
    out = grading.grade_outcome(card, flat, SPY)
    assert out["whisper_hit"] is True
    assert out["classification_hit"] is True
    big = [(d, 100.0) for d in DAYS]
    big[2] = (date(2026, 11, 23), 104.0)             # +4% reaction
    out = grading.grade_outcome(card, big, SPY)
    assert out["whisper_hit"] is False
    assert out["classification_hit"] is False


# -- Claim A progress --------------------------------------------------------------


def _a_rows(hits: int, graded: int, *, none: int = 0):
    rows = [{"classification_hit": True}] * hits \
        + [{"classification_hit": False}] * (graded - hits) \
        + [{"classification_hit": None}] * none
    return rows


def test_claim_a_waits_for_its_40_prints():
    p = grading.claim_a_progress(_a_rows(39, 39, none=3))
    assert p["graded"] == 39 and p["hits"] == 39
    assert p["separation"] == 1.0
    assert p["prints_remaining"] == 1
    assert p["verdict"] is None


def test_claim_a_passes_at_60_percent_and_fires_below():
    assert grading.claim_a_progress(_a_rows(24, 40))["verdict"] == "passed"
    assert grading.claim_a_progress(_a_rows(23, 40))["verdict"] == "fired"


def test_claim_a_kill_on_a_rolling_60_below_50_percent():
    rows = _a_rows(24, 40) + _a_rows(5, 20)          # 29/60 rolling
    p = grading.claim_a_progress(rows)
    assert p["rolling60_separation"] == 29 / 60
    assert p["verdict"] == "killed"


# -- Claim C progress --------------------------------------------------------------


def test_claim_c_waits_for_five_fires_then_judges_the_first_five():
    assert grading.claim_c_progress([100.0, -50.0])["verdict"] is None
    p = grading.claim_c_progress([100.0, -50.0, 25.0, -10.0, 5.0])
    assert p["fires"] == 5 and p["net"] == 70.0 and p["verdict"] == "passed"
    # Net exactly zero is not positive: the form dies.
    assert grading.claim_c_progress([10.0, -10.0, 0.0, 0.0, 0.0])["verdict"] == "fired"
    # A later rescue does not reopen the frozen first-five window.
    p = grading.claim_c_progress([-5.0] * 5 + [1000.0])
    assert p["verdict"] == "fired" and p["net"] == -25.0
