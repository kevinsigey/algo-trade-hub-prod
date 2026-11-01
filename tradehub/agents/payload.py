"""The Ideas-feed payload (feed spec §6): cards with the mandatory labels, and the
debate record kept separate in the header. Display strings are resolved here --
a missing field renders the literal "not recorded", an ungraded horizon "pending" --
so the frontend never invents a placeholder of its own."""

from __future__ import annotations

import pandas as pd

from tradehub.agents.grader import HORIZONS, record_summary
from tradehub.agents.schema import GradeEntry, RunRecord

CHIP = "LLM agent debate — not a model signal"
NOT_RECORDED = "not recorded"
STALE_AFTER_TRADING_DAYS = 5


def _or_nr(value: str | None) -> str:
    return value if value else NOT_RECORDED


def is_stale(run: RunRecord, latest_session: str | None) -> bool:
    """Stale after 5 trading days from the as-of date (business days as the calendar
    proxy, the same convention the hub's other stale labels use)."""
    if latest_session is None:
        return False
    days = len(pd.bdate_range(run.as_of_date, latest_session)) - 1
    return days > STALE_AFTER_TRADING_DAYS


def card(run: RunRecord, grades: list[GradeEntry], *, latest_session: str | None) -> dict:
    mine = {g.horizon: g for g in grades if g.run_id == run.run_id}
    grade_view = {}
    for horizon in HORIZONS:
        g = mine.get(horizon)
        grade_view[f"+{horizon}d"] = ({"ret_pct": g.ret_pct, "outcome": g.outcome} if g is not None
                                      else "pending")
    return {
        "source": "agent_debate",
        "chip": CHIP,
        "run_id": run.run_id,
        "ticker": run.ticker,
        "decision": run.decision if run.decision else NOT_RECORDED,
        "run_at_ct": run.run_at_ct,
        "as_of_date": run.as_of_date,
        "historical": run.historical,
        "historical_label": "historical run" if run.historical else None,
        "framework_version": _or_nr(run.framework_version),
        "framework_short": (run.framework_version[:7] if run.framework_version else NOT_RECORDED),
        "llm_provider": _or_nr(run.llm_provider),
        "llm_model": _or_nr(run.llm_model),
        "status": run.status,
        "error": run.error,
        "stale": is_stale(run, latest_session),
        "cost_usd": run.cost_usd if run.cost_usd is not None else NOT_RECORDED,
        "inputs_note": _or_nr(run.inputs_note),
        "analyst_summaries": {k: _or_nr(v) for k, v in
                              sorted(run.analyst_summaries.items())} or
                             {k: NOT_RECORDED for k in ("fundamentals", "sentiment", "news", "technicals")},
        "bull_case": _or_nr(run.bull_case),
        "bear_case": _or_nr(run.bear_case),
        "trader_rationale": _or_nr(run.trader_rationale),
        "risk_verdict": _or_nr(run.risk_verdict),
        "has_report": run.report_path is not None,
        "grades": grade_view,
    }


def feed(runs: list[RunRecord], grades: list[GradeEntry], *, latest_session: str | None) -> dict:
    summary = record_summary(grades)
    return {
        "chip": CHIP,
        "cards": [card(r, grades, latest_session=latest_session) for r in runs],
        "record": summary,
        "banner": "No edge detected in graded runs" if summary["banner"] else None,
    }
