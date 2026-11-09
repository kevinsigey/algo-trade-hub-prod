"""EDGAR frame selection (DataStore.edgar_concept).

The pinned case (SBUX, CashAndCashEquivalentsAtCarryingValue, captured from
the live companyconcept payload): the concept's fp=FY rows stop at
2021-10-03 while its latest reported observation is 2022-07-03. The old
selection — FY-tagged rows, then latest end — returned the 2021 frame, so
every downstream net-debt figure silently wore a 2021 as-of. The rule now:
instant concepts take the latest period end regardless of the fiscal-period
tag; duration concepts take a true full-year row (FY tag + a ~1-year span);
ties break by the latest filed date, so a restatement supersedes the
original filing."""
import json

import pytest

from tradehub.screening import sources

SBUX_CASH_ROWS = [
    # trimmed from the live payload; the trap rows are the FY ones
    {"end": "2020-09-27", "val": 4626400000, "form": "10-K", "fp": "FY",
     "filed": "2020-11-20", "accn": "a1"},
    {"end": "2021-10-03", "val": 6455700000, "form": "10-K", "fp": "FY",
     "filed": "2021-11-19", "accn": "a2"},
    {"end": "2021-10-03", "val": 6455700000, "form": "10-Q", "fp": "Q1",
     "filed": "2022-02-01", "accn": "a3"},
    {"end": "2022-01-02", "val": 3969400000, "form": "10-Q", "fp": "Q1",
     "filed": "2022-02-01", "accn": "a4"},
    {"end": "2022-04-03", "val": 3913400000, "form": "10-Q", "fp": "Q2",
     "filed": "2022-05-03", "accn": "a5"},
    {"end": "2022-07-03", "val": 3177500000, "form": "10-Q", "fp": "Q3",
     "filed": "2022-08-02", "accn": "a6"},
    # an 8-K row with an even later end: not an audited filing, never picked
    {"end": "2022-10-02", "val": 2800000000, "form": "8-K", "fp": "FY",
     "filed": "2022-11-01", "accn": "a7"},
]

REVENUE_ROWS = [
    {"start": "2023-10-02", "end": "2023-12-31", "val": 9.0e9,
     "form": "10-Q", "fp": "Q1", "filed": "2024-02-01", "accn": "r1"},
    {"start": "2022-10-03", "end": "2023-10-01", "val": 35.0e9,
     "form": "10-K", "fp": "FY", "filed": "2023-11-20", "accn": "r2"},
    {"start": "2023-10-02", "end": "2024-09-29", "val": 36.0e9,
     "form": "10-K", "fp": "FY", "filed": "2024-11-15", "accn": "r3"},
    # the same FY restated in a later filing: the later filed date wins
    {"start": "2023-10-02", "end": "2024-09-29", "val": 36.5e9,
     "form": "10-K", "fp": "FY", "filed": "2025-03-01", "accn": "r4"},
    # a two-year comparative column wearing an FY tag: not a one-year figure
    {"start": "2022-10-03", "end": "2024-09-29", "val": 71.0e9,
     "form": "10-K", "fp": "FY", "filed": "2024-11-15", "accn": "r5"},
    # a later quarter must not displace the annual figure for a flow concept
    {"start": "2024-09-30", "end": "2024-12-29", "val": 9.5e9,
     "form": "10-Q", "fp": "Q1", "filed": "2025-02-01", "accn": "r6"},
]


def test_sbux_cash_takes_the_latest_period_end_not_the_latest_fy_tag():
    row = sources._select_edgar_row(
        [r for r in SBUX_CASH_ROWS if r["form"] in ("10-K", "10-Q")])
    assert (row["val"], row["end"]) == (3177500000, "2022-07-03")


def test_duration_concept_takes_the_full_year_row_latest_filed():
    row = sources._select_edgar_row(REVENUE_ROWS)
    assert (row["val"], row["end"]) == (36.5e9, "2024-09-29")


def test_edgar_concept_end_to_end_on_the_sbux_payload(tmp_path, monkeypatch):
    payloads = {
        "company_tickers.json": {"0": {"ticker": "SBUX", "cik_str": 829224}},
        "CashAndCashEquivalentsAtCarryingValue.json": {
            "units": {"USD": SBUX_CASH_ROWS}},
    }

    def fake_get(url, _headers, timeout=30):
        for key, payload in payloads.items():
            if url.endswith(key):
                return json.dumps(payload).encode()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(sources, "_http_get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    ds = sources.DataStore(cache_dir=tmp_path)
    assert ds.edgar_concept(
        "SBUX", "CashAndCashEquivalentsAtCarryingValue") == \
        (3177500000.0, "2022-07-03")


def test_edgar_concept_missing_concept_is_none_not_a_crash(tmp_path,
                                                          monkeypatch):
    def fake_get(url, _headers, timeout=30):
        if url.endswith("company_tickers.json"):
            return json.dumps(
                {"0": {"ticker": "SBUX", "cik_str": 829224}}).encode()
        return json.dumps({"units": {}}).encode()

    monkeypatch.setattr(sources, "_http_get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    ds = sources.DataStore(cache_dir=tmp_path)
    assert ds.edgar_concept("SBUX", "NoSuchConcept") is None


@pytest.mark.parametrize("rows", [[], [{"form": "10-K"}]])
def test_select_edgar_row_tolerates_junk(rows):
    assert sources._select_edgar_row(rows) is None
