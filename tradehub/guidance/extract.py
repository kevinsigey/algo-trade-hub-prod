"""Guidance extraction from SEC earnings releases.

Step 2 of the guidance recorder pipeline: fetch the press-release exhibit,
turn HTML into plain text, ask the model for guidance items through a forced
tool call, verify every item, snapshot consensus, write guidance_records,
and mark the filing extracted / no_guidance / failed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any, ClassVar, Literal

import requests
from pydantic import BaseModel, Field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TEXT_CHARS = 60_000


class _HtmlToTextParser(HTMLParser):
    """HTMLParser that extracts text, dropping scripts/styles, turning block tags into newlines."""

    BLOCK_TAGS: ClassVar[set[str]] = {
        "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "ul", "ol", "table", "tr", "td", "th", "blockquote",
        "section", "article", "header", "footer", "main", "aside",
        "nav", "pre", "hr",
    }

    def __init__(self):
        super().__init__()
        self._in_script = 0
        self._in_style = 0
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._in_script += 1
        elif tag == "style":
            self._in_style += 1
        elif tag in self.BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = max(0, self._in_script - 1)
        elif tag == "style":
            self._in_style = max(0, self._in_style - 1)
        elif tag in self.BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_script == 0 and self._in_style == 0:
            self._text_parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._text_parts)
        # collapse runs of whitespace (spaces, tabs, newlines) to a single space
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Convert HTML to plain text using stdlib html.parser.

    Drops <script> and <style> content. Block tags become line breaks.
    Collapses runs of whitespace to a single space.
    """
    parser = _HtmlToTextParser()
    parser.feed(html)
    return parser.get_text()


class GuidanceItem(BaseModel):
    """A single guidance item extracted from a release."""

    period: str
    metric: Literal["revenue", "eps_gaap", "eps_adjusted", "capex", "operating_margin", "other"]
    unit: Literal["usd", "usd_per_share", "pct"]
    scale: Literal["units", "thousands", "millions", "billions"]
    low: float | None = None
    high: float | None = None
    evidence: str


class Envelope(BaseModel):
    """Model reply envelope for guidance extraction."""

    no_guidance: bool
    items: list[GuidanceItem] = Field(default_factory=list)
    model: str = ""


_SCALE_FACTORS = {
    "units": 1,
    "thousands": 1e3,
    "millions": 1e6,
    "billions": 1e9,
}


def to_base(value: float | None, scale: str) -> float | None:
    """Convert a value from the given scale to base units (multiply by scale factor)."""
    if value is None:
        return None
    factor = _SCALE_FACTORS.get(scale, 1)
    return value * factor


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, curly quotes to straight, collapse whitespace."""
    text = text.lower()
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_NUMBER_TOKEN_RE = re.compile(r"[\d,]+\.?\d*")


def _number_tokens(text: str) -> list[float]:
    """Extract number tokens from text (digits with optional commas and decimal point)."""
    tokens = []
    for m in _NUMBER_TOKEN_RE.finditer(text):
        num_str = m.group().replace(",", "")
        try:
            tokens.append(float(num_str))
        except ValueError:
            pass
    return tokens


def verify(items: list[GuidanceItem], text: str) -> tuple[list[GuidanceItem], int]:
    """Verify items against the release text.

    Keeps an item only if:
    - Its normalized evidence is a substring of the normalized text
    - Every non-None low/high value equals some number token in the evidence (as float, abs diff < 1e-9)

    Returns (kept_items, dropped_count).
    """
    norm_text = _normalize(text)
    kept: list[GuidanceItem] = []
    dropped = 0

    for item in items:
        norm_evidence = _normalize(item.evidence)

        # Check evidence is in text
        if norm_evidence not in norm_text:
            dropped += 1
            continue

        # Check low/high numbers appear in evidence
        evidence_numbers = _number_tokens(norm_evidence)
        ok = True
        for val in (item.low, item.high):
            if val is not None and not any(abs(val - n) < 1e-9 for n in evidence_numbers):
                ok = False
                break
        if ok and _names_metric(item, norm_evidence):
            kept.append(item)
        else:
            dropped += 1

    return kept, dropped


# The quote has to say what the number is. A free model filed a dividend sentence as capex (2026-11-06); a number in
# the right sentence under the wrong label passes the quote check, so the label is checked against the words too.
METRIC_WORDS = {
    "revenue": ("revenue", "sales"),
    "eps_gaap": ("earnings per share", "eps", "per diluted share", "per share"),
    "eps_adjusted": ("earnings per share", "eps", "per diluted share", "per share"),
    "capex": ("capital expenditure", "capex", "capital spending", "capital investment"),
    "operating_margin": ("margin",),
}


def _names_metric(item: GuidanceItem, norm_evidence: str) -> bool:
    if "dividend" in norm_evidence:
        return False
    words = METRIC_WORDS.get(item.metric)
    return words is None or any(w in norm_evidence for w in words)


def stored_values(item: GuidanceItem) -> tuple[float | None, float | None]:
    """Low and high in base units. Per-share and percentage figures are never scaled, whatever scale the model
    gave: a free model labelled a $13.95 EPS guide "billions" (2026-11-06)."""
    per_share = item.metric.startswith("eps") or item.unit in ("usd_per_share", "pct")
    scale = "units" if per_share else item.scale  # BMY's EPS came back as unit "usd", scale billions
    return to_base(item.low, scale), to_base(item.high, scale)


def cleaned(item: GuidanceItem) -> GuidanceItem:
    """Labels fixed from the quote's own words: EPS is per share, and "non-GAAP" or "adjusted" EPS is adjusted
    (a free model filed Arista's non-GAAP per-share guide as GAAP, 2026-11-06)."""
    if not item.metric.startswith("eps"):
        return item
    words = _normalize(item.evidence)
    metric = "eps_adjusted" if ("non-gaap" in words or "adjusted" in words) else item.metric
    return item.model_copy(update={"metric": metric, "unit": "usd_per_share", "scale": "units"})


def dedupe(items: list[GuidanceItem]) -> list[GuidanceItem]:
    """One item per (period, metric, unit, low, high): the model sometimes repeats an item."""
    seen, out = set(), []
    for it in items:
        key = (it.period.strip().lower(), it.metric, it.unit, it.low, it.high)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def wants_consensus(item: GuidanceItem) -> bool:
    """Street consensus is total revenue in dollars and adjusted EPS: only those are compared against it."""
    return (item.metric == "revenue" and item.unit == "usd") or item.metric == "eps_adjusted"


SYSTEM_PROMPT = (
    "Extract only forward-looking guidance the company gives for a future period "
    "(not reported results). Produce one item per metric and period. "
    "For each item, include low and high exactly as written with the scale word "
    "given separately. The evidence field must be an exact sentence or clause copied "
    "from the text. If there is no forward-looking guidance, set no_guidance to true."
)


def _envelope_tool_schema() -> dict:
    """Generate the tool input schema for record_guidance (Envelope without model field)."""
    schema = Envelope.model_json_schema()
    if "properties" in schema and "model" in schema["properties"]:
        del schema["properties"]["model"]
    if "required" in schema and "model" in schema["required"]:
        schema["required"].remove("model")
    return schema


def _parse_openrouter_response(content: str) -> Envelope:
    """Parse OpenRouter response content which may have prose around JSON."""
    try:
        return Envelope.model_validate_json(content)
    except Exception:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        return Envelope.model_validate_json(content[start:end + 1])


def ask_model(text: str, *, key: str, post: Callable[..., Any] = requests.post) -> Envelope:
    """Free models only (Kevin, 2026-11-06): OpenRouter's free route with the shared list the agent debates and
    the Workshop draft use. No paid model is ever called, and the key only ever goes to OpenRouter."""
    from tradehub.workshop.draft import _models

    if not key:
        raise ValueError("OPENROUTER_API_KEY is required")
    body = {
        "models": _models()[:3],  # OpenRouter rejects routes with more than three models
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": text[:MAX_TEXT_CHARS]}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "Guidance", "strict": False, "schema": _envelope_tool_schema()}},
    }
    resp = post(OPENROUTER_URL, headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json=body, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "content_filter":
        raise RuntimeError("model refused to extract guidance")
    content = (choice.get("message") or {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("model returned no guidance")
    env = _parse_openrouter_response(content)
    env.model = data.get("model") or body["models"][0]
    return env


def consensus(
    ticker: str,
    metric: str,
    period: str,
) -> tuple[float | None, str | None, str | None]:
    """Default consensus implementation using yfinance.

    Returns (value_in_base_units, row_label, "yfinance") or (None, None, None) on error.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None, None, None

    try:
        tk = yf.Ticker(ticker)

        # Determine row: "0q" for quarterly (Q in period), else "0y" for annual
        row_label = "0q" if "Q" in period.upper() else "0y"

        if metric == "revenue":
            estimates = tk.revenue_estimate
        elif metric in ("eps_gaap", "eps_adjusted"):
            estimates = tk.earnings_estimate
        else:
            # capex, operating_margin, other -> no consensus available
            return None, None, None

        if estimates is None or estimates.empty:
            return None, None, None

        # Get the 'avg' column for the row
        if row_label not in estimates.index:
            return None, None, None

        avg_val = estimates.loc[row_label, "avg"]
        if avg_val is None:
            return None, None, None

        # yfinance returns values in base units (USD), no scale conversion needed
        return float(avg_val), row_label, "yfinance"

    except Exception:  # noqa: BLE001 -- yfinance can raise various errors
        return None, None, None


def run(
    supa,
    *,
    fetch: Callable[[str], str],
    model: Callable[[str], Envelope],
    consensus: Callable[[str, str, str], tuple[float | None, str | None, str | None]],
    key: str,
    limit: int = 10,
) -> dict:
    """Process new guidance_filings rows, extract guidance, and write records.

    Returns a summary dict with counts: extracted, no_guidance, failed, records, dropped.
    If key is empty, returns {"skipped": "no model key", "waiting": count_of_new} and changes nothing.
    """
    if not key:
        # Count filings with status "new"
        result = supa.table("guidance_filings").select("accession").eq("status", "new").execute()
        waiting = len(result.data or [])
        return {"skipped": "no model key", "waiting": waiting}

    # Get up to 'limit' filings with status "new"
    filings_result = (
        supa.table("guidance_filings")
        .select("*")
        .eq("status", "new")
        .limit(limit)
        .execute()
    )
    filings = filings_result.data or []

    counts = {"extracted": 0, "no_guidance": 0, "failed": 0, "records": 0, "dropped": 0}

    for filing in filings:
        accession = filing["accession"]
        ticker = filing["ticker"]
        doc_url = filing["doc_url"]

        try:
            # Fetch and convert HTML to text
            html = fetch(doc_url)
            text = html_to_text(html)

            # Ask model for guidance
            env = model(text, key=key)

            if env.no_guidance or not env.items:
                supa.table("guidance_filings").update({"status": "no_guidance"}).eq("accession", accession).execute()
                counts["no_guidance"] += 1
                continue

            # Verify items against text
            kept, dropped = verify(env.items, text)
            kept = dedupe([cleaned(it) for it in kept])
            counts["dropped"] += dropped

            if not kept:
                supa.table("guidance_filings").update({"status": "no_guidance", "dropped": dropped}).eq("accession", accession).execute()
                counts["no_guidance"] += 1
                continue

            # Insert guidance_records for each kept item
            for item in kept:
                cons_value, cons_period, cons_source = (consensus(ticker, item.metric, item.period)
                                                        if wants_consensus(item) else (None, None, None))
                record = {
                    "accession": accession,
                    "ticker": ticker,
                    "period": item.period,
                    "metric": item.metric,
                    "unit": item.unit,
                    "low": stored_values(item)[0],
                    "high": stored_values(item)[1],
                    "evidence": item.evidence,
                    "consensus": cons_value,
                    "consensus_period": cons_period,
                    "consensus_source": cons_source,
                    "model": env.model,
                }
                supa.table("guidance_records").insert(record).execute()
                counts["records"] += 1

            # Update filing status
            supa.table("guidance_filings").update(
                {"status": "extracted", "dropped": dropped}
            ).eq("accession", accession).execute()
            counts["extracted"] += 1

        except Exception as exc:  # noqa: BLE001 -- any exception marks filing as failed
            error_msg = str(exc)[:300]
            supa.table("guidance_filings").update(
                {"status": "failed", "error": error_msg}
            ).eq("accession", accession).execute()
            counts["failed"] += 1

    return counts