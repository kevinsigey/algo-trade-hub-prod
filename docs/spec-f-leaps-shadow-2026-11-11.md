# Spec — Spec F LEAPS shadow trial (idea 81), shadow-first

Build spec, 2026-11-11. Source of the strategy: Spec F in
`~/workspace/ibkr-comp/research/engine_specs_2026-11-09.md` as amended
2026-11-11 14:50 CT (Kevin): the T8-LEAPS-1 trial runs SHADOW-FIRST — both
lines shadow-tracked at triggers, no live capital under idea 81 until Kevin
promotes it on shadow grading evidence, and the 4-trigger / 12-month gate is
measured on shadow fills first. Preregistration: Workshop idea 81
(family T8-LEAPS-1, single trial). This build creates the shadow machinery;
it places no orders and has no path to them.

## 1. What a trigger is

A trigger is a row the existing Spec C band-crossing engine already writes
(`band_crossings`): zone `bear` or `base`, action `starter` or `add`, for a
ticker in the T8 sleeve — the `t8_ai` sleeve of the Portfolio Check config,
read live the same way `valuation/candidates.py` reads it. The crossing
engine's own candidate rules have already enforced the guide legs (a guide
cut or unknown guide status suppresses the action), so a qualifying crossing
row IS the stamped base-band trigger with T8's legs intact; no new scanner
is built. The row's snapshot id, bands, price and guide status are copied
onto the shadow record as provenance.

Rules around triggers:

- One open shadow pair per ticker. A further qualifying crossing while a
  pair on that name is open is recorded as a trigger event on the pair but
  does not stack a second pair and does not count toward the 4.
- A trigger with no qualifying contract (§2) or no fillable size (§3) is
  recorded as a trigger with its reason and does not count toward the 4:
  the gate counts opened pairs.

## 2. The LEAPS line (contract selection)

At trigger time, from the hub's existing live options plumbing
(`tradehub/portfolio/options.py`: contracts from the paper host, quotes from
the data host — the same source the order planner uses, never the hub's
model marks):

- Listed calls on the underlying with expiry 365–550 days out; among them,
  the expiry nearest 455 days.
- Delta from the Alpaca snapshot for each candidate strike (greeks ride the
  snapshot; a Black-Scholes delta from the snapshot's IV is the fallback
  when greeks are absent). The strike whose delta is nearest 0.80 inside
  0.75–0.85 wins. None inside the band → no line, reason recorded.
- Extrinsic at entry = ask − max(spot − strike, 0). Extrinsic over 15% of
  the ask → no line, reason recorded (the Spec F entry condition failed at
  this trigger; it is a fact about the trigger, not a near-miss fill).
- Entry price is the ASK at capture (a taker fill, conservative); bid and
  mid are recorded beside it, with the capture timestamp.

## 3. Size and the paired share line

- Contracts = floor($10,000 / (ask × 100)), at least 1. If one contract
  alone costs more than the $10,000 premium cap → no line, reason recorded.
- Delta-notional of the LEAPS line = contracts × 100 × delta × spot.
- The share line opens the same moment at identical delta-notional:
  shares = delta-notional / the trigger price the crossing row recorded
  (fractional in shadow), entered at that trigger price — so shares ×
  entry price is the delta-notional exactly, whatever the live spot at
  capture.
- Both lines are booked at delta-notional; the premium is carried as its
  own field everywhere it is shown, never as the position's value. (This is
  the T10 booking rule from the preregistration, applied to shadow first.)

## 4. Storage (one migration)

`20261111xxxxxx_leaps_shadow.sql` creates one table, `leaps_shadow_pairs`:

- identity: id, idea_id (81), crossing_id, ticker, opened_at, status
  (open / closed / expired), close_reason, closed_at.
- trigger provenance: snapshot_id, zone, action, base/bear/bull bands,
  guide_status, trigger price.
- LEAPS leg: occ symbol, strike, expiry, contracts, entry bid/mid/ask,
  premium total, delta at entry, extrinsic at entry, IV at entry, spot at
  entry, delta-notional.
- share leg: shares, entry price.
- nightly marks (latest grading pass): marked_at, leaps mid (null when the
  quote is missing or too wide — marked stale, never fabricated), share
  price, DTE remaining, roll_flag (DTE ≤ 180), leaps P&L, share P&L,
  delta delivered (leaps P&L per dollar of premium-side capital vs the
  share line's P&L per dollar of share cash, as the claim defines it),
  carry drag annualized (premium decay + entry spread paid, per year of
  delta-notional).
- trigger events after opening (further crossings, roll reviews) ride in a
  jsonb `events` list on the row.

No other table changes. Idea 81 is tagged `leaps-trial` (the ideas.tags
array already exists) and published (record only) when the build ships;
its tracked/live timestamps are NOT used — the trial state lives in this
table and its summary, not in the share-basket lifecycle.

## 5. Marking and grading

A nightly script (`tradehub/scripts/leaps_shadow_grade.py`, VPS cron beside
the valuation grade) walks open pairs: refreshes marks (§4), sets the
180-DTE roll flag (a flag only — no auto-roll in v1; a roll is Kevin's call
or a later build), and closes a pair when the name's band state exits
(zone `above_bull` on the latest stamped sheet) or its guide status turns
`cut` — T8's falsifiers, read from the same stamped sheets the crossing
engine reads. Pairs also close at expiry (settled at intrinsic from the
final close) and at trial end.

The trial summary (computed by the same pass, shown on idea 81's page):
pairs opened, pairs closed, mean carry drag across closed + open pairs,
mean delta delivery, premium cash vs the share cash the same delta would
have taken (the ≤40% leg), and the gate read against the frozen rule —
first 4 opened pairs or 12 months from the first pair: drag over 3.5%/yr
or delivery under 80% kills the vehicle; a pass extends the trial to 8
pairs. The summary is a read, never an actor: promotion to live capital is
Kevin's separate call.

**Gate amendment (Kevin's call, 2026-11-11, before any pair opened — no
evidence is regraded).** Three faults in the gate as first built, found by
Claude's round-2 review: (1) "mean delta delivery" averaged per-pair
ratios of return-on-cash, which reads ~3.0 for a perfectly tracking LEAPS,
so the 80% bar could only fire on near-total failure. Delivery is now
POOLED dollars — sum(leaps_pnl) / sum(share_pnl) over the cohort — and the
80% bar stays constant, meaning 80¢ delivered per $1 the share line made.
Delivery is undefined (the gate reads insufficient data) when the cohort's
share line made nothing in total. (2) The cohort could be judged the day
the 4th pair opened, with carry drag annualized off a 1-day floor; the
cohort is now judged only once every pair in it is closed or carries at
least 90 days of marks. (3) The verdict was recomputed on every read; the
first judged verdict is now stored (table `leaps_trial_verdicts`, written
by the nightly grade) and served verbatim, never recomputed.

## 6. Surfaces

- Idea 81's Workshop page gains a Spec F panel (rendered for any idea
  tagged `leaps-trial`): the trial summary, then each pair — ticker,
  trigger date and zone, the contract in words (strike, expiry, delta and
  extrinsic at entry), premium vs delta-notional booked, the share line
  beside it, current marks, DTE and the roll flag when lit.
- Nothing else changes: no Portfolio/T10 surface in v1 (no LEAPS position
  is held by any book; the booking rule is implemented inside the shadow
  record and panel, which is where a position would first exist).

## 7. Tests

- Contract selection: delta band, nearest-455 expiry, extrinsic veto,
  no-quote and wide-quote paths (fixtures, no network).
- Sizing: cap floor, one-contract-over-cap refusal, paired share size at
  identical delta-notional.
- Trigger intake: a crossing fixture (T8 name, base zone, starter) opens a
  pair; a non-T8 name, a bull-zone crossing and a suppressed action do not;
  a second crossing on an open name records an event only.
- Grading math: drag and delivery on fixed marks, the roll flag at 180
  DTE, close on above_bull / guide cut, the gate read at 4 pairs.
- API + page: the panel payload on idea 81; the tag is the only switch.

## 8. Decisions this spec takes (Kevin can amend any)

1. Trigger = Spec C crossing rows (starter/add into bear/base) on T8
   sleeve names — the conjunction the hub already grades, no new scanner.
2. Entry at the ask; delta from Alpaca snapshot greeks (BS fallback).
3. Unfillable triggers (no contract in band, extrinsic over the cap, one
   contract over the premium cap) are recorded and do not count to the 4.
4. No auto-roll in v1: 180 DTE raises the flag only.
5. Idea 81 is tagged and published for the record; the share-basket
   tracked/live lifecycle is untouched.
