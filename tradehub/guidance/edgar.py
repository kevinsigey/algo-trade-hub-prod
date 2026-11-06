"""SEC EDGAR reads for the guidance recorder: earnings 8-Ks and their press-release exhibit."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date

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


def http_get(url: str) -> dict:
    global _last
    wait = _last + _MIN_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    resp = httpx.get(url, headers={"User-Agent": SEC_UA}, timeout=20)
    _check(resp)
    return resp.json()


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


def exhibit_url(cik: str, accession: str, *, get: Callable[[str], dict] = http_get) -> str | None:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    docs = get(f"{base}/index.json")["directory"]["item"]
    ex = [d for d in docs if d["name"].lower().endswith(".htm") and d.get("type", "").upper().startswith("EX-99")]
    ex.sort(key=lambda d: d["type"].upper() != "EX-99.1")  # stable: EX-99.1 first, else first EX-99.x
    return f"{base}/{ex[0]['name']}" if ex else None
