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
BRENT_SYMBOL = "BZ=F"
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


def _default_brent_history(start: date | None = None, end: date | None = None) -> Any:
    import yfinance as yf

    kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False}
    if start is None and end is None:
        kwargs["period"] = "2y"
    else:
        if start is not None:
            kwargs["start"] = start.isoformat()
        if end is not None:
            kwargs["end"] = end.isoformat()
    return yf.Ticker(BRENT_SYMBOL).history(**kwargs)


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


def _default_intraday_history() -> Any:
    import yfinance as yf

    return yf.Ticker(WTI_SYMBOL).history(period="1d", interval="1m", auto_adjust=False)


def wti_last_price(
    *,
    history_fn: Callable[[], Any] = _default_intraday_history,
) -> Observation | None:
    """The latest CL=F 1-minute close as an Observation stamped with its bar time.

    The hourly WTI model's live anchor: Kalshi's hourly markets settle on the Pyth WTI
    1-minute candle close at the top of the hour, and CL=F is the tape whose close the
    daily engine already validated against Kalshi settlements. The bar timestamp is the
    observation time, so the forecaster can refuse a stale print instead of pricing an
    hour-old price as if it were live.
    """
    frame = history_fn()
    if frame is None or "Close" not in frame:
        return None
    for stamp, close in reversed(list(frame["Close"].items())):
        if close is None or close != close:  # NaN check without requiring pandas.
            continue
        stamp = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)
        return Observation("WTI:CL=F:last", float(close), stamp.astimezone(timezone.utc))
    return None


def wti_minute_tape(
    *,
    history_fn: Callable[[], Any] = _default_intraday_history,
) -> list[tuple[datetime, float]]:
    """The day's CL=F 1-minute closes, oldest first, as (bar time, close).

    The oil ITM line's stability check reads this: a strike only counts as
    clear if the tape stayed on one side of it for the trailing minutes.
    Fail-soft: a missing or malformed frame is an empty tape, and callers
    treat that as "no pick", never as a clear strike."""
    try:
        frame = history_fn()
        if frame is None or "Close" not in frame:
            return []
        out: list[tuple[datetime, float]] = []
        for stamp, close in frame["Close"].items():
            if close is None or close != close:  # NaN check without pandas.
                continue
            stamp = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)
            out.append((stamp.astimezone(timezone.utc), float(close)))
        out.sort(key=lambda t: t[0])
        return out
    except Exception:  # noqa: BLE001 -- a tape hiccup is "no pick", not an error
        return []


def wti_closes(
    start: date | None = None,
    end: date | None = None,
    *,
    history_fn: Callable[..., Any] = _default_history,
    deadline: float | None = None,
    label: str = "WTI:CL=F",
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
        out.append(Observation(f"{label}:{day.isoformat()}", float(close), published))
    return sorted(out, key=lambda observation: observation.published_at)


def brent_closes(start: date | None = None, end: date | None = None) -> list[Observation]:
    """Brent front-month (BZ=F) daily closes, the KXBRENTD sibling's input --
    same loader, same publication convention as WTI."""
    return wti_closes(start, end, history_fn=_default_brent_history, label="BRENT:BZ=F")
