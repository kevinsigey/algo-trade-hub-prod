"""Spec F LEAPS shadow trial (Workshop idea 81, family T8-LEAPS-1,
preregistered 2026-11-11, shadow-first): trigger intake off Spec C
crossing rows for T8 sleeve names only, live-chain contract selection
(delta band, nearest-455 expiry, extrinsic veto), sizing at the $10k
premium cap with the share line at identical delta-notional, nightly
marks (drag / delivery / roll flag), falsifier closes, and the frozen
gate read. Fixtures only — no network."""
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.workshop_fake import DB
from tradehub import leaps_shadow as leaps
from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
EXP = TODAY + timedelta(days=455)          # 2028-02-10, the target expiry
T8 = {"NVDA", "MSFT"}


def _contract(symbol, expiry, strike):
    return {"symbol": symbol, "expiration_date": expiry.isoformat(),
            "strike_price": strike, "type": "call"}


def _chain(spot=100.0):
    """Strikes 60/70/80 around spot 100 at the target expiry; deltas are
    served by the snapshot fake below (0.62 / 0.79 / 0.93)."""
    return [_contract("NVDA  280210C00060000", EXP, 60.0),
            _contract("NVDA  280210C00070000", EXP, 70.0),
            _contract("NVDA  280210C00080000", EXP, 80.0)]


def _snaps(**kw):
    base = {"NVDA  280210C00060000": {"delta": 0.93, "iv": 0.30, "bid": 40.6, "ask": 41.0},
            "NVDA  280210C00070000": {"delta": 0.79, "iv": 0.30, "bid": 31.7, "ask": 32.0},
            "NVDA  280210C00080000": {"delta": 0.62, "iv": 0.30, "bid": 22.5, "ask": 23.0}}
    base.update(kw)
    return base


def _crossing(cid, ticker="NVDA", zone="base", action="starter", price=100.0, book="main"):
    return {"id": cid, "book": book, "ticker": ticker, "zone": zone, "action": action,
            "price": price, "bear": 80.0, "base": 100.0, "bull": 130.0,
            "guide_status": "intact", "snapshot_id": 12, "scan_id": 3,
            "created_at": "2026-11-12T04:00:00+00:00"}


def _providers(**over):
    p = {"contracts_fn": lambda ticker, today: _chain(),
         "snapshots_fn": lambda symbols: _snaps(),
         "quote_fn": lambda symbol: None,
         "spot_fn": lambda ticker: 100.0,
         "t8_fn": lambda client: set(T8)}
    p.update(over)
    return p


def _db_with_crossings(*rows):
    db = DB()
    db.db["band_crossings"] = [dict(r) for r in rows]
    return db


# ── contract selection ───────────────────────────────────────────────────────

def test_select_picks_strike_nearest_point_eight_in_the_band():
    sel, reason = leaps.select_leaps(_chain(), _snaps(), spot=100.0, today=TODAY)
    assert reason is None
    assert sel["strike"] == 70.0 and sel["delta"] == 0.79
    assert sel["ask"] == 32.0 and sel["bid"] == 31.7
    assert sel["extrinsic"] == pytest.approx(2.0)       # 32.0 - (100 - 70)


def test_select_prefers_the_expiry_nearest_455_days():
    near = TODAY + timedelta(days=400)
    far = TODAY + timedelta(days=500)
    chain = [_contract("X     270401C00070000", near, 70.0),
             _contract("X     280210C00070000", EXP, 70.0),
             _contract("X     280326C00070000", far, 70.0)]
    snaps = {c["symbol"]: {"delta": 0.80, "iv": 0.3, "bid": 31.7, "ask": 32.0}
             for c in chain}
    sel, _ = leaps.select_leaps(chain, snaps, spot=100.0, today=TODAY)
    assert sel["expiry"] == EXP


def test_select_no_expiry_in_window_is_a_recorded_refusal():
    chain = [_contract("X     261218C00070000", TODAY + timedelta(days=37), 70.0)]
    sel, reason = leaps.select_leaps(chain, {}, spot=100.0, today=TODAY)
    assert sel is None and reason == "no_expiry_in_window"


def test_select_no_strike_in_the_delta_band():
    snaps = _snaps(**{"NVDA  280210C00070000": {"delta": 0.55, "iv": 0.3, "bid": 31.7, "ask": 32.0},
                      "NVDA  280210C00060000": {"delta": 0.97, "iv": 0.3, "bid": 40.6, "ask": 41.0},
                      "NVDA  280210C00080000": {"delta": 0.40, "iv": 0.3, "bid": 22.5, "ask": 23.0}})
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY)
    assert sel is None and reason == "no_contract_in_delta_band"


def test_select_bs_delta_fallback_when_greeks_are_absent():
    # The 80 strike's snapshot carries an IV but no greeks: the BS delta
    # (~0.798) lands in the band and nearest 0.80, so it wins on the fallback.
    snaps = _snaps(**{"NVDA  280210C00080000": {"delta": None, "iv": 0.30, "bid": 22.5, "ask": 23.0}})
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY)
    assert reason is None and sel["strike"] == 80.0
    # Independent expectation: N(d1) for S=100, K=80, IV=0.30, T=455/365
    # is 0.7978 (computed outside this module; a hardcoded constant, so a
    # wrong fallback formula cannot satisfy both sides of the assert).
    assert sel["delta"] == pytest.approx(0.7978, abs=1e-3)
    assert 0.75 <= sel["delta"] <= 0.85


def test_select_extrinsic_over_fifteen_percent_is_vetoed():
    snaps = _snaps(**{"NVDA  280210C00070000": {"delta": 0.79, "iv": 0.3, "bid": 31.7, "ask": 38.0}})
    # extrinsic = 38 - 30 = 8 > 15% of 38 = 5.7
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY)
    assert sel is None and reason == "extrinsic_over_cap"


def test_select_missing_quote_falls_back_then_refuses():
    snaps = _snaps(**{"NVDA  280210C00070000": {"delta": 0.79, "iv": 0.3, "bid": None, "ask": None}})
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY,
                                     quote_fn=lambda s: (31.7, 32.0))
    assert reason is None and sel["ask"] == 32.0
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY,
                                     quote_fn=lambda s: None)
    assert sel is None and reason == "no_quote"


def test_select_wide_quote_is_no_quote():
    snaps = _snaps(**{"NVDA  280210C00070000": {"delta": 0.79, "iv": 0.3, "bid": 20.0, "ask": 32.0}})
    sel, reason = leaps.select_leaps(_chain(), snaps, spot=100.0, today=TODAY)
    assert sel is None and reason == "no_quote"   # spread 46% of mid > 25%


# ── sizing ───────────────────────────────────────────────────────────────────

def test_size_floors_to_the_premium_cap_and_pairs_the_share_line():
    out, reason = leaps.size_pair(ask=32.0, delta=0.79, spot=100.0, trigger_price=100.0)
    assert reason is None
    assert out["contracts"] == 3                              # floor(10000 / 3200)
    assert out["premium_total"] == pytest.approx(9_600.0)
    assert out["delta_notional"] == pytest.approx(3 * 100 * 0.79 * 100.0)
    assert out["share_shares"] == pytest.approx(out["delta_notional"] / 100.0)
    assert out["share_entry_price"] == 100.0


def test_size_one_contract_over_the_cap_is_refused():
    out, reason = leaps.size_pair(ask=101.0, delta=0.80, spot=500.0, trigger_price=500.0)
    assert out is None and reason == "single_contract_over_cap"


# ── trigger intake ───────────────────────────────────────────────────────────

def test_intake_opens_a_pair_on_a_t8_base_starter():
    db = _db_with_crossings(_crossing(1))
    out = leaps.run_intake(db, now=NOW, **_providers())
    assert out == {"opened": 1, "unfilled": 0, "events": 0, "errors": 0}
    (pair,) = db.db["leaps_shadow_pairs"]
    assert pair["status"] == "open" and pair["ticker"] == "NVDA"
    assert pair["idea_id"] == 81 and pair["crossing_id"] == 1
    assert pair["zone"] == "base" and pair["snapshot_id"] == 12
    assert pair["contracts"] == 3 and pair["entry_ask"] == 32.0
    assert pair["share_entry_price"] == 100.0


def test_intake_ignores_non_t8_bull_zone_and_suppressed_rows():
    db = _db_with_crossings(
        _crossing(1, ticker="AAPL"),                       # not in the T8 sleeve
        _crossing(2, zone="bull", action="none"),          # not an entry zone
        _crossing(3, zone="bear", action="none"),          # suppressed: no action
        _crossing(4, zone="above_bull", action="starter")) # wrong zone entirely
    out = leaps.run_intake(db, now=NOW, **_providers())
    assert out == {"opened": 0, "unfilled": 0, "events": 0, "errors": 0}
    assert db.db.get("leaps_shadow_pairs", []) == []


def test_intake_second_crossing_on_an_open_name_is_an_event_only():
    db = _db_with_crossings(_crossing(1), _crossing(2, book="big"), _crossing(2, book="big"))
    out = leaps.run_intake(db, now=NOW, **_providers())
    assert out == {"opened": 1, "unfilled": 0, "events": 1, "errors": 0}   # idempotent on rerun rows
    (pair,) = db.db["leaps_shadow_pairs"]
    assert [e["crossing_id"] for e in pair["events"]] == [2]


def test_intake_unfillable_trigger_is_recorded_and_does_not_count():
    db = _db_with_crossings(_crossing(1))
    snaps = {s: {"delta": 0.40, "iv": 0.3, "bid": 1.0, "ask": 1.1} for s in _snaps()}
    out = leaps.run_intake(db, now=NOW, **_providers(snapshots_fn=lambda symbols: snaps))
    assert out == {"opened": 0, "unfilled": 1, "events": 0, "errors": 0}
    (row,) = db.db["leaps_shadow_pairs"]
    assert row["status"] == "unfilled" and row["close_reason"] == "no_contract_in_delta_band"
    summary = leaps.trial_summary(db.db["leaps_shadow_pairs"], now=NOW)
    assert summary["pairs_opened"] == 0 and summary["unfilled"] == 1


# ── grading: marks, closes, the gate ─────────────────────────────────────────

def _open_pair(**over):
    pair = {"id": 1, "idea_id": 81, "crossing_id": 1, "ticker": "NVDA",
            "opened_at": "2026-11-12T05:00:00+00:00", "status": "open",
            "occ_symbol": "NVDA  280210C00070000", "strike": 70.0,
            "expiry": EXP.isoformat(), "contracts": 3,
            "entry_bid": 31.7, "entry_mid": 31.85, "entry_ask": 32.0,
            "premium_total": 9_600.0, "delta_at_entry": 0.79,
            "extrinsic_at_entry": 2.0, "spot_at_entry": 100.0,
            "delta_notional": 23_700.0, "share_shares": 237.0,
            "share_entry_price": 100.0, "events": []}
    pair.update(over)
    return pair


def test_marks_math_on_fixed_numbers():
    pair = _open_pair()
    later = NOW + timedelta(days=182)
    patch = leaps.pair_marks(pair, leaps_mid=36.0, share_price=110.0, marked_at=later)
    assert patch["leaps_pnl"] == pytest.approx((36.0 - 32.0) * 300)
    assert patch["share_pnl"] == pytest.approx(10.0 * 237.0)
    # delivery (Kevin's 2026-11-11 definition): LEAPS P&L dollars over
    # share P&L dollars for the pair -- 1200 / 2370, not a ratio of
    # per-dollar returns (which read ~3.0 for a perfect tracker).
    assert patch["delta_delivered"] == pytest.approx(1200 / 2370)
    # drag: extrinsic now = 36 - (110-70) < 0 -> 0; decay = 2*300 - 0 = 600;
    # spread paid = (32-31.85)*300 = 45; years = 182/365
    assert patch["carry_drag_pct"] == pytest.approx((600 + 45) / 23_700 / (182 / 365) * 100)
    assert patch["roll_flag"] is False and patch["mark_stale"] is False


def test_marks_roll_flag_at_180_dte_and_stale_when_no_quote():
    pair = _open_pair()
    at_flag = datetime(2027, 8, 14, 5, 0, tzinfo=UTC)       # exactly 180 days before expiry
    patch = leaps.pair_marks(pair, leaps_mid=None, share_price=110.0, marked_at=at_flag)
    assert patch["dte"] == 180 and patch["roll_flag"] is True
    assert patch["leaps_mid"] is None and patch["mark_stale"] is True
    assert "leaps_pnl" not in patch                          # never fabricated
    day_before = leaps.pair_marks(pair, leaps_mid=None, share_price=110.0,
                                  marked_at=at_flag - timedelta(days=1))
    assert day_before["dte"] == 181 and day_before["roll_flag"] is False


def _grade(db, **over):
    p = {"mid_fn": lambda symbol: 36.0, "spot_fn": lambda ticker: 110.0,
         "sheets_fn": lambda client: []}
    p.update(over)
    return leaps.run_grading(db, now=NOW + timedelta(days=30), **p)


def _sheet(ticker="NVDA", bands=(80.0, 100.0, 130.0), direction="held"):
    return {"ticker": ticker, "bands": {"bear": bands[0], "base": bands[1], "bull": bands[2]},
            "anchor": {"metric": "eps_adjusted"}, "directions": {"eps_adjusted": {"direction": direction}}}


def test_grading_closes_on_above_bull_and_on_guide_cut():
    db = DB(); db.db["leaps_shadow_pairs"] = [_open_pair()]
    out = _grade(db, sheets_fn=lambda c: [_sheet()], spot_fn=lambda t: 150.0)  # price > bull 130
    assert out["closed"] == 1
    assert db.db["leaps_shadow_pairs"][0]["status"] == "closed"
    assert db.db["leaps_shadow_pairs"][0]["close_reason"] == "above_bull"

    db = DB(); db.db["leaps_shadow_pairs"] = [_open_pair()]
    out = _grade(db, sheets_fn=lambda c: [_sheet(direction="cut")])
    assert out["closed"] == 1
    assert db.db["leaps_shadow_pairs"][0]["close_reason"] == "guide_cut"


def test_grading_expires_at_expiry_settled_at_intrinsic():
    db = DB(); db.db["leaps_shadow_pairs"] = [_open_pair()]
    out = leaps.run_grading(db, now=datetime(2028, 2, 11, 5, 0, tzinfo=UTC),
                            mid_fn=lambda s: None, spot_fn=lambda t: 90.0,
                            sheets_fn=lambda c: [])
    pair = db.db["leaps_shadow_pairs"][0]
    assert out["closed"] == 1 and pair["status"] == "expired"
    assert pair["leaps_pnl"] == pytest.approx((90.0 - 70.0) * 300 - 9_600.0)


def _gate_pair(i, drag=2.0, leaps_pnl=900.0, share_pnl=1000.0, **over):
    pair = _open_pair(id=i, crossing_id=i, carry_drag_pct=drag,
                      leaps_pnl=leaps_pnl, share_pnl=share_pnl,
                      status="closed")
    pair.update(over)
    return pair


def test_gate_read_pass_and_kill():
    rows = [_gate_pair(i) for i in range(1, 5)]   # pooled delivery 3600/4000 = 0.9
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["pairs_opened"] == 4 and s["gate"]["state"] == "pass" and s["gate"]["judged"]

    rows[0]["carry_drag_pct"] = 9.0    # mean drag (9+2+2+2)/4 = 3.75 > 3.5
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "killed" and "drag" in s["gate"]["reason"]

    rows = [_gate_pair(i, leaps_pnl=700.0) for i in range(1, 5)]  # pooled 0.7
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "killed" and "delivery" in s["gate"]["reason"]

    s = leaps.trial_summary(rows[:2], now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "open" and not s["gate"]["judged"]


def test_intake_a_failed_chain_read_leaves_the_crossing_for_a_retry():
    db = _db_with_crossings(_crossing(1))

    def boom(ticker, today):
        raise RuntimeError("contracts read failed: HTTP 500")

    out = leaps.run_intake(db, now=NOW, **_providers(contracts_fn=boom))
    assert out == {"opened": 0, "unfilled": 0, "events": 0, "errors": 1}
    assert db.db.get("leaps_shadow_pairs", []) == []        # nothing consumed
    out = leaps.run_intake(db, now=NOW, **_providers())     # the retry lands
    assert out["opened"] == 1


def test_intake_pages_past_a_thousand_consumed_crossings():
    rows = [_crossing(i, ticker="AAPL") for i in range(1, 1002)]  # never T8
    rows.append(_crossing(1002))                                  # the trigger
    db = _db_with_crossings(*rows)
    out = leaps.run_intake(db, now=NOW, **_providers())
    assert out["opened"] == 1


def test_intake_ignores_a_crossing_that_fired_after_the_trial_ended():
    db = DB()
    db.db["leaps_shadow_pairs"] = [_open_pair()]            # opened 2026-11-12
    late = _crossing(9, ticker="MSFT")
    late["created_at"] = "2027-12-25T04:00:00+00:00"        # past trial end
    db.db["band_crossings"] = [late]
    out = leaps.run_intake(db, now=NOW + timedelta(days=30), **_providers())
    assert out == {"opened": 0, "unfilled": 0, "events": 0, "errors": 0}
    assert len(db.db["leaps_shadow_pairs"]) == 1


def test_intake_an_event_recorded_on_a_closed_pair_is_never_reprocessed():
    db = DB()
    pair = _open_pair(status="closed", close_reason="guide_cut",
                      events=[{"type": "trigger", "crossing_id": 5,
                               "at": "2026-11-13T04:00:00+00:00",
                               "zone": "base", "action": "add", "book": "main"}])
    db.db["leaps_shadow_pairs"] = [pair]
    db.db["band_crossings"] = [_crossing(5, action="add")]
    out = leaps.run_intake(db, now=NOW, **_providers())
    assert out == {"opened": 0, "unfilled": 0, "events": 0, "errors": 0}
    assert len(db.db["leaps_shadow_pairs"]) == 1


def test_grading_closes_on_a_guide_cut_even_when_the_spot_read_fails():
    db = DB(); db.db["leaps_shadow_pairs"] = [_open_pair()]
    out = _grade(db, sheets_fn=lambda c: [_sheet(direction="cut")],
                 spot_fn=lambda t: None)
    assert out["closed"] == 1
    assert db.db["leaps_shadow_pairs"][0]["close_reason"] == "guide_cut"


def test_gate_with_no_metrics_is_insufficient_data_never_a_pass():
    rows = [_open_pair(id=i, crossing_id=i, status="closed")
            for i in range(1, 5)]  # closed (mature) but never marked
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["judged"] and s["gate"]["state"] == "insufficient_data"


def test_gate_verdict_is_frozen_on_the_first_four_pairs():
    rows = [_gate_pair(i, drag=d)
            for i, d in enumerate([9.0, 2.0, 2.0, 2.0], start=1)]  # mean 3.75: killed
    rows.append(_gate_pair(5, drag=0.1, leaps_pnl=990.0))
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "killed"                   # pair 5 cannot un-kill


def test_gate_extension_is_read_separately_from_the_first_verdict():
    rows = [_gate_pair(i) for i in range(1, 9)]
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "complete" and s["gate"]["extension"]["state"] == "pass"

    for r in rows[4:]:
        r["leaps_pnl"] = 500.0                               # extension cohort fails
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "pass"                      # first verdict stands
    assert s["gate"]["extension"]["state"] == "killed"


# ── the live-chain reads: failures raise, snapshots batch and page ──────────

class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        return self.responses.pop(0)


def _snap(symbol, delta=0.8):
    return {symbol: {"greeks": {"delta": delta}, "impliedVolatility": 0.3,
                     "latestQuote": {"bp": 10.0, "ap": 10.2}}}


def test_snapshots_batch_at_a_hundred_and_follow_page_tokens(monkeypatch):
    from tradehub.portfolio import alpaca_paper, options
    monkeypatch.setattr(alpaca_paper, "_headers", lambda book=None: {})
    symbols = [f"S{i:03d}" for i in range(150)]
    session = _Session([
        _Resp(200, {"snapshots": _snap("S000"), "next_page_token": "t1"}),
        _Resp(200, {"snapshots": _snap("S001")}),
        _Resp(200, {"snapshots": _snap("S100")}),
    ])
    out = options.fetch_snapshots(symbols, session=session)
    assert out["S000"]["delta"] == 0.8 and out["S001"]["ask"] == 10.2
    assert out["S100"]["iv"] == 0.3
    assert len(session.calls) == 3                          # 2 pages + batch 2
    assert session.calls[1].get("page_token") == "t1"
    assert len(session.calls[2]["symbols"].split(",")) == 50


def test_snapshots_and_window_reads_raise_on_http_errors(monkeypatch):
    from tradehub.portfolio import alpaca_paper, options
    monkeypatch.setattr(alpaca_paper, "_headers", lambda book=None: {})
    with pytest.raises(RuntimeError):
        options.fetch_snapshots(["S000"], session=_Session([_Resp(500)]))
    ok = _Resp(200, {"option_contracts": [], "next_page_token": "t1"})
    with pytest.raises(RuntimeError):                       # page 2 fails whole
        options.fetch_contracts_window("NVDA", "call", TODAY, EXP,
                                       session=_Session([ok, _Resp(429)]))


# ── the API surface: the panel rides the idea detail, tag-gated ─────────────

@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: ("closes", tuple(tickers)))
    monkeypatch.setattr(main, "workshop_fred", lambda series, start: "series")
    monkeypatch.setattr(main, "workshop_earnings", lambda t: f"earnings:{t}")
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def _idea(db, tags):
    row = {"id": 81, "title": "Spec F", "plain_words": "x", "tags": tags,
           "published_at": "2026-11-11T22:20:25+00:00"}
    db.db.setdefault("ideas", []).append(row)
    db.db.setdefault("workshop_runs", [])
    return row


def test_detail_carries_the_leaps_panel_only_for_the_tag(api):
    c, db = api
    _idea(db, ["leaps-trial"])
    db.db["leaps_shadow_pairs"] = [_open_pair()]
    body = c.get("/api/workshop/ideas/81").json()
    assert body["leaps"]["summary"]["pairs_opened"] == 1
    assert body["leaps"]["pairs"][0]["ticker"] == "NVDA"

    db.db["ideas"][0]["tags"] = []
    body = c.get("/api/workshop/ideas/81").json()
    assert body["leaps"] is None
