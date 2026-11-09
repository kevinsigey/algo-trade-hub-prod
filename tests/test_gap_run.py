"""The tracker from stored market snapshots, through a fake store: no network, no order path."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from workshop_fake import DB

from tradehub.gaps import logic
from tradehub.gaps.report import desk
from tradehub.gaps.run import GROSS, NET, OUTCOMES, POSITIONS, RUNS, SNAPSHOTS, run_tracker

NOW = datetime(2026, 11, 4, 12, 15, tzinfo=UTC)
SERIES = {"fee_type": "quadratic", "fee_multiplier": 1, "settlement_sources": [{"name": "CF Benchmarks"}]}
BOOK = [["0.50", "50000"], ["0.72", "50000"]]


class Store(DB):
    def __init__(self):
        super().__init__()
        self.unresolved = []

    def rpc(self, name, params):
        rows = [{"ticker": t} for t in self.unresolved]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))


def raw(ticker="KXBTC-A", hours=5.0, bid="0.58", ask="0.60", no_bid="0.40", no_ask="0.42"):
    close = (NOW + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"ticker": ticker, "event_ticker": "KXBTC-E", "close_time": close, "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "no_bid_dollars": no_bid, "no_ask_dollars": no_ask, "floor_strike": 100.0,
            "strike_type": "greater", "last_price_dollars": "0.59", "volume_fp": "100.00", "open_interest_fp": "50.00",
            "rules_primary": "Resolves on BRTI."}


class Model:
    name, version = "crypto_btc_hourly", "btc-hourly-v1"

    def __init__(self, prob):
        self.prob = prob

    def forecast(self, entry, now):
        if self.prob is None:
            return None
        return SimpleNamespace(probability=self.prob, payload={"price_at": (now - timedelta(minutes=2)).isoformat()})


def _run(db, raws, *, prob=0.75, book=BOOK, now=NOW, series=SERIES, market=None):
    live = SimpleNamespace(open_raws=lambda s: raws)
    source = {"category": "crypto", "series": "KXBTC", "fc": Model(prob)}
    return run_tracker(db, now, live=live, sources=[source], read_book=lambda t, s: book,
                       read_market=market or (lambda t: {}), read_series=lambda s: series)


@pytest.fixture(autouse=True)
def plain_market(monkeypatch):
    monkeypatch.setattr("tradehub.gaps.run.parse_market", lambda r: SimpleNamespace(
        ticker=r["ticker"], close_time=datetime.fromisoformat(r["close_time"].replace("Z", "+00:00"))))


def test_a_passing_gap_logs_flags_and_opens_one_paper_position():
    db = Store()
    summary = _run(db, [raw()])
    assert summary["logged"] == 1 and summary["flagged"] == 1 and summary["opened"] == 1
    snap = db.db[SNAPSHOTS][0]
    assert snap["side"] == "yes" and snap["gap_pts"] == pytest.approx(15.0) and snap["flagged"] is True
    assert snap["mid"] == pytest.approx(0.59) and snap["resolution_source"] == "CF Benchmarks"
    assert snap["model_data_age_s"] == pytest.approx(120)
    pos = db.db[POSITIONS][0]
    assert pos["entry_price"] == 0.60 and pos["contracts"] == 1000  # half Kelly is 18.75%, so the 6% cap: $600 at 60c
    assert pos["entry_fee"] == pytest.approx(16.80) and "settlement" in pos["exit_condition"]
    assert db.db[RUNS][0]["logged"] == 1


def test_a_second_run_does_not_open_the_same_contract_again():
    db = Store()
    _run(db, [raw()])
    assert _run(db, [raw()], now=NOW + timedelta(minutes=5))["opened"] == 0
    assert len(db.db[POSITIONS]) == 1


def test_one_sided_contracts_are_counted_not_logged():
    db = Store()
    _run(db, [raw(bid="0.0000")])
    assert SNAPSHOTS not in db.db or db.db[SNAPSHOTS] == []
    assert db.db[RUNS][0]["one_sided_skipped"] == 1 and db.db[RUNS][0]["open_markets"] == 1


def test_an_unknown_model_reads_unknown_never_zero():
    db = Store()
    _run(db, [raw()], prob=None)
    snap = db.db[SNAPSHOTS][0]
    assert snap["model_prob"] is None and snap["gap_pts"] is None and snap["failed"] == ["model_or_market_unknown"]


def test_near_misses_say_why_and_only_reach_the_book_when_needed():
    db = Store()
    reads = []
    live = SimpleNamespace(open_raws=lambda s: [raw(), raw("KXBTC-B", hours=1.5)])
    source = {"category": "crypto", "series": "KXBTC", "fc": Model(0.62)}
    run_tracker(db, NOW, live=live, sources=[source], read_book=lambda t, s: reads.append(t) or BOOK,
                read_market=lambda t: {}, read_series=lambda s: SERIES)
    assert db.db[SNAPSHOTS][0]["failed"] == ["gap"]
    assert db.db[SNAPSHOTS][1]["failed"] == ["gap", "too_close_to_settlement"]
    assert reads == []


def test_an_unreadable_book_is_liquidity_unknown_and_never_flags():
    db = Store()
    live = SimpleNamespace(open_raws=lambda s: [raw()])
    source = {"category": "crypto", "series": "KXBTC", "fc": Model(0.75)}

    def boom(t, s):
        raise RuntimeError("no book")
    run_tracker(db, NOW, live=live, sources=[source], read_book=boom, read_market=lambda t: {}, read_series=lambda s: SERIES)
    assert db.db[SNAPSHOTS][0]["failed"] == ["liquidity_unknown"] and db.db[POSITIONS] == []


def test_a_thin_book_fails_on_depth():
    db = Store()
    _run(db, [raw()], book=[["0.58", "1"]])
    assert db.db[SNAPSHOTS][0]["failed"] == ["not_enough_depth"]


def test_an_unnamed_resolution_source_fails_the_gate():
    db = Store()
    _run(db, [raw()], series={**SERIES, "settlement_sources": []})
    snap = db.db[SNAPSHOTS][0]
    assert snap["resolution_source"] is None and snap["failed"] == ["resolution_source_unknown"]


def test_never_more_than_five_open():
    db = Store()
    _run(db, [raw(f"KXBTC-E{i}-T1") for i in range(8)])
    assert len(db.db[POSITIONS]) == logic.MAX_POSITIONS


def test_an_event_holds_two_positions_at_most_biggest_gaps_first():
    db = Store()
    raws = [raw("KXWTI-E1-T1", ask="0.60", no_ask="0.42"), raw("KXWTI-E1-T2", ask="0.50", no_ask="0.52"),
            raw("KXWTI-E1-T3", ask="0.55", no_ask="0.47"), raw("KXWTI-E2-T1", ask="0.60", no_ask="0.42")]
    summary = _run(db, raws)
    assert summary["flagged"] == 4 and summary["opened"] == 3
    tickers = {p["ticker"] for p in db.db[POSITIONS]}
    assert tickers == {"KXWTI-E1-T2", "KXWTI-E1-T3", "KXWTI-E2-T1"}  # T1 had E1's smallest gap
    assert sum(r["flagged"] for r in db.db[SNAPSHOTS]) == 4  # the third is still on the record


def test_positions_already_over_the_event_limit_block_new_ones_and_stay_open():
    db = Store()
    for i in range(3):
        db.table(POSITIONS).insert({"ticker": f"KXWTI-E1-T{i}", "status": "open", "side": "yes", "contracts": 1,
                                    "settles_at": (NOW + timedelta(hours=9)).isoformat(), "model_at_entry": 0.75,
                                    "entry_price": 0.5, "entry_fee": 0.0, "gap_pts": 9.0}).execute()
    assert _run(db, [raw("KXWTI-E1-T9")])["opened"] == 0
    assert [p["status"] for p in db.db[POSITIONS]] == ["open", "open", "open"]


def test_a_closed_gap_exits_at_the_bid_net_of_fees():
    db = Store()
    _run(db, [raw()])
    pos = db.db[POSITIONS][0]
    _run(db, [raw(bid="0.72", ask="0.74", no_bid="0.26", no_ask="0.28")], now=NOW + timedelta(hours=1))
    assert pos["status"] == "closed" and pos["exit_reason"] == "gap_closed" and pos["exit_price"] == pytest.approx(0.72)
    expected = pos["contracts"] * (0.72 - 0.60) - pos["entry_fee"] - logic.fee_dollars(0.72, pos["contracts"])
    assert pos["pnl"] == pytest.approx(expected) and pos["pnl_basis"] == NET


def test_a_missing_exit_quote_stays_open_and_says_unknown():
    db = Store()
    _run(db, [raw()])
    pos = db.db[POSITIONS][0]
    _run(db, [raw(bid="0.0000", ask="0.74")], now=NOW + timedelta(hours=1))
    assert pos["status"] == "open" and pos["exit_state"].startswith("UNKNOWN") and pos.get("pnl") is None


def test_an_exit_is_priced_across_the_book_not_just_the_best_bid():
    db = Store()
    _run(db, [raw()])
    pos = db.db[POSITIONS][0]
    book = [["0.70", "5000"], ["0.72", "500"]]  # half the position at each price
    _run(db, [raw(bid="0.72", ask="0.74", no_bid="0.26", no_ask="0.28")], now=NOW + timedelta(hours=1), book=book)
    assert pos["exit_price"] == pytest.approx(0.71)


def test_a_book_too_thin_for_the_exit_stays_open_and_unknown():
    db = Store()
    _run(db, [raw()])
    pos = db.db[POSITIONS][0]
    _run(db, [raw(bid="0.72", ask="0.74", no_bid="0.26", no_ask="0.28")], now=NOW + timedelta(hours=1),
         book=[["0.72", "5"]])
    assert pos["status"] == "open" and pos["exit_state"].startswith("UNKNOWN")


def test_a_failed_close_leaves_the_outcome_unrecorded_for_a_retry(monkeypatch):
    db = Store()
    _run(db, [raw()])
    db.unresolved = ["KXBTC-A"]

    def boom(*a, **k):
        raise RuntimeError("write failed")
    monkeypatch.setattr("tradehub.gaps.run.close_position", boom)
    with pytest.raises(RuntimeError):
        _run(db, [], market=lambda t: {"result": "yes"}, now=NOW + timedelta(hours=6))
    assert OUTCOMES not in db.db


def test_a_void_market_marks_the_position_unknown():
    db = Store()
    _run(db, [raw()])
    db.unresolved = ["KXBTC-A"]
    _run(db, [], market=lambda t: {"result": "void"}, now=NOW + timedelta(hours=6))
    assert db.db[POSITIONS][0]["exit_state"] == "UNKNOWN: market result void" and OUTCOMES not in db.db


def test_a_malformed_market_skips_only_itself(monkeypatch):
    from tradehub.gaps import run as run_mod

    real = run_mod.parse_market

    def picky(r):
        if r["ticker"] == "BAD":
            raise KeyError("floor_strike")
        return real(r)
    monkeypatch.setattr(run_mod, "parse_market", picky)
    db = Store()
    assert _run(db, [raw("BAD"), raw("GOOD")])["logged"] == 1


def test_unknown_fees_are_labelled_gross():
    db = Store()
    _run(db, [raw()], series={**SERIES, "fee_type": "something_new"})
    pos = db.db[POSITIONS][0]
    assert pos["entry_fee"] is None
    _run(db, [raw(bid="0.72", ask="0.74", no_bid="0.26", no_ask="0.28")], now=NOW + timedelta(hours=1), series={**SERIES, "fee_type": "something_new"})
    assert pos["pnl_basis"] == GROSS and pos["pnl"] == pytest.approx(pos["contracts"] * 0.12)


def test_settlement_records_the_outcome_and_closes_the_position():
    db = Store()
    _run(db, [raw()])
    pos = db.db[POSITIONS][0]
    db.unresolved = ["KXBTC-A"]
    _run(db, [], market=lambda t: {"result": "yes"}, now=NOW + timedelta(hours=6))
    assert db.db[OUTCOMES][0] == {**db.db[OUTCOMES][0], "ticker": "KXBTC-A", "outcome": 1}
    assert pos["exit_reason"] == "settlement"
    assert pos["pnl"] == pytest.approx(pos["contracts"] * 0.40 - pos["entry_fee"])


def test_an_unsettled_result_records_nothing():
    db = Store()
    db.unresolved = ["KXBTC-A"]
    _run(db, [], market=lambda t: {"result": ""})
    assert OUTCOMES not in db.db


def test_one_bad_series_is_reported_and_others_continue():
    db = Store()

    def boom(s):
        raise RuntimeError("series down")
    summary = run_tracker(
        db, NOW, live=SimpleNamespace(open_raws=boom),
        sources=[{"category": "crypto", "series": "KXBTC", "fc": Model(0.75)}],
        read_book=lambda t, s: BOOK, read_market=lambda t: {}, read_series=lambda s: SERIES)
    assert "series down" in summary["errors"][0] and "series down" in db.db[RUNS][0]["error"]


# ── the desk read ──

class ReportStore(Store):
    def __init__(self, pairs=(), funnel=()):
        super().__init__()
        self.rpcs = {"gap_first_pairs": list(pairs), "gap_funnel": list(funnel)}

    def rpc(self, name, params=None):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rpcs.get(name, [])))


def test_pairs_page_past_the_row_cap(monkeypatch):
    monkeypatch.setattr("tradehub.gaps.report.PAIR_PAGE", 2)
    pages = {"": [{"ticker": t, "category": "oil", "model": 0.5, "market": 0.5, "outcome": 1} for t in ("A", "B")],
             "B": [{"ticker": "C", "category": "oil", "model": 0.5, "market": 0.5, "outcome": 1}]}
    db = ReportStore()
    db.rpc = lambda name, params=None: SimpleNamespace(execute=lambda: SimpleNamespace(
        data=pages[params["after_ticker"]] if name == "gap_first_pairs" else []))
    assert desk(db, NOW)["evidence"]["pairs"] == 3


def test_mixed_fees_are_labelled_mixed():
    db = ReportStore()
    db.db[POSITIONS] = [{"id": 1, "status": "closed", "pnl": 1.0, "gap_pts": 9.0, "exit_at": "1", "pnl_basis": GROSS},
                        {"id": 2, "status": "closed", "pnl": 1.0, "gap_pts": 9.0, "exit_at": "2", "pnl_basis": NET}]
    assert desk(db, NOW)["fee_basis"] == "mixed"


def test_one_category_cannot_crowd_out_the_other():
    db = ReportStore()
    db.db[RUNS] = [{"id": 1, "taken_at": "2026-11-04T12:00:00+00:00", "series": "S", "error": None}]
    db.db[SNAPSHOTS] = [{"id": i, "taken_at": "2026-11-04T12:00:00+00:00", "ticker": f"C{i}", "category": "crypto",
                         "flagged": True, "gap_pts": 50.0 + i} for i in range(12)]
    db.db[SNAPSHOTS].append({"id": 99, "taken_at": "2026-11-04T12:00:00+00:00", "ticker": "OIL", "category": "oil",
                             "flagged": True, "gap_pts": 9.0})
    assert "OIL" in [g["ticker"] for g in desk(db, NOW)["top_gaps"]]


def test_the_desk_route_answers_uncached(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main._GAP_DESK_CACHE.update(at=0.0, payload=None)
    main.app.dependency_overrides[get_supabase] = lambda: ReportStore()
    try:
        r = TestClient(main.app).get("/api/gaps/desk")
    finally:
        main.app.dependency_overrides.clear()
        main._GAP_DESK_CACHE.update(at=0.0, payload=None)
    assert r.status_code == 200 and r.json()["evidence"]["status"] == "NOT ENOUGH EVIDENCE"


def test_the_desk_starts_at_zero_and_says_not_enough_evidence():
    out = desk(ReportStore(), NOW)
    assert out["evidence"]["status"] == "NOT ENOUGH EVIDENCE" and out["evidence"]["pairs"] == 0
    assert out["started_at"] is None and out["grade"]["all"]["brier_delta"] is None
    assert out["ledger"]["resolved"] == 0 and out["ledger"]["return_pct"] == 0 and out["top_gaps"] == []


def test_the_desk_reports_pairs_funnel_ledger_and_current_gaps():
    pairs = [{"ticker": "A", "category": "crypto", "model": 0.8, "market": 0.5, "outcome": 1}]
    funnel = [{"category": "crypto", "reason": "rows", "n": 10}, {"category": "crypto", "reason": "gap", "n": 9},
              {"category": "crypto", "reason": "flagged", "n": 1}]
    db = ReportStore(pairs, funnel)
    db.db[RUNS] = [{"id": 1, "taken_at": "2026-10-01T00:00:00+00:00", "series": "KXBTC", "error": None}]
    db.db[SNAPSHOTS] = [
        {"id": 1, "taken_at": "2026-10-01T00:00:00+00:00", "ticker": "OLD", "category": "crypto", "flagged": True, "gap_pts": 20.0, "side": "yes"},
        {"id": 2, "taken_at": "2026-10-01T00:00:00+00:00", "ticker": "A", "category": "crypto", "flagged": True, "gap_pts": 9.0, "side": "yes"},
        {"id": 3, "taken_at": "2026-10-01T00:00:00+00:00", "ticker": "B", "category": "crypto", "flagged": True, "gap_pts": 12.0, "side": "no"},
    ]
    db.db[POSITIONS] = [{"id": 1, "ticker": "A", "status": "open", "gap_pts": 9.0, "pnl": None, "exit_at": None, "opened_at": "x"}]
    out = desk(db, NOW)
    assert out["evidence"]["days"] == pytest.approx(34.5, abs=0.1) and out["evidence"]["pairs"] == 1
    assert out["grade"]["crypto"]["n"] == 1
    assert out["funnel"]["crypto"] == {"rows": 10, "gap": 9, "flagged": 1}
    assert [g["ticker"] for g in out["top_gaps"]][:2] == ["OLD", "B"] and len(out["open_positions"]) == 1


def test_ledger_by_category_splits_each_desk_and_reconciles():
    db = ReportStore()
    db.db[POSITIONS] = [
        {"id": 1, "ticker": "A", "category": "oil", "status": "closed", "pnl": 120.5, "gap_pts": 9.0, "exit_at": "1"},
        {"id": 2, "ticker": "B", "category": "oil", "status": "closed", "pnl": -40.0, "gap_pts": 9.0, "exit_at": "2"},
        {"id": 3, "ticker": "C", "category": "oil", "status": "closed", "pnl": -10.25, "gap_pts": 9.0, "exit_at": "3"},
        {"id": 4, "ticker": "D", "category": "crypto", "status": "closed", "pnl": -260.0, "gap_pts": 9.0, "exit_at": "4"},
        {"id": 5, "ticker": "E", "category": "crypto", "status": "closed", "pnl": 30.0, "gap_pts": 9.0, "exit_at": "5"},
        {"id": 6, "ticker": "F", "category": "oil", "status": "open", "pnl": None, "gap_pts": 9.0, "exit_at": None},
        {"id": 7, "ticker": "G", "category": "crypto", "status": "closed", "pnl": None, "gap_pts": 9.0, "exit_at": "6"},
    ]
    out = desk(db, NOW)
    by_cat = out["ledger_by_category"]
    assert by_cat["oil"] == {"closed": 3, "realized": 70.25, "win_rate": pytest.approx(1 / 3),
                             "median_pnl": -10.25}
    assert by_cat["crypto"] == {"closed": 2, "realized": -230.0, "win_rate": 0.5, "median_pnl": -115.0}
    # The desks are the same trades as the shared ledger: counts and dollars reconcile.
    assert sum(c["closed"] for c in by_cat.values()) == out["ledger"]["resolved"] == 5
    assert sum(c["realized"] for c in by_cat.values()) == pytest.approx(
        out["ledger"]["bankroll"] - logic.BANKROLL, abs=0.01)


def test_ledger_by_category_counts_past_the_closed_page_cap():
    db = ReportStore()
    db.db[POSITIONS] = [
        {"id": i, "ticker": f"T{i}", "category": "oil", "status": "closed", "pnl": 1.0,
         "gap_pts": 9.0, "exit_at": str(i)} for i in range(60)
    ]
    out = desk(db, NOW)
    assert len(out["closed_positions"]) == 50  # the page of trades stays capped
    assert out["ledger_by_category"]["oil"]["closed"] == 60
    assert out["ledger_by_category"]["oil"]["realized"] == 60.0
