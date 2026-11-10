"""Spec D — Level Watcher, Stage 1 (Rung 1): the trigger engine, its
conditions, idempotency, governor, heartbeat/down detection, grading +
automatic demotion, and the Spec C band-crossing integration (one
detector: the watcher drives band_crossing's own state machine).

Every fire test runs a clearly-labeled TEST watch through a fake feed
in a test harness — nothing here touches a live book.
"""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from workshop_fake import DB

from tradehub import level_watcher as lw
from tradehub.valuation import band_crossing as bc

ET = ZoneInfo("America/New_York")
MON = date(2026, 11, 9)          # a Monday
FOMC_DAY = date(2026, 12, 9)     # a Wednesday, FOMC statement 14:00 ET


def at(day, hh, mm, ss=0):
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=ET)


def bar(day, hh, mm, *, o, h, l, c, v=1_000):
    return {"t": at(day, hh, mm), "o": float(o), "h": float(h),
            "l": float(l), "c": float(c), "v": float(v)}


def flat_bars(day, start, minutes, price, *, v=1_000):
    """`minutes` consecutive 1-min bars from `start` (an ET time), all
    opening/closing at `price` with a 0.10 range."""
    out = []
    t0 = datetime.combine(day, start, tzinfo=ET)
    for i in range(minutes):
        t = t0 + timedelta(minutes=i)
        out.append({"t": t, "o": price, "h": price + 0.05,
                    "l": price - 0.05, "c": price, "v": float(v)})
    return out


class FakeFeed:
    def __init__(self, bars=None, prices=None, history=None):
        self._bars = bars or {}
        self._prices = prices or {}
        self._history = history or {}

    def bars_today(self, symbol, now):
        return list(self._bars.get(symbol, []))

    def latest_trade(self, symbol):
        return self._prices[symbol]

    def bars_between(self, symbol, start, end):
        return list(self._history.get((symbol, start.date().isoformat()), []))


def watch(**kw):
    base = {"id": 1, "name": "TEST — harness watch", "family": "test-family",
            "kind": "level", "instrument": "SPY", "trigger_type": "cross_up",
            "level": 100.0, "level_hi": None, "hold_minutes": None,
            "conditions": {}, "intent": "long", "rung": 1, "book": None,
            "action": None, "governor_group": None, "allow_multi_fire": False,
            "enabled": True, "expires_at": None, "disabled_reason": None,
            "note": "test harness only"}
    base.update(kw)
    return base


def rig(watches, feed, **tick_kw):
    db = DB()
    db.db["level_watches"] = [dict(w) for w in watches]
    return db, feed, tick_kw


def tick(db, feed, now, **kw):
    return lw.run_tick(db, now=now, feed=feed, **kw)


def fires(db):
    return db.db.get("watcher_fires", [])


def alerts(db, kind=None):
    rows = db.db.get("watcher_alerts", [])
    return [r for r in rows if kind is None or r.get("kind") == kind]


# ── cross triggers + the fire record ─────────────────────────────────────────

def cross_feed(price=100.60):
    bars = [bar(MON, 9, 58, o=99.5, h=99.6, l=99.4, c=99.50),
            bar(MON, 9, 59, o=99.5, h=99.9, l=99.5, c=99.90)]
    return FakeFeed(bars={"SPY": bars}, prices={"SPY": price})


def test_cross_up_fires_writes_fire_and_pending_alert():
    db, feed, _ = rig([watch()], cross_feed())
    out = tick(db, feed, at(MON, 10, 0))
    assert len(out["fired"]) == 1
    rows = fires(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["instrument"] == "SPY" and row["rung_effective"] == 1
    assert row["trigger_price"] == pytest.approx(100.60)
    assert row["session_date"] == "2026-11-09"
    assert row["idempotency_key"] == f"{row['watch_id']}:2026-11-09"
    assert row["price_path_past"], "the -5min price path rides the fire"
    got = alerts(db, "trigger")
    assert len(got) == 1 and got[0]["status"] == "pending"
    assert "SPY" in got[0]["body"] and "100" in got[0]["body"]


def test_cross_up_needs_the_cross_not_just_the_side():
    # Previous completed close already above the level: no cross.
    bars = [bar(MON, 9, 30, o=100.5, h=100.6, l=100.4, c=100.50),
            bar(MON, 9, 31, o=100.5, h=100.9, l=100.5, c=100.90)]
    db, feed, _ = rig([watch()], FakeFeed(bars={"SPY": bars},
                                          prices={"SPY": 101.20}))
    out = tick(db, feed, at(MON, 10, 0))
    assert out["fired"] == [] and fires(db) == []


def test_cross_down_fires():
    bars = [bar(MON, 9, 30, o=100.5, h=100.6, l=100.4, c=100.50),
            bar(MON, 9, 31, o=100.4, h=100.5, l=100.1, c=100.10)]
    w = watch(trigger_type="cross_down", intent="short")
    db, feed, _ = rig([w], FakeFeed(bars={"SPY": bars}, prices={"SPY": 99.40}))
    out = tick(db, feed, at(MON, 10, 0))
    assert len(out["fired"]) == 1


def test_watch_above_rung1_still_fires_as_rung1_in_stage1():
    db, feed, _ = rig([watch(rung=3)], cross_feed())
    tick(db, feed, at(MON, 10, 0))
    assert fires(db)[0]["rung_effective"] == 1


def test_expired_and_disabled_watches_do_not_fire():
    db, feed, _ = rig([watch(expires_at="2026-11-08T00:00:00+00:00")],
                      cross_feed())
    assert tick(db, feed, at(MON, 10, 0))["fired"] == []
    db2, feed2, _ = rig([watch(enabled=False)], cross_feed())
    assert tick(db2, feed2, at(MON, 10, 0))["fired"] == []


def test_no_evaluation_outside_market_hours():
    db, feed, _ = rig([watch()], cross_feed())
    sunday = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
    out = tick(db, feed, sunday)
    assert out["fired"] == [] and out["market_hours"] is False
    assert db.db.get("watcher_heartbeats", []) == []


# ── idempotency (incl. the restart re-touch) ─────────────────────────────────

def test_one_fire_per_day_and_restart_retouch_cannot_double_fire():
    db, feed, _ = rig([watch()], cross_feed())
    tick(db, feed, at(MON, 10, 0))
    # A restart re-derives state from bars alone and re-touches the level:
    # the day's fire already exists, so nothing fires again.
    out = tick(db, feed, at(MON, 10, 5))
    assert out["fired"] == [] and len(fires(db)) == 1
    assert len(alerts(db, "trigger")) == 1


def test_multi_fire_watch_may_fire_again():
    db, feed, _ = rig([watch(allow_multi_fire=True)], cross_feed())
    tick(db, feed, at(MON, 10, 0))
    out = tick(db, feed, at(MON, 10, 5))
    assert len(out["fired"]) == 1 and len(fires(db)) == 2


# ── conditions ───────────────────────────────────────────────────────────────

def test_vwap_side_blocks_when_price_is_on_the_wrong_side():
    # Bars sit below the trigger price all morning: VWAP ~99.7 < price,
    # so vwap_side 'below' fails even though the cross fires.
    w = watch(conditions={"vwap_side": "below"})
    db, feed, _ = rig([w], cross_feed())
    out = tick(db, feed, at(MON, 10, 0))
    assert out["fired"] == []
    w2 = watch(conditions={"vwap_side": "above"})
    db2, feed2, _ = rig([w2], cross_feed())
    assert len(tick(db2, feed2, at(MON, 10, 0))["fired"]) == 1


def test_time_window_blocks_outside_the_window():
    w = watch(conditions={"time_window": {"start_et": "11:00", "end_et": "12:00"}})
    db, feed, _ = rig([w], cross_feed())
    assert tick(db, feed, at(MON, 10, 0))["fired"] == []
    w2 = watch(conditions={"time_window": {"start_et": "09:30", "end_et": "12:00"}})
    db2, feed2, _ = rig([w2], cross_feed())
    assert len(tick(db2, feed2, at(MON, 10, 0))["fired"]) == 1


def test_volume_multiple_uses_the_same_minute_baseline():
    bars = [bar(MON, 9, 30, o=99.5, h=99.6, l=99.4, c=99.50, v=800),
            bar(MON, 9, 31, o=99.5, h=99.9, l=99.5, c=99.90, v=3_000)]
    history = {}
    for back in range(1, 11):
        d = MON - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        history[("SPY", d.isoformat())] = [
            bar(d, 9, 30, o=1, h=1, l=1, c=1, v=700),
            bar(d, 9, 31, o=1, h=1, l=1, c=1, v=1_000)]
    feed = FakeFeed(bars={"SPY": bars}, prices={"SPY": 100.60},
                    history=history)
    w = watch(conditions={"volume_multiple": 2.0})  # 3000 >= 2 x median 1000
    db, _, _ = rig([w], feed)
    assert len(tick(db, feed, at(MON, 9, 32))["fired"]) == 1
    w2 = watch(conditions={"volume_multiple": 4.0})  # 3000 < 4 x 1000
    db2, _, _ = rig([w2], feed)
    assert tick(db2, feed, at(MON, 9, 32))["fired"] == []


def test_volume_multiple_without_baseline_never_fires():
    db, feed, _ = rig([watch(conditions={"volume_multiple": 1.5})],
                      cross_feed())
    assert tick(db, feed, at(MON, 10, 0))["fired"] == []


def test_file_state_cannot_fire_without_a_classification_store():
    w = watch(conditions={"file_state": "intact_or_better"})
    db, feed, _ = rig([w], cross_feed())
    out = tick(db, feed, at(MON, 10, 0))
    assert out["fired"] == []
    assert out["evaluated"][0]["detail"]["conditions"]["file_state"]["reason"] \
        == "no_t1_classification"


def test_fomc_blackout_suppresses_and_event_watch_is_exempt():
    bars = [bar(FOMC_DAY, 13, 30, o=99.5, h=99.6, l=99.4, c=99.50),
            bar(FOMC_DAY, 13, 31, o=99.5, h=99.9, l=99.5, c=99.90)]
    feed = FakeFeed(bars={"SPY": bars}, prices={"SPY": 100.60})
    db, _, _ = rig([watch()], feed)
    # 13:45 ET is inside the +/-30min blackout of the 14:00 statement.
    out = tick(db, feed, at(FOMC_DAY, 13, 45))
    assert out["fired"] == []
    assert out["evaluated"][0]["detail"]["conditions"]["blackout"]["pass"] is False
    w = watch(conditions={"event_watch": True})
    db2, _, _ = rig([w], feed)
    assert len(tick(db2, feed, at(FOMC_DAY, 13, 45))["fired"]) == 1
    # And the blackout does not consume the day's fire: after the window
    # the same watch can still fire.
    bars2 = [bar(FOMC_DAY, 14, 35, o=99.5, h=99.6, l=99.4, c=99.50),
             bar(FOMC_DAY, 14, 36, o=99.5, h=99.9, l=99.5, c=99.90)]
    feed2 = FakeFeed(bars={"SPY": bars2}, prices={"SPY": 100.60})
    assert len(tick(db, feed2, at(FOMC_DAY, 14, 37))["fired"]) == 1


# ── touch_and_hold / zone_entry: continuity ──────────────────────────────────

def test_touch_and_hold_fires_on_a_continuous_run():
    bars = flat_bars(MON, time(9, 30), 20, 100.20)   # on-side from the open
    bars[0] = bar(MON, 9, 30, o=99.8, h=99.9, l=99.7, c=99.80)  # starts below
    bars[1] = bar(MON, 9, 31, o=99.9, h=100.1, l=99.9, c=100.05)
    for i in range(2, 20):
        bars[i] = bar(MON, 9, 30 + i, o=100.2, h=100.3, l=100.05, c=100.20)
    w = watch(trigger_type="touch_and_hold", hold_minutes=15)
    feed = FakeFeed(bars={"SPY": bars}, prices={"SPY": 100.25})
    db, _, _ = rig([w], feed)
    assert len(tick(db, feed, at(MON, 9, 50))["fired"]) == 1


def test_touch_and_hold_one_offside_bar_resets_the_run():
    bars = []
    for i in range(20):
        hh, mm = 9, 30 + i
        if i == 10:  # dips below the level: the run restarts here
            bars.append(bar(MON, hh, mm, o=100.2, h=100.3, l=99.90, c=100.10))
        else:
            bars.append(bar(MON, hh, mm, o=100.2, h=100.3, l=100.05, c=100.20))
    w = watch(trigger_type="touch_and_hold", hold_minutes=15)
    feed = FakeFeed(bars={"SPY": bars}, prices={"SPY": 100.25})
    db, _, _ = rig([w], feed)
    assert tick(db, feed, at(MON, 9, 50))["fired"] == []


def test_zone_entry_with_hold_needs_entry_plus_continuous_minutes_inside():
    w = watch(trigger_type="zone_entry", level=258.0, level_hi=262.0,
              hold_minutes=15, instrument="CEG")
    bars = [bar(MON, 9, 30, o=250, h=251, l=249, c=250.0)]  # outside (below)
    for i in range(15):
        hh, mm = 9, 31 + i
        bars.append(bar(MON, hh, mm, o=260, h=261, l=259, c=260.0))
    feed = FakeFeed(bars={"CEG": bars}, prices={"CEG": 260.50})
    db, _, _ = rig([w], feed)
    assert len(tick(db, feed, at(MON, 9, 46))["fired"]) == 1
    # One minute less of hold: no fire.
    feed2 = FakeFeed(bars={"CEG": bars[:-1]}, prices={"CEG": 260.50})
    db2, _, _ = rig([w], feed2)
    assert tick(db2, feed2, at(MON, 9, 45))["fired"] == []


def test_zone_entry_without_hold_fires_on_entry():
    w = watch(trigger_type="zone_entry", level=258.0, level_hi=262.0,
              instrument="CEG")
    bars = [bar(MON, 9, 30, o=250, h=251, l=249, c=250.0),
            bar(MON, 9, 31, o=259, h=260, l=258.5, c=259.5)]
    feed = FakeFeed(bars={"CEG": bars}, prices={"CEG": 260.0})
    db, _, _ = rig([w], feed)
    assert len(tick(db, feed, at(MON, 9, 32))["fired"]) == 1


# ── heartbeat + down detection ───────────────────────────────────────────────

def test_heartbeat_written_in_market_hours_and_status_up():
    db, feed, _ = rig([], FakeFeed())
    out = tick(db, feed, at(MON, 10, 0))
    assert out["heartbeat"] is True
    assert len(db.db["watcher_heartbeats"]) == 1
    status = lw.watcher_status(db, now=at(MON, 10, 5))
    assert status["state"] == "up"


def test_two_missed_heartbeats_read_down_and_alert_once():
    db, feed, _ = rig([], FakeFeed())
    stale = (at(MON, 10, 0) - timedelta(minutes=45)).isoformat()
    db.db["watcher_heartbeats"] = [{"id": 1, "at": stale,
                                    "session_date": "2026-11-09"}]
    out = tick(db, feed, at(MON, 10, 0))
    assert out["down_alert"] is True
    assert len(alerts(db, "watcher_down")) == 1
    # The outage is recorded once; a later tick with a fresh heartbeat
    # does not re-alert.
    out2 = tick(db, feed, at(MON, 10, 20))
    assert out2["down_alert"] is False
    assert len(alerts(db, "watcher_down")) == 1
    status = lw.watcher_status(db, now=at(MON, 10, 50))
    assert status["state"] == "up"


# ── the governor ─────────────────────────────────────────────────────────────

def _governor_rig(pnl):
    db = DB()
    db.db["watcher_governor_groups"] = [{
        "name": "g1", "standard_unit_usd": 100.0,
        "daily_profit_target_usd": 300.0, "daily_loss_stop_usd": 200.0,
        "note": "test"}]
    db.db["level_watches"] = [watch(governor_group="g1")]
    return db


def test_governor_disarms_at_the_profit_target_and_suppresses_the_group():
    db = _governor_rig(350.0)
    out = tick(db, cross_feed(), at(MON, 10, 0),
               pnl_reader=lambda group, day: 350.0)
    assert out["fired"] == []
    state = db.db["watcher_governor_state"]
    assert len(state) == 1 and state[0]["disarmed"] is True
    assert state[0]["reason"] == "profit_target_hit"
    assert len(alerts(db, "governor_stand_down")) == 1
    # The disarm holds for the rest of the session with no P&L read.
    out2 = tick(db, cross_feed(), at(MON, 10, 30))
    assert out2["fired"] == []


def test_governor_disarms_at_the_loss_stop():
    db = _governor_rig(-250.0)
    tick(db, cross_feed(), at(MON, 10, 0), pnl_reader=lambda g, d: -250.0)
    state = db.db["watcher_governor_state"]
    assert state[0]["disarmed"] is True and state[0]["reason"] == "loss_stop_hit"


def test_governor_with_unset_numbers_never_disarms():
    db = DB()
    db.db["watcher_governor_groups"] = [{
        "name": "g1", "standard_unit_usd": None,
        "daily_profit_target_usd": None, "daily_loss_stop_usd": None,
        "note": None}]
    db.db["level_watches"] = [watch(governor_group="g1")]
    out = tick(db, cross_feed(), at(MON, 10, 0),
               pnl_reader=lambda g, d: 999_999.0)
    assert len(out["fired"]) == 1
    assert db.db.get("watcher_governor_state", []) == []
    surface = lw.read_surface(db, now=at(MON, 10, 5))
    gov = surface["governors"][0]
    assert gov["numbers_set"] is False and "not set" in gov["note"]


# ── grading + automatic demotion ─────────────────────────────────────────────

class FakeDS:
    def __init__(self, closes):
        self._closes = closes

    def prices(self, tickers, years=3):
        return pd.DataFrame(self._closes)


def declining_ds():
    days = pd.bdate_range("2026-10-19", periods=40)
    closes = [200.0 - i for i in range(40)]       # falls every session
    return FakeDS({"SPY": pd.Series(closes, index=days)})


def seed_fires(db, n, *, family="fam-x", intent="long"):
    rows = []
    for i in range(n):
        rows.append({"id": i + 1, "watch_id": 1, "family": family,
                     "instrument": "SPY", "session_date": "2026-11-02",
                     "fired_at": "2026-11-02T15:00:00+00:00",
                     "rung_effective": 1, "trigger_price": 185.0,
                     "level": 184.0, "intent": intent,
                     "idempotency_key": f"1:2026-11-02:{i}",
                     "crossing_ids": None, "detail": {},
                     "price_path_past": None, "price_path_future": None,
                     "ret_1": None, "ret_5": None,
                     "score_1": None, "score_5": None})
    db.db["watcher_fires"] = rows
    return rows


def test_grading_fills_signed_scores_against_no_action():
    db = DB()
    seed_fires(db, 1)
    out = lw.grade_fires(db, declining_ds(), now=at(MON, 10, 0))
    row = db.db["watcher_fires"][0]
    assert row["ret_5"] is not None and row["ret_5"] < 0
    assert row["score_5"] == pytest.approx(row["ret_5"])   # long: sign +1
    assert row["score_1"] == pytest.approx(row["ret_1"])
    assert out["graded"] == 1


def test_demotion_at_20_negative_graded_triggers_disables_and_alerts_once():
    db = DB()
    db.db["level_watches"] = [watch(family="fam-x")]
    seed_fires(db, 20)
    lw.grade_fires(db, declining_ds(), now=at(MON, 10, 0))
    w = db.db["level_watches"][0]
    assert w["enabled"] is False and w["disabled_reason"] == "auto_demotion"
    assert len(alerts(db, "demotion")) == 1
    fam = db.db["watcher_family_state"][0]
    assert fam["graded_count"] == 20 and fam["mean_score_5"] < 0
    assert fam["demoted_at"] is not None
    # Latched: grading again does not re-alert or re-disable.
    lw.grade_fires(db, declining_ds(), now=at(MON, 10, 30))
    assert len(alerts(db, "demotion")) == 1


def test_no_demotion_below_20_graded():
    db = DB()
    db.db["level_watches"] = [watch(family="fam-x")]
    seed_fires(db, 19)
    lw.grade_fires(db, declining_ds(), now=at(MON, 10, 0))
    assert db.db["level_watches"][0]["enabled"] is True
    assert alerts(db, "demotion") == []


def test_intent_none_fires_grade_raw_only_and_skip_demotion():
    db = DB()
    db.db["level_watches"] = [watch(family="fam-x", intent="none")]
    seed_fires(db, 20, intent="none")
    lw.grade_fires(db, declining_ds(), now=at(MON, 10, 0))
    row = db.db["watcher_fires"][0]
    assert row["ret_5"] is not None and row["score_5"] is None
    assert db.db["level_watches"][0]["enabled"] is True


# ── the Spec C integration: one detector ─────────────────────────────────────

def ceg_sheet(price, *, direction="raised", snapshot_id=None):
    sheet = {"ticker": "CEG", "status": "banded",
             "bands": {"bear": 185.90, "base": 215.54, "bull": 224.52},
             "band_basis": "eps", "price": price, "price_as_of": "2026-11-07",
             "stale": False, "peer_group": "sector:Utilities",
             "anchor": {"metric": "eps_adjusted", "period": "FY2026"},
             "directions": {"eps_adjusted": {"direction": direction,
                                             "period": "FY2026"}},
             "computed_at": "2026-11-07T21:00:00Z"}
    if snapshot_id is not None:
        sheet["snapshot_id"] = snapshot_id
    return sheet


def band_rig(price):
    db = DB()
    db.db["valuation_fact_sheets"] = [ceg_sheet(price)]
    db.db["band_crossing_controls"] = [
        {"scope": "global", "orders_enabled": False, "note": "log-only"}]
    readers = dict(
        positions_reader=lambda book: {},
        equity_reader=lambda book: 100_000.0,
        t1_reader=lambda client, ticker: None,
        pc_runner=lambda book, ticker, delta: ("would_pass", "passes"))
    return db, readers


def test_watcher_evaluation_writes_nothing_before_the_baseline():
    db, readers = band_rig(220.0)
    out = bc.run_watcher_evaluation(db, prices={"CEG": 200.0}, now=at(MON, 10, 0),
                                    **readers)
    assert out["ran"] is False and out["reason"] == "no_baseline"
    assert db.db.get("band_crossings", []) == []


def test_intraday_transition_writes_one_watcher_crossing_then_scan_is_silent():
    db, readers = band_rig(220.0)          # bull zone: no candidate
    bc.run_scan(db, kind="weekly", now=at(MON, 9, 0), **readers)   # baseline
    assert db.db.get("band_crossings", []) == []
    out = bc.run_watcher_evaluation(db, prices={"CEG": 200.0},
                                    now=at(MON, 10, 0), **readers)
    assert out["ran"] is True and out["crossings_written"] == 2  # one per book
    rows = db.db["band_crossings"]
    assert all(r["scan_kind"] == "watcher" and r["action"] == "starter"
               for r in rows)
    assert all(r["price"] == 200.0 for r in rows)
    # Spec C's own scan now evaluates the same name at the same zone:
    # the state already moved, so it writes no duplicate.
    db.db["valuation_fact_sheets"] = [ceg_sheet(200.0)]
    out2 = bc.run_scan(db, kind="event", now=at(MON, 11, 0), **readers)
    assert out2["crossings_written"] == 0
    assert len(db.db["band_crossings"]) == 2


def test_watcher_rows_carry_the_band_snapshot_id_scans_omit_it():
    # The Guidance Reliability lane's provenance: a sheet stamped with
    # a persisted snapshot id passes it onto watcher-written crossing
    # rows under the clearly-named snapshot_id field; scan-written
    # rows do not carry the key at all (their inserts are unchanged).
    db, readers = band_rig(220.0)
    db.db["valuation_fact_sheets"] = [ceg_sheet(220.0, snapshot_id=77)]
    bc.run_scan(db, kind="weekly", now=at(MON, 9, 0), **readers)
    out = bc.run_watcher_evaluation(db, prices={"CEG": 200.0},
                                    now=at(MON, 10, 0), **readers)
    assert out["crossings_written"] == 2
    assert all(r["snapshot_id"] == 77 for r in db.db["band_crossings"])
    # And without a snapshot stamp on the sheet, the field is null —
    # never an invented id.
    db2, readers2 = band_rig(220.0)
    bc.run_scan(db2, kind="weekly", now=at(MON, 9, 0), **readers2)
    bc.run_watcher_evaluation(db2, prices={"CEG": 200.0},
                              now=at(MON, 10, 0), **readers2)
    assert all(r["snapshot_id"] is None for r in db2.db["band_crossings"])


def test_tick_band_watch_alerts_from_the_logged_crossing():
    db, readers = band_rig(220.0)
    bc.run_scan(db, kind="weekly", now=at(MON, 9, 0), **readers)
    db.db["level_watches"] = [watch(
        name="Band crossings — all banded names", kind="band_crossing",
        instrument="*", trigger_type="zone_entry", family="band_crossing",
        intent="none")]
    feed = FakeFeed(prices={"CEG": 200.0})
    out = lw.run_tick(db, now=at(MON, 10, 0), feed=feed, bc_readers=readers)
    assert len(out["fired"]) == 1
    row = fires(db)[0]
    assert row["instrument"] == "CEG" and len(row["crossing_ids"]) == 2
    assert len(alerts(db, "trigger")) == 1
    # Same price again: the zone no longer differs from state — no re-fire.
    out2 = lw.run_tick(db, now=at(MON, 10, 5), feed=feed, bc_readers=readers)
    assert out2["fired"] == [] and len(fires(db)) == 1


def test_tick_without_a_band_watch_never_evaluates_bands():
    db, readers = band_rig(220.0)
    bc.run_scan(db, kind="weekly", now=at(MON, 9, 0), **readers)
    feed = FakeFeed(prices={"CEG": 200.0})
    out = lw.run_tick(db, now=at(MON, 10, 0), feed=feed, bc_readers=readers)
    assert out["band"] is None
    assert db.db.get("band_crossings", []) == []


# ── the read surface ─────────────────────────────────────────────────────────

def test_surface_states_stage_rung_cap_and_the_cpi_gap():
    db, feed, _ = rig([watch()], cross_feed())
    tick(db, feed, at(MON, 10, 0))
    surface = lw.read_surface(db, now=at(MON, 10, 5))
    assert surface["stage"] == 1 and surface["rung_cap"] == 1
    assert surface["cpi_blackout_gap"] is True
    assert surface["status"]["state"] == "up"
    assert len(surface["fires"]) == 1
    assert len(surface["alerts_pending"]) == 1
    assert surface["watches"][0]["name"].startswith("TEST")
