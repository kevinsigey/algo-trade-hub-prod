"""Deals builders (Part B): the IPO math reproduces Kevin's Anthropic entry
test to the paper's own assertions; the M&A math keeps its identities
(bridge splits sum to the synergy PV, ownership sums to 100, the ratio range
brackets standalone value)."""

import pytest

from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tradehub.deals.ipo import DealInputError, run_ipo
from tradehub.deals.ma import run_ma

ANTHROPIC = {"company": "Anthropic", "shares_b": 16.9368, "revenue_b": 65.0,
             "talk_low_ps": 85, "talk_high_ps": 110,
             "scenarios": [{"name": "bear", "ev_b": 446, "weight": 0.20},
                           {"name": "software comp", "ev_b": 1130, "weight": 0.30},
                           {"name": "base", "ev_b": 1525, "weight": 0.35},
                           {"name": "bull", "ev_b": 4628, "weight": 0.15}],
             "conditions": [{"name": "share", "odds": 0.60}, {"name": "layer", "odds": 0.45},
                            {"name": "constraint", "odds": 0.55}]}


def test_ipo_reproduces_the_paper():
    out = run_ipo(ANTHROPIC)
    assert out["pw_ev_b"] == pytest.approx(1656.15, abs=0.5)
    assert out["pw_ps"] == pytest.approx(97.78, abs=0.05)
    assert [r["ps"] for r in out["ladder"]] == [26.33, 66.72, 90.04, 273.25]
    assert out["conditions"]["joint_odds"] == 0.1485
    mid = out["entry"]["at_mid"]
    # The paper's verdict: no real price is a clean ENTER -- the bear is too deep.
    assert mid["enter"] is False and mid["rules"]["mos_25"] is False and mid["rules"]["bear_bound_40"] is False
    assert mid["bear_downside_pct"] == pytest.approx(-73.0, abs=0.2)


def test_ipo_validation_names_missing_inputs():
    with pytest.raises(DealInputError, match="weights must sum"):
        run_ipo({**ANTHROPIC, "scenarios": [{**s, "weight": 0.5} for s in ANTHROPIC["scenarios"]]})
    out = run_ipo({k: v for k, v in ANTHROPIC.items() if not k.startswith("talk")})
    assert "missing" in out["entry"]


SIDE = {"shares_b": 2.0, "price": 50.0, "revenue_b": 40.0, "ebitda_b": 8.0, "eps": 2.0,
        "rev_multiples": {"low": 1.0, "high": 1.5}, "ebitda_multiples": {"low": 8, "high": 12},
        "dcf": {"fcf_margin": 0.1, "growth": 0.05, "wacc": 0.1, "exit_multiple": 10}}


def test_ma_identities():
    out = run_ma({"acquirer": {**SIDE, "name": "Acq"}, "target": {**SIDE, "name": "Tgt", "price": 40.0},
                  "offer": {"exchange_ratio": 0.8, "cash_ps": 5.0, "undisturbed_ps": 40.0},
                  "synergies": {"bear": 0.5, "base": 1.0, "bull": 2.0}, "tax_rate": 0.25,
                  "synergy_multiple": 10})
    own = out["pro_forma"]["ownership"]
    assert own["acquirer_pct"] + own["target_pct"] == pytest.approx(100.0, abs=0.15)
    base = out["cases"]["base"]
    assert base["target_captures_b"] + base["acquirer_captures_b"] == pytest.approx(base["synergy_pv_b"], abs=0.02)
    assert out["ratio_range"]["low"] <= out["ratio_range"]["high"]
    assert out["offer"]["premium_pct"] == pytest.approx((45 / 40 - 1) * 100, abs=0.2)
    assert out["pro_forma"]["combined_revenue_b"] == 80.0
    assert base["accretion_pct"] is not None


def test_ma_missing_offer_is_named():
    with pytest.raises(DealInputError, match="exchange ratio"):
        run_ma({"acquirer": SIDE, "target": SIDE, "offer": {}})


def test_deals_api_saves_a_run(monkeypatch):
    from tests.test_screening_screens import FakeSupabase
    fake = FakeSupabase()
    main.app.dependency_overrides[main.admin.require_admin] = lambda: {"email": "k@example.com"}
    main.app.dependency_overrides[get_supabase] = lambda: fake
    try:
        c = TestClient(main.app)
        r = c.post("/api/deals/ipo/run", json={"inputs": ANTHROPIC})
        assert r.status_code == 201, r.text
        assert r.json()["outputs"]["pw_ps"] == pytest.approx(97.78, abs=0.05)
        bad = c.post("/api/deals/ipo/run", json={"inputs": {"shares_b": 1}})
        assert bad.status_code == 422
        listed = c.get("/api/deals/runs").json()
        assert listed[0]["kind"] == "ipo" and listed[0]["has_summary"] is False
    finally:
        main.app.dependency_overrides.pop(main.admin.require_admin, None)
        main.app.dependency_overrides.pop(get_supabase, None)


def test_fair_value_blend_and_ratio_position():
    out = run_ma({"acquirer": {**SIDE, "name": "Acq"}, "target": {**SIDE, "name": "Tgt", "price": 40.0},
                  "offer": {"exchange_ratio": 0.8, "cash_ps": 5.0, "undisturbed_ps": 40.0},
                  "synergies": {"bear": 0.5, "base": 1.0, "bull": 2.0}, "tax_rate": 0.25,
                  "synergy_multiple": 10})
    fv = out["fair_value"]
    mids = list(fv["methods"].values())
    assert min(mids) <= fv["ps"] <= max(mids)          # a blend sits inside its methods
    assert sum(fv["weights"].values()) == pytest.approx(1.0, abs=0.02)
    assert fv["ps_low"] <= fv["ps"] <= fv["ps_high"] and fv["verdict"]
    assert 0 <= out["ratio_range"]["position"] <= 1
    assert out["pro_forma"]["ev_at_offer_b"] > 0 and out["pro_forma"]["ev_to_revenue"] is not None


def test_ipo_prob_below_talk_mid():
    out = run_ipo(ANTHROPIC)
    # talk mid 97.5: bear (26.33, w .20) + comp (66.72, w .30) + base (90.04, w .35) sit below it
    assert out["prob_below_talk_mid"] == pytest.approx(0.85)
    assert out["implied_ps_at_pw"] == pytest.approx(1656.15 / 65.0, abs=0.2)


def test_edgar_prefill_parses_filed_facts():
    pub = pytest.importorskip("tradehub.deals.public")

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_get(url, headers=None, timeout=None):
        if "company_tickers" in url:
            return Resp({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}})
        concept = url.rsplit("/", 1)[-1].replace(".json", "")
        vals = {"RevenueFromContractWithCustomerExcludingAssessedTax": 400_000_000_000,
                "OperatingIncomeLoss": 120_000_000_000,
                "CashAndCashEquivalentsAtCarryingValue": 30_000_000_000,
                "DebtLongtermAndShorttermCombinedAmount": 100_000_000_000,
                "EntityCommonStockSharesOutstanding": 15_000_000_000,
                "EarningsPerShareDiluted": 7.5}
        if concept not in vals:
            raise RuntimeError("404")
        return Resp({"units": {"USD": [{"form": "10-K", "end": "2025-09-30",
                                        "filed": "2025-10-31", "val": vals[concept]}]}})

    pub._cik_cache.clear()
    out = pub.edgar_company("AAPL", get=fake_get)
    assert out["revenue_b"] == 400.0 and out["ebitda_b"] == 120.0
    assert out["net_cash_b"] == -70.0 and out["shares_b"] == 15.0
    assert out["filing_as_of"] == "2025-10-31" and "EDGAR" in out["source"]
