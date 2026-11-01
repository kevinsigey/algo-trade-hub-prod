"""Diagnostics pack (phase-2 §6.1): measurement only, never a gate.

Two families of checks, both computed from what a run already produced:

* **Stationarity screening** over the feature inputs a model consumed (ADF,
  constant/no-trend, MacKinnon critical values), plus the share of exact zeros.
  The failure this exists to catch is the ghost_gap class: a feature that silently
  reads 0 for most of its history, or one whose character changed under the model.
  It appears in the run output, per feature, per run -- not in a post-mortem.
* **Residual diagnostics** on the nowcast's standardised residuals (Ljung-Box for
  leftover autocorrelation, ARCH-LM for volatility clustering). Flags, not gates:
  a flag is a reason to look, never a reason a run is refused or a model stopped.

The tests are the textbook formulas on numpy/scipy (both runtime deps);
statsmodels lives in a research extra and is not importable where the engines
run, so nothing here imports it. A series too short to judge returns
{"status": "too_short"} -- an honest absence, not a pass.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

# MacKinnon 5% critical values, ADF with constant and no trend, by sample size
# (response-surface table; the asymptotic value is -2.86).
_ADF_CRIT_5 = ((25, -3.00), (50, -2.93), (100, -2.89), (250, -2.88), (500, -2.87))
_ASYMPTOTIC_5 = -2.86

MIN_ADF_N = 30
ZERO_SHARE_FLAG = 0.9


def _crit_5(n: int) -> float:
    for size, crit in _ADF_CRIT_5:
        if n <= size:
            return crit
    return _ASYMPTOTIC_5


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(coefficients, standard errors) for a plain OLS fit."""
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = max(len(y) - x.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(x.T @ x)
    return beta, np.sqrt(np.diag(cov))


def adf_test(values: list[float] | np.ndarray) -> dict:
    """Augmented Dickey-Fuller (constant, no trend). Verdict at the 5% level."""
    y = np.asarray(values, dtype=float)
    y = y[~np.isnan(y)]
    n = len(y)
    if n < MIN_ADF_N:
        return {"n": int(n), "status": "too_short"}
    lag = max(0, min(10, int(round(12 * (n / 100.0) ** 0.25))))
    dy = np.diff(y)
    rows, target = [], []
    for t in range(lag, len(dy)):
        rows.append([1.0, y[t]] + [dy[t - k] for k in range(1, lag + 1)])
        target.append(dy[t])
    x, target_arr = np.array(rows), np.array(target)
    try:
        beta, se = _ols(x, target_arr)
    except np.linalg.LinAlgError:
        # A (near-)constant series -- the zero-filled feature is exactly this --
        # makes the design singular. That is a finding, not a crash.
        return {"n": int(n), "lag": lag, "status": "degenerate"}
    stat = float(beta[1] / se[1]) if se[1] > 0 else 0.0
    crit = _crit_5(n)
    return {"n": int(n), "lag": lag, "stat": round(stat, 3), "crit_5pct": crit,
            "verdict": "stationary" if stat < crit else "non_stationary"}


def ljung_box(residuals: list[float] | np.ndarray, lags: int = 10) -> dict:
    """Q test for residual autocorrelation up to `lags`. Flag at p < 0.05."""
    e = np.asarray(residuals, dtype=float)
    e = e[~np.isnan(e)]
    n = len(e)
    if n <= lags + 5:
        return {"n": int(n), "status": "too_short"}
    e = e - e.mean()
    denom = float(e @ e)
    if denom == 0:
        return {"n": int(n), "status": "degenerate"}
    q = 0.0
    for k in range(1, lags + 1):
        rho = float(e[k:] @ e[:-k]) / denom
        q += rho * rho / (n - k)
    q *= n * (n + 2)
    p = float(stats.chi2.sf(q, lags))
    return {"n": int(n), "lags": lags, "q": round(q, 2), "p": round(p, 4), "flag": bool(p < 0.05)}


def arch_lm(residuals: list[float] | np.ndarray, lags: int = 5) -> dict:
    """Engle's ARCH-LM: regress squared residuals on their lags; LM = n*R^2."""
    e = np.asarray(residuals, dtype=float)
    e = e[~np.isnan(e)]
    n = len(e)
    if n <= lags + 10:
        return {"n": int(n), "status": "too_short"}
    e2 = e * e
    rows, target = [], []
    for t in range(lags, n):
        rows.append([1.0] + [e2[t - k] for k in range(1, lags + 1)])
        target.append(e2[t])
    x, target_arr = np.array(rows), np.array(target)
    try:
        beta, _ = _ols(x, target_arr)
    except np.linalg.LinAlgError:
        return {"n": int(n), "status": "degenerate"}
    fitted = x @ beta
    ss_res = float(((target_arr - fitted) ** 2).sum())
    ss_tot = float(((target_arr - target_arr.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    lm = len(target_arr) * max(r2, 0.0)
    p = float(stats.chi2.sf(lm, lags))
    return {"n": int(n), "lags": lags, "lm": round(float(lm), 2), "p": round(p, 4), "flag": bool(p < 0.05)}


def feature_diagnostics(series_by_feature: dict[str, list[float]]) -> list[dict]:
    """Per-feature screening, in the caller's feature order."""
    out = []
    for name, values in series_by_feature.items():
        arr = np.asarray(values, dtype=float)
        zero_share = float((arr == 0).mean()) if len(arr) else 0.0
        adf = adf_test(arr)
        flags = []
        if adf.get("verdict") == "non_stationary":
            flags.append("non_stationary")
        if zero_share >= ZERO_SHARE_FLAG:
            flags.append("mostly_zero")
        out.append({"feature": name, "n": int(len(arr)), "zero_share": round(zero_share, 3),
                    "adf": adf, "flags": flags})
    return out


def residual_diagnostics(residuals: list[float]) -> dict:
    """Both residual checks with their flags lifted to the top level."""
    lb, arch = ljung_box(residuals), arch_lm(residuals)
    flags = []
    if lb.get("flag"):
        flags.append("residual_autocorrelation")
    if arch.get("flag"):
        flags.append("residual_arch")
    return {"n": len(residuals), "ljung_box": lb, "arch_lm": arch, "flags": flags}
