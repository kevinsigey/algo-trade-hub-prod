"""Loop Round 3: the display limit is not a cohort count, and builder runs
never write a screen's record.

Round 2's live verification found: (1) the builder's "show top" limit (25)
rides into the composed spec of a loaded saved screen, and the runner
applies it BEFORE counting -- a Buffett card run reported "25 survivors ·
24 issuers" for a 40-name cohort, and recorded runs built their survivor
list from the truncated rows; (2) ad-hoc builder runs must never write a
saved screen's last_run or membership baseline -- only the saved-screen
run path (POST /screens/{id}/run, the scheduled refresh) may; (3) the run
summary's provenance must agree per field with the field layer: ROE is a
yfinance.info field, eps_growth_5y is the EDGAR one.
"""
import copy
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tradehub.screening import runner, store as screen_store
from tradehub.screening.functions import REGISTRY
from tradehub.screening.runner import RunResult


def _store():
    return SimpleNamespace(asof={}, missing=[])


def _field(values):
    def fn(store, tickers, **params):
        return pd.Series({t: values.get(t) for t in tickers}, dtype=float)
    return {"fn": fn, "kind": "field", "returns": "float", "params": {},
            "source": "test", "category": "test", "doc": "fake"}


@pytest.fixture
def names_sidecar(tmp_path, monkeypatch):
    cache = tmp_path / "screening"
    cache.mkdir(exist_ok=True)
    (cache / "universe_names.json").write_text(json.dumps({"names": {
        "GOOG": "Alphabet Inc. - Class C Capital Stock",
        "GOOGL": "Alphabet Inc. - Class A Common Stock",
    }}))
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(cache))
    return cache


# ── FIX 1: limit truncates the display, never the counts ────────────────────

def test_limit_truncates_display_never_counts(monkeypatch):
    vals = {"AAA": 50.0, "BBB": 40.0, "CCC": 30.0, "DDD": 20.0, "EEE": 10.0}
    monkeypatch.setitem(REGISTRY, "roe", _field(vals))
    spec = {"name": "limited", "universe": {"type": "list", "tickers": list(vals)},
            "filters": [{"fn": "roe", "op": "gt", "value": 5}],
            "sort": {"by": "roe", "ascending": False}, "limit": 2}
    out = runner.run_spec(spec, store=_store())
    # The table the page draws is the top 2...
    assert list(out.table["ticker"]) == ["AAA", "BBB"]
    # ...but every count in the footer is the TRUE filter count.
    assert out.footer["survivors"] == 5
    assert out.footer["survivor_issuers"] == 5
    assert out.footer["displayed"] == 2
    assert out.footer["display_limit"] == 2
    # The full cohort list rides in the footer for the record path.
    assert out.footer["survivor_tickers"] == ["AAA", "BBB", "CCC", "DDD", "EEE"]


def test_issuer_count_uses_the_full_cohort_not_the_display(names_sidecar, monkeypatch):
    # GOOGL sits BELOW the display cut; its issuer must still be counted
    # (and GOOG+GOOGL must count once) in the true totals.
    vals = {"AAA": 50.0, "BBB": 40.0, "GOOG": 30.0, "GOOGL": 20.0}
    monkeypatch.setitem(REGISTRY, "roe", _field(vals))
    spec = {"name": "limited_dual", "universe": {"type": "list", "tickers": list(vals)},
            "filters": [{"fn": "roe", "op": "gt", "value": 5}],
            "sort": {"by": "roe", "ascending": False}, "limit": 2}
    out = runner.run_spec(spec, store=_store())
    assert list(out.table["ticker"]) == ["AAA", "BBB"]
    assert out.footer["survivors"] == 4
    assert out.footer["survivor_issuers"] == 3


def test_no_limit_means_no_display_fields(monkeypatch):
    monkeypatch.setitem(REGISTRY, "roe", _field({"AAA": 50.0}))
    spec = {"name": "plain", "universe": {"type": "list", "tickers": ["AAA"]},
            "filters": [{"fn": "roe", "op": "gt", "value": 5}]}
    out = runner.run_spec(spec, store=_store())
    assert out.footer["survivors"] == 1
    assert out.footer["displayed"] == 1
    assert "display_limit" not in out.footer
    assert out.footer["survivor_tickers"] == ["AAA"]


# ── FIX 2: only the saved-screen run path writes the record ─────────────────

class FakeQuery:
    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self.col, self.desc = col, desc
        return self

    def insert(self, row):
        rows = self.store.setdefault(self.table, [])
        row = {**row, "id": max([r.get("id", 0) for r in rows], default=0) + 1}
        rows.append(row)
        self.inserted = [row]
        return self

    def update(self, values):
        self.updates = values
        return self

    def execute(self):
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(c) == v for c, v in self.filters)]
        if getattr(self, "inserted", None) is not None and hasattr(self, "inserted"):
            return type("R", (), {"data": self.inserted})()
        if getattr(self, "updates", None):
            for r in rows:
                r.update(self.updates)
        if getattr(self, "col", None):
            rows.sort(key=lambda r: r.get(self.col) or 0, reverse=getattr(self, "desc", False))
        return type("R", (), {"data": rows})()


class FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return FakeQuery(self.store, name)


BUFFETT_SPEC = {"name": "buffett_quality_classic",
                "universe": {"type": "list", "tickers": ["AAA", "BBB", "CCC"]},
                "filters": [{"fn": "roe", "op": "gt", "value": 15}],
                "membership_diff": True}
TRUE_RUN = {"footer": {"run_at": "2026-11-10T05:43:10+00:00", "survivors": 3},
            "columns": ["ticker", "roe"], "survivors": ["AAA", "BBB", "CCC"]}


@pytest.fixture
def client(monkeypatch):
    fake = FakeSupabase()
    fake.store["screens"] = [{
        "id": 6, "name": "Buffett quality (classic)", "spec": BUFFETT_SPEC,
        "last_run": copy.deepcopy(TRUE_RUN),
        "membership": {"tracked_since": "2026-11-10", "as_of": "2026-11-10",
                       "members": {"AAA": "2026-11-10", "BBB": "2026-11-10",
                                   "CCC": "2026-11-10"}},
        "membership_events": None, "updated_at": "2026-11-10T05:43:10+00:00"}]
    main.app.dependency_overrides[main.admin.require_admin] = lambda: {"email": "k@example.com"}
    main.app.dependency_overrides[get_supabase] = lambda: fake
    yield TestClient(main.app), fake
    main.app.dependency_overrides.pop(main.admin.require_admin, None)
    main.app.dependency_overrides.pop(get_supabase, None)


def _canned_result(tickers):
    table = pd.DataFrame({"ticker": tickers, "roe": [99.0] * len(tickers)})
    footer = {"spec_name": "adhoc", "run_at": "2026-11-10T05:47:00+00:00",
              "survivors": len(tickers), "survivor_tickers": list(tickers)}
    return RunResult(table=table, footer=footer, spec={})


def test_adhoc_builder_run_never_writes_a_screen_record(client, monkeypatch):
    c, fake = client
    before = copy.deepcopy(fake.store["screens"][0])
    # The ad-hoc run returns a DIFFERENT (truncated) cohort than the record.
    monkeypatch.setattr("tradehub.screening.run_spec",
                        lambda spec, store=None: _canned_result(["AAA"]))
    r = c.post("/api/screening/run", json={"spec": BUFFETT_SPEC})
    assert r.status_code == 200, r.text
    assert r.json()["footer"]["survivors"] == 1
    # The saved screen's record is byte-identical: last_run, membership,
    # events and the row stamp all untouched by the builder run.
    assert fake.store["screens"][0] == before


def test_saved_run_records_the_full_cohort_of_a_limited_spec(client, monkeypatch):
    c, fake = client
    # A saved spec carrying a display limit: the endpoint's recorded
    # survivor list (and the membership baseline diffed from it) must be
    # the FULL cohort from the footer, not the truncated payload rows.
    table = pd.DataFrame({"ticker": ["AAA", "BBB"], "roe": [30.0, 20.0]})
    footer = {"spec_name": "buffett_quality_classic",
              "run_at": "2026-11-11T05:43:10+00:00", "survivors": 3,
              "survivor_tickers": ["AAA", "BBB", "CCC"]}
    monkeypatch.setattr("tradehub.screening.run_spec",
                        lambda spec, store=None: RunResult(table=table, footer=footer, spec=spec))
    r = c.post("/api/screening/screens/6/run", json={})
    assert r.status_code == 200, r.text
    row = fake.store["screens"][0]
    assert row["last_run"]["survivors"] == ["AAA", "BBB", "CCC"]
    # Membership still holds all three members; nobody phantom-exited.
    assert sorted(row["membership"]["members"]) == ["AAA", "BBB", "CCC"]
    assert not row.get("membership_events")


# ── FIX 3: provenance agrees per field, from the field layer ────────────────

def test_field_layer_provenance_roe_is_yfinance_eps5y_is_edgar():
    assert REGISTRY["roe"]["source"] == "yfinance.info"
    assert REGISTRY["eps_growth_5y"]["source"] == "SEC EDGAR company facts"
    from tradehub.screening.cards import cards_payload
    cards = {c["fn"]: c for c in cards_payload()}
    assert cards["roe"]["source"] == "yfinance.info"
    assert cards["eps_growth_5y"]["source"] == "SEC EDGAR company facts"


def test_run_footer_provenance_matches_the_registry(monkeypatch):
    monkeypatch.setitem(REGISTRY, "roe", {**REGISTRY["roe"],
                                          "fn": _field({"AAA": 30.0})["fn"]})
    monkeypatch.setitem(REGISTRY, "eps_growth_5y",
                        {**REGISTRY["eps_growth_5y"],
                         "fn": _field({"AAA": 20.0})["fn"]})
    spec = {"name": "buffett_like", "universe": {"type": "list", "tickers": ["AAA"]},
            "filters": [{"fn": "roe", "op": "gt", "value": 15},
                        {"fn": "eps_growth_5y", "op": "gt", "value": 10}]}
    out = runner.run_spec(spec, store=_store())
    cols = out.footer["columns"]
    assert cols["roe"]["source"] == "yfinance.info"
    assert cols["eps_growth_5y"]["source"] == "SEC EDGAR company facts"


def test_last_run_view_carries_per_field_sources():
    last_run = {"footer": {"run_at": "2026-11-10T05:43:10+00:00", "survivors": 40,
                           "survivor_issuers": 39, "data_as_of": "2026-11-10",
                           "columns": {
                               "roe": {"fn": "roe", "source": "yfinance.info"},
                               "eps_growth_5y": {"fn": "eps_growth_5y",
                                                 "source": "SEC EDGAR company facts"}}},
                "columns": ["ticker", "roe", "eps_growth_5y"],
                "survivors": ["AAA"]}
    view = screen_store._last_run_view(last_run)
    assert view["column_sources"] == {"roe": "yfinance.info",
                                      "eps_growth_5y": "SEC EDGAR company facts"}
    # The distinct-sources list stays for older readers.
    assert view["sources"] == ["SEC EDGAR company facts", "yfinance.info"]
