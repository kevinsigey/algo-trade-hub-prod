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
import re
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from tradehub.workshop import signals
from tradehub.workshop.spec import CASH, Condition, Exits, Group, IdeaSpec

DAYS = 252
MIN_UNSEEN_DAYS = 504
MIN_CONDITION_DAYS = 21
CURVE_POINTS = 600
MIN_GATE_DAYS = 63  # live-paper gate: ~3 months of data the backtest never saw (Kevin, 2026-10-30)
GATE_WINDOW = 252  # ...judged on at most the most recent 12 months of it
MAX_POSITION_PCT = 25
COVERAGE_GAP = pd.Timedelta(days=365)  # analyst data: a hole this long means coverage hadn't really started
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
    needed += [leg.underlying for leg in spec.options]
    needed += [c.series for c in _conditions(spec) if c.source in ("price", "analyst")]  # target_upside reads the close
    needed += [t for c in _conditions(spec) if c.source == "spread" for t in re.split(r"[+/]", c.series)]
    needed += list(spec.portfolio.core) if spec.portfolio else []
    return list(dict.fromkeys(needed + list(CONTEXT)))


def _conditions(spec: IdeaSpec) -> list[Condition]:
    if spec.rules is None:
        return []
    return list(spec.rules.enter.conditions) + (list(spec.rules.exit.conditions) if spec.rules.exit else [])


def rule_series_ids(spec: IdeaSpec) -> list[str]:
    """The FRED ids the rule reads."""
    return list(dict.fromkeys(c.series for c in _conditions(spec) if c.source == "fred"))


def option_series_ids(spec: IdeaSpec) -> list[str]:
    """The FRED ids option legs read: each underlying's vol index (when CBOE publishes one)
    plus DTB3 for the rate. Underlyings without an index fall back to realised vol in the
    pricing core and the run labels them the cruder model."""
    if not spec.options:
        return []
    from tradehub.workshop.options import VOL_INDEX
    ids = [VOL_INDEX[u] for u in dict.fromkeys(leg.underlying for leg in spec.options) if u in VOL_INDEX]
    return list(dict.fromkeys(ids + ["DTB3"]))


def analyst_tickers(spec: IdeaSpec) -> list[str]:
    """The stocks whose analyst actions the rule reads."""
    return list(dict.fromkeys(c.series for c in _conditions(spec) if c.source == "analyst"))


def news_series_ids(spec: IdeaSpec) -> list[str]:
    """The news baskets the rule reads (workshop/news.py). They land in the same
    series dict as FRED and take the same t-2 publication lag in _hit: a day's tone
    is only complete after the day ends."""
    return list(dict.fromkeys(c.series for c in _conditions(spec) if c.source == "news"))


def spread_series(series: str, closes: pd.DataFrame) -> pd.Series:
    """log(equal-weight geometric basket of the left legs) - log(same of the right legs), from daily closes."""
    left, right = (side.split("+") for side in series.split("/"))
    return np.log(closes[left]).mean(axis=1, skipna=False) - np.log(closes[right]).mean(axis=1, skipna=False)


def _hit(c: Condition, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> pd.Series:
    """True on day t when the condition held on information available at the close of t-1 (FRED: t-2)."""
    idx = closes.index
    bars = None
    if c.source == "price":
        values, lag = closes[c.series], 1
        if c.measure == "vs_vwap":
            t = c.series
            cols = {f"{t}.high": "high", f"{t}.low": "low", t: "close", f"{t}.volume": "volume"}
            if any(k not in closes for k in cols):
                raise ValueError(f"a VWAP rule needs daily bars with volume for {t}")
            bars = closes[list(cols)].rename(columns=cols)
    elif c.source == "spread":
        values, lag = spread_series(c.series, closes), 1
    elif c.source == "analyst":  # actions land during the day: one more day, like FRED
        measured = signals.analyst_measure(fred[f"{c.series}@analyst"], idx, c.measure, c.lookback_days,
                                           close=closes[c.series])
        hit = measured > c.threshold if c.op == ">" else measured < c.threshold
        return (hit & measured.notna()).shift(2, fill_value=False).astype(bool)
    else:
        raw = fred[c.series].sort_index()
        values, lag = raw.reindex(idx.union(raw.index)).ffill().reindex(idx), 2  # +1 day for publication
    measured = signals.measure(values, c.measure, c.lookback_days, slow=c.slow_days, bars=bars)
    hit = measured > c.threshold if c.op == ">" else measured < c.threshold
    return (hit & measured.notna()).shift(lag, fill_value=False).astype(bool)  # missing value = false


def _group(g: Group, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> np.ndarray:
    hits = np.vstack([_hit(c, closes, fred).to_numpy() for c in g.conditions])
    return hits.all(axis=0) if g.mode == "all" else hits.any(axis=0)


def _hold_state(enter: np.ndarray, exit: np.ndarray) -> np.ndarray:
    """In from a day `enter` holds until a day `exit` holds; exit wins a day both hold."""
    out = np.zeros(len(enter), dtype=bool)
    on = False
    for i in range(len(enter)):
        if exit[i]:
            on = False
        elif enter[i]:
            on = True
        out[i] = on
    return out


def condition_mask(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series]) -> pd.Series:
    """True on day t when the rule has the idea in, on information available before day t."""
    idx = closes.index
    if spec.rules is None:
        return pd.Series(True, index=idx)
    mask = _group(spec.rules.enter, closes, fred)
    if spec.rules.exit is not None:
        mask = _hold_state(mask, _group(spec.rules.exit, closes, fred))
    lag = 1 if spec.execution.timing == "close" else 0  # a market-on-close order fills a day after the decision
    return pd.Series(mask, index=idx).shift(lag, fill_value=False).astype(bool)


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
            return False, math.nan, "the rule was never in"
        v = float(np.mean(r[mask] - b[mask]) * DAYS * 100)
        return v > 0, v, f"{v:+.1f} pts/yr vs benchmark while the rule was in"
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


def _frame(spec: IdeaSpec, closes: pd.DataFrame, fred: dict | None = None) -> pd.DataFrame:
    """The rows the rule runs on: from the start date (or the day analyst coverage begins, so years with no
    analyst data don't count as "out" days), dropping any day a rule ticker has no close."""
    rule = list(dict.fromkeys(list(spec.hold) + list(spec.short) + ([spec.otherwise] if spec.otherwise != CASH else [])
                              + [spec.benchmark, "SPY"] + (list(spec.portfolio.core) if spec.portfolio else [])
                              + [leg.underlying for leg in spec.options]))
    start = pd.Timestamp(spec.start)
    for c in _conditions(spec):
        if c.source == "analyst":
            acts = (fred or {})[f"{c.series}@analyst"]
            dated = acts.index[acts["target"].notna()] if c.measure == "target_upside" else acts.index
            if not len(dated):
                start = pd.Timestamp.max
                continue
            d = dated.sort_values()
            gaps = np.flatnonzero((d[1:] - d[:-1]) > COVERAGE_GAP)
            # Coverage begins after the last year-long hole (AAPL: one 2012 row, then nothing until 2019).
            start = max(start, d[gaps[-1] + 1 if len(gaps) else 0].normalize())
    return closes[closes.index >= start].dropna(subset=rule)


def _legbars(spec: IdeaSpec, closes: pd.DataFrame, fred: dict | None = None) -> dict | None:
    """For intraday exits: the single leg's daily open/high/low/close and prior close, aligned with the returns."""
    if spec.exits.mode != "intraday" or not spec.exits.any():
        return None
    leg = (spec.hold or spec.short)[0]
    cols = [f"{leg}.open", f"{leg}.high", f"{leg}.low"]
    if any(c not in closes for c in cols):
        raise ValueError(f"intraday exits need daily bars for {leg} (open/high/low)")
    frame = _frame(spec, closes, fred)
    filled = frame[cols].fillna({c: frame[leg] for c in cols})  # a missing bar part reads as the close
    return {"open": filled[cols[0]].to_numpy()[1:], "high": filled[cols[1]].to_numpy()[1:],
            "low": filled[cols[2]].to_numpy()[1:], "close": frame[leg].to_numpy()[1:],
            "prev": frame[leg].to_numpy()[:-1], "side": 1 if spec.hold else -1}


def _option_leg_series(spec: IdeaSpec, frame: pd.DataFrame, fred: dict[str, pd.Series],
                         mask_all: pd.Series, div_yields: dict[str, float]) -> dict[int, pd.Series]:
    """Each option leg's daily return per $1 of underlying notional, on the returns index
    (frame rows 1..). A leg opens a FRESH contract at the first close of every in-segment --
    strike set from that close -- and is flat while the rule is out; rolls inside a segment
    are the pricing core's job. Model prices throughout (options.py): the run says so."""
    from tradehub.workshop.options import implied_vol_series, leg_returns

    if "DTB3" not in fred:
        raise ValueError("an options test needs the DTB3 rate series (the data layer fetches it)")
    rets_index = frame.index[1:]
    in_mask = mask_all.iloc[1:].to_numpy(dtype=bool)
    rate = (fred["DTB3"].astype(float) / 100.0).reindex(frame.index, method="ffill")
    vols: dict[str, pd.Series] = {}
    out: dict[int, pd.Series] = {}
    # In-segment boundaries over returns positions: a segment [a..b] enters at frame row a+1.
    starts = [i for i in range(len(in_mask)) if in_mask[i] and (i == 0 or not in_mask[i - 1])]
    ends = [i for i in range(len(in_mask)) if in_mask[i] and (i == len(in_mask) - 1 or not in_mask[i + 1])]
    for li, leg in enumerate(spec.options):
        u = leg.underlying
        if u not in vols:
            vols[u] = implied_vol_series(u, frame[u], fred)[0]
        series = pd.Series(0.0, index=rets_index)
        for a, b in zip(starts, ends, strict=True):
            rows = frame.index[a + 1: b + 2]  # entry close .. last in-day close
            priced = leg_returns(leg.kind, 1 if leg.side == "buy" else -1, frame[u].loc[rows],
                                 vols[u].loc[rows], rate.loc[rows], div_yields.get(u, 0.0),
                                 days_to_expiry=leg.days_to_expiry, strike_pct=leg.strike_pct,
                                 roll_days_left=leg.roll_days_left)
            series.loc[rows] = priced["ret"].to_numpy()
        out[li] = series
    return out


def _legs(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series],
          div_yields: dict[str, float] | None = None):
    """The one rule implementation shared by the backtest, the live-paper gate and the shadow track."""
    frame = _frame(spec, closes, fred)
    mask_all = condition_mask(spec, frame, fred)
    rets = frame.pct_change().iloc[1:]
    # Equal weight across every position; a short leg earns -r (rebalanced daily) and pays its borrow fee
    # each day held. A covered option leg folds into its underlying's stream (its return is per $1 of
    # underlying notional); a standalone leg is its own position.
    hold_sum = rets[spec.hold].sum(axis=1) if spec.hold else pd.Series(0.0, index=rets.index)
    short_sum = rets[spec.short].sum(axis=1) if spec.short else pd.Series(0.0, index=rets.index)
    n_pos = len(spec.hold) + len(spec.short)
    extra = pd.Series(0.0, index=rets.index)
    if spec.options:
        leg_map = _option_leg_series(spec, frame, fred, mask_all, div_yields or {})
        for li, leg in enumerate(spec.options):
            contrib = leg_map[li] * leg.qty_per_share
            if leg.underlying in spec.hold:
                hold_sum = hold_sum + contrib
            else:
                extra = extra + contrib
                n_pos += 1
    borrow = spec.borrow_bps_yr / 1e4 / DAYS * len(spec.short) / n_pos
    held = ((hold_sum - short_sum + extra) / n_pos).to_numpy() - borrow
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


def apply_exits_intraday(signal: np.ndarray, b: dict[str, np.ndarray], side: int, exits: Exits,
                         cooldown: int | None, lag: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(held, exit_reason, exit_day_return) for a one-ticker idea whose stops are real orders during the day.

    `b` holds the leg's daily open/high/low/close and `prev` (the prior close) aligned with the signal. Entry is
    the prior close. A stop (fixed or trailing, whichever is tighter) fills at the stop, or at the open when the
    day gaps through it; a take-profit likewise. If one day touches both, the stop is assumed to come first. The
    exit day earns prior close -> fill and the idea is out from the next day. The trailing high-water mark is the
    best daily high before today. Time stops stay close-based (decided at the close, out after `lag`). Re-entry
    rules are apply_exits'."""
    n = len(signal)
    held = np.zeros(n, dtype=bool)
    why = np.full(n, "", dtype=object)
    ret = np.full(n, np.nan)
    in_pos = stopped = False
    entry = hwm = 0.0
    days = left = 0
    exit_from = None
    for i in range(n):
        want = bool(signal[i])
        if exit_from is not None and i >= exit_from:
            in_pos, stopped, left, exit_from = False, True, cooldown or 0, None
        if stopped:
            if cooldown is None:
                stopped = want
            elif left == 0:
                stopped = False
            else:
                left -= 1
        if not (want and not stopped):
            in_pos, exit_from = False, None
            continue
        if not in_pos:
            in_pos, entry, hwm, days = True, b["prev"][i], b["prev"][i], 0
        held[i] = True
        days += 1
        o, hi, lo, prev = b["open"][i], b["high"][i], b["low"][i], b["prev"][i]
        stops = []
        if exits.stop_loss_pct is not None:
            stops.append((entry * (1 - side * exits.stop_loss_pct / 100), "stop-loss"))
        if exits.trailing_pct is not None:
            stops.append((hwm * (1 - side * exits.trailing_pct / 100), "trailing"))
        fill = None
        if stops:
            level, kind = (max if side > 0 else min)(stops, key=lambda x: x[0])  # the tighter one binds
            if side * (o - level) <= 0:
                fill = (o, kind)
            elif side * ((lo if side > 0 else hi) - level) <= 0:
                fill = (level, kind)
        if fill is None and exits.take_profit_pct is not None:
            target = entry * (1 + side * exits.take_profit_pct / 100)
            if side * (o - target) >= 0:
                fill = (o, "take-profit")
            elif side * ((hi if side > 0 else lo) - target) >= 0:
                fill = (target, "take-profit")
        hwm = max(hwm, hi) if side > 0 else min(hwm, lo)
        if fill is not None and exit_from is None:
            ret[i] = side * (fill[0] / prev - 1)
            why[i] = fill[1]
            exit_from = i + 1  # out from tomorrow: the stop order already sold
        elif exit_from is None and exits.max_days is not None and days >= exits.max_days:
            why[i] = "time"
            exit_from = i + lag
    return held, why, ret


def _held(spec: IdeaSpec, signal: np.ndarray, sleeve: np.ndarray, legbars: dict | None = None
          ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(position, exit_reason, sleeve) with the idea's exits applied. Intraday exits replace the exit day's sleeve
    return with the fill (prior close -> stop/target price)."""
    if not spec.exits.any():
        return signal, np.full(len(signal), "", dtype=object), sleeve
    lag = 2 if spec.execution.timing == "close" else 1
    cooldown = None if spec.rules is not None else EXIT_COOLDOWN
    if legbars is None:
        position, why = apply_exits(signal, sleeve, spec.exits, cooldown, lag)
        return position, why, sleeve
    position, why, fill = apply_exits_intraday(signal, legbars, legbars["side"], spec.exits, cooldown, lag)
    return position, why, np.where(np.isnan(fill), sleeve, fill)


def _blend(spec: IdeaSpec, r: np.ndarray, rets: pd.DataFrame, rows: slice = slice(None)) -> np.ndarray:
    """A portfolio idea's daily return: its share of the idea plus the rest in the core (equal weight, daily)."""
    if spec.portfolio is None:
        return r
    core = rets[spec.portfolio.core].mean(axis=1).to_numpy()[rows]
    w = spec.portfolio.idea_share
    return w * r + (1 - w) * core


def _switch_cost(spec: IdeaSpec) -> float:
    """Commission plus slippage, as a fraction, paid on each switch in or out."""
    return (spec.cost_bps + spec.slippage_bps) / 1e4


def _build(m: np.ndarray, held: np.ndarray, other: np.ndarray, cost: float) -> np.ndarray:
    switches = np.concatenate([[False], m[1:] != m[:-1]])
    return np.where(m, held, other) - cost * switches


def daily_frame(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series],
                div_yields: dict[str, float] | None = None) -> pd.DataFrame:
    """Per trading day: the idea's return after costs, whether the rule had it in, the benchmark's and SPY's."""
    idx, mask, held, other, b, s, rets = _legs(spec, closes, fred, div_yields)
    position, why, sleeve = _held(spec, mask, held, _legbars(spec, closes, fred))
    ret = _blend(spec, _build(position, sleeve, other, _switch_cost(spec)), rets)
    return pd.DataFrame({"ret": ret, "on": mask, "bench": b, "spy": s, "exit": why, "held": position.astype(bool)},
                        index=idx)


def target_and_reason(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series],
                      div_yields: dict[str, float] | None = None) -> tuple[dict[str, float], str]:
    """Signed weights for the holding the order placed this morning establishes, from data up to the last close.

    Open/day orders set today's holding; a close order sets tomorrow's. Phantom business days are appended and the
    engine's own condition_mask reads them, so the lag rules are exactly the backtest's."""
    ahead = 2 if spec.execution.timing == "close" else 1
    frame = _frame(spec, closes, fred)  # drop gaps exactly as _legs does
    if frame.empty:
        return {}, "no data"
    extra = pd.bdate_range(frame.index[-1], periods=ahead + 1)[1:]
    padded = pd.concat([frame, frame.iloc[[-1] * ahead].set_axis(extra)])  # phantom days copy the last close
    for leg in list(spec.hold) + list(spec.short):  # ...as flat bars, so a phantom day can't trip an intraday stop
        for part in ("open", "high", "low"):
            if f"{leg}.{part}" in padded:
                padded.loc[extra, f"{leg}.{part}"] = frame[leg].iloc[-1]
    _, mask, held, *_ = _legs(spec, padded, fred, div_yields)
    position, why, _ = _held(spec, mask, held, _legbars(spec, padded, fred))  # the morning after a stop, it's out
    if bool(position[-1]):
        n = len(spec.hold) + len(spec.short)
        return _blend_weights(spec, {**{t: 1 / n for t in spec.hold}, **{t: -1 / n for t in spec.short}}), ""
    # The reason names an exit only when the exit is what keeps it flat: the rule itself still says hold.
    reason = next((w for w in why[::-1] if w), "") if bool(mask[-1]) else ""
    return _blend_weights(spec, {} if spec.otherwise == CASH else {spec.otherwise: 1.0}), reason


def _blend_weights(spec: IdeaSpec, idea: dict[str, float]) -> dict[str, float]:
    """The idea's weights scaled to its share, plus the core's share; a ticker in both adds up."""
    if spec.portfolio is None:
        return idea
    w, core = spec.portfolio.idea_share, spec.portfolio.core
    out = {t: w * v for t, v in idea.items()}
    for t in core:
        out[t] = out.get(t, 0.0) + (1 - w) / len(core)
    return out


def target_today(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series],
                 div_yields: dict[str, float] | None = None) -> dict[str, float]:
    return target_and_reason(spec, closes, fred, div_yields)[0]


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


def _late_listing_notes(spec: IdeaSpec, closes: pd.DataFrame) -> list[str]:
    """Say out loud when a leg's history starts long after the test's start date.

    `_frame` drops any day a rule ticker has no close, so one late-listing leg (a recent IPO)
    silently truncates the whole test: the "years it was built on" quietly become only the years
    since that listing, and years of benchmark history are never tested at all. The truncation
    itself is correct -- there are no prices to test -- but it must not be silent.
    """
    legs = list(dict.fromkeys(list(spec.hold) + list(spec.short)
                              + ([spec.otherwise] if spec.otherwise != CASH else [])
                              + [spec.benchmark]
                              + (list(spec.portfolio.core) if spec.portfolio else [])
                              + [leg.underlying for leg in spec.options]))
    start = pd.Timestamp(spec.start)
    notes = []
    for t in legs:
        if t not in closes:
            continue
        first = closes[t].first_valid_index()
        if first is not None and first > start + pd.Timedelta(days=30):
            notes.append(f"{t} has no prices before {first.date()}: every leg of this test starts then, "
                         "so the years before it are not tested.")
    return notes


def _walk_forward(spec: IdeaSpec, idx, r: np.ndarray, b: np.ndarray, s: np.ndarray, mask: np.ndarray) -> dict:
    """The claim re-judged on each successive stretch of the timeline, in order.

    The built/unseen split judges the claim once, on the final stretch. That cannot distinguish
    an edge that held throughout from one that only ever worked in the last two years. Split the
    timeline into five sequential folds, skip the first (that is the ground the idea was built
    on), and judge the claim on each later fold with at least a quarter of trading days.
    """
    n = len(r)
    folds = []
    for chunk in np.array_split(np.arange(n), 5)[1:]:
        if not len(chunk):
            continue
        days = len(chunk)
        entry = {"start": str(idx[chunk[0]].date()), "end": str(idx[chunk[-1]].date()), "days": days,
                 "holds": None, "value": None, "label": f"too short to judge ({days} days)",
                 "idea_cagr": _cagr(r[chunk]), "bench_cagr": _cagr(b[chunk])}
        if days >= MIN_GATE_DAYS:
            holds, value, label = _claim(spec.claim, r[chunk], b[chunk], s[chunk], mask[chunk])
            if math.isfinite(value):
                entry.update({"holds": bool(holds), "value": value, "label": label})
            else:
                entry["label"] = label  # e.g. the condition never held on this stretch
        folds.append(entry)
    judged = [f for f in folds if f["holds"] is not None]
    return {"folds": folds, "held": sum(1 for f in judged if f["holds"]), "of": len(judged)}


def run_test(spec: IdeaSpec, closes: pd.DataFrame, fred: dict[str, pd.Series], *, variations: int, seed: int,
             permutations: int = 1000, div_yields: dict[str, float] | None = None) -> dict:
    idx, mask, held, other, b, s, rets = _legs(spec, closes, fred, div_yields)
    cost = _switch_cost(spec)

    def build(m: np.ndarray, h: np.ndarray = held) -> np.ndarray:
        return _build(m, h, other, cost)

    legbars = _legbars(spec, closes, fred)
    position, _, sleeve = _held(spec, mask, held, legbars)
    r = _blend(spec, build(position, sleeve), rets)
    n = len(r)
    k = int(n * (1 - spec.unseen_fraction))
    built, unseen = slice(0, k), slice(k, n)
    bar = 0.05 / variations
    base = {"variations": variations, "split_date": str(idx[k].date()) if n > k else None,
            "data_start": str(idx[0].date()) if n else None, "data_end": str(idx[-1].date()) if n else None}
    # Computed before the not-enough-data return: a truncated or short history is exactly when
    # the notes matter, and the walk-forward's "of 0" is itself the honest answer there.
    notes = _late_listing_notes(spec, closes)
    options_info = None
    if spec.options:
        from tradehub.workshop.options import implied_vol_series
        leg_info = []
        for leg in spec.options:
            _, vol_label = implied_vol_series(leg.underlying, closes[leg.underlying], fred)
            leg_info.append({**leg.model_dump(mode="json"), "vol": vol_label})
        options_info = {"model_prices": True, "legs": leg_info}
        vols = ", ".join(f"{li['underlying']}: {li['vol']}" for li in leg_info)
        notes = notes + [f"Option legs are priced with a Black-Scholes model ({vols}), not real option "
                         "history -- read this verdict as a model check, not a market record."]
    walk_forward = _walk_forward(spec, idx, r, b, s, mask)

    reason = None
    n_u = n - k
    if n_u < MIN_UNSEEN_DAYS:
        reason = f"only {n_u} unseen trading days; at least {MIN_UNSEEN_DAYS} (2 years) are needed"
    elif spec.rules is not None and not (MIN_CONDITION_DAYS <= mask[unseen].sum() <= n_u - MIN_CONDITION_DAYS):
        reason = (f"the rule was in on {int(mask[unseen].sum())} of {n_u} unseen days; it needs at least "
                  f"{MIN_CONDITION_DAYS} days on and off")
    if reason:
        return _clean({**base, "verdict": "NOT ENOUGH DATA", "headline": HEADLINES["nodata"], "reason": reason,
                       "claim": None, "shuffle": None, "t_test": None, "periods": None, "context": [], "curve": [],
                       "notes": notes, "walk_forward": walk_forward, "options": options_info})

    kind = spec.claim
    on_b = _claim(kind, r[built], b[built], s[built], mask[built])
    on_u = _claim(kind, r[unseen], b[unseen], s[unseen], mask[unseen])
    actual = on_u[1]

    rng = np.random.default_rng(seed)
    ru, bu, su, mu, hu = r[unseen], b[unseen], s[unseen], mask[unseen], held[unseen]
    lb_u = None if legbars is None else {k: (v[unseen] if isinstance(v, np.ndarray) else v) for k, v in legbars.items()}
    if spec.rules is not None:
        perm = np.empty(permutations)
        for i in range(permutations):
            shifted = np.roll(mu, int(rng.integers(MIN_CONDITION_DAYS, n_u - MIN_CONDITION_DAYS)))
            pos, _, hp = _held(spec, shifted, hu, lb_u)  # random timing goes through the same exits
            sw = np.concatenate([[False], pos[1:] != pos[:-1]])
            rp = _blend(spec, np.where(pos, hp, other[unseen]) - cost * sw, rets, unseen)
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
                    "method": "random timing" if spec.rules is not None else "sign-flip vs comparison"},
        "t_test": t_test, "periods": {"held": held_periods, "of": 5}, "context": context, "curve": curve,
        "notes": notes, "walk_forward": walk_forward, "options": options_info,
    })


ROLLING_DAYS = 252


def analysis(frame: pd.DataFrame) -> dict:
    """A deeper look at a daily_frame: each calendar year (idea vs benchmark, share of days in, the idea's return
    on its in-days) and the rolling 12-month excess return, so a run shows when an edge appeared or stopped."""
    years = []
    for year, part in frame.groupby(frame.index.year):
        idea, bench = float((1 + part["ret"]).prod() - 1) * 100, float((1 + part["bench"]).prod() - 1) * 100
        on = part["held" if "held" in part else "on"].astype(bool)  # held: the rule's days minus stopped-out ones
        years.append({"year": int(year), "idea": idea, "bench": bench, "excess": idea - bench,
                      "days_in": float(on.mean() * 100),
                      "idea_in": float((1 + part["ret"][on]).prod() - 1) * 100 if on.any() else None})
    grow = lambda r: np.exp(np.log1p(r).rolling(ROLLING_DAYS).sum())  # noqa: E731
    excess = ((grow(frame["ret"]) - grow(frame["bench"])) * 100).dropna()
    step = max(1, math.ceil(len(excess) / CURVE_POINTS))
    points = list(range(0, len(excess), step)) + ([len(excess) - 1] if len(excess) and (len(excess) - 1) % step else [])
    return {"years": years, "rolling": [{"t": str(excess.index[i].date()), "excess": float(excess.iloc[i])}
                                        for i in points]}
