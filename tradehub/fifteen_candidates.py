"""The fifteen-minute v4 shadow family (preregistered 2026-11-12,
revised 2026-11-13 before PREREG_AT on Claude's forward-data analysis
and Kevin's per-commodity call; PREREG_AT 2026-11-14T00:00:00Z -- see
docs/superpowers/specs/2026-11-14-fifteen-v4-shadow-family-prereg.md).

Four candidates, each a fixed set of per-series dials (entry minutes x
edge bar) over the live gate's own offset track
(fifteen_window_offsets). Scored read-only as the track accrues. No
new tables, no writes except the gate_switch alerts the scorer emits
on state transitions (tradehub/gate_alerts.py). The live rule is never
touched.

Semantics (frozen in the prereg): one trade per window -- the earliest
row inside the candidate's entry minutes for that series whose row the
dial accepts. The paired baseline is the live gate's own decision: the
offset_min == 5 row when it is a settled trade, else no trade. Fresh
windows are window_open >= PREREG_AT, the blend's convention. Late
dials (entry minutes 11-13) carry the fillability rule: a trade counts
only when the minute tape's ask size for its side at that minute is at
least the demo's 1%-of-$500 size for that price; an unmeasured minute
is fill-unknown and the window is excluded from scoring, never assumed
filled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradehub.engines.fifteen_min import WINDOW_MINUTES
from tradehub.fifteen_volregime import clustered_low95

PREREG_AT = datetime(2026, 11, 14, tzinfo=UTC)
PROMOTION_MIN_TRADES = 100
STOP_DAYS = 60
STOP_TRADES = 300
LIVE_MINUTE = 5
# The fillability bar, frozen at the demo's terms when the family was
# preregistered: kalshi_demo.size_contracts(STARTING_BALANCE_USD,
# price, 0.01) -- 1% of the $500 starting balance, minimum 1 contract.
DEMO_START_BALANCE_USD = 500.0
DEMO_BUDGET_PCT = 0.01

NATGAS = "KXNATGAS15M"
WTI = "KXWTI15M"
BRENT = "KXBRENT15M"
GOLD = "KXGOLD15M"
SILVER = "KXSILVER15M"
COPPER = "KXCOPPER15M"
_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Dial:
    """One series' fixed dial for a candidate: entry minutes
    (inclusive), the fee-netted edge bar on top of the live 10c floor
    the rows already carry, and whether the late-minute fillability
    rule binds this dial."""
    minutes: tuple[int, int]
    min_edge: float
    fill_checked: bool = False


@dataclass(frozen=True)
class Candidate:
    default: Dial | None
    per_series: dict[str, Dial | None]

    def dial_for(self, series: str) -> Dial | None:
        return self.per_series.get(series, self.default)


_LIVE = Dial((LIVE_MINUTE, LIVE_MINUTE), 0.10)
_LATE = Dial((11, 13), 0.10, fill_checked=True)

CANDIDATES: dict[str, Candidate] = {
    # The live gate's minute at a 20c bar, every series.
    "v4-edge20-shadow": Candidate(
        default=Dial((LIVE_MINUTE, LIVE_MINUTE), 0.20), per_series={}),
    # The live gate's minute and bar with gold excluded (gold lost at
    # every timing on the forward record).
    "v4-no-gold-shadow": Candidate(
        default=_LIVE, per_series={GOLD: None}),
    # Minutes 11-13 at the live bar, every series, fill-checked.
    "v4-late-window-shadow": Candidate(default=_LATE, per_series={}),
    # Each series at its own best forward cell (Kevin's call,
    # 2026-11-13): gas keeps the live minute (late timing hurts it),
    # copper late needs the 20c bar, gold does not trade.
    "v4-per-commodity-shadow": Candidate(
        default=None,
        per_series={
            NATGAS: _LIVE,
            WTI: _LATE,
            BRENT: _LATE,
            SILVER: _LATE,
            COPPER: Dial((11, 13), 0.20, fill_checked=True),
            GOLD: None,
        }),
}


def criterion_met(n: int, low95: float | None, paired_low95: float | None) -> bool:
    """The frozen promotion criterion, the house shape (the oil shadow's
    fifteen_shadow.criterion_met is the same test at its own n=150):
    every leg must hold, and an unmeasurable leg never passes."""
    return (n >= PROMOTION_MIN_TRADES and low95 is not None and low95 > 0
            and paired_low95 is not None and paired_low95 > 0)


def _settled_trade(row: dict) -> bool:
    return (row.get("side") is not None and row.get("outcome") is not None
            and row.get("pnl") is not None)


def _close_dt(row: dict) -> datetime:
    return datetime.fromisoformat(str(row["close_time"]).replace("Z", "+00:00"))


def window_open(row: dict) -> datetime:
    return _close_dt(row) - timedelta(minutes=WINDOW_MINUTES)


def candidate_trade(rows: list[dict], candidate: Candidate,
                    series: str) -> dict | None:
    """The window's one trade under a candidate: the earliest settled
    trade row inside the series' entry minutes clearing its edge bar,
    or None when the dial never trades this series/window."""
    dial = candidate.dial_for(series)
    if dial is None:
        return None
    lo, hi = dial.minutes
    for row in sorted(rows, key=lambda r: int(r["offset_min"])):
        k = int(row["offset_min"])
        if lo <= k <= hi and _settled_trade(row) \
                and float(row["edge_net"]) >= dial.min_edge:
            return row
    return None


def live_trade(rows: list[dict]) -> dict | None:
    """The paired baseline: the live gate's own decision on this grid --
    the offset_min == LIVE_MINUTE row when it is a settled trade, else
    no trade. (Not the earliest trade anywhere: the gate freezes at
    minute 5, so an earlier row is a trade it never took.)"""
    for row in rows:
        if int(row["offset_min"]) == LIVE_MINUTE and _settled_trade(row):
            return row
    return None


def demo_size(cost: float) -> int:
    """Contracts in the demo's 1% order at `cost`, at the family's
    frozen starting terms (see DEMO_START_BALANCE_USD)."""
    return max(1, math.floor(DEMO_START_BALANCE_USD * DEMO_BUDGET_PCT / cost))


def _et_day(row: dict) -> str:
    return _close_dt(row).astimezone(_ET).date().isoformat()


def evaluate(rows: list[dict], version: str, *, now: datetime,
             fills: dict | None = None) -> dict[str, Any]:
    """Score one candidate over the forward offset rows. `rows` is the
    raw fifteen_window_offsets read; only settled windows with
    window_open >= PREREG_AT count. `fills` maps
    (series, close_time_iso, offset_min) -> {"yes": size|None,
    "no": size|None} from the minute tape; a fill-checked trade with
    no measurement is fill-unknown and its window leaves scoring
    entirely, while a measured size below the demo's need means the
    candidate simply does not trade that window. Pure: no I/O."""
    candidate = CANDIDATES[version]
    windows: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if window_open(row) < PREREG_AT:
            continue
        windows.setdefault((row["series"], row["target"]), []).append(row)

    trades: list[tuple[tuple[str, str], float]] = []
    deltas: list[tuple[tuple[str, str], float]] = []
    by_series: dict[str, list[tuple[tuple[str, str], float]]] = {}
    considered = 0
    fill_unknown = 0
    fill_short = 0
    for (series, _target), wrows in sorted(windows.items()):
        if not any(_settled_trade(r) for r in wrows):
            continue  # nothing settled here yet: not a scored window
        considered += 1
        mine = candidate_trade(wrows, candidate, series)
        live = live_trade(wrows)
        if mine is not None and candidate.dial_for(series).fill_checked:
            key = (series, str(mine["close_time"]), int(mine["offset_min"]))
            sizes = (fills or {}).get(key)
            size = sizes.get(mine["side"]) if sizes else None
            if size is None:
                fill_unknown += 1
                continue  # unmeasured: the window leaves scoring
            if float(size) < demo_size(float(mine["side_cost"])):
                fill_short += 1
                mine = None  # measured, too thin: no trade that window
        if mine is None and live is None:
            continue
        day = _et_day((mine or live))
        cluster = (series, day)
        my_pnl = float(mine["pnl"]) if mine is not None else 0.0
        live_pnl = float(live["pnl"]) if live is not None else 0.0
        if mine is not None:
            trades.append((cluster, my_pnl))
            by_series.setdefault(series, []).append((cluster, my_pnl))
        deltas.append((cluster, my_pnl - live_pnl))

    n = len(trades)
    mean = sum(x for _c, x in trades) / n if n else None
    low95 = clustered_low95(trades) if n else None
    paired_low95 = clustered_low95(deltas) if deltas else None
    eligible = criterion_met(n, low95, paired_low95)
    days_run = (now - PREREG_AT).days
    killed = not eligible and (days_run >= STOP_DAYS or n >= STOP_TRADES)
    return {
        "version": version,
        "windows": considered,
        "trades": n,
        "net_per_contract": round(mean, 4) if mean is not None else None,
        "low95": round(low95, 4) if low95 is not None else None,
        "paired_windows": len(deltas),
        "paired_low95": round(paired_low95, 4) if paired_low95 is not None else None,
        "by_series": {
            s: {"trades": len(ts),
                "net_per_contract": round(sum(x for _c, x in ts) / len(ts), 4),
                "low95": (round(v, 4) if (v := clustered_low95(ts)) is not None else None)}
            for s, ts in sorted(by_series.items())},
        "fill_unknown": fill_unknown,
        "fill_short": fill_short,
        "eligible": eligible,
        "killed": killed,
        "days_run": max(days_run, 0),
    }
