"""SEC EDGAR reads for the guidance recorder: earnings 8-Ks and their press-release exhibit."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date
from html.parser import HTMLParser

import httpx

SEC_UA = os.getenv("SEC_USER_AGENT", "AlgoTradeHub research hub-research@example.com")
_MIN_GAP = 0.2  # 5 requests a second
_last = 0.0


class SecRefused(Exception):
    """SEC answered 403 or 429; the run stops and never retries in a loop."""


def _check(resp) -> None:
    if resp.status_code in (403, 429):
        raise SecRefused(f"SEC returned {resp.status_code}")
    resp.raise_for_status()


def _fetch(url: str):
    global _last
    wait = _last + _MIN_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    resp = httpx.get(url, headers={"User-Agent": SEC_UA}, timeout=20)
    _check(resp)
    return resp


def http_get(url: str) -> dict:
    return _fetch(url).json()


def get_text(url: str) -> str:
    return _fetch(url).text


def earnings_filings(cik: str, *, since: date, get: Callable[[str], dict] = http_get) -> list[dict]:
    r = get(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]
    out = []
    for i, form in enumerate(r["form"]):
        if form not in ("8-K", "8-K/A") or "2.02" not in r["items"][i].split(","):
            continue
        if date.fromisoformat(r["filingDate"][i]) < since:
            continue
        out.append({"cik": cik, "accession": r["accessionNumber"][i], "form": form,
                    "items": r["items"][i], "filed_at": r["acceptanceDateTime"][i]})
    return out


class _DocTable(HTMLParser):
    """Rows (type, href) of the 'Document Format Files' table on a filing index page."""

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, str]] = []
        self._in = False
        self._cells: list[str] = []
        self._href = ""
        self._td = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._in = a.get("summary") == "Document Format Files"
        elif self._in and tag == "tr":
            self._cells, self._href = [], ""
        elif self._in and tag == "td":
            self._td = True
            self._cells.append("")
        elif self._in and tag == "a" and not self._href:
            self._href = a.get("href") or ""

    def handle_data(self, data):
        if self._td:
            self._cells[-1] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self._td = False
        elif tag == "table":
            self._in = False
        elif tag == "tr" and self._in and len(self._cells) >= 4 and self._href:
            self.rows.append((self._cells[3].strip().upper(), self._href))


def exhibit_url(cik: str, accession: str, *, get: Callable[[str], str] = get_text) -> str | None:
    """EX-99.1 from the filing index page (index.json only carries icon names, not exhibit types)."""
    nodash = accession.replace("-", "")
    p = _DocTable()
    p.feed(get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}/{accession}-index.html"))
    ex = [h for t, h in p.rows if t.startswith("EX-99") and h.lower().endswith(".htm")]
    ex.sort(key=lambda h: next(t for t, x in p.rows if x == h) != "EX-99.1")
    return f"https://www.sec.gov{ex[0]}" if ex else None
