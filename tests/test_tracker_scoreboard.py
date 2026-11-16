"""Thesis tracker PR 7 — the scoreboard read model: per-claim
progress computed with the grader's own functions, per-play-kind P&L
from the FIFO join, the two signals graded separately, the regime
panel against the frozen capex lines, the cash-floor gauge, and the
breach log (order-route refusals + stale research files)."""
from datetime import UTC, datetime, timedelta

from workshop_fake import DB

from tradehub.tracker import scoreboard as sb

NOW = datetime(2026, 11, 16, 18, 0, tzinfo=UTC)


def _seed_core(db):
    db.db["theses"] = [
        {"id": 1, "slug": "event-lab", "title": "Event lab",
         "sleeve": "event_lab", "status": "live",
         "kill_lines": [{"symbol": "NVDA", "level": 159.0}],
         "spec_ref": "spec#event-lab"},
        {"id": 2, "slug": "core", "title": "Core beta", "sleeve": "core",
         "status": "live", "kill_lines": [], "spec_ref": "spec#core"},
    ]
    db.db["thesis_falsifiers"] = [
        {"id": 1, "thesis_id": 1, "claim": "A",
         "metric": "classification_separation",
         "threshold": {"min_separation": 0.60, "demote_below": 0.60,
                       "kill_below_rolling": 0.50},
         "window_spec": {"prints": 40, "rolling_kill_prints": 60},
         "deadline": "2027-03-01", "state": "armed"},
        {"id": 2, "thesis_id": 1, "claim": "B",
         "metric": "supplier_excess_per_cluster",
         "threshold": {"kill_mean_excess_max": 0.0,
                       "min_positive_clusters": 3},
         "window_spec": {"clusters": 4},
         "deadline": "2027-11-30", "state": "armed"},
        {"id": 3, "thesis_id": 1, "claim": "C",
         "metric": "play_kind_a_net_after_costs",
         "threshold": {"must_net_positive": True},
         "window_spec": {"fires": 5},
         "deadline": "2027-03-01", "state": "armed"},
    ]
    db.db["tracker_config"] = [
        {"id": 1, "unit_v2_premium": 5000.0, "unit_v2_top": 10000.0,
         "unit_fallback": 1500.0, "play_kind_c_live": False,
         "cash_floor_pct": 10.0}]
    db.db["tracker_health"] = [
        {"id": 1, "last_grader_run_at": (NOW - timedelta(hours=2)).isoformat(),
         "last_grader_ok": True}]
    db.db["regime_inputs"] = [
        {"key": "gray_area_odds", "state": "ratified",
         "detail": {"stalemate": 0.55, "boom": 0.20, "crash": 0.25},
         "as_of": "2026-11-15", "source_note": "Kevin's judgment"},
        {"key": "big4_capex_2027", "state": "unknown",
         "detail": {"crash_below_usd_bn": 620,
                    "boom_at_or_above_usd_bn": 950},
         "as_of": None, "source_note": "lines from Thesis v6"},
        {"key": "credit_light_dc_yields", "state": "unknown",
         "detail": {}, "as_of": None, "source_note": "no free feed"},
        {"key": "credit_light_redemption_gates", "state": "flickering",
         "detail": {}, "as_of": "2026-11-16T00:00:00Z",
         "source_note": "Bank of England"},
        {"key": "credit_light_bank_lending", "state": "off",
         "detail": {}, "as_of": "2026-11-16T00:00:00Z",
         "source_note": "regime note"},
        {"key": "crash_triggers", "state": "unknown",
         "detail": {"fired": []}, "as_of": None,
         "source_note": "maintained by hand"},
    ]


def _seed_grades(db):
    cards, outcomes = [], []
    hits_a = [True, True, False, True]
    hits_w = [True, None, False, True]
    hits_m = [None, None, True, None]
    for i in range(4):
        cards.append({"id": 10 + i, "ticker": f"T{i}", "thesis_id": 1,
                      "print_at": f"2026-11-{10 + i}T21:00:00+00:00",
                      "frozen_at": f"2026-11-{10 + i}T12:00:00+00:00"})
        outcomes.append({"id": 20 + i, "card_id": 10 + i,
                         "classification_hit": hits_a[i],
                         "whisper_hit": hits_w[i],
                         "money_flow_hit": hits_m[i]})
    db.db["forecast_cards"] = cards
    db.db["forecast_outcomes"] = outcomes


def _seed_trades(db):
    db.db["trade_links"] = [
        {"id": 1, "client_order_id": "ext-6-a1", "book": "main",
         "forecast_id": 10, "thesis_id": 1, "play_kind": "a",
         "modal_value": 0.4, "opposing_case_ref": "f.md#opp",
         "shadow": False, "created_at": "2026-11-12T15:00:00+00:00"},
        {"id": 2, "client_order_id": "ext-6-b1", "book": "main",
         "forecast_id": None, "thesis_id": 1, "play_kind": "b",
         "modal_value": None, "opposing_case_ref": None,
         "shadow": False, "created_at": "2026-11-13T15:00:00+00:00"},
    ]
    state = {"main": {
        "closed": [
            {"client_order_id": "ext-6-a1", "pnl": 100.0},
            {"client_order_id": "ext-6-b1", "pnl": -30.0}],
        "open_client_ids": set(), "open_order_ids": set()}}
    return state


def _accounts(book):
    return {"main": {"cash": "20000", "portfolio_value": "100000"},
            "big": {"cash": "5000", "portfolio_value": "100000"}}.get(book)


def _board(db, state=None):
    return sb.build_scoreboard(
        db, now=NOW, book_state=state if state is not None else {},
        account_fn=_accounts)


# ── the interval ─────────────────────────────────────────────────────

def test_wilson_interval_bounds_and_empty():
    assert sb.wilson_interval(0, 0) is None
    lo, hi = sb.wilson_interval(8, 10)
    assert lo < 0.8 < hi and 0.0 <= lo and hi <= 1.0
    lo, hi = sb.wilson_interval(0, 5)
    assert lo == 0.0 and hi > 0.0


# ── claims ───────────────────────────────────────────────────────────

def test_claim_a_progress_matches_the_grader_math():
    db = DB()
    _seed_core(db)
    _seed_grades(db)
    board = _board(db)
    claim_a = next(c for c in board["claims"] if c["claim"] == "A")
    assert claim_a["thesis_slug"] == "event-lab"
    assert claim_a["state"] == "armed"
    assert claim_a["graded"] == 4 and claim_a["hits"] == 3
    assert claim_a["rate"] == 0.75
    assert claim_a["interval"] is not None
    assert claim_a["prints_target"] == 40
    assert claim_a["prints_remaining"] == 36
    assert claim_a["days_to_deadline"] == (
        datetime(2027, 3, 1).date() - NOW.date()).days


def test_claim_b_is_an_honest_countdown_with_nothing_graded():
    db = DB()
    _seed_core(db)
    board = _board(db)
    claim_b = next(c for c in board["claims"] if c["claim"] == "B")
    assert claim_b["clusters_target"] == 4
    assert claim_b["clusters_graded"] == 0
    assert claim_b["clusters_remaining"] == 4
    assert claim_b["mean_excess"] is None
    assert claim_b["rate"] is None


def test_claim_c_counts_fires_from_the_fifo_walk():
    db = DB()
    _seed_core(db)
    board = _board(db, _seed_trades(db))
    claim_c = next(c for c in board["claims"] if c["claim"] == "C")
    assert claim_c["graded"] == 1
    assert claim_c["fires_remaining"] == 4
    assert claim_c["net"] == 100.0
    assert claim_c["progress_verdict"] is None


def test_signals_are_graded_separately_never_combined():
    db = DB()
    _seed_core(db)
    _seed_grades(db)
    board = _board(db)
    assert board["signals"]["whisper"]["graded"] == 3
    assert board["signals"]["whisper"]["hits"] == 2
    assert board["signals"]["money_flow"]["graded"] == 1
    assert board["signals"]["money_flow"]["hits"] == 1
    assert "combined" not in board["signals"]


# ── play kinds, sizing, registry ─────────────────────────────────────

def test_play_kinds_report_pnl_and_hit_rate_separately():
    db = DB()
    _seed_core(db)
    board = _board(db, _seed_trades(db))
    assert board["play_kinds"]["a"]["pnl"] == 100.0
    assert board["play_kinds"]["a"]["hit_rate"] == 1.0
    assert board["play_kinds"]["b"]["pnl"] == -30.0
    assert board["play_kinds"]["b"]["hit_rate"] == 0.0
    assert "c" not in board["play_kinds"]


def test_sizing_block_reads_the_governing_unit_live():
    db = DB()
    _seed_core(db)
    board = _board(db)
    assert board["sizing"]["governing_unit"]["unit"] == 5000.0
    assert board["sizing"]["governing_unit"]["source"] == "schedule_v2"
    assert board["sizing"]["health"]["last_grader_ok"] is True
    registry = {t["slug"]: t for t in board["theses"]}
    assert registry["event-lab"]["kill_line_count"] == 1
    assert registry["core"]["status"] == "live"


# ── regime panel + cash gauge ────────────────────────────────────────

def test_regime_panel_odds_lights_and_unrecorded_capex():
    db = DB()
    _seed_core(db)
    regime = _board(db)["regime"]
    assert regime["odds"]["stalemate"] == 0.55
    assert regime["odds"]["crash"] == 0.25
    assert regime["capex"]["figure_usd_bn"] is None
    assert regime["capex"]["grading"] is None
    assert regime["capex"]["crash_below_usd_bn"] == 620
    assert regime["capex"]["boom_at_or_above_usd_bn"] == 950
    lights = {row["key"]: row for row in regime["credit_lights"]}
    assert lights["credit_light_redemption_gates"]["state"] == "flickering"
    assert lights["credit_light_redemption_gates"]["age_days"] == 0.8
    assert lights["credit_light_bank_lending"]["state"] == "off"
    assert regime["crash_triggers"]["fired_count"] == 0


def test_capex_figure_grades_against_the_frozen_lines():
    rows = [{"key": "big4_capex_2027", "state": "tracking",
             "detail": {"crash_below_usd_bn": 620,
                        "boom_at_or_above_usd_bn": 950, "usd_bn": 500},
             "as_of": None, "source_note": ""}]
    assert sb._regime_block(rows, now=NOW)["capex"]["grading"] == "crash"
    rows[0]["detail"]["usd_bn"] = 700
    assert sb._regime_block(rows, now=NOW)["capex"]["grading"] == "between"
    rows[0]["detail"]["usd_bn"] = 1000
    assert sb._regime_block(rows, now=NOW)["capex"]["grading"] == "boom"


def test_cash_gauge_flags_the_book_under_the_floor():
    db = DB()
    _seed_core(db)
    gauge = _board(db)["cash_gauge"]
    assert gauge["floor_pct"] == 10.0
    books = {b["book"]: b for b in gauge["books"]}
    assert books["main"]["cash_pct"] == 20.0
    assert books["main"]["breach"] is False
    assert books["big"]["cash_pct"] == 5.0
    assert books["big"]["breach"] is True


# ── breach log ───────────────────────────────────────────────────────

def test_breach_log_keeps_order_route_refusals_and_stale_files():
    db = DB()
    _seed_core(db)
    db.db["api_key_events"] = [
        {"id": 1, "key_id": 3, "route": "POST /api/v1/orders",
         "outcome": "refused:tracker",
         "detail": "post-trade cash share 8.1% breaches the 10% cash floor",
         "at": "2026-11-16T15:00:00+00:00", "client_order_id": "x1"},
        {"id": 2, "key_id": 3,
         "route": "POST /api/v1/forward-file/classifications",
         "outcome": "refused:scope", "detail": "missing scope",
         "at": "2026-11-16T15:05:00+00:00", "client_order_id": None},
        {"id": 3, "key_id": 3, "route": "POST /api/v1/orders/preflight",
         "outcome": "refused:tracker",
         "detail": "event-lab order carries no opposing_case_ref",
         "at": "2026-11-16T15:10:00+00:00", "client_order_id": "x2"},
        {"id": 4, "key_id": 3, "route": "POST /api/v1/orders",
         "outcome": "placed", "detail": None,
         "at": "2026-11-16T15:15:00+00:00", "client_order_id": "x3"},
    ]
    db.db["research_files"] = [
        {"id": 1, "path": "research/nvda.md", "thesis_id": 1,
         "amended_at": "2026-11-10T00:00:00+00:00",
         "last_decision_at": "2026-11-12T00:00:00+00:00"},
        {"id": 2, "path": "research/amat.md", "thesis_id": 1,
         "amended_at": "2026-11-13T00:00:00+00:00",
         "last_decision_at": "2026-11-12T00:00:00+00:00"},
        {"id": 3, "path": "research/new.md", "thesis_id": 2,
         "amended_at": None, "last_decision_at": None},
    ]
    board = _board(db)
    refusals = board["breaches"]["refusals"]
    assert [r["client_order_id"] for r in refusals] == ["x2", "x1"]
    assert refusals[1]["cash_floor"] is True
    assert refusals[0]["cash_floor"] is False
    stale = board["breaches"]["stale_files"]
    assert [f["path"] for f in stale] == ["research/nvda.md"]
    assert stale[0]["thesis_slug"] == "event-lab"


def test_empty_tracker_reads_as_an_empty_board_not_an_error():
    db = DB()
    board = _board(db)
    assert board["theses"] == [] and board["claims"] == []
    assert board["play_kinds"] == {}
    assert board["signals"]["whisper"]["graded"] == 0
    assert board["sizing"]["governing_unit"]["unit"] == 1500.0
    assert board["breaches"] == {"refusals": [], "stale_files": []}


# ── the route ────────────────────────────────────────────────────────

def test_scoreboard_route_serves_the_board():
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    from tradehub.api.dependencies import get_supabase

    db = DB()
    _seed_core(db)
    _seed_grades(db)
    main.app.dependency_overrides[admin.require_admin] = (
        lambda: {"role": "admin"})
    main.app.dependency_overrides[get_supabase] = lambda: db
    try:
        resp = TestClient(main.app).get("/api/thesis/scoreboard")
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    board = resp.json()["scoreboard"]
    assert [c["claim"] for c in board["claims"]] == ["A", "B", "C"]
    assert board["claims"][0]["graded"] == 4
    assert len(board["theses"]) == 2
