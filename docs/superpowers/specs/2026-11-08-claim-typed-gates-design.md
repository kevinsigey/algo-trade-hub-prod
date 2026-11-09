# Claim-typed gates — design (Kevin approved 2026-11-08)

**Amendment, same night (2026-11-08, 23:04 CT):** Kevin extended the scope — the
`event` and `overlay` batteries are built in this pass too, not specced only. Their
frozen constants are preregistered below (§Event battery, §Overlay battery) before
the code. Grandfathering is unchanged: the event battery is *reported inside* every
event run while the run's own verdict stays the existing event gate's; the overlay
battery, like the basket battery, judges only ideas that declare it.

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
| `event` | "Around this event class, the name drifts abnormally vs its context." | Per-event excess vs the index and vs matched peers, both frozen at event time; cross-event t and hit rate per span (§Event battery). Runs on the event-study path (`EventSpec` / `run_event_test`), which already computes the per-event reads. | **Live with the amendment.** The battery is reported in every event run's result; the run's headline verdict remains the existing event gate's (grandfathering — §Event battery). `claim_type="event"` on an *IdeaSpec* stays refused on the rule-run path (422): an IdeaSpec has no event windows. |
| `overlay` | "Bolted onto the book, this sleeve improves the combined portfolio." | With-vs-without on the combined portfolio: the run's benchmark blended with the sleeve at a frozen weight; drawdown margin, Sharpe guard, return budget (§Overlay battery). Never standalone return. | **Live with the amendment.** Dispatched in `run_test` like `basket`; requires a `ballast` or `smoother_ride` claim. |

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
- `overlay` requires the claim it answers: `claim` must be `ballast` or
  `smoother_ride` — the two claims that are statements about a host portfolio, not
  about standalone return. Validation rejects any other pairing. Rules and option
  legs stay allowed: a sleeve is graded as specified (a protective-put overlay is
  the canonical case; its legs are model-priced and the run's options block already
  says so).
- `event` is not an IdeaSpec type at all: event studies are declared by their
  `EventSpec` (`kind="event"`) and run on the event-study endpoint. Setting
  `claim_type="event"` on an IdeaSpec is refused (422) with that explanation, not
  graded by the rule engine.

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
   adjustment is defined over the timing family's shuffle p-values; **basket and
   overlay battery runs are exempt from registry demotion** (their stored verdict
   stands in the adjusted view) until a cross-battery FDR treatment is itself
   preregistered. Event runs are *not* exempt: their battery is a reported read
   inside a run whose verdict still comes from the timing-family event gate, so
   they keep flowing through the BH adjustment exactly as before. A battery
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

## Event battery (frozen constants)

Computed inside `run_event_test` from the per-event rows the event engine already
measures — no new data, no new windows. Spans are the event path's own split (by
event day, newest `unseen_fraction` of event days unseen), and every event is
assigned wholly to the span containing its reaction day.

- **Index excess (the judged series):** per event, the signed abnormal return the
  engine already computes — the study's window return minus the benchmark's over
  the identical window, signed by the claimed direction, in %. This is valuation
  §6's index leg, frozen at event time by construction.
- **Peer excess (reported control, not a verdict leg):** per event, the name's
  window return minus the **median window return of the study's other tickers**
  over the identical window — the matched peers are the study's own names, frozen
  at event time because the window is contemporaneous. Reported per span (n,
  mean, cross-event t, hit rate). Not a verdict leg, for the same reason the
  basket battery's equal-weight reference is not: for the canonical single-name
  studies (FOMC drift on SPY) no in-study peer exists, so a peer verdict leg
  would grade the study's ticker list, not its claim. Single-name studies report
  the peer block as n/a.
- **Cross-event significance:** per span, the one-sample t of the signed index
  excess, `mean / (sd/√n)` with sd at ddof=1 — events, not days, are the sample,
  so no block correction is needed across well-separated events. The battery also
  reports the one-sided t p-value on the unseen span as `p` (family log only).
- **Hit rate:** per span, the share of events whose signed index excess is > 0.
- **Frozen bar.** Minimum counts are adopted unchanged from the event engine
  (frozen there since 2026-10-31; a parity test pins the two modules' constants
  together so they cannot drift): **MIN_EVENTS 20** total, **MIN_UNSEEN_EVENTS
  10** — below either, the battery verdict is NOT ENOUGH DATA. PASS requires, on
  the **unseen** span: mean > 0, **t ≥ 2.0**, **hit rate ≥ 0.55**; and on the
  **built** span: mean > 0 with **t ≥ 1.0** (the built span formed the hypothesis,
  so it confirms direction at a lower bar; the verdict bar lives on unseen data).
  FAIL otherwise, with the failing legs named.
- **Cost treatment (inherited, stated):** per-event windows are gross of switch
  costs, exactly as the event gate has always measured them — the event path has
  no cost model. The battery does not change that in this pass; netting event
  windows is a separate preregistration.
- **Grandfathering, applied literally:** the battery rides in the run's result as
  `battery` (both the NOT ENOUGH DATA early return and the full return), and the
  run's own verdict, headline and shuffle remain the existing event gate's,
  untouched. Event runs are not registry-exempt (see core §5). Promoting the
  battery to *be* the event verdict is a re-registration decision for Kevin, not
  something this build does silently.

## Overlay battery (frozen constants)

Computed per span (built, unseen) in `run_test` for `claim_type="overlay"`, from
the same daily frame as every other battery. The host is the run's benchmark —
the portfolio the sleeve would accompany, in the only terms the Workshop can
measure — and the combined series is built once, from the two return series:

- **Combined series:** `c = (1 − W) × benchmark + W × idea`, daily, with
  **SLEEVE_WEIGHT W = 0.20** frozen. A sleeve is a minority allocation: a fifth
  of the book is the smallest share at which protection is measurable at
  portfolio scale, and the largest that leaves the host dominant. Both series
  are already net of the idea's house costs; the benchmark is costless, as
  everywhere in the core. Nothing is double-counted: the blend is one series,
  computed once.
- **Per span, host vs combined:** Sharpe (annualized, the house convention),
  max drawdown and CAGR, in points where the quantity is a percent.
- **Frozen bar, per span** (must hold on **both** spans):
  - **Drawdown margin:** `|maxDD_host| − |maxDD_combined| ≥ 3.0` points
    (**DD_MARGIN_PP**). When the host's span drawdown is under **5.0** points
    (**DD_MIN_HOST_PP**, the basket battery's convention) there was no fall to
    protect against: the leg is recorded not-binding and does not gate.
  - **Sharpe guard:** combined Sharpe ≥ host Sharpe − **0.05**
    (**SHARPE_TOLERANCE**) — protection may not be bought with a meaningfully
    worse risk-adjusted ride.
  - **Return budget:** host CAGR − combined CAGR ≤ **2.0** points/yr
    (**RETURN_BUDGET_PP**) — the most return the sleeve may give back.
- **Verdict:** PASS iff every binding leg holds on both spans (the shared
  504-unseen-day gate fires upstream, as for every battery). FAIL otherwise,
  with the failing legs named. The sleeve's standalone numbers appear only in
  the shared `claim`/`context` blocks, as context — never as legs.
- **Result shape:** identical discipline to the basket battery — the timing
  result's top-level keys, `shuffle`/`t_test` null, `claim_type: "overlay"`,
  and `battery`: `{type, constants, spans: {built, unseen} (host vs combined),
  legs, verdict}`. Registry treatment matches basket (exempt; core §5).

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

With the amendment, two more demonstrations, both additional runs, both reported
only: idea 65 (Post-FOMC drift — a PASS under the existing event gate) re-run on
the event path so its new run carries the event battery's read beside the gate's;
and idea 61 (W18, a `smoother_ride` frozen basket — the support sleeve) re-run
with `claim_type="overlay"`. Neither idea's state changes.

---

## Amendment 2 (2026-11-08, 23:35 CT): the event battery takes over, and the FOMC event source is corrected

Kevin's ruling, same night: *"things should measure with their best measure so
if battery is accurate it should take over and fix the quirk."* Two changes,
both preregistered here before the code. This amendment supersedes, for event
runs only: the taxonomy table's event row ("the run's headline verdict remains
the existing event gate's"), core §5's event paragraph, the Event battery's
"Grandfathering, applied literally" paragraph, and the Grandfathering section's
registry sentence as it applies to event runs. Everything else stands.

### 1. Promotion: the battery's verdict IS the event verdict

- For every new event run, the run's headline `verdict` (and the stored
  `idea_runs.verdict`) is the **event battery's verdict** (`battery.verdict`).
  The battery was the accurate instrument for the claim all along: it judges
  the signed per-event excess directly (cross-event t, hit rate, both spans),
  where the old gate judged a mean against random dates — a timing question
  wearing an event study's clothes.
- The headline follows the battery: PASS → the house pass headline; FAIL with
  the built-span direction leg holding → the overfit headline; FAIL without it
  → the fail headline; NOT ENOUGH DATA → the nodata headline and the engine's
  reason, exactly as today.
- **The old gate is preserved as a named control, never deleted.** Its complete
  verdict record — `verdict`, `headline`, `claim`, `shuffle`, `t_test`,
  `periods` — is computed exactly as before and stored in the result as
  **`legacy_event_gate`**, so old-vs-new stays comparable on every future run.
  On the NOT ENOUGH DATA early return the old gate never ran, and
  `legacy_event_gate` is null — the record says so rather than implying it did.
- Top-level result discipline (the basket/overlay rule): `shuffle`, `t_test`
  and `periods` at top level become **null** — the judging instrument is the
  battery, and the record must not present the control's numbers as the
  judge's. The descriptive `claim` block (built/unseen mean moves) stays at
  top level, as it does for basket runs, and the battery's legs and spans are
  the verdict's evidence. `per_ticker`, `events`, `n_events`, `context`,
  `curve` are unchanged.
- **Grandfathering is unchanged in kind:** stored runs keep their recorded
  verdicts; no idea's lifecycle state changes; promotion applies to new runs.

### 2. Multiple-testing accounting under promotion

- The registry's BH family p for an event run is now **the battery's p**
  (`result.battery.p`, the one-sided cross-event t p on the unseen span) when
  the run carries an event battery — the p of the instrument that rendered the
  verdict is the p that answers for it in the family. A run whose battery is
  NOT ENOUGH DATA carries `p = null` and stays out of the family, exactly as a
  null shuffle p did.
- Pre-promotion stored event runs carry no battery block; they keep their
  legacy shuffle p in the family — their verdict *was* the shuffle's, so its p
  is still the honest accounting for them.
- Nothing else in `registry.adjusted` changes. In particular the walk-forward
  leg still reads `walk_forward`, which event results have never carried, so a
  saved event PASS's `verdict_now` continues to be demoted on that leg — the
  same treatment the legacy gate's PASSes received; promotion changes the
  verdict and the family p, not the standing rule. Making the battery's own
  durability legs (built direction, unseen hit rate) the event standing rule
  is a cross-battery standing treatment: **an open item for Kevin's
  preregistration, deliberately not improvised here.** A battery PASS
  therefore still cannot feed a go-live decision, as before.

### 3. The FOMC quirk, diagnosed and fixed

**Diagnosis.** Idea 65's study counted 3,145 "events" because its source was
FRED release 101's *release-date list*. Release 101 is indeed named "FOMC
Press Release", but the only series it contains are the **daily** federal
funds target-range series (DFEDTARU / DFEDTARL, and the discontinued
DFEDTAR) — and a FRED release-date list holds, in ALFRED's own words, "the
dates when any series from this release was revised". A daily series is
revised every business day, so the "FOMC calendar" the engine consumed was
**every business day** (~250/year from 2019 on; verified in run 91's stored
events: every weekday of Jan–Feb 2024 is present). The study was measuring
drift after arbitrary days, and both the old gate's PASS and the battery's
t 6.23 were computed on that non-event set. CPI (release 10) and jobs
(release 50) do not share the defect: their releases contain monthly series
and their date lists are the monthly publication dates (verified against the
live API in the same pass: 12/year each). Earnings dates are per-ticker
reported prints (~4/year by construction) and gap/custom events derive from
prices or the user's own rows — no other event type carries a calendar of
the wrong frequency.

**The corrected source.** FOMC events are the **statement dates of FOMC
meetings**, frozen in `tradehub/workshop/fomc_calendar.py`, transcribed from
the Federal Reserve's published meeting calendars (the current calendars
page for 2021–2027, the Historical Materials year pages for 2010–2020) on
2026-11-08:

- The statement date is the meeting's last day (statements issue at 14:00
  New York; each date is timestamped 14:00 and the engine's standing noon
  rule assigns the reaction day — the next trading day — uniformly, as it
  does for every afternoon release). One documented exception: the
  2020-03-03 emergency cut was released at 10:00 and is timestamped so.
- **Included:** all scheduled meetings, plus unscheduled meetings and
  statement-bearing conference calls (2010-05-09 swap-lines call,
  2019-10-11 statement of the Oct 4 meeting, 2020-03-03 and 2020-03-15).
- **Excluded, by the same rule:** gatherings with no statement (the
  2010-10-15, 2011-08-01, 2011-11-28, 2013-10-16 and 2014-03-04 calls), the
  cancelled 2020-03-17/18 meeting, and **notation-vote statements**
  (2020-03-23, 2020-08-27, 2025-08-22) — announcements without a meeting are
  a different event class; adding them is a new preregistration, not a fix.
- The table runs 2010–2027 (2027 as scheduled at transcription). A test pins
  its shape: 8 statement dates in a normal year, 9 in 2010, 2019 and 2020 —
  139 over 2010–2026 — so a future edit that breaks the frequency fails CI.
  Maintenance is extending the table from the Fed's calendar as new years
  are published; the FRED release list is never used for FOMC again.
  `RELEASES` keeps only `cpi` and `jobs`.
- **Idea 65 is re-run** on the corrected list, as a new run (an unsaved
  preview, like tonight's other demonstrations — evidence, not a state
  change), and the old-vs-new record is reported: 3,145 pseudo-events vs the
  true meetings, the promoted battery's verdict and numbers on the corrected
  set. Whatever it says is the report.
