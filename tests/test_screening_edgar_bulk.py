"""EDGAR bulk pass (universe expansion PR 2): the SEC's companyfacts.zip
writes the same edgarrows cache entries the per-concept API path writes,
so EDGAR fields evaluate at full-universe scale from one download."""

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest

from tradehub.screening import edgar_bulk
from tradehub.screening.cache import Cache
from tradehub.screening.sources import TTL, DataStore

_FACTS = {
    "cik": 1, "entityName": "Acme",
    "facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 100,
             "form": "10-K", "fp": "FY", "filed": "2026-02-01",
             "frame": "CY2025"},
            {"start": "2026-01-01", "end": "2026-03-31", "val": 30,
             "form": "10-Q", "fp": "Q1", "filed": "2026-05-01"},
            {"end": "2024-06-30", "val": 9, "form": "S-1", "fp": "",
             "filed": "2024-07-01"},  # not a 10-K/10-Q row: excluded
        ], "USD/shares": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 1,
             "form": "10-K", "fp": "FY", "filed": "2026-02-01"},
        ]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 2.5,
             "form": "10-K", "fp": "FY", "filed": "2026-02-01"},
        ]}},
    }},
}


def test_rows_from_facts_merges_units_and_filters_forms():
    rows = edgar_bulk.rows_from_facts(_FACTS, "NetIncomeLoss")
    assert [(r["end"], r["val"]) for r in rows] == [
        ("2025-12-31", 100), ("2026-03-31", 30), ("2025-12-31", 1)]
    assert edgar_bulk.rows_from_facts(_FACTS, "DebtCurrent") == []
    assert edgar_bulk.rows_from_facts({}, "NetIncomeLoss") == []


def _bulk_zip(path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, blob in entries.items():
            zf.writestr(name, blob)


def _store(tmp_path, cik_map):
    return SimpleNamespace(cache=Cache(tmp_path / "cache"),
                           _cik_map=lambda: cik_map)


def test_load_bulk_writes_the_same_entries_the_api_path_reads(tmp_path, monkeypatch):
    zip_path = tmp_path / "companyfacts.zip"
    _bulk_zip(zip_path, {
        "CIK0000000001.json": json.dumps(_FACTS).encode(),
        "CIK0000000002.json": json.dumps(_FACTS).encode(),  # not in universe
        "CIK0000000003.json": b"not json",                   # corrupt: skipped
        "submissions-001.json": b"{}",                      # not a CIK entry
    })
    store = _store(tmp_path, {"ACME": 1, "BROKEN": 3})
    counts = edgar_bulk.load_bulk(store, ["ACME", "BROKEN", "NOCIK"],
                                  zip_path=zip_path)
    assert counts["universe"] == 3 and counts["with_cik"] == 2
    assert counts["ciks_seen"] == 1 and counts["ciks_skipped"] == 1
    assert counts["entries_written"] == len(edgar_bulk.CONCEPTS)
    rows = store.cache.get("edgarrows|ACME|NetIncomeLoss", TTL["edgar"])
    assert rows and len(rows) == 3
    # A concept the filer does not report is an honest empty entry.
    assert store.cache.get("edgarrows|ACME|DebtCurrent", TTL["edgar"]) == []
    assert store.cache.get("edgarrows|BROKEN|NetIncomeLoss", TTL["edgar"]) is None

    # The real data layer now reads those entries with the network DOWN:
    # _edgar_rows must serve from cache, and edgar_concept must compute.
    def _down(*a, **k):
        raise AssertionError("network touched")

    monkeypatch.setattr("tradehub.screening.sources._http_get", _down)
    ds = DataStore(cache_dir=tmp_path / "cache")
    assert len(ds._edgar_rows("ACME", "NetIncomeLoss")) == 3
    assert ds.edgar_concept("ACME", "NetIncomeLoss") == (100.0, "2025-12-31")
    series = ds.edgar_annual_series("ACME", "EarningsPerShareDiluted")
    assert series == [("2025-12-31", 2.5)]


def test_download_streams_via_requests_with_the_house_ua(tmp_path, monkeypatch):
    # _UA is a headers dict (sources.py); download must pass it as one.
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"abc"
            yield b""
            yield b"def"

    def fake_get(url, **kw):
        seen.update(kw)
        seen["url"] = url
        return Resp()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    dest = tmp_path / "z.zip"
    assert edgar_bulk.download("https://example.invalid/z.zip", dest) == dest
    assert dest.read_bytes() == b"abcdef"
    assert seen["headers"] == {"User-Agent": "screening-lab research sigeykevin@gmail.com"}
    assert seen["stream"] is True


def test_load_bulk_counts_a_universe_with_no_ciks(tmp_path):
    zip_path = tmp_path / "companyfacts.zip"
    _bulk_zip(zip_path, {"CIK0000000001.json": json.dumps(_FACTS).encode()})
    store = _store(tmp_path, {})
    counts = edgar_bulk.load_bulk(store, ["ZZZZ"], zip_path=zip_path)
    assert counts == {"universe": 1, "with_cik": 0, "ciks_seen": 0,
                      "ciks_skipped": 0, "entries_written": 0,
                      "rows_written": 0}
