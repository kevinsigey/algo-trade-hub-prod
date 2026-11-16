"""The tracker's grading math (Thesis v6, spec Sections 3 and 5).

Pure functions over daily bars -- no I/O, no store. The conventions
here are the frozen ones from the design (docs/superpowers/specs/
2026-11-16-thesis-tracker-design.md):

- The reaction session is the first session whose close reflects the
  print: the print's own session when it lands before the 16:00 ET
  close on a trading day, otherwise the next session.
- `ret_1d` is the reaction return off the pre-print close (the last
  close before the reaction session); `ret_3d`/`ret_5d` are cumulative
  over the same base, counting the reaction session as day 1. SPY is
  measured over the identical dates; excess is the difference.
- An outcome exists only when EVERY horizon is computable. A card
  whose +5 session has not happened yet -- or whose bars have a hole
  -- grades later, never partially.
- The two signals and the classification grade SEPARATELY, each by
  sign agreement with the reaction return: positive/inflow/improved
  call for an up move, negative/outflow/deteriorated for a down move.
  A flat whisper or an intact classification calls for no move and
  hits inside FLAT_BAND. A mixed money flow makes no directional call
  and is never graded (its hit stays None), as is any missing signal.

Claim progress is computed against the falsifiers' frozen forms:
Claim A separates over its first 40 prints (pass at >= 60%) with a
rolling-60 kill below 50%; Claim C judges the net of its first five
play-kind-(a) fires (must be positive after costs).
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLOSE = time(16, 0)
FLAT_BAND = 0.01
HORIZONS = (1, 3, 5)

_UP_CALLS = {"positive", "inflow", "improved"}
_DOWN_CALLS = {"negative", "outflow", "deteriorated"}
_FLAT_CALLS = {"flat", "intact"}


def _instant(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sign_hit(call, reaction_ret: float) -> bool | None:
    """One signal's grade: sign agreement with the reaction return."""
    if call is None:
        return None
    if call in _UP_CALLS:
        return reaction_ret > 0
    if call in _DOWN_CALLS:
        return reaction_ret < 0
    if call in _FLAT_CALLS:
        return abs(reaction_ret) <= FLAT_BAND
    return None  # mixed money flow, or anything unrecognized: no call


def reaction_date(dates: list[date], print_at: datetime) -> date | None:
    """The first session whose close reflects the print, or None when
    the bars do not reach it yet."""
    et = print_at.astimezone(ET)
    day = et.date()
    if et.time() < CLOSE and day in dates:
        return day
    for d in dates:
        if d > day:
            return d
    return None


def grade_outcome(card: dict, ticker_bars, spy_bars) -> dict | None:
    """One card's outcome row (minus card_id/graded_at), or None when
    any horizon is not yet computable -- no partial outcomes, ever."""
    ticker = {d: float(c) for d, c in ticker_bars}
    spy = {d: float(c) for d, c in spy_bars}
    dates = sorted(ticker)
    if not dates:
        return None
    reaction = reaction_date(dates, _instant(card["print_at"]))
    if reaction is None:
        return None
    idx = dates.index(reaction)
    if idx == 0:
        return None  # no pre-print close to measure from
    base = dates[idx - 1]
    if base not in spy:
        return None
    out: dict = {"reaction_close": ticker[reaction]}
    for n in HORIZONS:
        if idx + n - 1 >= len(dates):
            return None
        target = dates[idx + n - 1]
        if target not in spy:
            return None
        ret = ticker[target] / ticker[base] - 1.0
        spy_ret = spy[target] / spy[base] - 1.0
        out[f"ret_{n}d"] = ret
        out[f"spy_{n}d"] = spy_ret
        out[f"excess_{n}d"] = ret - spy_ret
    reaction_ret = out["ret_1d"]
    out["whisper_hit"] = _sign_hit(card.get("whisper_sign"), reaction_ret)
    out["money_flow_hit"] = _sign_hit(card.get("money_flow_direction"),
                                      reaction_ret)
    out["classification_hit"] = _sign_hit(card.get("classification"),
                                          reaction_ret)
    return out


def claim_a_progress(rows, *, prints: int = 40, rolling: int = 60,
                     min_separation: float = 0.60,
                     kill_below: float = 0.50) -> dict:
    """Claim A over graded classification rows, in print order.

    `rows` carry `classification_hit` (None = the card made no
    classification call; those prints are not graded and do not
    count). The verdict completes the frozen window: at `prints`
    graded, separation over the FIRST `prints` decides pass vs demote
    (fired); once a full rolling window exists, a rolling separation
    below `kill_below` kills, and the kill takes precedence.
    """
    hits = [bool(r["classification_hit"]) for r in rows
            if r.get("classification_hit") is not None]
    graded = len(hits)
    separation = (sum(hits) / graded) if graded else None
    first = hits[:prints]
    first_sep = (sum(first) / len(first)) if len(first) == prints else None
    roll = hits[-rolling:] if graded >= rolling else []
    roll_sep = (sum(roll) / len(roll)) if roll else None
    verdict = None
    if roll_sep is not None and roll_sep < kill_below:
        verdict = "killed"
    elif first_sep is not None:
        verdict = "passed" if first_sep >= min_separation else "fired"
    return {"graded": graded, "hits": sum(hits), "separation": separation,
            "window_separation": first_sep,
            "rolling60_separation": roll_sep,
            "prints_remaining": max(0, prints - graded),
            "verdict": verdict}


def claim_c_progress(fire_nets, *, fires: int = 5) -> dict:
    """Claim C over play-kind-(a) fire nets (after costs), in order.

    The frozen window is the NEXT `fires` fires: their net decides,
    and later fires neither reopen nor rescue the verdict.
    """
    nets = [float(x) for x in fire_nets]
    window = nets[:fires]
    net = sum(window)
    verdict = None
    if len(window) == fires:
        verdict = "passed" if net > 0 else "fired"
    return {"fires": len(nets), "net": net, "verdict": verdict}
