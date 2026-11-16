"""Thesis tracker PR 6 — the kill-line bridge: theses.kill_lines
materialize as level_watches rows tagged with the thesis, and a
watcher fire on one opens ONE deduped exit_review manual action per
held book (the NVDA 2026-11-12 case: kill lines fired, no review —
now structurally impossible)."""
from datetime import UTC, datetime, timedelta

from workshop_fake import DB

from tradehub.tracker import kill_lines as kl

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)


def _thesis(db, *, slug="event-lab", status="live", lines=None, tid=1):
    db.db.setdefault("theses", []).append(
        {"id": tid, "slug": slug, "title": slug, "status": status,
         "kill_lines": lines if lines is not None else []})


def _watches(db):
    return db.db.get("level_watches", [])


def _actions(db):
    return db.db.get("manual_actions", [])


def _fire(db, *, watch_id, fired_at, fid=1, symbol="NVDA"):
    db.db.setdefault("watcher_fires", []).append(
        {"id": fid, "watch_id": watch_id, "family": kl.FAMILY,
         "instrument": symbol, "fired_at": fired_at.isoformat(),
         "trigger_price": 150.0, "level": 159.0})


def _positions(held_main=None, held_big=None):
    books = {"main": held_main or {}, "big": held_big or {}}
    return lambda book: books.get(book, {})


# ── parsing ──────────────────────────────────────────────────────────

def test_parse_lines_normalizes_and_keys():
    lines, bad = kl.parse_lines({"kill_lines": [
        {"symbol": "nvda", "level": "159", "note": "support"},
        {"symbol": "SPY", "level": 700.0, "direction": "above"},
    ]})
    assert bad == 0
    assert lines[0] == {"symbol": "NVDA", "level": 159.0,
                        "direction": "below", "note": "support",
                        "key": "NVDA@159:below"}
    assert lines[1]["key"] == "SPY@700:above"


def test_parse_lines_counts_unusable_entries():
    lines, bad = kl.parse_lines({"kill_lines": [
        {"symbol": "", "level": 10.0},
        {"symbol": "X", "level": -1},
        {"symbol": "X", "level": 10.0, "direction": "sideways"},
        "not-a-dict",
        {"symbol": "OK", "level": 5.0},
    ]})
    assert [ln["symbol"] for ln in lines] == ["OK"]
    assert bad == 4
    assert kl.parse_lines({}) == ([], 0)
    assert kl.parse_lines({"kill_lines": "junk"}) == ([], 1)


# ── watch sync ───────────────────────────────────────────────────────

def test_sync_arms_a_watch_per_line_tagged_with_the_thesis():
    db = DB()
    _thesis(db, lines=[{"symbol": "NVDA", "level": 159.0,
                        "note": "159 support break"}])
    out = kl.sync_watches(db, now=NOW)
    assert out["armed"] == 1 and out["skipped_invalid"] == 0
    (watch,) = _watches(db)
    assert watch["family"] == kl.FAMILY
    assert watch["instrument"] == "NVDA"
    assert watch["trigger_type"] == "cross_down"
    assert watch["level"] == 159.0
    assert watch["intent"] == "alert" and watch["rung"] == 1
    assert watch["conditions"]["thesis_id"] == 1
    assert watch["conditions"]["kill_line"] == "NVDA@159:below"
    assert "159 support break" in watch["note"]
    # A re-sync is a no-op — the persisted identity blocks a duplicate.
    assert kl.sync_watches(db, now=NOW)["armed"] == 0
    assert len(_watches(db)) == 1


def test_sync_skips_dead_theses_and_disables_removed_lines():
    db = DB()
    _thesis(db, status="killed",
            lines=[{"symbol": "DEAD", "level": 10.0}])
    _thesis(db, slug="core", status="live", tid=2,
            lines=[{"symbol": "GONE", "level": 20.0}])
    out = kl.sync_watches(db, now=NOW)
    assert out["armed"] == 1  # only the live thesis's line
    # The line is edited out of the thesis: the next sync disables it.
    db.db["theses"][1]["kill_lines"] = []
    out = kl.sync_watches(db, now=NOW)
    assert out["disabled"] == 1
    assert _watches(db)[0]["enabled"] is False
    # And when the line comes back, the same watch re-enables — no dup.
    db.db["theses"][1]["kill_lines"] = [{"symbol": "GONE", "level": 20.0}]
    out = kl.sync_watches(db, now=NOW)
    assert out["reenabled"] == 1 and out["armed"] == 0
    assert len(_watches(db)) == 1
    assert _watches(db)[0]["enabled"] is True


def test_sync_arms_an_above_line_as_cross_up():
    db = DB()
    _thesis(db, lines=[{"symbol": "SPY", "level": 700.0,
                        "direction": "above"}])
    kl.sync_watches(db, now=NOW)
    assert _watches(db)[0]["trigger_type"] == "cross_up"


# ── exit reviews ─────────────────────────────────────────────────────

def _armed_db_with_fire(*, fired_at=None):
    db = DB()
    _thesis(db, lines=[{"symbol": "NVDA", "level": 159.0,
                        "note": "159 support break"}])
    kl.sync_watches(db, now=NOW)
    watch_id = _watches(db)[0]["id"]
    _fire(db, watch_id=watch_id, fired_at=fired_at or NOW)
    return db


def test_a_fire_opens_one_exit_review_per_held_book():
    db = _armed_db_with_fire()
    out = kl.open_exit_reviews(
        db, now=NOW, positions_fn=_positions({"NVDA": 40.0},
                                             {"NVDA": 120.0}))
    assert out["actions_opened"] == 2
    actions = _actions(db)
    assert {a["book"] for a in actions} == {"main", "big"}
    assert all(a["kind"] == "exit_review" for a in actions)
    assert all(a["symbol"] == "NVDA" for a in actions)
    assert all("[kill line event-lab:NVDA@159:below]" in a["detail"]
               for a in actions)
    assert all("[kill-line fire 1]" in a["detail"] for a in actions)
    # A replay opens nothing new — the fire marker persists.
    out = kl.open_exit_reviews(
        db, now=NOW, positions_fn=_positions({"NVDA": 40.0},
                                             {"NVDA": 120.0}))
    assert out["actions_opened"] == 0
    assert len(_actions(db)) == 2


def test_a_second_fire_waits_while_the_first_review_is_open():
    db = _armed_db_with_fire()
    kl.open_exit_reviews(db, now=NOW,
                         positions_fn=_positions({"NVDA": 40.0}))
    _fire(db, watch_id=_watches(db)[0]["id"], fid=2,
          fired_at=NOW + timedelta(hours=2))
    out = kl.open_exit_reviews(db, now=NOW + timedelta(hours=2),
                               positions_fn=_positions({"NVDA": 40.0}))
    assert out["actions_opened"] == 0  # one open review per kill line
    # Resolve the first review: the second fire now opens a fresh one.
    _actions(db)[0]["state"] = "done"
    out = kl.open_exit_reviews(db, now=NOW + timedelta(hours=3),
                               positions_fn=_positions({"NVDA": 40.0}))
    assert out["actions_opened"] == 1
    assert "[kill-line fire 2]" in _actions(db)[-1]["detail"]


def test_a_fire_on_a_name_no_longer_held_opens_nothing():
    db = _armed_db_with_fire()
    out = kl.open_exit_reviews(db, now=NOW,
                               positions_fn=_positions({}, {}))
    assert out["actions_opened"] == 0
    assert _actions(db) == []


def test_old_fires_and_foreign_families_are_ignored():
    db = _armed_db_with_fire(fired_at=NOW - timedelta(days=30))
    out = kl.open_exit_reviews(
        db, now=NOW, positions_fn=_positions({"NVDA": 40.0}))
    assert out["fires_seen"] == 0 and out["actions_opened"] == 0
    db2 = _armed_db_with_fire()
    db2.db["watcher_fires"][0]["family"] = "guidance_band"
    out = kl.open_exit_reviews(
        db2, now=NOW, positions_fn=_positions({"NVDA": 40.0}))
    assert out["fires_seen"] == 0 and out["actions_opened"] == 0


def test_run_bridge_syncs_then_reviews():
    db = DB()
    _thesis(db, lines=[{"symbol": "NVDA", "level": 159.0}])
    first = kl.run_bridge(db, now=NOW,
                          positions_fn=_positions({"NVDA": 10.0}))
    assert first["sync"]["armed"] == 1
    assert first["reviews"]["actions_opened"] == 0
    _fire(db, watch_id=_watches(db)[0]["id"], fired_at=NOW)
    second = kl.run_bridge(db, now=NOW,
                           positions_fn=_positions({"NVDA": 10.0}))
    assert second["sync"]["armed"] == 0
    assert second["reviews"]["actions_opened"] == 1
