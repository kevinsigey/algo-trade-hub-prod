"""The AI summary draft (Part B): Kevin's paper structure -- MECE, unit
economics first, Base/Bear/Bull, football field, Catalysts and Risks --
written from the run's own inputs and outputs, and labelled a DRAFT on the
record. Runs on the hub's OpenRouter reasoning chain."""

from __future__ import annotations

import json
import os

import requests

from tradehub.workshop.draft import _models

URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = (
    "You are drafting a research summary for a deal analysis, in the structure of Kevin's "
    "Research Desk papers. It is a DRAFT for a human writer -- say so in the first line. "
    "Structure: 1) The deal in one paragraph. 2) Unit economics first. 3) Valuation football "
    "field (the computed ranges, as text). 4) Scenarios: Base / Bear / Bull with the computed "
    "verdicts. 5) Catalysts. 6) Risks. Use ONLY the numbers in the run record provided; never "
    "invent a figure. Where the record names a missing input, name it as missing."
)


class SummaryUnavailable(Exception):
    pass


def draft_summary(kind: str, name: str, inputs: dict, outputs: dict, *, post=requests.post) -> tuple[str, str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SummaryUnavailable("the summary writer is not configured on the server (OPENROUTER_API_KEY)")
    body = {"models": _models(),
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content":
                          f"Kind: {kind}\nName: {name}\nInputs (as entered):\n{json.dumps(inputs, indent=1)}\n"
                          f"Computed outputs:\n{json.dumps(outputs, indent=1)}"}]}
    try:
        resp = post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0].get("message") or {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        raise SummaryUnavailable(f"the summary failed: {type(exc).__name__}") from exc
    if not content.strip():
        raise SummaryUnavailable("the summary writer returned nothing")
    return content.strip(), data.get("model") or "openrouter"
