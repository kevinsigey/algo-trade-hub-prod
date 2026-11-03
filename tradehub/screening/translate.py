"""Natural language -> screen spec (Screening A3). The translator runs on the
hub's OpenRouter reasoning-model chain (the Workshop drafter's model list --
Gemini's free daily quota stays reserved for debates and drafting). The
reply is extracted as JSON and MUST pass the same validate_spec every saved
screen passes; a spec that does not validate is an error the user sees, never
a silent fix-up."""

from __future__ import annotations

import json
import os

import requests

from tradehub.screening.catalog import OPS, catalog_dict
from tradehub.screening.spec import SpecError, validate_spec
from tradehub.workshop.draft import _models

URL = "https://openrouter.ai/api/v1/chat/completions"

EXAMPLE = {
    "name": "momentum_quality",
    "description": "Top-quartile 6-month momentum, positive earnings growth, leverage at or below the median.",
    "universe": {"type": "index", "id": "sp500"},
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
        "universe: {\"type\": \"index\", \"id\": \"sp500\"|\"nasdaq100\"|\"nasdaq_all\"} or "
        "{\"type\": \"list\", \"tickers\": [...]}.\n"
        f"filters: [{{\"fn\": <field name>, \"params\"?: {{}}, \"op\": <one of: {ops}>, \"value\": <number>}}]. "
        "pct_gte/pct_lte compare against the universe percentile (0-100); gt/gte/lt/lte compare raw values.\n"
        "derived: [{\"name\": <lowercase_id>, \"expr\": \"field_a / field_b\"}] composes NEW ratios from field "
        "names with + - * / and parentheses; filters and score may then use the derived name.\n"
        "score: [{\"fn\": <field or derived name>, \"weight\": <number>, \"direction\": \"high\"|\"low\"}] -- "
        "include a score when the request ranks or asks for the 'best' matches.\n"
        "Fields (name, kind, what it returns):\n" + "\n".join(lines) +
        "\nExample spec:\n" + json.dumps(EXAMPLE) +
        "\nUse only the listed field names. If the request names something no field measures, leave it out "
        "rather than inventing a field."
    )


def translate(query: str, *, post=requests.post) -> tuple[dict, str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise TranslateUnavailable("the translator is not configured on the server (OPENROUTER_API_KEY)")
    body = {"models": _models(),
            "messages": [{"role": "system", "content": _system()},
                         {"role": "user", "content": query}]}
    try:
        resp = post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        raise TranslateUnavailable(f"the translator failed: {type(exc).__name__}") from exc
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise TranslateUnavailable("the translator returned no spec")
    try:
        spec = json.loads(content[start:end + 1])
        validate_spec(spec)
    except (json.JSONDecodeError, SpecError) as exc:
        raise TranslateUnavailable(f"the translated spec does not validate: {exc}") from exc
    return spec, data.get("model") or "openrouter"
