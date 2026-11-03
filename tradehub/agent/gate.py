"""Phase 2 -- the accuracy gate (phase spec, 2026-11-02; built 2026-11-03).

Where a StrategySpec is expressible as a Workshop rule run, the gate runs it
through the Workshop's own verdict machinery (run_test: the shuffle bar and
the claim check on the unseen split) and records the outcome on the spec.
Where it is not expressible, the spec stays research-only with the reason
stated -- the gate never invents a translation.

Expressible in v1: an always-in universe hold (entry.rule "manual") with the
spec's exits (a pct stop, a take-profit, a time stop) and its benchmark.
Level/event entries (close_below, close_above, event) are NOT translated:
the band is relative to reference prices the spec does not carry, so a
backtest of them would be a different strategy wearing the same name.
Sizing is a staging concern (phase 3) -- the gate tests the universe and
exits at full weight and says so.
"""

from __future__ import annotations

from datetime import datetime, timezone

GATE_START = "2020-01-02"  # the Workshop's own backtests start here


def to_idea_spec(spec: dict, title: str) -> tuple[dict | None, str]:
    """(idea_spec_dict, note). idea_spec_dict is None when the strategy is
    not expressible as a rule run; the note says why, in plain words."""
    entry = spec.get("entry") or {}
    rule = entry.get("rule")
    if rule != "manual":
        return None, (f"entry rule '{rule}' is a level/event trigger: the band is relative to "
                      "reference prices the spec does not carry, so there is no faithful rule "
                      "run for it yet -- this spec stays research-only")
    stops = spec.get("stops") or {}
    exits_in = spec.get("exits") or {}
    exits: dict = {}
    notes = ["the gate tests the universe and exits at full weight; sizing applies at staging (phase 3)"]
    if stops.get("kind") == "pct" and isinstance(stops.get("value"), (int, float)):
        exits["stop_loss_pct"] = float(stops["value"])
    elif stops.get("kind") == "price":
        notes.append("a price stop does not translate to the backtest's percent stops; the run carries no stop")
    if isinstance(exits_in.get("take_profit_pct"), (int, float)):
        exits["take_profit_pct"] = float(exits_in["take_profit_pct"])
    if isinstance(exits_in.get("time_stop_days"), (int, float)):
        exits["max_days"] = int(exits_in["time_stop_days"])
    scoring = spec.get("scoring") or {}
    idea = {
        "title": title[:120],
        "hold": list(spec.get("universe") or []),
        "claim": "beats_benchmark",
        "benchmark": scoring.get("benchmark") or "SPY",
        "start": GATE_START,
    }
    if exits:
        idea["exits"] = exits
    return idea, "; ".join(notes)


def _trim(result: dict) -> dict:
    """The gate record: the verdict and the numbers behind it, without the
    equity curve (the full run stays reproducible from the stored spec)."""
    claim = result.get("claim") or {}
    shuffle = result.get("shuffle") or {}
    return {
        "verdict": result.get("verdict"),
        "headline": result.get("headline"),
        "reason": result.get("reason"),
        "split_date": result.get("split_date"),
        "data_start": result.get("data_start"),
        "data_end": result.get("data_end"),
        "claim_holds_unseen": (claim.get("unseen") or {}).get("holds"),
        "unseen": (claim.get("unseen") or {}),
        "shuffle_p": shuffle.get("p"),
        "walk_forward": result.get("walk_forward"),
        "notes": result.get("notes") or [],
    }


def run_gate(supa, row: dict, *, run_fn=None, data_fns: dict | None = None) -> dict:
    """Run the gate for one spec row and persist the outcome. Returns the
    updated row. A failed verdict blocks the spec (phase spec: blocked =
    gate failed or Kevin says no); a PASS leaves it in draft for Kevin to
    promote; a research-only spec stays draft with the reason recorded."""
    from tradehub.agent import store

    spec = row["spec"]
    idea_dict, note = to_idea_spec(spec, row["title"])
    at = datetime.now(timezone.utc).isoformat()
    if idea_dict is None:
        gate = {"expressible": False, "note": note, "at": at}
        return store.set_state(supa, row["id"], row["state"], gate=gate)

    from tradehub.workshop.data import (analyst as ws_analyst, bars as ws_bars,
                                        closes as ws_closes, fred_series as ws_fred,
                                        rule_series, with_rule_bars)
    from tradehub.workshop.engine import run_test, tickers_for
    from tradehub.workshop.spec import IdeaSpec

    fns = {"closes": ws_closes, "bars": ws_bars, "fred": ws_fred, "analyst": ws_analyst,
           "run": run_test, "div_yields": None}
    if data_fns:
        fns.update(data_fns)
    idea = IdeaSpec.model_validate(idea_dict)
    prices = with_rule_bars(idea, fns["closes"](tickers_for(idea), idea.start), idea.start,
                            bars_fn=fns["bars"])
    from datetime import timedelta

    from tradehub.workshop.data import div_yields as real_div_yields
    fred_start = idea.start - timedelta(days=3 * 366)  # main.py's _fred_start rule
    series = rule_series(idea, fred_start, fred=fns["fred"], analyst_fn=fns["analyst"])
    yields = fns["div_yields"](idea, prices) if fns["div_yields"] else real_div_yields(idea, prices)
    # Attempts count per spec (Kevin, 2026-11-03): re-running the gate used
    # to reset the bar (variations=1 every time), so a blocked spec could be
    # re-rolled until the shuffle cooperated. Each attempt tightens the bar
    # and changes the shuffle seed.
    attempts = int((row.get("gate") or {}).get("attempts") or 0) + 1
    result = (run_fn or fns["run"])(idea, prices, series, variations=attempts,
                                    seed=int(row["id"]) * 1000 + attempts, div_yields=yields)
    gate = {"expressible": True, "note": note, "at": at, "attempts": attempts,
            "idea_spec": idea_dict, **_trim(result)}
    if gate["verdict"] == "PASS":
        return store.set_state(supa, row["id"], row["state"], gate=gate)
    updated = store.set_state(supa, row["id"], "blocked", gate=gate)
    return updated
