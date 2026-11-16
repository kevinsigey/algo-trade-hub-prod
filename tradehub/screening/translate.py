"""Natural language -> screen spec (Screening A3). The translator runs on the
hub's OpenRouter reasoning-model chain (the Workshop drafter's model list --
Gemini's free daily quota stays reserved for debates and drafting). The
reply is extracted as JSON and MUST pass the same validate_spec every saved
screen passes. A translation that cannot honor part of the request DISLOSES
it in the returned notes (the model's "unhonored" list, a refusal, or the
rules fallback's standing disclosure) — never a silent fix-up or narrowing;
only a query no path can read raises."""

from __future__ import annotations

import json
import os

import requests

from tradehub.screening.catalog import OPS, catalog_dict
from tradehub.screening.rules import rules_spec
from tradehub.screening.spec import SpecError, validate_spec
from tradehub.workshop.draft import _models

URL = "https://openrouter.ai/api/v1/chat/completions"

EXAMPLE = {
    "name": "momentum_quality",
    "description": "Top-quartile 6-month momentum, positive earnings growth, leverage at or below the median.",
    "universe": {"type": "index", "index": "sp500"},
    "filters": [{"fn": "momentum", "params": {"months": 6}, "op": "pct_gte", "value": 75},
                {"fn": "earnings_growth_yoy", "op": "gt", "value": 0},
                {"fn": "debt_to_equity", "op": "pct_lte", "value": 50}],
    "score": [{"fn": "momentum", "params": {"months": 6}, "weight": 2, "direction": "high"},
              {"fn": "fcf_yield", "weight": 1, "direction": "high"}],
    "limit": 10,
}


class TranslateUnavailable(Exception):
    pass


def _system() -> str:
    fns = catalog_dict()["functions"]
    lines = [f"- {f['name']} ({f['kind']}, returns {f['returns']}): {f['doc']}" for f in fns]
    ops = ", ".join(o["op"] for o in OPS)
    return (
        "You translate a plain-English stock screen into ONE JSON spec. Output only the JSON object.\n"
        "Shape: {name, description, universe, filters, derived?, score?, context?, limit?}.\n"
        "universe: {\"type\": \"index\", \"index\": \"sp500\"|\"nasdaq100\"|\"nasdaq_all\"}, "
        "{\"type\": \"index_union\", \"indexes\": [\"sp500\", \"nasdaq100\"]} when the request "
        "spans several indexes, {\"type\": \"list\", \"tickers\": [...]}, or a cut of a base "
        "universe: {\"type\": \"sector\", \"sector\": \"Technology\", \"base\": <universe>} or "
        "{\"type\": \"common_equity\", \"base\": <universe>}.\n"
        "If the request names anything you cannot express with the listed fields and "
        "universe forms, do NOT silently drop it: add a top-level \"unhonored\" array of "
        "short strings naming each dropped element. Omit \"unhonored\" when nothing was "
        "dropped.\n"
        f"filters: [{{\"fn\": <field name>, \"params\"?: {{}}, \"op\": <one of: {ops}>, \"value\": <number>}}]. "
        "pct_gte/pct_lte compare against the universe percentile (0-100); gt/gte/lt/lte compare raw values.\n"
        "derived: [{\"name\": <lowercase_id>, \"expr\": \"field_a / field_b\"}] composes NEW ratios from field "
        "names with + - * / and parentheses; filters and score may then use the derived name.\n"
        "score: [{\"fn\": <field or derived name>, \"weight\": <number>, \"direction\": \"high\"|\"low\"}] -- "
        "include a score when the request ranks or asks for the 'best' matches.\n"
        "Fields (name, kind, what it returns):\n" + "\n".join(lines) +
        "\nExample spec:\n" + json.dumps(EXAMPLE) +
        "\nUse only the listed field names; never invent a field — name what you cannot "
        "express in \"unhonored\" instead."
    )


# The disclosure every rules-fallback answer carries (translator rule, Nov
# 2026): a translation that cannot honor a requested element must say so,
# never silently narrow the screen. The rules path reads only a small set of
# phrases, so its spec is served WITH this note, not as if it were the AI's.
RULES_DISCLOSURE = (
    "This spec came from the built-in rules fallback, which reads only a "
    "small set of phrases — it may not cover everything the request named. "
    "Check the cards against the request before running.")


def translate(query: str, *, post=requests.post) -> tuple[dict, str, list[str]]:
    """AI first; on any AI failure the deterministic rules answer instead
    (the prototype's design) and the model name says so. Only a query
    neither path can read raises. The third element is the disclosure
    notes: anything the served spec does NOT honor from the request is
    named there (the model's own "unhonored" list, or the rules
    fallback's standing disclosure) — a translation never silently
    narrows the screen."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        fallback = rules_spec(query)
        if fallback is not None:
            return fallback, "rules (no AI key configured)", [RULES_DISCLOSURE]
        raise TranslateUnavailable("the translator is not configured on the server (OPENROUTER_API_KEY)")
    body = {"models": _models()[:3],  # OpenRouter rejects routes with >3 models
            "messages": [{"role": "system", "content": _system()},
                         {"role": "user", "content": query}]}
    try:
        resp = post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        fallback = rules_spec(query)
        if fallback is not None:
            return fallback, f"rules (AI unavailable: {type(exc).__name__})", [RULES_DISCLOSURE]
        raise TranslateUnavailable(f"the translator failed: {type(exc).__name__}") from exc
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        fallback = rules_spec(query)
        if fallback is not None:
            return fallback, "rules (AI reply was not a spec)", [RULES_DISCLOSURE]
        raise TranslateUnavailable("the translator returned no spec")
    notes: list[str] = []
    try:
        spec = json.loads(content[start:end + 1])
        if isinstance(spec, dict):
            # The model's disclosure rides OUTSIDE the spec (the schema
            # admits no such key); it is stripped before validation and
            # returned as notes.
            unhonored = spec.pop("unhonored", None)
            if isinstance(unhonored, list):
                notes += [f"not honored: {item}" for item in unhonored
                          if isinstance(item, str) and item.strip()]
            elif unhonored is not None:
                notes.append(f"not honored: {unhonored}")
        universe = spec.get("universe") if isinstance(spec, dict) else None
        if isinstance(universe, dict) and "index" not in universe and "id" in universe:
            universe["index"] = universe.pop("id")  # the models' persistent alias for the key
            notes.append("the model's 'id' key was read as the universe index name")
        validate_spec(spec)
    except (json.JSONDecodeError, SpecError) as exc:
        fallback = rules_spec(query)
        if fallback is not None:
            return fallback, "rules (AI spec was refused)", [
                RULES_DISCLOSURE, f"the AI translation was refused: {exc}"]
        raise TranslateUnavailable(f"the translated spec does not validate: {exc}") from exc
    return spec, data.get("model") or "openrouter", notes
