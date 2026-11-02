"""Oil engine (pure): P(KXWTI settlement in a contract's range) from the last settlement
plus a CL=F pass-through drift, fitted walk-forward. The gas engine's shape, pointed at crude.

The market settles on the day's ICE WTI settlement (~14:30 ET), and the journal freezes in the
2h before the close with yesterday's settlement as the level and the CL=F 5-close change as the
drift feature. Settlements skip weekends and holidays, so training changes are normalized per
day across their gap and the serve-time horizon scales the same way (mu and sigma both grow
with the gap, exactly as the gas engine scales with its horizon).

ponytail: this is a measurement, not an edge hunt -- the same posture as gas. The market is
liquid and was cent-accurate against the free tape on the audit's check; the journal records
whether a free-data model can stay anywhere near it, with a persistence baseline and a w25
market-shrunk row beside it from day one (the two things gas lacked at its start).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

OIL_ENGINE_VERSION = "wti-v1"
OIL_SERIES = "KXWTI"
OIL_RESOLUTION = 0.01  # KXWTI settles to the cent (104.12 on 2026-10-30)
MIN_OIL_SIGMA = 0.25    # dollars; a floor so a quiet fitted week never prices a strike at 0/1
CL_WINDOW = 5
# The market closes at the 14:30 ET settlement on the reference day (verified live:
# KXWTI-26NOV0214 close_time 2026-11-02T19:30:00Z); freeze in the 2h before it.
OIL_DECISION_LEAD = timedelta(hours=2)
_EASTERN = ZoneInfo("America/New_York")
_SETTLEMENT = time(14, 30)


@dataclass(frozen=True)
class OilModel:
    alpha: float
    beta: float
    sigma: float


DEFAULT_OIL = OilModel(alpha=0.0, beta=0.0, sigma=1.5)


def market_close(day: date) -> datetime:
    """When the market that settles on `day` stops trading: the 14:30 ET settlement."""
    return datetime.combine(day, _SETTLEMENT, _EASTERN)


def decision_time(day: date, lead: timedelta = OIL_DECISION_LEAD) -> datetime:
    """When the model decides the market that settles on `day`: its close minus `lead`.

    The CL=F feature is read here in training and at inference alike, so both see the same
    last published close (the previous session's; today's bar publishes at 18:00 ET)."""
    return market_close(day) - lead


def wti_change(
    closes: list[Observation],
    as_of: datetime,
    window: int = CL_WINDOW,
) -> float | None:
    """The CL=F change over the last `window` closes published by `as_of`."""
    known = sorted((o for o in closes if o.published_at <= as_of), key=lambda o: o.published_at)
    if len(known) < window + 1:
        return None
    sample = known[-(window + 1):]
    return sample[-1].value - sample[0].value


def _ordered(settlements: list[Observation]) -> list[Observation]:
    return sorted(settlements, key=lambda o: event_date(o.name))


def settlement_daily_changes(settlements: list[Observation]) -> list[float]:
    """Per-day settlement changes: each consecutive pair's change divided by its day gap,
    so a Friday->Monday step counts as three days of movement, not one."""
    ordered = _ordered(settlements)
    out = []
    for prev, cur in zip(ordered, ordered[1:]):
        gap = (event_date(cur.name) - event_date(prev.name)).days
        if gap >= 1:
            out.append((cur.value - prev.value) / gap)
    return out


def oil_training_pairs(
    settlements: list[Observation],
    closes: list[Observation],
    window: int = CL_WINDOW,
    *,
    lead: timedelta = OIL_DECISION_LEAD,
) -> list[tuple[float, float, datetime]]:
    """(CL=F change at the decision time, per-day settlement change, publish time) triples."""
    ordered = _ordered(settlements)
    pairs = []
    for prev, cur in zip(ordered, ordered[1:]):
        gap = (event_date(cur.name) - event_date(prev.name)).days
        if gap < 1:
            continue
        x = wti_change(closes, decision_time(event_date(cur.name), lead), window)
        if x is None:
            continue
        pairs.append((x, (cur.value - prev.value) / gap, cur.published_at))
    return pairs


def fit_oil_model(
    pairs: list[tuple[float, float]],
    min_points: int = 30,
    *,
    settlements: list[Observation] | None = None,
) -> OilModel:
    if len(pairs) < min_points:
        changes = settlement_daily_changes(settlements or [])
        if len(changes) < min_points:
            return DEFAULT_OIL
        return OilModel(
            alpha=statistics.fmean(changes),
            beta=0.0,
            sigma=max(MIN_OIL_SIGMA, statistics.stdev(changes)),
        )
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in pairs) / sxx if sxx > 0 else 0.0
    alpha = my - beta * mx
    residuals = [y - (alpha + beta * x) for x, y in pairs]
    sigma = math.sqrt(sum(r * r for r in residuals) / (len(pairs) - 2))
    return OilModel(alpha=alpha, beta=beta, sigma=max(MIN_OIL_SIGMA, sigma))


def oil_prob(market: KalshiMarket, last_value: float, horizon_days: int, cl_x: float | None,
             model: OilModel) -> float:
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be >= 1, got {horizon_days}")
    x = 0.0 if cl_x is None else cl_x
    mu = last_value + horizon_days * (model.alpha + model.beta * x)
    sigma = model.sigma * math.sqrt(horizon_days)
    return prob_in_interval(mu, sigma, yes_interval(market, OIL_RESOLUTION))
