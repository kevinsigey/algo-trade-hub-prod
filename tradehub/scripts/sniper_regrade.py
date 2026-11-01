"""One-time re-grade of the retired crypto sniper's archived signals (phase-3 §5).

The sniper worker (legacy market_sentiment_tool/backend/orchestrator.py) wrote
signal_events from 2026-04-08 until it stopped on 2026-06-02, against the
Kalshi demo API; every signal's execution was skipped or blocked. Its live
scorecard (/api/shadow-performance) only ever looks back 24-168 hours, so the
archive was never graded as a whole. This script grades it ONCE, with the
existing evaluator (tradehub.scripts.shadow_performance.evaluate_recent_signals
and its thresholds, unchanged), and writes a dated snapshot that the Crypto
research page serves as a closed record. It is never re-run as a live feed;
re-running it overwrites the snapshot with a new graded_on date.

The one substitution: the evaluator's price fetch only reaches Kraken's /
Coinbase's recent-candle windows, which no longer cover Apr-May 2026. This
script pages the SAME two venues' historical candles for the archive window
and hands them to the evaluator in the evaluator's own frame shape. The
grading rule -- probability vs the next hour's spot direction, side from the
model's own thresholds -- is the evaluator's, untouched.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from market_sentiment_tool.backend.runtime_bootstrap import load_canonical_env
from tradehub.core.crypto_data import (
    COINBASE_HEADERS,
    COINBASE_PRODUCTS,
    COINBASE_URL,
    KRAKEN_PAIRS,
    KRAKEN_URL,
    parse_coinbase_candles,
    parse_kraken_ohlc,
)
from tradehub.scripts import shadow_performance as sp

WINDOW_START = datetime(2026, 4, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 3, tzinfo=timezone.utc)
CLOSES_START = datetime(2026, 4, 8, tzinfo=timezone.utc)
CLOSES_END = datetime(2026, 6, 2, 6, tzinfo=timezone.utc)
GRADED_STATUSES = ("signal_detected", "inference_heartbeat")
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "sniper_verdict.json"


def fetch_archived_rows() -> list[dict[str, Any]]:
    """Every signal_events row in the archive window, paged (the evaluator's
    fetch caps at 500 recent rows; the archive is ~84k)."""
    supa = sp._load_supabase_client()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = (
            supa.table("signal_events")
            .select("asset,created_at,source_market_ticker,desired_side,status,model_probability_yes,payload")
            .eq("domain", "crypto")
            .gte("created_at", WINDOW_START.isoformat())
            .lt("created_at", WINDOW_END.isoformat())
            .order("created_at")
            .range(offset, offset + 999)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def grading_population(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The evaluator's own population rule (fetch_recent_signal_events):
    graded statuses, BTC/ETH, a model probability present, manual tests out."""
    out = []
    for row in rows:
        if row.get("status") not in GRADED_STATUSES:
            continue
        if str(row.get("asset") or "").upper() not in {"BTC", "ETH"}:
            continue
        if row.get("model_probability_yes") is None:
            continue
        if sp._is_manual_test(row.get("payload") or {}):
            continue
        out.append(row)
    return out


def _coinbase_history(asset: str) -> pd.DataFrame:
    frames = []
    start = CLOSES_START
    while start < CLOSES_END:
        end = min(start + timedelta(hours=299), CLOSES_END)
        resp = requests.get(
            COINBASE_URL.format(product=COINBASE_PRODUCTS[asset]),
            params={"granularity": 3600, "start": start.isoformat(), "end": end.isoformat()},
            headers=COINBASE_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list) and payload:
            frames.append(parse_coinbase_candles(payload, product=COINBASE_PRODUCTS[asset]))
        start = end
    if not frames:
        raise RuntimeError(f"Coinbase returned no candles for {asset}")
    return pd.concat(frames).sort_index().loc[lambda df: ~df.index.duplicated(keep="first")]


def _kraken_history(asset: str) -> pd.DataFrame:
    pair = KRAKEN_PAIRS[asset]
    frames = []
    since = int(CLOSES_START.timestamp())
    end_ts = int(CLOSES_END.timestamp())
    while since < end_ts:
        resp = requests.get(
            KRAKEN_URL,
            params={"pair": pair, "interval": 60, "since": since},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            raise RuntimeError(f"Kraken error: {payload['error']}")
        frame = parse_kraken_ohlc(payload, pair=pair, drop_last=False)
        if frame.empty:
            break
        frames.append(frame)
        last = int(frame.index.max().timestamp())
        if last <= since:
            break
        since = last + 3600
    if not frames:
        raise RuntimeError(f"Kraken returned no candles for {asset}")
    return pd.concat(frames).sort_index().loc[lambda df: ~df.index.duplicated(keep="first")]


def fetch_historical_closes(asset: str) -> tuple[pd.DataFrame, str]:
    """Historical hourly closes for the archive window. Kraken first (the
    evaluator's primary venue), Coinbase as the fallback -- same order as
    tradehub.core.crypto_data.fetch_hourly_closes. A frame only counts if it
    actually covers the window: Kraken's OHLC is a rolling ~720-candle window
    that silently ignores a `since` older than the window (verified live
    2026-11-01: an Apr-2026 `since` returned Oct-Nov 2026 candles), so an
    uncovered frame falls through to Coinbase instead of grading nothing."""
    need_last = CLOSES_END - timedelta(hours=1)
    for name, fetch in (("kraken", _kraken_history), ("coinbase", _coinbase_history)):
        try:
            frame = fetch(asset)
        except Exception:
            continue
        if not frame.empty and frame.index.min() <= CLOSES_START and frame.index.max() >= need_last:
            return frame, name
    raise RuntimeError(f"No venue could serve {asset} hourly closes for {CLOSES_START}..{CLOSES_END}")


def build_verdict(
    *,
    by_status: dict[str, int],
    first_row: str | None,
    last_row: str | None,
    population: list[dict[str, Any]],
    evaluated: list[sp.EvaluatedSignal],
    consideration: dict[str, int],
    thresholds: dict[str, sp.ThresholdConfig],
    price_source: str,
    graded_on: date,
) -> dict[str, Any]:
    """The closed-record snapshot, assembled from the evaluator's outputs the
    same way build_shadow_report assembles its summary."""
    archived_total = sum(by_status.values())
    if evaluated:
        outcomes = np.array([i.realized_yes for i in evaluated], dtype=float)
        probs = np.array([i.probability_yes for i in evaluated], dtype=float)
        overall = {
            "count": len(evaluated),
            "hit_rate": float(np.mean([i.correct for i in evaluated])),
            "virtual_pnl_pct": float(np.sum([i.virtual_return_pct for i in evaluated])),
            "brier_score": float(np.mean((probs - outcomes) ** 2)),
        }
    else:
        overall = {"count": 0, "hit_rate": None, "virtual_pnl_pct": 0.0, "brier_score": None}
    buckets: dict[str, dict[str, float | int]] = {}
    for bucket in sorted({sp._probability_bucket(i.probability_yes) for i in evaluated}):
        items = [i for i in evaluated if sp._probability_bucket(i.probability_yes) == bucket]
        buckets[bucket] = {"count": len(items), "hit_rate": float(np.mean([i.correct for i in items]))}
    considered = int(consideration["considered_count"])
    dead = int(consideration["dead_zone_count"])
    total = int(consideration["evaluated_count"])
    return {
        "record": "sniper_closed_record",
        "graded_on": graded_on.isoformat(),
        "worker": {
            "first_row": first_row,
            "last_row": last_row,
            "stopped": "2026-06-02",
            "venue": "Kalshi demo API",
        },
        "population": {
            "archived_rows": archived_total,
            "by_status": by_status,
            "grading_population": len(population),
            "rows_with_probability": total,
            "considered": considered,
            "dead_zone": dead,
            "dead_zone_share": (dead / total) if total else None,
            "graded": len(evaluated),
        },
        "overall": overall,
        "by_asset": {asset: sp._asset_summary(evaluated, asset) for asset in ("BTC", "ETH")},
        "buckets": buckets,
        "thresholds": {a: {"yes": t.yes, "no": t.no} for a, t in thresholds.items()},
        "price_source": price_source,
        "method": (
            "Graded once with the hub's existing shadow evaluator: each archived row's model "
            "probability against the next hour's spot direction (hourly closes), the trade side "
            "taken from the model's own probability thresholds. Rows sharing an hour share its "
            "outcome; the grade is the evaluator's row-level grade, not a per-event grade."
        ),
    }


def main() -> int:
    load_canonical_env(__file__)
    parser = argparse.ArgumentParser(description="Re-grade the retired sniper's archived signals, once.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--rows-file", type=Path, default=None,
        help="Read exported rows ({\"rows\": [...], \"by_status\": {...}}) instead of querying "
             "Supabase -- the route used for the 2026-11-01 grade, where the archive's payload "
             "column made paged PostgREST reads through the proxy too slow. The export carries "
             "the evaluator's manual-test flag precomputed from the payload.",
    )
    args = parser.parse_args()

    if args.rows_file is not None:
        blob = json.loads(args.rows_file.read_text())
        archived = blob["rows"]
        by_status = {str(k): int(v) for k, v in blob["by_status"].items()}
    else:
        archived = fetch_archived_rows()
        by_status = {}
        for row in archived:
            by_status[str(row.get("status"))] = by_status.get(str(row.get("status")), 0) + 1
    stamps = sorted(str(r["created_at"]) for r in archived)
    population = grading_population(archived)
    frames: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    for asset in ("BTC", "ETH"):
        frames[asset], sources[asset] = fetch_historical_closes(asset)
    price_source = ", ".join(f"{a}: {s}" for a, s in sorted(sources.items()))

    current_hour = sp._current_hour_utc()

    def _historical(asset: str, *, start: pd.Timestamp, end: pd.Timestamp):
        return frames[asset][frames[asset].index < current_hour], sources[asset]

    original = sp._fetch_crypto_hourly_closes
    sp._fetch_crypto_hourly_closes = _historical
    try:
        thresholds = sp.default_thresholds()
        consideration = sp._considered_signal_count(population, thresholds)
        evaluated = sp.evaluate_recent_signals(population, thresholds=thresholds)
    finally:
        sp._fetch_crypto_hourly_closes = original

    verdict = build_verdict(
        by_status=by_status,
        first_row=stamps[0] if stamps else None,
        last_row=stamps[-1] if stamps else None,
        population=population,
        evaluated=evaluated,
        consideration=consideration,
        thresholds=thresholds,
        price_source=price_source,
        graded_on=datetime.now(timezone.utc).date(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(verdict, indent=2) + "\n")
    print(f"wrote {args.out}: graded {verdict['population']['graded']} of "
          f"{verdict['population']['grading_population']} rows; "
          f"hit rate {verdict['overall']['hit_rate']}, Brier {verdict['overall']['brier_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
