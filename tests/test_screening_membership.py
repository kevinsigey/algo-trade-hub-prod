"""Classic-screens addenda (Kevin, 2026-11-09): the wider-universe run option
(index_union + a spec's own max_universe) and entrance/exit diffing
(membership_diff) for the adopted watchlist screens.

Diffing contract: a refresh diffs survivors vs the persisted membership —
entrances and exits are dated events; the FIRST diffed run baselines
silently (members since the baseline date, no entrance storm); a no-change
refresh produces no events. The universe option is a spec-level choice;
specs without it (screens 1-4) keep the standard 300 cap exactly.
"""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from tradehub.screening import membership, runner, store as screen_store
from tradehub.screening.functions import REGISTRY
from tradehub.screening.spec import SpecError, validate_spec
from tradehub.screening.universes import resolve_universe

D0, D1, D2 = "2026-11-03", "2026-11-10", "2026-11-11"


# --------------------------------------------------------------------------
# diff_membership: the pure transition logic
# --------------------------------------------------------------------------

def test_baseline_run_is_silent():
    state, events = membership.diff_membership(None, ["BBB", "AAA"], D0)
    assert events == []
    assert state["tracked_since"] == D0 and state["as_of"] == D0
    assert state["members"] == {"AAA": D0, "BBB": D0}


def test_baseline_from_an_empty_prior_state_is_still_silent():
    state, events = membership.diff_membership({}, ["AAA"], D0)
    assert events == [] and state["members"] == {"AAA": D0}


def test_entrance_is_a_dated_event_and_keeps_existing_since():
    prior, _ = membership.diff_membership(None, ["AAA"], D0)
    state, events = membership.diff_membership(prior, ["AAA", "BBB"], D1)
    assert events == [{"ticker": "BBB", "kind": "entered", "date": D1}]
    assert state["members"] == {"AAA": D0, "BBB": D1}
    assert state["tracked_since"] == D0 and state["as_of"] == D1


def test_exit_event_carries_the_member_since_date():
    prior, _ = membership.diff_membership(None, ["AAA", "BBB"], D0)
    state, events = membership.diff_membership(prior, ["AAA"], D1)
    assert events == [{"ticker": "BBB", "kind": "exited", "date": D1, "since": D0}]
    assert state["members"] == {"AAA": D0}


def test_reentrance_gets_a_fresh_since_and_a_new_event():
    s0, _ = membership.diff_membership(None, ["AAA"], D0)
    s1, _ = membership.diff_membership(s0, [], D1)
    assert s1["members"] == {}
    s2, events = membership.diff_membership(s1, ["AAA"], D2)
    assert events == [{"ticker": "AAA", "kind": "entered", "date": D2}]
    assert s2["members"] == {"AAA": D2}


def test_no_change_refresh_produces_no_events():
    prior, _ = membership.diff_membership(None, ["AAA", "BBB"], D0)
    state, events = membership.diff_membership(prior, ["BBB", "AAA"], D1)
    assert events == []
    assert state["members"] == {"AAA": D0, "BBB": D0}


def test_survivors_are_normalized_before_diffing():
    state, events = membership.diff_membership(None, ["aaa", "AAA", " bbb "], D0)
    assert events == []
    assert state["members"] == {"AAA": D0, "BBB": D0}


def test_event_log_is_bounded():
    old = [{"ticker": f"T{i}", "kind": "entered", "date": D0} for i in range(120)]
    out = membership.append_events(old, [{"ticker": "NEW", "kind": "entered", "date": D1}])
    assert len(out) == membership.EVENT_CAP
    assert out[-1]["ticker"] == "NEW"


# --------------------------------------------------------------------------
# record_run: the diff rides the run recording, classic screens only
# --------------------------------------------------------------------------

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
            return SimpleNamespace(data=self.inserted)
        if getattr(self, "updates", None):
            for r in rows:
                r.update(self.updates)
        if getattr(self, "col", None):
            rows.sort(key=lambda r: r.get(self.col) or 0, reverse=getattr(self, "desc", False))
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return FakeQuery(self.store, name)


def _run(survivors, run_at):
    return {"footer": {"run_at": run_at, "survivors": len(survivors)},
            "columns": ["ticker"], "survivors": survivors}


CLASSIC = {"name": "Graham value (classic)", "membership_diff": True,
           "universe": {"type": "list", "tickers": ["AAA", "BBB", "CCC"]},
           "filters": [{"fn": "pe_ratio", "op": "lt", "value": 7}]}
PLAIN = {"name": "plain", "universe": {"type": "list", "tickers": ["AAA"]},
         "filters": [{"fn": "pe_ratio", "op": "lt", "value": 7}]}


def test_record_run_diffs_only_flagged_screens():
    fake = FakeSupabase()
    classic = screen_store.create_screen(fake, "classic", CLASSIC)
    plain = screen_store.create_screen(fake, "plain", PLAIN)

    screen_store.record_run(fake, classic["id"], _run(["AAA", "BBB"], "2026-11-10T04:00:00Z"))
    row = screen_store.get_screen(fake, classic["id"])
    assert row["membership"]["members"] == {"AAA": "2026-11-10", "BBB": "2026-11-10"}
    assert not row.get("membership_events")  # baseline: silent

    screen_store.record_run(fake, classic["id"], _run(["BBB", "CCC"], "2026-11-11T04:00:00Z"))
    row = screen_store.get_screen(fake, classic["id"])
    kinds = [(e["ticker"], e["kind"]) for e in row["membership_events"]]
    assert kinds == [("CCC", "entered"), ("AAA", "exited")]
    assert row["membership_events"][1]["since"] == "2026-11-10"
    assert row["membership"]["members"] == {"BBB": "2026-11-10", "CCC": "2026-11-11"}

    screen_store.record_run(fake, plain["id"], _run(["AAA"], "2026-11-10T04:00:00Z"))
    prow = screen_store.get_screen(fake, plain["id"])
    assert "membership" not in prow and "membership_events" not in prow


def test_list_screens_passes_membership_through_when_present():
    fake = FakeSupabase()
    classic = screen_store.create_screen(fake, "classic", CLASSIC)
    screen_store.create_screen(fake, "plain", PLAIN)
    screen_store.record_run(fake, classic["id"], _run(["AAA"], "2026-11-10T04:00:00Z"))
    listed = {r["name"]: r for r in screen_store.list_screens(fake)}
    assert listed["classic"]["membership"]["members"] == {"AAA": "2026-11-10"}
    assert "membership" not in listed["plain"]


# --------------------------------------------------------------------------
# the wider-universe run option
# --------------------------------------------------------------------------

@pytest.fixture
def fake_fields(monkeypatch):
    def num_field(values):
        def fn(store, tickers, **params):
            return pd.Series({t: values.get(t) for t in tickers}, dtype=float)
        return fn

    saved = dict(REGISTRY)
    REGISTRY["fake_alpha"] = {"fn": num_field({"AAA": 10.0, "BBB": 4.0, "CCC": 9.0}),
                              "kind": "field", "returns": "float", "params": {},
                              "source": "test", "category": "test", "doc": "fake"}
    yield
    REGISTRY.clear()
    REGISTRY.update(saved)


@pytest.fixture
def refreshed(tmp_path, monkeypatch):
    (tmp_path / "universe_sp500.json").write_text(json.dumps(
        {"tickers": ["AAA", "BBB"], "as_of": "2026-11-09T11:17:03+00:00"}))
    (tmp_path / "universe_nasdaq100.json").write_text(json.dumps(
        {"tickers": ["BBB", "CCC"], "as_of": "2026-11-09T11:17:03+00:00"}))
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(tmp_path))
    return tmp_path


def test_index_union_resolves_the_union(refreshed):
    store = SimpleNamespace()
    out = resolve_universe(store, {"type": "index_union", "indexes": ["sp500", "nasdaq100"]})
    assert out == ["AAA", "BBB", "CCC"]


def test_index_union_names_an_unknown_index(refreshed):
    with pytest.raises(ValueError, match="nope"):
        resolve_universe(SimpleNamespace(),
                         {"type": "index_union", "indexes": ["sp500", "nope"]})


def test_spec_validation_accepts_the_run_option_and_diff_flag():
    spec = {"name": "classic", "universe": {"type": "index_union",
                                            "indexes": ["sp500", "nasdaq100"]},
            "max_universe": 600, "membership_diff": True,
            "filters": [{"fn": "pe_ratio", "op": "lt", "value": 7}]}
    assert validate_spec(spec) is spec


def test_spec_validation_rejects_a_bad_max_universe():
    base = {"name": "x", "universe": {"type": "list", "tickers": ["AAA"]}}
    with pytest.raises(SpecError):
        validate_spec({**base, "max_universe": 0})
    with pytest.raises(SpecError):
        validate_spec({**base, "max_universe": "600"})


def test_max_universe_lifts_the_cap_for_that_spec_only(fake_fields, monkeypatch):
    monkeypatch.setattr(runner, "MAX_UNIVERSE", 2)
    base = {"name": "t", "universe": {"type": "list", "tickers": ["AAA", "BBB", "CCC"]},
            "filters": [{"fn": "fake_alpha", "op": "gt", "value": 3}]}
    store = SimpleNamespace(asof={}, missing=[])
    capped = runner.run_spec(base, store=store)
    assert capped.footer["universe_size"] == 2
    assert capped.footer["universe_capped"] == {"cap": 2, "universe_size_full": 3}
    wide = runner.run_spec({**base, "max_universe": 3}, store=store)
    assert wide.footer["universe_size"] == 3
    assert "universe_capped" not in wide.footer


def test_list_screens_passes_near_misses_through():
    fake = FakeSupabase()
    sc = screen_store.create_screen(fake, "classic", CLASSIC)
    run = _run(["AAA"], "2026-11-10T04:00:00Z")
    run["footer"]["near_misses"] = [{"ticker": "LEN", "fn": "pe_ratio",
                                     "column": "pe_ratio", "value": 7.4,
                                     "op": "lt", "threshold": 7}]
    run["footer"]["near_miss_count"] = 1
    screen_store.record_run(fake, sc["id"], run)
    listed = {r["name"]: r for r in screen_store.list_screens(fake)}
    assert listed["classic"]["last_run"]["near_misses"][0]["ticker"] == "LEN"
    assert listed["classic"]["last_run"]["near_miss_count"] == 1


# --------------------------------------------------------------------------
# near misses: exactly one filter failed, on a real value
# --------------------------------------------------------------------------

@pytest.fixture
def nm_fields(monkeypatch):
    def num_field(values):
        def fn(store, tickers, **params):
            return pd.Series({t: values.get(t) for t in tickers}, dtype=float)
        return fn

    saved = dict(REGISTRY)
    REGISTRY["fake_alpha"] = {"fn": num_field({"PASS": 10.0, "NEAR": 6.0, "TWO": 1.0,
                                               "MISS": 9.0}),
                              "kind": "field", "returns": "float", "params": {},
                              "source": "test", "category": "test", "doc": "fake"}
    REGISTRY["fake_beta"] = {"fn": num_field({"PASS": 5.0, "NEAR": 5.0, "TWO": 0.5,
                                              "MISS": None}),
                             "kind": "field", "returns": "float", "params": {},
                             "source": "test", "category": "test", "doc": "fake"}
    yield
    REGISTRY.clear()
    REGISTRY.update(saved)


def test_near_miss_is_exactly_one_real_value_failure(nm_fields):
    spec = {"name": "t",
            "universe": {"type": "list", "tickers": ["PASS", "NEAR", "TWO", "MISS"]},
            "filters": [{"fn": "fake_alpha", "op": "gt", "value": 8},
                        {"fn": "fake_beta", "op": "gt", "value": 2}]}
    result = runner.run_spec(spec, store=SimpleNamespace(asof={}, missing=[]))
    # NEAR fails only alpha, with a real value -> a near miss. TWO fails both
    # -> not. MISS fails only beta, on a missing (NaN) value -> not a near
    # miss: missing is not close, it belongs to the missing-data record.
    assert result.footer["near_misses"] == [
        {"ticker": "NEAR", "fn": "fake_alpha", "column": "fake_alpha",
         "value": 6.0, "op": "gt", "threshold": 8}]
    assert result.footer["near_miss_count"] == 1
    assert list(result.table["ticker"]) == ["PASS"]


def test_the_shipped_classic_specs_still_validate_with_the_option():
    """The exact filter sets of screens 5/6/7 (filters unchanged) plus the
    addenda keys must pass validation — the addenda change the run, never
    the filters."""
    filters = {
        5: [("pe_ratio", "lt", 7), ("price_to_book", "lt", 1.5),
            ("debt_to_equity", "lt", 0.5), ("current_ratio", "gt", 1.5)],
        6: [("roe", "gt", 15), ("net_margin", "gt", 10),
            ("eps_growth_5y", "gt", 10), ("debt_to_equity", "lt", 0.5)],
        7: [("eps_growth_yoy", "gt", 20), ("eps_growth_qoq", "gt", 20),
            ("revenue_growth_qoq", "gt", 20), ("roe", "gt", 15)],
    }
    for sid, legs in filters.items():
        spec = {"name": f"classic {sid}",
                "universe": {"type": "index_union", "indexes": ["sp500", "nasdaq100"]},
                "max_universe": 600, "membership_diff": True,
                "filters": [{"fn": fn, "op": op, "value": v} for fn, op, v in legs]}
        assert validate_spec(spec) is spec
