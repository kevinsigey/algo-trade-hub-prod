# Fifteen-minute metals: gold, silver and copper forecasters as a preregistered forward record (2026-11-09)

Preregisters a **new fifteen-minute family** on Kalshi's metals complex —
`KXGOLD15M`, `KXSILVER15M`, `KXCOPPER15M` — mirroring the oil and gas
fifteen-minute family (`tradehub/engines/fifteen_min.py`, gate in
`tradehub/oil_fifteen_rule.py`) construction-for-construction. Kevin's
direction, 2026-11-09: *"can we use the same techniques we have for the
commodities 15mins to build a metals 15mins predictor as well?"* — and, on
the scoping's series-set question, his explicit pick: **gold + silver +
copper** (overriding the scoping's gold+silver-only recommendation;
copper's weak tape basis is recorded below as a known risk the forward
record will judge, not a reason to exclude it unseen).

The scoping of record is `research/metals_15m/RESULTS.md` (branch
`research/metals-15m-scope`): the contract reality was verified live
against Kalshi's trade API on 2026-11-09. The contracts are the family's
exact shape — one contract per 15-minute window, `strike_type:
greater_or_equal`, YES iff the settlement source's 1-minute candle closes
the window at or above its open (Pyth Metal.Index.1OZGOLD /
Metal.Index.SILVER / Commodities.Index.CU respectively), quadratic fee
with multiplier 1 — the same `0.07 · cost · (1 − cost)` taker fee the live
gate already nets. Settlement tracks Pyth spot/index feeds, not CME
futures; the forecast models the Pyth series from Hyperliquid's xyz perp
tape (xyz:GOLD / xyz:SILVER / xyz:COPPER), free and live, exactly the oil
family's arrangement, with the perp-vs-index basis part of what the record
grades.

## The forecasters (frozen)

One forecaster per series, beside the existing three in
`tradehub/journal/forecasters/fifteen_min.py`, sharing the family's model
class, freeze band and strictness — no forked logic:

| Series | Forecaster name | Version | Anchor coin |
|---|---|---|---|
| KXGOLD15M | `gold_15m` | `gold-15m-v1` | xyz:GOLD |
| KXSILVER15M | `silver_15m` | `silver-15m-v1` | xyz:SILVER |
| KXCOPPER15M | `copper_15m` | `copper-15m-v1` | xyz:COPPER |

- **Construction:** the family's drift-scaled random walk, unchanged —
  `P(up) = Φ( ln(S/S₀) / (σ₁ₘ · √minutes_left) )`, σ₁ₘ the trailing
  realized volatility of 1-minute log returns (≥30 returns, 2bp floor),
  read through `read_window`'s strict rules: a missing window-open candle,
  a stale tape, or a too-thin sigma tape **skips the freeze** — the method
  is never swapped, because a swapped method would corrupt the record the
  model is graded on.
- **Cadence:** the v2 every-window cadence from the start — the existing
  5-minute runner (`tradehub/scripts/fifteen_min_run.py`) freezes each
  window once, about 5 minutes in, in the same invocation as the oil
  family. (The oil family's v1 hourly sampling was a pilot artifact;
  metals start where the family already is.)
- **Shadow row:** a `KalshiImplied` row per forecast, same as the family —
  the market's own frozen read, graded beside the model.
- **No calibration layer at launch.** The 2026-11-09 calibration study is
  the standing evidence: at a few hundred settled windows per series,
  calibration layers tax exactly the tail the gate trades. If the
  journal-side remainder-bucketing wrapper is ever applied to metals, it
  is applied later, on metals' own record, under its own stop rule — the
  family's treatment, not an import.

## The gate (frozen)

The family's live gate, unchanged, in the family's own code
(`oil_fifteen_rule.evaluate` / `pick_net` / `pnl` — one implementation,
shared, never copied):

- At the freeze, buy the side whose chance beats its price by **0.10 or
  more net of Kalshi's taker fee** (YES at `yes_ask`, NO at `1 − yes_bid`;
  quotes sane iff `0.02 < yes_bid ≤ yes_ask < 0.98`), one hypothetical
  contract, hold to the window's close. No early exit.
- **Halt parity:** no decisions on windows frozen **16:45–18:30 ET** —
  metals halt at the same Globex hour (17:00–18:00 ET) as energy, so the
  family's exclusion is the honest mirror. Session splits use the same
  `futures_open` Globex week shape; per-metal session reads are computed
  from metals' own record, never imported from oil's (gold trades actively
  in the Asian session where WTI is thin).
- **Record-only.** Nothing here places an order; no order path exists or
  may be added. Fills at the quoted ask are assumed; book depth is not
  recorded — the family's stated convention.

## The record

Written by the same runner invocation, into the same tables the family
uses (they are keyed by series and target — generalized, not duplicated):

- journal forecasts and settlements for the three forecasters and their
  KalshiImplied shadows;
- `fifteen_rule_decisions`: one persisted decision per targeted window per
  series — the gated buy, or the skip with its reason named
  (`halt` / `no_quote` / `no_edge` / `no_prediction` / `stale_tape`),
  stamped `gate_version = 'v1'`;
- `fifteen_window_offsets`: one row per settled window per minute offset
  0..15 — the model's chance (live tick read where the per-minute tape
  captured it, tape-recomputed otherwise), the gated edge on offer, what
  entering there would have made, and the underlying's moves. The tick
  tape (`fifteen_min_ticks`) is extended to the three metals series from
  day one so the minute 1–14 grid accrues on live reads, as oil's does.

**PREREG_AT = `2026-11-09T21:30:00+00:00`** — frozen in this document
before the first forward row exists (the forecasters do not exist in
production before this build deploys). Rows frozen before it are replay,
never evidence; there is no metals replay segment in the record.

## Segmentation (hard)

- This is a **separate family's record**. It counts toward nothing in the
  oil family — not its 300-trade go-live bar (which keeps counting gate-v1
  oil/gas freeze trades only), not the v2-oil shadow's promotion
  criterion — and it borrows nothing from them: no oil statistic, slice or
  variant enters a metals verdict.
- **No imported variants.** Oil's minute-1 × 0.05-bar interaction is an
  *oil* hypothesis, preregistered as an oil shadow on oil's fresh segment.
  Metals get no variant until a paired per-series entry-timing study on
  metals' own offsets says so. The same for the bar: 0.10 net is frozen
  here because the family's band evidence gives no basis for a lower one;
  a metals band study, if ever wanted, runs on the metals forward record
  the way `research/fifteen_bar/` ran on oil's.
- The oil family's code and record are untouched except where the shared
  tracking and summaries are generalized to carry a second family without
  mixing it into the first family's numbers.

## Evaluation and the go-live bar

Counted per series, mirroring the family's amended counting rule
(2026-11-09, PR #424): **the bar is 300 settled GATED forward trades on
the series' own gated record** — the trades the live gate would actually
have taken, frozen at or after PREREG_AT — **still ahead at the low end of
the 95% range** (the record's standing convention: mean − 1.96·sd/√n > 0).
The raw reconstruction (the same picks measured gross, the family's
control) is reported beside the gated record at every read. A series
clears its bar on its own numbers or not at all; the family is never
pooled into a verdict. Clearing the bar is a *report*, not an automatic
action — any go-live decision stays Kevin's, as with the oil family.

## Copper's recorded risks (Kevin's pick, eyes open)

From the scoping replay (~3.5 days, exploratory, same-sample — a first
read, not evidence):

- the Hyperliquid tape's window direction matched Kalshi's settled result
  only **88.1%** of the time (gold 94.0%, silver 98.6%; the oil family
  grades 94.2–97.8%) — the weakest basis in either family;
- the median freeze-minute spread was **3¢** against 1¢ for gold and
  silver — wider quotes mean the gate's fills-at-ask assumption is
  kindest exactly where the tape is weakest;
- its replay gated record fired oftenest and earned least per fire
  (42 @ +4.9¢, low95 −8.4¢) — the profile of model error being harvested.

None of that is a verdict. The forward record above is what judges copper,
on the same terms as gold and silver.

## Excluded

**Platinum and palladium are not in this build** — not as forecasters, not
as journal rows (Kevin chose the three; their Hyperliquid day volumes are
~1/60th of silver's, and the family's strictness rule reads a thin tape as
a gap, never an approximation). Adding them later is its own
preregistration.

## Expected horizon

At the replay's fire rates (gold ~14% of windows gated), 300 gated trades
per series is a **multi-month** accrual — the same pace as the oil
family's bar. The studies' raw material accrues far faster: ~300 settled
windows per series ≈ 4–5 trading days of tape.
