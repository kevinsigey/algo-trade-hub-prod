"""Peer Price/Sales construction for the revenue band basis (Phase B
amendment, 2026-11-09): median over the frozen group of last close x diluted
shares / latest FY revenue, stale-revenue members excluded, sector widening
mirrors the forward-P/E path. DataStore is faked; no network."""
from datetime import datetime, timezone

import pandas as pd

from tradehub.valuation import run as val_run

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"
REV1 = "RevenueFromContractWithCustomerExcludingAssessedTax"

# GILD's frozen group (biotechnology): ABBV, AMGN, BIIB, GILD, INCY, MRNA, REGN, VRTX
PRICES = {"ABBV": 100.0, "AMGN": 50.0, "BIIB": 999.0, "GILD": 20.0,
          "INCY": 10.0, "MRNA": 10.0, "REGN": 10.0, "VRTX": 10.0}
EDGAR = {
    # ticker -> {concept: (value, as_of) or None}
    "ABBV": {SHARES: (10.0, "2026-09-30"), REV1: (100.0, "2026-09-30")},
    "AMGN": {SHARES: (10.0, "2026-09-30"), REV1: (100.0, "2026-09-30")},
    "BIIB": {SHARES: (10.0, "2026-09-30"), REV1: (100.0, "2019-12-31")},  # stale frame
    "GILD": {SHARES: (10.0, "2026-09-30"), REV1: (100.0, "2026-09-30")},
    "INCY": {SHARES: None, REV1: (100.0, "2026-09-30")},
    "MRNA": {SHARES: (10.0, "2026-09-30"), REV1: None},
    "REGN": {SHARES: (10.0, "2026-09-30"), REV1: (100.0, "2026-09-30")},
    "VRTX": {SHARES: None, REV1: None},
}


class FakeDS:
    def prices(self, tickers, years=1):
        idx = pd.to_datetime(["2026-11-06"])
        return pd.DataFrame({t: [PRICES[t]] for t in tickers}, index=idx)

    def edgar_concept(self, ticker, concept):
        return EDGAR.get(ticker, {}).get(concept)

    def info(self, ticker):
        return {}


REV2 = "Revenues"


class TowerDS:
    """Tower REITs: the ASC 606 concept is a sub-stream; the total revenue
    sits under 'Revenues' (Phase B annex, first-compute correction)."""

    PRICES = {"AMT": 190.0, "CCI": 90.0, "SBAC": 190.0}
    EDGAR = {
        "AMT": {SHARES: (470e6, "2025-12-31"), REV1: (0.94e9, "2025-12-31"),
                REV2: (10.5e9, "2025-12-31")},
        "CCI": {SHARES: (437e6, "2025-12-31"), REV1: (0.22e9, "2025-12-31"),
                REV2: (5.7e9, "2025-12-31")},
        "SBAC": {SHARES: (108e6, "2025-12-31"), REV1: (0.24e9, "2025-12-31"),
                 REV2: (2.7e9, "2025-12-31")},
    }

    def prices(self, tickers, years=1):
        idx = pd.to_datetime(["2026-11-06"])
        return pd.DataFrame({t: [self.PRICES[t]] for t in tickers}, index=idx)

    def edgar_concept(self, ticker, concept):
        return self.EDGAR.get(ticker, {}).get(concept)

    def info(self, ticker):
        return {}


def test_fy_revenue_reads_the_total_not_a_substream():
    hit = val_run._fy_revenue(TowerDS(), "AMT")
    assert hit == (10.5e9, "2025-12-31")


def test_peer_sales_multiple_for_towers_uses_totals():
    mult, count, basis, group = val_run._peer_sales_multiple(TowerDS(), "AMT", NOW)
    # totals: AMT 190*470M/10.5B = 8.50, CCI 90*437M/5.7B = 6.90,
    # SBAC 190*108M/2.7B = 7.60 -> median 7.60 (sub-streams would give ~95x)
    assert group == "telecom_tower_reits"
    assert count == 3
    assert mult == 7.6


def test_fundamentals_revenue_is_the_total():
    fund = val_run._fundamentals(TowerDS(), "AMT")
    assert fund["revenue"] == {"value": 10.5e9, "as_of": "2025-12-31"}


def test_peer_sales_multiple_median_with_stale_member_excluded():
    mult, count, basis, group = val_run._peer_sales_multiple(FakeDS(), "GILD", NOW)
    # valid members: ABBV 10.0, AMGN 5.0, GILD 2.0, REGN 1.0 -> median 3.5.
    # BIIB is excluded on its 2019 revenue frame despite a computable ratio.
    assert group == "biotechnology"
    assert basis == "industry_group"
    assert count == 4
    assert mult == 3.5
