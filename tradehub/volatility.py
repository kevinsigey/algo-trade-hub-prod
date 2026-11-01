"""Volatility layer (phase-2 §6.2) -- ships DARK.

Equity/options side only. Three candidate forecasters of next-day volatility,
graded walk-forward against the incumbent static sigma (trailing 60-day realised
vol) on INTERVAL COVERAGE over the same windows:

* GARCH(1,1) and GJR-GARCH(1,1) (the asymmetric form: negative shocks feed
  variance harder), fit by maximum likelihood on returns in percent.
* HAR-RV: tomorrow's realised vol regressed on its daily / weekly / monthly
  averages -- the heterogeneous-autoregression benchmark.

"Dark" is literal: nothing in the hub imports a forecast from here for sizing,
pricing, or display. The layer's only product is the grade
(scripts/volatility_grade.py): per forecaster, empirical coverage of the 80%
and 95% normal intervals vs nominal, the coverage error, and the mean interval
width (a forecaster can win coverage by being uselessly wide, so the width
ratio rides along). A candidate earns a consumer only by beating the incumbent
on coverage in that grade -- the same evidence bar §6 sets for every model
swap. Interval math assumes conditional normality and says so; the grade
measures whether that assumption, plus each forecaster, survives contact.
"""

from __future__ import annotations

import numpy as np
from scipy import optimize, stats

TRADING_DAYS = 252
STATIC_WINDOW = 60
Z = {0.80: float(stats.norm.ppf(0.90)), 0.95: float(stats.norm.ppf(0.975))}


def log_returns(closes: list[float] | np.ndarray) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    c = c[c > 0]
    return np.diff(np.log(c))


def realised_vol(returns: np.ndarray, annualize: bool = True) -> float:
    """The sample stdev of a return window, annualised by default."""
    sd = float(np.std(np.asarray(returns, dtype=float), ddof=1))
    return sd * np.sqrt(TRADING_DAYS) if annualize else sd


def static_sigma(returns: np.ndarray, window: int = STATIC_WINDOW) -> float:
    """The incumbent: trailing-window realised vol, used as tomorrow's sigma."""
    return realised_vol(np.asarray(returns, dtype=float)[-window:])


# --------------------------------------------------------------------------- #
# GARCH family (fit on returns x 100; sigma returned in daily-return units)
# --------------------------------------------------------------------------- #

def _garch_variances(r: np.ndarray, omega: float, alpha: float, beta: float, gamma: float) -> np.ndarray:
    # Plain-Python floats in the recursion: numpy scalar indexing costs several x
    # here, and the likelihood calls this hundreds of times per fit.
    xs = [float(v) for v in r]
    var = [0.0] * len(xs)
    var[0] = max(float(np.var(r)), 1e-8)
    for t in range(1, len(xs)):
        prev = xs[t - 1]
        shock = prev * prev
        coef = alpha + (gamma if prev < 0 else 0.0)
        var[t] = omega + coef * shock + beta * var[t - 1]
    return np.array(var)


def _neg_loglik(params: np.ndarray, r: np.ndarray, gjr: bool) -> float:
    omega, alpha, beta = params[0], params[1], params[2]
    gamma = params[3] if gjr else 0.0
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or alpha + beta + 0.5 * gamma >= 0.999:
        return 1e10
    var = _garch_variances(r, omega, alpha, beta, gamma)
    return float(0.5 * np.sum(np.log(var) + r ** 2 / var))


def garch_forecast(returns: np.ndarray, *, gjr: bool = False) -> dict:
    """Fit GARCH(1,1) (or GJR with gjr=True) and forecast tomorrow's sigma.

    Returns are scaled to percent for the optimiser (the standard numerical
    hygiene); the forecast comes back in daily-return units, unannualised.
    A failed fit answers status='fit_failed' -- never a made-up sigma."""
    r = np.asarray(returns, dtype=float) * 100.0
    if len(r) < 100:
        return {"status": "too_short", "n": int(len(r))}
    x0 = np.array([0.05, 0.08, 0.88] + ([0.06] if gjr else []))
    bounds = [(1e-6, 2.0), (0.0, 0.5), (0.0, 0.999)] + ([(0.0, 0.5)] if gjr else [])
    try:
        fit = optimize.minimize(_neg_loglik, x0, args=(r, gjr), method="L-BFGS-B", bounds=bounds)
        if not fit.success and fit.fun >= 1e9:
            return {"status": "fit_failed", "n": int(len(r))}
        params = fit.x
    except Exception:  # noqa: BLE001 - a failed fit is a status, not an exception path
        return {"status": "fit_failed", "n": int(len(r))}
    omega, alpha, beta = float(params[0]), float(params[1]), float(params[2])
    gamma = float(params[3]) if gjr else 0.0
    var = _garch_variances(r, omega, alpha, beta, gamma)
    last_shock = r[-1] ** 2
    asym = gamma * last_shock if r[-1] < 0 else 0.0
    next_var = omega + (alpha + asym) * last_shock + beta * var[-1]
    return {"status": "ok", "n": int(len(r)), "model": "gjr-garch" if gjr else "garch",
            "omega": round(omega, 5), "alpha": round(alpha, 4), "beta": round(beta, 4),
            "gamma": round(gamma, 4) if gjr else None,
            "sigma_daily": float(np.sqrt(next_var)) / 100.0}


# --------------------------------------------------------------------------- #
# HAR-RV
# --------------------------------------------------------------------------- #

def _har_design(daily_vol: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rows [1, RV_d, RV_w, RV_m] -> next day's RV, from a daily-vol series."""
    rows, target = [], []
    for t in range(22, len(daily_vol) - 1):
        rows.append([1.0, daily_vol[t], daily_vol[t - 4:t + 1].mean(), daily_vol[t - 21:t + 1].mean()])
        target.append(daily_vol[t + 1])
    return np.array(rows), np.array(target)


def har_forecast(returns: np.ndarray) -> dict:
    """HAR-RV on 5-day rolling realised vol (daily granularity from daily returns
    alone -- no intraday tape exists in this hub, so the 'daily RV' input is the
    trailing 5-day realised vol sampled daily; the grade walks the same series,
    so the comparison stays honest)."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 120:
        return {"status": "too_short", "n": int(len(r))}
    daily_vol = np.array([realised_vol(r[i - 4:i + 1], annualize=False)
                          for i in range(4, len(r))])
    daily_vol = np.concatenate([np.full(4, daily_vol[0]), daily_vol])  # first 4 days: no full window yet
    x, y = _har_design(daily_vol)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    last = np.array([1.0, daily_vol[-1], daily_vol[-5:].mean(), daily_vol[-22:].mean()])
    return {"status": "ok", "n": int(len(r)), "model": "har-rv",
            "sigma_daily": float(max(last @ beta, 1e-6))}


# --------------------------------------------------------------------------- #
# The grade
# --------------------------------------------------------------------------- #

FORECASTERS = ("static", "garch", "gjr", "har")


def _sigma_for(name: str, history: np.ndarray) -> float | None:
    """Tomorrow's sigma in DAILY-return units (the grade's common currency)."""
    if name == "static":
        return realised_vol(history[-STATIC_WINDOW:], annualize=False)
    if name == "garch":
        out = garch_forecast(history)
    elif name == "gjr":
        out = garch_forecast(history, gjr=True)
    elif name == "har":
        out = har_forecast(history)
    else:  # pragma: no cover - guarded by FORECASTERS
        return None
    return out.get("sigma_daily") if out.get("status") == "ok" else None


def walk_forward_grade(returns: np.ndarray, *, train: int = 500, step: int = 21) -> dict:
    """Walk-forward coverage grade over the returns AFTER the initial train window.

    Every `step` days, each forecaster is (re)fit on ALL returns so far and its
    sigma is held for the next `step` days -- the cadence a real consumer would
    run at. Per forecaster: empirical coverage of the 80/95% normal intervals,
    total coverage error (|emp-nominal| summed), and mean 95% width relative to
    the static incumbent's. The incumbent is graded on the same days."""
    r = np.asarray(returns, dtype=float)
    out: dict[str, dict] = {}
    if len(r) <= train + step:
        return {"status": "too_short", "n": int(len(r))}
    hits = {name: {lvl: 0 for lvl in Z} for name in FORECASTERS}
    widths = {name: [] for name in FORECASTERS}
    days = {name: 0 for name in FORECASTERS}
    t = train
    while t < len(r):
        horizon = min(step, len(r) - t)
        sigmas = {name: _sigma_for(name, r[:t]) for name in FORECASTERS}
        for name, sigma in sigmas.items():
            if sigma is None or sigma <= 0:
                continue
            for day in range(horizon):
                actual = r[t + day]
                days[name] += 1
                for lvl, z in Z.items():
                    if abs(actual) <= z * sigma:
                        hits[name][lvl] += 1
                widths[name].append(2 * Z[0.95] * sigma)
        t += step
    for name in FORECASTERS:
        if days[name] == 0:
            out[name] = {"status": "no_forecasts"}
            continue
        cov = {lvl: hits[name][lvl] / days[name] for lvl in Z}
        static_width = float(np.mean(widths["static"])) if widths["static"] else None
        out[name] = {
            "days": days[name],
            "coverage_80": round(cov[0.80], 3), "coverage_95": round(cov[0.95], 3),
            "coverage_error": round(abs(cov[0.80] - 0.80) + abs(cov[0.95] - 0.95), 3),
            "width_vs_static": (round(float(np.mean(widths[name])) / static_width, 3)
                                if static_width else None),
        }
    ranked = sorted((n for n in FORECASTERS if "coverage_error" in out[n]),
                    key=lambda n: out[n]["coverage_error"])
    return {"status": "ok", "n": int(len(r)), "train": train, "step": step,
            "forecasters": out, "best_on_coverage": ranked[0] if ranked else None,
            "incumbent": "static"}
