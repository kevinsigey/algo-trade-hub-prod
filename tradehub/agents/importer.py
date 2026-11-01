"""Framework output -> run artifact (feed spec §5). The framework's formats drift
between versions, so extraction is tolerant by construction: anything not found is
None ("not recorded"), never guessed. The full text always lands in report.md --
summaries here are openings/excerpts of it, marked when cut."""

from __future__ import annotations

import re

from tradehub.agents.schema import RATINGS, RunRecord

_RATING_RE = re.compile(r"rating[:\s\*]*\b(Buy|Overweight|Hold|Underweight|Sell)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"\b(Buy|Overweight|Hold|Underweight|Sell)\b")


def _cut(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rstrip() + " […]"


def _tail(text: str | None, limit: int) -> str | None:
    """The closing stretch of a debate history: the last argument, not the first."""
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None
    return text if len(text) <= limit else "[…] " + text[-limit:].lstrip()


def extract_decision(raw: dict) -> str | None:
    """The framework's rating, verbatim. Prefer an explicit decision string; else the
    Rating line of the final trade decision; else the first rating word in it."""
    decision = raw.get("decision")
    if isinstance(decision, str):
        for rating in RATINGS:
            if decision.strip().lower() == rating.lower():
                return rating
    state = raw.get("final_state") or {}
    final = state.get("final_trade_decision") or ""
    m = _RATING_RE.search(final) or _WORD_RE.search(final)
    if m:
        return next(r for r in RATINGS if r.lower() == m.group(1).lower())
    return None


def build_report(raw: dict) -> str:
    """The full markdown report assembled from the framework state, section by section.
    Whatever the framework produced is here whole; the card's summaries excerpt it."""
    state = raw.get("final_state") or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    parts = [f"# Agent debate: {raw.get('ticker', '')}"]
    for title, key in (("Market / technicals", "market_report"), ("Sentiment", "sentiment_report"),
                       ("News", "news_report"), ("Fundamentals", "fundamentals_report")):
        if state.get(key):
            parts.append(f"## {title}\n\n{state[key]}")
    if debate.get("bull_history"):
        parts.append(f"## Bull case (debate)\n\n{debate['bull_history']}")
    if debate.get("bear_history"):
        parts.append(f"## Bear case (debate)\n\n{debate['bear_history']}")
    research = state.get("investment_plan") or debate.get("judge_decision")
    if research:
        parts.append(f"## Research verdict\n\n{research}")
    if state.get("trader_investment_plan"):
        parts.append(f"## Trader plan\n\n{state['trader_investment_plan']}")
    if risk.get("judge_decision"):
        parts.append(f"## Risk verdict\n\n{risk['judge_decision']}")
    if state.get("final_trade_decision"):
        parts.append(f"## Final decision\n\n{state['final_trade_decision']}")
    return "\n\n".join(parts) + "\n"


def build_record(raw: dict, *, run_id: str, run_at_ct: str, run_at_utc: str, as_of_date: str,
                 historical: bool, status: str = "complete", error: str | None = None) -> RunRecord:
    state = raw.get("final_state") or {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    summaries = {
        "fundamentals": _cut(state.get("fundamentals_report"), 1500),
        "sentiment": _cut(state.get("sentiment_report"), 1500),
        "news": _cut(state.get("news_report"), 1500),
        "technicals": _cut(state.get("market_report"), 1500),
    }
    decision = extract_decision(raw)
    if status == "complete" and decision is None:
        status = "partial"  # a debate with no readable rating is a partial artifact
    return RunRecord(
        run_id=run_id, ticker=str(raw.get("ticker", "")).upper(), run_at_ct=run_at_ct,
        run_at_utc=run_at_utc, as_of_date=as_of_date, historical=historical,
        framework_version=raw.get("framework_version"), llm_provider=raw.get("llm_provider"),
        llm_model=raw.get("llm_model"), decision=decision, analyst_summaries=summaries,
        bull_case=_tail(debate.get("bull_history"), 1500), bear_case=_tail(debate.get("bear_history"), 1500),
        trader_rationale=_cut(state.get("trader_investment_plan"), 2000),
        # The risk team's reviewed verdict IS the final trade decision in current versions;
        # older ones carried a separate judge_decision on the risk state.
        risk_verdict=_cut(risk.get("judge_decision") or state.get("final_trade_decision"), 2000),
        inputs_note=raw.get("inputs_note"), cost_usd=raw.get("cost_usd"), status=status, error=error)
