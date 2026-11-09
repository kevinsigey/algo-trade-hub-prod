# Amendment: WTI hourly best-strike picker v2 — calibration, a 15-point bar, a second snapshot

Frozen 2026-11-09 (Kevin's approval of options A, B and D from the clarity
overhaul's diagnosis; option C — a probability/cost floor — is explicitly NOT
approved and is not in this design). This amendment governs the frozen record
in `oil_itm_lines` from the first v2 freeze forward. The v1 segment is never
rewritten; it stays in the same table as the control, separated by
`picker_version`.

## Why

The v1 record (audited 2026-11-09, production): 51 settled picks, 16 hits
(31.4%), mean stated probability 0.443 against a 31.4% realized rate — the
model overstates its chances by ~13 points — and −3.5¢ per contract after
fees (−1.5¢ before them: a calibration failure, not a fee problem). The
journal replay over the same model family agrees in direction. Losses
concentrate in the sub-0.40-probability longshots the argmax keeps landing
on. The model itself (a Normal centred on the live price, σ from the
trailing 72 hourly settlement changes) is not changed by this amendment;
what changes is how its stated probabilities are corrected, what edge a
pick must clear, and what each freeze records.

## The v1 test (for the record, exact)

From `tradehub/oil_live.py::pick_best_strike`: candidates are ladder rows
with spread ≤ 0.08; each side prices at a payable cost (YES at the ask, NO
at 1 − bid) inside the cost band [0.20, 0.80]. `edge_pts = (p − cost) · 100`
is the GROSS edge in points; `net_pts = (p − cost − fee) · 100` with
`fee = 0.07 · cost · (1 − cost)` is the edge after Kalshi's taker fee. The
pick is the candidate with maximal `net_pts`, taken only when its
`edge_pts ≥ 5.0`. One freeze per event, at 25–35 minutes to close.

## The v2 test (the whole rule, in one paragraph)

Probabilities are calibrated first (next section). For every candidate
side, `prob` is the CALIBRATED side probability (the map applies to the
YES probability; a NO side's probability is 1 − map(p_yes)), and
`edge_pts` / `net_pts` are computed from that calibrated `prob` with the
same fee formula, the same cost band [0.20, 0.80], and the same spread cap
0.08 as v1. The pick is the candidate with maximal `net_pts` — the fee
stays inside the ranking quantity, exactly as v1 — taken only when its
`edge_pts ≥ 15.0`. So the gated quantity is the same one v1 gated (gross
edge, in points), at 15 instead of 5, computed on calibrated instead of
raw probabilities. Anything else is not v2.

## A — Calibration of the stated probability

Approach: the remainder-bucket idea the 15-minute family uses, adapted to
this ladder model (bucketing stated probabilities against realized
frequencies, fitted walk-forward on settled journal rows — the pattern of
`journal/forecasters/calibrated.py`).

- **Population.** Settled journal rows for forecaster `oil_wti_hourly`,
  version `wti-hourly-v4-hl-shadow` — the live ladder's own model on the
  live Hyperliquid feed (the page and the ladder price off that feed; the
  v1 forecaster's CL=F rows are a different price source and are not
  mixed in). Audited at freeze time of this amendment: 6,937 settled rows
  over 83 events, 2026-11-04 → 2026-11-09. The picker's own frozen picks
  are NOT added as training rows: they are a selected subset of these
  same ladders, and including them would double-count contracts.
- **The map.** Fixed 10-point buckets over the stated YES probability.
  A bucket's value is `(hits + 20 · mean_stated) / (n + 20)` — the
  realized frequency pulled toward the bucket's own mean stated
  probability by a pseudocount of 20, so thin buckets barely move and
  full ones speak. Bucket values are made monotone across buckets
  (pool-adjacent-violators), and the map is piecewise-linear between
  bucket centres (0.05, 0.15, …, 0.95), clamped outside. This is a
  shrinkage-flavoured bucket map, not a free isotonic fit: the Nov 9
  15-minute experiment showed raw bin frequencies at small n carry more
  noise than the bias they correct, and the pseudocount is the guard.
- **Floors and fallback.** The bucket map requires ≥ 1,000 settled rows
  spanning ≥ 40 distinct events. Below that, the fallback is a
  least-squares linear shrinkage toward the training base rate,
  `cal = base + s · (p − base)` with `s` clamped to [0, 2]; below 5
  pairs, identity. At amendment time the population clears the floors
  several times over, so the bucket map is what ships; the fallback
  exists so a future data gap degrades honestly instead of silently.
- **Walk-forward purity.** A freeze for event E fits only on rows whose
  event closed strictly before E's close (event identity and close come
  from the target ticker, `engines/oil_hourly.event_hour`). A freeze
  never trains on its own event or a later one. Every frozen row stores
  the map version it used: kind, constants, training-through event
  close, and row count.
- **Stated limitations.** Journal rows are frozen at the journal's lead
  (~65 minutes), not at T−30/T−10; the map corrects the model's
  probability-vs-frequency relationship and the forward record is what
  grades whether it transfers across leads. Rows inside one event are
  correlated (one settlement value decides the whole ladder); bucket
  counts are row counts, with the pseudocount and the ≥40-event floor
  as the guards. No independence is claimed.

## D — A second snapshot, and freezes that record what they saw

- **Two freeze kinds.** `T-30` at 25–35 minutes to close (the v1 window)
  and `T-10` at 5–15 minutes to close. The T−10 window is 10 wide
  because the runner's cadence is ~10 minutes: any run phase lands
  exactly one run inside it. One v2 row per (event, freeze_kind); each
  kind is graded as its own pick set, so pick timing becomes testable.
  If a legacy v1 row already exists for an event when v2 first runs,
  v2 still freezes its own T−30 row for that event; the segments stay
  separated by `picker_version`.
- **Stored per freeze** (new columns on `oil_itm_lines`): `freeze_kind`,
  `picker_version` ('v2'; legacy rows carry NULL = v1), `ours_cal` (the
  calibrated side probability the v2 test used — `ours` keeps its v1
  meaning, the raw side probability, in both segments), `yes_bid` /
  `yes_ask` (the picked ladder row's quotes), `sigma_h`, 
  `minutes_to_close` (exact, at the freeze), `edge_net_pts` (the
  `net_pts` the pick ranked on), `calib_map_version`.
- **Grading** is unchanged math, applied to every row of every segment
  and kind. `record()` keeps its existing aggregate and gains a
  `by_segment` split (legacy / v2 T−30 / v2 T−10).

## Coherence of the live ladder

The Oil page hero computes its pick from the same ladder; leaving it on
the v1 rule while the record freezes v2 picks would make the page show
one rule and grade another. So `live_ladder` runs the v2 pick whenever
a calibration map is supplied: the serving process fits one at most
every 30 minutes (fail-soft — any error leaves the v1 pick in place and
the payload's `picker_version` says which ran; the map is fitted on
events already closed at fit time, so the purity rule holds for any
event it is applied to). Freezes never use that cached map: each freeze
fits its own, with the freeze event's close as the exact cutoff. The
15-minute display path keeps `pick_best_strike` (v1) untouched — a
different rule family with its own frozen gate.

## What does not change

The model (`hourly_prob`, its σ, its price feed), the cost band, the
spread cap, the fee rate, the grading math, and the picker's nature: it
is a record, never an order. Nothing here trades.

## Expected volume (measured after this design was frozen)

A walk-forward replay of both rules over the journal's frozen
`v4-hl-shadow` ladders (quotes frozen at the journal's lead, not at
T−30 — the same caveat the existing replay carries) is run before the
merge and its picks/day figures are appended here as a dated appendix,
so the volume cost of A + B is on record before the first v2 freeze.

### Appendix, 2026-11-09: the replay

`scripts/research/oil_picker_v2_replay.py` over the 3,513 quoted +
settled `v4-hl-shadow` rows (83 events, 5.54 days, walk-forward maps:
identity for the first event, shrinkage until the 1,000-row floor,
buckets after):

| rule | picks | picks/day | net/contract |
| --- | ---: | ---: | ---: |
| v1 (raw, gross ≥ 5) | 46 | 8.30 | −4.41¢ |
| **v2 (calibrated, gross ≥ 15)** | **7** | **1.26** | **+15.98¢** |
| reference: raw, gross ≥ 15 | 9 | 1.62 | +27.75¢ |
| reference: calibrated, net ≥ 15 | 4 | 0.72 | +8.59¢ |

Read honestly: the 15-point bar does most of the volume work — v2
expects roughly **1.3 picks/day per freeze kind, an ~85% cut** from
v1's replay rate — and in this window both 15-point variants are
positive while v1 is negative, in line with the live record. What the
replay does NOT establish is the calibration layer's own contribution:
at n = 7–9 picks per variant, the raw-15 reference nets more than v2,
and the ordering is well inside noise. The amendment ships A + B as
approved; the forward segments (v2 T−30 and T−10 against the legacy
control) are the arbiter, and no claim about which layer earns what is
made until they grade.
