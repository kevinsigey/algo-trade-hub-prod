"""Step A: where do the 15-minute models work (plan 2026-11-12, Step A).

Read-only study over the two offset records, ALWAYS side by side and
never pooled across sources:

- forward: `fifteen_window_offsets`, the live record (Nov 6 onward);
- replay: the A0 history replay with the 1c haircut already inside
  `side_cost` / `pnl` (Claude's ruling on #517: replay fills at the
  candle ask + 1c and is never used alone to rank a rule).

One row per (series, window, entry minute), settled only. Every feature
is computed from data available at the entry minute:

- trend uses only windows that closed BEFORE this window opened;
- the event feature reads the published schedule (events_calendar),
  which is public before the window opens;
- move-so-far and the cross-market moves use the underlying price at
  the entry minute against the same window's earliest-offset price --
  replay rows only, because the forward record stores no prices. The
  replay rows' `move_to_60m_bps` / `price_at_60m` fields are NOT used:
  they are measured against a price 60 minutes after the window opens,
  which is look-ahead for an entry inside the window.

Output per cell: net cents per trade after the fee (the rows' `pnl` is
already fee-netted), n, and a day-clustered low95 (the repo's
`fifteen_volregime.clustered_low95`, clusters = (series, ET day)).
Cells under 30 trades are blanked. The whole report is labelled
"in-sample, for choosing what to test".

Not in this study, by data rather than by choice (named in the PR):
sigma regime (sigma_1m is not stored on either record; it would need a
tape re-run), the forward order-book features (they need the tick tape
joined per window -- the runner attaches `fillable` from it when it can,
and the book's own cells are a follow-up), gas weather history (the
degree-days snapshots are not retained), and daily cross-asset series
(DXY / TIPS / USDCNH -- the in-study cross-market features use the other
five series from the same record instead, per the model-v2 plan).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.fifteen_volregime import clustered_low95
from tradehub.research.events_calendar import event_feature

ET = ZoneInfo("America/New_York")
MIN_CELL = 30
LABEL = "in-sample, for choosing what to test"
SAMPLE_NOTE = ("A 4c paired difference needs roughly 1,000-1,500 matched "
               "windows over 15-20 or more trading days per series.")

SERIES = ("KXNATGAS15M", "KXWTI15M", "KXBRENT15M",
          "KXGOLD15M", "KXSILVER15M", "KXCOPPER15M")
OILS = ("KXWTI15M", "KXBRENT15M")


def parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _et_day(ts: datetime) -> str:
    return ts.astimezone(ET).date().isoformat()


def _sign(x: float | None) -> str | None:
    if x is None:
        return None
    return "up" if x > 0 else "down" if x < 0 else "flat"


def edge_bucket(edge: float | None) -> str | None:
    if edge is None:
        return None
    if edge < 0.10:
        return "<10"
    if edge < 0.15:
        return "10-15"
    if edge < 0.20:
        return "15-20"
    return "20+"


def hour_band(entry: datetime) -> str:
    h = entry.astimezone(ET).hour
    return "00-05" if h < 6 else "06-11" if h < 12 else "12-17" if h < 18 else "18-23"


def enrich(rows: list[dict], source: str) -> list[dict]:
    """Traded rows of one source with their Step A features attached.
    `rows` is the source's full offset record (untraded rows included:
    they carry the window outcomes the trend features read)."""
    rows = [r for r in rows if r.get("outcome") is not None]
    outcome_by_window: dict[tuple[str, datetime], int] = {}
    open_price: dict[tuple[str, str], tuple[int, float]] = {}
    price_at: dict[tuple[str, datetime, int], float] = {}
    for r in rows:
        close = parse_ts(r["close_time"])
        outcome_by_window[(r["series"], close)] = int(r["outcome"])
        price = r.get("price")
        if price is not None:
            key = (r["series"], r["target"])
            offset = int(r["offset_min"])
            if key not in open_price or offset < open_price[key][0]:
                open_price[key] = (offset, float(price))
            price_at[(r["series"], close, offset)] = float(price)

    def move_bps(series: str, target: str, close: datetime, offset: int) -> float | None:
        price = price_at.get((series, close, offset))
        open_ = open_price.get((series, target))
        if price is None or not open_ or not open_[1]:
            return None
        return (price / open_[1] - 1.0) * 1e4

    trades = []
    for r in rows:
        if r.get("side") is None or r.get("pnl") is None:
            continue
        series = r["series"]
        close = parse_ts(r["close_time"])
        offset = int(r["offset_min"])
        entry = close - timedelta(minutes=15) + timedelta(minutes=offset)
        prev = [outcome_by_window.get((series, close - timedelta(minutes=15 * k)))
                for k in (1, 2, 3)]
        prev1 = prev[0]
        agrees = None
        if prev1 is not None:
            bet_up = r["side"] == "yes"
            agrees = "agrees" if bet_up == (prev1 == 1) else "against"
        trend3 = None
        if all(p is not None for p in prev):
            net = sum(1 if p == 1 else -1 for p in prev)
            trend3 = "up" if net > 0 else "down" if net < 0 else "flat"
        own_move = move_bps(series, r["target"], close, offset)
        cross = None
        if own_move is not None:
            others = [move_bps(s, _target_at(rows, s, close), close, offset)
                      for s in SERIES if s != series]
            known = [o for o in others if o is not None]
            if known:
                cross = sum(known) / len(known)
        spread = None
        if series in OILS and own_move is not None:
            other = OILS[1] if series == OILS[0] else OILS[0]
            other_move = move_bps(other, _target_at(rows, other, close), close, offset)
            if other_move is not None:
                brent = own_move if series == "KXBRENT15M" else other_move
                wti = own_move if series == "KXWTI15M" else other_move
                spread = brent - wti
        ev = event_feature(series, entry)
        cost = r.get("side_cost")
        trades.append({
            "series": series, "target": r["target"], "source": source,
            "day": _et_day(close), "minute": offset,
            "pnl_cents": float(r["pnl"]) * 100.0,
            "fillable": r.get("fillable"),
            "edge_bucket": edge_bucket(r.get("edge_net")),
            "prev_window": None if prev1 is None else ("up" if prev1 == 1 else "down"),
            "side_agrees_last": agrees,
            "trend3": trend3,
            "move_so_far": _sign(own_move),
            "cross_move": _sign(cross),
            "spread_move": _sign(spread),
            "price_level": None if cost is None else
                           ("near_50" if 0.40 <= float(cost) <= 0.60 else "extreme"),
            "hour_band": hour_band(entry),
            "event_kind": ev["event_kind"],
        })
    return trades


_target_cache: dict[int, dict[tuple[str, datetime], str]] = {}


def _target_at(rows: list[dict], series: str, close: datetime) -> str | None:
    """The target (window id) of `series` closing at `close`, from the
    record itself -- windows are identified by their close time."""
    key = id(rows)
    index = _target_cache.get(key)
    if index is None:
        index = {}
        for r in rows:
            index[(r["series"], parse_ts(r["close_time"]))] = r["target"]
        _target_cache[key] = index
    return index.get((series, close))


def cell(trades: list[dict]) -> dict | None:
    """One report cell, blanked under MIN_CELL trades."""
    if len(trades) < MIN_CELL:
        return None
    items = [((t["series"], t["day"]), t["pnl_cents"]) for t in trades]
    low = clustered_low95(items)
    return {"n": len(trades),
            "cents": round(sum(t["pnl_cents"] for t in trades) / len(trades), 2),
            "low95": None if low is None else round(low, 2)}


def _by_source_cells(trades: list[dict]) -> dict:
    """{series|'POOLED': {source: cell}} for one bucket of trades."""
    out = {}
    for series in (*SERIES, "POOLED"):
        per = {}
        for source in ("forward", "replay"):
            sel = [t for t in trades
                   if t["source"] == source and (series == "POOLED" or t["series"] == series)]
            per[source] = cell(sel)
        out[series] = per
    return out


FEATURES: list[tuple[str, list]] = [
    ("minute", list(range(0, 15))),
    ("edge_bucket", ["<10", "10-15", "15-20", "20+"]),
    ("prev_window", ["up", "down"]),
    ("side_agrees_last", ["agrees", "against"]),
    ("trend3", ["up", "flat", "down"]),
    ("move_so_far", ["up", "flat", "down"]),
    ("cross_move", ["up", "flat", "down"]),
    ("spread_move", ["up", "flat", "down"]),
    ("price_level", ["near_50", "extreme"]),
    ("hour_band", ["00-05", "06-11", "12-17", "18-23"]),
    ("event_kind", ["none", "api_inventories", "eia_petroleum", "eia_gas_storage",
                    "cpi", "jobs", "fomc_decision", "fomc_minutes"]),
]


def feature_table(trades: list[dict]) -> dict:
    out = {}
    for name, buckets in FEATURES:
        rows = []
        for bucket in buckets:
            sel = [t for t in trades if t.get(name) == bucket]
            if not sel:
                continue
            rows.append({"bucket": str(bucket), "cells": _by_source_cells(sel)})
        if rows:
            out[name] = rows
    return out


def minute_edge_table(trades: list[dict]) -> list[dict]:
    rows = []
    for minute in range(0, 15):
        for bucket in ("<10", "10-15", "15-20", "20+"):
            sel = [t for t in trades if t["minute"] == minute and t["edge_bucket"] == bucket]
            if sel:
                rows.append({"minute": minute, "edge_bucket": bucket,
                             "cells": _by_source_cells(sel)})
    return rows


def paired_table(trades: list[dict], *, base_minute: int = 5) -> list[dict]:
    """Per-window pnl difference, minute M minus minute `base_minute`,
    over windows where BOTH minutes trade (same source, series, window)."""
    by_window: dict[tuple[str, str, str], dict[int, dict]] = defaultdict(dict)
    for t in trades:
        by_window[(t["source"], t["series"], t["target"])][t["minute"]] = t
    out = []
    for minute in range(0, 15):
        if minute == base_minute:
            continue
        for series in (*SERIES, "POOLED"):
            for source in ("forward", "replay"):
                diffs = []
                for (src, ser, _tgt), minutes in by_window.items():
                    if src != source or (series != "POOLED" and ser != series):
                        continue
                    if minute in minutes and base_minute in minutes:
                        a, b = minutes[minute], minutes[base_minute]
                        diffs.append(((ser, a["day"]), a["pnl_cents"] - b["pnl_cents"]))
                if len(diffs) < MIN_CELL:
                    continue
                low = clustered_low95(diffs)
                out.append({"minute": minute, "series": series, "source": source,
                            "n_windows": len(diffs),
                            "cents": round(sum(d for _k, d in diffs) / len(diffs), 2),
                            "low95": None if low is None else round(low, 2)})
    return out


def data_so_far(rows_by_source: dict[str, list[dict]]) -> list[dict]:
    out = []
    for source, rows in rows_by_source.items():
        settled = [r for r in rows if r.get("outcome") is not None]
        for series in SERIES:
            sel = [r for r in settled if r["series"] == series]
            if not sel:
                continue
            windows = {r["target"] for r in sel}
            days = {_et_day(parse_ts(r["close_time"])) for r in sel}
            closes = sorted(parse_ts(r["close_time"]) for r in sel)
            out.append({"source": source, "series": series,
                        "settled_windows": len(windows), "days": len(days),
                        "trades": sum(1 for r in sel if r.get("side") is not None),
                        "first_close": closes[0].date().isoformat(),
                        "last_close": closes[-1].date().isoformat()})
    return out


def build_report(forward_rows: list[dict], replay_rows: list[dict]) -> dict:
    """The full Step A report. Sources are enriched separately and only
    ever shown side by side."""
    trades = enrich(forward_rows, "forward") + enrich(replay_rows, "replay")
    views = {}
    for view, sel in (("all", trades),
                      ("fillable", [t for t in trades if t.get("fillable") is True])):
        views[view] = {"features": feature_table(sel),
                       "minute_edge": minute_edge_table(sel),
                       "paired_vs_5": paired_table(sel)}
    return {"label": LABEL, "min_cell": MIN_CELL, "sample_note": SAMPLE_NOTE,
            "data_so_far": data_so_far({"forward": forward_rows, "replay": replay_rows}),
            "views": views}
