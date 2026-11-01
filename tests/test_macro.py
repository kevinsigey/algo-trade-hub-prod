"""The Macro dashboard composition (phase-3 §1): cards built from the hub's
existing reads, with per-source absence rendered as null -- never as a zero,
a clean record, or another engine's numbers."""
from __future__ import annotations

from datetime import date

from tradehub.macro import build_macro

TODAY = date(2026, 11, 1)

JOBS = [
    {"reference_month": "2026-09-01", "release_date": "2026-10-02", "nowcast_mu": 120.0,
     "kalshi_mean_1h": 118.0, "first_print": 119.0},
    {"reference_month": "2026-10-01", "release_date": "2026-11-06", "nowcast_mu": 150.0,
     "kalshi_mean_1h": 140.0, "first_print": None},
]
RUNS = [
    {"engine": "labor_nowcast", "n_settled": 300, "brier_ours": 0.18, "brier_market": 0.17,
     "gate_status": "SHADOW", "promotion_status": "SHADOW",
     "diagnostics": {"features": [{"feature": "pay_rev_3m", "flags": ["mostly_zero"]}],
                     "residuals": {"flags": []}}},
    {"engine": "cpi_nowcast", "n_settled": 24, "brier_ours": 0.21, "brier_market": 0.19,
     "gate_status": "SHADOW", "promotion_status": "SHADOW", "diagnostics": None},
]
SCORES = [{"forecaster": "gas", "forecaster_version": "v2", "n_settled": 90,
           "brier": 0.22, "brier_baseline": 0.20, "gap": 0.02, "gap_se": 0.01}]
FORECASTS = [
    {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "target": "KXCPI-26NOV",
     "probability": 0.62, "frozen_at": "2026-10-30T13:00:00Z"},
    {"forecaster": "kalshi_implied_cpi", "forecaster_version": "mkt", "target": "KXCPI-26NOV",
     "probability": 0.58, "frozen_at": "2026-10-30T13:00:00Z"},
    {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "target": "KXCPI-26OCT",
     "probability": 0.40, "frozen_at": "2026-09-30T13:00:00Z"},
    {"forecaster": "kalshi_implied_cpi", "forecaster_version": "mkt", "target": "KXCPI-26OCT",
     "probability": 0.44, "frozen_at": "2026-09-30T13:00:00Z"},
    {"forecaster": "gas", "forecaster_version": "v2", "target": "gas-2026-11-02",
     "probability": 0.55, "frozen_at": "2026-11-01T08:00:00Z"},
    {"forecaster": "kalshi_implied_gas", "forecaster_version": "mkt", "target": "gas-2026-11-02",
     "probability": 0.50, "frozen_at": "2026-11-01T08:00:00Z"},
]
SETTLEMENTS = [{"target": "KXCPI-26OCT", "outcome": 0}]


def _build(**over):
    args = dict(jobs_rows=JOBS, scoreboard_rows=RUNS, journal_scores=SCORES,
                journal_forecasts=FORECASTS, journal_settlements=SETTLEMENTS, today=TODAY)
    args.update(over)
    return {c["key"]: c for c in build_macro(**args)["cards"]}


def test_jobs_card_carries_the_live_call_the_trail_and_the_record():
    jobs = _build()["jobs"]
    assert jobs["call"]["label"] == "Oct 2026 payrolls"
    assert jobs["call"]["ours"] == 150.0 and jobs["call"]["market"] == 140.0
    assert jobs["call"]["last_actual"] == 119.0
    assert jobs["next_release"] == "2026-11-06"
    assert jobs["trail"] == [{"label": "Sep 2026", "ours": 120.0, "market": 118.0, "actual": 119.0}]
    assert jobs["trail_kind"] == "value"
    assert jobs["record"]["brier_ours"] == 0.18
    assert jobs["record"]["diagnostics_flags"] == ["pay_rev_3m: mostly_zero"]


def test_cpi_card_pairs_probabilities_by_target_and_marks_display_only():
    cpi = _build()["cpi"]
    assert cpi["display_only"] is True
    assert cpi["call"]["ours"] == 0.62 and cpi["call"]["market"] == 0.58
    assert cpi["trail"] == [{"label": "KXCPI-26OCT", "ours": 0.40, "market": 0.44, "actual": 0}]
    assert cpi["trail_kind"] == "probability"
    assert cpi["record"]["n_settled"] == 24


def test_no_gas_card_even_when_gas_rows_exist():
    # Both 2026-11-01 audits graded gas a completed, decisive loss; the Macro
    # page stops presenting it as a prediction. Its journal rows may still be
    # in the inputs -- they simply earn no card.
    assert "gas" not in _build()


def test_oil_card_pairs_with_the_kalshi_oil_row_and_reads_the_journal_record():
    scores = SCORES + [{"forecaster": "oil_wti", "forecaster_version": "wti-v1", "n_settled": 12,
                        "brier": 0.19, "brier_baseline": 0.17, "gap": 0.02, "gap_se": 0.02}]
    forecasts = FORECASTS + [
        {"forecaster": "oil_wti", "forecaster_version": "wti-v1", "target": "kalshi:KXWTI-26NOV0214-T90.49",
         "probability": 0.61, "frozen_at": "2026-11-02T18:00:00Z"},
        {"forecaster": "kalshi_implied_oil", "forecaster_version": "mkt", "target": "kalshi:KXWTI-26NOV0214-T90.49",
         "probability": 0.58, "frozen_at": "2026-11-02T18:00:00Z"},
    ]
    oil = _build(journal_scores=scores, journal_forecasts=forecasts)["oil"]
    assert oil["title"] == "Oil" and oil["display_only"] is False
    assert oil["record"]["source"] == "journal" and oil["record"]["n_settled"] == 12
    assert oil["call"]["ours"] == 0.61 and oil["call"]["market"] == 0.58
    assert oil["detail_href"] == "/journal"


def test_empty_sources_degrade_to_null_sections_never_zeros():
    cards = _build(jobs_rows=[], scoreboard_rows=[], journal_scores=[],
                   journal_forecasts=[], journal_settlements=[])
    for card in cards.values():
        assert card["call"] is None and card["record"] is None and card["trail"] == []
