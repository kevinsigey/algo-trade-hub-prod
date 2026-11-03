"""The weekly critic (self-improving loop piece 1, Kevin, 2026-11-03).

For every live or tracking idea, the critic compares three things that already
exist -- the idea's live record since activation, its latest backtest verdict,
and its original preregistered claim -- and writes one blunt recommendation:
PAUSE, HOLD or WATCH, with the reasons stated. It only recommends; pausing an
idea stays Kevin's call or the existing kill paths'.

The live number is the claim's OWN statistic recomputed on the live record
(engine._claim over the shadow days), so the degradation is always in the
claim's own units -- pts/yr vs benchmark for beats_benchmark, % per down day
for ballast -- never an invented metric. The shadow record is the strategy's
live record (real days, real prices, the confirmed rules); the paper block
alongside it is the execution record (what the broker actually filled), kept
separate on purpose: a strategy can hold live while its fills leak, and the
two facts must not be averaged into one number.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tradehub.workshop import engine

MIN_DAYS = 10  # below this the only honest verdict is "too little record"
JUDGE_DAYS = 60  # below this an annualized live number is too noisy to pause on
PAUSE_RATIO = 0.5
WATCH_RATIO = 0.75
CLUSTER_SHARE = 0.6


def _num(value: float | None) -> float | None:
    """JSON cannot carry NaN or inf, and a stored critique must never smuggle
    one in: non-finite numbers become None (absent), never a fake zero."""
    return value if value is not None and math.isfinite(value) else None


def regime_tags(spy: pd.Series) -> dict[str, dict]:
    """Per-day market regime from SPY closes alone: trend = close vs its 50-day
    average, vol = trailing 20-day realized vol (annualized %). Days without the
    history are 'unknown' -- stated, never backfilled with a guess."""
    closes = spy.dropna()
    ma50 = closes.rolling(50).mean()
    vol = closes.pct_change().rolling(20).std() * math.sqrt(252) * 100
    out: dict[str, dict] = {}
    for day, close in closes.items():
        trend = "unknown"
        if pd.notna(ma50.loc[day]):
            trend = "up" if close >= ma50.loc[day] else "down"
        v = vol.loc[day]
        band = "unknown" if pd.isna(v) else ("low" if v < 12 else "normal" if v <= 20 else "high")
        label = (f"{'uptrend' if trend == 'up' else 'downtrend' if trend == 'down' else 'unknown trend'}"
                 f" · {band} vol")
        out[str(day.date())] = {"trend": trend, "vol": band, "label": label}
    return out


def live_claim(kind: str, rows: list[dict]) -> tuple[bool, float, str]:
    """The claim statistic on the live shadow record: engine._claim over the
    same arrays the backtest judged, so live and backtest are one ruler."""
    r = np.array([row["ret"] for row in rows], dtype=float)
    b = np.array([row["bench"] for row in rows], dtype=float)
    s = np.array([row["spy"] for row in rows], dtype=float)
    mask = np.array([bool(row["on"]) for row in rows], dtype=bool)
    return engine._claim(kind, r, b, s, mask)


def recommend(*, days: int, live_value: float | None, backtest_value: float | None) -> tuple[str, list[str]]:
    """Blunt and deterministic: the bands are the whole policy. A claim whose
    live statistic is not yet testable (NaN -- e.g. ballast before any SPY down
    day) is a WATCH with that reason, never a silent zero."""
    if days < MIN_DAYS:
        return "WATCH", [f"only {days} live days since activation -- too little record to judge"]
    if live_value is None or not math.isfinite(live_value):
        return "WATCH", ["the claim has not been testable live yet (its live statistic is undefined)"]
    if backtest_value is not None and math.isfinite(backtest_value) and backtest_value > 0:
        if live_value <= 0 or live_value / backtest_value < PAUSE_RATIO:
            reason = (f"the claim is not holding live: {live_value:+.1f} against "
                      f"{backtest_value:+.1f} backtested, in the claim's own units"
                      if live_value <= 0 else
                      f"live is running at {live_value / backtest_value:.0%} of the backtested "
                      f"claim ({live_value:+.1f} vs {backtest_value:+.1f})")
            if days < JUDGE_DAYS:
                # Annualizing a few weeks of live days explodes the number;
                # the direction is worth a watch, not a pause.
                return "WATCH", [reason + f" -- but only {days} live days, too early "
                                          "to pause on an annualized number"]
            return "PAUSE", [reason]
        ratio = live_value / backtest_value
        if ratio < WATCH_RATIO:
            return "WATCH", [f"live is running at {ratio:.0%} of the backtested claim "
                             f"({live_value:+.1f} vs {backtest_value:+.1f})"]
        return "HOLD", [f"live is running at {ratio:.0%} of the backtested claim "
                        f"({live_value:+.1f} vs {backtest_value:+.1f})"]
    if live_value > 0:
        return "HOLD", ["the live record is positive; the backtested claim value "
                        "gives no positive bar to ratio against"]
    return "WATCH", ["the live record is not positive, and the backtested claim "
                     "value gives no positive bar to ratio against"]


def _spans(rows: list[dict]) -> list[dict]:
    """Contiguous in-market spans: one span is one entry. Excess is the span's
    compounded idea return over its compounded benchmark, in %."""
    spans, current = [], None
    for row in rows:
        if row["on"]:
            if current is None:
                current = {"start": row["day"], "days": 0, "idea": 1.0, "bench": 1.0}
            current["days"] += 1
            current["idea"] *= 1 + row["ret"]
            current["bench"] *= 1 + row["bench"]
        elif current is not None:
            spans.append(current)
            current = None
    if current is not None:
        spans.append(current)
    for span in spans:
        span["excess_pct"] = (span.pop("idea") / span.pop("bench") - 1) * 100
    return spans


def critique_payload(*, idea_id: int, book: str, at: str, kind: str, backtest: dict,
                     rows: list[dict], regimes: dict[str, dict], paper: dict | None,
                     prior_dominant: str | None) -> dict:
    """One critique: the comparison, the conditions, the flags, the verdict."""
    days = len(rows)
    if days:
        holds, live_value, live_label = live_claim(kind, rows)
    else:
        holds, live_value, live_label = False, None, "no live days yet"
    backtest_value = backtest.get("value")
    degradation = (live_value - backtest_value
                   if live_value is not None and backtest_value is not None
                   and math.isfinite(live_value) and math.isfinite(backtest_value) else None)

    spans = _spans(rows)
    losing = [s for s in spans if s["excess_pct"] < 0]
    counts: dict[str, int] = {}
    for span in losing:
        label = regimes.get(span["start"], {}).get("label", "unknown regime")
        counts[label] = counts.get(label, 0) + 1
    dominant, share = None, 0.0
    if counts:
        dominant = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        share = counts[dominant] / len(losing)
    flags: list[str] = []
    if len(losing) >= 2 and share >= CLUSTER_SHARE:
        flags.append(f"losses cluster when {dominant} "
                     f"({counts[dominant]} of {len(losing)} losing entries)")
    if dominant is not None and dominant == prior_dominant and losing and share >= CLUSTER_SHARE:
        flags.append(f"the same losing conditions as the last critique ({dominant}) "
                     "-- a repeated pattern, not new information")

    rec, reasons = recommend(days=days, live_value=live_value, backtest_value=backtest_value)
    return {
        "idea_id": idea_id, "book": book, "at": at,
        "claim": {"kind": kind, "backtest_value": _num(backtest_value),
                  "backtest_label": backtest.get("label"), "backtest_holds": backtest.get("holds"),
                  "verdict": backtest.get("verdict"), "p": _num(backtest.get("p")),
                  "walk_forward": backtest.get("walk_forward")},
        "live": {"days": days,
                 "span": [rows[0]["day"], rows[-1]["day"]] if days else None,
                 "value": _num(live_value), "label": live_label, "holds": holds},
        "degradation": degradation,
        "conditions": {"entries": len(spans), "losing_entries": len(losing),
                       "dominant": dominant, "dominant_share": round(share, 2) if dominant else None},
        "paper": paper,
        "flags": flags,
        "recommendation": rec, "reasons": reasons,
    }
