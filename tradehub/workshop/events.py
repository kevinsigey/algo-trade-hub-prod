"""Event studies (Kevin, 2026-10-31): the IB Python Models method in the Workshop.

An event is an earnings print, an FOMC statement, a CPI or jobs release (FRED's release calendar), or a price gap.
Each event is measured the way earnings_event_study.py does it:
- the reaction day is the first trading day whose close reflects it (released before noon New York -> that day,
  later -> the next trading day);
- AR = the ticker's daily return minus SPY's (market-adjusted; SPY itself uses its raw return);
- ar0 = AR on the reaction day; car_a_b = AR summed over days +a..+b; pre_5 = days -5..-1. All in %.
The claim ("<ticker> drifts <up|down> over <window> after <event>") is judged like every Workshop idea: on the
newest events it was not built on, against the same window measured on random non-event dates, with the bar
raised for each variation tried. Per-ticker means are also shrunk toward the pooled mean (empirical Bayes, the
Strategy HQ v5.0 rule), so a perfect 3-for-3 record shows as the small sample it is.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scipy import stats

from tradehub.workshop.engine import HEADLINES, _clean, p_value, verdict_of
from tradehub.workshop.spec import _ticker

RELEASES = {"fomc": 101, "cpi": 10, "jobs": 50}  # FRED release ids: FOMC Press Release, CPI, Employment Situation
WINDOWS = {"reaction": ("ar0", "the reaction day"), "drift_1_3": ("car_1_3", "days +1 to +3"),
           "drift_1_5": ("car_1_5", "days +1 to +5"), "drift_1_10": ("car_1_10", "days +1 to +10")}
MIN_EVENTS, MIN_UNSEEN_EVENTS = 20, 10
COLUMNS = ("ar0", "car_1_3", "car_1_5", "car_1_10", "pre_5")


class EventSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event"] = "event"
    title: str = Field(min_length=3, max_length=120)
    tickers: list[str] = Field(min_length=1, max_length=10)
    event: Literal["earnings", "fomc", "cpi", "jobs", "gap"]
    when: Literal["all", "beat", "miss", "up", "down"] = "all"  # earnings: all/beat/miss; gap: up/down
    gap_pct: float = Field(5, ge=1, le=50)  # a gap = a day's move vs SPY at least this big, in %
    window: Literal["reaction", "drift_1_3", "drift_1_5", "drift_1_10"] = "drift_1_5"
    direction: Literal["up", "down"]
    benchmark: str = "SPY"
    start: date = date(2010, 1, 4)
    unseen_fraction: float = Field(0.3, ge=0.1, le=0.5)
    assumptions: list[str] = []

    @field_validator("tickers")
    @classmethod
    def _tickers(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(_ticker(t) for t in v))

    @field_validator("benchmark")
    @classmethod
    def _bench(cls, v: str) -> str:
        return _ticker(v)

    @model_validator(mode="after")
    def _fits(self) -> EventSpec:
        if self.event == "gap":
            if self.when not in ("up", "down"):
                raise ValueError("a gap event needs when = up or down")
            if self.window == "reaction":
                raise ValueError("a gap is its own reaction day: judge the drift after it")
        elif self.event == "earnings" and self.when not in ("all", "beat", "miss"):
            raise ValueError("earnings events take when = all, beat or miss")
        elif self.event in RELEASES and self.when != "all":
            raise ValueError(f"{self.event} days take when = all")
        return self


def reaction_day(t: pd.Timestamp, days: pd.DatetimeIndex) -> pd.Timestamp | None:
    """The first trading day whose close reflects an event at New York time `t` (before noon -> that day)."""
    d = t.normalize() if t.hour < 12 else t.normalize() + pd.Timedelta(days=1)
    i = days.searchsorted(d)
    return days[i] if i < len(days) else None


def _windows(ar: np.ndarray) -> dict[str, np.ndarray]:
    """Every window, for every day as if it were an event day (NaN where the window runs off the data)."""
    n = len(ar)
    cs = np.concatenate([[0.0], np.cumsum(np.nan_to_num(ar))])
    bad = np.concatenate([[0], np.cumsum(np.isnan(ar))])
    i = np.arange(n)

    def span(a: int, b: int) -> np.ndarray:
        lo, hi = i + a, i + b + 1
        ok = (lo >= 0) & (hi <= n)
        lo_c, hi_c = np.clip(lo, 0, n), np.clip(hi, 0, n)
        out = (cs[hi_c] - cs[lo_c]) * 100
        return np.where(ok & (bad[hi_c] - bad[lo_c] == 0), out, np.nan)
    return {"ar0": span(0, 0), "car_1_3": span(1, 3), "car_1_5": span(1, 5), "car_1_10": span(1, 10),
            "pre_5": span(-5, -1)}


def measure(events: pd.DataFrame, r_stock: pd.Series, r_bench: pd.Series) -> pd.DataFrame:
    """Each event's AR windows (events: columns `day` (a trading day in r_stock's index) and `surprise`)."""
    ar = (r_stock - r_bench.reindex(r_stock.index)).to_numpy(dtype=float)
    w = _windows(ar)
    pos = r_stock.index.get_indexer(pd.DatetimeIndex(events["day"]))
    out = events.assign(**{k: [w[k][p] if p >= 0 else np.nan for p in pos] for k in COLUMNS})
    return out.dropna(subset=list(COLUMNS)).reset_index(drop=True)


def shrink(rows: pd.DataFrame, col: str) -> pd.DataFrame:
    """Per-ticker means shrunk toward the pooled mean: weight = tau^2 / (tau^2 + s^2/n), tau^2 from the spread of
    the ticker means (method of moments, floored at 0). With one ticker, weight is 1."""
    g = rows.groupby("ticker")[col]
    per = pd.DataFrame({"n": g.size(), "mean": g.mean(), "sd": g.std(ddof=1)}).reset_index()
    pooled = float(rows[col].mean())
    se2 = (per["sd"].fillna(rows[col].std(ddof=1)) ** 2) / per["n"]
    tau2 = max(0.0, float(per["mean"].var(ddof=1)) - float(se2.mean())) if len(per) > 1 else math.inf
    per["weight"] = 1.0 if math.isinf(tau2) else (tau2 / (tau2 + se2)).fillna(0.0)
    per["shrunk"] = per["weight"] * per["mean"] + (1 - per["weight"]) * pooled
    per["t"] = per["mean"] / np.sqrt(se2)
    return per[["ticker", "n", "mean", "shrunk", "weight", "t"]]


def _event_rows(spec: EventSpec, closes: pd.DataFrame, events: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frame = closes[closes.index >= pd.Timestamp(spec.start)]
    r = frame.pct_change()
    days = frame.index
    rows = []
    for t in spec.tickers:
        if t not in r:
            continue
        bench = pd.Series(0.0, index=days) if t == spec.benchmark else r[spec.benchmark]
        if spec.event == "gap":
            ar = (r[t] - bench) * 100
            hit = ar <= -spec.gap_pct if spec.when == "down" else ar >= spec.gap_pct
            ev = pd.DataFrame({"day": days[hit.fillna(False).to_numpy()], "surprise": np.nan})
        else:
            src = events.get(t, events.get("*"))
            if src is None or src.empty:
                continue
            if spec.event == "earnings" and spec.when != "all":
                keep = src["surprise"] > 0 if spec.when == "beat" else src["surprise"] < 0
                src = src[keep.fillna(False)]
            ev = pd.DataFrame({"day": [reaction_day(pd.Timestamp(x), days) for x in src["time"]],
                               "surprise": src["surprise"].to_numpy() if "surprise" in src else np.nan})
            ev = ev.dropna(subset=["day"]).drop_duplicates("day")
        m = measure(ev, r[t], bench)
        if len(m):
            rows.append(m.assign(ticker=t))
    if not rows:
        return pd.DataFrame(columns=["day", "surprise", "ticker", *COLUMNS])
    return pd.concat(rows).sort_values(["day", "ticker"]).reset_index(drop=True)


def run_event_test(spec: EventSpec, closes: pd.DataFrame, events: dict[str, pd.DataFrame], *, variations: int,
                   seed: int, permutations: int = 1000) -> dict:
    """Did the window move the claimed way after these events, on the newest events, beyond random dates?"""
    rows = _event_rows(spec, closes, events)
    col, words = WINDOWS[spec.window]
    sign = 1.0 if spec.direction == "up" else -1.0
    n = len(rows)
    k = int(n * (1 - spec.unseen_fraction))
    bar = 0.05 / variations
    base = {"kind": "event", "variations": variations, "n_events": n,
            "split_date": str(rows["day"].iloc[k].date()) if n > k else None,
            "data_start": str(rows["day"].iloc[0].date()) if n else None,
            "data_end": str(closes.index[-1].date()) if len(closes) else None,
            "events": [{"date": str(d.date()), "ticker": t, "surprise": s, **{c: v[c] for c in COLUMNS}}
                       for d, t, s, v in zip(rows["day"], rows["ticker"], rows["surprise"],
                                             rows[list(COLUMNS)].to_dict("records"))][-2000:]}
    if n < MIN_EVENTS or n - k < MIN_UNSEEN_EVENTS:
        reason = (f"only {n} events ({n - k} unseen); at least {MIN_EVENTS} ({MIN_UNSEEN_EVENTS} unseen) are "
                  f"needed")
        return _clean({**base, "verdict": "NOT ENOUGH DATA", "headline": HEADLINES["nodata"], "reason": reason,
                       "claim": None, "shuffle": None, "t_test": None, "periods": None, "per_ticker": [],
                       "context": [], "curve": []})

    signed = sign * rows[col].to_numpy(dtype=float)

    def claim(x: np.ndarray) -> tuple[bool, float, str]:
        v = float(np.mean(x))
        return v > 0, v, (f"{sign * v:+.2f}% average move vs {spec.benchmark} over {words}, {len(x)} events")
    on_b, on_u = claim(signed[:k]), claim(signed[k:])

    # Random dates: the same window on non-event days of the unseen span, same count per ticker.
    rng = np.random.default_rng(seed)
    frame = closes[closes.index >= pd.Timestamp(spec.start)]
    r = frame.pct_change()
    unseen = rows.iloc[k:]
    lo = unseen["day"].min()
    pools = []
    for t, cnt in unseen["ticker"].value_counts().items():
        bench = 0.0 if t == spec.benchmark else r[spec.benchmark]
        w = _windows((r[t] - bench).to_numpy(dtype=float))[col]
        ok = (frame.index >= lo) & ~frame.index.isin(rows.loc[rows["ticker"] == t, "day"]) & ~np.isnan(w)
        pools.append((sign * w[ok], int(cnt)))
    perm = np.array([np.mean(np.concatenate([rng.choice(p, size=c, replace=True) for p, c in pools if len(p)]))
                     for _ in range(permutations)])
    p, beats = p_value(on_u[1], perm)
    verdict = verdict_of(on_u[0], p, bar)
    headline = (HEADLINES["pass"] if verdict == "PASS" else HEADLINES["chance"] if on_u[0]
                else HEADLINES["overfit"] if on_b[0] else HEADLINES["fail"])
    t = stats.ttest_1samp(signed[k:], 0.0, alternative="greater")
    chunks = np.array_split(signed, 5)
    per = shrink(rows.assign(x=rows[col]), "x").sort_values("n", ascending=False)
    return _clean({
        **base, "verdict": verdict, "headline": headline, "reason": None,
        "claim": {"built": {"holds": bool(on_b[0]), "value": on_b[1], "label": on_b[2]},
                  "unseen": {"holds": bool(on_u[0]), "value": on_u[1], "label": on_u[2]}},
        "shuffle": {"beats_pct": beats, "p": p, "bar": bar, "permutations": permutations, "seed": seed,
                    "method": "random dates"},
        "t_test": {"mean_daily_diff": float(np.mean(signed[k:])), "t": float(t.statistic), "p": float(t.pvalue)},
        "periods": {"held": int(sum(float(np.mean(c)) > 0 for c in chunks if len(c))), "of": 5},
        "per_ticker": per.to_dict("records"), "context": [], "curve": [],
    })
