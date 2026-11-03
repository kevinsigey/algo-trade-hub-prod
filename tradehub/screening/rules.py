"""Deterministic NL -> spec fallback (the artifact prototype's design: AI
first, rules second, never a dead end). Deliberately small and legible:
each rule maps a plain phrase to the filter card a person would pick,
with the plausible value in the direction the words imply. "Guidance"
has no field in the catalog (planned, not faked); the market's reaction
to the last print is the honest proxy and the spec says so."""
from __future__ import annotations

_RULES = (
    (("momentum", "strong", "rising", "trending", "uptrend"),
     {"fn": "momentum", "params": {"months": 6}, "op": "pct_gte", "value": 75}),
    (("beat earnings", "earnings beat", "beat", "surprise"),
     {"fn": "last_print_surprise_pct", "op": "gt", "value": 0}),
    (("guidance", "reaction", "gapped up", "gap up"),
     {"fn": "last_print_reaction_pct", "op": "gt", "value": 0}),
    (("cheap", "value", "low p/e", "undervalued"),
     {"fn": "pe_ratio", "op": "lt", "value": 15}),
    (("cash flow", "fcf", "free cash"),
     {"fn": "fcf_yield", "op": "ge", "value": 4.0}),
    (("dividend", "yield", "income"),
     {"fn": "dividend_yield", "op": "ge", "value": 2.0}),
    (("growth", "growing", "grow"),
     {"fn": "revenue_growth_yoy", "op": "gt", "value": 10.0}),
    (("profitable", "quality", "margins"),
     {"fn": "operating_margin", "op": "gt", "value": 15.0}),
    (("oversold", "washed out", "washout"),
     {"fn": "rsi", "params": {"days": 14}, "op": "le", "value": 35}),
    (("52-week high", "52 week high", "near high", "new high"),
     {"fn": "drawdown_from_high", "op": "ge", "value": -5.0}),
    (("low volatility", "low vol", "calm", "steady"),
     {"fn": "realized_vol", "params": {"days": 63}, "op": "le", "value": 40.0}),
    (("large cap", "large-cap", "big companies", "mega"),
     {"fn": "market_cap", "op": "ge", "value": 10000000000}),
)


def rules_spec(query: str) -> dict | None:
    q = f" {query.lower()} "
    filters = []
    seen = set()
    for words, spec_filter in _RULES:
        if any(w in q for w in words):
            key = (spec_filter["fn"], str(spec_filter.get("params")))
            if key not in seen:
                seen.add(key)
                filters.append(dict(spec_filter))
    if not filters:
        return None
    score = []
    for f in filters:
        if f["fn"] == "momentum":
            score.append({"fn": "momentum", "params": {"months": 6}, "weight": 2, "direction": "high"})
        if f["fn"] == "last_print_surprise_pct":
            score.append({"fn": f["fn"], "weight": 1, "direction": "high"})
    return {"name": "described_screen", "universe": {"type": "index", "index": "sp500"},
            "filters": filters, "score": score, "limit": 10}
