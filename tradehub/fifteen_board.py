"""The Strategies redesign board (Kevin's spec via Claude, 2026-11-18):
the fifteen-minute family grouped by commodity, every model scored on a
commodity ranked on one wide card, with a simulated account under each
model. Display only -- built from the per-contract records already kept
(the journal-recomputed live record, the shadows' decision tables, the
offset grid the candidates score from). No new trading, no writes.

The simulated account (frozen in the spec, bust rule as amended by
Claude's review of this PR): start at $20; each trade stakes 10% of
the current balance, buying max(1, floor(stake / cost)) contracts;
when the tick depth is known the contracts cap at what was on offer
at the ask, and a trade with nothing on offer is skipped, not a
bust; the account is bust only when the balance cannot buy one
contract at all (balance < cost), and the replay stops there. Models sort best to worst by fresh net
cents per contract, models under 10 trades last ("too few"); commodity
cards sort by their best proven model (best net among models with
10+ trades, else the best overall). The board's pairing is uniform:
every model pairs against the live rule on the model's own settled
windows in that series -- the ones it traded and the ones it sat out --
with the live rule's pnl on each (0 where it did not trade); live
windows outside the model's span are not paired.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradehub.fifteen_volregime import clustered_low95

_ET = ZoneInfo("America/New_York")
ACCOUNT_START = 20.0
STAKE_PCT = 0.10
TOO_FEW = 10

COMMODITIES = [
    ("KXNATGAS15M", "Natural gas"),
    ("KXWTI15M", "WTI"),
    ("KXBRENT15M", "Brent"),
    ("KXCOPPER15M", "Copper"),
    ("KXSILVER15M", "Silver"),
    ("KXGOLD15M", "Gold"),
]
_LABEL_TO_SERIES = {"Natural gas": "KXNATGAS15M", "WTI": "KXWTI15M", "Brent": "KXBRENT15M",
                    "Gold": "KXGOLD15M", "Silver": "KXSILVER15M", "Copper": "KXCOPPER15M"}


def replay_account(trades: list[dict]) -> dict[str, Any]:
    """Replay one model's trades (time order; each {cost, pnl,
    ask_size}) through the $20 / 10% simulated account."""
    balance = ACCOUNT_START
    peak = ACCOUNT_START
    drawdown = 0.0
    curve = [ACCOUNT_START]
    bust = False
    for trade in trades:
        cost = float(trade["cost"])
        if cost <= 0:
            continue  # unpriceable: skipped, not a bust
        size = trade.get("ask_size")
        if size is not None and int(size) < 1:
            continue  # nothing on offer at the ask: skipped, not a bust
        if balance < cost:
            bust = True
            break
        contracts = max(1, math.floor(balance * STAKE_PCT / cost))
        if size is not None:
            contracts = min(contracts, int(size))
        balance = round(balance + contracts * float(trade["pnl"]), 2)
        peak = max(peak, balance)
        drawdown = max(drawdown, round(peak - balance, 2))
        curve.append(balance)
    return {"start": ACCOUNT_START, "balance": balance, "drawdown": drawdown,
            "bust": bust, "curve": curve, "trades_taken": len(curve) - 1}


def _et_day(iso: str) -> str:
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(_ET).date().isoformat()


def _cents(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None else None


def model_row(version: str, label: str, series: str, trades: list[dict],
              live_by_target: dict[str, float], *, fill_short: int,
              needed: int, extra_windows: list[dict] | None = None) -> dict[str, Any]:
    """One model's row on one commodity card. `trades` are its settled
    fresh trades in time order; `live_by_target` is the live rule's pnl
    by target in this series; `extra_windows` are settled windows the
    model sat out (its own decision rows with no trade), so the pairing
    covers every window the model saw -- traded or sat out -- and skips
    live windows outside that span."""
    ordered = sorted(trades, key=lambda t: t["frozen_at"])
    pnls = [float(t["pnl"]) for t in ordered]
    n = len(pnls)
    net = sum(pnls) / n if n else None
    low95 = clustered_low95([(_et_day(t["frozen_at"]), float(t["pnl"])) for t in ordered]) if n else None
    mine = {t["target"]: float(t["pnl"]) for t in ordered}
    sat_out = {w["target"] for w in (extra_windows or [])}
    targets = set(mine) | set(live_by_target) | sat_out
    day_of = {t["target"]: _et_day(t["frozen_at"]) for t in ordered}
    for w in (extra_windows or []):
        day_of.setdefault(w["target"], _et_day(w["frozen_at"]))
    deltas = []
    for target in targets:
        if target in live_by_target and target not in day_of:
            continue  # a live window outside this model's own span: not its pairing
        deltas.append((day_of.get(target, ""), mine.get(target, 0.0) - live_by_target.get(target, 0.0)))
    deltas = [d for d in deltas if d[0]]
    paired_low95 = clustered_low95(deltas) if deltas else None
    legs = {"n": n >= needed,
            "low95": low95 is not None and low95 > 0,
            "paired": paired_low95 is not None and paired_low95 > 0}
    return {"version": version, "label": label, "series": series,
            "trades": n, "net_cents": _cents(net), "low95": _cents(low95),
            "paired_low95": _cents(paired_low95), "fill_short": fill_short,
            "progress": {"n": n, "needed": needed, "legs": legs},
            "too_few": n < TOO_FEW,
            "account": replay_account(ordered)}


def sort_board(cards: list[dict]) -> list[dict]:
    """Models best to worst within a card (under-10-trades last); cards
    by their best proven model, then by their best model overall."""
    def model_key(m: dict) -> tuple:
        return (1 if m["too_few"] else 0,
                -(m["net_cents"] if m["net_cents"] is not None else -1e9))

    def card_key(card: dict) -> float:
        proven = [m["net_cents"] for m in card["models"]
                  if not m["too_few"] and m["net_cents"] is not None]
        any_net = [m["net_cents"] for m in card["models"] if m["net_cents"] is not None]
        best = max(proven) if proven else (max(any_net) if any_net else None)
        return -(best if best is not None else -1e9)

    for card in cards:
        card["models"] = sorted(card["models"], key=model_key)
    return sorted(cards, key=card_key)


# ---------------------------------------------------------------- assembly

def _read(supa, table: str, build=None) -> list[dict]:
    from tradehub.fifteen_blend import _read as blend_read
    return blend_read(supa, table, build)


def _fills(supa, rows: list[dict]) -> dict:
    """Ask sizes from the minute tape, keyed (series, close_time,
    offset_min) -> {"yes": size|None, "no": size|None} -- the
    candidates scorer's own bucketing (fifteen_candidates_score._fills)."""
    from tradehub.fifteen_tracking import _tick_buckets, fetch_ticks
    closes: dict[str, set[str]] = {}
    for row in rows:
        closes.setdefault(row["series"], set()).add(str(row["close_time"]))
    fills: dict = {}
    for series, close_times in sorted(closes.items()):
        by_close: dict[str, list[dict]] = {}
        for tick in fetch_ticks(supa, series, sorted(close_times)):
            by_close.setdefault(str(tick["close_time"]), []).append(tick)
        for close_time, ticks in by_close.items():
            for k, tick in _tick_buckets(ticks).items():
                fills[(series, close_time, k)] = {"yes": tick.get("yes_ask_size"),
                                                  "no": tick.get("no_ask_size")}
    return fills


def _too_thin(size, cost: float) -> bool:
    """A measured ask size below the demo's 1% order at `cost`. A cost of
    zero or less has no order size (demo_size would divide by it) and the
    account replay skips such a trade, so it is never counted thin."""
    from tradehub.fifteen_candidates import demo_size
    return size is not None and cost > 0 and float(size) < demo_size(cost)


def _attach_sizes(trades: list[dict], fills: dict) -> int:
    """In place: each trade's ask_size from the tape (None when
    unmeasured). Returns the fill_short count: measured sizes below
    the demo's 1% size for the trade's cost (fifteen_candidates'
    demo_size)."""
    short = 0
    for trade in trades:
        sizes = fills.get((trade["series"], str(trade["close_time"]), int(trade["offset"])))
        size = sizes.get(trade["side"]) if sizes else None
        trade["ask_size"] = size
        if _too_thin(size, float(trade["cost"])):
            short += 1
    return short


def _live_trades(supa) -> dict[str, list[dict]]:
    """The live gate's gated fresh trades per series, recomputed from
    the journal exactly as the two rule modules' record() does."""
    from tradehub import metals_fifteen_rule, oil_fifteen_rule
    from tradehub.journal import store
    out: dict[str, list[dict]] = {}
    for module in (oil_fifteen_rule, metals_fifteen_rule):
        picker = lambda p, *, yes_ask, yes_bid: (  # noqa: E731
            c[:2] if (c := module.pick_net(p, yes_ask=yes_ask, yes_bid=yes_bid)) else None)
        for forecaster, version, label in module.SERIES:
            rows = store.fetch_forecasts(supa, forecaster, version)
            first: dict[str, dict] = {}
            for r in sorted(rows, key=lambda r: r["frozen_at"]):
                first.setdefault(r["target"], r)
            trades, _pending = oil_fifteen_rule._series_trades(supa, first, label, picker)
            series = _LABEL_TO_SERIES[label]
            out[series] = [{"series": series, "target": t["target"], "frozen_at": t["frozen_at"],
                            "side": t["side"], "cost": t["cost"], "pnl": t["pnl"], "offset": 5}
                           for t in trades if t["frozen_at"] >= module.PREREG_AT]
    return out


def _decisions_trades(supa, module) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """A shadow's fresh settled trades and its sat-out settled windows,
    per series, from its decisions table."""
    rows = _read(supa, module.DECISIONS_TABLE,
                 lambda q: q.gte("window_open", module.PREREG_AT))
    trades: dict[str, list[dict]] = {}
    sat_out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("outcome") is None or not r.get("frozen_at") or not r.get("window_open"):
            continue
        opened = datetime.fromisoformat(str(r["window_open"]).replace("Z", "+00:00"))
        frozen = datetime.fromisoformat(str(r["frozen_at"]).replace("Z", "+00:00"))
        entry = {"series": r["series"], "target": r["target"], "frozen_at": r["frozen_at"],
                 "close_time": r["close_time"], "side": r.get("side"),
                 "cost": r.get("cost"), "pnl": r.get("pnl"),
                 "offset": round((frozen - opened).total_seconds() / 60)}
        if r["action"] == "buy" and r.get("pnl") is not None:
            trades.setdefault(r["series"], []).append(entry)
        else:
            sat_out.setdefault(r["series"], []).append(entry)
    return trades, sat_out


def _candidate_trades(supa, offsets: list[dict], fills: dict) -> dict[str, dict[str, tuple]]:
    """Per candidate version, per series: (trades, sat_out, fill_short),
    extracted with fifteen_candidates' own trade picker and fill rules
    (a fill-checked lane's unmeasured window leaves scoring entirely;
    a measured-short entry is refused and counted)."""
    from tradehub import fifteen_candidates as fc
    windows: dict[tuple[str, str], list[dict]] = {}
    for row in offsets:
        if fc.window_open(row) < fc.PREREG_AT:
            continue
        windows.setdefault((row["series"], row["target"]), []).append(row)
    out: dict[str, dict[str, tuple]] = {}
    for version, candidate in fc.CANDIDATES.items():
        per_series: dict[str, tuple] = {}
        for (series, _target), wrows in sorted(windows.items()):
            if candidate.dial_for(series) is None:
                continue
            if fc.window_open(wrows[0]) < getattr(candidate, "prereg_at", fc.PREREG_AT):
                continue  # the candidate scores only from its own preregistration
            if not any(fc._settled_trade(r) for r in wrows):
                continue
            mine = fc.candidate_trade(wrows, candidate, series)
            trades, sat_out, short = per_series.get(series, ([], [], 0))
            if mine is not None and candidate.dial_for(series).fill_checked:
                key = (series, str(mine["close_time"]), int(mine["offset_min"]))
                sizes = fills.get(key)
                size = sizes.get(mine["side"]) if sizes else None
                if size is None:
                    continue  # unmeasured: the window leaves scoring
                if _too_thin(size, float(mine["side_cost"])):
                    short += 1
                    mine = None  # measured, too thin: no trade that window
            if mine is None:
                sat_out.append({"target": _target, "frozen_at": wrows[0]["close_time"]})
            else:
                trades.append({"series": series, "target": _target,
                               "frozen_at": mine["close_time"], "close_time": mine["close_time"],
                               "side": mine["side"], "cost": mine["side_cost"],
                               "pnl": mine["pnl"], "offset": int(mine["offset_min"])})
            per_series[series] = (trades, sat_out, short)
        out[version] = per_series
    return out


def board(supa) -> dict[str, Any]:
    """The full board: commodity cards with every model scored on each."""
    from tradehub import fifteen_binance, fifteen_blend, fifteen_volregime
    from tradehub.journal import store as journal_store

    live = _live_trades(supa)
    offsets = journal_store.select_all(
        supa, "fifteen_window_offsets",
        lambda q: q.gte("close_time", "2026-11-14T00:00:00+00:00"),
        ("close_time", "series", "target", "offset_min"))
    # close_time by (series, target) for the live trades' tape lookups.
    close_by_target = {}
    for row in offsets:
        close_by_target.setdefault((row["series"], row["target"]), str(row["close_time"]))
    for series, trades in live.items():
        for trade in trades:
            trade["close_time"] = close_by_target.get((series, trade["target"]), trade["frozen_at"])

    blend_trades, blend_out = _decisions_trades(supa, fifteen_blend)
    vol_trades, vol_out = _decisions_trades(supa, fifteen_volregime)
    bin_trades, bin_out = _decisions_trades(supa, fifteen_binance)
    fills = _fills(supa, offsets + [t for trades in (blend_trades, vol_trades, bin_trades)
                                    for ts in trades.values() for t in ts])
    candidates = _candidate_trades(supa, offsets, fills)

    weights: dict[str, float] = {}
    for r in _read(supa, fifteen_blend.WEIGHTS_TABLE):
        cur = weights.get(r["series"])
        if cur is None or str(r["day"]) >= str(cur[0]):
            weights[r["series"]] = (r["day"], r["weight"])

    cards = []
    for series, commodity in COMMODITIES:
        live_by_target = {t["target"]: float(t["pnl"]) for t in live.get(series, [])}
        models = []
        live_short = _attach_sizes(live.get(series, []), fills)
        models.append(model_row("live", "Live rule", series, live.get(series, []),
                                {}, fill_short=live_short, needed=300))
        # The live row pairs against itself by construction, so it has no
        # paired interval to show; its paired leg in the go-live bar is its
        # own low95 leg.
        models[-1]["paired_low95"] = None
        models[-1]["progress"]["legs"]["paired"] = models[-1]["progress"]["legs"]["low95"]
        for version, label, trades_map, out_map, needed in (
                ("v2-blend-shadow", "Blend", blend_trades, blend_out, 100),
                ("v3-volregime-shadow", "Vol-regime challenger", vol_trades, vol_out, 100)):
            trades = trades_map.get(series, [])
            short = _attach_sizes(trades, fills)
            row = model_row(version, label, series, trades, live_by_target,
                            fill_short=short, needed=needed,
                            extra_windows=out_map.get(series, []))
            if version == "v2-blend-shadow" and series in weights:
                row["weight"] = weights[series][1]
            models.append(row)
        for version, per_series in candidates.items():
            if series not in per_series:
                continue
            trades, sat_out, short = per_series[series]
            _attach_sizes(trades, fills)
            models.append(model_row(version, version, series, trades, live_by_target,
                                    fill_short=short, needed=100, extra_windows=sat_out))
        if series == "KXGOLD15M":
            trades = bin_trades.get(series, [])
            short = _attach_sizes(trades, fills)
            models.append(model_row("v5-binance-gold-shadow", "Binance-tape gold", series,
                                    trades, live_by_target, fill_short=short, needed=100,
                                    extra_windows=bin_out.get(series, [])))
        cards.append({"series": series, "commodity": commodity, "models": models})
    return {"commodities": sort_board(cards), "account_start": ACCOUNT_START,
            "generated_at": datetime.now(timezone.utc).isoformat()}
