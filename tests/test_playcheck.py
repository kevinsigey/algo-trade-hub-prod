"""The one-click play check (Kevin, 2026-11-02): pure diff math + the two
endpoints (Workshop working spec, public record spec). Read-only throughout."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import service as portfolio_service
from tradehub.workshop.playcheck import play_check
from workshop_fake import DB


BASE = dict(why="", prices={"GLD": 250.0, "ASML": 500.0, "SPY": 500.0, "XLE": 100.0},
            equity=100_000.0, cash=60_000.0, positions=[], size_pct=10.0,
            own_title="Mine", otherwise="SPY", legs=["GLD"])


def test_target_book_and_affordable():
    out = play_check(weights={"GLD": 0.5, "ASML": 0.5}, **BASE)
    rows = {r["ticker"]: r for r in out["rows"]}
    assert rows["GLD"]["target_value"] == 5_000 and rows["GLD"]["target_shares"] == 20
    assert rows["ASML"]["target_value"] == 5_000 and rows["ASML"]["target_shares"] == 10
    assert out["buys"] == 10_000 and out["verdict"] == "affordable" and out["state"] == "in"
    assert out["rows"][0]["ticker"] in ("GLD", "ASML")  # sorted by |delta|


def test_unrelated_holdings_are_not_the_plays_funding():
    # Kevin's correction (2026-11-03): a holding that is not one of the play's
    # tickers is never a "sell" and never funds the play -- the verdict rests
    # on the cash at hand alone.
    out = play_check(weights={"GLD": 1.0}, **{**BASE, "cash": 2_000.0, "positions": [
        {"symbol": "SPY", "qty": 16, "market_value": 8_000, "idea": "No idea yet (manual)"}]})
    assert out["buys"] == 10_000 and out["sells"] == 0
    assert out["verdict"] == "not_affordable" and out["shortfall"] == 8_000
    assert all(r["ticker"] != "SPY" for r in out["rows"])


def test_own_leg_trims_can_fund_the_buys():
    # The only sells that count: trimming the play's OWN over-target leg.
    out = play_check(weights={"GLD": 0.5, "ASML": 0.5}, **{**BASE, "cash": 2_000.0, "positions": [
        {"symbol": "ASML", "qty": 18, "market_value": 9_000, "idea": "Mine"},
        {"symbol": "SPY", "qty": 16, "market_value": 8_000, "idea": "No idea yet (manual)"}]})
    assert out["buys"] == 5_000 and out["sells"] == 4_000
    assert out["verdict"] == "affordable_after_sells" and out["shortfall"] == 0
    assert "trimming $4,000 of the play's own" in out["verdict_line"]


def test_wrap_coverage_and_in_place_the_chip_makers_shape():
    # Kevin's live example (2026-11-03): chips at 20% of the sleeve around a
    # defensive core the book already holds, plus unrelated holdings that
    # must not enter the math at all.
    weights = {"TSM": 1 / 15, "INTC": 1 / 15, "TXN": 1 / 15,
               "XLV": 4 / 15, "XLP": 4 / 15, "XLU": 4 / 15}
    prices = {"TSM": 400.0, "INTC": 60.0, "TXN": 300.0, "XLV": 185.0, "XLP": 91.0, "XLU": 44.0}
    out = play_check(weights=weights, why="", prices=prices, equity=100_000.0, cash=59_240.0,
                     positions=[
                         {"symbol": "XLU", "qty": 104, "market_value": 4_545, "idea": "Other"},
                         {"symbol": "XLV", "qty": 20, "market_value": 3_691, "idea": "Other"},
                         {"symbol": "XLP", "qty": 29, "market_value": 2_636, "idea": "Other"},
                         {"symbol": "XOM", "qty": 49, "market_value": 8_834, "idea": "Other"},
                         {"symbol": "AAPL", "qty": -12, "market_value": -3_952, "idea": "Other"}],
                     size_pct=10.0, own_title="Chips", otherwise="CASH",
                     legs=["TSM", "INTC", "TXN"])
    rows = {r["ticker"]: r for r in out["rows"]}
    assert set(rows) == {"TSM", "INTC", "TXN", "XLV", "XLP", "XLU"}  # no XOM, no AAPL
    assert abs(out["buys"] - 2_030.67) < 0.02       # the three chips + the XLP top-up
    assert abs(out["sells"] - 2_902.67) < 0.02      # trims of the play's own core only
    assert out["verdict"] == "affordable"           # cash at hand covers the buys
    assert rows["XLP"]["coverage_pct"] == 98.9
    assert rows["XLU"]["coverage_pct"] == 170.4
    assert rows["TSM"]["coverage_pct"] == 0.0
    assert abs(out["already_in_place_usd"] - 7_969.33) < 0.02
    assert out["in_place_pct"] == 79.7


def test_not_affordable_names_the_shortfall():
    out = play_check(weights={"GLD": 1.0}, **{**BASE, "cash": 0.0})
    assert out["verdict"] == "not_affordable" and out["shortfall"] == 10_000
    assert "$10,000 short on cash" in out["verdict_line"]


def test_cap_breach_is_flagged():
    out = play_check(weights={"XLE": 1.0}, **{**BASE, "size_pct": 30.0, "legs": ["XLE"]})
    assert out["cap_breaches"] == [{"ticker": "XLE", "pct": 30.0, "cap": 25}]
    assert "XLE would be 30% of the account" in out["verdict_line"]


def test_out_state_and_short_leg():
    out = play_check(weights={"GLD": 1.0}, **{**BASE, "legs": ["ASML"]})
    assert out["state"] == "out"  # weights sit in the otherwise asset, none in the leg
    short = play_check(weights={"XLE": -1.0}, **{**BASE, "legs": ["XLE"]})
    row = short["rows"][0]
    assert row["target_value"] == -10_000 and row["target_shares"] == -100 and short["state"] == "in"


def test_overlap_only_counts_other_ideas():
    out = play_check(weights={"GLD": 0.5, "ASML": 0.5}, **{**BASE, "positions": [
        {"symbol": "ASML", "qty": 4, "market_value": 2_000, "idea": "Other idea"},
        {"symbol": "GLD", "qty": 2, "market_value": 500, "idea": "Mine"},
        {"symbol": "GLD", "qty": 1, "market_value": 250, "idea": "No idea yet (manual)"}]})
    rows = {r["ticker"]: r for r in out["rows"]}
    assert rows["ASML"]["overlap_ideas"] == ["Other idea"]
    assert rows["GLD"]["overlap_ideas"] == [] and rows["GLD"]["held_value"] == 750


SPEC = {"title": "Gold when rates rise", "hold": ["GLD"], "otherwise": "SPY", "claim": "beats_benchmark_when",
        "when": {"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25}}
RESULT = {"verdict": "PASS", "headline": "Did what it claims.", "data_end": "2026-10-29"}
BOOK = {"state": "live", "as_of": "2026-11-02T15:00:00+00:00", "scoreboard": {"equity": 100_000.0},
        "positions": [{"symbol": "Cash", "qty": None, "market_value": 60_000.0, "idea": None},
                      {"symbol": "SPY", "qty": 10, "market_value": 5_000.0, "idea": "No idea yet (manual)"}]}


@pytest.fixture
def api(monkeypatch):
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    frame = pd.DataFrame({"GLD": [240.0, 250.0], "SPY": [490.0, 500.0]},
                         index=pd.date_range("2026-10-30", periods=2, freq="B"))
    monkeypatch.setattr(main, "workshop_closes", lambda tickers, start: frame)
    monkeypatch.setattr(main, "with_rule_bars", lambda spec, prices, start, bars_fn=None: prices)
    monkeypatch.setattr(main, "rule_series", lambda spec, start, fred=None, analyst_fn=None: {})
    monkeypatch.setattr(main, "workshop_div_yields", lambda spec, prices: {})
    monkeypatch.setattr(main, "target_and_reason", lambda spec, closes, fred, div=None: ({"GLD": 1.0}, ""))
    monkeypatch.setattr(main, "run_test", lambda spec, closes, fred, **k: RESULT)
    monkeypatch.setattr(portfolio_service, "portfolio", lambda supa, now=None, book_name=None: BOOK)
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def _idea_with_run(c):
    idea = c.post("/api/workshop/ideas", json={"title": "Gold", "plain_words": "x"}).json()
    run = c.post(f"/api/workshop/ideas/{idea['id']}/runs", json={"spec": SPEC}).json()
    return idea, run


def test_workshop_play_check(api):
    c, _ = api
    idea, _ = _idea_with_run(c)
    out = c.get(f"/api/workshop/ideas/{idea['id']}/play-check", params={"size_pct": 10}).json()
    assert out["available"] is True and out["state"] == "in" and out["verdict"] == "affordable"
    rows = {r["ticker"]: r for r in out["rows"]}
    assert rows["GLD"]["target_value"] == 10_000 and rows["GLD"]["target_shares"] == 40
    # SPY is this idea's otherwise asset with the rule IN: it is not one of the
    # play's positions today, so the held SPY is not a row and not a sell.
    assert "SPY" not in rows and out["sells"] == 0
    assert out["cash"] == 60_000 and out["as_of"] == BOOK["as_of"]
    assert out["book"] == "main" and out["book_label"] == "Main book"
    big = c.get(f"/api/workshop/ideas/{idea['id']}/play-check", params={"book": "big"}).json()
    assert big["book"] == "big" and big["book_label"] == "$1M book"
    assert c.get(f"/api/workshop/ideas/{idea['id']}/play-check", params={"book": "nope"}).status_code == 422


def test_public_play_check_needs_published_and_saved(api):
    c, _ = api
    idea, run = _idea_with_run(c)
    assert c.get(f"/api/ideas/{idea['id']}/play-check").status_code == 404  # not published
    c.post(f"/api/workshop/ideas/{idea['id']}/publish")
    assert c.get(f"/api/ideas/{idea['id']}/play-check").status_code == 409  # run not saved yet
    c.post(f"/api/workshop/ideas/{idea['id']}/runs/{run['id']}/save")
    out = c.get(f"/api/ideas/{idea['id']}/play-check").json()
    assert out["available"] is True and out["verdict"] == "affordable"


def test_play_check_without_a_book(api, monkeypatch):
    c, _ = api
    idea, _ = _idea_with_run(c)
    monkeypatch.setattr(portfolio_service, "portfolio", lambda supa, **k: {"state": "not_connected", "positions": []})
    out = c.get(f"/api/workshop/ideas/{idea['id']}/play-check").json()
    assert out["available"] is False and "No paper account" in out["note"]
