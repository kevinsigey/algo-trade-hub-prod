"""The section 5 band watch: held positions get flags (never orders), band
crossings and new guidance queue debate triggers by the frozen priority —
crossings first, new guidance next, refresh last."""
from datetime import datetime, timezone

import pandas as pd

from tradehub.valuation import watch
from tests.test_valuation_verdicts import FakeClient, _sheet_row

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def _chat(system, user, *, schema=None):
    """A structurer that copies its choice prices out of Exhibit A itself,
    the way the real one is instructed to."""
    import re

    if "BULL RESEARCHER" in system:
        return "bull prose", "qwen-fake"
    if "BEAR RESEARCHER" in system:
        return "bear prose", "qwen-fake"
    bands = re.search(r"Bear ([\d.]+) / Base ([\d.]+) / Bull ([\d.]+)", user)
    price = re.search(r"price ([\d.]+) as of", user)
    bear, base = float(bands.group(1)), float(bands.group(2))
    px = float(price.group(1))
    return {
        "choices": [
            {"choice_id": "act_at_band_low", "label": "Act at the low band",
             "price": bear},
            {"choice_id": "act_at_band_mid", "label": "Act at the mid band",
             "price": base},
            {"choice_id": "watch", "label": "Watch", "price": px},
            {"choice_id": "pass", "label": "Pass", "price": px},
        ],
        "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                           "direction_momentum": 0.15,
                           "options_expression": 0.1,
                           "falsifier_proximity": 0.2},
        "digest": "digest",
        "proposer_pick": {"choice_id": "watch", "direction": "none",
                          "probability": None},
        "rationale": "watch it",
    }, "qwen-fake"


class _DS:
    def prices(self, tickers, years=1):
        idx = pd.bdate_range("2026-11-02", periods=5)
        return pd.DataFrame({t: [100.0] * 5 for t in tickers}, index=idx)

    def implied_move(self, _ticker):
        return 9.0

    def earnings_dates(self, _ticker):
        return pd.DataFrame()  # no print in the window


def _client():
    client = FakeClient()
    client.tables["valuation_fact_sheets"] = [
        _sheet_row(),  # AMGN, price 460.42 above its bull band 317.92
        _sheet_row(id=42, ticker="GILD", price=168.57,
                   bands={"bear": 154.96, "base": 173.01, "bull": 173.84},
                   baseline_verdict="buy_zone"),
    ]
    client.tables["guidance_records"] = [{
        "ticker": "AMGN", "metric": "eps_adjusted", "period": "FY2026",
        "unit": "usd_per_share", "low": 18.34, "high": 19.28,
        "consensus": 18.9, "consensus_period": "FY2026",
        "consensus_source": "yf", "accession": "x",
        "created_at": "2026-11-05T12:00:00+00:00"}]
    return client


def _positions(_book):
    return {"AMGN": 10.0, "GILD": 25.0, "SPY261204C00770000": -1.0}


def test_held_position_above_the_top_band_is_a_potential_sell_flag():
    out = watch.compute_watch(_client(), _DS(), positions_fn=_positions,
                              now=NOW)
    flags = {(f["book"], f["underlying"]): f for f in out["flags"]}
    amgn = flags[("big", "AMGN")] if ("big", "AMGN") in flags else \
        flags[("main", "AMGN")]
    assert amgn["flag"] == "potential_sell"
    assert amgn["detail"] == "above_bull"


def test_held_position_inside_its_bands_is_a_comfortable_hold():
    out = watch.compute_watch(_client(), _DS(), positions_fn=_positions,
                              now=NOW)
    gild = [f for f in out["flags"] if f["underlying"] == "GILD"][0]
    assert gild["flag"] == "comfortable_hold"
    assert gild["detail"] == "inside_bands"


def test_options_positions_resolve_to_their_underlying():
    out = watch.compute_watch(_client(), _DS(), positions_fn=_positions,
                              now=NOW)
    # SPY has no fact sheet, so the short SPY call produces no flag at all --
    # but a covered name's option would resolve through parse_occ.
    assert all(f["underlying"] != "SPY" for f in out["flags"])
    assert watch.underlying("AMGN261204C00200000") == "AMGN"
    assert watch.underlying("AMGN") == "AMGN"


def test_crossing_queues_a_priority_one_trigger_exactly_once():
    client = _client()
    # prior state: AMGN's zone was neutral at a lower price
    from tradehub.valuation import verdict_store

    verdict_store.set_watch_state(client, {
        "key": "ticker:AMGN", "kind": "ticker", "ticker": "AMGN",
        "zone": "neutral", "price": 300.0,
        "last_guide_at": "2026-11-05T12:00:00+00:00"})
    watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    pending = verdict_store.pending_triggers(client)
    crossings = [t for t in pending if t["ticker"] == "AMGN"
                 and t["kind"] == "crossing"]
    assert len(crossings) == 1
    assert crossings[0]["priority"] == 1


def test_new_guidance_queues_a_priority_two_trigger():
    client = _client()
    from tradehub.valuation import verdict_store

    verdict_store.set_watch_state(client, {
        "key": "ticker:GILD", "kind": "ticker", "ticker": "GILD",
        "zone": "buy_zone", "price": 168.57,
        "last_guide_at": "2026-11-01T00:00:00+00:00"})
    client.tables["guidance_records"].append({
        "ticker": "GILD", "metric": "revenue", "period": "FY2026",
        "unit": "usd", "low": 31.0e9, "high": 31.3e9, "consensus": None,
        "consensus_period": None, "consensus_source": None, "accession": "y",
        "created_at": "2026-11-08T00:00:00+00:00"})
    watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    pending = verdict_store.pending_triggers(client)
    guidance = [t for t in pending if t["ticker"] == "GILD"
                and t["kind"] == "new_guidance"]
    assert len(guidance) == 1 and guidance[0]["priority"] == 2


def test_drain_renders_by_priority_and_marks_triggers_done():
    client = _client()
    from tradehub.valuation import verdict_store

    verdict_store.insert_trigger(client, {
        "ticker": "GILD", "kind": "new_guidance", "priority": 2,
        "state": "pending", "created_at": NOW.isoformat(), "detail": {}})
    verdict_store.insert_trigger(client, {
        "ticker": "AMGN", "kind": "crossing", "priority": 1,
        "state": "pending", "created_at": NOW.isoformat(), "detail": {}})
    rendered = watch.drain_triggers(client, _DS(), chat=_chat, now=NOW)
    assert [r["ticker"] for r in rendered] == ["AMGN", "GILD"]  # priority 1 first
    assert verdict_store.pending_triggers(client) == []
    assert len(client.tables["valuation_verdicts"]) == 2
