"""A model turns Kevin's plain words into an IdeaSpec draft. Kevin confirms or edits it before anything runs.

Two providers, one contract (phase-2 spec §2.2). Claude first: the Anthropic API with the IdeaSpec schema
generated from the pydantic model and forced as a tool call, so a reply that does not fit the engine's
contract cannot be returned. The free OpenRouter list is the automatic fallback when the Anthropic key is
unset or the call fails (a refusal is an answer, not a failure -- it does not fall back). No key, a refusal
or an API error all become DraftUnavailable, and the Workshop shows the hand-fill form.

Both providers answer in the same envelope -- {spec, requested, unexpressed} -- and the server diffs
`requested` against the spec's actual tickers: anything named but neither used nor explained in
`unexpressed` comes back as a loud drop, never a silent one. A draft may be incomplete; it may not be
quietly incomplete.
"""

from __future__ import annotations

import os

import requests
from pydantic import BaseModel, Field

from tradehub.workshop.spec import IdeaSpec

URL = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
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
    "N days is above the price). source spread watches the log ratio of two equal-weight baskets, series "
    "written A+B/C+D (longs/shorts), with measures level, change, vs_sma, volatility, zscore (standard deviations "
    "from its N-day mean) and percentile (today's rank in the last N days, 0-100); zscore and percentile also work "
    "on price and FRED series. Never invent results. "
    "Reply with JSON only."
)
ENVELOPE_NOTE = (
    " Beside the spec itself, return requested -- every ticker, leg and condition the words name, one short "
    "entry each -- and unexpressed -- anything the words ask for that the spec cannot carry, in plain words. "
    "A named ticker that does not appear in the spec must be explained in unexpressed; unexplained absences "
    "are reported to the user as silent drops."
)


class DraftEnvelope(BaseModel):
    """The drafter's reply (spec §2.2): the spec, what the words asked for, and what the
    schema could not carry. Its JSON schema is generated from IdeaSpec, never paraphrased."""

    spec: IdeaSpec
    requested: list[str] = Field(default_factory=list)
    unexpressed: list[str] = Field(default_factory=list)


class DraftUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def _models() -> list[str]:
    raw = os.getenv("OPENROUTER_MODELS", "")
    return [m.strip() for m in raw.split(",") if m.strip()] or list(MODELS)


def envelope_check(env: DraftEnvelope, text: str) -> tuple[list[str], list[str]]:
    """Diff `requested` against the spec (spec §2.2). Returns (dropped, unexpressed):
    dropped = tickers named in `requested` (or in the words themselves) that the spec never
    uses and `unexpressed` does not explain. Conditions cannot be diffed mechanically --
    a missing condition is exactly what `unexpressed` exists to confess."""
    from tradehub.workshop.playbook import dropped_tickers, tickers_in, used_tickers

    used = used_tickers(env.spec)
    explained: set[str] = set()
    for entry in env.unexpressed:
        explained |= set(tickers_in(entry))
    dropped: list[str] = []
    for entry in env.requested:
        for t in tickers_in(entry):
            if t not in used and t not in explained and t not in dropped:
                dropped.append(t)
    if text:
        for t in dropped_tickers(text, env.spec):
            if t not in explained and t not in dropped:
                dropped.append(t)
    return dropped, list(env.unexpressed)


def check_imported(spec: IdeaSpec, requested: list[str], unexpressed: list[str]) -> tuple[list[str], list[str]]:
    """The import door's half of the envelope contract: no original words to scan, so the
    diff runs on the supplied `requested` list alone."""
    return envelope_check(DraftEnvelope(spec=spec, requested=requested, unexpressed=unexpressed), "")


def _draft_claude(text: str, *, post=requests.post) -> tuple[DraftEnvelope, str]:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise DraftUnavailable("no_key", "ANTHROPIC_API_KEY is not set on the server")
    model = os.getenv("ANTHROPIC_DRAFT_MODEL", "").strip() or "claude-sonnet-4-5"
    body = {
        "model": model,
        "max_tokens": 4096,
        "system": SYSTEM + ENVELOPE_NOTE,
        "messages": [{"role": "user", "content": text}],
        "tools": [{"name": "draft_idea",
                   "description": "Return the drafted backtest spec, what the words requested, "
                                  "and anything the spec could not express.",
                   "input_schema": DraftEnvelope.model_json_schema()}],
        "tool_choice": {"type": "tool", "name": "draft_idea"},
    }
    try:
        resp = post(ANTHROPIC_URL, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                            "content-type": "application/json"},
                    json=body, timeout=90)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 -- any HTTP failure means: try the fallback
        raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc
    if data.get("stop_reason") == "refusal":
        raise DraftUnavailable("refused", "the model declined to draft this idea")
    for block in data.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == "draft_idea":
            try:
                return DraftEnvelope.model_validate(block.get("input") or {}), data.get("model") or model
            except Exception as exc:  # noqa: BLE001
                raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc
    raise DraftUnavailable("error", "the model returned no draft")


def _draft_openrouter(text: str, *, post=requests.post) -> tuple[DraftEnvelope, str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise DraftUnavailable("no_key", "no drafting model is configured on the server "
                                         "(ANTHROPIC_API_KEY / OPENROUTER_API_KEY)")
    body = {
        "models": _models(),
        "messages": [{"role": "system", "content": SYSTEM + ENVELOPE_NOTE},
                     {"role": "user", "content": text}],
        # strict is off: IdeaSpec has optional fields with defaults, which strict schemas reject on many providers.
        # The reply is validated against the envelope (and so IdeaSpec) below either way.
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "IdeaDraft", "strict": False,
                                            "schema": DraftEnvelope.model_json_schema()}},
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
        return DraftEnvelope.model_validate_json(content), data.get("model") or MODEL
    except Exception as exc:  # noqa: BLE001
        raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc


def draft_spec(text: str, *, post=requests.post) -> tuple[IdeaSpec, str, list[str], list[str]]:
    """(draft, the model id that wrote it, dropped, unexpressed). Claude first, OpenRouter
    on fallback; the envelope diff runs on whichever answered."""
    env: DraftEnvelope | None = None
    model = ""
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        try:
            env, model = _draft_claude(text, post=post)
        except DraftUnavailable as exc:
            if exc.reason == "refused":
                raise
            env = None  # unset key or a failed call: the free list gets its turn
    if env is None:
        env, model = _draft_openrouter(text, post=post)
    dropped, unexpressed = envelope_check(env, text)
    return env.spec, model, dropped, unexpressed
