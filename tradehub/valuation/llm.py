"""Free-model chat for the valuation debate layer, on the hub's existing
plumbing pattern (the Workshop drafter's provider chain): Gemini's free tier
first when its key is set, then the OpenRouter free reasoning roster. A
refusal from a provider is an answer and stops the chain; an error moves to
the next provider; no provider at all raises LLMUnavailable. Structured
calls carry a JSON schema and the reply is validated as JSON either way.

The decision seat never rides this chain's free rotation for its identity —
the seat is judge.py's concern; this module is the proposer's voice."""
from __future__ import annotations

import json
import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent")


class LLMUnavailable(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


def _openrouter_models() -> list[str]:
    from tradehub.workshop.draft import _models

    return _models()


def _parse_json(content: str):
    """Parse a structured reply; reasoning models may fence or narrate around
    the JSON, so on a strict failure retry with the outermost {...} span."""
    try:
        return json.loads(content)
    except Exception:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(content[start:end + 1])


def _gemini(system: str, user: str, *, schema, post) -> tuple[object, str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable("no_key", "GEMINI_API_KEY is not set")
    model = os.getenv("VALUATION_LLM_MODEL", "").strip() or \
        os.getenv("GEMINI_DRAFT_MODEL", "").strip() or "gemini-3.8-flash"
    generation: dict = {"maxOutputTokens": 8192,
                        "thinkingConfig": {"thinkingBudget": 1024}}
    if schema is not None:
        generation["responseMimeType"] = "application/json"
        generation["responseJsonSchema"] = schema
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": generation,
    }
    try:
        resp = post(GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": key,
                             "content-type": "application/json"},
                    json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 -- any HTTP failure: next provider
        raise LLMUnavailable("error", f"gemini call failed: "
                             f"{type(exc).__name__}") from exc
    if (data.get("promptFeedback") or {}).get("blockReason"):
        raise LLMUnavailable("refused", "the model declined to answer")
    candidate = (data.get("candidates") or [{}])[0]
    if candidate.get("finishReason") in ("SAFETY", "BLOCKLIST",
                                         "PROHIBITED_CONTENT", "SPII"):
        raise LLMUnavailable("refused", "the model declined to answer")
    content = "".join(part.get("text") or ""
                      for part in (candidate.get("content") or {})
                      .get("parts") or [])
    if not content.strip():
        raise LLMUnavailable("error", "the model returned nothing")
    if schema is None:
        return content, model
    try:
        return _parse_json(content), model
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable("error", "the structured reply was not JSON") \
            from exc


def _openrouter(system: str, user: str, *, schema, post) -> tuple[object, str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable(
            "no_key", "no valuation model is configured on the server "
                      "(GEMINI_API_KEY / OPENROUTER_API_KEY)")
    body: dict = {
        "models": _openrouter_models()[:3],  # OpenRouter caps routes at 3
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": 8192,
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "ValuationPacket", "strict": False,
                            "schema": schema}}
    try:
        resp = post(OPENROUTER_URL, headers={"Authorization": f"Bearer {key}"},
                    json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable("error", f"openrouter call failed: "
                             f"{type(exc).__name__}") from exc
    if choice.get("finish_reason") == "content_filter" or not content.strip():
        raise LLMUnavailable("refused", "the model declined to answer")
    if schema is None:
        return content, data.get("model") or "openrouter"
    try:
        return _parse_json(content), data.get("model") or "openrouter"
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable("error", "the structured reply was not JSON") \
            from exc


def chat(system: str, user: str, *, schema: dict | None = None,
         post=requests.post) -> tuple[object, str]:
    """(content, model_id): the content is text, or the parsed JSON object
    when a schema was given. Gemini first (free tier), OpenRouter free roster
    as the fallback; a refusal stops the chain (draft.py's contract)."""
    if os.getenv("GEMINI_API_KEY", "").strip():
        try:
            return _gemini(system, user, schema=schema, post=post)
        except LLMUnavailable as exc:
            if exc.reason == "refused":
                raise
    return _openrouter(system, user, schema=schema, post=post)
