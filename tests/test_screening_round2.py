"""Loop Round 2: determinism + issuer-keyed membership + crossings freshness.

Round 1 shipped the union universe and the max_universe override, but the
thesis side's live verification found: (1) a capped run's cohort depends on
the order tickers arrive in -- 40 survivors recorded vs 23 on a re-run of
the same screen; (2) dual-class names (GOOG/GOOGL) counted as two issuers
and diffed as two members; (3) the crossings header can cite an older
snapshot than the page serves. These tests pin the fixes.
"""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from tradehub.screening import membership, runner
from tradehub.screening import universes
from tradehub.screening.functions import REGISTRY
from tradehub.valuation import band_crossing as bc
from workshop_fake import DB


def _store():
    return SimpleNamespace(asof={}, missing=[])


def _field(values):
    def fn(store, tickers, **params):
        return pd.Series({t: values.get(t) for t in tickers}, dtype=float)
    return {"fn": fn, "kind": "field", "returns": "float", "params": {},
            "source": "test", "category": "test", "doc": "fake"}


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def refreshed(tmp_path, monkeypatch):
    cache = tmp_path / "screening"
    cache.mkdir(exist_ok=True)
    for name, tickers in {"sp500": ["AAA", "BBB"], "nasdaq100": ["BBB", "CCC"]}.items():
        (cache / f"universe_{name}.json").write_text(json.dumps(
            {"as_of": "2026-11-09T00:00:00Z", "source": "wikipedia", "tickers": tickers}))
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(cache))
    return cache


@pytest.fixture
def roe_field(monkeypatch):
    monkeypatch.setitem(REGISTRY, "roe",
                        _field({"AAA": 30.0, "BBB": 5.0, "CCC": 25.0}))


def _union_spec():
    return {"name": "union_screen",
            "universe": {"type": "index_union", "indexes": ["sp500", "nasdaq100"]},
            "filters": [{"fn": "roe", "op": "gt", "value": 10}]}


# ── FIX 2: the union is never capped; capped subsets are deterministic ──────

def test_union_universe_is_never_capped(refreshed, roe_field, monkeypatch):
    # Even with the process default cap BELOW the union size and no
    # max_universe in the spec, a union-rooted screen enriches every name.
    monkeypatch.setattr(runner, "MAX_UNIVERSE", 2)
    out = runner.run_spec(_union_spec(), store=_store())
    assert out.footer["universe_size"] == 3
    assert "universe_capped" not in out.footer
    assert "no enrichment cap" in out.footer["universe_selection"]


def test_common_equity_wrapped_union_is_never_capped(refreshed, roe_field, monkeypatch):
    monkeypatch.setattr(runner, "MAX_UNIVERSE", 2)
    spec = _union_spec()
    spec["universe"] = {"type": "common_equity", "base": spec["universe"]}
    out = runner.run_spec(spec, store=_store())
    assert out.footer["universe_size"] == 3
    assert "universe_capped" not in out.footer


def test_capped_subset_is_the_sorted_set_not_the_arrival_order(refreshed, roe_field, monkeypatch):
    # The refreshed file order is the arrival order; rewriting it reversed
    # must not change who gets enriched. Pre-fix, the cap slices the raw
    # order, so the cohort flips with the file.
    monkeypatch.setattr(runner, "MAX_UNIVERSE", 2)
    spec = {"name": "capped", "universe": {"type": "index", "index": "sp500"},
            "filters": [{"fn": "roe", "op": "gt", "value": 10}]}
    (refreshed / "universe_sp500.json").write_text(json.dumps(
        {"as_of": "x", "source": "wikipedia", "tickers": ["CCC", "AAA", "BBB"]}))
    first = runner.run_spec(spec, store=_store())
    (refreshed / "universe_sp500.json").write_text(json.dumps(
        {"as_of": "x", "source": "wikipedia", "tickers": ["BBB", "CCC", "AAA"]}))
    second = runner.run_spec(spec, store=_store())
    assert list(first.table["ticker"]) == list(second.table["ticker"])
    assert "sorted ticker order" in first.footer["universe_selection"]
    assert first.footer["universe_capped"] == {"cap": 2, "universe_size_full": 3}


def test_run_twice_on_unchanged_data_is_reproducible(refreshed, roe_field):
    spec = _union_spec()
    one = runner.run_spec(spec, store=_store())
    two = runner.run_spec(spec, store=_store())
    assert list(one.table["ticker"]) == list(two.table["ticker"])
    assert one.footer["survivors"] == two.footer["survivors"]


# ── FIX 5: dual-class names are one issuer ──────────────────────────────────

@pytest.fixture
def names_sidecar(tmp_path, monkeypatch):
    cache = tmp_path / "screening"
    cache.mkdir(exist_ok=True)
    (cache / "universe_names.json").write_text(json.dumps({"names": {
        "GOOG": "Alphabet Inc. - Class C Capital Stock",
        "GOOGL": "Alphabet Inc. - Class A Common Stock",
        "BRK-A": "Berkshire Hathaway Inc. - Class A Common Stock",
        "BRK-B": "Berkshire Hathaway Inc. - Class B Common Stock",
        "ACGL": "Arch Capital Group Ltd. - Common Shares",
        "ACGLN": "Arch Capital Group Ltd. - 5.45% Non-Cumulative Preferred Shares",
    }}))
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(cache))
    return cache


def test_issuer_key_merges_share_classes_only(names_sidecar):
    assert universes.issuer_key("GOOG") == universes.issuer_key("GOOGL")
    assert universes.issuer_key("BRK-A") == universes.issuer_key("BRK-B")
    # A preferred line is a different security, not a share class of the
    # common: it must not collapse into the common's key.
    assert universes.issuer_key("ACGL") != universes.issuer_key("ACGLN")
    # No recorded name: the ticker is its own issuer, never merged blindly.
    assert universes.issuer_key("ZZZZ") == "ZZZZ"


def test_membership_diff_keys_share_classes_by_issuer(names_sidecar):
    key = universes.issuer_key
    # GOOGL joining while GOOG is already a member is not an entrance, and
    # it inherits the issuer's membership date.
    state, events = membership.diff_membership(
        {"members": {"GOOG": "2026-11-10"}}, ["GOOG", "GOOGL"], "2026-11-11", key=key)
    assert events == []
    assert state["members"]["GOOGL"] == "2026-11-10"
    # GOOG leaving while GOOGL stays is not an exit.
    state, events = membership.diff_membership(
        state, ["GOOGL"], "2026-11-12", key=key)
    assert events == []
    # A genuinely new issuer still fires, carrying both class tickers.
    state, events = membership.diff_membership(
        state, ["GOOGL", "BRK-A", "BRK-B"], "2026-11-13", key=key)
    assert [e["kind"] for e in events] == ["entered"]
    assert events[0]["tickers"] == ["BRK-A", "BRK-B"]


def test_footer_counts_issuers_beside_rows(names_sidecar, monkeypatch):
    monkeypatch.setitem(REGISTRY, "roe", _field({"GOOG": 30.0, "GOOGL": 28.0}))
    spec = {"name": "dual", "universe": {"type": "list", "tickers": ["GOOG", "GOOGL"]},
            "filters": [{"fn": "roe", "op": "gt", "value": 10}]}
    out = runner.run_spec(spec, store=_store())
    assert out.footer["survivors"] == 2
    assert out.footer["survivor_issuers"] == 1


# ── FIX 6: the Graham P/E floor leg (spec-level) ────────────────────────────

def test_graham_floor_leg_excludes_sub_half_pe(monkeypatch):
    pe = {"DUST": 0.3, "REAL": 3.0, "EDGE": 0.5}
    monkeypatch.setitem(REGISTRY, "pe_ratio", _field(pe))
    for fn_name, val in {"price_to_book": 1.0, "debt_to_equity": 0.2,
                         "current_ratio": 2.0}.items():
        monkeypatch.setitem(REGISTRY, fn_name, _field({t: val for t in pe}))
    spec = {"name": "graham_value_classic",
            "universe": {"type": "list", "tickers": ["DUST", "REAL", "EDGE"]},
            "filters": [{"fn": "pe_ratio", "op": "ge", "value": 0.5},
                        {"fn": "pe_ratio", "op": "lt", "value": 7},
                        {"fn": "price_to_book", "op": "lt", "value": 1.5},
                        {"fn": "debt_to_equity", "op": "lt", "value": 0.5},
                        {"fn": "current_ratio", "op": "gt", "value": 1.5}]}
    out = runner.run_spec(spec, store=_store())
    assert sorted(out.table["ticker"]) == ["EDGE", "REAL"]


# ── FIX 3: crossings surface reports the latest completed snapshot ──────────

def test_read_surface_reports_latest_completed_snapshot():
    db = DB()
    db.db["band_crossing_controls"] = [{"scope": "global", "orders_enabled": False}]
    db.db["band_crossing_scans"] = [
        {"id": 2, "kind": "weekly", "snapshot_id": 1, "started_at": "2026-11-10T04:42:54Z",
         "banded_names": 49, "crossings_written": 2}]
    db.db["band_crossings"] = []
    db.db["valuation_snapshots"] = [
        {"id": 3, "completed_at": "2026-11-10T04:46:16Z"},
        {"id": 2, "completed_at": "2026-11-10T04:43:23Z"}]
    surface = bc.read_surface(db)
    assert surface["latest_snapshot_id"] == 3
    assert surface["scans"][0]["snapshot_id"] == 1
