"""The Kalshi gap tracker's rules, as pure functions. A paper ledger only: nothing here or
anywhere in this package places an order. An unknown value stays None, never zero."""

from __future__ import annotations

import math

from shared.kalshi_fees import kalshi_fee_cents

MIN_GAP_PTS = 8.0
MIN_HOURS_TO_SETTLE = 2.0
MAX_EXIT_SLIPPAGE = 0.03
BANKROLL = 10_000.0
MAX_POSITION_PCT = 6.0
MAX_POSITIONS = 5
EXIT_GAP_PTS = 2.0
EXIT_MODEL_MOVE_PTS = 5.0
EXIT_HOURS = 1.0
MIN_DAYS, MIN_PAIRS = 28, 150
EPSILON = 1e-6  # keeps log loss finite on a forecast of exactly 0 or 1


def executable_gap(model_prob: float | None, *, yes_ask: float | None, no_ask: float | None
                   ) -> tuple[str | None, float | None]:
    """The better side to buy, and its gap in points against that side's ask."""
    if model_prob is None:
        return None, None
    sides = []
    if yes_ask is not None:
        sides.append(("yes", (model_prob - yes_ask) * 100))
    if no_ask is not None:
        sides.append(("no", ((1 - model_prob) - no_ask) * 100))
    return max(sides, key=lambda s: s[1]) if sides else (None, None)


def half_kelly_contracts(side_prob: float, price: float, bankroll: float) -> int:
    """Whole contracts: half the binary Kelly fraction at the entry price, capped at 6% of bankroll."""
    if not 0 < price < 1 or bankroll <= 0 or side_prob <= price:
        return 0
    fraction = min((side_prob - price) / (1 - price) / 2, MAX_POSITION_PCT / 100)
    return math.floor(bankroll * fraction / price + 1e-9)


def exit_slippage(bid_levels: list | None, contracts: int) -> float | None:
    """How far below the best bid the full position would average on the way out, as a fraction.
    None: no book to read. inf: the book can't hold the whole position."""
    if bid_levels is None:
        return None
    levels = sorted(((float(p), float(s)) for p, s in bid_levels), reverse=True)
    if not levels or contracts <= 0:
        return math.inf
    left, proceeds = contracts, 0.0
    for price, size in levels:
        taken = min(left, size)
        proceeds += taken * price
        left -= taken
        if left <= 0:
            return (levels[0][0] - proceeds / contracts) / levels[0][0]
    return math.inf


def gate(*, gap_pts: float | None, hours_to_settle: float, source: str | None, slippage: float | None) -> list[str]:
    """Every gate this contract failed; empty means flagged."""
    failed = []
    if gap_pts is None:
        failed.append("model_or_market_unknown")
    elif gap_pts < MIN_GAP_PTS:
        failed.append("gap")
    if hours_to_settle <= MIN_HOURS_TO_SETTLE:
        failed.append("too_close_to_settlement")
    if not source:
        failed.append("resolution_source_unknown")
    if slippage is None:
        failed.append("liquidity_unknown")
    elif slippage == math.inf:
        failed.append("not_enough_depth")
    elif slippage > MAX_EXIT_SLIPPAGE:
        failed.append("exit_slippage")
    return failed


def exit_decision(*, side: str, model_at_entry: float, hours_to_settle: float, model_prob: float | None,
                  side_ask: float | None) -> dict:
    """The first mechanical exit that applies. A rule needing an unknown value can't fire."""
    if hours_to_settle < EXIT_HOURS:
        return {"reason": "near_settlement"}
    if model_prob is None:
        return {"reason": None}
    if abs(model_prob - model_at_entry) * 100 > EXIT_MODEL_MOVE_PTS:
        return {"reason": "model_moved"}
    if side_ask is not None:
        side_prob = model_prob if side == "yes" else 1 - model_prob
        if (side_prob - side_ask) * 100 <= EXIT_GAP_PTS:
            return {"reason": "gap_closed"}
    return {"reason": None}


def fee_dollars(price: float, contracts: int) -> float:
    """Kalshi's published taker fee for one order. Settlement itself charges none."""
    return kalshi_fee_cents(price * 100, contracts=contracts) / 100


def settled_pnl(*, side: str, outcome: int, contracts: int, entry_price: float, entry_fee: float) -> float:
    won = outcome == 1 if side == "yes" else outcome == 0
    return (contracts if won else 0) - contracts * entry_price - entry_fee


def _log_loss(prob: float, outcome: int) -> float:
    p = min(max(prob, EPSILON), 1 - EPSILON)
    return -math.log(p if outcome == 1 else 1 - p)


def _score(pairs: list[dict]) -> dict:
    n = len(pairs)
    if n == 0:
        return {"n": 0, "model_brier": None, "market_brier": None, "brier_delta": None,
                "model_log_loss": None, "market_log_loss": None, "calibration": []}
    model = sum((p["model"] - p["outcome"]) ** 2 for p in pairs) / n
    market = sum((p["market"] - p["outcome"]) ** 2 for p in pairs) / n
    buckets: dict[int, list[dict]] = {}
    for p in pairs:
        buckets.setdefault(min(int(p["model"] * 10), 9), []).append(p)
    calibration = [{"bucket": f"{b * 10}-{b * 10 + 10}", "n": len(rows),
                    "mean_model": sum(r["model"] for r in rows) / len(rows),
                    "hit_rate": sum(r["outcome"] for r in rows) / len(rows)}
                   for b, rows in sorted(buckets.items())]
    return {"n": n, "model_brier": model, "market_brier": market, "brier_delta": model - market,
            "model_log_loss": sum(_log_loss(p["model"], p["outcome"]) for p in pairs) / n,
            "market_log_loss": sum(_log_loss(p["market"], p["outcome"]) for p in pairs) / n,
            "calibration": calibration}


def grade(pairs: list[dict]) -> dict:
    """Model vs the market price as a forecast, overall and per category. Negative delta: model better."""
    return {"all": _score(pairs), "crypto": _score([p for p in pairs if p["category"] == "crypto"]),
            "oil": _score([p for p in pairs if p["category"] == "oil"])}


def evidence_status(*, days: float, pairs: int) -> dict:
    enough = days >= MIN_DAYS and pairs >= MIN_PAIRS
    return {"status": "ENOUGH TO READ" if enough else "NOT ENOUGH EVIDENCE", "days": days, "pairs": pairs,
            "min_days": MIN_DAYS, "min_pairs": MIN_PAIRS}


def summarize_ledger(rows: list[dict]) -> dict:
    closed = sorted((r for r in rows if r["status"] == "closed" and r.get("pnl") is not None),
                    key=lambda r: str(r.get("exit_at")))
    bankroll = peak = BANKROLL
    worst = 0.0
    for r in closed:
        bankroll += float(r["pnl"])
        peak = max(peak, bankroll)
        worst = max(worst, (peak - bankroll) / peak * 100)
    gaps = [float(r["gap_pts"]) for r in rows if r.get("gap_pts") is not None]
    return {"bankroll": bankroll, "return_pct": (bankroll - BANKROLL) / BANKROLL * 100, "max_drawdown_pct": worst,
            "resolved": len(closed), "open": sum(r["status"] == "open" for r in rows),
            "win_rate": sum(float(r["pnl"]) > 0 for r in closed) / len(closed) if closed else None,
            "avg_entry_gap_pts": sum(gaps) / len(gaps) if gaps else None}
