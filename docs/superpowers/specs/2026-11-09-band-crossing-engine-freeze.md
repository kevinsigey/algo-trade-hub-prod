# Band-Crossing Engine — rules v1 freeze (Spec C, LOG-ONLY)

Frozen 2026-11-09, before the engine's first scan. Spec of record:
`~/workspace/ibkr-comp/research/engine_specs_2026-11-09.md` (Spec C).
Kevin's amendment (2026-11-09, binding over the spec where they differ):
**log-only first — no orders until he flips it.** This document is the
preregistration: the rules, the state machine, and the grading computation
below do not change after the first crossing exists. A changed rule is a
new version with a new freeze.

## Mode: LOG-ONLY (structural, not a flag on an order path)

- This build contains **no order-placement code path at all** — no machine
  API calls, no idea activations, no manual-order code. The engine computes
  crossings and records the would-be action at full fidelity, and that is
  all it can do.
- A durable control row follows the `gap_controls` precedent (PR #451):
  table `band_crossing_controls`, one `global` row, `orders_enabled`
  seeded **false** and read back before deploy. The engine reads it on
  every scan and stamps every crossing row with the mode it ran under
  (`log_only` while false).
- The future flip is: Kevin's word + `orders_enabled = true` on that row
  **plus a separate live build** that adds an order path reading the row.
  Flipping the row against THIS build changes nothing — there is nothing
  for it to switch on. That is stated here so the flip is never oversold.
- Portfolio Check still runs on every would-be activation and its outcome
  is recorded on the crossing row (`would_pass` / `would_warn` /
  `would_block` / `unavailable`, reason verbatim). A would-be breach does
  **not** create a `manual_actions` row in log-only mode; it lives in the
  crossing log only.

## Rules v1 (verbatim from Spec C)

- LONG starter: price <= base band AND latest guide intact or raised ->
  2% of book. Add to 4% at price <= bear band.
- TRIM: price > bull band -> trim half. Price > bull band AND file
  deteriorated -> full-exit review within 24h (Kevin's call, per the T8
  escalation rule — review, never auto-exit).
- SHORT: only price >= bull band AND a deteriorated T1 classification ->
  defined-risk put spreads at the standard $1,500 unit. Never short shares
  (asymmetry doctrine).
- Every activation runs the portfolio check; a breach lands in
  manual-actions with the portfolio reason (machinery already live).
  *(Log-only amendment: the breach lands in the crossing log instead —
  see Mode above.)*

Falsifier (verbatim): after 20 graded crossings, if entries do not beat
same-name buy-and-hold on excess return per unit of risk, the engine
shelves. The exact computation is frozen under Grading below.

## Zones

From the sheet's stored bands (bear <= base <= bull) and stored price:

| zone | condition |
|---|---|
| `bear` | price <= bear |
| `base` | bear < price <= base |
| `bull` | base < price <= bull |
| `above_bull` | price > bull |

## Inputs, as the hub actually stores them

- **Bands / price / basis / staleness**: the latest `valuation_fact_sheets`
  row per ticker (the valuation engine's own record). `band_basis` is
  `eps` or `revenue`; the bases never mix on a sheet and the crossing row
  records which basis its bands came from. Industry = the sheet's frozen
  `peer_group` (a leading `sector:` is stripped); `unknown` if absent.
- **Guide status**: the sheet's `directions` for the anchor metric
  (EPS anchor metric on the EPS basis, `revenue` on the revenue basis):
  `raised` -> raised; `held` or `first` -> intact; `cut` -> cut;
  missing -> unknown. "Intact or raised" = {intact, raised}.
- **T1 forward-file classification**: **finding, 2026-11-09 — the hub has
  no machine-readable T1 classification store.** The production database
  has no forward-file or print-classification table (checked against the
  full public table list); the forward file lives as research documents,
  not rows. The engine therefore reads classifications through one
  provider with a fixed contract — table `forward_file_classifications`
  (`ticker`, `classification` in {improved, intact, deteriorated},
  `as_of`) — which does not exist yet, so the provider honestly returns
  "no classification" for every name. Classifications are never invented,
  inferred from guide direction, or back-filled by the engine. Until a
  source exists, the T1-dependent rules (short entries; the review
  escalation) **cannot fire**, and the reason is recorded wherever they
  would have been evaluated (see data-missing rules).
- **Books**: both paper books, `main` and `big`, evaluated every scan.
  Position-dependent rules (trim, review) read that book's holdings via
  the portfolio check's own position read (underlying-level market
  value). Starter/add are sized per book: target dollars = pct x that
  book's Alpaca account equity at scan time; "at target" when the held
  market value is within $0.01 of the target. A signal that applies to
  both books logs one row per book.

## The candidate (would-be action) — pure function of one scan

Evaluated per (ticker, book), in this order:

1. zone `bear` or `base`:
   - guide cut -> suppressed, reason `guide_cut`.
   - guide unknown -> suppressed, reason `guide_status_unknown`.
   - guide intact/raised -> long candidate, target 4% (zone `bear`) or
     2% (zone `base`). Actionable when held MV < target$ - $0.01:
     action `starter` (held MV = 0) or `add` (held MV > 0), hypothetical
     delta = target$ - held MV. At/above target -> none, reason
     `target_reached`.
2. zone `above_bull`:
   - held and T1 deteriorated -> `review_full_exit` (a flag for Kevin;
     no would-be order, so no Portfolio Check run: `pc_outcome =
     not_run`).
   - held -> `trim_half`, hypothetical delta = -0.5 x held MV.
   - not held and T1 deteriorated -> `short_put_spread`, $1,500 unit.
   - not held and no T1 classification -> suppressed, reason
     `no_t1_classification`.
   - not held and T1 present, not deteriorated -> no rule applies
     (plain none; nothing recorded beyond state).
3. zone `bull`: no rule applies.

Portfolio Check deltas (frozen convention): starter/add as above;
trim_half as above; `short_put_spread` = {ticker: -1500.00} (the max-risk
unit treated as capital committed). The check is called with recording
off — its outcome is written to the crossing row, never to
`portfolio_check_events` or `manual_actions`, in log-only mode.

## The crossing state machine

State per (ticker, book) in `band_crossing_state`: zone, action,
target_pct, guide_status, t1_classification, held flag, the sheet's
`computed_at`, updated each scan.

- **First sighting** (no state row — the baseline scan, or a name banded
  later): state is established silently, **no crossing row**. The scan
  that runs with an empty state table is recorded with kind `baseline`
  and labeled as such everywhere it is shown.
- **A crossing row is written iff**, comparing this scan's evaluation to
  the stored state:
  - the candidate (action, target_pct) changed — to an actionable
    candidate, or from an actionable candidate to none (the row then
    records action `none` with the reason: `zone_exit`, `guide_cut`,
    `target_reached`, `guide_status_unknown`); or
  - the zone changed into territory where a rule is gated off
    (`guide_cut`, `guide_status_unknown`, `no_t1_classification`) — one
    `none` row naming the gate, so the gate behaving is on the record
    (the CEG shape: price above base into an improved file correctly
    produces **no long crossing**).
- Merely remaining in a zone, scan after scan, with an unchanged
  candidate writes **nothing**.
- State updates every scan regardless of whether a row was written.

## Data-missing rules (no crossing, reason recorded)

- Sheet not `banded`, or bands null -> the name is not in the universe:
  no state, no row.
- Sheet `stale` (the valuation system's own staleness flag) or price
  null -> the name is skipped this scan; state is left untouched; the
  skip and reason (`stale_sheet`) are recorded in the scan's audit row.
- No T1 classification -> shorts and the review escalation cannot fire
  (above); trim still fires for held names (the escalation is simply
  unavailable, and the row records `t1_classification = null`).
- A book's positions/equity cannot be read -> that book is skipped for
  that name-scan, named in the scan audit row; holdings are never
  guessed.

## Crossing log schema (`band_crossings`)

date/time, scan kind, book, ticker, industry, band basis, bear/base/bull,
price + price_as_of, zone, previous action, action (or `none`),
target_pct, hypothetical delta USD, held MV + held weight % of equity,
guide status (+ raw direction), T1 classification as read, suppress
reason, Portfolio Check outcome + verbatim detail, mode stamp, and the
grading outcomes (below) filled in later. Review flags are rows with
action `review_full_exit` — in this log, never auto-exits, never
`manual_actions`.

## Cadence

- **Weekly scan**: Mondays 13:00 UTC, on the closes stored on the latest
  sheets (Friday's close, as the sheets stand before the Monday watch
  refresh; each row records its `price_as_of`, so the basis is never
  ambiguous).
- **Event re-scan**: hourly on weekdays during the valuation watch hours
  (13:37-21:37 UTC), running only when the latest sheets'
  max(`computed_at`) is newer than the last completed scan's watermark —
  i.e. within the hour, hence within a day, of any re-banding.
- **Grading**: nightly 04:37 UTC, after the valuation grading pass.

## Grading — the falsifier computation, frozen

- Graded entries: crossing rows with action in {`starter`, `add`,
  `short_put_spread`}. Direction +1 for longs, -1 for the short.
  Trim/review/none rows are not entries and are never graded.
- Prices: daily closes from the hub's DataStore (the valuation grading
  convention). Sessions are trading days in that series. Entry = the
  close on the row's `price_as_of` date; both outcome ends use series
  closes (the recorded price is display).
- At horizon h in {5, 20} sessions:
  - `r_h` = P(entry+h) / P(entry) - 1.
  - Unconditional control `u_h`: the mean of (P(s+h)/P(s) - 1) over
    starts s = every 5th session in the 252 sessions ending the session
    before entry, keeping starts with a full h-window; fewer than 10
    starts -> ungradeable at h. (This is the same-name buy-and-hold
    timing control: what entering this name unconditionally, on this
    cadence, earned over h sessions.)
  - Risk `sigma_h` = stdev of the name's daily log returns over the h
    sessions after entry, x sqrt(h); sigma_h = 0 -> ungradeable.
  - `score_h` = direction x (r_h - u_h) / sigma_h.
- `outcome_5` is informational. `outcome_20` governs. The falsifier
  counter counts entries with a `score_20`. **At 20 graded entries:
  mean(score_20) > 0 -> the falsifier is survived; mean(score_20) <= 0
  -> the engine shelves** (in log-only mode shelving is a recorded
  status on the read surface and in this lane's report — there are no
  orders to stop, and the failed verdict is reported, never hidden).

## Worked example (acceptance)

CEG, 2026-11-09: bear 185.90 / base 215.54 / bull 224.52, price 249.95 ->
zone `above_bull`. Not a long zone: **no long crossing**, whatever the
file says. (Held -> trim/review evaluation; not held -> short evaluation,
gated on a T1 classification that does not exist yet.)
