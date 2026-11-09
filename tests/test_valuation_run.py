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


def test_peer_sales_multiple_median_with_stale_member_excluded():
    mult, count, basis, group = val_run._peer_sales_multiple(FakeDS(), "GILD", NOW)
    # valid members: ABBV 10.0, AMGN 5.0, GILD 2.0, REGN 1.0 -> median 3.5.
    # BIIB is excluded on its 2019 revenue frame despite a computable ratio.
    assert group == "biotechnology"
    assert basis == "industry_group"
    assert count == 4
    assert mult == 3.5
