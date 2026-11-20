"""Crypto routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, HTTPException




log = logging.getLogger(__name__)

router = APIRouter()
_EDGE_FIELDS = ("sport", "kind", "side", "entry_price", "maker", "home", "away", "start_utc", "game_id",
                "tier", "candidate", "reject_reasons", "review", "engine_version")


@router.get("/api/onchain", tags=["Crypto"])
def get_onchain():
    """Live BTC and ETH chain state from free public endpoints; fails soft per chain, cached 60 s."""
    from tradehub.onchain import collect

    return collect()


@router.get("/api/crypto/desk", tags=["Crypto"])
def get_crypto_desk():
    """The crypto desk (step 2 of Kevin's crypto program): protocols and
    networks as companies -- price, mcap, FDV, 24h fees/revenue, P/F and
    P/S, fee trend, TVL -- from DefiLlama + CoinGecko, server-cached
    5 minutes (tradehub/crypto_desk.py)."""
    from tradehub.crypto_desk import desk

    return desk()


@router.get("/api/crypto/watch", tags=["Crypto"])
def get_crypto_watch():
    """The crypto watcher (Kevin, 2026-11-06): live BTC/ETH market-structure signals -- funding, perp
    premium, realized and implied volatility, open interest, stablecoin supply, Bitcoin fees -- each with
    a plain reading and an explainer, and a stress read from the signals that can speak. Free keyless
    sources, server-cached 5 minutes (tradehub/crypto_watch.py). Public; never a 500."""
    from tradehub import crypto_watch

    try:
        return crypto_watch.watch()
    except Exception:  # noqa: BLE001 -- the page says unavailable rather than breaking
        log.exception("api: crypto watch unavailable")
        return {"state": "unavailable"}


@router.get("/api/crypto/board", tags=["Crypto"])
def get_crypto_board():
    """Tracked Kalshi crypto markets (phase-3 §5): the hourly ladder's
    coin-flip line and the 15-minute market's implied probability, per coin,
    beside Kraken spot. Market data, not predictions; each series is guarded
    separately inside live_board, so a dead read nulls its own cell."""
    from tradehub.crypto_board import live_board

    return live_board()


@router.get("/api/crypto/sniper-verdict", tags=["Crypto"])
def get_sniper_verdict():
    """The retired sniper's closed record (phase-3 §5): the one-time re-grade
    snapshot written by tradehub.scripts.sniper_regrade. A missing or
    unreadable snapshot is a 503 with the reason -- never an invented record,
    and never a live refresh: this record is closed."""
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    path = _Path(_os.environ.get(
        "TRADEHUB_SNIPER_VERDICT",
        str(_Path(__file__).resolve().parents[1] / "data" / "sniper_verdict.json"),
    ))
    try:
        return _json.loads(path.read_text())
    except FileNotFoundError:
        raise HTTPException(503, detail=f"no sniper verdict snapshot at {path} -- "
                                        "the one-time re-grade (tradehub.scripts.sniper_regrade) has not been run")
    except (OSError, ValueError) as exc:
        raise HTTPException(503, detail=f"sniper verdict snapshot at {path} is unreadable: {exc}")
