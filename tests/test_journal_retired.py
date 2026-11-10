"""The 2026-11-10 retirement: retired rows stop freezing but still settle and score."""

from datetime import UTC, datetime

from tradehub.journal import runner


def test_retired_and_live_are_disjoint_and_keep_the_right_rows():
    from tradehub.journal.registry import FORECASTERS, RETIRED

    live = {(f.name, f.version) for f in FORECASTERS}
    retired = {(f.name, f.version) for f in RETIRED}
    assert not live & retired
    for key in (("oil_wti", "wti-v1"), ("oil_brent", "brent-v1"), ("natgas_daily", "natgas-v1"), ("gas", "v2"),
                ("weather_high", "ens-v2.1"), ("weather_low_nbm", "nbm-v1"), ("ercot_peak", "ls-v1"),
                ("sports_cfb_spread", "feed-v1"), ("sports_nfl_cal", "feed-v1+cal"),
                ("oil_wti_hourly", "wti-hourly-v1"), ("oil_wti_hourly", "wti-hourly-v6-hl-geo2-shadow"),
                ("kalshi_implied_oil", "v1"), ("baseline_climatology_weather_high", "v1")):
        assert key in retired, key
    for key in (("oil_wti_hourly", "wti-hourly-v4-hl-shadow"), ("kalshi_implied_oil_hourly", "v1"),
                ("natgas_15m", "natgas-15m-v2"), ("weather_rain", "ens-v2.1"), ("sports_nfl", "feed-v1"),
                ("kalshi_implied_weather_rain", "v1"), ("crypto_btc_hourly", "btc-hourly-v1")):
        assert key in live, key


def test_a_retired_forecaster_takes_no_new_targets(monkeypatch):
    class Fc:
        name, version, cadence = "x", "v1", "daily"

        def targets(self, now):
            raise AssertionError("a retired forecaster must not be asked for targets")

        def settle(self, target, now):
            return None

    calls = []
    monkeypatch.setattr(runner.store, "register_calendar", lambda supa, entries, now: len(entries))
    monkeypatch.setattr(runner.store, "fetch_forecasts", lambda *a, **k: [])
    monkeypatch.setattr(runner.store, "fetch_calendar", lambda *a, **k: {})
    monkeypatch.setattr(runner.store, "fetch_settlements", lambda *a, **k: {})
    monkeypatch.setattr(runner.store, "upsert_score", lambda *a, **k: calls.append(a))
    out = runner.run_journal(None, [], datetime(2026, 11, 10, tzinfo=UTC), retired=[Fc()])
    assert out["failures"] == []
    assert out["forecasters"]["x@v1"]["frozen"] == 0
    assert len(calls) == 1  # still scored
