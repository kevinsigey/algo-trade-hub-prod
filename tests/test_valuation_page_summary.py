"""Guidance re-presentation: the additive page summary block.

The verdict strip / attention feed / zone board on the Guidance page are
served ONE stamped summary computed from data the hub already persists:
valuation_band_history (one compact row per name per snapshot) for the
zone/guide diff between the latest and previous COMPLETED snapshots,
band_crossings rows stamped with the snapshot id, the forward-file
classification store, and the debate candidate queue. These tests pin
the diff (including its honest empty case), the ranking (conjunctions
pinned first), and the rule that only completed snapshots are read.
"""
from datetime import UTC, datetime

from workshop_fake import DB

from tradehub.valuation import page_summary, store

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _hist(ticker, *, zone="neutral", low=10.0, high=12.0, bear=90.0,
          base=110.0, bull=120.0, price=105.0, metric="eps_adjusted",
          direction="held", snapshot_id=2):
    return {"snapshot_id": snapshot_id, "ticker": ticker,
            "band_basis": "eps", "guide_metric": metric,
            "guide_unit": "usd_per_share", "guide_low": low,
            "guide_high": high, "direction": direction,
            "peer_multiple": 10.0, "bear": bear, "base": base,
            "bull": bull, "price": price, "zone": zone,
            "computed_at": "2026-11-10T04:00:00Z"}


def _snapshots(db, n=2):
    ids = []
    for i in range(n):
        sid = store.begin_snapshot(db, NOW, source="valuation_run")
        store.complete_snapshot(db, sid, sheet_count=3, banded_count=3)
        ids.append(sid)
    return ids


# ── previous completed snapshot ─────────────────────────────────────────────

def test_previous_snapshot_is_the_second_completed():
    db = DB()
    s1, s2 = _snapshots(db, 2)
    # An in-flight recompute must not become "previous" or shadow latest.
    store.begin_snapshot(db, NOW, source="valuation_run")
    assert store.latest_snapshot(db)["id"] == s2
    assert page_summary.previous_snapshot(db)["id"] == s1


def test_previous_snapshot_none_when_only_one_completed():
    db = DB()
    _snapshots(db, 1)
    assert page_summary.previous_snapshot(db) is None


# ── the history diff ────────────────────────────────────────────────────────

def test_diff_finds_zone_change_and_guide_revision():
    prev = [_hist("AAA", zone="neutral", low=10.0, high=12.0, snapshot_id=1),
            _hist("BBB", zone="buy_zone", snapshot_id=1)]
    latest = [_hist("AAA", zone="buy_zone_strong", low=11.0, high=13.0,
                    direction="raised"),
              _hist("BBB", zone="buy_zone")]
    diff = page_summary.diff_history(latest, prev)
    assert [c["ticker"] for c in diff["zone_changes"]] == ["AAA"]
    zc = diff["zone_changes"][0]
    assert zc["from_zone"] == "neutral" and zc["to_zone"] == "buy_zone_strong"
    assert [r["ticker"] for r in diff["guide_revisions"]] == ["AAA"]
    rev = diff["guide_revisions"][0]
    assert (rev["from_low"], rev["from_high"]) == (10.0, 12.0)
    assert (rev["to_low"], rev["to_high"]) == (11.0, 13.0)
    assert diff["new_banded"] == []


def test_diff_empty_when_histories_identical():
    rows = [_hist("AAA"), _hist("BBB", zone="short_zone")]
    diff = page_summary.diff_history(rows, [dict(r) for r in rows])
    assert diff == {"zone_changes": [], "guide_revisions": [],
                    "new_banded": []}


def test_diff_flags_newly_banded_and_ignores_dropped_names():
    prev = [_hist("AAA", snapshot_id=1),
            _hist("GONE", snapshot_id=1),
            {"snapshot_id": 1, "ticker": "NEW", "band_basis": None,
             "guide_metric": None, "guide_unit": None, "guide_low": None,
             "guide_high": None, "direction": None, "peer_multiple": None,
             "bear": None, "base": None, "bull": None, "price": 50.0,
             "zone": "no_bands", "computed_at": "2026-11-09T04:00:00Z"}]
    latest = [_hist("AAA"), _hist("NEW", zone="buy_zone")]
    diff = page_summary.diff_history(latest, prev)
    assert [r["ticker"] for r in diff["new_banded"]] == ["NEW"]
    assert diff["zone_changes"] == []  # GONE leaving coverage is not an item
    assert diff["guide_revisions"] == []


def test_diff_no_previous_snapshot_is_all_new_banded_free():
    # With no previous snapshot there is nothing to diff against: the
    # caller marks the feed unavailable rather than calling every name new.
    diff = page_summary.diff_history([_hist("AAA")], [])
    assert diff["new_banded"] == [] and diff["zone_changes"] == []


# ── the assembled summary ───────────────────────────────────────────────────

def _seed_full(db):
    s1, s2 = _snapshots(db, 2)
    db.db["valuation_band_history"] = [
        _hist("AAA", zone="neutral", snapshot_id=s1),
        _hist("BBB", zone="short_zone_strong", snapshot_id=s1),
        _hist("CCC", zone="buy_zone", snapshot_id=s1),
        _hist("AAA", zone="buy_zone_strong", low=11.0, high=13.0,
              direction="raised", snapshot_id=s2),
        _hist("BBB", zone="short_zone_strong", snapshot_id=s2),
        _hist("CCC", zone="buy_zone", snapshot_id=s2),
    ]
    db.db["band_crossings"] = [
        {"id": 1, "ticker": "AAA", "book": "main", "zone": "buy_zone_strong",
         "action": "starter", "snapshot_id": s2,
         "created_at": "2026-11-10T05:00:00Z", "bear": 90.0, "base": 110.0,
         "bull": 120.0, "price": 88.0},
        {"id": 2, "ticker": "BBB", "book": "big", "zone": "short_zone_strong",
         "action": "none", "snapshot_id": s1,
         "created_at": "2026-11-09T05:00:00Z", "bear": 90.0, "base": 110.0,
         "bull": 120.0, "price": 130.0},
    ]
    db.db["forward_file_classifications"] = [
        {"ticker": "BBB", "classification": "improved",
         "as_of": "2026-11-09"},
        {"ticker": "BBB", "classification": "deteriorated",
         "as_of": "2026-10-01"},
        {"ticker": "ZZZ", "classification": "intact", "as_of": "2026-11-08"},
    ]
    db.db["screens"] = [
        {"id": 6, "name": "Buffett quality",
         "membership": {"tracked_since": "2026-11-10",
                        "members": {"BBB": "2026-11-10"}},
         "membership_events": [],
         "last_run": {"survivors": ["BBB"]}},
    ]
    db.db["debate_candidates"] = [
        {"ticker": "AAA", "snapshot_id": s2, "state": "pending",
         "candidate_class": "zone", "priority": 20},
        {"ticker": "BBB", "snapshot_id": s2, "state": "pending",
         "candidate_class": "conjunction", "priority": 5},
        {"ticker": "CCC", "snapshot_id": s2, "state": "rendered",
         "candidate_class": "zone", "priority": 40},
        {"ticker": "OLD", "snapshot_id": s1, "state": "pending",
         "candidate_class": "zone", "priority": 40},
    ]
    return s1, s2


def test_summary_counts_crossings_debates_and_classifications():
    db = DB()
    s1, s2 = _seed_full(db)
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    assert out["snapshot_id"] == s2
    assert out["previous_snapshot_id"] == s1
    counts = out["counts"]
    assert counts["banded"] == 3
    assert counts["buy_zones"] == 2          # AAA strong + CCC buy
    assert counts["strong_short_zones"] == 1  # BBB
    # Only crossings stamped with the LATEST snapshot count.
    assert counts["crossings_since_last_snapshot"] == 1
    assert counts["pending_debates"] == 2     # OLD belongs to snapshot s1
    assert counts["classified_prints"] == 2   # BBB + ZZZ, latest row wins
    names = {c["ticker"]: c for c in out["classified_names"]}
    assert names["BBB"]["classification"] == "improved"  # newest as_of wins
    assert out["feed_state"] == "ok"


def test_summary_feed_pins_conjunction_first():
    db = DB()
    _seed_full(db)
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    kinds = [item["kind"] for item in out["feed"]]
    # BBB: strong-short zone x fresh print (2026-11-09) x recorded screen
    # membership -> conjunction, pinned above the crossing and changes.
    assert kinds[0] == "conjunction"
    assert out["feed"][0]["ticker"] == "BBB"
    assert out["feed"][0]["classification"] == "improved"
    assert "crossing" in kinds and "zone_change" in kinds
    assert "guide_revision" in kinds
    tickers = [i["ticker"] for i in out["feed"] if i["kind"] == "crossing"]
    assert tickers == ["AAA"]  # the s1 crossing is not in this feed


def test_summary_feed_honest_empty_state():
    db = DB()
    s1, s2 = _snapshots(db, 2)
    rows = [_hist("AAA", snapshot_id=s1), _hist("AAA", snapshot_id=s2)]
    db.db["valuation_band_history"] = rows
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    assert out["feed"] == []
    assert out["feed_state"] == "ok"  # compared, and nothing changed


def test_summary_no_previous_snapshot_marks_feed_unavailable():
    db = DB()
    (s1,) = _snapshots(db, 1)
    db.db["valuation_band_history"] = [_hist("AAA", snapshot_id=s1)]
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    assert out["feed"] == []
    assert out["feed_state"] == "no_previous_snapshot"
    assert out["counts"]["banded"] == 1


def test_summary_no_snapshot_at_all():
    db = DB()
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    assert out["snapshot_id"] is None
    assert out["feed_state"] == "no_snapshot"
    assert out["counts"]["banded"] == 0


def test_summary_held_map_rides_along_for_board_markers():
    db = DB()
    _seed_full(db)
    out = page_summary.build_summary(
        db, positions_fn=lambda book: {"BBB": 10} if book == "big" else {},
        now=NOW)
    assert out["held"]["BBB"]["books"] == ["big"]
    assert out["held_positions_unavailable"] is False


# ── Round 6: filtered-view reconciliation ───────────────────────────────────
# Every filtered view must account for every name its count promises:
# tile count == boarded names + accounted names. The summary therefore
# stamps each classified / held entry with whether it is banded (i.e. on
# the board) and, when it is not, the stored sheet status that says why.

def _sheet(ticker, status, snapshot_id, *, verdict=None):
    return {"snapshot_id": snapshot_id, "ticker": ticker, "status": status,
            "baseline_verdict": verdict or (
                "neutral" if status == "banded" else "no_bands"),
            "stale": False}


def test_classified_entries_carry_banded_flag_status_and_reason():
    db = DB()
    s1, s2 = _snapshots(db, 2)
    db.db["valuation_band_history"] = [
        _hist("AAA", zone="neutral", snapshot_id=s2)]
    db.db["valuation_fact_sheets"] = [
        _sheet("AAA", "banded", s2), _sheet("BBB", "no_full_year_guide", s2)]
    db.db["forward_file_classifications"] = [
        {"ticker": "AAA", "classification": "improved",
         "as_of": "2026-11-09"},
        {"ticker": "BBB", "classification": "intact", "as_of": "2026-11-09"},
        {"ticker": "CCC", "classification": "deteriorated",
         "as_of": "2026-11-09"},
    ]
    out = page_summary.build_summary(db, positions_fn=lambda book: {},
                                     now=NOW)
    # The strip count itself does not move: all three classifications count.
    assert out["counts"]["classified_prints"] == 3
    entries = {c["ticker"]: c for c in out["classified_names"]}
    assert entries["AAA"]["banded"] is True
    assert entries["AAA"]["sheet_status"] == "banded"
    assert entries["AAA"]["reason"] is None
    assert entries["BBB"]["banded"] is False
    assert entries["BBB"]["sheet_status"] == "no_full_year_guide"
    assert "full-year guide" in entries["BBB"]["reason"]
    assert entries["CCC"]["banded"] is False
    assert entries["CCC"]["sheet_status"] is None
    assert entries["CCC"]["reason"] == (
        "not in the guidance universe / no fact sheet in this snapshot")
    boarded = sum(1 for c in entries.values() if c["banded"])
    accounted = sum(1 for c in entries.values() if not c["banded"])
    assert boarded + accounted == out["counts"]["classified_prints"]


def test_held_names_account_for_every_held_ticker():
    db = DB()
    s1, s2 = _snapshots(db, 2)
    db.db["valuation_band_history"] = [
        _hist("AAA", zone="neutral", snapshot_id=s2)]
    db.db["valuation_fact_sheets"] = [
        _sheet("AAA", "banded", s2), _sheet("BBB", "no_full_year_guide", s2)]
    positions = lambda book: ({"AAA": 5, "BBB": 7, "ZZZ": 3}
                              if book == "big" else {})
    out = page_summary.build_summary(db, positions_fn=positions, now=NOW)
    held_names = {h["ticker"]: h for h in out["held_names"]}
    assert sorted(held_names) == ["AAA", "BBB", "ZZZ"]
    assert held_names["AAA"]["banded"] is True
    assert held_names["AAA"]["books"] == ["big"]
    assert held_names["BBB"]["banded"] is False
    assert held_names["BBB"]["sheet_status"] == "no_full_year_guide"
    assert "full-year guide" in held_names["BBB"]["reason"]
    assert held_names["ZZZ"]["banded"] is False
    assert held_names["ZZZ"]["sheet_status"] is None
    assert held_names["ZZZ"]["reason"] == (
        "not in the guidance universe / no fact sheet in this snapshot")
    # The held map the board markers read is unchanged.
    assert out["held"]["AAA"]["books"] == ["big"]
    assert out["held_positions_unavailable"] is False


def test_held_names_empty_when_the_book_read_is_unavailable():
    db = DB()
    _snapshots(db, 2)

    def boom(book):
        raise RuntimeError("book read down")

    out = page_summary.build_summary(db, positions_fn=boom, now=NOW)
    assert out["held_positions_unavailable"] is True
    assert out["held_names"] == []


# ── the API block ───────────────────────────────────────────────────────────

def test_bands_payload_carries_the_summary_block(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    from tradehub.api.dependencies import get_supabase as real_get_supabase

    db = DB()
    s1, s2 = _seed_full(db)
    monkeypatch.setattr(
        "tradehub.valuation.candidates.held_positions",
        lambda client, positions_fn=None: {})
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"email": "k@example.com", "is_admin": True})
    main.app.dependency_overrides[real_get_supabase] = lambda: db
    try:
        body = TestClient(main.app).get("/api/valuation-bands").json()
    finally:
        main.app.dependency_overrides.pop(admin.require_admin, None)
        main.app.dependency_overrides.pop(real_get_supabase, None)
    assert body["snapshot"]["id"] == s2
    assert body["summary"]["snapshot_id"] == s2
    assert body["summary"]["counts"]["banded"] == 3
    assert body["summary"]["feed"][0]["kind"] == "conjunction"
