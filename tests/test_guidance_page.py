"""Guidance rebuild board block: movers between the two latest
completed snapshots, the football-field grid, the missing-band queue,
freshness. Fixtures are realistic stored rows (the acceptance shape:
the movers must compute correctly between two snapshots on real-shaped
data)."""
from datetime import UTC, datetime, timedelta

from workshop_fake import DB

from tradehub.valuation import guidance_page as gp
from tradehub.valuation import store

T0 = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 16, 14, 0, tzinfo=UTC)


def _sheet(ticker, *, snapshot_id, price, bands=None, status="banded",
           shares=None, computed=T1):
    return {"ticker": ticker, "tier": "open", "status": status,
            "price": price, "price_as_of": "2026-11-16",
            "peer_group": "sector:Tech", "peer_multiple": 20.0,
            "peer_count": 5, "peer_basis": "industry_group",
            "anchor": {"metric": "eps_adjusted", "low": 5.0, "high": 6.0},
            "bands": bands, "band_basis": "eps",
            "baseline_verdict": "neutral", "stale": False,
            "fundamentals": ({"shares_diluted": {"value": shares,
                                                 "as_of": "2026-09-30"}}
                             if shares else {}),
            "inputs": {}, "directions": {}, "falsifier": None,
            "computed_at": computed.isoformat(),
            "snapshot_id": snapshot_id}


def _hist(ticker, *, snapshot_id, price, bands, low=5.0, high=6.0,
          zone="neutral", direction="held"):
    return {"snapshot_id": snapshot_id, "ticker": ticker,
            "band_basis": "eps", "guide_metric": "eps_adjusted",
            "guide_unit": "usd_per_share", "guide_low": low,
            "guide_high": high, "direction": direction,
            "peer_multiple": 20.0,
            "bear": bands["bear"] if bands else None,
            "base": bands["base"] if bands else None,
            "bull": bands["bull"] if bands else None,
            "price": price, "zone": zone,
            "computed_at": T1.isoformat()}


def _two_snapshots(db):
    s1 = store.begin_snapshot(db, T0, source="valuation_run")
    store.complete_snapshot(db, s1, sheet_count=2, banded_count=2)
    s2 = store.begin_snapshot(db, T1, source="valuation_run")
    store.complete_snapshot(db, s2, sheet_count=2, banded_count=2)
    return s1, s2


HELD = {"main": {"HELD": 10.0, "NOBAND": 5.0}, "big": {}}


def _positions(book):
    return HELD.get(book, {})


# ── the recorder revision rule ───────────────────────────────────────────────

def test_guide_change_uses_the_newest_periods_latest_pair():
    recs = [
        {"period": "FY2026", "low": 100.0, "high": 120.0,
         "created_at": "2026-10-01T00:00:00Z"},
        {"period": "FY2026", "low": 110.0, "high": 130.0,
         "created_at": "2026-11-01T00:00:00Z"},
        {"period": "FY2025", "low": 1.0, "high": 3.0,
         "created_at": "2026-09-01T00:00:00Z"},
    ]
    # FY2026 midpoints 110 -> 120 = +9.09%
    assert abs(gp.guide_change_pct(recs) - 9.0909) < 0.01


def test_guide_change_none_without_a_pair():
    recs = [{"period": "FY2026", "low": 1.0, "high": 2.0,
             "created_at": "2026-10-01T00:00:00Z"}]
    assert gp.guide_change_pct(recs) is None


def test_recorder_revisions_split_capex_and_fcf_by_evidence():
    records = {"AAA": [
        {"metric": "capex", "period": "FY2026", "low": 10.0, "high": 10.0,
         "evidence": "capex guide", "created_at": "2026-10-01T00:00:00Z"},
        {"metric": "capex", "period": "FY2026", "low": 12.0, "high": 12.0,
         "evidence": "capex guide", "created_at": "2026-11-01T00:00:00Z"},
        {"metric": "other", "period": "FY2026", "low": 5.0, "high": 5.0,
         "evidence": "free cash flow guide", "created_at": "2026-10-01T00:00:00Z"},
        {"metric": "other", "period": "FY2026", "low": 4.0, "high": 4.0,
         "evidence": "free cash flow guide", "created_at": "2026-11-01T00:00:00Z"},
        {"metric": "other", "period": "FY2026", "low": 9.0, "high": 9.0,
         "evidence": "buyback authorization", "created_at": "2026-11-02T00:00:00Z"},
    ]}
    rev = gp.recorder_revisions(records)["AAA"]
    assert abs(rev["capex"] - 20.0) < 0.01
    assert abs(rev["fcf"] - (-20.0)) < 0.01  # the buyback row is not FCF


def test_recorder_revision_window_excludes_history():
    """A revision whose newest guide predates the window is history,
    not a mover: with `since` after the pair's newest record the
    revision disappears; with `since` before it, it stands."""
    recs = [
        {"ticker": "AAA", "metric": "capex", "period": "FY2026",
         "low": 10.0, "high": 10.0, "evidence": "capex guide",
         "created_at": "2026-10-01T00:00:00Z"},
        {"ticker": "AAA", "metric": "capex", "period": "FY2026",
         "low": 12.0, "high": 12.0, "evidence": "capex guide",
         "created_at": "2026-11-01T00:00:00Z"},
    ]
    by_ticker = {"AAA": recs}
    fresh = gp.recorder_revisions(by_ticker, since="2026-10-15T00:00:00Z")
    assert abs(fresh["AAA"]["capex"] - 20.0) < 0.01
    stale = gp.recorder_revisions(by_ticker, since="2026-11-10T00:00:00Z")
    assert "AAA" not in stale


def test_records_read_pages_past_the_postgrest_cap():
    """guidance_records only grows and PostgREST caps a response at
    1000 rows: the read must page, or it silently degrades to the
    oldest records."""
    db = DB()
    rows = [{"ticker": "AAA", "metric": "capex", "period": "FY2026",
             "low": 10.0, "high": 10.0, "evidence": "capex guide",
             "created_at": f"2026-10-{(i % 28) + 1:02d}T{i % 24:02d}:00:00Z"}
            for i in range(1001)]
    db.table("guidance_records").insert(rows).execute()
    out = gp._records(db)
    assert len(out["AAA"]) == 1001


# ── grid position ────────────────────────────────────────────────────────────

def test_position_statuses_and_distance():
    bands = {"bear": 90.0, "base": 110.0, "bull": 130.0}
    assert gp.position(85.0, bands)["status"] == "below_bear"
    assert gp.position(100.0, bands)["status"] == "buy_zone"
    assert gp.position(120.0, bands)["status"] == "between"
    assert gp.position(140.0, bands)["status"] == "above_bull"
    # 120 vs base 110: 8.33% above the buy zone
    assert gp.position(120.0, bands)["distance_pct"] == 8.33
    assert gp.position(100.0, bands)["distance_pct"] == -10.0
    assert gp.position(100.0, None)["status"] == "no_band"


# ── the board on two snapshots ───────────────────────────────────────────────

def _board_db():
    db = DB()
    s1, s2 = _two_snapshots(db)
    bands = {"bear": 90.0, "base": 110.0, "bull": 130.0}
    # HELD: above the base band in s1, inside the buy zone in s2, and
    # its anchor guide was raised (low/high 5/6 -> 6/7).
    store.insert_sheet(db, _sheet("HELD", snapshot_id=s1, price=125.0,
                                  bands=bands, computed=T0))
    store.insert_sheet(db, _sheet("HELD", snapshot_id=s2, price=100.0,
                                  bands=bands, shares=2_000_000))
    store.insert_history(db, [
        _hist("HELD", snapshot_id=s1, price=125.0, bands=bands),
        _hist("HELD", snapshot_id=s2, price=100.0, bands=bands,
              low=6.0, high=7.0, direction="raised")])
    # FREE: not held, guide unchanged, zone unchanged.
    store.insert_sheet(db, _sheet("FREE", snapshot_id=s2, price=125.0,
                                  bands=bands))
    store.insert_history(db, [
        _hist("FREE", snapshot_id=s1, price=124.0, bands=bands),
        _hist("FREE", snapshot_id=s2, price=125.0, bands=bands)])
    # NOBAND: held in main, sheet exists but unbanded (the AMAT shape).
    store.insert_sheet(db, _sheet("NOBAND", snapshot_id=s2, price=50.0,
                                  bands=None, status="no_full_year_guide"))
    return db


def test_board_movers_grid_and_missing_queue():
    db = _board_db()
    board = gp.build_board(db, positions_fn=_positions,
                           now=T1 + timedelta(hours=2))
    assert board["snapshot_id"] is not None
    assert board["freshness"]["stale"] is False
    assert board["freshness"]["age_hours"] == 2.0
    movers = board["movers"]
    revs = [r for r in movers["guide_revisions"] if r["metric"] == "anchor"]
    assert len(revs) == 1 and revs[0]["ticker"] == "HELD"
    assert revs[0]["held"] is True
    # midpoints 5.5 -> 6.5 = +18.18%
    assert revs[0]["change_pct"] == 18.18
    assert movers["held_status"][0]["ticker"] == "HELD"
    assert movers["held_status"][0]["status"] == "buy_zone"

    grid = {r["ticker"]: r for r in board["grid"]}
    assert set(grid) == {"HELD", "FREE"}
    assert grid["HELD"]["held"] is True
    assert grid["HELD"]["distance_pct"] == -10.0
    assert grid["HELD"]["market_cap"] == 200_000_000.0
    assert board["grid"][0]["ticker"] == "HELD"  # held pinned first

    missing = {r["ticker"]: r for r in board["missing_band"]}
    assert "NOBAND" in missing
    assert missing["NOBAND"]["held"] is True
    assert "no full-year guide" in missing["NOBAND"]["reason"]


def test_board_movers_none_with_a_single_snapshot():
    db = DB()
    s1 = store.begin_snapshot(db, T0, source="valuation_run")
    store.complete_snapshot(db, s1, sheet_count=0, banded_count=0)
    board = gp.build_board(db, positions_fn=_positions, now=T1)
    assert board["movers"] is None
    assert board["freshness"]["previous_snapshot_id"] is None
