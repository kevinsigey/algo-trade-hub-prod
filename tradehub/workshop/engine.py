"""The Workshop's first test type: did the idea do what it claims, on years it was not built on, beyond chance?

Pure: daily closes and FRED series in, a verdict dict out. Rules (spec 2026-10-29 §4.4, step 2 plan Task 3):
- a condition is evaluated on data available at the PRIOR close; FRED values are lagged one more day;
- the claim is judged on the unseen span (the last `unseen_fraction` of the common range);
- the shuffle test runs on the unseen span only. A rule with a condition gets random timing (the condition
  mask circularly shifted). A rule with no condition has no timing to shuffle, so it gets a paired sign-flip
  test of the claim's own per-day quantity (log excess return, down-day excess, or downside variance), whose
  null is exactly symmetric -- flipping raw return differences would add volatility drag the idea never paid;
- PASS needs the claim to hold on unseen years AND p < 0.05 / variations.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from tradehub.workshop.spec import CASH, Exits, IdeaSpec

DAYS = 252
MIN_UNSEEN_DAYS = 504
MIN_CONDITION_DAYS = 21
CURVE_POINTS = 600
MIN_GATE_DAYS = 63  # live-paper gate: ~3 months of data the backtest never saw (Kevin, 2026-10-30)
GATE_WINDOW = 252  # ...judged on at most the most recent 12 months of it
MAX_POSITION_PCT = 25
EXIT_COOLDOWN = 21  # an idea with no condition has no fresh signal: back in after a month out (Kevin, 2026-10-30)
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
    needed = list(spec.hold) + list(spec.short) + ([spec.otherwise] if spec.otherwise != CASH else []) + [spec.benchmark]
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
    lag += 1 if spec.execution.timing == "close" else 0  # a market-on-close order fills a day after the decision
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


def _signflip_terms(kind: str, r: np.ndarray, b: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Per-day terms whose mean is the claim's test statistic; under the null each term is symmetric about 0."""
    if kind == "ballast":
        down = s < 0
        return (r - s)[down]
    if kind == "smoother_ride":
        return np.minimum(b, 0) ** 2 - np.minimum(r, 0) ** 2
    return np.log1p(r) - np.log1p(b)  # beats_benchmark


def p_value(actual: float, perm: np.ndarray) -> tuple[float, float]:
    """One-sided shuffle p and the share of shuffles beaten. A NaN shuffle counts AGAINST the idea."""
    if not math.isfinite(actual):
        return 1.0, 0.0
    perm = np.nan_to_num(perm, nan=np.inf)
    return (1 + int(np.sum(perm >= actual))) / (1 + len(perm)), 100 * float(np.sum(perm < actual)) / len(perm)


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


def _legs(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series]):
    """The one rule implementation shared by the backtest, the live-paper gate and the shadow track."""
    rule = list(dict.fromkeys(list(spec.hold) + list(spec.short) + ([spec.otherwise] if spec.otherwise != CASH else [])
                              + [spec.benchmark, "SPY"]))
    frame = closes[closes.index >= pd.Timestamp(spec.start)].dropna(subset=rule)
    mask_all = condition_mask(spec, frame, fred)
    rets = frame.pct_change().iloc[1:]
    # Equal weight across every leg; a short leg earns -r (rebalanced daily, borrow cost inside cost_bps).
    held = ((rets[spec.hold].sum(axis=1) - rets[spec.short].sum(axis=1)) / (len(spec.hold) + len(spec.short))).to_numpy()
    other = rets[spec.otherwise].to_numpy() if spec.otherwise != CASH else np.zeros(len(rets))
    return (rets.index, mask_all.iloc[1:].to_numpy(), held, other, rets[spec.benchmark].to_numpy(),
            rets["SPY"].to_numpy(), rets)


def apply_exits(signal: np.ndarray, sleeve: np.ndarray, exits: Exits, cooldown: int | None, lag: int
                ) -> tuple[np.ndarray, np.ndarray]:
    """(held, exit_reason) per day: the rule's signal with the idea's exits applied, checked at each close.

    An exit decided at the close of day i takes effect `lag` days later (1 for open/day orders, 2 for close orders,
    the same lag a rule change gets). Afterwards the idea stays out until a fresh signal (the signal off for a day),
    or, with no condition to give one, for `cooldown` days. A close-based exit can't cap a gap: the day's whole
    move counts."""
    n = len(signal)
    held = np.zeros(n, dtype=bool)
    why = np.full(n, "", dtype=object)
    in_pos = stopped = False
    value = best = 1.0
    days = left = 0
    exit_from = None
    for i in range(n):
        want = bool(signal[i])
        if exit_from is not None and i >= exit_from:
            in_pos, stopped, left, exit_from = False, True, cooldown or 0, None
        if stopped:
            if cooldown is None:
                stopped = want  # a day with the signal off ends it: the next "on" is fresh
            elif left == 0:
                stopped = False
            else:
                left -= 1
        on = want and not stopped
        if not on:
            in_pos, exit_from = False, None
            continue
        if not in_pos:
            in_pos, value, best, days = True, 1.0, 1.0, 0
        held[i] = True
        value *= 1 + sleeve[i]
        best, days = max(best, value), days + 1
        if exit_from is None:
            if exits.stop_loss_pct is not None and value <= 1 - exits.stop_loss_pct / 100:
                why[i] = "stop-loss"
            elif exits.trailing_pct is not None and value <= best * (1 - exits.trailing_pct / 100):
                why[i] = "trailing"
            elif exits.take_profit_pct is not None and value >= 1 + exits.take_profit_pct / 100:
                why[i] = "take-profit"
            elif exits.max_days is not None and days >= exits.max_days:
                why[i] = "time"
            if why[i]:
                exit_from = i + lag
    return held, why


def _held(spec: IdeaSpec, signal: np.ndarray, sleeve: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if not spec.exits.any():
        return signal, np.full(len(signal), "", dtype=object)
    lag = 2 if spec.execution.timing == "close" else 1
    return apply_exits(signal, sleeve, spec.exits, None if spec.when is not None else EXIT_COOLDOWN, lag)


def _build(m: np.ndarray, held: np.ndarray, other: np.ndarray, cost: float) -> np.ndarray:
    switches = np.concatenate([[False], m[1:] != m[:-1]])
    return np.where(m, held, other) - cost * switches


def daily_frame(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> pd.DataFrame:
    """Per trading day: the idea's return after costs, whether the condition held, the benchmark's and SPY's."""
    idx, mask, held, other, b, s, _ = _legs(spec, closes, fred)
    position, why = _held(spec, mask, held)
    return pd.DataFrame({"ret": _build(position, held, other, spec.cost_bps / 1e4), "on": mask, "bench": b, "spy": s,
                         "exit": why}, index=idx)


def target_today(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> dict[str, float]:
    """Signed weights for the holding the order placed this morning establishes, from data up to the last close.

    Open/day orders set today's holding; a close order sets tomorrow's. Phantom business days are appended and the
    engine's own condition_mask reads them, so the lag rules are exactly the backtest's."""
    ahead = 2 if spec.execution.timing == "close" else 1
    last = closes.dropna(subset=list(spec.hold) + list(spec.short)).index[-1]
    extra = pd.bdate_range(last, periods=ahead + 1)[1:]
    padded = pd.concat([closes[closes.index <= last],
                        pd.DataFrame(index=extra, columns=closes.columns, dtype=float)]).ffill()
    _, mask, held, *_ = _legs(spec, padded, fred)
    position, _ = _held(spec, mask, held)  # exits too: the morning after a stop, the idea is out
    if bool(position[-1]):
        n = len(spec.hold) + len(spec.short)
        return {**{t: 1 / n for t in spec.hold}, **{t: -1 / n for t in spec.short}}
    return {} if spec.otherwise == CASH else {spec.otherwise: 1.0}


def claim_check(spec: IdeaSpec, rows: pd.DataFrame) -> dict:
    """The claim on any span of daily_frame rows (gate recheck, paper record)."""
    holds, value, label = _claim(spec.claim, rows["ret"].to_numpy(), rows["bench"].to_numpy(),
                                 rows["spy"].to_numpy(), rows["on"].to_numpy(dtype=bool))
    judged = math.isfinite(value)  # e.g. the condition never held on these days: nothing to judge yet
    return {"holds": bool(holds) if judged else None, "value": value, "label": label, "days": len(rows)}


def gate_check(spec: IdeaSpec, frame: pd.DataFrame, data_end: date, size_pct: float | None) -> dict:
    """Live-paper gate (spec §5): the claim on data that arrived after the backtest (at most the last 12 months),
    each position within the book limit. Kevin's button is the third part."""
    new = frame[frame.index > pd.Timestamp(data_end)]
    reasons: list[str] = []
    per = None if size_pct is None else size_pct / len(spec.hold)
    size_ok = None if per is None else per <= MAX_POSITION_PCT
    if size_ok is False:
        reasons.append(f"each position would be {per:.0f}% of the account; the limit is {MAX_POSITION_PCT}%")
    claim = None
    if len(new) < MIN_GATE_DAYS:
        reasons.insert(0, f"waiting for data: {len(new)} of {MIN_GATE_DAYS} new trading days since the backtest")
    else:
        claim = _clean(claim_check(spec, new.iloc[-GATE_WINDOW:]))
        if claim["holds"] is None:
            reasons.append(f"waiting for data: the claim can't be judged on the new data yet ({claim['label']})")
        elif not claim["holds"]:
            reasons.append(f"the claim did not hold on the new data ({claim['label']})")
    if size_ok is None:
        reasons.append("enter a size")
    if size_ok is False or (claim is not None and claim["holds"] is False):
        status = "fails"
    elif claim is None or claim["holds"] is None or size_ok is None:
        status = "waiting"
    else:
        status = "ready"
    return {"status": status, "new_days": len(new), "needed": MIN_GATE_DAYS, "claim": claim, "size_ok": size_ok,
            "reasons": reasons}


def run_test(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series], *, variations: int, seed: int,
             permutations: int = 1000) -> dict:
    idx, mask, held, other, b, s, rets = _legs(spec, closes, fred)
    cost = spec.cost_bps / 1e4

    def build(m: np.ndarray, h: np.ndarray = held) -> np.ndarray:
        return _build(m, h, other, cost)

    r = build(_held(spec, mask, held)[0])
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
    if spec.when is not None:
        perm = np.empty(permutations)
        for i in range(permutations):
            shifted = np.roll(mu, int(rng.integers(MIN_CONDITION_DAYS, n_u - MIN_CONDITION_DAYS)))
            pos = _held(spec, shifted, hu)[0]  # random timing goes through the same exits
            sw = np.concatenate([[False], pos[1:] != pos[:-1]])
            rp = np.where(pos, hu, other[unseen]) - cost * sw
            perm[i] = _claim(kind, rp, bu, su, shifted)[1]
        p, beats = p_value(actual, perm)
    else:
        terms = _signflip_terms(kind, ru, bu, su)
        signs = rng.choice((-1.0, 1.0), size=(permutations, len(terms)))
        p, beats = p_value(float(np.mean(terms)) if len(terms) else math.nan, (signs * terms).mean(axis=1))

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
