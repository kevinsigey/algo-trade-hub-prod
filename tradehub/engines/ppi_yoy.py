"""PPI year-over-year nowcast (KXUSPPIYOY): the next YoY first print as a Normal.

The YoY rate is a 12-month moving window, so its monthly changes are small
and persistent; the model is the walk-forward OLS of the next change on the
last change,

    yoy(t) - yoy(t-1)  ~  alpha + beta * (yoy(t-1) - yoy(t-2)),

over the YoY series computed point-in-time from ALFRED *first prints* of the
final-demand PPI index (level(t) / level(t-12) - 1, in percent -- the form
BLS headlines and Kalshi settles). No free nowcast exists to wrap (the audit's
note), so this fitted level model is the hub's own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

PPI_SERIES = "KXUSPPIYOY"
PPI_RESOLUTION = 0.1  # YoY prints publish rounded to a tenth of a point
MIN_PPI_SIGMA = 0.05
MIN_PAIRS = 30


@dataclass(frozen=True)
class PpiModel:
    alpha: float
    beta: float
    sigma: float
    n_train: int


def ppi_pairs(yoy: list[float]) -> list[tuple[float, float]]:
    changes = [b - a for a, b in zip(yoy, yoy[1:])]
    return list(zip(changes, changes[1:]))


def fit_ppi_model(pairs: list[tuple[float, float]], min_points: int = MIN_PAIRS) -> PpiModel | None:
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
    sigma = max(math.sqrt(sum(r * r for r in resid) / dof), MIN_PPI_SIGMA)
    return PpiModel(alpha=alpha, beta=beta, sigma=sigma, n_train=n)


def ppi_mu_sigma(yoy: list[float], model: PpiModel) -> tuple[float, float]:
    last_change = yoy[-1] - yoy[-2]
    return yoy[-1] + model.alpha + model.beta * last_change, model.sigma


def ppi_prob(market: KalshiMarket, mu: float, sigma: float) -> float:
    return prob_in_interval(mu, sigma, yes_interval(market, PPI_RESOLUTION))
