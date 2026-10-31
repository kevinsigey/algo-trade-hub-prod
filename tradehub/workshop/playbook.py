"""The playbook (Kevin, 2026-10-31): plain words -> one of a fixed set of plays -> an IdeaSpec.

Instead of the AI writing a whole spec, the words are first matched against each play's typical phrasings (no AI),
the slots each play needs (tickers, days, thresholds, claim) are filled from what the words say, and the AI, when
there is a key, only picks which of the top candidates fits and adjusts slot values inside fixed ranges/options.
"none" sends the idea back to the free-form draft (draft.draft_spec). Plays come from Strategy HQ v5.0 and the
quants.md library (docs/research/2026-10-31-quants-md-and-tradingagents.md).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from tradehub.workshop.draft import URL, _models
from tradehub.workshop.spec import TICKER, IdeaSpec

# Plain names -> the instrument that actually tracks them ("GOLD" the ticker is a stock, Gold.com, not gold).
NAMES = [
    (r"\bgold\b", "GLD"), (r"\bsilver\b", "SLV"), (r"\b(oil|crude)\b", "USO"), (r"\bnat(ural)? ?gas\b", "UNG"),
    (r"\b(s ?& ?p( 500)?|the market|stocks|equities|general index|the index)\b", "SPY"),
    (r"\b(nasdaq|tech stocks|tech)\b", "QQQ"), (r"\b(small caps?|russell)\b", "IWM"),
    (r"\b(long )?bonds?\b|\btreasur(y|ies) etf\b", "TLT"), (r"\butilities\b", "XLU"), (r"\bstaples\b", "XLP"),
    (r"\bhealth ?care\b", "XLV"), (r"\benergy( stocks| sector)?\b", "XLE"), (r"\b(banks|financials)\b", "XLF"),
    (r"\bbitcoin\b", "IBIT"),
]
# Capitalised words that are not tickers in an idea's words.
NOT_TICKERS = {"VIX", "FED", "FOMC", "CPI", "GDP", "RSI", "MACD", "SMA", "EMA", "ETF", "ETFS", "USD", "WTI", "EIA",
               "AI", "AND", "THE", "OR", "IF", "WHEN", "BUY", "SELL", "HOLD", "LONG", "SHORT", "NYSE", "US", "IPO",
               "EPS", "PE", "ATH", "YOY", "QOQ", "OK", "TO", "IN", "ON", "AT", "OF", "IT", "IS", "BE", "VWAP", "DMA"}


def tickers_in(text: str) -> list[str]:
    """Tickers the words name, in order: $TICKER or a capitalised 2-5 letter word, and plain names (gold -> GLD)."""
    found: list[tuple[int, str]] = []
    for m in re.finditer(r"\$([A-Za-z][A-Za-z.\-]{0,9})|\b([A-Z]{2,5})\b", text):
        sym = (m.group(1) or m.group(2)).upper()
        if m.group(1) or sym not in NOT_TICKERS:
            found.append((m.start(), sym))
    low = text.lower()
    for pattern, sym in NAMES:
        for m in re.finditer(pattern, low):
            if not any(abs(m.start() - p) < 2 for p, _ in found):  # "$GOLD" is the stock, not the word "gold"
                found.append((m.start(), sym))
    found.sort()
    return list(dict.fromkeys(s for _, s in found if TICKER.match(s)))


def _explicit(text: str) -> list[str]:
    return [s for s in (m.group(1) or m.group(2) for m in re.finditer(r"\$([A-Za-z][A-Za-z.\-]{0,9})|\b([A-Z]{2,5})\b",
                                                                       text)) if s.upper() not in NOT_TICKERS or s.islower()]


# ---- slots ----

@dataclass(frozen=True)
class Slot:
    name: str
    kind: str  # tickers | ticker | int | num | choice
    default: Any
    hint: str
    lo: float | None = None
    hi: float | None = None
    options: tuple = ()

    def coerce(self, value: Any) -> Any:
        """The value if it fits this slot, else None (the caller keeps what it had)."""
        try:
            if self.kind == "tickers":
                vals = [str(v).strip().upper() for v in value][:5]
                return vals if vals and all(TICKER.match(v) for v in vals) else None
            if self.kind == "ticker":
                v = str(value).strip().upper()
                return v if TICKER.match(v) else None
            if self.kind in ("int", "num"):
                v = int(value) if self.kind == "int" else float(value)
                return v if self.lo <= v <= self.hi else None
            return value if value in self.options else None
        except (TypeError, ValueError):
            return None

    def schema(self) -> dict:
        if self.kind == "tickers":
            return {"type": "array", "items": {"type": "string"}, "maxItems": 5, "description": self.hint}
        if self.kind == "ticker":
            return {"type": "string", "description": self.hint}
        if self.kind in ("int", "num"):
            return {"type": "integer" if self.kind == "int" else "number", "minimum": self.lo, "maximum": self.hi,
                    "description": self.hint}
        return {"enum": list(self.options), "description": self.hint}


def T(name, default, hint):  # noqa: N802
    return Slot(name, "tickers", default, hint)


def T1(name, default, hint):  # noqa: N802
    return Slot(name, "ticker", default, hint)


def I(name, default, lo, hi, hint):  # noqa: N802, E743
    return Slot(name, "int", default, hint, lo, hi)


def N(name, default, lo, hi, hint):  # noqa: N802
    return Slot(name, "num", default, hint, lo, hi)


def C(name, default, options, hint):  # noqa: N802
    return Slot(name, "choice", default, hint, options=tuple(options))


def _c(source, series, measure, n, op, t, slow=None) -> dict:
    out = {"source": source, "series": series, "measure": measure, "lookback_days": n, "op": op, "threshold": t}
    return {**out, "slow_days": slow} if slow else out


def _rules(enter: list[dict], exit: list[dict] | None = None, mode: str = "all") -> dict:
    return {"enter": {"mode": mode, "conditions": enter}, "exit": {"mode": "any", "conditions": exit} if exit else None}


# ---- plays ----

@dataclass(frozen=True)
class Play:
    id: str
    name: str
    summary: str
    source: str
    patterns: tuple[tuple[str, int], ...]  # (regex on lower-cased words, weight)
    slots: tuple[Slot, ...]
    builder: Callable[[dict], dict]
    exclude: tuple[str, ...] = ()  # tickers the play reads as a signal, not as something to hold
    fillers: tuple[tuple[str, Callable[[re.Match], dict]], ...] = field(default_factory=tuple)


def _hedge(v):
    return {"hold": v["tickers"], "otherwise": v["otherwise"], "claim": v["claim"], "benchmark": v["market"],
            "rules": _rules([_c("price", v["market"], "pct_change", v["days"], "<", v["drop"])])}


def _ballast(v):
    return {"hold": v["tickers"], "claim": v["claim"], "benchmark": "SPY"}


def _trend(v):
    t = v["ticker"]
    return {"hold": [t], "claim": v["claim"], "benchmark": t,
            "rules": _rules([_c("price", t, "sma_cross", v["fast"], ">", 0, v["slow"])],
                            [_c("price", t, "sma_cross", v["fast"], "<", 0, v["slow"])])}


def _rsi(v):
    t = v["ticker"]
    return {"hold": [t], "claim": v["claim"], "benchmark": t, "exits": {"max_days": v["max_days"]},
            "rules": _rules([_c("price", t, "rsi", v["rsi_days"], "<", v["buy_below"])],
                            [_c("price", t, "rsi", v["rsi_days"], ">", v["sell_above"])])}


def _breakout(v):
    t = v["ticker"]
    return {"hold": [t], "claim": v["claim"], "benchmark": t,
            "rules": _rules([_c("price", t, "vs_high", v["high_days"], ">", 0)],
                            [_c("price", t, "vs_low", v["low_days"], "<", 0)])}


def _gate(v):
    return {"hold": v["tickers"], "claim": v["claim"], "benchmark": "SPY", "exits": {"stop_loss_pct": v["stop_pct"]},
            "rules": _rules([_c("price", "SPY", "vs_sma", v["sma_days"], ">", 0),
                             _c("fred", "VIXCLS", "level", 1, "<", v["vix_below"])])}


def _commodity(v):
    return {"hold": v["tickers"], "claim": v["claim"], "benchmark": "SPY",
            "rules": _rules([_c("fred", v["series"], "vs_sma", v["sma_days"], ">", 0)])}


def _macro(v):
    return {"hold": v["tickers"], "otherwise": v["otherwise"], "claim": v["claim"], "benchmark": "SPY",
            "rules": _rules([_c("fred", v["series"], "change", v["days"], v["direction"], v["threshold"])])}


def _analyst(v):
    t = v["ticker"]
    return {"hold": [t], "claim": v["claim"], "benchmark": "SPY",
            "rules": _rules([_c("analyst", t, v["measure"], v["days"], ">", v["threshold"])])}


def _hold(v):
    return {"hold": v["tickers"], "claim": v["claim"], "benchmark": v["benchmark"]}


CLAIMS = ("beats_benchmark", "beats_benchmark_when", "ballast", "smoother_ride")
MARKET_FALL = r"(stocks?|the market|market|spy|s ?& ?p|equit\w*|index\w*)"
FALL = r"(down|fall\w*|drop\w*|declin\w*|red|sell[- ]?offs?|crash\w*|tank\w*)"

PLAYS: tuple[Play, ...] = (
    Play("hedge_when_market_falls", "Hold it while the market falls",
         "Hold the asset only after SPY has fallen over the last N days; cash (or SPY) otherwise.",
         "Ideas #3/#5; quants.md hedge sleeve",
         ((rf"\bwhen (the )?{MARKET_FALL}\b.{{0,20}}\b{FALL}\b", 5), (rf"\b{FALL} (of|in) (the )?{MARKET_FALL}", 4),
          (r"\bballast against\b", 3), (r"\bhedge (against|for)\b", 3), (r"\bdoes (better|well) when\b", 1)),
         (T("tickers", ["GLD"], "what to hold"), T1("market", "SPY", "the market whose fall turns it on"),
          I("days", 21, 2, 126, "trading days the fall is measured over"),
          N("drop", 0.0, -20, 5, "SPY % change over those days must be below this"),
          C("otherwise", "CASH", ("CASH", "SPY"), "held the rest of the time"),
          C("claim", "beats_benchmark_when", CLAIMS, "what success means")),
         _hedge, exclude=("SPY",),
         fillers=((r"\b(\d{1,3})[- ]?(trading )?days?\b", lambda m: {"days": int(m.group(1))}),)),
    Play("ballast_basket", "Ballast basket",
         "Always hold a low-volatility basket; judged on SPY's down days.",
         "Strategy HQ v5.0 ballast sleeve (XLV, XLP, XLU, MA)",
         ((r"\bballast\b", 2), (r"\bdefensive\b", 3), (r"\bsafe[- ]?havens?\b", 3), (r"\blow[- ]?vol\w*\b", 3),
          (r"\bprotect\w*\b", 1)),
         (T("tickers", ["XLV", "XLP", "XLU", "MA"], "the basket"), C("claim", "ballast", CLAIMS, "what success means")),
         _ballast),
    Play("trend_following", "Moving-average trend",
         "Hold while the fast moving average is above the slow one (golden cross); out on the death cross.",
         "quants.md W01 (SMA 50/200)",
         ((r"\bgolden cross\b", 4), (r"\bdeath cross\b", 4), (r"\bmoving averages?\b", 3), (r"\b\d{1,3} ?/ ?\d{2,3}\b", 1),
          (r"\b(20|50|100|200)[- ]?(day|dma|sma)\b", 2), (r"\btrend(ing)?\b", 1)),
         (T1("ticker", "SPY", "what to hold"), I("fast", 50, 5, 200, "fast average, days"),
          I("slow", 200, 20, 400, "slow average, days"), C("claim", "smoother_ride", CLAIMS, "what success means")),
         _trend,
         fillers=((r"\b(\d{1,3}) ?/ ?(\d{2,3})\b", lambda m: {"fast": int(m.group(1)), "slow": int(m.group(2))}),)),
    Play("rsi_reversion", "RSI dip buy",
         "Buy when RSI says oversold, sell when it recovers, with a time stop.",
         "quants.md W03 / O03",
         ((r"\brsi\b", 4), (r"\boversold\b", 4), (r"\boverbought\b", 2), (r"\bmean[- ]?revers\w*\b", 3),
          (r"\bbuy (the )?dips?\b", 3), (r"\bbounce\b", 1)),
         (T1("ticker", "SPY", "what to hold"), I("rsi_days", 14, 2, 50, "RSI length"),
          N("buy_below", 35, 5, 50, "buy when RSI is below"), N("sell_above", 60, 50, 95, "sell when RSI is above"),
          I("max_days", 20, 1, 252, "sell after this many days regardless"),
          C("claim", "beats_benchmark", CLAIMS, "what success means")),
         _rsi,
         fillers=((r"\brsi\D{0,12}(below|under|<)\s*(\d{1,2})", lambda m: {"buy_below": float(m.group(2))}),
                  (r"\b(sell|exit)\D{0,20}(above|over|>)\s*(\d{2})", lambda m: {"sell_above": float(m.group(3))}))),
    Play("breakout", "Breakout",
         "Buy on a new N-day high, sell on a new M-day low.",
         "quants.md breakouts; Donchian",
         ((r"\bbreak ?outs?\b", 4), (r"\bnew (\d+[- ])?(day|week|month|year)?[- ]?highs?\b", 3), (r"\b52[- ]?week\b", 3),
          (r"\ball[- ]?time highs?\b", 2), (r"\bdonchian\b", 4)),
         (T1("ticker", "SPY", "what to hold"), I("high_days", 55, 5, 252, "buy on a new high over this many days"),
          I("low_days", 20, 5, 252, "sell on a new low over this many days"),
          C("claim", "beats_benchmark", CLAIMS, "what success means")),
         _breakout,
         fillers=((r"\b52[- ]?week\b", lambda m: {"high_days": 252}),
                  (r"\b(\d{1,3})[- ]?day highs?\b", lambda m: {"high_days": int(m.group(1))}))),
    Play("risk_gate", "Calm-market beta gate",
         "Hold equity beta only while SPY is above its average and VIX is calm; a stop below each entry.",
         "Strategy HQ v5.0 equity-beta gate (QQQ + SPY, VIX < 22, 2.5% stop)",
         ((r"\bvix\b", 4), (r"\bafter the fed\b", 3), (r"\bfomc\b", 3), (r"\brisk[- ]?on\b", 2), (r"\bgate\b", 1),
          (r"\bcalm\b", 1)),
         (T("tickers", ["QQQ", "SPY"], "what to hold"), I("sma_days", 50, 10, 200, "SPY must be above this average"),
          N("vix_below", 22, 10, 40, "VIX must be below"), N("stop_pct", 2.5, 0.5, 20, "stop-loss %"),
          C("claim", "smoother_ride", CLAIMS, "what success means")),
         _gate,
         fillers=((r"\bvix\D{0,12}(below|under|<)\s*(\d{2})", lambda m: {"vix_below": float(m.group(2))}),
                  (r"\b(\d(\.\d)?)% stop", lambda m: {"stop_pct": float(m.group(1))}))),
    Play("commodity_trend", "Oil-trend energy sleeve",
         "Hold energy while oil is above its moving average.",
         "Strategy HQ v5.0 oil sleeve (XLE, XOP, XOM, CVX)",
         ((r"\b(oil|crude|wti|brent)\b", 3), (r"\benergy\b", 1), (r"\bcommodit\w*\b", 2), (r"\btrend\w*\b", 1)),
         (T("tickers", ["XLE", "XOP", "XOM", "CVX"], "what to hold"),
          C("series", "DCOILWTICO", ("DCOILWTICO", "DCOILBRENTEU"), "the oil price (FRED)"),
          I("sma_days", 50, 10, 200, "oil must be above its average over this many days"),
          C("claim", "beats_benchmark", CLAIMS, "what success means")),
         _commodity, exclude=("USO",),
         fillers=((r"\bbrent\b", lambda m: {"series": "DCOILBRENTEU"}),)),
    Play("macro_regime", "Rates / macro regime",
         "Hold the asset while a FRED series (yields, the curve, inflation) moves the named way.",
         "Workshop step 2 (gold when rates rise)",
         ((r"\byields?\b", 3), (r"\b(interest )?rates?\b", 2), (r"\btreasur\w*\b", 2), (r"\bfed funds\b", 3),
          (r"\binflation\b", 2), (r"\b(yield )?curve\b", 2), (r"\bcpi\b", 2)),
         (T("tickers", ["GLD"], "what to hold"),
          C("series", "DGS10", ("DGS10", "DGS2", "T10Y2Y", "DFF", "T10YIE"), "the FRED series"),
          C("direction", ">", (">", "<"), "> rising, < falling"), I("days", 63, 5, 252, "change measured over"),
          N("threshold", 0.0, -3, 3, "change must be past this"), C("otherwise", "CASH", ("CASH", "SPY"), "otherwise"),
          C("claim", "beats_benchmark_when", CLAIMS, "what success means")),
         _macro, exclude=("SPY",),
         fillers=((r"\b(rise|rising|up|higher|climb\w*)\b", lambda m: {"direction": ">"}),
                  (r"\b(fall|falling|down|lower|drop\w*)\b", lambda m: {"direction": "<"}),
                  (r"\b2[- ]?year\b", lambda m: {"series": "DGS2"}), (r"\b(curve|spread)\b", lambda m: {"series": "T10Y2Y"}),
                  (r"\bfed funds\b", lambda m: {"series": "DFF"}), (r"\b(inflation|breakeven)\b", lambda m: {"series": "T10YIE"}))),
    Play("analyst_momentum", "Analyst momentum",
         "Hold a stock while analysts upgrade it more than they downgrade (or targets sit above the price).",
         "Step 6 Part B analyst signals",
         ((r"\bupgrad\w*\b", 4), (r"\bdowngrad\w*\b", 2), (r"\banalysts?\b", 3), (r"\bprice targets?\b", 4),
          (r"\bratings?\b", 1)),
         (T1("ticker", "AAPL", "the stock (not an ETF)"),
          C("measure", "net_upgrades", ("net_upgrades", "target_upside"), "upgrades minus downgrades, or target upside"),
          I("days", 63, 5, 252, "over this many trading days"), N("threshold", 0.0, -20, 50, "must be above"),
          C("claim", "beats_benchmark", CLAIMS, "what success means")),
         _analyst,
         fillers=((r"\b(price targets?|upside)\b", lambda m: {"measure": "target_upside", "threshold": 10.0}),)),
    Play("buy_and_hold", "Buy and hold",
         "Always hold it and see whether it beats the benchmark.",
         "baseline",
         ((r"\bbuy and hold\b", 4), (r"\bjust hold\b", 3), (r"\balways (hold|own)\b", 3)),
         (T("tickers", ["SPY"], "what to hold"), T1("benchmark", "SPY", "compared with"),
          C("claim", "beats_benchmark", CLAIMS, "what success means")),
         _hold),
)
BY_ID = {p.id: p for p in PLAYS}


@dataclass(frozen=True)
class Match:
    play: Play
    score: int
    why: tuple[str, ...]


def match(text: str) -> list[Match]:
    """Plays whose typical phrasings appear in the words, best first."""
    low = text.lower()
    out = []
    for p in PLAYS:
        hits = [m.group(0) for pat, _ in p.patterns for m in [re.search(pat, low)] if m]
        score = sum(w for pat, w in p.patterns if re.search(pat, low))
        if score:
            out.append(Match(p, score, tuple(hits)))
    return sorted(out, key=lambda m: -m.score)


def fill(play: Play, text: str) -> dict:
    """Slot values from the words, defaults for the rest."""
    values = {s.name: s.default for s in play.slots}
    low = text.lower()
    named = [t for t in tickers_in(text) if t not in play.exclude]
    explicit = [t for t in dict.fromkeys(s.upper() for s in _explicit(text)) if TICKER.match(t) and t not in play.exclude]
    picks = explicit or named
    for s in play.slots:
        if s.kind == "tickers" and picks:
            values[s.name] = picks[:5]
        elif s.kind == "ticker" and s.name not in ("market", "benchmark") and picks:
            values[s.name] = picks[0]
    for pattern, f in play.fillers:
        m = re.search(pattern, low)
        if m:
            for k, v in f(m).items():
                slot = next(s for s in play.slots if s.name == k)
                if slot.coerce(v) is not None:
                    values[k] = slot.coerce(v)
    return values


def build(play_id: str, values: dict, title: str) -> IdeaSpec:
    play = BY_ID[play_id]
    v = {s.name: s.default for s in play.slots} | {k: x for k, x in values.items() if k in {s.name for s in play.slots}}
    return IdeaSpec.model_validate({"title": title, **play.builder(v)})


def _title(text: str) -> str:
    t = " ".join(text.split())[:120]
    return t if len(t) >= 3 else f"Idea: {t}"


@dataclass
class Drafted:
    play: Play
    spec: IdeaSpec
    model: str
    why: tuple[str, ...]
    alternatives: list[Drafted] = field(default_factory=list)


PROMPT = ("You match one plain-words trading idea to the closest of the plays listed, or 'none' if no play fits what "
          "the words claim. Then give values for that play's slots, only where the words say something different from "
          "the suggested values. Use only tickers you are confident exist; 'gold' means GLD (GOLD is a stock). Never "
          "invent results. Reply with JSON only.")


def _ask(text: str, cands: list[Match], filled: dict[str, dict], post) -> tuple[str, dict, str] | None:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    slots: dict[str, dict] = {}
    for m in cands:
        for s in m.play.slots:
            slots.setdefault(s.name, s.schema())
    menu = [{"play": m.play.id, "name": m.play.name, "what": m.play.summary,
             "slots": {s.name: s.hint for s in m.play.slots}, "suggested": filled[m.play.id]} for m in cands]
    body = {"models": _models(),
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": json.dumps({"idea": text, "plays": menu})}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "PlayChoice", "strict": False, "schema": {
                "type": "object", "required": ["play"], "properties": {
                    "play": {"enum": [m.play.id for m in cands] + ["none"]},
                    "values": {"type": "object", "properties": slots}}}}}}
    try:
        resp = post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        reply = json.loads(data["choices"][0]["message"]["content"])
        return str(reply.get("play")), dict(reply.get("values") or {}), data.get("model") or "openrouter"
    except Exception:  # noqa: BLE001 -- the AI is optional here: fall back to the word match
        return None


def draft(text: str, *, post=requests.post, top: int = 3) -> Drafted | None:
    """The best play for these words, or None (no play fits: the free-form draft takes over)."""
    ranked = match(text)
    if not ranked:
        return None
    cands = ranked[:top]
    filled = {m.play.id: fill(m.play, text) for m in cands}
    chosen, values, model = cands[0].play.id, dict(filled[cands[0].play.id]), "playbook"
    asked = _ask(text, cands, filled, post)
    if asked is not None:
        pick, ai_values, model = asked
        if pick == "none":
            return None
        if pick in filled:
            chosen, values = pick, dict(filled[pick])
            for s in BY_ID[pick].slots:
                if s.name in ai_values and s.coerce(ai_values[s.name]) is not None:
                    values[s.name] = s.coerce(ai_values[s.name])
    title = _title(text)
    why = next(m.why for m in cands if m.play.id == chosen)
    alts = [Drafted(m.play, build(m.play.id, filled[m.play.id], title), "playbook", m.why)
            for m in cands if m.play.id != chosen]
    return Drafted(BY_ID[chosen], build(chosen, values, title), model, why, alts)
