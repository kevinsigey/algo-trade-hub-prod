"""Classic-screen defect fixes (Kevin's survivor pull, 2026-11-09 22:14 CT):

1. Non-positive multiples are missing data encoded as a sentinel, never a
   reading: AEHL's trailing P/E of 0 passed Graham's "P/E < 7" as the sole
   survivor. Every info-sourced multiple where 0/negative can only be a
   sentinel now fails as missing with the reason logged.
2. Equity screens screen COMMON equity: Buffett's cohort was one issuer
   three times (ACGL + its preferreds ACGLN/ACGLO). The common_equity
   universe wrapper drops non-common classes by the exchange security
   name (refreshed names file; yfinance name as fallback).
3. Hygiene: the debt/equity card is a ratio (it was labelled "%" with a
   percent preset against a ratio field), the growth fields carry cards
   with units + sources, and the catalog carries a computed-at stamp.
"""

import json
import math
from types import SimpleNamespace

import pandas as pd
import pytest

from tradehub.screening import runner
from tradehub.screening.cards import cards_payload
from tradehub.screening.catalog import catalog_dict
from tradehub.screening.functions import REGISTRY
from tradehub.screening.spec import validate_spec
from tradehub.screening.universes import resolve_universe


class InfoStore:
    def __init__(self, infos=None):
        self._infos = infos or {}
        self.missing = []
        self.asof = {}

    def note_missing(self, ticker, field, reason):
        self.missing.append({"ticker": ticker, "field": field, "reason": str(reason)})

    def info(self, ticker):
        return self._infos.get(ticker, {})


def _field(name, store, tickers):
    return REGISTRY[name]["fn"](store, tickers)


# --------------------------------------------------------------------------
# fix 1: sentinel multiples fail as missing
# --------------------------------------------------------------------------

def test_pe_ratio_zero_and_negative_fail_as_missing():
    store = InfoStore({"ZERO": {"trailingPE": 0}, "NEG": {"trailingPE": -4.2},
                       "OK": {"trailingPE": 6.2}})
    out = _field("pe_ratio", store, ["ZERO", "NEG", "OK"])
    assert math.isnan(out["ZERO"]) and math.isnan(out["NEG"])
    assert out["OK"] == pytest.approx(6.2)
    reasons = {m["ticker"]: m["reason"] for m in store.missing if m["field"] == "pe_ratio"}
    assert "sentinel" in reasons["ZERO"] and "sentinel" in reasons["NEG"]


def test_the_other_positive_multiples_drop_nonpositive_sentinels():
    cases = [("price_to_book", "priceToBook"), ("price_to_sales", "priceToSalesTrailing12Months"),
             ("forward_pe", "forwardPE"), ("ev_to_ebitda", "enterpriseToEbitda"),
             ("current_ratio", "currentRatio"), ("market_cap", "marketCap")]
    for fname, key in cases:
        store = InfoStore({"ZERO": {key: 0}, "NEG": {key: -1.5}, "OK": {key: 2.5}})
        out = _field(fname, store, ["ZERO", "NEG", "OK"])
        assert math.isnan(out["ZERO"]) and math.isnan(out["NEG"]), fname
        assert out["OK"] == pytest.approx(2.5), fname
        assert any(m["field"] == fname and "sentinel" in m["reason"]
                   for m in store.missing), fname


def test_debt_to_equity_zero_is_real_but_negative_is_a_sentinel():
    store = InfoStore({"FREE": {"debtToEquity": 0}, "NEGEQ": {"debtToEquity": -45.0},
                       "OK": {"debtToEquity": 38.0}})
    out = _field("debt_to_equity", store, ["FREE", "NEGEQ", "OK"])
    assert out["FREE"] == 0.0                    # a debt-free company is real
    assert math.isnan(out["NEGEQ"])               # negative equity is not low leverage
    assert out["OK"] == pytest.approx(0.38)       # Yahoo percent -> ratio x
    assert any(m["ticker"] == "NEGEQ" and "sentinel" in m["reason"] for m in store.missing)


def test_lt_debt_to_equity_negative_equity_is_missing():
    cols = pd.to_datetime(["2026-09-30"])
    balance = pd.DataFrame([[100.0], [-50.0]],
                           index=["Long Term Debt", "Total Equity Gross Minority Interest"],
                           columns=cols)
    store = InfoStore()
    store.statements = lambda t: {"income": pd.DataFrame(), "balance": balance,
                                  "cashflow": pd.DataFrame()}
    out = _field("lt_debt_to_equity", store, ["AAA"])
    assert math.isnan(out["AAA"])
    assert any(m["field"] == "lt_debt_to_equity" for m in store.missing)


# --------------------------------------------------------------------------
# fix 2: common equity only
# --------------------------------------------------------------------------

NAMES = {
    "ACGL": "Arch Capital Group Ltd.",
    "ACGLN": "Arch Capital Group Ltd. 5.45% Non-Cumulative Preferred Shares",
    "ACGLO": "Arch Capital Group Ltd. 5.20% Non-Cumulative Preferred Shares",
    "SPACU": "Meridian Acquisition Corp Units",
    "BOND": "Example Corp 6.250% Senior Notes due 2031",
    "UALCO": "United Example Holdings Inc",
    "PLAIN": "Plain Common Corp",
}


@pytest.fixture
def names_file(tmp_path, monkeypatch):
    (tmp_path / "universe_names.json").write_text(json.dumps(
        {"names": NAMES, "source": "test", "as_of": "2026-11-09T11:17:03+00:00"}))
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(tmp_path))
    return tmp_path


def _wrap(tickers):
    return {"type": "common_equity", "base": {"type": "list", "tickers": tickers}}


def test_common_equity_drops_preferreds_units_and_notes(names_file):
    store = SimpleNamespace(info=lambda t: {})
    out = resolve_universe(store, _wrap(list(NAMES)))
    assert out == ["ACGL", "PLAIN", "UALCO"]


def test_common_equity_falls_back_to_the_info_name(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_SCREENING_CACHE", str(tmp_path))  # no names file
    infos = {"ACGL": {"longName": "Arch Capital Group Ltd."},
             "ACGLN": {"longName": "Arch Capital Group Ltd. 5.45% Non-Cumulative Preferred Shares"}}
    store = SimpleNamespace(info=lambda t: infos.get(t, {}))
    out = resolve_universe(store, _wrap(["ACGL", "ACGLN"]))
    assert out == ["ACGL"]


def test_preferred_series_never_reaches_a_classic_result(names_file, monkeypatch):
    saved = dict(REGISTRY)
    REGISTRY["fake_alpha"] = {"fn": lambda store, tickers, **p: pd.Series(
        {t: 5.0 for t in tickers}, dtype=float),
        "kind": "field", "returns": "float", "params": {},
        "source": "test", "category": "test", "doc": "fake"}
    try:
        store = SimpleNamespace(asof={}, missing=[],
                                info=lambda t: {"longName": NAMES.get(t, t)})
        spec = {"name": "graham-ish", "universe": _wrap(["ACGL", "ACGLN", "ACGLO"]),
                "filters": [{"fn": "fake_alpha", "op": "gt", "value": 3}]}
        result = runner.run_spec(spec, store=store)
        assert list(result.table["ticker"]) == ["ACGL"]
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)


def test_common_equity_specs_validate():
    spec = {"name": "classic", "membership_diff": True, "max_universe": 600,
            "universe": {"type": "common_equity",
                         "base": {"type": "index_union", "indexes": ["sp500", "nasdaq100"]}},
            "filters": [{"fn": "pe_ratio", "op": "lt", "value": 7}]}
    assert validate_spec(spec) is spec


# --------------------------------------------------------------------------
# fix 3 + 5 hygiene: cards and the catalog stamp
# --------------------------------------------------------------------------

def test_debt_to_equity_card_is_a_ratio():
    card = next(c for c in cards_payload() if c["fn"] == "debt_to_equity")
    assert card["unit"] == "x"
    assert card["preset"] == {"op": "lt", "value": 0.5}


def test_growth_fields_have_cards_with_units_and_sources():
    cards = {c["fn"]: c for c in cards_payload()}
    for fn in ("eps_growth_qoq", "eps_growth_yoy", "revenue_growth_qoq", "eps_growth_5y"):
        assert fn in cards, fn
        assert cards[fn]["unit"] == "%"
        assert cards[fn]["source"]  # provenance rides the card, not just the row
    assert "EDGAR" in cards["eps_growth_5y"]["source"]
    assert "statements" in cards["eps_growth_qoq"]["source"]


def test_catalog_carries_a_computed_at_stamp():
    stamp = catalog_dict()["computed_at"]
    assert stamp.endswith("Z") or "+00:00" in stamp
    from datetime import datetime
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))  # parses as ISO
