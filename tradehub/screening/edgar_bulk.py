"""Bulk SEC company-facts pass for the screening cache (universe expansion
PR 2, Nov 2026).

The data layer's per-concept EDGAR reads (_edgar_rows) cost one API request
per (ticker, concept) — fine for hundreds of names, not for a ~6,000-name
listed universe. The SEC publishes the same dataset as one bulk file,
companyfacts.zip (one JSON per CIK, facts -> us-gaap -> concept -> units ->
rows: exactly the shape the companyconcept endpoint returns). This module
streams that file once and writes the SAME cache entries _edgar_rows would
have written — key `edgarrows|{ticker}|{concept}`, every unit merged,
10-K/10-Q rows only — so the field functions cannot tell the difference,
and the per-concept API remains the on-demand fallback for anything the
pass did not cover.

Only the concepts the registry reads are written: the _edgar_fn family in
functions.py plus EarningsPerShareDiluted (the annual-series input). Keep
CONCEPTS in step when a new EDGAR field registers. A concept absent from a
filer's bulk JSON is written as an empty entry — the bulk file is the
complete dataset, so absent means not reported, which is exactly what
_edgar_rows caches after a successful fetch.
"""

from __future__ import annotations

import json
import re
import urllib.request
import zipfile
from pathlib import Path

from tradehub.sec_ua import sec_user_agent

ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"

CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "CashAndCashEquivalentsAtCarryingValue",
    "DebtCurrent",
    "RevenueRemainingPerformanceObligation",
    "EarningsPerShareDiluted",
]

_FORMS = ("10-K", "10-Q")
_ENTRY = re.compile(r"CIK(\d+)\.json$")


def rows_from_facts(facts: dict, concept: str) -> list[dict]:
    """The 10-K/10-Q rows for one concept out of a per-CIK bulk JSON —
    the same merge and filter _edgar_rows applies to the API response."""
    units = (((facts.get("facts") or {}).get("us-gaap") or {})
             .get(concept) or {}).get("units") or {}
    rows: list[dict] = []
    for unit_rows in units.values():
        rows.extend(r for r in unit_rows if r.get("form") in _FORMS)
    return rows


def download(url: str, dest: Path) -> Path:
    """Stream the bulk zip to disk (never held in memory: the file is
    ~1.4 GB and the box is small). requests first, like _http_get — bare
    urllib stalls through this proxy for some hosts."""
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        with requests.get(url, headers=sec_user_agent(), stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    if chunk:
                        fh.write(chunk)
        return dest
    req = urllib.request.Request(url, headers=sec_user_agent())
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    return dest


def load_bulk(store, tickers, *, zip_path) -> dict:
    """Write edgarrows cache entries for `tickers` from the bulk zip.

    Fail-soft per CIK: one unreadable entry is skipped and counted, never
    fatal. Returns the pass's counts for the caller's log line.
    """
    cik_map = store._cik_map()
    wanted: dict[int, str] = {}
    for t in tickers:
        cik = cik_map.get(str(t).upper())
        if cik is not None:
            wanted[int(cik)] = str(t).upper()
    counts = {"universe": len(tickers), "with_cik": len(wanted),
              "ciks_seen": 0, "ciks_skipped": 0,
              "entries_written": 0, "rows_written": 0}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            m = _ENTRY.search(name)
            if not m:
                continue
            ticker = wanted.get(int(m.group(1)))
            if ticker is None:
                continue
            try:
                facts = json.loads(zf.read(name))
            except Exception:
                counts["ciks_skipped"] += 1
                continue
            counts["ciks_seen"] += 1
            for concept in CONCEPTS:
                rows = rows_from_facts(facts, concept)
                store.cache.set(f"edgarrows|{ticker}|{concept}", rows)
                counts["entries_written"] += 1
                counts["rows_written"] += len(rows)
    return counts
