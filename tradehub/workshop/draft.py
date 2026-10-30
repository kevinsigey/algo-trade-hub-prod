"""Claude turns Kevin's plain words into an IdeaSpec draft. Kevin confirms or edits it before anything runs.

No key, a refusal or an API error all become DraftUnavailable, and the Workshop shows the hand-fill form.
Server-side refusal fallbacks are deliberately off: every draft is reviewed by Kevin, and a refusal already has
a fallback (the form).
"""

from __future__ import annotations

import os

from tradehub.workshop.spec import IdeaSpec

MODEL = "claude-opus-5-5"
SYSTEM = (
    "You turn one plain-words trading idea into a backtest spec. Use only daily ETF/stock tickers and FRED series ids "
    "you are confident exist. Pick the claim that matches what the idea says success is: beating the benchmark "
    "overall (beats_benchmark), beating it only while a condition holds (beats_benchmark_when), protecting on SPY's "
    "down days (ballast), or a shallower worst drop at similar return (smoother_ride). Every choice the words do "
    "not pin down goes in assumptions as one short sentence, for example \"rates rising = 10-year yield up more "
    "than 0.25 points over 3 months\". Never invent results."
)


class DraftUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def draft_spec(text: str, *, client=None) -> IdeaSpec:
    if client is None:
        if not os.getenv("ANTHROPIC_API_KEY", "").strip():
            raise DraftUnavailable("no_key", "ANTHROPIC_API_KEY is not set on the server")
        import anthropic

        client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model=MODEL, max_tokens=4000, output_config={"effort": "medium"}, system=SYSTEM,
            messages=[{"role": "user", "content": text}], output_format=IdeaSpec,
        )
    except Exception as exc:  # noqa: BLE001 -- any SDK or validation failure means: fill the form by hand
        raise DraftUnavailable("error", f"the draft failed: {type(exc).__name__}") from exc
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise DraftUnavailable("refused", "Claude declined to draft this idea")
    return response.parsed_output
