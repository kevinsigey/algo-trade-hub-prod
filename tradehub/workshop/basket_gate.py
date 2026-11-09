"""The basket battery (spec 2026-11-08, claim-typed gates): the verdict for an
always-in allocation, measured relatively.

The timing gate asks "did the rule get in at the right times?" — a question a
permanent basket cannot answer, because it is never out. This battery asks the
allocation's own question instead: over identical windows, did the idea outrun
its benchmark by more than bootstrap chance, and did it fall into a deeper hole
doing it? Everything is computed on the log-excess series
`log1p(idea) - log1p(benchmark)` — the same per-day terms the timing gate's
sign-flip uses — with the context frozen at run time (the run's benchmark, its
spans, the house cost defaults already inside the idea's series).

Frozen constants (preregistered in the spec; changing them is a new
preregistration, not an edit):

- BLOCK_DAYS 21: the circular block bootstrap resamples ~monthly blocks, the
  standard block length for daily financial series.
- BOOTSTRAPS 2000, CI the 95% percentile interval of bootstrap relative
  Sharpes; a span's CI leg holds only when the interval excludes 0.
- DD_RATIO_MAX 1.25: per span, the idea's max drawdown may be at most a
  quarter deeper than the benchmark's over the same span.
- DD_MIN_BENCH_PP 5.0: below a 5-point benchmark drawdown the ratio is noise;
  the leg is recorded not-binding and does not gate.
- SEED_OFFSET 7919: the battery draws from the run's seed plus this frozen
  offset, so its randomness never reuses the timing shuffle's stream.

Pure: daily return arrays in, a battery dict out. The engine owns the frame,
the spans and the result shape; this module owns the measurement.
"""

from __future__ import annotations

import math

import numpy as np

DAYS = 252
BLOCK_DAYS = 21
BOOTSTRAPS = 2000
CI_LO_PCT, CI_HI_PCT = 2.5, 97.5
DD_RATIO_MAX = 1.25
DD_MIN_BENCH_PP = 5.0
SEED_OFFSET = 7919
_CHUNK = 250  # bootstrap rows per block of work: caps the index matrix's memory


def _cagr(r: np.ndarray) -> float:
    if len(r) == 0:
        return math.nan
    growth = float(np.prod(1 + r))
    return (growth ** (DAYS / len(r)) - 1) * 100 if growth > 0 else -100.0


def _max_dd(r: np.ndarray) -> float:
    """Worst peak-to-trough fall, in percent, <= 0 — the engine's own convention."""
    if not len(r):
        return math.nan
    wealth = np.cumprod(1 + r)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1) * 100)


def relative_sharpe(x: np.ndarray) -> float:
    """Annualized Sharpe of a daily excess series. A series with no variance
    has no measurable edge: 0.0 when its mean is 0, signed infinity otherwise
    (a constant non-zero excess — a bookkeeping case, not a market one)."""
    if len(x) < 2:
        return math.nan
    sd = float(np.std(x, ddof=1))
    if sd == 0.0:
        mean = float(np.mean(x))
        return 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
    return float(np.mean(x) / sd * math.sqrt(DAYS))


def _sharpe_rows(samples: np.ndarray) -> np.ndarray:
    means = samples.mean(axis=1)
    stds = samples.std(axis=1, ddof=1)
    out = np.where(stds > 0, means / np.where(stds > 0, stds, 1.0), 0.0)
    flat = stds == 0  # a resample with no variance: its Sharpe is 0 unless its mean isn't
    out = np.where(flat & (means != 0), np.sign(means) * 1e6, out)
    return out * math.sqrt(DAYS)


def bootstrap_ci(x: np.ndarray, *, seed: int, bootstraps: int = BOOTSTRAPS,
                 block: int = BLOCK_DAYS) -> tuple[float, float, float]:
    """(ci_low, ci_high, p) for the relative Sharpe of `x`, by circular block bootstrap.

    p is the one-sided bootstrap analogue, (1 + #{Sharpe <= 0}) / (1 + B) — the
    house's plus-one convention, so a perfect record reads 1/(B+1), never 0."""
    n = len(x)
    if n < block + 1 or not math.isfinite(relative_sharpe(x)):
        return math.nan, math.nan, 1.0
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    offsets = np.arange(block)
    sharpes = np.empty(bootstraps)
    for lo in range(0, bootstraps, _CHUNK):
        rows = min(_CHUNK, bootstraps - lo)
        starts = rng.integers(0, n, size=(rows, n_blocks))
        idx = ((starts[:, :, None] + offsets) % n).reshape(rows, -1)[:, :n]
        sharpes[lo:lo + rows] = _sharpe_rows(x[idx])
    ci_low, ci_high = (float(v) for v in np.percentile(sharpes, [CI_LO_PCT, CI_HI_PCT]))
    p = (1 + int(np.sum(sharpes <= 0))) / (1 + bootstraps)
    return ci_low, ci_high, float(p)


def span_stats(r: np.ndarray, ref: np.ndarray, *, seed: int,
               bootstraps: int = BOOTSTRAPS) -> dict:
    """One span of the idea against one reference (the benchmark, or the
    equal-weight basket of its own legs): the relative read the battery judges."""
    x = np.log1p(r) - np.log1p(ref)
    ci_low, ci_high, p = bootstrap_ci(x, seed=seed, bootstraps=bootstraps)
    dd_i, dd_r = _max_dd(r), _max_dd(ref)
    binding = bool(math.isfinite(dd_r) and abs(dd_r) >= DD_MIN_BENCH_PP)
    ratio = float(abs(dd_i) / abs(dd_r)) if binding else None
    return {"days": int(len(r)), "excess_cagr": float(_cagr(r) - _cagr(ref)),
            "rel_sharpe": float(relative_sharpe(x)), "ci_low": ci_low, "ci_high": ci_high, "p": p,
            "idea_max_dd": float(dd_i), "bench_max_dd": float(dd_r),
            "dd_ratio": ratio, "dd_binding": binding,
            "dd_holds": bool(ratio <= DD_RATIO_MAX) if binding else True}


def battery(r: np.ndarray, b: np.ndarray, ew: np.ndarray | None, *, split: int, seed: int,
            bootstraps: int = BOOTSTRAPS) -> dict:
    """The basket verdict over both spans. `ew` is the equal-weight reference
    series (same length as `r`), or None when the comparison is degenerate —
    the engine decides; the battery just reports what it is given."""
    spans: dict[str, dict] = {}
    legs: list[dict] = []
    for name, sl in (("built", slice(0, split)), ("unseen", slice(split, len(r)))):
        st = span_stats(r[sl], b[sl], seed=seed + (0 if name == "built" else 1), bootstraps=bootstraps)
        spans[name] = st
        ci_holds = bool(math.isfinite(st["ci_low"]) and st["ci_low"] > 0)
        legs.append({"name": f"ci_{name}", "holds": ci_holds,
                     "detail": f"relative Sharpe {st['rel_sharpe']:.2f}, 95% CI "
                               f"[{st['ci_low']:.2f}, {st['ci_high']:.2f}] must exclude 0"})
        dd_detail = (f"idea {st['idea_max_dd']:.1f}% vs benchmark {st['bench_max_dd']:.1f}% "
                     f"(ratio {st['dd_ratio']:.2f} <= {DD_RATIO_MAX})" if st["dd_binding"] else
                     f"not binding: the benchmark fell only {st['bench_max_dd']:.1f}% on this span")
        legs.append({"name": f"dd_{name}", "holds": bool(st["dd_holds"]), "detail": dd_detail})
    ew_block = None
    if ew is not None:
        ew_block = {"spans": {
            name: span_stats(r[sl], ew[sl], seed=seed + (101 if name == "built" else 102),
                             bootstraps=bootstraps)
            for name, sl in (("built", slice(0, split)), ("unseen", slice(split, len(r))))}}
    return {"type": "basket",
            "constants": {"block_days": BLOCK_DAYS, "bootstraps": bootstraps,
                          "ci_pct": [CI_LO_PCT, CI_HI_PCT], "dd_ratio_max": DD_RATIO_MAX,
                          "dd_min_bench_pp": DD_MIN_BENCH_PP},
            "spans": spans, "ew_reference": ew_block, "p": spans["unseen"]["p"], "legs": legs,
            "verdict": "PASS" if all(leg["holds"] for leg in legs) else "FAIL"}
