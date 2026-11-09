# Claim-typed gates — design (Kevin approved 2026-11-08)

## Why

The Workshop has one gate, and it judges every idea's claim as a **timing** claim: a rule
idea gets random-timing shuffles, a rule-less idea gets a paired sign-flip test of its per-day
excess. That is the right instrument for "my rule gets in at the right times" and the wrong
instrument for "this allocation outperforms" — a permanent basket has no timing to shuffle.
On 2026-11-08 the two Mag 7 trackers (ideas 69/70) made the flaw concrete: +7,071% and
+7,869% against SPY +616% and QQQ +1,088% over 2012–2026, and both FAILed with the headline
"no better than random timing" — a true statement about a question nobody asked.

The same night, on the valuation side, Kevin ruled that grading must be **relative to the
context frozen at decision time** (valuation spec §6: peer-median excess primary, index
excess beside it, a counterfactual basket as the opportunity-cost control, entry-path
quality). This design brings that ruling to the Workshop: one measurement core that applies
all round, and a verdict battery assembled per claim type.

## The answer to "one gate or many"

- **The core applies all round.** Frozen context, benchmark-relative (excess) measurement,
  the idea's series net of house costs against costless references, the 504-unseen-day
  minimum, walk-forward durability reads, and hub-wide multiple-testing accounting are
  measurement upgrades, not verdict choices. Every battery below is built from them.
- **The verdict battery is claim-typed.** Every idea spec declares `claim_type`; the gate
  assembles the battery for that type. An idea is graded on the question it actually asks.

## Claim taxonomy

| claim_type | The claim | Battery | Status |
|---|---|---|---|
| `timing` | "My rule / entry-exit logic beats the benchmark beyond chance timing." | The existing gate, **unchanged** (mask shuffle for rule ideas, sign-flip for rule-less ones; verdict_of with walk-forward + registry bars). | Live; the default for every existing idea. |
| `basket` | "This always-in allocation outruns its benchmark, after costs, without falling into a deeper hole." | **New, built in this pass** (§Basket battery). | Live with this change. |
| `event` | "Around this event class, the name drifts abnormally vs its context." | Per-event excess vs matched peers/index frozen at event time, cross-event significance, hit rate. The event-study path (`events.py`) already computes per-event reads; the typed battery formalizes its verdict. | **Design only in this pass.** `claim_type="event"` on an IdeaSpec is stored, but the rule-run path refuses it (422): event ideas run through the event-study endpoint. |
| `overlay` | "Bolted onto the book, this sleeve improves the combined portfolio." | With-vs-without comparison on the combined portfolio (Sharpe and max-DD deltas), never standalone return. | **Design only in this pass.** Stored, refused on the rule-run path (422). |

`claim_type` lives on `IdeaSpec` (default `"timing"`, a Literal, so it is validated,
stored in every run's spec JSON, and surfaced wherever the spec is read). No database
migration: specs are JSON on `idea_runs`.

**Anti-gate-shopping rules** (the taxonomy is a declaration, not a menu):

- `basket` requires the allocation itself to be the claim: `claim` must be
  `beats_benchmark`, and the spec must carry **no rules and no option legs** — an
  enter/exit rule is a timing claim wearing allocation clothes, and option legs are
  model-priced timing claims in this pass. Validation rejects the combination.
- An existing idea keeps `timing` unless Kevin re-registers it. Switching type is a
  re-registration, not an edit: it happens by running the idea under the new type, in
  the open, where the run record shows both.
- `event` / `overlay` declarations are data until their batteries are preregistered
  and built; the run path refuses them loudly rather than grading them with the
  wrong instrument.

## The common core (all batteries)

1. **Frozen context.** The run's benchmark, spans, and cost defaults are fixed at run
   time and stored on the run. Grading never reaches for a benchmark chosen later.
2. **Relative measurement.** The primary quantity is the excess series
   `log1p(idea) − log1p(benchmark)` per day — the same terms the timing gate's
   sign-flip already uses — judged against the run's own benchmark over the identical
   window. Raw return is context, never the verdict.
3. **Cost realism.** The idea's series is net of the spec's house costs
   (`cost_bps` + `slippage_bps` per switch, borrow on shorts). Benchmarks and
   reference baskets are costless, so every comparison is conservative.
4. **Unseen minimum.** The claim is judged on the unseen span (the last
   `unseen_fraction` of the common range); under 504 unseen trading days the verdict
   is NOT ENOUGH DATA, whichever battery runs. This gate fires before dispatch.
5. **Multiple-testing accounting.** Every run — any idea, any battery — is inserted
   through `store.insert_run`, which stamps the hub-wide test number: every
   idea×battery run counts in the family log. The registry's Benjamini-Hochberg
   adjustment is defined over the timing family's shuffle p-values; battery runs are
   **exempt from registry demotion** (their stored verdict stands in the adjusted
   view) until a cross-battery FDR treatment is itself preregistered. A battery
   PASS therefore cannot feed a go-live decision until that treatment exists —
   see Grandfathering.

## Basket battery (frozen constants)

Computed per span (built, unseen) from the engine's daily frame. The idea's series is
the one `run_test` already builds (rules/exits/portfolio blending applied — for a
basket-typed spec there are no rules, but exits and a portfolio core are part of the
allocation as specified and stay in the series).

- **Relative series:** `x = log1p(r_idea) − log1p(r_bench)`, daily.
- **Relative Sharpe:** `mean(x) / std(x, ddof=1) × √252`.
- **Significance:** circular **block bootstrap** of `x` — block length **21** trading
  days, **2,000** resamples, seed = the run's seed + 7919 (frozen offset). The 95%
  percentile CI of the bootstrap relative Sharpes must **exclude 0 on the built span
  AND on the unseen span**. The battery also reports
  `p = (1 + #{bootstrap Sharpe ≤ 0}) / (1 + 2000)` per span (a one-sided bootstrap
  p-analogue, for the family log — not fed to the registry's BH family).
- **Drawdown bound:** per span, `|maxDD_idea| ≤ 1.25 × |maxDD_bench|` (frozen ratio:
  a concentrated allocation may fall a quarter further than its index, not without
  limit). When the benchmark's span drawdown is under 5 points the leg is recorded
  **not binding** and does not gate (a ratio against a near-zero denominator is
  noise). The bound must hold (or be not-binding) on **both** spans.
- **Equal-weight reference (reported, not a verdict leg):** the equal-weight basket
  of the same legs (unique tickers, same signs, always-in, costless) over the same
  spans: excess CAGR of the idea over it, its relative Sharpe and bootstrap CI.
  This is the counterfactual control — "you could have just held the legs equally".
  Reported as **n/a** when the idea *is* its own equal-weight basket (unique long
  legs held once each, no shorts, no portfolio blend) or has fewer than 2 unique
  legs. For a portfolio-blended spec it is computed on the sleeve's legs and
  labelled sleeve-level context.
- **Verdict:** PASS iff both CI legs hold and both drawdown legs hold (the unseen
  minimum already fired upstream). FAIL otherwise, with the failing legs named in
  the battery block. NOT ENOUGH DATA only via the shared unseen gate.
- **Result shape:** the run result keeps the timing result's top-level keys
  (`claim` carries the excess-CAGR reads, `context` and `curve` are unchanged,
  `walk_forward` still reports the claim's excess-CAGR folds as a durability read),
  sets `shuffle` and `t_test` to null (neither was run — the record must not imply
  they were), and adds `battery`: `{type, constants, spans: {built, unseen},
  ew_reference, p, legs: [{name, holds, detail}]}` plus `claim_type` at top level.

## Event battery (design only)

Per event (earnings print, FOMC/CPI/jobs release, gap): the name's abnormal return
over the preregistered window, minus the matched peer median and the index over the
identical window, both frozen at event time (valuation §6's peer-relative rule,
applied per event). Verdict from the cross-event distribution: mean abnormal excess
with a cross-event t / bootstrap CI excluding 0, hit rate reported, minimum event
count in place of the unseen-days minimum. The existing event-study engine already
produces per-event reads; what remains to build is the typed verdict assembly and
its frozen peer sets.

## Overlay battery (design only)

An overlay is graded only in combination: run the host portfolio (or benchmark
sleeve) with and without the overlay over identical spans; the claim holds when the
combined series' Sharpe improves and/or its max drawdown shrinks by a preregistered
margin, with the overlay's standalone return reported as context and never judged.
Costs double-counted nowhere: the combined series is built once, from legs.

## Grandfathering (hard rule)

- Existing ideas keep their original gate and lifecycle state. Nothing in this
  change re-grades the book.
- A run under a new battery is an **additional** run. Its verdict is reported; it is
  never auto-applied to an idea's status, standing, or lifecycle. The registry's
  adjusted view leaves battery verdicts as stored (above).
- An idea adopts a non-`timing` claim type only when the field is explicitly set on
  a new run's spec (new ideas) or when Kevin re-registers it (existing ideas).
- Go-live, tracking, and the live-paper gate are untouched in this pass: they read
  the timing family's record exactly as before. A basket PASS is evidence for
  Kevin's decision, not an input to any automated gate, until a follow-up
  preregistration says otherwise.

## Demonstration (this pass)

Ideas 69 and 70 — the Mag 7 trackers, still drafts, never tracked or live — are
re-run with `claim_type="basket"` set on their run specs (both benchmark
variations), and the old-gate vs new-gate verdicts reported side by side with the
battery's numbers. If the honest basket verdict is still FAIL, FAIL is the report:
the framework's job is to measure the right thing, not to pass the trackers.
