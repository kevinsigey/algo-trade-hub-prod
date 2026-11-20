"""Would-have-filled record + dead-book alert (Kevin's ruling,
2026-11-17): at each demo decision the runner reads the PRODUCTION
book (stubbed here) and records what the real book would have done;
when a whole ET session's decisions skip on an unavailable demo ask,
one deduped alert fires and the report's health line says so.

No network: the prod reader is monkeypatched, the portfolio is the
house fake, the DB is the house fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradehub import kalshi_demo as kd
from tradehub import oil_fifteen_rule as rule
from tests.test_kalshi_demo import FakePortfolio, decision, order_row, seed
from tests.workshop_fake import DB

NOW = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)  # Thu 12:00 ET
TICKER = "KXNATGAS15M-26NOV121215-00"
TARGET = f"kalshi:{TICKER}"


def _prod_market(yes_ask: float, yes_bid: float | None = None) -> dict:
    bid = yes_ask - 0.02 if yes_bid is None else yes_bid
    return {"ticker": TICKER,
            "yes_ask_dollars": f"{yes_ask:.4f}",
            "yes_bid_dollars": f"{bid:.4f}",
            "no_ask_dollars": f"{1.02 - yes_ask:.4f}",
            "no_bid_dollars": f"{1.0 - yes_ask:.4f}"}


@pytest.fixture()
def prod(monkeypatch):
    """A stubbed production book: yes ask 0.38, deep at the ask."""
    state = {"market": _prod_market(0.38), "size": 100, "down": False}

    def read_market(ticker):
        return None if state["down"] else state["market"]

    def read_ask_size(ticker, side, ask):
        return state["size"]

    monkeypatch.setattr(kd.kalshi_prod_book, "read_market", read_market)
    monkeypatch.setattr(kd.kalshi_prod_book, "read_ask_size", read_ask_size)
    return state


@pytest.fixture(autouse=True)
def _open_decisions(monkeypatch):
    monkeypatch.setattr(kd.fifteen_tracking, "open_decisions",
                        lambda supa, now, series_set=None: list(supa.db.get("_open", [])))


def _seeded(db, **kw):
    db = seed(db, **kw)
    db.db.setdefault(kd.PROD_FILLS, [])
    db.db.setdefault("watcher_alerts", [])
    return db


def _fills(db):
    return db.db[kd.PROD_FILLS]


def test_a_decision_records_a_would_fill_against_the_real_book(prod):
    # The demo book is empty (the Kevin case): the demo decision skips
    # live_ask_unavailable, but the production record still lands.
    db = _seeded(DB(), open_=[decision()])
    pf = FakePortfolio()
    pf.live_market = False
    out = kd.run_once(db, pf, NOW)
    assert out["prod_recorded"] == 1  # the live lane; the edge20 lane's bar is 20c
    rows = _fills(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["gate_version"] == "v1" and row["side"] == "yes"
    assert row["frozen_quote"] == 0.40
    assert row["prod_yes_ask"] == 0.38 and row["prod_yes_bid"] == 0.36
    assert row["would_price"] == 0.38 and row["ask_size"] == 100
    assert row["contracts"] == 13  # $500 x 1% / $0.38
    assert row["status"] == "would_fill"
    # And the demo side behaved exactly as before: a clean skip.
    assert db.db[kd.ORDERS][0]["skip_reason"] == "live_ask_unavailable"


def test_the_record_is_written_once_per_decision(prod):
    db = _seeded(DB(), open_=[decision()])
    pf = FakePortfolio()
    pf.live_market = False
    kd.run_once(db, pf, NOW)
    out = kd.run_once(db, pf, NOW + timedelta(minutes=5))
    assert out["prod_recorded"] == 0
    assert len(_fills(db)) == 1


def test_no_edge_at_the_production_ask(prod):
    prod["market"] = _prod_market(0.52)  # edge ~1c against the 10c bar
    db = _seeded(DB(), open_=[decision()])
    kd.run_once(db, FakePortfolio(), NOW)
    row = _fills(db)[0]
    assert row["status"] == "no_edge_at_ask"
    assert row["would_price"] == 0.52


def test_a_production_run_past_the_frozen_quote_is_slippage_capped(prod):
    prod["market"] = _prod_market(0.46)
    db = _seeded(DB(), open_=[decision(model_prob=0.75)])
    kd.run_once(db, FakePortfolio(), NOW)
    row = _fills(db)[0]
    assert row["status"] == "slippage_cap"
    assert row["would_price"] == 0.46


def test_a_thin_production_book_is_thin_not_a_fill(prod):
    prod["size"] = 5  # fewer on offer than the 13 the sizing wants
    db = _seeded(DB(), open_=[decision()])
    kd.run_once(db, FakePortfolio(), NOW)
    row = _fills(db)[0]
    assert row["status"] == "thin"
    assert row["ask_size"] == 5 and row["contracts"] == 13


def test_unknown_depth_records_nothing(prod):
    # CodeRabbit on #560: an unmeasured book is not an observation -- no
    # row that takes the key or reads as a fill -- like an unreadable book.
    prod["size"] = None
    db = _seeded(DB(), open_=[decision()])
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert _fills(db) == []
    assert out["placed"] == 1  # the demo placement is unaffected


def test_an_empty_side_is_no_cross_not_no_edge(prod):
    # Claude's review: an empty side (the cross finds nothing) is not
    # a no-edge call -- the row carries its own no_cross status.
    prod["market"] = _prod_market(1.0)  # yes ask 1.0000: the empty side
    db = _seeded(DB(), open_=[decision()])
    kd.run_once(db, FakePortfolio(), NOW)
    row = _fills(db)[0]
    assert row["status"] == "no_cross"
    assert row["would_price"] is None


def test_an_unreadable_production_book_records_nothing(prod):
    prod["down"] = True
    db = _seeded(DB(), open_=[decision()])
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert _fills(db) == []
    assert out["placed"] == 1  # the demo placement is unaffected


def test_a_would_fill_settles_from_the_window_outcome(prod):
    db = _seeded(DB(), open_=[decision()])
    pf = FakePortfolio()
    pf.live_market = False
    kd.run_once(db, pf, NOW)
    # The outcome lands on the tracked decision; the next pass settles.
    db.db[kd.DECISIONS] = [decision(outcome=1)]
    out = kd.run_once(db, pf, NOW + timedelta(minutes=20))
    assert out["prod_settled"] == 1
    row = _fills(db)[0]
    assert row["outcome"] == 1
    assert row["pnl"] == round(13 * rule.pnl("yes", 0.38, 1), 4)
    assert row["settled_at"] is not None


def test_the_dead_book_alert_fires_once_per_session(prod):
    skip = order_row(status="skipped_no_depth",
                     skip_reason="live_ask_unavailable",
                     created_at=NOW.isoformat())
    db = _seeded(DB(), orders=[skip])
    kd.run_once(db, FakePortfolio(), NOW)
    kd.run_once(db, FakePortfolio(), NOW + timedelta(minutes=5))
    alerts = [a for a in db.db["watcher_alerts"]
              if (a.get("evidence") or {}).get("event") == "dead_book"]
    assert len(alerts) == 1
    assert alerts[0]["title"] == "Kalshi demo book empty: KXNATGAS15M"
    assert alerts[0]["evidence"]["count"] == 1


def test_a_reachable_book_means_no_dead_book_alert(prod):
    skip = order_row(status="skipped_no_depth",
                     skip_reason="live_ask_unavailable",
                     created_at=NOW.isoformat())
    placed = order_row(id=2, status="resting",
                       created_at=NOW.isoformat())
    db = _seeded(DB(), orders=[skip, placed])
    kd.run_once(db, FakePortfolio(), NOW)
    assert db.db["watcher_alerts"] == []


def test_report_health_and_prod_book_lines(prod):
    skip = order_row(status="skipped_no_depth",
                     skip_reason="live_ask_unavailable",
                     created_at=NOW.isoformat())
    fill = {"id": 1, "series": kd.SERIES, "target": TARGET,
            "gate_version": "v1", "ticker": TICKER, "side": "yes",
            "model_prob": 0.55, "frozen_quote": 0.40,
            "prod_yes_bid": 0.36, "prod_yes_ask": 0.38,
            "prod_no_bid": 0.62, "prod_no_ask": 0.64,
            "ask_size": 100, "would_price": 0.38, "contracts": 13,
            "status": "would_fill", "outcome": 1,
            "pnl": round(13 * rule.pnl("yes", 0.38, 1), 4),
            "window_close": (NOW + timedelta(minutes=10)).isoformat(),
            "created_at": NOW.isoformat(), "settled_at": NOW.isoformat()}
    db = _seeded(DB(), orders=[skip])
    db.db[kd.PROD_FILLS] = [fill]
    kd._summary_cache = None
    pf = FakePortfolio()
    pf.get_positions = lambda: []
    report = kd.build_report(db, pf, NOW)
    kd._summary_cache = None
    assert report["health"] == ["demo book empty: KXNATGAS15M"]
    (lane,) = report["prod_book"]
    assert lane["gate_version"] == "v1"
    assert lane["recorded"] == 1 and lane["would_fill"] == 1
    assert lane["fill_rate"] == 1.0 and lane["settled"] == 1
    assert lane["pnl_per_contract"] == round(
        fill["pnl"] / 13, 4)
    # One settled fill on one day is a single cluster: the clustered
    # estimator honestly returns no interval yet.
    assert lane["low95_cents"] is None


def test_settle_reaches_the_newest_would_fill_rows_past_the_limit(prod):
    # 1,000 older would_fill rows whose outcomes never land, then the
    # settleable row as the newest: the settle read must come back
    # newest-first or the limit hides it forever (Claude's #560 review).
    old = [{"id": i + 1, "series": kd.SERIES, "target": f"kalshi:OLD-{i}",
            "gate_version": "v1", "ticker": "OLD", "side": "yes",
            "would_price": 0.38, "contracts": 1, "status": "would_fill",
            "outcome": None, "created_at": "2026-11-01T00:00:00+00:00"}
           for i in range(1000)]
    newest = {"id": 1001, "series": kd.SERIES, "target": TARGET,
              "gate_version": "v1", "ticker": TICKER, "side": "yes",
              "would_price": 0.38, "contracts": 13, "status": "would_fill",
              "outcome": None, "created_at": NOW.isoformat()}
    db = _seeded(DB())
    db.db[kd.PROD_FILLS] = old + [newest]
    db.db[kd.DECISIONS] = [decision(outcome=1)]
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert out["prod_settled"] == 1
    row = _fills(db)[-1]
    assert row["outcome"] == 1
    assert row["pnl"] == round(13 * rule.pnl("yes", 0.38, 1), 4)


def test_the_dead_book_alert_sees_todays_skips_past_the_limit(prod):
    # 500 older rows ahead of today's skip in insertion order: the
    # post-pass read must come back newest-first or the alert misses
    # the session's skips entirely (Claude's #560 review).
    yesterday = (NOW - timedelta(days=1)).isoformat()
    old = [order_row(id=i + 1, status="skipped_no_depth",
                     skip_reason="stale_quote", created_at=yesterday)
           for i in range(500)]
    skip = order_row(id=501, status="skipped_no_depth",
                     skip_reason="live_ask_unavailable",
                     created_at=NOW.isoformat())
    db = _seeded(DB(), orders=old + [skip])
    kd.run_once(db, FakePortfolio(), NOW)
    alerts = [a for a in db.db["watcher_alerts"]
              if (a.get("evidence") or {}).get("event") == "dead_book"]
    assert len(alerts) == 1
    assert alerts[0]["evidence"]["count"] == 1


def test_settle_skips_already_settled_rows_in_the_query(prod):
    # 1,000 newer would_fill rows that are already settled, then an older
    # unsettled row: settled rows must be excluded in the query, before the
    # limit, or they fill the page and hide it (Claude's #560 review, :358).
    settled = [{"id": i + 2, "series": kd.SERIES, "target": f"kalshi:NEW-{i}",
                "gate_version": "v1", "ticker": "NEW", "side": "yes",
                "would_price": 0.38, "contracts": 1, "status": "would_fill",
                "outcome": 0, "pnl": -0.38, "settled_at": NOW.isoformat(),
                "created_at": (NOW + timedelta(minutes=1)).isoformat()}
               for i in range(1000)]
    older = {"id": 1, "series": kd.SERIES, "target": TARGET,
             "gate_version": "v1", "ticker": TICKER, "side": "yes",
             "would_price": 0.38, "contracts": 13, "status": "would_fill",
             "outcome": None, "created_at": (NOW - timedelta(days=1)).isoformat()}
    db = _seeded(DB())
    db.db[kd.PROD_FILLS] = [older] + settled
    db.db[kd.DECISIONS] = [decision(outcome=1)]
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert out["prod_settled"] == 1
    assert _fills(db)[0]["outcome"] == 1


def test_low95_uses_the_same_contract_weighted_mean_as_the_headline():
    # Three settled days with very different sizes. The headline is pnl /
    # contracts; the low95 must be built on that same contract-weighted mean,
    # not an unweighted mean of per-row cents (Claude's #560 review, :1277).
    from tradehub.fifteen_volregime import clustered_low95

    def row(i, day, contracts, cents_per_contract):
        return {"id": i, "series": kd.SERIES, "target": f"kalshi:T{i}",
                "gate_version": "v1", "status": "would_fill",
                "contracts": contracts, "pnl": contracts * cents_per_contract / 100.0,
                "window_close": (NOW + timedelta(days=day)).isoformat(),
                "created_at": (NOW + timedelta(days=day)).isoformat()}

    db = _seeded(DB())
    db.db[kd.PROD_FILLS] = [row(1, 0, 1, 50.0), row(2, 1, 9, -10.0), row(3, 2, 2, 5.0)]
    (lane,) = kd._prod_lane_summaries(db)
    headline_cents = lane["pnl_per_contract"] * 100
    weighted = [((kd.SERIES, d), c) for d, n, c in [(0, 1, 50.0), (1, 9, -10.0), (2, 2, 5.0)]
                for _ in range(n)]
    assert abs(sum(c for _k, c in weighted) / len(weighted) - headline_cents) < 1e-6
    assert lane["low95_cents"] == round(clustered_low95(weighted), 2)
    unweighted = clustered_low95([((kd.SERIES, d), c) for d, c in [(0, 50.0), (1, -10.0), (2, 5.0)]])
    assert lane["low95_cents"] != round(unweighted, 2)
    assert lane["low95_cents"] < headline_cents



def test_an_incomplete_market_response_records_nothing(prod):
    # CodeRabbit on #560: a market object with no readable quote is not a
    # measured empty side; it must not take the key as no_cross.
    prod["market"] = {"ticker": TICKER}
    db = _seeded(DB(), open_=[decision()])
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert _fills(db) == []
    assert out["placed"] == 1


def test_a_settlement_failure_does_not_stop_demo_placement(prod, monkeypatch):
    # CodeRabbit on #560: the observation-only settle step must not take
    # the demo lanes down with it.
    def boom(*_a, **_k):
        raise RuntimeError("settle read failed")

    monkeypatch.setattr(kd, "_settle_prod_fills", boom)
    db = _seeded(DB(), open_=[decision()])
    out = kd.run_once(db, FakePortfolio(), NOW)
    assert out["placed"] == 1
    assert any("prod settle" in e for e in out["errors"])
