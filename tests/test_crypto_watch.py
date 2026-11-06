"""The crypto watcher (Kevin, 2026-11-06): live market-structure signals with plain explainers, the way the
Hormuz watcher reads shipping. Pure functions here; the network is faked."""
import math

from tradehub import crypto_watch as cw


def test_funding_is_shown_as_an_annual_rate():
    assert cw.annualized_funding_pct(0.0000125) == round(0.0000125 * 24 * 365 * 100, 2)


def test_percentile_of_the_current_value_in_its_own_history():
    hist = list(range(1, 101))
    assert cw.percentile(50, hist) == 49.5  # ties count half
    assert cw.percentile(1, [1, 1, 1, 1]) == 50.0  # a value equal to every hour is the middle, not the top
    assert cw.percentile(101, hist) == 100.0
    assert cw.percentile(5, []) is None


def test_realized_volatility_is_annualized_from_hourly_closes():
    closes = [100 * math.exp(0.01 * (1 if i % 2 else -1)) for i in range(50)]
    rv = cw.realized_vol_pct(closes)
    assert 0 < rv and abs(rv - 0.02 * math.sqrt(24 * 365) * 100) < 1


def test_stress_is_the_weighted_mean_of_the_signals_that_can_speak():
    signals = [{"stress": 0.8, "weight": 2}, {"stress": 0.0, "weight": 2}, {"stress": None, "weight": 5}]
    assert cw.aggregate(signals) == {"stress": 0.4, "label": "Watch", "speaking": 2, "of": 3}
    assert cw.aggregate([{"stress": None, "weight": 1}])["stress"] is None


def _fakes(**over):
    base = {
        "ctx": lambda: {"BTC": {"funding": "0.0001", "openInterest": "40000", "premium": "-0.0003", "markPx": "76000",
                                "prevDayPx": "80000", "dayNtlVlm": "4800000000"},
                        "ETH": {"funding": "0.0000125", "openInterest": "960000", "premium": "0.0001", "markPx": "2240",
                                "prevDayPx": "2431", "dayNtlVlm": "1500000000"}},
        "funding_history": lambda coin: [0.0000125] * 400 + [0.00005] * 100,
        "closes": lambda coin: [100.0 + (i % 3) for i in range(24 * 30)],
        "dvol": lambda coin: [40.0] * 600 + [60.0],
        "stablecoins": lambda: [290e9] * 30 + [293.7e9],
        "fees": lambda: {"fastestFee": 5, "hourFee": 1},
    }
    base.update(over)
    return base


def test_the_watch_reads_every_signal_with_a_plain_sentence():
    out = cw.build_watch(**_fakes())
    btc = out["coins"]["BTC"]
    assert btc["price"] == 76000.0 and round(btc["change_24h_pct"], 1) == -5.0
    keys = [s["key"] for s in btc["signals"]]
    assert keys == ["funding", "premium", "realized_vol", "implied_vol", "open_interest"]
    funding = btc["signals"][0]
    assert funding["value"] == cw.annualized_funding_pct(0.0001) and funding["percentile"] == 100.0
    assert funding["reading"] and funding["why"]
    assert out["market"][0]["key"] == "stablecoins" and out["market"][1]["key"] == "fees"
    assert out["stress"]["label"] in ("Calm", "Watch", "Stressed")


def test_a_missing_source_leaves_only_its_own_signal_unknown():
    def down(*_a):
        raise cw.SourceDown("deribit")
    out = cw.build_watch(**_fakes(dvol=down))
    implied = next(s for s in out["coins"]["BTC"]["signals"] if s["key"] == "implied_vol")
    assert implied["value"] is None and implied["stress"] is None and "unavailable" in implied["reading"]
    funding = out["coins"]["BTC"]["signals"][0]
    assert funding["value"] is not None


def test_the_route_reads_unavailable_rather_than_erroring(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import main

    def boom():
        raise RuntimeError("all sources down")

    monkeypatch.setattr(cw, "watch", boom)
    body = TestClient(main.app).get("/api/crypto/watch").json()
    assert body == {"state": "unavailable"}
