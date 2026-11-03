"""The in-site agent's StrategySpec: the ONLY thing the interpreter's LLM
may emit (phase spec, Nov 2 2026). Deterministic code validates it here;
the compiler (phase 3) will turn valid specs into machine-API orders.

Rules carried from the hub: per-name cap 25% of equity (the go-live gate's
own rule), sizing is a percent of equity, stops are pct / price / none, and
a horizon terminal date is an ISO date. Validation problems NAME the field
-- the interpreter returns them to Kevin as questions, never guesses.
"""
from __future__ import annotations

import re
from datetime import date

ENTRY_RULES = ("close_below", "close_above", "manual", "event")
STOP_KINDS = ("pct", "price", "none")
MONITOR_KINDS = ("price_cross", "headline_keyword", "invalidation", "terminal_date")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def validate_spec(spec) -> list[str]:
    """Human-readable problems, each naming its field; [] means valid."""
    if not isinstance(spec, dict):
        return ["spec: the interpreter must return a JSON object"]
    problems: list[str] = []

    thesis = spec.get("thesis")
    if not isinstance(thesis, str) or len(thesis.strip()) < 20:
        problems.append("thesis: one paragraph (20+ characters) in Kevin's words, condensed")
    for key in ("catalysts", "invalidation"):
        value = spec.get(key)
        if value is not None and (not isinstance(value, list)
                                  or any(not isinstance(x, str) or not x.strip() for x in value)):
            problems.append(f"{key}: a list of short strings")

    universe = spec.get("universe")
    if not isinstance(universe, list) or not universe:
        problems.append("universe: a non-empty list of tickers is required")
    elif any(not isinstance(t, str) or not _TICKER.match(t) for t in universe):
        problems.append("universe: every entry must be a ticker symbol (e.g. XLE)")

    entry = spec.get("entry") or {}
    if entry.get("rule") not in ENTRY_RULES:
        problems.append(f"entry.rule: one of {', '.join(ENTRY_RULES)}")
    band = entry.get("band_pct")
    if band is not None and (not isinstance(band, (int, float)) or not 0 < float(band) <= 20):
        problems.append("entry.band_pct: a percent between 0 and 20")

    sizing = spec.get("sizing") or {}
    if sizing.get("kind") != "pct_of_equity":
        problems.append("sizing.kind: 'pct_of_equity' (the only sizing the hub stages)")
    value = sizing.get("value")
    if not isinstance(value, (int, float)) or not 0 < float(value) <= 100:
        problems.append("sizing.value: percent of equity, 0-100")
    cap = sizing.get("per_name_cap_pct")
    if cap is not None and (not isinstance(cap, (int, float)) or not 0 < float(cap) <= 25):
        problems.append("sizing.per_name_cap_pct: at most 25 (the hub's per-name cap)")

    stops = spec.get("stops") or {}
    if stops.get("kind") not in STOP_KINDS:
        problems.append(f"stops.kind: one of {', '.join(STOP_KINDS)}")
    elif stops["kind"] != "none" and not isinstance(stops.get("value"), (int, float)):
        problems.append("stops.value: required when stops.kind is pct or price")

    exits = spec.get("exits") or {}
    for key in ("take_profit_pct", "time_stop_days"):
        value = exits.get(key)
        if value is not None and (not isinstance(value, (int, float)) or float(value) <= 0):
            problems.append(f"exits.{key}: a positive number or null")

    horizon = spec.get("horizon") or {}
    terminal = horizon.get("terminal_date")
    if terminal is not None:
        if not isinstance(terminal, str) or not _DATE.match(terminal):
            problems.append("horizon.terminal_date: an ISO date (YYYY-MM-DD) or null")
        else:
            try:
                date.fromisoformat(terminal)
            except ValueError:
                problems.append("horizon.terminal_date: not a real calendar date")

    monitoring = spec.get("monitoring")
    if monitoring is not None and (not isinstance(monitoring, list)
                                   or any(m not in MONITOR_KINDS for m in monitoring)):
        problems.append(f"monitoring: a list drawn from {', '.join(MONITOR_KINDS)}")

    scoring = spec.get("scoring") or {}
    benchmark = scoring.get("benchmark")
    if benchmark is not None and (not isinstance(benchmark, str) or not _TICKER.match(benchmark)):
        problems.append("scoring.benchmark: a ticker symbol (default SPY)")
    return problems
