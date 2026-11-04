"""One pass of the Kalshi gap tracker: log contracts, settle and exit paper positions, open new ones.

A separate layer: its forecaster instances are its own and it writes only gap_* tables, so the frozen
journal can't be touched. It reads Kalshi's public data and places nothing. Contracts without a two-sided
quote aren't logged (a run has about 900 open, 120 two-sided, and a one-sided contract can't pass the exit
check anyway); each run counts how many it skipped. Models here are priced further from the close than the
journal freezes them, so a fair value more than a couple of hours out is an extrapolation of that record.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from tradehub.gaps import logic
from tradehub.journal.kalshi_linked import kalshi_target
from tradehub.markets import parse_market

log = logging.getLogger(__name__)

SNAPSHOTS, POSITIONS, OUTCOMES, RUNS = "gap_snapshots", "gap_positions", "gap_outcomes", "gap_runs"
DEPTH_CAP = 30
RESOLVE_CAP = 200
EXIT_CONDITION = ("gap at or under 2 points or sign flip; model moves over 5 points from entry; "
                  "under 1 hour to settlement, at the bid; or settlement")
GROSS, NET = "gross: fees unknown for this series", "net of Kalshi's published taker fee"


def _f(raw: dict, key: str) -> float | None:
    """A price or count from Kalshi. Kalshi sends 0 or an empty string for no quote: that's unknown."""
    value = raw.get(key)
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number else None


def _quotes(raw: dict) -> dict[str, float | None]:
    yes_bid, yes_ask = _f(raw, "yes_bid_dollars"), _f(raw, "yes_ask_dollars")
    no_bid, no_ask = _f(raw, "no_bid_dollars"), _f(raw, "no_ask_dollars")
    yes_ask = None if yes_ask == 1.0 else yes_ask
    no_ask = None if no_ask == 1.0 else no_ask
    two_sided = yes_bid is not None and yes_ask is not None
    return {"yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
            "mid": (yes_bid + yes_ask) / 2 if two_sided else None,
            "spread": yes_ask - yes_bid if two_sided else None}


def _hours(settles_at: datetime, now: datetime) -> float:
    return (settles_at - now).total_seconds() / 3600


def _fees_known(series: dict) -> bool:
    return series.get("fee_type") == "quadratic" and float(series.get("fee_multiplier") or 0) == 1


def _fair_value(fc, lm, now: datetime) -> tuple[float | None, float | None]:
    """The forecaster's own math on this contract, ignoring its freeze window. Unknown if it can't say."""
    target = kalshi_target(lm.market.ticker)
    fc._open = {target: lm}
    forecast = fc.forecast(SimpleNamespace(target=target), now)
    if forecast is None:
        return None, None
    stamp = forecast.payload.get("price_at")
    age = (now - datetime.fromisoformat(stamp)).total_seconds() if stamp else None
    return forecast.probability, age


def _sources(live) -> list[dict]:
    from tradehub.engines.oil import OIL_SERIES
    from tradehub.engines.oil_hourly import HOURLY_SERIES
    from tradehub.journal.forecasters.crypto_hourly import CryptoHourlyModel, build_crypto_hourly
    from tradehub.journal.forecasters.oil import OilWti, build_oil
    from tradehub.journal.forecasters.oil_hourly import OilWtiHourly, build_oil_hourly

    out = [{"category": "crypto", "series": fc.series, "fc": fc}
           for fc in build_crypto_hourly(live) if isinstance(fc, CryptoHourlyModel)]
    out += [{"category": "oil", "series": OIL_SERIES, "fc": fc} for fc in build_oil(live) if type(fc) is OilWti]
    out += [{"category": "oil", "series": HOURLY_SERIES, "fc": fc}
            for fc in build_oil_hourly(live) if type(fc) is OilWtiHourly]
    return out


def snapshot_row(*, now: datetime, source: dict, raw: dict, market, series: dict, model_prob: float | None,
                 age: float | None) -> dict:
    quotes = _quotes(raw)
    side, gap = logic.executable_gap(model_prob, yes_ask=quotes["yes_ask"], no_ask=quotes["no_ask"])
    sources = series.get("settlement_sources") or []
    fc = source["fc"]
    return {"taken_at": now.isoformat(), "category": source["category"], "series": source["series"],
            "event_ticker": raw.get("event_ticker"), "ticker": market.ticker,
            "settles_at": market.close_time.isoformat(),
            "resolution_source": (sources[0].get("name") or None) if sources else None,
            "rule_summary": (raw.get("rules_primary") or "")[:300] or None,
            "model": f"{fc.name}@{fc.version}", "model_prob": model_prob, "model_data_age_s": age, **quotes,
            "last_price": _f(raw, "last_price_dollars"), "volume": _f(raw, "volume_fp"),
            "open_interest": _f(raw, "open_interest_fp"), "side": side, "gap_pts": gap,
            "exit_slippage": None, "failed": [], "flagged": False}


def _side_prob(row: dict) -> float:
    return row["model_prob"] if row["side"] == "yes" else 1 - row["model_prob"]


def apply_gates(row: dict, *, now: datetime, settles_at: datetime, bankroll: float, read_book, depth_left: int
                ) -> tuple[int, int]:
    """Fills the row's failed list. The book is read only when everything else passed, and a row that
    never reached it isn't charged a liquidity failure. Returns (contracts, book reads used)."""
    hours = _hours(settles_at, now)
    reads, slippage, contracts = 0, None, 0
    first = logic.gate(gap_pts=row["gap_pts"], hours_to_settle=hours, source=row["resolution_source"], slippage=0.0)
    if not first:
        price = row["yes_ask"] if row["side"] == "yes" else row["no_ask"]
        contracts = logic.half_kelly_contracts(_side_prob(row), price, bankroll)
        if depth_left > 0:
            reads = 1
            try:
                slippage = logic.exit_slippage(read_book(row["ticker"], row["side"]), contracts)
            except Exception:  # noqa: BLE001 -- no book read means unknown, never passing
                log.exception("gap tracker: order book read failed for %s", row["ticker"])
        row["failed"] = logic.gate(gap_pts=row["gap_pts"], hours_to_settle=hours, source=row["resolution_source"],
                                   slippage=slippage)
        row["exit_slippage"] = None if slippage in (None, math.inf) else slippage
    else:
        row["failed"] = first
    row["flagged"] = not row["failed"]
    return contracts, reads


def close_position(supa, position: dict, *, now: datetime, reason: str, price: float | None, pnl: float,
                   fee: float | None, basis: str) -> None:
    supa.table(POSITIONS).update({"status": "closed", "exit_state": None, "exit_at": now.isoformat(),
                                  "exit_reason": reason, "exit_price": price, "exit_fee": fee, "pnl": pnl,
                                  "pnl_basis": basis}).eq("id", position["id"]).execute()


def manage_position(supa, position: dict, *, now: datetime, row: dict | None, raw: dict | None, fees_known: bool
                    ) -> None:
    """Mechanical exits for one open position still listed. A missing exit quote stays open, shown UNKNOWN."""
    settles_at = datetime.fromisoformat(str(position["settles_at"]))
    quotes = _quotes(raw) if raw else {}
    side = position["side"]
    decision = logic.exit_decision(side=side, model_at_entry=float(position["model_at_entry"]),
                                   hours_to_settle=_hours(settles_at, now),
                                   model_prob=row["model_prob"] if row else None,
                                   side_ask=quotes.get(f"{side}_ask"))
    if decision["reason"] is None:
        return
    bid = quotes.get(f"{side}_bid")
    if bid is None:
        supa.table(POSITIONS).update({"exit_state": f"UNKNOWN: {decision['reason']} but no bid"}).eq(
            "id", position["id"]).execute()
        return
    contracts = int(position["contracts"])
    gross = contracts * (bid - float(position["entry_price"]))
    if fees_known and position.get("entry_fee") is not None:
        fee = logic.fee_dollars(bid, contracts)
        close_position(supa, position, now=now, reason=decision["reason"], price=bid, fee=fee,
                       pnl=gross - float(position["entry_fee"]) - fee, basis=NET)
    else:
        close_position(supa, position, now=now, reason=decision["reason"], price=bid, fee=None, pnl=gross, basis=GROSS)


def settle_unresolved(supa, now: datetime, read_market) -> int:
    """Record outcomes for contracts past settlement, and settle any open position on them."""
    tickers = [r["ticker"] for r in supa.rpc("gap_unresolved", {"asof": now.isoformat(), "max_rows": RESOLVE_CAP})
               .execute().data or []]
    done = 0
    for ticker in tickers:
        try:
            result = (read_market(ticker) or {}).get("result")
        except Exception:  # noqa: BLE001 -- tried again next run
            log.exception("gap tracker: could not read %s", ticker)
            continue
        if result not in ("yes", "no"):
            continue
        outcome = 1 if result == "yes" else 0
        supa.table(OUTCOMES).insert({"ticker": ticker, "outcome": outcome}).execute()
        done += 1
        for position in supa.table(POSITIONS).select("*").eq("ticker", ticker).eq("status", "open").execute().data or []:
            fee = position.get("entry_fee")
            pnl = logic.settled_pnl(side=position["side"], outcome=outcome, contracts=int(position["contracts"]),
                                    entry_price=float(position["entry_price"]), entry_fee=float(fee or 0))
            close_position(supa, position, now=now, reason="settlement", price=None, fee=0.0 if fee is not None else None,
                           pnl=pnl, basis=NET if fee is not None else GROSS)
    return done


def open_positions(supa) -> list[dict]:
    return supa.table(POSITIONS).select("*").eq("status", "open").execute().data or []


def _maybe_open(supa, row: dict, contracts: int, *, now: datetime, fees_known: bool, held: set[str]) -> bool:
    if contracts <= 0 or row["ticker"] in held or len(open_positions(supa)) >= logic.MAX_POSITIONS:
        return False
    price = row["yes_ask"] if row["side"] == "yes" else row["no_ask"]
    supa.table(POSITIONS).insert({
        "ticker": row["ticker"], "category": row["category"], "settles_at": row["settles_at"], "side": row["side"],
        "opened_at": now.isoformat(), "model": row["model"], "model_at_entry": row["model_prob"], "entry_price": price,
        "gap_pts": row["gap_pts"], "contracts": contracts,
        "entry_fee": logic.fee_dollars(price, contracts) if fees_known else None,
        "exit_condition": EXIT_CONDITION, "status": "open"}).execute()
    held.add(row["ticker"])
    return True


def _read_book(live):
    def read(ticker: str, side: str) -> list | None:
        book = (live._get(f"/markets/{ticker}/orderbook") or {}).get("orderbook_fp") or {}
        return book.get(f"{side}_dollars") or []
    return read


def run_tracker(supa, now: datetime, *, live=None, sources=None, read_book=None, read_market=None, read_series=None
                ) -> dict[str, Any]:
    if live is None:
        from tradehub.data.kalshi_live import KalshiLive

        live = KalshiLive()
    sources = sources if sources is not None else _sources(live)
    read_book = read_book or _read_book(live)
    read_market = read_market or (lambda t: (live._get(f"/markets/{t}") or {}).get("market"))
    read_series = read_series or (lambda s: (live._get(f"/series/{s}") or {}).get("series") or {})

    summary: dict[str, Any] = {"settled": settle_unresolved(supa, now, read_market), "logged": 0, "flagged": 0,
                               "opened": 0, "errors": []}
    ledger = supa.table(POSITIONS).select("*").execute().data or []
    bankroll = logic.summarize_ledger([r for r in ledger if r["status"] == "closed"])["bankroll"]
    held_ever = {r["ticker"] for r in ledger}
    still_open = {r["ticker"]: r for r in ledger if r["status"] == "open"}
    depth_left = DEPTH_CAP
    candidates: list[tuple[dict, int, bool]] = []
    for source in sources:
        counts = {"open_markets": 0, "logged": 0, "one_sided_skipped": 0}
        error = None
        try:
            series = read_series(source["series"])
            fees_known = _fees_known(series)
            rows = []
            raws = live.open_raws(source["series"])
            counts["open_markets"] = len(raws)
            for raw in raws:
                ticker = raw.get("ticker")
                quotes = _quotes(raw)
                if quotes["mid"] is None and ticker not in still_open:
                    counts["one_sided_skipped"] += 1
                    continue
                market = parse_market(raw)
                lm = SimpleNamespace(market=market, quote=_quote_for(raw))
                try:
                    prob, age = _fair_value(source["fc"], lm, now)
                except Exception:  # noqa: BLE001 -- the model can't say: unknown, for this contract only
                    log.exception("gap tracker: %s failed on %s", source["series"], ticker)
                    prob, age = None, None
                row = snapshot_row(now=now, source=source, raw=raw, market=market, series=series, model_prob=prob, age=age)
                contracts, used = apply_gates(row, now=now, settles_at=market.close_time, bankroll=bankroll,
                                              read_book=read_book, depth_left=depth_left)
                depth_left -= used
                rows.append(row)
                if ticker in still_open:
                    manage_position(supa, still_open[ticker], now=now, row=row, raw=raw, fees_known=fees_known)
                if row["flagged"]:
                    candidates.append((row, contracts, fees_known))
            for start in range(0, len(rows), 500):
                supa.table(SNAPSHOTS).insert(rows[start:start + 500]).execute()
            counts["logged"] = len(rows)
            summary["logged"] += len(rows)
            summary["flagged"] += sum(r["flagged"] for r in rows)
        except Exception as exc:  # noqa: BLE001 -- one series failing never stops the others
            log.exception("gap tracker: series %s failed", source["series"])
            error = f"{type(exc).__name__}: {exc}"[:300]
            summary["errors"].append(f"{source['series']}: {error}")
        supa.table(RUNS).insert({"taken_at": now.isoformat(), "series": source["series"],
                                 "category": source["category"], **counts, "error": error}).execute()
    # Exits ran above, so capacity they freed is available. Biggest gap first.
    for row, contracts, fees_known in sorted(candidates, key=lambda c: -c[0]["gap_pts"]):
        summary["opened"] += _maybe_open(supa, row, contracts, now=now, fees_known=fees_known, held=held_ever)
    return summary


def _quote_for(raw: dict):
    from tradehub.data.kalshi_live import quote_from_market_raw

    return quote_from_market_raw(raw)
