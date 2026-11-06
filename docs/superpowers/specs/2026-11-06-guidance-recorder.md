# Guidance recorder — design (Kevin approved 2026-11-06)

## Why
Strategy HQ's edge was guidance against what analysts expected, not reported capex (a 262-event backtest of
capex raises failed, 2026-11-06). There is no free history of guidance, so it cannot be backtested. We record it
from now on, the way the 15-minute rule builds a forward record, and grade it once a season or two exists.

## What it records
For each large-cap earnings release: the guidance the company gave (revenue, EPS, capex ranges for a stated
period), with an exact quote for every number, the analyst consensus at that moment, and later the stock's
reaction. Nothing trades.

## Pipeline
1. **Poll** (`tradehub/guidance/edgar.py`, `scripts/guidance_poll.py`, every 15 minutes on weekdays): for each
   company in the universe, read SEC EDGAR `https://data.sec.gov/submissions/CIK##########.json`; a new 8-K whose
   items include `2.02` (Results of Operations) is an earnings release. Find its press-release exhibit (EX-99.1,
   else the first EX-99.x) in the filing index and store a `guidance_filings` row with status `new`.
2. **Extract** (`tradehub/guidance/extract.py`, `scripts/guidance_extract.py`, same schedule): for each `new`
   filing, fetch the exhibit, turn HTML into text, ask the model for guidance items through a forced tool call,
   **verify** every item, snapshot consensus, write `guidance_records`, set the filing to `extracted`,
   `no_guidance` or `failed`.
3. **Grade** (later): reaction from closes; a page under Strategies once data exists.

## Verification (the part that keeps the record honest)
- Every item carries `evidence`: an exact sentence from the release. It is kept only if the evidence, with
  whitespace and quote marks normalized, appears in the release text, AND every number in low/high appears in the
  evidence (digits compared after removing commas and currency signs; "$9.8 billion" matches 9.8 with unit
  billions). Anything else is dropped and counted on the filing row (`dropped`).
- The model never supplies consensus or reaction; those come from data.
- A release with no forward-looking numbers is `no_guidance`, not an error.

## Tables (one migration, RLS on, no anon or authenticated access; the service role writes)
`guidance_filings`: id, cik text, ticker text, accession text unique, form text, items text, filed_at timestamptz,
doc_url text, status text check in (new, extracted, no_guidance, failed), error text, dropped int default 0,
created_at timestamptz default now(), updated_at timestamptz.

`guidance_records`: id, accession text references guidance_filings(accession), ticker text, period text (as stated,
e.g. "Q1 FY27", "FY2026"), metric text check in (revenue, eps_gaap, eps_adjusted, capex, operating_margin, other),
unit text (usd, usd_per_share, pct), low numeric, high numeric, evidence text, consensus numeric, consensus_period
text, consensus_source text, model text, created_at timestamptz default now().

## Universe
S&P 100 constituents as a list in `tradehub/guidance/universe.py` (ticker -> CIK, from SEC
`https://www.sec.gov/files/company_tickers.json`, cached to the repo list; one share class per company).

## Model and cost
Free models only (Kevin, 2026-11-06: no paid Claude credits for analysis). OpenRouter's free route, the same one the
agent debates and the Workshop draft use (`OPENROUTER_API_KEY`, the shared free list from
`tradehub.workshop.draft._models()`, at most three models per request, JSON-schema response format), with the
release text truncated to 60,000 characters. Free models make more mistakes, which is what the verification step is
for: a number without an exact quote from the release never reaches the record. If no key, the filing stays `new`
and the run says so.

## SEC etiquette
User-Agent from `SEC_USER_AGENT`, default `AlgoTradeHub research hub-research@example.com`; at most 5 requests a
second; a 403 or 429 stops the run and is logged, never retried in a loop.
