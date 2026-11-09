# Valuation Phase 1 — the fork (design note, Nov 9, 2026)

Built to the frozen spec (`valuation-bands-preregistration-draft.md`, Spec v1 +
amendments, incl. §6 relative grading) and the implementation plan's Phase 1.
Kevin's Nov 9 re-brief: valuation merges into the debates engine the way it was
originally designed — integrated, not bolted on.

## The fork

The stock TradingAgents framework has no exhibit channel: `framework_runner.py`
passes it only (ticker, date) and it builds its own state from its own vendors.
So the fork is implemented in-repo, as spec §4 prescribes ("forked and made our
own; Exhibit A is fixed"): `tradehub/valuation/debate_fork.py` re-creates the
TradingAgents flow shape — researchers argue, a structurer turns the argument
into a typed decision problem, a decision seat renders the verdict — with the
valuation fact sheet as the fixed factual core injected verbatim into every
stage. Bulls argue the file is conservative/improving; bears argue the price
implies more than the file. Numbers cited must come from Exhibit A; code
validates the structured packet against the sheet and a mismatch voids the
verdict (spec §4). The classic framework debates stay on the Debates page
beside the valuation cards, and a verdict logs the classic run id for the same
ticker/session when one exists.

## Decision seat (frozen Nov 8, seat behind an interface)

`tradehub/valuation/judge.py`: `DecisionSeat` protocol. Until Kevin loads
OpenRouter credits (reminder Nov 18; the key on file is dead), the seat is the
FREE AI version — the Qwen-class proposer/structurer renders the verdict
itself (`judge = "free-ai-proposer"` on every row). `JevSeat`
(`typesafe/jev-1.13`, OpenRouter Decisions API) drops in behind the same
interface with no schema or caller changes once a credited key exists; Kev is
the designated successor, interface-compatible, not built. Every verdict row
carries which judge rendered it.

## What ships in Phase 1

- Options-layer inputs (spec §3), computed at verdict render and stored on the
  verdict record: implied move vs distance to the next band; expression sketch
  (debit call/put spread with band strikes) only when the implied move
  underprices that distance. Inputs only — nothing is placed.
- `valuation_verdicts` (migration 20261109000004): the rendered verdict, the
  judge identity, BOTH controls (band-rule baseline from the sheet, the
  proposer's own pick), the frozen peer group + each peer's price state at
  render, the fact-sheet id/state, options inputs, falsifier, timestamps.
- Grading skeleton (spec §6; the plan phases the job in Phase 2 — pulled
  forward here as a skeleton per the Nov 9 brief, definitions unchanged):
  `valuation_verdict_grades` at +20/+60 trading days — peer-relative excess
  (primary), index-relative excess, counterfactual peer-median basket,
  entry-path quality (MFE/MAE, time-to-target-band), Brier on the relative
  outcome; the same frozen context grades both controls. The ~40-verdict
  authority gate counts relative passes.
- Cadence (§5): `valuation_watch_state` + `valuation_triggers` — continuous
  watch on held positions (price above bull = potential-sell flag; inside the
  bands = comfortable-hold flag; flags only, never orders), event triggers
  (band crossing, new guidance recorded, print window), on-demand runs from
  the Debates page. §5 priority: crossings/falsifier windows first, new
  guidance next, refresh last; the shared 10/day debate budget caps renders.
- EDGAR frame-selection fix (`DataStore.edgar_concept`): instant concepts pick
  the latest period end regardless of fiscal-period tag (the SBUX cash case:
  fp=FY rows stop at 2021-10-03 while the concept's latest observation is
  2022-07-03); duration concepts pick a true full-year row (fiscal-year tag +
  ~1-year duration); ties break by latest filed date (restatements supersede).

## Authority (spec default, in force)

DISPLAY-ONLY. Verdicts render, log, and grade; they do not feed Workshop
ideas, place or suggest orders, or carry sizing until ~40 graded verdicts
pass the relative bar.
