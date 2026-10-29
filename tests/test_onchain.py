from tradehub import onchain

FEES = {"fastestFee": 4, "hourFee": 1, "economyFee": 1}
POOL = {"count": 55000, "vsize": 22_300_000}
DIFF = {"difficultyChange": 5.8304, "remainingBlocks": 113}
HASH = {"currentHashrate": 1.076e21}


def _get(url):
    return {"fees/recommended": FEES, "mempool": POOL, "difficulty-adjustment": DIFF,
            "hashrate/3d": HASH, "tip/height": 973615}[next(k for k in ("fees/recommended", "mempool", "difficulty-adjustment", "hashrate/3d", "tip/height") if url.endswith(k))]


def test_btc_state_reads_the_four_endpoints():
    s = onchain.btc_state(_get)
    assert (s["fee_fastest"], s["mempool_txs"], s["mempool_mb"], s["retarget_pct"], s["hashrate_eh"]) == (4, 55000, 22.3, 5.83, 1076.0)


def test_a_missing_field_is_none_not_zero():
    s = onchain.btc_state(lambda u: 5 if u.endswith("height") else {})
    assert s["fee_fastest"] is None and s["mempool_mb"] is None and s["hashrate_eh"] is None


def test_eth_state_from_fee_history():
    hist = {"oldestBlock": "0x10", "baseFeePerGas": ["0x3b9aca00", "0x77359400", "0x3b9aca00"], "gasUsedRatio": [0.4, 0.6]}
    s = onchain.eth_state(lambda m, p: hist)
    assert s["block"] == 0x11 and s["base_fee_gwei"] == 1.0 and s["base_fee_20_block_avg_gwei"] == 1.333 and s["block_fullness"] == 0.5


def test_one_failing_chain_does_not_take_the_other_down_and_stale_is_marked():
    onchain._cache.clear()
    calls = {"btc": 0}

    def btc():
        calls["btc"] += 1
        if calls["btc"] > 1:
            raise RuntimeError("down")
        return {"height": 1}

    def eth():
        raise RuntimeError("down")

    t = [0.0]
    first = onchain.collect({"btc": btc, "eth": eth}, now=lambda: t[0])
    assert [c["status"] for c in first["chains"]] == ["ok", "unavailable"]
    t[0] = 120.0  # past the cache
    second = onchain.collect({"btc": btc, "eth": eth}, now=lambda: t[0])
    assert second["chains"][0]["stale"] is True and second["chains"][0]["height"] == 1
