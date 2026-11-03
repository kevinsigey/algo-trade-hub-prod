"""Why a run lost: the recurring pattern in its losing trades, and which part of the spec it points at.

A diagnosis, not a verdict: it never changes a run's result. Trades are the spans the idea held,
with long holds cut into monthly blocks so an always-in idea still has something to compare; only
real entries can be blamed on entry timing. A
trade loses when it trails the benchmark. Market conditions are read from the day before entry,
so the diagnosis only uses what was known at the time.
"""

from __future__ import annotations

from math import comb

import numpy as np
import pandas as pd

from tradehub.portfolio.sectors import sector_for
from tradehub.workshop.critic import regime_tags

BLOCK_DAYS = 21
MIN_TRADES, MIN_LOSERS = 10, 5
MIN_TAGGED, MIN_LIFT = 5, 1.2
ALPHA = 0.05  # a lead over the base rate this likely by chance isn't a pattern
BIG_MOVE = 0.015
MAX_SUGGESTIONS = 5  # per idea; every revision still counts against the idea's bar

_SUGGEST = {
    "gate": "Try a rule that stays out in {tag}.",
    "entry": "Try waiting a day after large market moves before entering.",
    "exit": "Try a stop: a few trades did most of the damage.",
    "sizing": "Try a smaller weight on {tag}, or dropping it.",
}


def tail_probability(lost: int, n: int, base: float) -> float:
    """The chance of at least `lost` losers out of `n` if this group lost at the base rate."""
    return sum(comb(n, k) * base ** k * (1 - base) ** (n - k) for k in range(lost, n + 1))


def trades(frame: pd.DataFrame) -> list[dict]:
    """Held spans as [start, end] row numbers, inclusive, each with its return minus the benchmark's."""
    held = frame["held"].to_numpy(dtype=bool)
    ret, bench = frame["ret"].to_numpy(dtype=float), frame["bench"].to_numpy(dtype=float)
    out = []
    i = 0
    while i < len(held):
        if not held[i]:
            i += 1
            continue
        end = i
        while end + 1 < len(held) and held[end + 1] and end + 1 - i < BLOCK_DAYS:
            end += 1
        excess = float(np.prod(1 + ret[i:end + 1]) - np.prod(1 + bench[i:end + 1]))
        out.append({"start": i, "end": end, "excess": excess, "fresh": i == 0 or not held[i - 1]})
        i = end + 1
    return out


def _entry_pattern(frame: pd.DataFrame, spans: list[dict], base: float) -> dict | None:
    spy = frame["spy"].to_numpy(dtype=float)
    days = [str(d.date()) for d in frame.index]
    regimes = regime_tags(pd.Series(np.cumprod(1 + spy), index=frame.index))
    groups: dict[tuple[str, str], list[dict]] = {}
    for t in spans:
        before = t["start"] - 1
        if before < 0:
            continue
        label = regimes.get(days[before], {}).get("label", "")
        if "unknown" not in label:
            groups.setdefault(("gate", label.replace(" · ", " with ")), []).append(t)
        if t["fresh"] and abs(spy[before]) >= BIG_MOVE:  # a monthly block isn't a decision to enter
            groups.setdefault(("entry", "the day after a big market move"), []).append(t)
    best = None
    for (implicates, tag), members in groups.items():
        lost = sum(t["excess"] < 0 for t in members)
        lift = (lost / len(members)) / base if base else 0.0
        if len(members) < MIN_TAGGED or lift < MIN_LIFT or tail_probability(lost, len(members), base) >= ALPHA:
            continue
        if best is None or lift > best["lift"]:
            best = {"implicates": implicates, "tag": tag, "lift": lift, "n": len(members), "lost": lost,
                    "text": f"{lost} of {len(members)} holding periods that began in {tag} lost to the benchmark, "
                            f"against {base:.0%} of all periods."}
    return best


def _exit_pattern(losers: list[dict]) -> dict | None:
    worst = sorted(t["excess"] for t in losers)
    top = max(1, len(worst) // 5)
    share = sum(worst[:top]) / sum(worst)
    if share < 0.5:
        return None
    return {"implicates": "exit", "tag": "", "text": f"The worst {top} of {len(worst)} losing trades made up "
                                                     f"{share:.0%} of the damage, and the idea has no exit rule."}


def _sizing_pattern(losers: list[dict], hold: list[str], closes: pd.DataFrame) -> dict | None:
    names = [t for t in hold if t in closes.columns]
    if len(names) < 2:
        return None
    lost = dict.fromkeys(names, 0.0)
    for t in losers:
        window = closes.iloc[max(t["start"] - 1, 0):t["end"] + 1]
        for name in names:
            move = window[name].dropna()
            if len(move) > 1:
                lost[name] += min(float(move.iloc[-1] / move.iloc[0] - 1), 0.0)
    total = sum(lost.values())
    if total >= 0:
        return None
    name = min(lost, key=lost.get)
    share = lost[name] / total
    if share < 0.5:
        return None
    sector = sector_for(name)
    label = name if sector == "Other" else f"{name} ({sector})"
    return {"implicates": "sizing", "tag": name,
            "text": f"{label} made up {share:.0%} of the losses across the idea's {len(names)} names."}


def autopsy(frame: pd.DataFrame, *, hold: list[str], closes: pd.DataFrame, has_exits: bool, variation: int) -> dict:
    spans = trades(frame)
    losers = [t for t in spans if t["excess"] < 0]
    summary = {"trades": len(spans), "losers": len(losers), "pattern": None, "suggestion": None,
               "suggestions_left": max(MAX_SUGGESTIONS - variation, 0)}
    if len(spans) < MIN_TRADES or len(losers) < MIN_LOSERS:
        return {**summary, "status": "too_few"}
    base = len(losers) / len(spans)
    found = (_entry_pattern(frame, spans, base) or (None if has_exits else _exit_pattern(losers))
             or _sizing_pattern(losers, hold, closes))
    if found is None:
        return {**summary, "status": "ok"}
    suggestion = _SUGGEST[found["implicates"]].format(tag=found["tag"]) if variation <= MAX_SUGGESTIONS else None
    return {**summary, "status": "ok", "suggestion": suggestion,
            "pattern": {"implicates": found["implicates"], "text": found["text"]}}
