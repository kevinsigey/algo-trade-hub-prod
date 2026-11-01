"""A free OpenRouter model turns Kevin's plain words into an IdeaSpec draft. Kevin confirms or edits it before anything
runs.

No key, a refusal or an API error all become DraftUnavailable, and the Workshop shows the hand-fill form. Free models
churn on OpenRouter, so the request names a fallback list (`models`) and the reply's model id is what gets recorded.
"""

from __future__ import annotations

import os

import requests

from tradehub.workshop.spec import IdeaSpec

URL = "https://openrouter.ai/api/v1/chat/completions"
# Free models OpenRouter listed with structured outputs on 2026-10-30, best first. Override: OPENROUTER_MODELS.
MODELS = ("nvidia/nemotron-3.5-super-vl:free", "dots-studio/dots-3-note-preview:free",
          "xingchen-agi/xing4.0-29b-a4b:free")
MODEL = MODELS[0]
SYSTEM = (
    "You turn one plain-words trading idea into a backtest spec. Use only daily ETF/stock tickers and FRED series ids "
    "you are confident exist. Pick the claim that matches what the idea says success is: beating the benchmark "
    "overall (beats_benchmark), beating it only while its rule has it in (beats_benchmark_when), protecting on SPY's "
    "down days (ballast), or a shallower worst drop at similar return (smoother_ride). Every choice the words do "
    "not pin down goes in assumptions as one short sentence, for example \"rates rising = 10-year yield up more "
    "than 0.25 points over 3 months\". Tickers the idea bets against go in short (hold stays the long side; either may be "
    "empty, not both). Order execution defaults to a market order at the open; use timing close only when the idea "
    "says so (it fills a day later), and a limit order only when it names a price discipline. Exits (stop-loss %, "
    "trailing stop %, take-profit %, max days held) only when the idea names them. A timing idea goes in rules: "
    "rules.enter is the buy-when group and the optional rules.exit the sell-when group (without one it sells when the "
    "buy group stops holding); each group is all or any of 1-5 conditions. Measures: level, change, pct_change, "
    "vs_sma, sma_cross (needs slow_days > lookback_days), rsi, macd (fixed 12/26/9; above 0 = bullish), vs_high / "
    "vs_low (above 0 / below 0 = a new N-day high / low), volatility, vs_vwap; FRED series allow only level, change, "
    "pct_change, vs_sma and volatility. source analyst (stocks only, no ETFs; data mostly from 2019) allows "
    "net_upgrades (upgrades minus downgrades over N days) and target_upside (% the mean price target set in the last "
    "N days is above the price). Never invent results. "
    "Reply with JSON only."
)


class DraftUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def _models() -> list[str]:
    raw = os.getenv("OPENROUTER_MODELS", "")
    return [m.strip() for m in raw.split(",") if m.strip()] or list(MODELS)


def draft_spec(text: str, *, post=requests.post) -> tuple[IdeaSpec, str, list[str]]:
    """(draft, the model id that wrote it)."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise DraftUnavailable("no_key", "OPENROUTER_API_KEY is not set on the server")
    body = {
        "models": _models(),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
        # strict is off: IdeaSpec has optional fields with defaults, which strict schemas reject on many providers.
        # The reply is validated against IdeaSpec below either way.
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "IdeaSpec", "strict": False,
                                            "schema": IdeaSpec.model_json_schema()}},
    }
    try:
        resp = post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001 -- any HTTP or shape failure means: fill the form by hand
        raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc
    if choice.get("finish_reason") == "content_filter" or not content.strip():
        raise DraftUnavailable("refused", "the model declined to draft this idea")
    try:
        spec = IdeaSpec.model_validate_json(content)
    except Exception as exc:  # noqa: BLE001
        raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc
    from tradehub.workshop.playbook import dropped_tickers  # playbook imports draft: import here, not at the top
    return spec, data.get("model") or MODEL, dropped_tickers(text, spec)
