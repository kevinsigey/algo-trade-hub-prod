"""The section 5 band watch: held positions get flags (never orders), band
crossings and new guidance queue debate triggers by the frozen priority —
crossings first, new guidance next, refresh last."""
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from tradehub.valuation import verdict_store, watch
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


class _PrintDS(_DS):
    """A price layer with earnings prints for one ticker only."""

    def __init__(self, *print_dates, ticker="AMGN"):
        self.print_dates = list(print_dates)
        self.ticker = ticker

    def earnings_dates(self, ticker):
        if ticker != self.ticker:
            return pd.DataFrame()
        return pd.DataFrame(index=pd.to_datetime(self.print_dates))


def _prior_ticker_state(client, ticker="AMGN", *, zone="neutral",
                        price=300.0,
                        last_guide_at="2026-11-05T12:00:00+00:00"):
    verdict_store.set_watch_state(client, {
        "key": f"ticker:{ticker}", "kind": "ticker", "ticker": ticker,
        "zone": zone, "price": price, "last_guide_at": last_guide_at})


def _rendered_trigger(client, ticker, kind, created_at, **detail):
    verdict_store.insert_trigger(client, {
        "ticker": ticker, "kind": kind, "priority": watch.PRIORITY[kind],
        "state": "done", "created_at": created_at, "detail": detail})


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


def test_done_falsifier_suppresses_same_print_and_drains_nothing(caplog):
    client = _client()
    _rendered_trigger(client, "AMGN", "falsifier_window",
                      "2026-11-09T10:00:00+00:00",
                      within_days=watch.PRINT_WINDOW_DAYS,
                      print_date="2026-11-12")
    ds = _PrintDS("2026-11-12")
    with caplog.at_level(logging.INFO, logger="tradehub.valuation.watch"):
        out = watch.compute_watch(client, ds, positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0
    assert out["triggers_suppressed"] == 1
    pending = [t for t in verdict_store.pending_triggers(client)
               if t["ticker"] == "AMGN" and t["kind"] == "falsifier_window"]
    assert pending == []
    rendered = watch.drain_triggers(client, ds, chat=_chat, now=NOW)
    assert all(r["ticker"] != "AMGN" for r in rendered)
    assert "valuation watch: suppressed falsifier_window re-fire for AMGN " \
           "(same print_date)" in caplog.text


def test_different_print_date_queues_a_new_falsifier():
    client = _client()
    _rendered_trigger(client, "AMGN", "falsifier_window",
                      "2026-11-09T10:00:00+00:00",
                      within_days=watch.PRINT_WINDOW_DAYS,
                      print_date="2026-11-12")
    later = datetime(2027, 2, 8, 15, 0, tzinfo=timezone.utc)
    ds = _PrintDS("2027-02-10")
    out = watch.compute_watch(client, ds, positions_fn=_positions, now=later)
    assert out["triggers_queued"] == 1
    assert out["triggers_suppressed"] == 0
    pending = [t for t in verdict_store.pending_triggers(client)
               if t["ticker"] == "AMGN" and t["kind"] == "falsifier_window"]
    assert len(pending) == 1
    assert pending[0]["detail"]["print_date"] == "2027-02-10"
    assert pending[0]["detail"]["within_days"] == watch.PRINT_WINDOW_DAYS


def test_crossing_within_cooldown_is_suppressed():
    client = _client()
    _prior_ticker_state(client, "AMGN")
    _rendered_trigger(client, "AMGN", "crossing",
                      (NOW - timedelta(hours=2)).isoformat(), band="base")
    out = watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0
    assert out["triggers_suppressed"] == 1
    assert [t for t in verdict_store.pending_triggers(client)
            if t["ticker"] == "AMGN"] == []


def test_crossing_after_cooldown_queues():
    client = _client()
    _prior_ticker_state(client, "AMGN")
    _rendered_trigger(client, "AMGN", "crossing",
                      (NOW - timedelta(hours=25)).isoformat(), band="base")
    out = watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 1
    assert out["triggers_suppressed"] == 0
    pending = [t for t in verdict_store.pending_triggers(client)
               if t["ticker"] == "AMGN" and t["kind"] == "crossing"]
    assert len(pending) == 1


def test_done_guidance_with_same_recorded_at_is_suppressed():
    client = _client()
    _prior_ticker_state(client, "AMGN", zone="short_zone_strong",
                        price=460.42, last_guide_at="2026-11-01T00:00:00+00:00")
    _rendered_trigger(client, "AMGN", "new_guidance",
                      "2026-11-09T10:00:00+00:00",
                      recorded_at="2026-11-05T12:00:00+00:00")
    out = watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0
    assert out["triggers_suppressed"] == 1
    assert [t for t in verdict_store.pending_triggers(client)
            if t["ticker"] == "AMGN" and t["kind"] == "new_guidance"] == []


def test_pending_twin_is_still_skipped():
    client = _client()
    _prior_ticker_state(client, "AMGN")
    verdict_store.insert_trigger(client, {
        "ticker": "AMGN", "kind": "crossing", "priority": 1,
        "state": "pending", "created_at": NOW.isoformat(), "detail": {}})
    out = watch.compute_watch(client, _DS(), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0
    assert out["triggers_suppressed"] == 0
    pending = [t for t in verdict_store.pending_triggers(client)
               if t["ticker"] == "AMGN" and t["kind"] == "crossing"]
    assert len(pending) == 1



def test_a_failed_render_does_not_suppress_the_retry():
    client = _client()
    verdict_store.insert_trigger(client, {
        "ticker": "AMGN", "kind": "falsifier_window",
        "priority": watch.PRIORITY["falsifier_window"], "state": "failed",
        "created_at": "2026-11-09T10:00:00+00:00",
        "detail": {"within_days": watch.PRINT_WINDOW_DAYS, "print_date": "2026-11-12"}})
    out = watch.compute_watch(client, _PrintDS("2026-11-12"), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 1 and out["triggers_suppressed"] == 0


def test_a_legacy_falsifier_row_without_print_date_suppresses_inside_the_window():
    # Rows rendered before this fix carry no print_date; one inside the print
    # window must not let the first pass after deploy render the name again.
    client = _client()
    _rendered_trigger(client, "AMGN", "falsifier_window",
                      (NOW - timedelta(days=1)).isoformat(),
                      within_days=watch.PRINT_WINDOW_DAYS)
    out = watch.compute_watch(client, _PrintDS("2026-11-12"), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0 and out["triggers_suppressed"] == 1


def test_newer_failed_rows_do_not_hide_a_completed_trigger():
    # The 50-row window must count completed triggers only: a burst of newer
    # failed renders can't push the done row out and let a duplicate through.
    client = _client()
    _rendered_trigger(client, "AMGN", "falsifier_window",
                      (NOW - timedelta(days=2)).isoformat(),
                      within_days=watch.PRINT_WINDOW_DAYS, print_date="2026-11-12")
    for i in range(55):
        verdict_store.insert_trigger(client, {
            "ticker": "AMGN", "kind": "falsifier_window",
            "priority": watch.PRIORITY["falsifier_window"], "state": "failed",
            "created_at": (NOW - timedelta(hours=40 - i // 2)).isoformat(),
            "detail": {"within_days": watch.PRINT_WINDOW_DAYS, "print_date": "2026-11-12"}})
    out = watch.compute_watch(client, _PrintDS("2026-11-12"), positions_fn=_positions, now=NOW)
    assert out["triggers_queued"] == 0 and out["triggers_suppressed"] == 1
