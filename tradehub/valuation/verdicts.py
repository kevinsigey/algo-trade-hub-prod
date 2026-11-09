"""Verdict rendering (Phase 1): one ticker's fact sheet becomes Exhibit A,
the forked debate argues over it, the structurer builds the typed packet,
and the decision seat renders the verdict. The stored record carries the
verdict, the judge identity, BOTH controls (the band-rule baseline off the
sheet and the proposer's own pick), the peer state frozen at render, the
options-layer inputs, and the falsifier — everything grading needs, frozen.

Display-only (spec section 6 authority): this module has no path to ideas,
books, or orders. A stale sheet does not debate and does not render a
verdict; an unbanded sheet has nothing to debate. A packet that fails
validation against the sheet logs a VOID verdict — the failure is on the
record, never silently dropped and never repaired by guessing.
"""
from __future__ import annotations

import os
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from tradehub.valuation import debate_fork, exhibit, judge, verdict_store
from tradehub.valuation import llm as val_llm
from tradehub.valuation import options_layer
from tradehub.valuation import store as val_store

CT = ZoneInfo("America/Chicago")
DAILY_CAP = int(os.getenv("VALUATION_DAILY_CAP", "10"))


def _peer_prices(ds, members: list[str]) -> dict[str, tuple[float, str]]:
    """{ticker: (last close, as-of date)} from one batched price pull."""
    if not members:
        return {}
    frame = ds.prices(members, years=1)
    out: dict[str, tuple[float, str]] = {}
    for member in members:
        if member not in frame.columns:
            continue
        series = frame[member].dropna()
        if len(series):
            out[member] = (float(series.iloc[-1]),
                           series.index[-1].date().isoformat())
    return out


def _target_price(decision: dict | None, bands: dict | None) -> float | None:
    """The next band beyond the verdict's anchor, in the verdict's direction
    — the path-quality target grading watches for. None for watch/pass, a
    directionless verdict, or an anchor with no band beyond it."""
    if not decision or not bands:
        return None
    direction = decision.get("direction")
    choice = decision.get("choice_id")
    if direction == "long":
        return {"act_at_band_low": bands.get("base"),
                "act_at_band_mid": bands.get("bull")}.get(choice)
    if direction == "short":
        return {"act_at_band_mid": bands.get("bear")}.get(choice)
    return None


def _classic_debate_id(ticker: str, as_of: str) -> str | None:
    """The classic TradingAgents run for the same ticker/session, when one
    exists — the two panels sit side by side on the Debates page, and the
    verdict links its sibling rather than pretending to be it."""
    try:
        from tradehub.agents import store as agents_store

        for run in agents_store.list_runs():
            if run.ticker == ticker and run.as_of_date == as_of \
                    and run.status in ("complete", "partial"):
                return run.run_id
    except Exception:  # noqa: BLE001 -- a missing sibling is not a failure
        return None
    return None


def cap_reached(client, now: datetime) -> bool:
    """The shared daily debate budget (section 5): renders of every trigger
    kind, voids included, count against the same 10/day cap."""
    start_ct = datetime.combine(now.astimezone(CT).date(), time.min, CT)
    since = start_ct.astimezone(timezone.utc).isoformat()
    return len(verdict_store.verdicts_since(client, since)) >= DAILY_CAP


def render_verdict(client, ds, ticker: str, *, trigger: str,
                   chat=None, seat=None, now: datetime | None = None) -> dict:
    """Render (or decline to render) one verdict. Returns a status dict:
    rendered / void carry the stored row under 'verdict_row'; the declines
    (no_sheet, not_banded, stale_sheet, cap_reached, llm_unavailable,
    seat_unavailable) carry a 'reason' and store nothing."""
    now = now or datetime.now(timezone.utc)
    ticker = ticker.strip().upper()
    chat = chat or val_llm.chat
    sheet = val_store.latest_sheet(client, ticker)
    if sheet is None:
        return {"status": "no_sheet", "ticker": ticker,
                "reason": f"no fact sheet for {ticker}"}
    if sheet.get("status") != "banded" or not sheet.get("bands"):
        return {"status": "not_banded", "ticker": ticker,
                "reason": f"{ticker} has no bands "
                          f"(sheet status {sheet.get('status')})"}
    if sheet.get("stale"):
        return {"status": "stale_sheet", "ticker": ticker,
                "reason": f"{ticker}'s fact sheet is stale — a stale sheet "
                          "does not debate and does not render a verdict"}
    if cap_reached(client, now):
        return {"status": "cap_reached", "ticker": ticker,
                "reason": f"the daily debate budget ({DAILY_CAP}/day) is "
                          "spent"}

    ex = exhibit.exhibit_a(sheet)
    frozen = exhibit.freeze_peer_states(
        sheet, prices_fn=lambda members: _peer_prices(ds, members))
    options = options_layer.gather(ds, ticker, sheet)
    base_row = {
        "ticker": ticker,
        "rendered_at": now.isoformat(),
        "trigger": trigger,
        "fact_sheet_id": sheet.get("id"),
        "fact_sheet_computed_at": sheet.get("computed_at"),
        "price": sheet.get("price"),
        "price_as_of": sheet.get("price_as_of"),
        "bands": sheet.get("bands"),
        "band_basis": sheet.get("band_basis", "eps"),
        "baseline_verdict": sheet.get("baseline_verdict"),
        "falsifier": sheet.get("falsifier"),
        "options_inputs": options,
        "frozen_peers": frozen,
        "entry_price": sheet.get("price"),
        "debate_run_id": _classic_debate_id(
            ticker, now.astimezone(CT).date().isoformat()),
    }
    try:
        debate = debate_fork.run_debate(ex, chat=chat)
    except debate_fork.PacketInvalid as exc:
        row = verdict_store.insert_verdict(client, {
            **base_row, "status": "void", "judge": None,
            "proposer_model": None, "verdict": None, "proposer_pick": None,
            "choices": None, "rubric_weights": None, "digest": None,
            "bull_case": None, "bear_case": None,
            "target_price": None, "void_reason": str(exc)})
        return {"status": "void", "ticker": ticker, "verdict_row": row,
                "reason": str(exc)}
    except val_llm.LLMUnavailable as exc:
        return {"status": "llm_unavailable", "ticker": ticker,
                "reason": f"the debate could not run: {exc.reason}"}

    packet = debate["packet"]
    seat = seat or judge.seat_for_env()
    try:
        decision = seat.render(packet)
    except judge.SeatUnavailable as exc:
        return {"status": "seat_unavailable", "ticker": ticker,
                "reason": str(exc)}
    row = verdict_store.insert_verdict(client, {
        **base_row,
        "status": "rendered",
        "judge": seat.judge_id,
        "proposer_model": debate.get("proposer_model"),
        "verdict": decision,
        "proposer_pick": packet["proposer_pick"],
        "choices": packet["choices"],
        "rubric_weights": packet["rubric_weights"],
        "digest": packet["digest"],
        "bull_case": debate["bull_case"],
        "bear_case": debate["bear_case"],
        "target_price": _target_price(decision, sheet.get("bands")),
        "void_reason": None,
    })
    return {"status": "rendered", "ticker": ticker, "verdict_row": row}
