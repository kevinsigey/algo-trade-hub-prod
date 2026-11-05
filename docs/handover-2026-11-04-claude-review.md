# For Claude: review of Muse's Nov 4 work — what Kevin asked, what Muse made of it, and Kevin's instruction to you

Written Wed Nov 4, 2026 ~22:50 CT at Kevin's request. This is a review
brief, not a status handover — for standing state and open decisions read
`docs/handover-2026-11-04-muse.md` (PR #374), which this file does not
repeat. Live code tag: `096daf3db70`.

## Kevin's instruction to you (his words, Nov 4 ~22:50 CT)

> "do a another handover file so that claude knows exactly what to
> review, tell it what i asked you tod, what you interpreted and did and
> ask it what itt would different and to go ahead and make that
> improvement"

So: **review the work below, state plainly what you would have done
differently, and go ahead and make those improvements.** That is Kevin's
authorization for improvements to the Nov 4 work listed here. The standing
rules still bind: paper only, one PR at a time pinned to its head, failing
test first, full gates on the exact shipped tree, deploy = workflow
conclusion + TRADEHUB_TAG + live probe, and anything outside today's work
(idea on/off or resizing, PASS verdict changes, the rebalance) still waits
for Kevin's own yes.

## What Kevin asked Muse today, in his words

1. **Nov 3 ~23:19 CT** (the takeover order, relayed with your handover):
   "(1) find the best live price from the get-go — do NOT force the Pyth
   runaround; (2) build the 15-minute model; (3) build more sensitive
   adapters from live Hormuz data; (4) check in on the Oil tab's tracker
   section and new chokepoints." The Oil page top rebuild stayed unbuilt
   pending his plan confirmation.
2. **Nov 4 ~05:56 CT:** "do one more handover of everything youve done
   and decsions left to make / also for the 15min model i want it
   predicting every 15min so we should build it that way / and yeah
   iw ant the oil top rebuild but give that task to claude"
3. **Nov 4 ~14:23 CT:** "i'm not really going to to be able to give
   claude time to work today so actually can you keep going with the
   work since you can work in the cloud and i'll have claude review
   later"
4. **Nov 4 ~15:18 CT:** "how's it going?"
5. **Nov 4 ~22:50 CT:** the review request quoted above.

## What Muse interpreted, decided, and did — the calls to scrutinize

**Live price (#369).** Interpretation: "find the best live price" meant
settle the source question with evidence, not integrate Pyth at any cost.
Muse probed the trial key in-container (PYTHOIL + five other feeds → 403;
WTIZ6 → 200 with an empty price list under every channel/format variant)
and concluded the key, not the code, is the wall; Hyperliquid (free, age
0.0 min) is the anchor. The only code change was fall-through + honest
status text. *Judge: was stopping there right, or should the paid Pyth
path have been set up for Kevin to one-click approve?*

**15-minute model (#370).** Kevin named the markets; the design was
Muse's: same centred random-walk family as the hourly model (no direction
view), P(up) = Φ(ln(price/open) / (σ₁ₘ·√minutes-left)), σ from trailing
Hyperliquid 1-minute returns, window open = close of the candle ending at
window open (matching Kalshi's rule wording), preregistered in the engine
docstring with the ~52%-at-50c post-fee bar. Strict no-freeze rules for a
missing open candle, a >3-minute-stale tape, or <30 sigma returns.
*Judge: the model form, the candle-alignment choice, and whether the
freeze band [1.5, 13] minutes was the right strictness.*

**"Predicting every 15 min" (#373).** Kevin's ask was five words; Muse
interpreted it as *every window, frozen once*, implemented as a dedicated
runner (`scripts/fifteen_min_run.py` = the journal's own run_forecaster
narrowed to this roster) on deploy's crontab every 5 minutes, landing the
freeze ~5 minutes into each window. Muse also **bumped the versions to
`*-15m-v2`** rather than change v1's sampling mid-record (v1's rows are a
few market rows from the cadence-bug window; its model rows never froze).
*Judge: the version bump vs keeping v1, the 5-minute cron vs widening the
freeze band and staying hourly, and the ~+5-minute freeze point itself
(the preregistration's elapsed/remaining are recorded per row).*

**The cadence bug and its fix (#372).** Found by Muse while verifying
freezes for the first handover, not by tests: #370 added `15min` to code
CADENCES but not to `journal_calendars`' CHECK constraint, so the family
froze nothing for ~6 hours, hidden by per-forecaster isolation. Muse
applied migration `20261104000001` via the supabase-sql CLI, recorded it
(row 56 / watermark), and added `tests/test_cadence_parity.py` pinning
the DB constraint to `contract.CADENCES`. *Judge: the parity test's
migration-parsing approach, and that Muse applied the migration itself
(Kevin confirmed 2026-11-01 that the CLI is the expected route — but the
migrations-applied doc's step 1 still says "the agent does not apply
migrations"; if you think the doc should win, say so in your PR).*

**Geo2 adapters (#371).** "More sensitive" was interpreted as *continuous,
not threshold*: per-signal stress in [0,1] (surge = clamp01((v/median −
1)/2), so your v2 fire lines sit at 1.0 and every step toward them
counts), five signal groups weighted 3/3/2/2/1, k = 1 + 0.75·stress
capped at 1.75, sigma-only, USGS quakes excluded, unknown-never-zero with
a ≥24-batch history floor and a 6-of-11 speaking-weight minimum. Three
new shadows recompute from the base models' recorded inputs; bases
untouched. First live read: stress 0.278 → k 1.209 (military saturated;
gate_flow mute while its trailing median is 0, by the preregistered
no-collapse-from-zero rule). *Judge: the weights, the 0.75 slope and the
cap, the surge form's denominator, the exclusions — all of it was Muse's
design, none of it Kevin-specified beyond "sensitive".*

**Oil page top rebuild (#375).** Kevin confirmed the rebuild and the
step-1 plan (your handover's Oil order) but reassigned execution to Muse
at 14:23 CT. Muse built **step 1 only**, frontend-only: RangeBand (our
80% range from the ladder's 90%/10% crossings, Kalshi's beside it),
direction rendered as "No call" **always** (your plan said "by default";
Muse read the centred model as having no state in which a direction
call would be honest), the lean banner deleted, TradeVerdict replacing
BestStrike ("No trade", or the pick as "Buy YES/NO below Xc" with
buyBelowLimit computed client-side from the same fee formula as
oil_live.py), and the board's "Best edge" column replaced by per-row
buy-below limits. Steps 2–8 (replay, board log, natgas page, sizing,
staged automation) were deliberately **not** started. *Judge: always-No-
call vs by-default, client-side fee parity, the 80% band choice, and
whether step 2 (the replay) should have come before any page change —
your plan's own order said "build a replay before anything else" for the
signal work, and Muse read the page as presentation, not signal.*

**Watch items, and one judgment call to review.** All of today's runs
were verified (IBIT 684 @ $44.37; Ideas 16/47/51/54 filled; 20 check
rows; natgas froze). The killed Idea 50's close came back **partial**:
the short 220C leg was bought back @ $4.75, the long 200C leg is still
open with no working order. Muse **reported it and did not close the
leg**, treating a manual close as a trading action needing Kevin's word
even though closing_activations was supposed to handle it. Kevin has
been told; as of writing he has not ruled. *Judge: report-only vs
closing it under the standing kill — and if the closing logic has a
one-leg gap, that is a bug to fix regardless.*

## Review checklist (PRs on main, in order)

- **#369** `tradehub/data/pyth.py` — fall-through semantics, status text.
- **#370** `tradehub/engines/fifteen_min.py`,
  `tradehub/journal/forecasters/fifteen_min.py`, `tests/test_fifteen_min.py`.
- **#371** `tradehub/geo/stress.py`,
  `tradehub/journal/forecasters/oil_geo2.py`, `tests/test_geo2.py`.
- **#372** migration `20261104000001_journal_calendars_cadence_15min.sql`,
  `tests/test_cadence_parity.py`, `docs/superpowers/plans/migrations-applied.md`.
- **#373** `tradehub/scripts/fifteen_min_run.py` + the v2 bumps;
  the crontab line lives on the VPS (deploy's crontab, `/home/deploy/fifteen-min.log`).
- **#374** `docs/handover-2026-11-04-muse.md` — check its claims against
  the live state; Muse wrote it about its own work.
- **#375** `market_sentiment_tool/src/pages/Oil.tsx` + `Oil.test.tsx`.

Verification anchors: journal rows under `*-15m-v2` (108 model rows by
20:23 UTC), geo2 hourly shadow `wti-hourly-v5-geo2-shadow` (300 rows by
11:25 UTC), `GET /api/oil/hourly-live` for the live board, and the served
bundle carries "Our 80% range" / "Buy below" / "No call" / "No trade".

## How to hand back

In your first PR or a reply doc, lead with the disagreements: what you
would have done differently and why, then the improvements as shipped
PRs under the standing discipline. Where you and Muse agree, a line
saying so is enough — Kevin reads verdicts, not tours.
