"""Live chain state for BTC and ETH from free public endpoints (no keys). Display only.

BTC: mempool.space (fees, mempool, difficulty retarget, hashrate). ETH: a public JSON-RPC node
(latest block, base fee, how full recent blocks were). Each chain fails soft on its own and is cached
for a minute; a failed refresh serves the last good numbers marked `stale`. A field the source did not
give is None, never 0.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from time import monotonic
from typing import Any

MEMPOOL = "https://mempool.space/api"
ETH_RPC = "https://ethereum-rpc.publicnode.com"
TIMEOUT_SECONDS = 8.0
CACHE_SECONDS = 60.0


def _num(v: Any) -> int | float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _round(v: Any, nd: int) -> float | None:
    v = _num(v)
    return None if v is None else round(v, nd)


def _get(url: str, timeout: float = TIMEOUT_SECONDS) -> Any:
    import requests

    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _rpc(method: str, params: list[Any], timeout: float = TIMEOUT_SECONDS) -> Any:
    import requests

    r = requests.post(ETH_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    r.raise_for_status()
    return r.json()["result"]


def btc_state(get: Callable[[str], Any] = _get) -> dict[str, Any]:
    fees, pool, diff, hash_ = (get(f"{MEMPOOL}/{p}") for p in (
        "v1/fees/recommended", "mempool", "v1/difficulty-adjustment", "v1/mining/hashrate/3d"))
    return {
        "height": _num(get(f"{MEMPOOL}/blocks/tip/height")),
        "fee_fastest": _num(fees.get("fastestFee")), "fee_hour": _num(fees.get("hourFee")),
        "fee_economy": _num(fees.get("economyFee")),  # sat/vB
        "mempool_txs": _num(pool.get("count")), "mempool_mb": _round((_num(pool.get("vsize")) or 0) / 1e6 or None, 1),
        "retarget_pct": _round(diff.get("difficultyChange"), 2), "blocks_to_retarget": _num(diff.get("remainingBlocks")),
        "hashrate_eh": _round((_num(hash_.get("currentHashrate")) or 0) / 1e18 or None, 0),
    }


def eth_state(rpc: Callable[[str, list[Any]], Any] = _rpc) -> dict[str, Any]:
    hist = rpc("eth_feeHistory", ["0x14", "latest", []])
    base = [int(x, 16) for x in hist["baseFeePerGas"]]
    used = [u for u in hist["gasUsedRatio"] if isinstance(u, (int, float))]
    return {
        "block": int(hist["oldestBlock"], 16) + len(used) - 1,
        "base_fee_gwei": _round(base[-1] / 1e9, 3) if base else None,
        "base_fee_20_block_avg_gwei": _round(sum(base) / len(base) / 1e9, 3) if base else None,
        "block_fullness": _round(sum(used) / len(used), 3) if used else None,  # 0.5 is the protocol's target
    }


CHAINS: dict[str, Callable[[], dict[str, Any]]] = {"btc": btc_state, "eth": eth_state}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def collect(chains: dict[str, Callable[[], dict[str, Any]]] | None = None, now: Callable[[], float] = monotonic) -> dict[str, Any]:
    chains = chains or CHAINS
    t = now()

    def one(name: str) -> dict[str, Any]:
        hit = _cache.get(name)
        if hit and t - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            result = {"chain": name, "status": "ok", **chains[name]()}
            _cache[name] = (t, result)
            return result
        except Exception as exc:  # noqa: BLE001 - fail soft per chain
            if hit:
                return {**hit[1], "stale": True}
            return {"chain": name, "status": "unavailable", "error": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=len(chains)) as pool:
        out = list(pool.map(one, chains))
    return {"as_of": datetime.now(timezone.utc).isoformat(), "chains": out}
