"""Guidance rebuild wired alerts: a held name's band crossing arms a
Level Watcher watch and opens a manual action (the acceptance test);
non-held names and first sightings never fire; re-runs are no-ops."""
from datetime import UTC, datetime

from workshop_fake import DB

from tradehub.valuation import guidance_alerts as ga
from tradehub.valuation import store

T0 = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 16, 14, 0, tzinfo=UTC)
BANDS = {"bear": 90.0, "base": 110.0, "bull": 130.0}


def _hist(ticker, *, snapshot_id, price, bands=BANDS):
    return {"snapshot_id": snapshot_id, "ticker": ticker,
            "band_basis": "eps", "guide_metric": "eps_adjusted",
            "guide_unit": "usd_per_share", "guide_low": 5.0,
            "guide_high": 6.0, "direction": "held",
            "peer_multiple": 20.0,
            "bear": bands["bear"] if bands else None,
            "base": bands["base"] if bands else None,
            "bull": bands["bull"] if bands else None,
            "price": price, "zone": "neutral",
            "computed_at": T1.isoformat()}


def _snap(db, at):
    sid = store.begin_snapshot(db, at, source="valuation_run")
    store.complete_snapshot(db, sid, sheet_count=1, banded_count=1)
    return sid


# ── detection (pure) ─────────────────────────────────────────────────────────

HELD = {"HELD": {"books": ["main"], "qty": 10.0, "sleeves": []}}


def test_detects_entry_into_buy_zone_for_held_only():
    prev = [_hist("HELD", snapshot_id=1, price=125.0),
            _hist("FREE", snapshot_id=1, price=125.0)]
    latest = [_hist("HELD", snapshot_id=2, price=100.0),
              _hist("FREE", snapshot_id=2, price=100.0)]
    out = ga.detect_crossings(latest, prev, HELD)
    assert len(out) == 1
    assert out[0]["ticker"] == "HELD"
    assert out[0]["kind"] == "entered_buy_zone"
    assert out[0]["level"] == 110.0
    assert out[0]["books"] == ["main"]


def test_detects_break_below_bear():
    prev = [_hist("HELD", snapshot_id=1, price=100.0)]
    latest = [_hist("HELD", snapshot_id=2, price=85.0)]
    out = ga.detect_crossings(latest, prev, HELD)
    kinds = {c["kind"] for c in out}
    assert "broke_below_bear" in kinds
    bear = next(c for c in out if c["kind"] == "broke_below_bear")
    assert bear["level"] == 90.0


def test_first_sighting_and_no_move_are_not_crossings():
    latest = [_hist("HELD", snapshot_id=2, price=100.0)]
    assert ga.detect_crossings(latest, [], HELD) == []
    same = [_hist("HELD", snapshot_id=1, price=100.0)]
    assert ga.detect_crossings(latest, same, HELD) == []


# ── the wired pass (acceptance) ──────────────────────────────────────────────

def _positions(book):
    return {"main": {"HELD": 10.0}, "big": {}}.get(book, {})


def _db_with_crossing():
    db = DB()
    s1 = _snap(db, T0)
    s2 = _snap(db, T1)
    store.insert_history(db, [
        _hist("HELD", snapshot_id=s1, price=125.0),
        _hist("HELD", snapshot_id=s2, price=100.0)])
    return db


def test_held_crossing_arms_watch_and_opens_manual_action():
    db = _db_with_crossing()
    out = ga.run_alerts(db, positions_fn=_positions, now=T1)
    assert out["ran"] is True
    assert out["watches_armed"] == 1
    assert out["actions_opened"] == 1
    watches = db.table("level_watches").select("*").execute().data
    assert len(watches) == 1
    w = watches[0]
    assert w["family"] == "guidance_band"
    assert w["instrument"] == "HELD"
    assert float(w["level"]) == 110.0
    assert w["intent"] == "alert" and w["rung"] == 1
    actions = db.table("manual_actions").select("*").execute().data
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "band_crossing_review"
    assert a["book"] == "main" and a["symbol"] == "HELD"
    # state is the schema default ('open'); the fake does not apply
    # column defaults, so assert it only when the row carries it.
    assert a.get("state") in (None, "open")


def test_rerun_over_the_same_pair_is_a_noop():
    db = _db_with_crossing()
    ga.run_alerts(db, positions_fn=_positions, now=T1)
    out = ga.run_alerts(db, positions_fn=_positions, now=T1)
    assert out["watches_armed"] == 0
    assert out["actions_opened"] == 0
    assert len(db.table("level_watches").select("*").execute().data) == 1
    assert len(db.table("manual_actions").select("*").execute().data) == 1


def test_no_crossing_no_wiring():
    db = DB()
    s1 = _snap(db, T0)
    s2 = _snap(db, T1)
    store.insert_history(db, [
        _hist("HELD", snapshot_id=s1, price=125.0),
        _hist("HELD", snapshot_id=s2, price=124.0)])
    out = ga.run_alerts(db, positions_fn=_positions, now=T1)
    assert out["ran"] is True and out["crossings"] == []
    assert db.table("level_watches").select("*").execute().data == []
