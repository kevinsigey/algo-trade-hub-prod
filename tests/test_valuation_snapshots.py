"""Guidance snapshot integrity (reliability pass F1-F4, 2026-11-09):
one completed snapshot is served whole, band history persists per
snapshot, guard reasons + ingest notes ride the sheet, and the
band-crossing scanner reads history with snapshot provenance.

Root cause these pin: the page served an unversioned latest-per-ticker
mix from the append-only fact-sheet table while the EDGAR fleet was
ingesting and recompute passes appended ticker-by-ticker -- successive
loads under one "as of" date showed different datasets (scar tissue #9).
"""
from datetime import UTC, datetime

from workshop_fake import DB

from tradehub.valuation import band_crossing as bc
from tradehub.valuation import run as val_run
from tradehub.valuation import store

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)


def _sheet(ticker="CEG", **over):
    base = {
        "ticker": ticker, "tier": "watch", "status": "banded",
        "price": 273.45, "price_as_of": "2026-11-07",
        "price_vendor": "Yahoo Finance",
        "peer_group": "sector:Utilities", "peer_multiple": 18.02,
        "peer_count": 9, "peer_basis": "sector_fallback",
        "anchor": {"metric": "eps_adjusted", "period": "FY 2026",
                   "period_key": "FY2026", "low": 11.5, "high": 12.5,
                   "mid": 12.0, "point_guide": False, "consensus": 11.9,
                   "consensus_source": "yfinance", "consensus_period": "+1y",
                   "recorded_at": "2026-10-30T12:00:00+00:00",
                   "accession": "0001"},
        "bands": {"bear": 186.65, "base": 216.41, "bull": 225.42},
        "implied": {"eps": 15.17, "vs_guide": "above"},
        "band_basis": "eps",
        "gap_range_widths": 3.17, "guidance_percentile": None,
        "baseline_verdict": "short_zone_strong", "stale": False,
        "stale_reasons": [], "guard_rejections": ["eps_gaap 2026: stale"],
        "ingest_notes": [], "falsifier": "x", "directions": {},
        "fundamentals": {}, "inputs": {}, "computed_at": NOW.isoformat(),
        "snapshot_id": None,
    }
    base.update(over)
    return base


# ── sheet persistence: the reason columns + snapshot stamp ───────────────────

def test_insert_sheet_persists_snapshot_and_reasons():
    db = DB()
    sheet = _sheet(snapshot_id=7)
    store.insert_sheet(db, sheet)
    [row] = db.db["valuation_fact_sheets"]
    assert row["snapshot_id"] == 7
    assert row["guard_rejections"] == ["eps_gaap 2026: stale"]
    assert row["stale_reasons"] == []
    assert row["ingest_notes"] == []
    assert row["price_vendor"] == "Yahoo Finance"


# ── snapshot lifecycle: only a COMPLETED snapshot is served ──────────────────

def test_latest_snapshot_ignores_incomplete():
    db = DB()
    sid = store.begin_snapshot(db, NOW, source="valuation_run")
    assert store.latest_snapshot(db) is None
    store.complete_snapshot(db, sid, sheet_count=39, banded_count=21)
    snap = store.latest_snapshot(db)
    assert snap["id"] == sid and snap["sheet_count"] == 39
    # A recompute in flight must not shadow the completed one.
    store.begin_snapshot(db, LATER, source="valuation_run")
    assert store.latest_snapshot(db)["id"] == sid


def test_snapshot_sheets_are_pinned_to_the_snapshot():
    db = DB()
    s1 = store.begin_snapshot(db, NOW, source="valuation_run")
    store.insert_sheet(db, _sheet("AAA", snapshot_id=s1))
    store.complete_snapshot(db, s1, sheet_count=1, banded_count=1)
    s2 = store.begin_snapshot(db, LATER, source="valuation_run")
    store.insert_sheet(db, _sheet("AAA", snapshot_id=s2, price=1.0))
    store.insert_sheet(db, _sheet("BBB", snapshot_id=s2))
    store.complete_snapshot(db, s2, sheet_count=2, banded_count=2)
    snap, sheets = store.latest_snapshot_sheets(db)
    assert snap["id"] == s2
    assert {sh["ticker"] for sh in sheets} == {"AAA", "BBB"}
    assert next(sh for sh in sheets if sh["ticker"] == "AAA")["price"] == 1.0


def test_latest_snapshot_sheets_falls_back_when_no_snapshot():
    db = DB()
    # Seeded directly: production rows carry the DB-defaulted computed_at
    # the legacy latest-per-ticker read orders by (the fake has no default).
    db.db["valuation_fact_sheets"] = [
        {"ticker": "AAA", "computed_at": "2026-11-09T00:00:00Z",
         "snapshot_id": None}]
    snap, sheets = store.latest_snapshot_sheets(db)
    assert snap is None
    assert [sh["ticker"] for sh in sheets] == ["AAA"]


# ── band history rows ────────────────────────────────────────────────────────

def test_history_row_maps_the_sheet():
    row = store.history_row(_sheet(), snapshot_id=3, computed_at=NOW)
    assert row["snapshot_id"] == 3 and row["ticker"] == "CEG"
    assert row["band_basis"] == "eps"
    assert row["guide_metric"] == "eps_adjusted"
    assert row["guide_unit"] == "usd_per_share"
    assert row["guide_low"] == 11.5 and row["guide_high"] == 12.5
    assert row["peer_multiple"] == 18.02
    assert row["bear"] == 186.65 and row["base"] == 216.41
    assert row["bull"] == 225.42
    assert row["price"] == 273.45 and row["zone"] == "short_zone_strong"
    # Compact by Kevin's directive: peer detail, gap, reasons, consensus
    # are current-state on the sheet, never per snapshot.
    for absent in ("peer_group", "peer_count", "gap_range_widths",
                   "guard_rejections", "consensus", "status", "stale"):
        assert absent not in row


def test_history_row_for_unbanded_name_has_no_bands():
    sheet = _sheet(status="guide_rejected", bands=None, anchor=None,
                   baseline_verdict="no_bands")
    row = store.history_row(sheet, snapshot_id=3, computed_at=NOW)
    assert row["bear"] is None and row["guide_metric"] is None
    assert row["zone"] == "no_bands" and row["direction"] is None


def test_latest_snapshot_history_reads_the_completed_snapshot():
    db = DB()
    s1 = store.begin_snapshot(db, NOW, source="valuation_run")
    store.insert_history(db, [store.history_row(_sheet("AAA"),
                                                snapshot_id=s1,
                                                computed_at=NOW)])
    store.complete_snapshot(db, s1, sheet_count=1, banded_count=1)
    store.begin_snapshot(db, LATER, source="valuation_run")  # in flight
    rows = store.latest_snapshot_history(db)
    assert [r["ticker"] for r in rows] == ["AAA"]
    assert rows[0]["snapshot_id"] == s1


# ── ingest notes (F3): zero guides + conflicting same-period guides ──────────

def _rec(**over):
    base = {"ticker": "BKNG", "metric": "revenue", "period": "FY 2026",
            "unit": "usd", "low": 0.0, "high": 0.0,
            "consensus": 28.606e9, "consensus_period": None,
            "consensus_source": "yfinance", "accession": "a1",
            "created_at": "2026-11-03T21:03:57+00:00"}
    base.update(over)
    return base


def test_ingest_notes_name_the_zero_guide_parse_failure():
    notes = val_run.ingest_notes([_rec()], NOW)
    assert len(notes) == 1
    assert "parse failure" in notes[0]
    assert "$0.00B" in notes[0] and "28.61" in notes[0]


def test_ingest_notes_silent_for_a_clean_guide():
    rec = _rec(low=27.0e9, high=29.0e9)
    assert val_run.ingest_notes([rec], NOW) == []


def test_ingest_notes_name_conflicting_point_guides():
    recs = [
        _rec(ticker="SO", metric="eps_adjusted", period="2026",
             unit="usd_per_share", low=4.40, high=4.40,
             consensus=4.62601, created_at="2026-11-05T13:09:18+00:00"),
        _rec(ticker="SO", metric="eps_adjusted", period="2026",
             unit="usd_per_share", low=1.94, high=1.94,
             consensus=4.62601, created_at="2026-11-05T13:09:18+00:00"),
    ]
    notes = val_run.ingest_notes(recs, NOW)
    assert len(notes) == 1
    assert "conflicting" in notes[0]
    assert "4.40" in notes[0] and "1.94" in notes[0]


# ── extractor sanity flag (F3, ingest side) ──────────────────────────────────

def test_sanity_flag_zero_and_outlier_and_clean():
    from tradehub.guidance.extract import sanity_flag_for

    assert sanity_flag_for(_rec(), NOW) == "zero_guide_value"
    outlier = _rec(ticker="SO", metric="eps_adjusted", period="2026",
                   unit="usd_per_share", low=1.94, high=1.94,
                   consensus=4.62601)
    assert sanity_flag_for(outlier, NOW) == "outlier_vs_consensus"
    clean = _rec(low=27.0e9, high=29.0e9)
    assert sanity_flag_for(clean, NOW) is None
    quarterly_zero = _rec(period="Q4 2026")
    assert sanity_flag_for(quarterly_zero, NOW) is None  # FY guides only


# ── F4: the crossings scanner reads history, stamps provenance ───────────────

def _history(ticker, *, price, bands, snapshot_id, computed_at,
             direction="held"):
    sheet = _sheet(ticker, price=price, bands=bands,
                   computed_at=computed_at.isoformat())
    row = store.history_row(sheet, snapshot_id=snapshot_id,
                            computed_at=computed_at)
    row["direction"] = direction
    return row


def _scan_rig(db, **kw):
    args = dict(kind="weekly", now=NOW, books=("main",),
                positions_reader=lambda book: {},
                equity_reader=lambda book: 100_000.0,
                t1_reader=lambda client, ticker: None,
                pc_runner=lambda book, ticker, delta: ("would_pass", "ok"))
    args.update(kw)
    return bc.run_scan(db, **args)


def test_scan_reads_history_and_first_sightings_are_silent():
    db = DB()
    db.db["band_crossing_controls"] = [
        {"scope": "global", "orders_enabled": False}]
    sid = store.begin_snapshot(db, NOW, source="valuation_run")
    bands = {"bear": 100.0, "base": 120.0, "bull": 130.0}
    store.insert_history(db, [
        _history("AAA", price=110.0, bands=bands, snapshot_id=sid,
                 computed_at=NOW),
        _history("BBB", price=110.0, bands=bands, snapshot_id=sid,
                 computed_at=NOW),
        _history("CCC", price=110.0, bands=bands, snapshot_id=sid,
                 computed_at=NOW),
    ])
    store.complete_snapshot(db, sid, sheet_count=3, banded_count=3)
    out = _scan_rig(db)
    assert out["banded_names"] == 3
    assert out["crossings_written"] == 0       # first sightings: silent
    assert len(db.db["band_crossing_state"]) == 3
    [scan] = db.db["band_crossing_scans"]
    assert scan["snapshot_id"] == sid


def test_scan_transition_rows_carry_snapshot_and_source():
    db = DB()
    db.db["band_crossing_controls"] = [
        {"scope": "global", "orders_enabled": False}]
    bands = {"bear": 100.0, "base": 120.0, "bull": 130.0}
    s1 = store.begin_snapshot(db, NOW, source="valuation_run")
    store.insert_history(db, [_history("AAA", price=125.0, bands=bands,
                                       snapshot_id=s1, computed_at=NOW)])
    store.complete_snapshot(db, s1, sheet_count=1, banded_count=1)
    _scan_rig(db)  # baseline state: bull zone, no action
    s2 = store.begin_snapshot(db, LATER, source="valuation_run")
    store.insert_history(db, [_history("AAA", price=110.0, bands=bands,
                                       snapshot_id=s2, computed_at=LATER)])
    store.complete_snapshot(db, s2, sheet_count=1, banded_count=1)
    out = _scan_rig(db, now=LATER)
    assert out["crossings_written"] == 1
    [row] = db.db["band_crossings"]
    assert row["snapshot_id"] == s2
    assert row["source"] == "scan"
    assert row["action"] == "starter"
