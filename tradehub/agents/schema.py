"""The run artifact contract (feed spec §5). Fields the framework does not produce are
None and render as "not recorded" -- never backfilled, never estimated, never 0."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STATUSES = ("complete", "partial", "failed_cost", "failed_error")
RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
# Grading direction (§7): Hold is a no-call, excluded from the hit rate.
DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    ticker: str
    run_at_ct: str
    run_at_utc: str
    as_of_date: str  # YYYY-MM-DD, the market date the debate is about
    historical: bool = False
    framework_version: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    decision: str | None = None  # the framework's rating, verbatim
    analyst_summaries: dict[str, str | None] = Field(default_factory=dict)
    bull_case: str | None = None
    bear_case: str | None = None
    trader_rationale: str | None = None
    risk_verdict: str | None = None
    report_path: str | None = None  # relative to the runs dir: "<run_id>/report.md"
    inputs_note: str | None = None
    cost_usd: float | None = None
    status: Literal["complete", "partial", "failed_cost", "failed_error"] = "complete"
    error: str | None = None  # the failure class/detail when status is a failure
    # The market's own numbers at debate time (hub-side yfinance, never the
    # framework's): {price, prev_close, year_high, year_low, at}. The card
    # holds the debate's stated levels up against this anchor.
    market_anchor: dict | None = None
    # Failed runs are shown once, then deleted (Kevin, 2026-11-03): the feed
    # flips this when it serves the failure, and deletes on the next read.
    failure_seen: bool = False


class GradeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    horizon: int  # trading days: 5 or 20
    ret_pct: float
    outcome: Literal["hit", "miss", "no-call"]
    graded_at: str
