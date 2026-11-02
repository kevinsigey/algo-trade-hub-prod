"""Unemployment-rate level nowcast (KXU3): the next U3 print as a Normal level.

U3 moves slowly and its monthly changes are persistent, so the model is the
walk-forward OLS of the next change on the last change,

    u3(t) - u3(t-1)  ~  alpha + beta * (u3(t-1) - u3(t-2)),

fit on ALFRED *first prints* (settlement grades the first print of the rate),
with the drift-only reduction until the pairs earn the regression. This is
the market-graded level successor to `unrate_direction`'s climatology-graded
up/down call: same first-print history, priced against KXU3 strikes instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

UNRATE_SERIES = "KXU3"
UNRATE_RESOLUTION = 0.1  # BLS publishes U3 rounded to a tenth of a point
MIN_UNRATE_SIGMA = 0.05
MIN_PAIRS = 30


@dataclass(frozen=True)
class UnrateModel:
    alpha: float
    beta: float
    sigma: float
    n_train: int


def unrate_pairs(levels: list[float]) -> list[tuple[float, float]]:
    """Point-in-time (last change, next change) pairs from ascending first prints."""
    changes = [b - a for a, b in zip(levels, levels[1:])]
    return list(zip(changes, changes[1:]))


def fit_unrate_model(pairs: list[tuple[float, float]], min_points: int = MIN_PAIRS) -> UnrateModel | None:
    if len(pairs) < min_points:
        return None
    n = len(pairs)
    mean_x = sum(x for x, _ in pairs) / n
    mean_y = sum(y for _, y in pairs) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in pairs)
    if sxx <= 0:
        alpha, beta = mean_y, 0.0
    else:
        beta = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
        alpha = mean_y - beta * mean_x
    resid = [y - (alpha + beta * x) for x, y in pairs]
    dof = max(n - 2, 1)
    sigma = max(math.sqrt(sum(r * r for r in resid) / dof), MIN_UNRATE_SIGMA)
    return UnrateModel(alpha=alpha, beta=beta, sigma=sigma, n_train=n)


def unrate_mu_sigma(levels: list[float], model: UnrateModel) -> tuple[float, float]:
    last_change = levels[-1] - levels[-2]
    return levels[-1] + model.alpha + model.beta * last_change, model.sigma


def unrate_prob(market: KalshiMarket, mu: float, sigma: float) -> float:
    """P(YES) for a KXU3 strike under the Normal(mu, sigma) print."""
    return prob_in_interval(mu, sigma, yes_interval(market, UNRATE_RESOLUTION))
