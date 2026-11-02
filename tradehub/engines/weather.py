"""Weather engine (pure): P(Kalshi daily-high market resolves YES) from a model-blend forecast.

The settled high ~ Normal(mean(model highs) + bias, sigma), with bias/sigma fit
walk-forward on past (forecast, actual) pairs. Model disagreement is already
represented by the fitted error term and is not added again here.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from tradehub.backtest.pit import Observation
from tradehub.markets import KalshiMarket, event_date, prob_in_interval, yes_interval

WEATHER_ENGINE_VERSION = "weather-v1"
TEMP_RESOLUTION = 1.0
MIN_SIGMA = 1.0
MIN_ERROR_PAIRS = 20


@dataclass(frozen=True)
class ErrorModel:
    bias: float
    sigma: float


DEFAULT_ERROR = ErrorModel(bias=0.0, sigma=2.5)
_LEAD_PATTERN = re.compile(r":lead(\d+)$")


def forecast_lead_days(observation: Observation) -> int:
    """Return a comparable lead rank; live and unlabelled values rank first."""
    match = _LEAD_PATTERN.search(observation.name)
    return int(match.group(1)) if match else 0


def select_forecast_observations(
    observations: Iterable[Observation],
    as_of: datetime,
) -> list[Observation]:
    """Select every model value from the smallest lead published by ``as_of``."""
    known = [observation for observation in observations if observation.published_at <= as_of]
    if not known:
        return []
    lead = min(forecast_lead_days(observation) for observation in known)
    return [observation for observation in known if forecast_lead_days(observation) == lead]


def fit_error_model(
    pairs: list[tuple[float, float]],
    min_pairs: int = MIN_ERROR_PAIRS,
    fallback: ErrorModel = DEFAULT_ERROR,
    weights: list[float] | None = None,
) -> ErrorModel:
    """Bias/sigma from (forecast, actual) pairs. `weights` (one per pair,
    oldest first) recency-weights the fit -- ens-v2.1 passes an exponential
    decay so a drifting station bias is tracked by its recent errors; None
    keeps the original equal-weight fit byte-identical."""
    if len(pairs) < min_pairs:
        return fallback
    errors = [actual - forecast for forecast, actual in pairs]
    if weights is None:
        bias = statistics.fmean(errors)
        sigma = statistics.stdev(errors)
    else:
        total = sum(weights)
        bias = sum(w * e for w, e in zip(weights, errors, strict=True)) / total
        denom = total - sum(w * w for w in weights) / total
        var = (sum(w * (e - bias) ** 2 for w, e in zip(weights, errors, strict=True)) / denom
               if denom > 0 else 0.0)
        sigma = var ** 0.5
    return ErrorModel(bias=bias, sigma=max(MIN_SIGMA, sigma))


MIN_CALIB_PAIRS = 40


def fit_probability_calibration(pairs: list[tuple[float, float]],
                                min_pairs: int = MIN_CALIB_PAIRS) -> tuple[float, float] | None:
    """Platt scaling on logit(p): outcome ~ sigmoid(a + b * logit(p)), fit by
    Newton iterations on the log-loss. Returns (a, b), or None below the pair
    floor or when the fitted slope is not positive (a non-positive slope says
    the raw probabilities carry no usable signal to rescale)."""
    import math
    usable = [(p, y) for p, y in pairs if 0.0 < p < 1.0]
    if len(usable) < min_pairs:
        return None
    xs = [math.log(p / (1.0 - p)) for p, _ in usable]
    ys = [y for _, y in usable]
    a, b = 0.0, 1.0
    for _ in range(50):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys, strict=True):
            z = a + b * x
            s = 1.0 / (1.0 + math.exp(-z)) if z > -500 else 0.0
            w = max(s * (1.0 - s), 1e-9)
            r = s - y
            ga += r
            gb += r * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            return None
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a -= da
        b -= db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    if b <= 0:
        return None
    return a, b


def apply_probability_calibration(params: tuple[float, float], p: float) -> float:
    import math
    a, b = params
    p = min(1.0 - 1e-6, max(1e-6, p))
    z = a + b * math.log(p / (1.0 - p))
    return 1.0 / (1.0 + math.exp(-z)) if z > -500 else 0.0


def walk_forward_error_model(
    actuals: Iterable[Observation],
    forecasts: Mapping[date, Sequence[Observation]],
    as_of: datetime,
    *,
    decision_time_for: Callable[[date], datetime] | None = None,
    fallback: ErrorModel = DEFAULT_ERROR,
    min_pairs: int = MIN_ERROR_PAIRS,
) -> ErrorModel:
    """Fit forecast errors from actuals and forecasts known at ``as_of``.

    With ``decision_time_for``, each past day's forecast is the one its own
    decision would have used (published by that day's decision time, and by
    ``as_of``), so the fitted errors match the lead the model actually trades at.
    """
    pairs: list[tuple[float, float]] = []
    for actual in actuals:
        if actual.published_at > as_of:
            continue
        day = event_date(actual.name)
        cutoff = as_of if decision_time_for is None else min(as_of, decision_time_for(day))
        known = select_forecast_observations(forecasts.get(day, ()), cutoff)
        if known:
            pairs.append((statistics.fmean(observation.value for observation in known), actual.value))
    return fit_error_model(pairs, min_pairs=min_pairs, fallback=fallback)


def weather_prob(market: KalshiMarket, highs: list[float], error: ErrorModel) -> float:
    if not highs:
        raise ValueError(f"no forecast highs for {market.ticker}")
    mu = statistics.fmean(highs) + error.bias
    # The fitted error sigma is the complete uncertainty term. Adding the
    # current model blend spread here would count model disagreement twice.
    sigma = error.sigma
    return prob_in_interval(mu, sigma, yes_interval(market, TEMP_RESOLUTION))
