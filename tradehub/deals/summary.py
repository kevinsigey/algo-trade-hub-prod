"""The AI summary (Part B), structured (Kevin, 2026-11-03): the writer
returns a JSON document -- headline, sections with paragraphs / bullets /
tables, takeaway -- in Kevin's paper structure (MECE, unit economics
first, Base/Bear/Bull, football field, Catalysts and Risks), and the
Deals page renders it with real components. Raw markdown in a <pre> is
the thing this replaces. A reply that will not parse still renders: it
falls back to cleaned paragraphs, never to raw markup.

The DRAFT label lives in the UI now (the summary header says so), so
the document itself no longer spends its first line on it. Storage is
the same deal_runs.summary text column, holding the JSON document;
rows written before this change hold plain text and are wrapped into
the same document shape on read (doc_from_stored).
"""

from __future__ import annotations

import json
import os
import re

import requests

from tradehub.workshop.draft import _models

URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = (
    "You are drafting a research summary for a deal analysis, in the structure of Kevin's "
    "Research Desk papers. It is a DRAFT for a human writer. Respond with ONLY a JSON object "
    "(no markdown, no code fences) of this exact shape: "
    '{"headline": string, "sections": [{"title": string, "paragraphs": [string], '
    '"bullets": [string], "table": {"columns": [string], "rows": [[string]]} or null}], '
    '"takeaway": string}. '
    "Sections, in order: 1) The deal. 2) Unit economics. 3) Valuation (the football field -- "
    "use a table with the computed ranges). 4) Scenarios (Base / Bear / Bull -- use a table "
    "with the computed verdicts). 5) Catalysts (bullets). 6) Risks (bullets). Use ONLY the "
    "numbers in the run record provided; never invent a figure. Where the record names a "
    "missing input, name it as missing. Every table cell is a string."
)


class SummaryUnavailable(Exception):
    pass


def _clean_section(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    def strs(v: object) -> list[str]:
        return [str(x) for x in v if x is not None] if isinstance(v, list) else []

    table = None
    t = raw.get("table")
    if isinstance(t, dict) and isinstance(t.get("columns"), list) and isinstance(t.get("rows"), list):
        table = {"columns": [str(c) for c in t["columns"]],
                 "rows": [[str(c) for c in row] if isinstance(row, list) else [str(row)]
                          for row in t["rows"]]}
    return {"title": title.strip(), "paragraphs": strs(raw.get("paragraphs")),
            "bullets": strs(raw.get("bullets")), "table": table}


def parse_summary_doc(content: str) -> dict | None:
    """The model's JSON, validated and coerced into the document shape.
    None when it is not that document (the caller falls back)."""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("headline"), str):
        return None
    sections = [s for s in (_clean_section(x) for x in doc.get("sections") or []) if s]
    if not sections:
        return None
    takeaway = doc.get("takeaway")
    return {"headline": doc["headline"].strip(),
            "sections": sections,
            "takeaway": takeaway.strip() if isinstance(takeaway, str) else ""}


def fallback_doc(text: str) -> dict:
    """A non-JSON reply (or a legacy stored summary) as a document: the
    markdown decoration stripped, paragraphs split on blank lines."""
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+)", "", raw).strip()
        line = line.replace("**", "").replace("__", "")
        lines.append(line)
    paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = ["The summary writer returned nothing usable."]
    headline = paragraphs[0].split("\n")[0][:140]
    return {"headline": headline,
            "sections": [{"title": "Summary", "paragraphs": paragraphs, "bullets": [], "table": None}],
            "takeaway": ""}


def doc_from_stored(stored: str | None) -> dict | None:
    """What the page renders for a stored summary: the JSON document if
    that is what is stored, the legacy text wrapped, or None."""
    if not stored or not stored.strip():
        return None
    return parse_summary_doc(stored) or fallback_doc(stored)


def draft_summary(kind: str, name: str, inputs: dict, outputs: dict, *, post=requests.post) -> tuple[dict, str]:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SummaryUnavailable("the summary writer is not configured on the server (OPENROUTER_API_KEY)")
    body = {"models": _models()[:3],  # OpenRouter rejects routes with >3 models (live-verified 400)
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
    doc = parse_summary_doc(content) or fallback_doc(content)
    return doc, data.get("model") or "openrouter"
