"""Extract forward-looking statements from earnings calls using free OpenRouter models."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import requests
from pydantic import BaseModel, Field

from research.call_outlook.statements import Statement, verify, prefilter


CACHE_DIR = Path("research/call_outlook/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EXTRACTIONS_CACHE = CACHE_DIR / "extractions.jsonl"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TEXT_CHARS = 60_000


class Envelope(BaseModel):
    """Model reply envelope for statement extraction."""
    
    statements: list[dict] = Field(default_factory=list)
    model: str = ""


# System prompt for the model
SYSTEM_PROMPT = (
    "You are an expert financial analyst. Extract ONLY forward-looking financial statements "
    "made by MANAGEMENT (not analysts) from the provided earnings call transcript. "
    "Each statement must be a specific, verifiable claim about future financial performance. "
    "Return ONLY valid JSON with a 'statements' array. Each statement object must have exactly these fields:\n"
    "- topic: one of [revenue, demand, pricing, gross_margin, operating_margin, eps, costs, tariffs, other]\n"
    "- direction: one of [up, down, flat]\n"
    "- magnitude_pct: number or null (if the statement includes a specific percentage, e.g., '5%', '10-15%')\n"
    "- horizon: one of [next_quarter, full_year, longer, unspecified]\n"
    "- quote: EXACT verbatim sentence or clause from the text that supports this statement\n\n"
    "Rules:\n"
    "1. Only extract statements by MANAGEMENT (CEO, CFO, executives), not analysts.\n"
    "2. Only forward-looking statements (predictions, guidance, expectations, plans).\n"
    "3. The 'quote' must be an EXACT verbatim substring of the provided text.\n"
    "4. If magnitude_pct is given, the percentage must appear in the quote.\n"
    "5. Horizon: next_quarter, full_year, longer, or unspecified.\n"
    "6. Topic must be one of: revenue, demand, pricing, gross_margin, operating_margin, eps, costs, tariffs, other.\n"
    "7. Direction: up, down, or flat.\n"
    "8. Return ONLY valid JSON with a 'statements' array. No prose, no markdown.\n"
    "8. If no forward-looking statements by management, return {'statements': []}."
)


def _load_cache() -> dict[str, dict]:
    """Load the extraction cache from JSONL file."""
    cache = {}
    if EXTRACTIONS_CACHE.exists():
        with open(EXTRACTIONS_CACHE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    cache[record["call_id"]] = record
                except json.JSONDecodeError:
                    continue
    return cache


def _save_cache_entry(entry: dict) -> None:
    """Append a single entry to the JSONL cache."""
    with open(EXTRACTIONS_CACHE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _models() -> list[str]:
    """Get the list of free OpenRouter models to try."""
    from tradehub.workshop.draft import _models
    return _models()


def _parse_openrouter_response(content: str) -> dict:
    """Parse OpenRouter response content which may have prose around JSON."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(content[start:end + 1])


def _post_openrouter(
    text: str,
    *,
    key: str,
    model: str,
    post: Callable[..., Any] = requests.post
) -> dict:
    """Post a single request to OpenRouter with a specific model."""
    body = {
        "models": [model],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[:MAX_TEXT_CHARS]},
        ],
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json=body,
        timeout=90,
    )
    if resp.status_code == 401:
        raise PermissionError("OpenRouter rejected the key (HTTP 401)")  # never invent statements
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "content_filter":
        raise RuntimeError("model refused to extract statements")
    content = (choice.get("message") or {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("model returned no statements")
    return _parse_openrouter_response(content)


def extract_call(
    call_id: str,
    text: str,
    key: str,
    post: Callable[..., Any] = requests.post,
) -> list[dict]:
    """Extract forward-looking statements from a single call.

    Returns a list of verified statement dicts (each with topic, direction, magnitude_pct, horizon, quote).
    Caches the result; if already cached, returns cached result immediately.
    """
    cache = _load_cache()
    if call_id in cache:
        return cache[call_id]["statements"]

    prefiltered = prefilter(text)
    if not prefiltered.strip():
        # Cache empty result
        entry = {"call_id": call_id, "model": "", "statements": [], "dropped": 0}
        _save_cache_entry(entry)
        return []

    models = _models()
    last_error = None
    
    for model in models:
        try:
            result = _post_openrouter(prefiltered, key=key, model=model)
            raw_statements = result.get("statements", [])
            model_used = result.get("model", model)
            break
        except PermissionError:
            raise  # a bad key fails every model: stop, do not cache an empty result
        except Exception as e:
            last_error = e
            continue
    else:
        raise RuntimeError(f"All models failed: {last_error}")

    # Verify statements
    kept, dropped = verify(raw_statements, text)
    
    # Cache the result
    entry = {
        "call_id": call_id,
        "model": model,
        "statements": kept,
        "dropped": len(raw_statements) - len(kept),
    }
    _save_cache_entry(entry)
    
    return kept