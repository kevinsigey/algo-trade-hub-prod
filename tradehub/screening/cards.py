"""The filter-card catalog: the artifact prototype's presentation layer
over the engine catalog. Each card is one engine function at one fixed
parameterization, with a plain label, a one-line blurb, a unit, and a
PRESET (op + plausible value in the direction people usually mean), so
building a screen is picking cards and nudging numbers -- never writing
JSON. The engine catalog stays the data source for provenance."""
from __future__ import annotations

from tradehub.screening.catalog import catalog_dict

_NUM_OPS = ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"]

# id, fn, params, label, group, blurb, unit, preset (op, value)
_DEFS = [
    ("mcap", "market_cap", {}, "Market cap", "Universe & liquidity",
     "How big the company is. Screens usually set a floor so results stay tradable.", "$B", ("ge", 2_000_000_000)),
    ("price", "price", {}, "Last price", "Universe & liquidity",
     "Latest share price. A floor keeps out penny-stock noise.", "$", ("ge", 5)),
    ("avgvol", "avg_volume_3m", {}, "Average volume (3M)", "Universe & liquidity",
     "Shares traded on a typical day over the last 3 months -- the liquidity gate.", "M shares", ("ge", 1_000_000)),
    ("ret1m", "return_pct", {"days": 21}, "Return 1M", "Momentum & trend",
     "Price return over the last month or so (21 trading days).", "%", ("gt", 5)),
    ("ret3m", "return_pct", {"days": 63}, "Return 3M", "Momentum & trend",
     "Price return over the last quarter (63 trading days).", "%", ("gt", 10)),
    ("ret6m", "return_pct", {"days": 126}, "Return 6M", "Momentum & trend",
     "Price return over the last half year (126 trading days).", "%", ("gt", 15)),
    ("ret12m", "return_pct", {"days": 252}, "Return 12M", "Momentum & trend",
     "Price return over the last year (252 trading days).", "%", ("gt", 20)),
    ("mom6", "momentum", {"months": 6}, "Momentum 6M", "Momentum & trend",
     "Six-month momentum. As a percentile it reads 'stronger than X% of the universe'.", "%", ("pct_gte", 75)),
    ("mom121", "momentum", {"months": 12, "skip_days": 21}, "Momentum 12-1", "Momentum & trend",
     "The classic cross-sectional momentum: 12 months skipping the most recent month.", "%", ("pct_gte", 50)),
    ("ma200", "ma_position", {"days": 200}, "Vs 200-day average", "Momentum & trend",
     "Percent above (positive) or below the 200-day moving average -- the long-term trend state.", "%", ("gt", 0)),
    ("ma50", "ma_position", {"days": 50}, "Vs 50-day average", "Momentum & trend",
     "Percent above or below the 50-day moving average -- the short-term trend state.", "%", ("gt", 0)),
    ("ddhigh", "drawdown_from_high", {}, "Distance to the high", "Momentum & trend",
     "How far below its trailing high the price sits (0 = at the high, -25 = 25% below). Near-high confirms momentum.", "%", ("ge", -5)),
    ("rsi", "rsi", {"days": 14}, "RSI (14)", "Momentum & trend",
     "14-day relative strength index. Under ~35 reads oversold, over ~70 overbought.", "", ("le", 35)),
    ("vol63", "realized_vol", {"days": 63}, "Volatility 63d", "Volatility & risk",
     "Annualized realized volatility of daily returns over the last quarter.", "%", ("le", 40)),
    ("beta", "beta", {}, "Beta", "Volatility & risk",
     "Sensitivity to the market. Under 1 moves less than the market.", "x", ("le", 1.2)),
    ("surprise", "last_print_surprise_pct", {}, "Last earnings surprise", "Earnings",
     "How far the last reported EPS landed from expectations (positive = a beat).", "%", ("gt", 0)),
    ("reaction", "last_print_reaction_pct", {}, "Reaction to the last print", "Earnings",
     "How the stock moved on its last earnings -- the market's verdict, and the honest stand-in for 'guidance' until a guidance feed exists.", "%", ("gt", 0)),
    ("earn_growth", "earnings_growth_yoy", {}, "Earnings growth YoY", "Earnings",
     "Earnings growth versus the same quarter a year ago.", "%", ("gt", 0)),
    ("days_earn", "days_to_earnings", {}, "Days to next earnings", "Earnings",
     "Days until the next scheduled report. Small numbers = a catalyst is close.", "days", ("le", 30)),
    ("rev_growth", "revenue_growth_yoy", {}, "Revenue growth YoY", "Fundamentals & quality",
     "Latest revenue versus a year ago.", "%", ("gt", 10)),
    ("gross_m", "gross_margin", {}, "Gross margin", "Fundamentals & quality",
     "Gross profit over revenue. Missing for most financials -- those rows fail honestly.", "%", ("gt", 40)),
    ("op_m", "operating_margin", {}, "Operating margin", "Fundamentals & quality",
     "Operating income over revenue.", "%", ("gt", 15)),
    ("net_m", "net_margin", {}, "Net margin", "Fundamentals & quality",
     "Net income over revenue.", "%", ("gt", 10)),
    ("roe", "roe", {}, "Return on equity", "Fundamentals & quality",
     "Net income over shareholders' equity.", "%", ("gt", 15)),
    ("cur_ratio", "current_ratio", {}, "Current ratio", "Fundamentals & quality",
     "Current assets over current liabilities -- short-term balance-sheet room.", "x", ("ge", 1.5)),
    ("dte", "debt_to_equity", {}, "Debt / equity", "Fundamentals & quality",
     "Total debt over equity, in percent (150 = 1.5x).", "%", ("le", 150)),
    ("int_cov", "interest_coverage", {}, "Interest coverage", "Fundamentals & quality",
     "Operating earnings over interest expense -- how comfortably debt is serviced.", "x", ("ge", 3)),
    ("capex_int", "capex_intensity", {}, "Capex intensity", "Fundamentals & quality",
     "Capex over revenue. Separates the real spenders from asset-light compounders.", "%", ("ge", 3)),
    ("pe", "pe_ratio", {}, "P/E ratio", "Valuation",
     "Price over trailing earnings. The preset is the classic value line.", "x", ("lt", 15)),
    ("fwd_pe", "forward_pe", {}, "Forward P/E", "Valuation",
     "Price over next-twelve-months expected earnings.", "x", ("lt", 15)),
    ("ps", "price_to_sales", {}, "Price / sales", "Valuation",
     "Market value over revenue.", "x", ("lt", 3)),
    ("pb", "price_to_book", {}, "Price / book", "Valuation",
     "Price over book value per share.", "x", ("lt", 3)),
    ("ev_ebitda", "ev_to_ebitda", {}, "EV / EBITDA", "Valuation",
     "Enterprise value over EBITDA -- the acquirer's multiple.", "x", ("lt", 12)),
    ("fcf_yield", "fcf_yield", {}, "FCF yield", "Valuation",
     "Free cash flow over market cap -- the cash version of earnings yield.", "%", ("ge", 4)),
    ("div_yield", "dividend_yield", {}, "Dividend yield", "Valuation",
     "Trailing dividend over price.", "%", ("ge", 2)),
    ("fcc", "fcc_proxy", {}, "Cash coverage of capex", "Valuation",
     "Operating cash flow over capex. Under ~1x the build-out is funded by someone other than operations.", "x", ("ge", 1)),
    ("capex_guide_change", "capex_guide_change_pct", {}, "Capex guide change", "Guidance",
     "Latest capex guide vs the prior one for the same period. Raised capex into a cut FCF guide is the kill-zone pair.", "%", ("gt", 0)),
    ("fcf_guide_change", "fcf_guide_change_pct", {}, "FCF guide change", "Guidance",
     "Latest free-cash-flow guide vs the prior one for the same period. Negative is a cut.", "%", ("lt", 0)),
]


def cards_payload() -> list[dict]:
    by_fn = {f["name"]: f for f in catalog_dict()["functions"]}
    cards = []
    for cid, fn, params, label, group, blurb, unit, (op, value) in _DEFS:
        meta = by_fn.get(fn)
        if meta is None:
            continue
        divisor = {"mcap": 1_000_000_000, "avgvol": 1_000_000}.get(cid, 1)
        cards.append({"id": cid, "fn": fn, "params": params, "label": label,
                      "group": group, "blurb": blurb, "unit": unit,
                      "divisor": divisor,
                      "source": meta["source"], "ops": _NUM_OPS,
                      "preset": {"op": op, "value": value}})
    return cards
