"""Daily universe refresh (Screening spec, Kevin 2026-11-02): pull the free
index/Nasdaq lists into the screening cache so universes track membership
instead of the bundled static proxies. Sources: Wikipedia's S&P 500 and
Nasdaq-100 constituent tables, and Nasdaq's own listed-securities file.
Each list lands as {tickers, as_of, source}; a failed pull keeps the previous
file (the footer of any run names which list it used)."""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(os.environ.get("TRADEHUB_SCREENING_CACHE", "/cache/screening"))
UA = {"User-Agent": "tradehub-screening sigeykevin@gmail.com"}


def _write(name: str, tickers: list[str], source: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"universe_{name}.json").write_text(json.dumps({
        "tickers": sorted(set(tickers)), "source": source,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}))


def _wiki_tickers(url: str, column: str) -> list[str]:
    # Wikipedia renames the header between pages and over time (the Nasdaq-100
    # page's constituents table reads "Symbol" now, not "Ticker"): accept
    # either header, on any table on the page.
    html = requests.get(url, headers=UA, timeout=30).text
    tables = pd.read_html(io.StringIO(html))
    for want in (column, "Symbol", "Ticker"):
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if want.lower() in cols:
                col = t.columns[cols.index(want.lower())]
                return [str(x).strip().replace(".", "-") for x in t[col] if str(x).strip()]
    raise ValueError(f"no '{column}' table at {url}")


def main() -> int:
    done, failed = [], []
    jobs = [
        ("sp500", lambda: _wiki_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
         "Wikipedia List of S&P 500 companies"),
        ("nasdaq100", lambda: _wiki_tickers("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
         "Wikipedia Nasdaq-100"),
    ]
    for name, pull, source in jobs:
        try:
            tickers = pull()
            if len(tickers) < 50:
                raise ValueError(f"suspiciously short list ({len(tickers)})")
            _write(name, tickers, source)
            done.append(name)
        except Exception as exc:
            failed.append({name: str(exc)[:200]})
    try:
        # The full listed file is slow through the proxy; a long read timeout
        # and one retry (the 2026-11-02 first run timed out at 60s).
        raw = None
        for attempt in range(2):
            try:
                raw = requests.get("https://www.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0",
                                   headers={**UA, "Accept": "application/json"}, timeout=240).json()
                break
            except Exception:
                if attempt == 1:
                    raise
        assert raw is not None
        tickers = [r["symbol"].strip() for r in raw["data"]["table"]["rows"] if r.get("symbol")]
        if len(tickers) < 1000:
            raise ValueError(f"suspiciously short list ({len(tickers)})")
        _write("nasdaq_all", tickers, "Nasdaq screener API (all listed)")
        done.append("nasdaq_all")
    except Exception as exc:
        failed.append({"nasdaq_all": str(exc)[:200]})
    print(json.dumps({"refreshed": done, "failed": failed}))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
