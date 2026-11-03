"""Data layer: yfinance + SEC EDGAR company facts + FRED (fredgraph CSV) +
local house files. Every getter records provenance (source + as-of) and, on
failure, records a missing-field reason instead of returning a silent zero.

TTL policy (cache aggressively, sources are rate-limited):
  prices 6h - info 24h - statements 7d - EDGAR 7d - FRED 24h - CIK map 30d.
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .cache import Cache

_UA = {"User-Agent": "screening-lab research sigeykevin@gmail.com"}
import os

# The house earnings panel lives on the VPS cache volume in production; absent
# file -> the earnings fields record missing-with-reason, never a fake zero.
_LOCAL_EARNINGS = Path(os.environ.get("TRADEHUB_EARNINGS_PANEL", "/cache/earnings_events.csv"))

TTL = {"prices": 6, "info": 24, "statements": 24 * 7, "edgar": 24 * 7,
       "fred": 24, "cikmap": 24 * 30, "options": 6, "earnings": 24}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _http_get(url: str, headers: dict, timeout: int = 30) -> bytes:
    """GET via requests when available (proxy/redirect handling on this VM
    stalls under bare urllib for some hosts, e.g. fred.stlouisfed.org),
    falling back to urllib."""
    try:
        import requests

        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.content
    except ImportError:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()


class DataStore:
    def __init__(self, cache_dir: str | Path | None = None):
        root = Path(cache_dir) if cache_dir else Path(
            os.environ.get("TRADEHUB_SCREENING_CACHE", "/cache/screening"))
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:  # a dev box without the cache volume: home fallback
            root = Path("~/.cache/tradehub-screening").expanduser()
        self.cache = Cache(root)
        self.asof: dict[str, str] = {}          # data-kind -> ISO timestamp of data used
        self.missing: list[dict] = []           # {ticker, field, reason}

    # -- provenance / missing bookkeeping ------------------------------------
    def note_missing(self, ticker: str, field: str, reason: str) -> None:
        self.missing.append({"ticker": ticker, "field": field, "reason": str(reason)[:200]})

    def _note_asof(self, kind: str) -> None:
        self.asof.setdefault(kind, _now())

    # -- yfinance: prices ------------------------------------------------------
    def prices(self, tickers: list[str], years: int = 3) -> pd.DataFrame:
        """Adjusted daily closes, wide frame (columns = tickers)."""
        import yfinance as yf

        tickers = sorted(set(tickers))
        key = f"prices|{years}|{','.join(tickers)}"
        hit = self.cache.get(key, TTL["prices"])
        if hit is not None:
            self._note_asof("prices")
            return hit
        raw = yf.download(tickers, period=f"{years}y", auto_adjust=True,
                          progress=False, threads=True)
        if raw is None or len(raw) == 0:
            raise RuntimeError("yfinance download returned no data")
        closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(tickers[0])
        closes = closes[[c for c in closes.columns if c in tickers]]
        closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
        closes = closes.sort_index()
        self.cache.set(key, closes)
        self._note_asof("prices")
        return closes

    # -- yfinance: info ---------------------------------------------------------
    def info(self, ticker: str) -> dict:
        import yfinance as yf

        key = f"info|{ticker}"
        hit = self.cache.get(key, TTL["info"])
        if hit is not None:
            self._note_asof("info")
            return hit
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as e:
            self.note_missing(ticker, "info", e)
            return {}
        if info:
            self.cache.set(key, info)
        self._note_asof("info")
        return info

    # -- yfinance: statements ----------------------------------------------------
    def statements(self, ticker: str) -> dict[str, pd.DataFrame]:
        """Quarterly statements: {'income': df, 'balance': df, 'cashflow': df}."""
        import yfinance as yf

        key = f"stmt|{ticker}"
        hit = self.cache.get(key, TTL["statements"])
        if hit is not None:
            self._note_asof("statements")
            return hit
        t = yf.Ticker(ticker)
        out = {}
        for name, attr in (("income", "quarterly_income_stmt"),
                           ("balance", "quarterly_balance_sheet"),
                           ("cashflow", "quarterly_cashflow")):
            try:
                df = getattr(t, attr)
                out[name] = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
            except Exception as e:
                self.note_missing(ticker, f"statements.{name}", e)
                out[name] = pd.DataFrame()
        if any(len(v) for v in out.values()):
            self.cache.set(key, out)
        self._note_asof("statements")
        return out

    # -- yfinance: earnings dates / options ---------------------------------------
    def earnings_dates(self, ticker: str) -> pd.DataFrame:
        import yfinance as yf

        key = f"earn|{ticker}"
        hit = self.cache.get(key, TTL["earnings"])
        if hit is not None:
            self._note_asof("earnings")
            return hit
        df = pd.DataFrame()
        try:
            got = yf.Ticker(ticker).get_earnings_dates(limit=12)
            if isinstance(got, pd.DataFrame):
                df = got
        except Exception as e:
            self.note_missing(ticker, "earnings_dates", e)
        if len(df):
            self.cache.set(key, df)
        self._note_asof("earnings")
        return df

    def implied_move(self, ticker: str) -> float | None:
        """Nearest-expiry ATM straddle / spot, in %. None if chain unusable."""
        import yfinance as yf

        key = f"implied|{ticker}"
        hit = self.cache.get(key, TTL["options"])
        if hit is not None:
            self._note_asof("options")
            return hit
        t = yf.Ticker(ticker)
        try:
            expiries = t.options
            if not expiries:
                self.note_missing(ticker, "implied_move", "no options listed")
                return None
            chain = t.option_chain(expiries[0])
            spot = None
            hist = t.history(period="5d")
            if len(hist):
                spot = float(hist["Close"].iloc[-1])
            if not spot:
                self.note_missing(ticker, "implied_move", "no spot price")
                return None

            def atm(df: pd.DataFrame) -> float | None:
                if df is None or not len(df):
                    return None
                row = df.iloc[(df["strike"] - spot).abs().argsort().iloc[0]]
                bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
                if bid and ask and ask >= bid and (bid + ask) > 0:
                    return float((bid + ask) / 2)
                return float(last) if last else None

            call, put = atm(chain.calls), atm(chain.puts)
            if call is None or put is None:
                self.note_missing(ticker, "implied_move", "ATM leg price unavailable")
                return None
            val = (call + put) / spot * 100.0
            self.cache.set(key, val)
            self._note_asof("options")
            return val
        except Exception as e:
            self.note_missing(ticker, "implied_move", e)
            return None

    # -- SEC EDGAR company facts ---------------------------------------------------
    def _cik_map(self) -> dict[str, int]:
        hit = self.cache.get("cikmap", TTL["cikmap"])
        if hit is not None:
            return hit
        raw = json.loads(_http_get("https://www.sec.gov/files/company_tickers.json",
                                   _UA))
        out = {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
        self.cache.set("cikmap", out)
        return out

    def edgar_concept(self, ticker: str, concept: str) -> tuple[float, str] | None:
        """Latest value for a us-gaap concept: (value, period_end) or None.

        Flow concepts (revenue, capex) return the latest fiscal-YEAR figure;
        stock concepts (cash, debt, RPO) return the latest reported figure.
        """
        key = f"edgar|{ticker}|{concept}"
        hit = self.cache.get(key, TTL["edgar"])
        if hit is not None:
            self._note_asof("edgar")
            return tuple(hit) if hit else None
        try:
            cik = self._cik_map().get(ticker.upper())
            if cik is None:
                self.note_missing(ticker, f"edgar.{concept}", "no CIK for ticker")
                self.cache.set(key, [])
                return None
            url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
                   f"CIK{cik:010d}/us-gaap/{concept}.json")
            data = json.loads(_http_get(url, _UA))
            time.sleep(0.15)  # EDGAR fair-use: stay well under 10 req/s
            rows = []
            for unit_rows in (data.get("units") or {}).values():
                rows.extend(unit_rows)
            if not rows:
                self.note_missing(ticker, f"edgar.{concept}", "concept not reported")
                self.cache.set(key, [])
                return None
            df = pd.DataFrame(rows)
            df = df[df["form"].isin(["10-K", "10-Q"])]
            if not len(df):
                self.cache.set(key, [])
                return None
            df["end"] = pd.to_datetime(df["end"])
            fy = df[df.get("fp", "") == "FY"] if "fp" in df else df.iloc[0:0]
            pick = fy if len(fy) else df
            row = pick.sort_values("end").iloc[-1]
            val = (float(row["val"]), str(row["end"].date()))
            self.cache.set(key, list(val))
            self._note_asof("edgar")
            return val
        except Exception as e:
            self.note_missing(ticker, f"edgar.{concept}", e)
            return None

    # -- FRED (keyless fredgraph CSV) ------------------------------------------------
    def fred(self, series_id: str) -> pd.Series:
        key = f"fred|{series_id}"
        hit = self.cache.get(key, TTL["fred"])
        if hit is not None:
            self._note_asof("fred")
            return hit
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        # UA note (verified Nov 2, 2026 on this VM): fred.stlouisfed.org via
        # the egress proxy stalls indefinitely on descriptive/bot UAs
        # ("Mozilla/5.0", "screening-lab research" both read-time-out) while
        # a plain curl UA answers in ~2s. SEC EDGAR is the opposite — it
        # requires the descriptive UA in _UA and answers fine with it.
        last_err = None
        for _attempt in range(2):
            try:
                text = _http_get(url, {"User-Agent": "curl/8.5.0"},
                                 timeout=45).decode()
                break
            except Exception as e:  # one retry, then surface as missing
                last_err = e
        else:
            raise RuntimeError(f"FRED fetch failed for {series_id}: {last_err}")
        df = pd.read_csv(io.StringIO(text))
        df.columns = ["date", "value"]
        s = pd.Series(pd.to_numeric(df["value"], errors="coerce").values,
                      index=pd.to_datetime(df["date"])).dropna()
        s.name = series_id
        self.cache.set(key, s)
        self._note_asof("fred")
        return s

    # -- Local house files -------------------------------------------------------------
    def local_earnings_events(self) -> pd.DataFrame:
        """House earnings panel (ticker, report_date, surprise_pct, react_ar...)."""
        key = "local|earnings_events"
        hit = self.cache.get(key, 1)
        if hit is not None:
            self._note_asof("local")
            return hit
        if not _LOCAL_EARNINGS.exists():
            return pd.DataFrame()
        df = pd.read_csv(_LOCAL_EARNINGS, parse_dates=["report_date"])
        self.cache.set(key, df)
        self._note_asof("local")
        return df
