"""Phase 1 -- the Interpreter: Kevin's text -> a validated StrategySpec.

The LLM's only output is the envelope {"spec": {...}, "questions": [...]}.
Anything the text does not settle goes in questions -- the model is told
never to guess a number. The reply is validated by tradehub.agent.spec;
every validation problem is appended to the questions, so what Kevin sees
is either a clean spec or a spec plus exactly what still needs his call.

Transports mirror the Workshop drafter: Gemini first (free tier), then
OpenRouter's free reasoning routes (capped at 3 -- OpenRouter rejects
longer routes). Context snippets (RAG over Kevin's corpus) may be attached
by the caller; the interpreter never fetches anything itself.
"""
from __future__ import annotations

import json
import os

import requests

from tradehub.agent.spec import validate_spec
from tradehub.workshop.draft import GEMINI_URL, _models

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = """You turn a trader's strategy memo into a StrategySpec JSON object. Reply with ONLY a
JSON object of the form {"spec": {...}, "questions": [...]} -- no prose outside it.

The spec fields:
- thesis: one paragraph condensing the memo in the trader's own framing.
- catalysts: short strings; invalidation: short strings (what would prove the thesis wrong).
- universe: ticker symbols the strategy trades.
- entry: {"rule": "close_below|close_above|manual|event", "band_pct": number or null} --
  band_pct is how far through a level price must go before entry, when the memo says one.
- sizing: {"kind": "pct_of_equity", "value": percent of equity in total, "per_name_cap_pct": at most 25}.
- stops: {"kind": "pct|price|none", "value": number or null}.
- exits: {"take_profit_pct": number or null, "time_stop_days": number or null}.
- horizon: {"terminal_date": "YYYY-MM-DD" or null} -- a date the position must be judged by.
- monitoring: any of ["price_cross", "headline_keyword", "invalidation", "terminal_date"].
- scoring: {"benchmark": "SPY", "review_at": "terminal_date" or null}.

RULES: never invent a number, ticker, or date the memo does not support. Anything missing or
ambiguous goes in "questions" as a plain question for the trader, and the field is left null
(or, for required fields, your best reading PLUS a question flagging it). Attached context
snippets are the trader's own earlier writing -- use them to resolve references, not to
change the strategy."""


class InterpretUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def _envelope(content: str) -> tuple[dict, list[str]]:
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise InterpretUnavailable("error", "the model returned no interpretable spec")
    try:
        data = json.loads(content[start:end + 1])
    except Exception as exc:  # noqa: BLE001
        raise InterpretUnavailable("error", "the model returned no interpretable spec") from exc
    if not isinstance(data, dict) or not isinstance(data.get("spec"), dict):
        raise InterpretUnavailable("error", "the model returned no interpretable spec")
    questions = [q for q in (data.get("questions") or []) if isinstance(q, str) and q.strip()]
    return data["spec"], questions


def _finish(spec: dict, questions: list[str], model: str) -> tuple[dict, list[str], str]:
    problems = validate_spec(spec)
    return spec, questions + [f"Needs your call -- {p}" for p in problems], model


def _interpret_gemini(text: str, *, post=requests.post) -> tuple[dict, list[str], str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise InterpretUnavailable("no_key", "GEMINI_API_KEY is not set on the server")
    model = os.getenv("GEMINI_DRAFT_MODEL", "").strip() or "gemini-3.8-flash"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 8192,
                             "thinkingConfig": {"thinkingBudget": 1024}},
    }
    try:
        resp = post(GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": key, "content-type": "application/json"},
                    json=body, timeout=90)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 -- any failure: try the next provider
        raise InterpretUnavailable("error", f"the interpreter failed: {type(exc).__name__}") from exc
    candidate = (data.get("candidates") or [{}])[0]
    parts = ((candidate.get("content") or {}).get("parts") or [{}])
    content = "".join(p.get("text", "") for p in parts)
    if not content.strip():
        raise InterpretUnavailable("error", "the model returned no spec")
    spec, questions = _envelope(content)
    return _finish(spec, questions, model)


def _interpret_openrouter(text: str, *, post=requests.post) -> tuple[dict, list[str], str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise InterpretUnavailable("no_key", "no interpreting model is configured on the server "
                                             "(GEMINI_API_KEY / OPENROUTER_API_KEY)")
    body = {"models": _models()[:3],  # OpenRouter rejects routes with >3 models
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": text}]}
    try:
        resp = post(OPENROUTER_URL, headers={"Authorization": f"Bearer {key}"},
                    json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise InterpretUnavailable("error", f"the interpreter failed: {type(exc).__name__}") from exc
    content = ((data["choices"][0].get("message") or {}).get("content")) or ""
    if not content.strip():
        raise InterpretUnavailable("error", "the model returned no spec")
    spec, questions = _envelope(content)
    return _finish(spec, questions, data.get("model") or "openrouter")


def interpret(text: str, context: list[str] | None = None, *,
              post=requests.post) -> tuple[dict, list[str], str]:
    """(spec, questions, model). Gemini first, OpenRouter fallback; raises
    InterpretUnavailable when neither can serve."""
    if not text or not text.strip():
        raise InterpretUnavailable("error", "nothing to interpret -- paste the strategy text")
    prompt = text.strip()
    if context:
        joined = "\n\n---\n\n".join(c.strip() for c in context if c and c.strip())
        if joined:
            prompt = f"CONTEXT FROM THE TRADER'S OWN WRITING:\n{joined}\n\n=== THE MEMO ===\n{prompt}"
    errors: list[InterpretUnavailable] = []
    for fn in (_interpret_gemini, _interpret_openrouter):
        try:
            return fn(prompt, post=post)
        except InterpretUnavailable as exc:
            errors.append(exc)
    no_key = all(e.reason == "no_key" for e in errors)
    raise InterpretUnavailable("no_key" if no_key else "error",
                               errors[-1].args[0] if errors else "the interpreter is unavailable")
