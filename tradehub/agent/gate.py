"""Whether a drafted strategy can be expressed as a Workshop rule run, and how.

Expressible: an always-in universe hold (entry.rule "manual") with its exits and
benchmark. Level and event entries are not translated: the band is relative to
reference prices the draft doesn't carry, so a backtest of them would be a
different strategy wearing the same name.
"""

from __future__ import annotations

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
