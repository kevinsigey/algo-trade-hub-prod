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


def _write_names(names: dict[str, str]) -> None:
    """The security-name sidecar (ticker -> exchange security name) the
    common-equity universe cut reads: share class lives in the name
    ("... 5.45% Non-Cumulative Preferred Shares"), not in any ratio."""
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "universe_names.json").write_text(json.dumps({
        "names": dict(sorted(names.items())),
        "source": "Nasdaq Trader symbol directory + Wikipedia constituent tables",
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}))


def _norm(x) -> str:
    return str(x).strip().replace(".", "-")


def _wiki_pull(url: str, column: str) -> tuple[list[str], dict[str, str]]:
    # Wikipedia renames the header between pages and over time (the Nasdaq-100
    # page's constituents table reads "Symbol" now, not "Ticker"): accept
    # either header, on any table on the page. The company name rides along
    # when the table carries one (Security / Company).
    html = requests.get(url, headers=UA, timeout=30).text
    tables = pd.read_html(io.StringIO(html))
    for want in (column, "Symbol", "Ticker"):
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if want.lower() in cols:
                col = t.columns[cols.index(want.lower())]
                tickers = [_norm(x) for x in t[col] if str(x).strip()]
                names = {}
                for name_col in ("security", "company", "name"):
                    if name_col in cols:
                        ncol = t.columns[cols.index(name_col)]
                        names = {_norm(s): str(n).strip()
                                 for s, n in zip(t[col], t[ncol])
                                 if str(s).strip() and str(n).strip()}
                        break
                return tickers, names
    raise ValueError(f"no '{column}' table at {url}")


def _wiki_tickers(url: str, column: str) -> list[str]:
    return _wiki_pull(url, column)[0]


def main() -> int:
    done, failed = [], []
    names: dict[str, str] = {}
    jobs = [
        ("sp500", lambda: _wiki_pull("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
         "Wikipedia List of S&P 500 companies"),
        ("nasdaq100", lambda: _wiki_pull("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", "Ticker"),
         "Wikipedia List of NASDAQ-100 companies"),
    ]
    for name, pull, source in jobs:
        try:
            tickers, pulled_names = pull()
            if len(tickers) < 50:
                raise ValueError(f"suspiciously short list ({len(tickers)})")
            _write(name, tickers, source)
            names.update(pulled_names)
            done.append(name)
        except Exception as exc:
            failed.append({name: str(exc)[:200]})
    try:
        # The full listed universe comes from Nasdaq Trader's own symbol
        # directory files (small, canonical): the screener API's full-list
        # pull read-times-out through the proxy even at 240s (2026-11-02).
        # Test issues are excluded; the files' footer row is not a symbol.
        tickers = []
        for fname, sym_col in (("nasdaqlisted.txt", "Symbol"), ("otherlisted.txt", "ACT Symbol")):
            text = requests.get(f"https://www.nasdaqtrader.com/dynamic/symdir/{fname}",
                                headers=UA, timeout=60).text
            frame = pd.read_csv(io.StringIO(text), sep="|")
            frame = frame[frame["Test Issue"] == "N"]
            tickers += [_norm(x) for x in frame[sym_col]
                        if str(x).strip() and str(x) != "nan"]
            if "Security Name" in frame.columns:
                names.update({_norm(s): str(n).strip()
                              for s, n in zip(frame[sym_col], frame["Security Name"])
                              if str(s).strip() and str(n).strip()})
        if len(tickers) < 1000:
            raise ValueError(f"suspiciously short list ({len(tickers)})")
        _write("nasdaq_all", tickers, "Nasdaq Trader symbol directory (all listed)")
        done.append("nasdaq_all")
    except Exception as exc:
        failed.append({"nasdaq_all": str(exc)[:200]})
    if len(names) >= 1000:
        _write_names(names)
        done.append("names")
    else:
        failed.append({"names": f"only {len(names)} names pulled; sidecar kept from before"})
    print(json.dumps({"refreshed": done, "failed": failed}))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
