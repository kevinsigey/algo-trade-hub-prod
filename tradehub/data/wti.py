"""WTI crude futures (front month, continuous CL=F) daily closes as point-in-time observations.

The continuous series is deliberate for v1: the oil engine consumes a 5-close CHANGE as its
feature, and Yahoo's CL=F is the same tape whose close matched Kalshi's KXWTI settlement to the
cent on 2026-10-30 (104.12, verified in the phase-3 weather/energy audit). The known cost is the
monthly contract roll: one close a month carries a roll step the same-contract RBOB loader goes
to lengths to avoid. The fit's windows are mostly roll-free and the step is bounded (adjacent
WTI months rarely differ by more than a dollar); a contract-level loader is the v2 fix if the
graded record says the feature is the problem. Bars publish at the RBOB convention, 18:00 ET,
so a freeze before the 14:30 ET settlement never sees that day's bar.
"""

from __future__ import annotations

import inspect
import time as monotonic_time
from datetime import date, datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation

WTI_SYMBOL = "CL=F"
_SETTLE_TZ = ZoneInfo("America/New_York")


def _default_history(start: date | None = None, end: date | None = None) -> Any:
    import yfinance as yf

    kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False}
    if start is None and end is None:
        kwargs["period"] = "2y"
    else:
        if start is not None:
            kwargs["start"] = start.isoformat()
        if end is not None:
            kwargs["end"] = end.isoformat()
    return yf.Ticker(WTI_SYMBOL).history(**kwargs)


def _call_history(history_fn: Callable[..., Any], start: date | None, end: date | None) -> Any:
    try:
        parameters = inspect.signature(history_fn).parameters.values()
    except (TypeError, ValueError):
        return history_fn()
    names = {parameter.name for parameter in parameters}
    accepts_kwargs = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters)
    if accepts_kwargs or {"start", "end"}.issubset(names):
        return history_fn(start=start, end=end)
    return history_fn()


def wti_closes(
    start: date | None = None,
    end: date | None = None,
    *,
    history_fn: Callable[..., Any] = _default_history,
    deadline: float | None = None,
) -> list[Observation]:
    if deadline is not None and monotonic_time.monotonic() >= deadline:
        raise TimeoutError("WTI scan deadline exceeded")
    frame = _call_history(history_fn, start, end)
    if deadline is not None and monotonic_time.monotonic() >= deadline:
        raise TimeoutError("WTI scan deadline exceeded")
    if frame is None or "Close" not in frame:
        return []
    out = []
    for stamp, close in frame["Close"].items():
        if close is None or close != close:  # NaN check without requiring pandas.
            continue
        day = stamp.date()
        if start is not None and day < start:
            continue
        if end is not None and day >= end:
            continue
        published = datetime.combine(day, time(18, 0), _SETTLE_TZ).astimezone(timezone.utc)
        out.append(Observation(f"WTI:CL=F:{day.isoformat()}", float(close), published))
    return sorted(out, key=lambda observation: observation.published_at)
