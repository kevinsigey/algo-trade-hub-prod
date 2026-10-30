"""The Workshop's first test type: did the idea do what it claims, on years it was not built on, beyond chance?

Pure: daily closes and FRED series in, a verdict dict out. Rules (spec 2026-10-29 §4.4, step 2 plan Task 3):
- a condition is evaluated on data available at the PRIOR close; FRED values are lagged one more day;
- the claim is judged on the unseen span (the last `unseen_fraction` of the common range);
- the shuffle test runs on the unseen span only. A rule with a condition gets random timing (the condition
  mask circularly shifted). A rule with no condition has no timing to shuffle, so it gets a paired sign-flip
  test of its daily returns against the series its claim compares with;
- PASS needs the claim to hold on unseen years AND p < 0.05 / variations.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from tradehub.workshop.spec import CASH, IdeaSpec

DAYS = 252
MIN_UNSEEN_DAYS = 504
MIN_CONDITION_DAYS = 21
CURVE_POINTS = 600
CONTEXT = ("SPY", "QQQ", "IWM")
HEADLINES = {
    "pass": "Did what it claims on the years it hadn't seen.",
    "overfit": "Worked on the years it was built on, not after.",
    "chance": "Held up, but no better than random timing.",
    "fail": "Did not do what it claims.",
    "nodata": "Not enough data to judge.",
}


def tickers_for(spec: IdeaSpec) -> list[str]:
    """Every ticker run_test reads: the rule's, the benchmark, SPY for ballast, and the context row."""
    needed = list(spec.hold) + ([spec.otherwise] if spec.otherwise != CASH else []) + [spec.benchmark]
    if spec.when and spec.when.source == "price":
        needed.append(spec.when.series)
    return list(dict.fromkeys(needed + list(CONTEXT)))


def _measure(values: pd.Series, how: str, lookback: int) -> pd.Series:
    if how == "level":
        return values
    if how == "change":
        return values - values.shift(lookback)
    return (values / values.shift(lookback) - 1) * 100


def condition_mask(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> pd.Series:
    """True on day t when the condition held on information available at the close of t-1."""
    idx = closes.index
    if spec.when is None:
        return pd.Series(True, index=idx)
    c = spec.when
    if c.source == "price":
        values, lag = closes[c.series], 1
    else:
        raw = fred[c.series].sort_index()
        values, lag = raw.reindex(idx.union(raw.index)).ffill().reindex(idx), 2  # +1 day for publication
    measured = _measure(values, c.measure, c.lookback_days)
    hit = measured > c.threshold if c.op == ">" else measured < c.threshold
    return (hit & measured.notna()).shift(lag, fill_value=False).astype(bool)


def _cagr(r: np.ndarray) -> float:
    if len(r) == 0:
        return math.nan
    growth = float(np.prod(1 + r))
    return (growth ** (DAYS / len(r)) - 1) * 100 if growth > 0 else -100.0


def _max_dd(r: np.ndarray) -> float:
    wealth = np.cumprod(1 + r)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1) * 100) if len(r) else math.nan


def _claim(kind: str, r: np.ndarray, b: np.ndarray, s: np.ndarray, mask: np.ndarray) -> tuple[bool, float, str]:
    """(holds, value, label) for one span. `value` is what the shuffle test compares."""
    if kind == "beats_benchmark":
        v = _cagr(r) - _cagr(b)
        return v > 0, v, f"{v:+.1f} pts/yr vs benchmark"
    if kind == "beats_benchmark_when":
        if not mask.any():
            return False, math.nan, "condition never held"
        v = float(np.mean(r[mask] - b[mask]) * DAYS * 100)
        return v > 0, v, f"{v:+.1f} pts/yr vs benchmark while the condition held"
    if kind == "ballast":
        down = s < 0
        if not down.any():
            return False, math.nan, "no SPY down days"
        mine, spy = float(np.mean(r[down])), float(np.mean(s[down]))
        total = float(np.prod(1 + r) - 1)
        holds = (mine > spy and total > 0) or mine > 0
        v = (mine - spy) * 100
        return holds, v, f"{mine * 100:+.2f}% vs SPY {spy * 100:+.2f}% on SPY's down days; {total * 100:+.0f}% overall"
    dd_r, dd_b, gap = _max_dd(r), _max_dd(b), _cagr(r) - _cagr(b)  # smoother_ride
    v = dd_r - dd_b
    return (v > 0 and gap >= -2), v, f"worst drop {dd_r:.0f}% vs {dd_b:.0f}%; return {gap:+.1f} pts/yr"


def verdict_of(holds: bool, p: float, bar: float) -> str:
    return "PASS" if holds and p < bar else "FAIL"


def _clean(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def run_test(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series], *, variations: int, seed: int,
             permutations: int = 1000) -> dict:
    rule = list(dict.fromkeys(list(spec.hold) + ([spec.otherwise] if spec.otherwise != CASH else [])
                              + [spec.benchmark, "SPY"]))
    frame = closes[closes.index >= pd.Timestamp(spec.start)].dropna(subset=rule)
    mask_all = condition_mask(spec, frame, fred)
    rets = frame.pct_change().iloc[1:]
    mask = mask_all.iloc[1:].to_numpy()
    idx = rets.index
    held = rets[spec.hold].mean(axis=1).to_numpy()
    other = rets[spec.otherwise].to_numpy() if spec.otherwise != CASH else np.zeros(len(idx))
    b, s = rets[spec.benchmark].to_numpy(), rets["SPY"].to_numpy()
    cost = spec.cost_bps / 1e4

    def build(m: np.ndarray, h: np.ndarray = held) -> np.ndarray:
        switches = np.concatenate([[False], m[1:] != m[:-1]])
        return np.where(m, h, other) - cost * switches

    r = build(mask)
    n = len(r)
    k = int(n * (1 - spec.unseen_fraction))
    built, unseen = slice(0, k), slice(k, n)
    bar = 0.05 / variations
    base = {"variations": variations, "split_date": str(idx[k].date()) if n > k else None,
            "data_start": str(idx[0].date()) if n else None, "data_end": str(idx[-1].date()) if n else None}

    reason = None
    n_u = n - k
    if n_u < MIN_UNSEEN_DAYS:
        reason = f"only {n_u} unseen trading days; at least {MIN_UNSEEN_DAYS} (2 years) are needed"
    elif spec.when is not None and not (MIN_CONDITION_DAYS <= mask[unseen].sum() <= n_u - MIN_CONDITION_DAYS):
        reason = (f"the condition held on {int(mask[unseen].sum())} of {n_u} unseen days; it needs at least "
                  f"{MIN_CONDITION_DAYS} days on and off")
    if reason:
        return _clean({**base, "verdict": "NOT ENOUGH DATA", "headline": HEADLINES["nodata"], "reason": reason,
                       "claim": None, "shuffle": None, "t_test": None, "periods": None, "context": [], "curve": []})

    kind = spec.claim
    on_b = _claim(kind, r[built], b[built], s[built], mask[built])
    on_u = _claim(kind, r[unseen], b[unseen], s[unseen], mask[unseen])
    actual = on_u[1]

    rng = np.random.default_rng(seed)
    ru, bu, su, mu, hu = r[unseen], b[unseen], s[unseen], mask[unseen], held[unseen]
    ref = su if kind == "ballast" else bu
    perm = np.empty(permutations)
    for i in range(permutations):
        if spec.when is not None:
            shifted = np.roll(mu, int(rng.integers(MIN_CONDITION_DAYS, n_u - MIN_CONDITION_DAYS)))
            sw = np.concatenate([[False], shifted[1:] != shifted[:-1]])
            rp = np.where(shifted, hu, other[unseen]) - cost * sw
            perm[i] = _claim(kind, rp, bu, su, shifted)[1]
        else:
            signs = rng.choice((-1.0, 1.0), size=n_u)
            perm[i] = _claim(kind, ref + signs * (ru - ref), bu, su, mu)[1]
    perm = np.nan_to_num(perm, nan=-np.inf)
    if math.isfinite(actual):
        p = (1 + int(np.sum(perm >= actual))) / (1 + permutations)
        beats = 100 * float(np.sum(perm < actual)) / permutations
    else:
        p, beats = 1.0, 0.0

    verdict = verdict_of(on_u[0], p, bar)
    if verdict == "PASS":
        headline = HEADLINES["pass"]
    elif on_u[0]:
        headline = HEADLINES["chance"]
    elif on_b[0]:
        headline = HEADLINES["overfit"]
    else:
        headline = HEADLINES["fail"]

    t_test = None
    if kind != "ballast":
        days = mu if kind == "beats_benchmark_when" else np.ones(n_u, dtype=bool)
        diff = ru[days] - bu[days]
        if len(diff) > 1:
            t = stats.ttest_1samp(diff, 0.0)
            t_test = {"mean_daily_diff": float(np.mean(diff) * 100), "t": float(t.statistic), "p": float(t.pvalue)}

    chunks = np.array_split(np.arange(n), 5)
    held_periods = sum(1 for c in chunks if _claim(kind, r[c], b[c], s[c], mask[c])[0])

    context = [{"name": "Idea", "built_cagr": _cagr(r[built]), "unseen_cagr": _cagr(ru), "unseen_max_dd": _max_dd(ru)}]
    for name in CONTEXT:
        if name in rets:
            col = rets[name].to_numpy()
            ok_b, ok_u = ~np.isnan(col[built]), ~np.isnan(col[unseen])
            context.append({"name": name, "built_cagr": _cagr(col[built][ok_b]), "unseen_cagr": _cagr(col[unseen][ok_u]),
                            "unseen_max_dd": _max_dd(col[unseen][ok_u])})

    cum_r, cum_b = (np.cumprod(1 + r) - 1) * 100, (np.cumprod(1 + b) - 1) * 100
    step = max(1, math.ceil(n / CURVE_POINTS))
    points = list(range(0, n, step))
    if points[-1] != n - 1:
        points[-1] = n - 1
    curve = [{"t": str(idx[i].date()), "idea": float(cum_r[i]), "benchmark": float(cum_b[i])} for i in points]

    return _clean({
        **base, "verdict": verdict, "headline": headline, "reason": None,
        "claim": {"built": {"holds": bool(on_b[0]), "value": on_b[1], "label": on_b[2]},
                  "unseen": {"holds": bool(on_u[0]), "value": on_u[1], "label": on_u[2]}},
        "shuffle": {"beats_pct": beats, "p": p, "bar": bar, "permutations": permutations, "seed": seed,
                    "method": "random timing" if spec.when is not None else "sign-flip vs comparison"},
        "t_test": t_test, "periods": {"held": held_periods, "of": 5}, "context": context, "curve": curve,
    })
