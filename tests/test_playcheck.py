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


def test_sells_fund_the_buys():
    out = play_check(weights={"GLD": 1.0}, **{**BASE, "cash": 2_000.0, "positions": [
        {"symbol": "SPY", "qty": 16, "market_value": 8_000, "idea": "No idea yet (manual)"}]})
    assert out["buys"] == 10_000 and out["sells"] == 8_000
    assert out["verdict"] == "affordable_after_sells" and out["shortfall"] == 0


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
    monkeypatch.setattr(portfolio_service, "portfolio", lambda supa: BOOK)
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
    assert rows["SPY"]["delta_value"] == -5_000  # the held SPY is sold back to cash in the diff
    assert out["cash"] == 60_000 and out["as_of"] == BOOK["as_of"]


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
    monkeypatch.setattr(portfolio_service, "portfolio", lambda supa: {"state": "not_connected", "positions": []})
    out = c.get(f"/api/workshop/ideas/{idea['id']}/play-check").json()
    assert out["available"] is False and "No paper account" in out["note"]
