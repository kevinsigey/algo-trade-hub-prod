"""Settle `predictions` rows against Kalshi public market results.

Pure math here; Supabase/Kalshi I/O is injected or isolated in thin
wrappers so the settlement rules are unit-testable. Predictions settle
against the Kalshi market result (spec section 4.5) — never against the
portfolio settlement history, which covers only owned positions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.backtest.kalshi_history import KalshiHistoryClient, parse_ts

log = logging.getLogger(__name__)

PREDICTIONS_TABLE = "predictions"

OPEN = "OPEN"
SETTLED = "SETTLED"
CANCELED = "CANCELED"
PAGE_SIZE = 1000


def compute_realized_pnl(qty: int, buy_price: float, settle_price: float, fees_cents: int = 0) -> float:
    """Realized dollar P&L for one settled position: (settle - buy) * qty minus fees."""
    return (settle_price - buy_price) * qty - fees_cents / 100.0


def brier_score(prob: float, outcome: int) -> float:
    """Brier score for a binary prediction: (prob - outcome) ** 2."""
    return (prob - outcome) ** 2


def parse_market_result(market: Any) -> tuple[str, int | None]:
    """Map a Kalshi `GET /markets/{ticker}` payload to (disposition, outcome).

    Disposition is OPEN, SETTLED, or CANCELED; outcome is 1/0/None.
    Anything malformed or ambiguous returns ("OPEN", None) — never settle
    on what we cannot parse. A finalized market whose result key is missing
    is malformed (stays OPEN, retried next pass); a finalized market with a
    present-but-non-binary result (null, "", "canceled", ...) was voided and
    is CANCELED — we never fabricate a yes/no.
    """
    try:
        inner = market["market"]
        status = inner["status"]
        result = inner.get("result")
    except (TypeError, KeyError, AttributeError):
        return (OPEN, None)
    if status == "finalized":
        if result == "yes":
            return (SETTLED, 1)
        if result == "no":
            return (SETTLED, 0)
        if "result" in inner:
            return (CANCELED, None)
        return (OPEN, None)
    return (OPEN, None)


def is_market_canceled(market: Any) -> bool:
    """True iff the market was finalized without a yes/no result."""
    return parse_market_result(market)[0] == CANCELED


def settle_prediction_row(row: dict[str, Any], market: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Build the `predictions` update payload for one row against a fetched market.

    Returns None when the market is still open (caller skips the row).
    A canceled market yields a CANCELED payload with no fabricated result.
    The Kalshi payload goes to `settlement_payload`; the engine's own
    `raw_payload` (its inputs) is never overwritten.
    """
    disposition, outcome = parse_market_result(market)
    if disposition == OPEN:
        return None
    settled_at = (now or datetime.now(UTC)).isoformat()
    if disposition == CANCELED:
        return {"id": row["id"], "status": CANCELED, "settlement_payload": market, "settled_at": settled_at}
    outcome_str = "yes" if outcome == 1 else "no"
    update: dict[str, Any] = {
        "id": row["id"],
        "status": SETTLED,
        "result": outcome_str,
        "brier": round(brier_score(float(row["our_prob"]), outcome), 5),
        "settlement_payload": market,
        "settled_at": settled_at,
    }
    market_prob = row.get("market_prob")
    update["market_brier"] = (
        round(brier_score(float(market_prob), outcome), 5) if market_prob is not None else None
    )
    return update


def clv_points(row: dict[str, Any], close: dict[str, Any] | None) -> float | None:
    """Closing-line value in probability points on the row's own side.

    Both `market_prob` and the candle's `yes_prob` are YES probabilities. A YES
    row owns that difference; a NO row owns its mirror. There is no `side`
    column on a prediction row: the favored side is the one with the positive
    edge in `tradehub.edges.best_side`, i.e. YES when our_prob >= market_prob.

    A close observed before the row was logged is not a close — it says what
    the market thought before we got there. Missing is None, never 0: zero
    would claim we exactly matched the close, which is a different claim from
    "we do not know". Canceled rows have no close to beat.
    """
    if not isinstance(close, dict) or row.get("status") == CANCELED:
        return None
    our_prob = row.get("our_prob")
    market_prob = row.get("market_prob")
    yes_prob = close.get("yes_prob")
    if not all(isinstance(v, (int, float)) for v in (our_prob, market_prob, yes_prob)):
        return None
    try:
        logged_at = parse_ts(str(row["as_of"])) if row.get("as_of") else None
        close_at = parse_ts(str(close["at"])) if close.get("at") else None
    except (TypeError, ValueError):
        logged_at = close_at = None
    if logged_at is not None and close_at is not None and close_at < logged_at:
        return None
    diff = float(yes_prob) - float(market_prob)
    return round(diff if float(our_prob) >= float(market_prob) else -diff, 5)


def fetch_closing_price(series: str, ticker: str, close_time: str,
                        *, client: KalshiHistoryClient | None = None) -> dict[str, Any] | None:
    """Last public 60m candle ending at or before the market close.

    Kalshi's public candlesticks give the yes bid/ask closes; their midpoint is
    the last price anyone could see. `KalshiHistoryClient.parse_candle` already
    falls back to `price.close` when the bid/ask blocks are absent. Returns the
    JSON-safe close record, or None when there is no usable candle.
    """
    close_dt = parse_ts(close_time)
    # 24h of 60m candles is enough to contain a market's last pre-close candle.
    candles = (client or KalshiHistoryClient()).candles(
        ticker, close_dt - timedelta(hours=24), close_dt,
        period_minutes=60, historical=False, series_ticker=series,
    )
    eligible = [c for c in candles if c.end_ts <= close_dt]
    if not eligible:
        return None
    last = max(eligible, key=lambda c: c.end_ts)
    bid, ask = last.yes_bid, last.yes_ask
    if bid is None and ask is None:
        return None
    yes_prob = (bid + ask) / 2.0 if bid is not None and ask is not None else (bid if bid is not None else ask)
    return {"yes_prob": round(yes_prob, 5), "source": "candle_60m", "at": last.end_ts.isoformat()}


def _series_for(ticker: str, inner: dict[str, Any]) -> str:
    return str(inner.get("series_ticker") or ticker.split("-")[0])


def _closing_for_ticker(fetch_close, ticker: str, market: Any,
                        closes: dict[str, Any], attempted: set[str]) -> dict[str, Any] | None:
    """Fetch a ticker's close at most once; a failure is logged once and never raised."""
    if ticker in attempted:
        return closes.get(ticker)
    attempted.add(ticker)
    inner = market.get("market") or {} if isinstance(market, dict) else {}
    close_time = inner.get("close_time")
    if not close_time:
        return None
    try:
        close = fetch_close(_series_for(ticker, inner), ticker, str(close_time))
        if isinstance(close, dict):
            closes[ticker] = close
    except Exception as exc:  # noqa: BLE001 - CLV must never break settlement
        log.warning("CLV close fetch failed for %s: %s", ticker, exc)
    return closes.get(ticker)


def fetch_open_predictions(supa) -> list[dict[str, Any]]:
    """Return all `predictions` rows still awaiting settlement, paged by id."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        res = (
            supa.table(PREDICTIONS_TABLE)
            .select("*")
            .eq("status", OPEN)
            .order("id")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def apply_prediction_settlement(supa, update: dict[str, Any]) -> bool:
    """Conditionally write one settlement payload to an OPEN row by id."""
    payload = {k: v for k, v in update.items() if k != "id"}
    result = (
        supa.table(PREDICTIONS_TABLE)
        .update(payload)
        .eq("id", update["id"])
        .eq("status", OPEN)
        .execute()
    )
    return bool(result.data)


def run_settlement_pass(supa, fetch_market, fetch_close=fetch_closing_price) -> dict[str, int]:
    """One idempotent settlement pass over all OPEN predictions.

    `fetch_market(ticker)` is injected so tests can fake it; the cron
    entrypoint passes the real Kalshi client. Each ticker is fetched at most
    once per pass (the hourly scan writes many rows per market). Fetch
    failures (404 unknown ticker, 429, connection errors) skip that ticker's
    rows and are counted in `fetch_errors`; a failed write skips its row and
    is counted in `write_errors`. Neither fabricates a result or blocks the
    rest of the pass.

    `fetch_close(series, ticker, close_time)` is injected too. A settled row's
    closing YES probability is stored under `settlement_payload["close"]`; a
    failure stores nothing and is logged once per ticker. Canceled rows never
    get a close.
    """
    summary = {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0, "fetch_errors": 0, "write_errors": 0}
    markets: dict[str, Any] = {}
    closes: dict[str, Any] = {}
    close_attempted: set[str] = set()
    failed: set[str] = set()
    now = datetime.now(UTC)
    for row in fetch_open_predictions(supa):
        summary["checked"] += 1
        ticker = row["market_ticker"]
        if ticker in failed:
            summary["skipped"] += 1
            continue
        if ticker not in markets:
            try:
                markets[ticker] = fetch_market(ticker)
            except Exception:  # noqa: BLE001 - injected fetcher failures must skip the ticker
                failed.add(ticker)
                summary["fetch_errors"] += 1
                summary["skipped"] += 1
                continue
        update = settle_prediction_row(row, markets[ticker], now=now)
        if update is None:
            summary["skipped"] += 1
            continue
        if update["status"] == SETTLED:
            close = _closing_for_ticker(fetch_close, ticker, markets[ticker], closes, close_attempted)
            if close is not None:
                update["settlement_payload"] = {**update["settlement_payload"], "close": close}
        try:
            written = apply_prediction_settlement(supa, update)
        except Exception:  # noqa: BLE001 - one bad write must not abort the pass
            summary["write_errors"] += 1
            summary["skipped"] += 1
            continue
        if not written:
            summary["skipped"] += 1
            continue
        if update["status"] == SETTLED:
            summary["settled"] += 1
        else:
            summary["canceled"] += 1
    return summary
