"""The function library. Every function is a small, pure-ish primitive with
typed params, a one-line doc, and a declared data source. Functions are
registered in REGISTRY and exported to the catalog (catalog.json / .md).

Signature: fn(store, tickers, **params) -> pd.Series indexed by ticker.
Missing data is NaN plus a reason in store.missing — never a silent zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REGISTRY: dict[str, dict] = {}

MAJOR_EXCHANGES = {"NMS", "NYQ", "ASE", "NCM", "NGM", "NAS", "NYSE", "NASDAQ", "AMEX"}


def register(name, category, params, returns, doc, source, kind="field"):
    def deco(fn):
        REGISTRY[name] = {"name": name, "category": category, "params": params,
                          "returns": returns, "doc": doc, "source": source,
                          "kind": kind, "fn": fn}
        return fn
    return deco


def get_function(name):
    return REGISTRY.get(name)


def P(type_, default, doc):
    return {"type": type_, "default": default, "doc": doc}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _series(tickers, values):
    return pd.Series(values, index=pd.Index(tickers, name="ticker"), dtype="float64")


def _info_field(store, tickers, key, fname):
    out = {}
    for t in tickers:
        v = store.info(t).get(key)
        if v is None:
            store.note_missing(t, fname, f"info field '{key}' absent")
            out[t] = np.nan
        else:
            try:
                out[t] = float(v)
            except (TypeError, ValueError):
                out[t] = np.nan
    return _series(tickers, out)


def _row(frame: pd.DataFrame, *labels):
    """First matching row of a yfinance statement frame, as a Series over dates."""
    if frame is None or not len(frame):
        return None
    for lab in labels:
        if lab in frame.index:
            return frame.loc[lab]
    lower = {str(i).lower(): i for i in frame.index}
    for lab in labels:
        if lab.lower() in lower:
            return frame.loc[lower[lab.lower()]]
    return None


def _ttm(row) -> float:
    if row is None:
        return np.nan
    vals = pd.to_numeric(row, errors="coerce").dropna()
    if len(vals) < 4:
        return np.nan
    return float(vals.iloc[:4].sum())


def _latest(row) -> float:
    if row is None:
        return np.nan
    vals = pd.to_numeric(row, errors="coerce").dropna()
    return float(vals.iloc[0]) if len(vals) else np.nan


def _stmt(store, ticker):
    return store.statements(ticker)


# --------------------------------------------------------------------------
# identity / static
# --------------------------------------------------------------------------
@register("sector", "identity", {}, "str",
          "GICS sector of the company.", "yfinance.info")
def sector(store, tickers):
    vals = {}
    for t in tickers:
        v = store.info(t).get("sector")
        if v is None:
            store.note_missing(t, "sector", "info field absent")
        vals[t] = v
    return pd.Series(vals, index=pd.Index(tickers, name="ticker"), dtype="object")


@register("industry", "identity", {}, "str",
          "Industry of the company.", "yfinance.info")
def industry(store, tickers):
    vals = {}
    for t in tickers:
        v = store.info(t).get("industry")
        if v is None:
            store.note_missing(t, "industry", "info field absent")
        vals[t] = v
    return pd.Series(vals, index=pd.Index(tickers, name="ticker"), dtype="object")


@register("market_cap", "identity", {}, "usd",
          "Market capitalization, USD.", "yfinance.info")
def market_cap(store, tickers):
    return _info_field(store, tickers, "marketCap", "market_cap")


@register("price", "identity", {}, "usd",
          "Last close price, USD.", "yfinance prices")
def price(store, tickers):
    closes = store.prices(tickers)
    out = {}
    for t in tickers:
        if t in closes and closes[t].notna().any():
            out[t] = float(closes[t].dropna().iloc[-1])
        else:
            store.note_missing(t, "price", "no price history")
            out[t] = np.nan
    return _series(tickers, out)


@register("avg_volume_3m", "identity", {}, "shares",
          "Average daily share volume, trailing 3 months.", "yfinance.info")
def avg_volume_3m(store, tickers):
    return _info_field(store, tickers, "averageDailyVolume3Month", "avg_volume_3m")


@register("is_major_exchange", "identity", {}, "0/1",
          "1 if listed on NYSE/Nasdaq/Amex (the cleaned-screen 'listed' test), else 0.",
          "yfinance.info")
def is_major_exchange(store, tickers):
    out = {}
    for t in tickers:
        ex = store.info(t).get("exchange")
        if ex is None:
            store.note_missing(t, "is_major_exchange", "exchange field absent")
            out[t] = np.nan
        else:
            out[t] = 1.0 if ex in MAJOR_EXCHANGES else 0.0
    return _series(tickers, out)


# --------------------------------------------------------------------------
# valuation multiples
# --------------------------------------------------------------------------
@register("pe_ratio", "valuation", {}, "x",
          "Trailing price/earnings multiple.", "yfinance.info")
def pe_ratio(store, tickers):
    return _info_field(store, tickers, "trailingPE", "pe_ratio")


@register("forward_pe", "valuation", {}, "x",
          "Forward price/earnings multiple.", "yfinance.info")
def forward_pe(store, tickers):
    return _info_field(store, tickers, "forwardPE", "forward_pe")


@register("price_to_sales", "valuation", {}, "x",
          "Price / trailing-12-month sales.", "yfinance.info")
def price_to_sales(store, tickers):
    return _info_field(store, tickers, "priceToSalesTrailing12Months", "price_to_sales")


@register("price_to_book", "valuation", {}, "x",
          "Price / book value (quote field; can be negative when equity is).",
          "yfinance.info")
def price_to_book(store, tickers):
    return _info_field(store, tickers, "priceToBook", "price_to_book")


@register("ev_to_ebitda", "valuation", {}, "x",
          "Enterprise value / EBITDA.", "yfinance.info")
def ev_to_ebitda(store, tickers):
    return _info_field(store, tickers, "enterpriseToEbitda", "ev_to_ebitda")


@register("dividend_yield", "valuation", {}, "pct",
          "Trailing dividend yield, %.", "yfinance.info")
def dividend_yield(store, tickers):
    s = _info_field(store, tickers, "dividendYield", "dividend_yield")
    # yfinance reports dividendYield as a fraction (0.0054 = 0.54%); a whole
    # column maxing under 0.60 can only be fraction form (a 60%+ yield is not
    # a real large-cap state), so rescale that case to %.
    return s * 100.0 if s.notna().any() and s.max() <= 0.60 else s


# --------------------------------------------------------------------------
# fundamentals (statements + info ratios)
# --------------------------------------------------------------------------
@register("net_margin", "fundamentals", {}, "pct",
          "Net profit margin, % (the Finviz screen's profitability leg).",
          "yfinance.info")
def net_margin(store, tickers):
    s = _info_field(store, tickers, "profitMargins", "net_margin")
    return s * 100.0


@register("gross_margin", "fundamentals", {}, "pct",
          "Gross margin, %.", "yfinance.info")
def gross_margin(store, tickers):
    return _info_field(store, tickers, "grossMargins", "gross_margin") * 100.0


@register("operating_margin", "fundamentals", {}, "pct",
          "Operating margin, %.", "yfinance.info")
def operating_margin(store, tickers):
    return _info_field(store, tickers, "operatingMargins", "operating_margin") * 100.0


@register("roe", "fundamentals", {}, "pct",
          "Return on equity, %.", "yfinance.info")
def roe(store, tickers):
    return _info_field(store, tickers, "returnOnEquity", "roe") * 100.0


@register("debt_to_equity", "fundamentals", {}, "x",
          "Total debt / equity (info convention: percent, returned here as x).",
          "yfinance.info")
def debt_to_equity(store, tickers):
    s = _info_field(store, tickers, "debtToEquity", "debt_to_equity")
    return s / 100.0


@register("lt_debt_to_equity", "fundamentals", {}, "x",
          "Long-term debt / total equity, computed from the balance sheet "
          "(the Finviz screen's leverage leg, which info does not carry).",
          "yfinance statements (quarterly balance sheet)")
def lt_debt_to_equity(store, tickers):
    out = {}
    for t in tickers:
        bal = _stmt(store, t)["balance"]
        ltd = _latest(_row(bal, "Long Term Debt And Capital Lease Obligation",
                           "Long Term Debt", "LongTermDebt"))
        eq = _latest(_row(bal, "Total Equity Gross Minority Interest",
                          "Stockholders Equity", "Common Stock Equity"))
        if np.isnan(ltd) or np.isnan(eq) or eq == 0:
            store.note_missing(t, "lt_debt_to_equity", "LT debt or equity row absent")
            out[t] = np.nan
        else:
            out[t] = ltd / eq
    return _series(tickers, out)


@register("current_ratio", "fundamentals", {}, "x",
          "Current assets / current liabilities.", "yfinance.info")
def current_ratio(store, tickers):
    return _info_field(store, tickers, "currentRatio", "current_ratio")


@register("revenue_growth_yoy", "fundamentals", {}, "pct",
          "Revenue growth, year over year, %.", "yfinance.info")
def revenue_growth_yoy(store, tickers):
    return _info_field(store, tickers, "revenueGrowth", "revenue_growth_yoy") * 100.0


@register("earnings_growth_yoy", "fundamentals", {}, "pct",
          "Earnings growth, year over year, %.", "yfinance.info")
def earnings_growth_yoy(store, tickers):
    return _info_field(store, tickers, "earningsGrowth", "earnings_growth_yoy") * 100.0


@register("fcf_yield", "fundamentals", {}, "pct",
          "Free cash flow (TTM, from statements) / market cap, %.",
          "yfinance statements (quarterly cashflow) + info")
def fcf_yield(store, tickers):
    out = {}
    for t in tickers:
        cf = _stmt(store, t)["cashflow"]
        fcf = _ttm(_row(cf, "Free Cash Flow"))
        if np.isnan(fcf):
            ocf = _ttm(_row(cf, "Operating Cash Flow", "Total Cash From Operating Activities"))
            capex = _ttm(_row(cf, "Capital Expenditure"))
            fcf = ocf + capex if not (np.isnan(ocf) or np.isnan(capex)) else np.nan
        mc = store.info(t).get("marketCap")
        if np.isnan(fcf) or not mc:
            store.note_missing(t, "fcf_yield", "FCF or market cap absent")
            out[t] = np.nan
        else:
            out[t] = fcf / float(mc) * 100.0
    return _series(tickers, out)


@register("capex_intensity", "fundamentals", {}, "pct",
          "Capex (TTM) / revenue (TTM), %.", "yfinance statements (quarterly)")
def capex_intensity(store, tickers):
    out = {}
    for t in tickers:
        st = _stmt(store, t)
        capex = _ttm(_row(st["cashflow"], "Capital Expenditure"))
        rev = _ttm(_row(st["income"], "Total Revenue"))
        if np.isnan(capex) or np.isnan(rev) or rev == 0:
            store.note_missing(t, "capex_intensity", "capex or revenue row absent")
            out[t] = np.nan
        else:
            out[t] = abs(capex) / rev * 100.0
    return _series(tickers, out)


@register("interest_coverage", "fundamentals", {}, "x",
          "EBIT (TTM) / interest expense (TTM).",
          "yfinance statements (quarterly income)")
def interest_coverage(store, tickers):
    out = {}
    for t in tickers:
        inc = _stmt(store, t)["income"]
        ebit = _ttm(_row(inc, "EBIT", "Operating Income"))
        interest = _ttm(_row(inc, "Interest Expense"))
        if np.isnan(ebit) or np.isnan(interest) or interest == 0:
            store.note_missing(t, "interest_coverage", "EBIT or interest row absent")
            out[t] = np.nan
        else:
            out[t] = ebit / abs(interest)
    return _series(tickers, out)


@register("fcc_proxy", "fundamentals", {}, "x",
          "APPROXIMATION of the house Funded Conversion Coverage: TTM revenue / "
          "(TTM capex + current debt due + TTM interest expense). The true FCC is "
          "guide-based (next-12m guides), which free sources do not carry; "
          "FCC < 0.5x is the checklist funding flag.",
          "yfinance statements (quarterly)")
def fcc_proxy(store, tickers):
    out = {}
    for t in tickers:
        st = _stmt(store, t)
        rev = _ttm(_row(st["income"], "Total Revenue"))
        capex = _ttm(_row(st["cashflow"], "Capital Expenditure"))
        interest = _ttm(_row(st["income"], "Interest Expense"))
        cur_debt = _latest(_row(st["balance"],
                                "Current Debt And Capital Lease Obligation",
                                "Current Debt", "Short Long Term Debt",
                                "Short Term Borrowings"))
        legs = {"revenue": rev, "capex": capex, "interest": interest,
                "current_debt": cur_debt}
        bad = [k for k, v in legs.items() if v is None or (isinstance(v, float) and np.isnan(v))]
        if bad:
            store.note_missing(t, "fcc_proxy", f"missing legs: {','.join(bad)}")
            out[t] = np.nan
        else:
            bill = abs(capex) + cur_debt + abs(interest)
            out[t] = rev / bill if bill > 0 else np.nan
    return _series(tickers, out)


def _guidance_rows(tickers, metric):
    """Guidance-recorder rows for these tickers + one metric. Empty on any
    failure -- the caller turns 'no comparable pair' into NaN + a note."""
    try:
        from tradehub.core.supabase_client import get_client
        return (get_client().table("guidance_records")
                .select("ticker,period,metric,low,high,evidence,created_at")
                .in_("ticker", list(tickers)).eq("metric", metric)
                .execute().data) or []
    except Exception:  # noqa: BLE001 -- a screen field must degrade, not crash
        return []


def _latest_guide_change(records):
    """% change between a period's two most recent guide midpoints, for the
    period whose latest guide is newest. None when no period has a pair --
    a single guide is a level, not a change."""
    by_period = {}
    for r in records:
        if r.get("low") is None or r.get("high") is None or not r.get("period"):
            continue
        by_period.setdefault(r["period"], []).append(r)
    best = None
    for rs in by_period.values():
        rs = sorted(rs, key=lambda r: r["created_at"])
        if len(rs) < 2:
            continue
        prev_mid = (rs[-2]["low"] + rs[-2]["high"]) / 2
        last_mid = (rs[-1]["low"] + rs[-1]["high"]) / 2
        if not prev_mid:
            continue
        change = (last_mid - prev_mid) / abs(prev_mid) * 100
        if best is None or rs[-1]["created_at"] > best[0]:
            best = (rs[-1]["created_at"], change)
    return None if best is None else best[1]


def _guide_change(store, tickers, metric, field, evidence_needle=None):
    rows = _guidance_rows(tickers, metric)
    if evidence_needle:
        rows = [r for r in rows if evidence_needle in (r.get("evidence") or "").lower()]
    out = {}
    for t in tickers:
        change = _latest_guide_change([r for r in rows if r["ticker"] == t])
        if change is None:
            store.note_missing(t, field, "fewer than two comparable guidance records")
            out[t] = np.nan
        else:
            out[t] = change
    return _series(tickers, out)


@register("capex_guide_change_pct", "fundamentals", {}, "pct",
          "Change between the company's two most recent capex guides for the same period, % "
          "(latest guide midpoint vs the prior one). Positive = the capex guide was RAISED. "
          "Reads the guidance recorder (live since 2026-11-05); NaN until a name has two "
          "comparable capex guides on record.",
          "guidance recorder (EDGAR filings)")
def capex_guide_change_pct(store, tickers):
    return _guide_change(store, tickers, "capex", "capex_guide_change_pct")


@register("fcf_guide_change_pct", "fundamentals", {}, "pct",
          "Change between the company's two most recent free-cash-flow guides for the same "
          "period, % (recorder rows whose evidence names free cash flow). Negative = the FCF "
          "guide was CUT. Reads the guidance recorder (live since 2026-11-05); NaN until a "
          "name has two comparable FCF guides on record.",
          "guidance recorder (EDGAR filings)")
def fcf_guide_change_pct(store, tickers):
    return _guide_change(store, tickers, "other", "fcf_guide_change_pct",
                         evidence_needle="free cash flow")


# --------------------------------------------------------------------------
# price-derived transforms
# --------------------------------------------------------------------------
def _closes(store, tickers):
    closes = store.prices(tickers)
    return closes


@register("return_pct", "price",
          {"days": P("int", 126, "Lookback in trading days.")}, "pct",
          "Total return over the last N trading days, %.", "yfinance prices")
def return_pct(store, tickers, days=126):
    closes = _closes(store, tickers)
    out = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) > days:
            out[t] = (s.iloc[-1] / s.iloc[-1 - days] - 1) * 100.0
        else:
            store.note_missing(t, "return_pct", f"only {len(s)} sessions of history")
            out[t] = np.nan
    return _series(tickers, out)


@register("momentum", "price",
          {"months": P("int", 6, "Momentum window in months (~21 trading days each)."),
           "skip_days": P("int", 0, "Most-recent trading days skipped (classic 12-1 uses ~21).")},
          "pct",
          "Price momentum over the window, %.", "yfinance prices")
def momentum(store, tickers, months=6, skip_days=0):
    closes = _closes(store, tickers)
    out = {}
    days, skip = int(months) * 21, int(skip_days)
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) > days + skip:
            end = s.iloc[-1 - skip] if skip else s.iloc[-1]
            out[t] = (end / s.iloc[-1 - skip - days] - 1) * 100.0
        else:
            store.note_missing(t, "momentum", "insufficient history")
            out[t] = np.nan
    return _series(tickers, out)


@register("realized_vol", "price",
          {"days": P("int", 63, "Window in trading days.")}, "pct",
          "Annualized realized volatility of daily returns, %.", "yfinance prices")
def realized_vol(store, tickers, days=63):
    closes = _closes(store, tickers)
    out = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) > days:
            r = s.pct_change().iloc[-days:]
            out[t] = float(r.std() * np.sqrt(252) * 100.0)
        else:
            store.note_missing(t, "realized_vol", "insufficient history")
            out[t] = np.nan
    return _series(tickers, out)


@register("drawdown_from_high", "price",
          {"days": P("int", 252, "Window in trading days.")}, "pct",
          "Distance below the window's highest close, % (0 = at the high).",
          "yfinance prices")
def drawdown_from_high(store, tickers, days=252):
    closes = _closes(store, tickers)
    out = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) > 20:
            w = s.iloc[-days:]
            out[t] = (s.iloc[-1] / w.max() - 1) * 100.0
        else:
            store.note_missing(t, "drawdown_from_high", "insufficient history")
            out[t] = np.nan
    return _series(tickers, out)


@register("ma_position", "price",
          {"days": P("int", 200, "Moving-average length in trading days.")}, "pct",
          "Last close vs its N-day simple moving average, %.", "yfinance prices")
def ma_position(store, tickers, days=200):
    closes = _closes(store, tickers)
    out = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) >= days:
            out[t] = (s.iloc[-1] / s.iloc[-days:].mean() - 1) * 100.0
        else:
            store.note_missing(t, "ma_position", "insufficient history")
            out[t] = np.nan
    return _series(tickers, out)


@register("rsi", "price",
          {"days": P("int", 14, "RSI period.")}, "0-100",
          "Wilder RSI on daily closes.", "yfinance prices")
def rsi(store, tickers, days=14):
    closes = _closes(store, tickers)
    out = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else pd.Series(dtype=float)
        if len(s) > days * 3:
            d = s.diff()
            gain = d.clip(lower=0).ewm(alpha=1 / days, adjust=False).mean()
            loss = (-d.clip(upper=0)).ewm(alpha=1 / days, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            val = 100 - 100 / (1 + rs)
            out[t] = float(val.iloc[-1])
        else:
            store.note_missing(t, "rsi", "insufficient history")
            out[t] = np.nan
    return _series(tickers, out)


@register("beta", "price", {}, "x",
          "Beta vs the broad market (provider estimate).", "yfinance.info")
def beta(store, tickers):
    return _info_field(store, tickers, "beta", "beta")


# --------------------------------------------------------------------------
# earnings / context
# --------------------------------------------------------------------------
@register("days_to_earnings", "earnings", {}, "days",
          "Calendar days until the next scheduled earnings print.",
          "yfinance earnings dates")
def days_to_earnings(store, tickers):
    out = {}
    today = pd.Timestamp.now(tz="UTC").normalize()
    for t in tickers:
        df = store.earnings_dates(t)
        fut = None
        if len(df):
            idx = pd.DatetimeIndex(df.index)
            idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
            future = idx[idx >= today]
            if len(future):
                fut = int((future.min() - today).days)
        if fut is None:
            store.note_missing(t, "days_to_earnings", "no future print scheduled/found")
            out[t] = np.nan
        else:
            out[t] = float(fut)
    return _series(tickers, out)


@register("last_print_reaction_pct", "earnings", {}, "pct",
          "Abnormal reaction at the most recent print, from the house earnings "
          "panel (167 prints); NaN when the name is not in the panel.",
          "local: ~/workspace/ibkr-comp/earnings_events.csv")
def last_print_reaction_pct(store, tickers):
    panel = store.local_earnings_events()
    out = {}
    for t in tickers:
        if len(panel):
            rows = panel[panel["ticker"] == t]
            if len(rows):
                out[t] = float(rows.sort_values("report_date").iloc[-1]["react_ar"])
                continue
        store.note_missing(t, "last_print_reaction_pct", "not in house panel")
        out[t] = np.nan
    return _series(tickers, out)


@register("last_print_surprise_pct", "earnings", {}, "pct",
          "EPS surprise at the most recent print, from the house earnings panel.",
          "local: ~/workspace/ibkr-comp/earnings_events.csv")
def last_print_surprise_pct(store, tickers):
    panel = store.local_earnings_events()
    out = {}
    for t in tickers:
        if len(panel):
            rows = panel[panel["ticker"] == t]
            if len(rows):
                out[t] = float(rows.sort_values("report_date").iloc[-1]["surprise_pct"])
                continue
        store.note_missing(t, "last_print_surprise_pct", "not in house panel")
        out[t] = np.nan
    return _series(tickers, out)


@register("implied_move_pct", "earnings", {}, "pct",
          "Options-implied move into the next expiry: ATM straddle / spot, %. "
          "Slow (one chain pull per name) and absent where no options trade.",
          "yfinance options")
def implied_move_pct(store, tickers):
    out = {}
    for t in tickers:
        v = store.implied_move(t)
        out[t] = np.nan if v is None else float(v)
    return _series(tickers, out)


# --------------------------------------------------------------------------
# SEC EDGAR company facts (latest FY for flows, latest report for stocks)
# --------------------------------------------------------------------------
def _edgar_fn(concept):
    def f(store, tickers):
        out = {}
        for t in tickers:
            got = store.edgar_concept(t, concept)
            out[t] = np.nan if got is None else got[0]
        return _series(tickers, out)
    return f


for _name, _concept, _doc in [
    ("edgar_revenue_fy", "RevenueFromContractWithCustomerExcludingAssessedTax",
     "Latest fiscal-year revenue from EDGAR company facts, USD."),
    ("edgar_net_income_fy", "NetIncomeLoss",
     "Latest fiscal-year net income from EDGAR company facts, USD."),
    ("edgar_capex_fy", "PaymentsToAcquirePropertyPlantAndEquipment",
     "Latest fiscal-year capex from EDGAR company facts, USD."),
    ("edgar_cash", "CashAndCashEquivalentsAtCarryingValue",
     "Cash & equivalents, latest reported, from EDGAR company facts, USD."),
    ("edgar_debt", "DebtCurrent",
     "Current debt, latest reported, from EDGAR company facts, USD "
     "(not all filers tag it; NaN where untagged)."),
    ("edgar_rpo", "RevenueRemainingPerformanceObligation",
     "Remaining performance obligations (backlog), latest reported, from "
     "EDGAR company facts, USD — the book-to-bill input."),
]:
    register(_name, "edgar", {}, "usd", _doc,
             "SEC EDGAR company facts")(_edgar_fn(_concept))


# --------------------------------------------------------------------------
# macro / regime (context-only: scalars, not per-ticker fields)
# --------------------------------------------------------------------------
@register("fred_latest", "macro",
          {"series_id": P("str", "DGS10",
                          "FRED series id (DGS10, DGS2, T10Y2Y, FEDFUNDS, CPIAUCSL, UNRATE...).")},
          "level",
          "Latest value of a FRED macro series (regime context; used in a "
          "spec's 'context' block, not as a per-ticker filter).",
          "FRED fredgraph (keyless)", kind="context")
def fred_latest(store, tickers=None, series_id="DGS10"):
    s = store.fred(series_id)
    return float(s.iloc[-1]) if len(s) else np.nan
