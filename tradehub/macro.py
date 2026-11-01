"""Macro predictions dashboard composition (phase-3 §1).

Pure: composes the three macro cards (jobs, CPI, gas) from reads the hub
already makes -- the jobs scorecard rows, the scoreboard's current runs, and
the journal's scores/forecasts/settlements. No forecasting, no storage; a
source that arrives empty yields that card's section as None, which the page
renders as "unavailable" rather than as a zero or a clean record.

Card semantics stay engine-honest: jobs trails are VALUES (thousands of jobs:
ours vs the market's mean vs the first print); CPI and gas trails are
PROBABILITIES (ours vs the Kalshi-implied freeze vs the outcome). `trail_kind`
says which, and the page renders them differently -- one shape, never one
meaning smuggled into another's units.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

TRAIL_N = 8


def _diagnostic_flags(diagnostics: Mapping[str, Any] | None) -> list[str]:
    if not diagnostics:
        return []
    flags = [f"{f.get('feature')}: {flag}"
             for f in diagnostics.get("features") or [] for flag in (f.get("flags") or [])]
    flags += list((diagnostics.get("residuals") or {}).get("flags") or [])
    return flags


def _scoreboard_record(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"source": "scoreboard", "n_settled": row.get("n_settled"),
            "brier_ours": row.get("brier_ours"), "brier_market": row.get("brier_market"),
            "gate_status": row.get("gate_status"), "promotion_status": row.get("promotion_status"),
            "diagnostics_flags": _diagnostic_flags(row.get("diagnostics"))}


def _journal_record(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"source": "journal", "n_settled": row.get("n_settled"),
            "brier_ours": row.get("brier"), "brier_market": row.get("brier_baseline"),
            "gap": row.get("gap"), "gap_se": row.get("gap_se"),
            "gate_status": None, "promotion_status": None, "diagnostics_flags": []}


def _month_label(ref: str) -> str:
    try:
        return date.fromisoformat(ref).strftime("%b %Y")
    except (TypeError, ValueError):
        return str(ref)


def _jobs_card(rows: Sequence[Mapping[str, Any]], record: dict | None, today: date) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: r.get("reference_month") or "")
    settled = [r for r in ordered if r.get("first_print") is not None]
    live = [r for r in ordered if r.get("first_print") is None]
    call = None
    if live:
        cur = live[-1]
        call = {"label": f"{_month_label(cur['reference_month'])} payrolls",
                "ours": cur.get("nowcast_mu"), "market": cur.get("kalshi_mean_1h"),
                "last_actual": settled[-1].get("first_print") if settled else None,
                "as_of": cur.get("release_date")}
    elif settled:
        cur = settled[-1]
        call = {"label": f"{_month_label(cur['reference_month'])} payrolls",
                "ours": cur.get("nowcast_mu"), "market": cur.get("kalshi_mean_1h"),
                "last_actual": cur.get("first_print"), "as_of": cur.get("release_date")}
    next_release = None
    for r in ordered:
        rel = r.get("release_date")
        if rel and rel >= today.isoformat() and r.get("first_print") is None:
            next_release = rel
            break
    trail = [{"label": _month_label(r["reference_month"]), "ours": r.get("nowcast_mu"),
              "market": r.get("kalshi_mean_1h"), "actual": r.get("first_print")}
             for r in settled[-TRAIL_N:]]
    return {"key": "jobs", "title": "Jobs nowcast", "predicts": "Next nonfarm payrolls print",
            "detail_href": "/jobs", "display_only": False, "call": call, "record": record,
            "trail": trail, "trail_kind": "value", "next_release": next_release}


def _prob_card(*, key: str, title: str, predicts: str, detail_href: str, display_only: bool,
               forecaster: str, market_forecaster: str,
               forecasts: Sequence[Mapping[str, Any]], outcomes: Mapping[str, float],
               record: dict | None) -> dict[str, Any]:
    ours = [f for f in forecasts if f.get("forecaster") == forecaster]
    # Settlements are keyed by target alone (one realised outcome per target),
    # and the market's freeze pairs with ours by target -- its latest freeze
    # for that target, since both freeze inside the same scan window.
    market: dict[str, Mapping[str, Any]] = {}
    for f in forecasts:
        if f.get("forecaster") != market_forecaster:
            continue
        cur = market.get(f.get("target"))
        if cur is None or (f.get("frozen_at") or "") >= (cur.get("frozen_at") or ""):
            market[f.get("target")] = f
    # The forecaster's live version = the version carrying its score record's
    # weight (most settled targets); headline CPI and core share a name, and the
    # card is the headline story.
    by_version: dict[str, list] = {}
    for f in ours:
        by_version.setdefault(f.get("forecaster_version"), []).append(f)
    live_version = None
    if by_version:
        live_version = max(by_version, key=lambda v: sum(
            1 for f in by_version[v] if f.get("target") in outcomes))
    mine = [f for f in ours if f.get("forecaster_version") == live_version]
    unsettled = [f for f in mine if f.get("target") not in outcomes]
    call = None
    if unsettled:
        cur = max(unsettled, key=lambda f: f.get("frozen_at") or "")
        mkt = market.get(cur.get("target"))
        call = {"label": str(cur.get("target")), "ours": cur.get("probability"),
                "market": (mkt or {}).get("probability"), "last_actual": None,
                "as_of": cur.get("frozen_at")}
    settled = sorted((f for f in mine if f.get("target") in outcomes),
                     key=lambda f: f.get("target") or "")
    trail = []
    for f in settled[-TRAIL_N:]:
        mkt = market.get(f.get("target"))
        trail.append({"label": str(f.get("target")), "ours": f.get("probability"),
                      "market": (mkt or {}).get("probability"),
                      "actual": outcomes[f.get("target")]})
    return {"key": key, "title": title, "predicts": predicts, "detail_href": detail_href,
            "display_only": display_only, "call": call, "record": record,
            "trail": trail, "trail_kind": "probability", "next_release": None}


def build_macro(*, jobs_rows: Sequence[Mapping[str, Any]],
                scoreboard_rows: Sequence[Mapping[str, Any]],
                journal_scores: Sequence[Mapping[str, Any]],
                journal_forecasts: Sequence[Mapping[str, Any]],
                journal_settlements: Sequence[Mapping[str, Any]],
                today: date) -> dict[str, Any]:
    """The /api/macro body. Every input may be empty (a failed read upstream);
    the affected sections come out None/empty, never fabricated."""
    runs = {r.get("engine"): r for r in scoreboard_rows}
    outcomes = {s.get("target"): s.get("outcome")
                for s in journal_settlements if s.get("outcome") is not None}
    scores = {(s.get("forecaster"), s.get("forecaster_version")): s for s in journal_scores}
    gas_scores = [s for (name, _v), s in scores.items() if name == "gas"]
    gas_record = _journal_record(max(gas_scores, key=lambda s: s.get("n_settled") or 0) if gas_scores else None)

    cards = [
        _jobs_card(jobs_rows, _scoreboard_record(runs.get("labor_nowcast")), today),
        _prob_card(key="cpi", title="CPI", predicts="Next CPI release (headline)",
                   detail_href="/cpi", display_only=True,
                   forecaster="cpi_nowcast", market_forecaster="kalshi_implied_cpi",
                   forecasts=journal_forecasts, outcomes=outcomes,
                   record=_scoreboard_record(runs.get("cpi_nowcast"))),
        _prob_card(key="gas", title="Gas", predicts="AAA gasoline price direction (daily)",
                   detail_href="/journal", display_only=False,
                   forecaster="gas", market_forecaster="kalshi_implied_gas",
                   forecasts=journal_forecasts, outcomes=outcomes, record=gas_record),
    ]
    return {"as_of": today.isoformat(), "cards": cards}
