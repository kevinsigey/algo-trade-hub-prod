"""Initial jobless claims nowcast (KXJOBLESSCLAIMS): the next DOL print as a
Normal level, from the print history's own mean reversion.

Claims prints are weekly and near-stationary around a slow-moving level: when
the last print sits above its own 4-week average the next print tends to fall
back, and vice versa. The model is the walk-forward OLS of the next change on
that gap,

    print(t) - print(t-1)  ~  alpha + beta * (avg4(t-1) - print(t-1)),

fit on point-in-time pairs (every pair's features predate its target), with a
persistence-with-drift fallback until the pairs earn the regression. History
is ALFRED *first prints* (the settlement grades the initial release, not the
revision), assembled by the forecaster from weekly vintages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

CLAIMS_SERIES = "KXJOBLESSCLAIMS"
CLAIMS_RESOLUTION = 1.0  # prints are whole persons; strikes step by 1,000
MIN_CLAIMS_SIGMA = 5000.0  # weekly changes run ~10-15k; a fitted sigma below this is a stub artifact
MIN_PAIRS = 30


@dataclass(frozen=True)
class ClaimsModel:
    alpha: float        # fitted mean weekly change at zero gap
    beta: float         # mean-reversion slope on the (avg4 - last) gap
    sigma: float        # residual stdev of the weekly change
    n_train: int


def claims_pairs(prints: list[float]) -> list[tuple[float, float]]:
    """Point-in-time (gap, next change) pairs from an ascending print history."""
    out = []
    for i in range(4, len(prints)):
        last, avg4 = prints[i - 1], sum(prints[i - 4:i]) / 4.0
        out.append((avg4 - last, prints[i] - last))
    return out


def fit_claims_model(pairs: list[tuple[float, float]], min_points: int = MIN_PAIRS) -> ClaimsModel | None:
    """OLS of the next change on the mean-reversion gap; None below min_points."""
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
    sigma = max(math.sqrt(sum(r * r for r in resid) / dof), MIN_CLAIMS_SIGMA)
    return ClaimsModel(alpha=alpha, beta=beta, sigma=sigma, n_train=n)


def claims_mu_sigma(prints: list[float], model: ClaimsModel) -> tuple[float, float]:
    last, avg4 = prints[-1], sum(prints[-4:]) / 4.0
    return last + model.alpha + model.beta * (avg4 - last), model.sigma


def claims_prob(market: KalshiMarket, mu: float, sigma: float) -> float:
    """P(YES) for a KXJOBLESSCLAIMS strike under the Normal(mu, sigma) print."""
    return prob_in_interval(mu, sigma, yes_interval(market, CLAIMS_RESOLUTION))
