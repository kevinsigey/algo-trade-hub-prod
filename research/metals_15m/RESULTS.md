---
title: "Metals 15-minute predictor: scoping and first replay read"
type: research-note
domain: metals
status: complete (scoping; no production change)
settlement_source: Kalshi settlements via the trade API (KXGOLD15M / KXSILVER15M / KXCOPPER15M results), verified live 2026-11-09
tags: [fifteen-rule, metals, kalshi, scoping, preregistration-template]
summary: "Kalshi lists a full 15-minute metals complex (gold, silver, platinum, palladium, copper) with the identical contract shape to the oil/gas family — Pyth 1-minute candle direction, quadratic fee multiplier 1. The family construction mirrors almost verbatim (Hyperliquid xyz has all five metals perps). Exploratory replay at the family's 0.10 net bar: gold 19 gated @ +13.5c (low95 -3.1), silver 6 @ -21.4c (n too small), copper 42 @ +4.9c (low95 -8.4) — nothing proven, gold the only series whose first read matches the oil family's shape. Recommendation: build gold + silver as v1 forecasters with the family's exact discipline; copper/platinum/palladium journal-only or deferred (weaker tape basis, wider spreads)."
---

# Metals 15-minute predictor — scoping (2026-11-09)

**Question (Kevin, 2026-11-09):** can the commodities 15-minute techniques
(drift-scaled random walk on a free perp tape, fee-netted edge gate, preregistered
forward record) be mirrored for metals? Full scope, researched the same way the
oil/gas family was.

## 1. Contract reality — the 15-minute metals complex EXISTS, same shape as oil/gas

Verified live against Kalshi's trade API on 2026-11-09 (the hub's own base URL,
`api.elections.kalshi.com/trade-api/v2`). Five series, all `frequency: fifteen_min`,
category Commodities:

| Series | Title | Settlement source (Pyth) | Fee |
|---|---|---|---|
| KXGOLD15M | Gold 15-minute | Metal.Index.1OZGOLD/USD | quadratic, multiplier 1 |
| KXSILVER15M | Silver 15-minute | Metal.Index.SILVER/USD | quadratic, multiplier 1 |
| KXPLATINUM15M | Platinum 15-minute | Metal.XPT/USD | quadratic, multiplier 1 |
| KXPALLADIUM15M | Palladium 15-minute | Metal.XPD/USD | quadratic, multiplier 1 |
| KXCOPPER15M | Copper 15-minute | Commodities.Index.CU/USD | quadratic, multiplier 1 |

Contract shape is **identical to the oil/gas family**: one contract per 15-minute
window, `strike_type: greater_or_equal`, the floor strike is the settlement
source's 1-minute candle close at the window open, and YES iff the close of the
1-minute Pyth candle at the window's end is at least that open close (verified
verbatim in `rules_primary` for gold, silver, platinum, copper). A direction bet,
not a strike ladder — the family's `prob_up` math applies unchanged. The fee is
the same schedule the live gate already nets: `0.07 * cost * (1 - cost)` per
contract (multiplier 1 on all five series, same as WTI/Brent/NatGas).

**Trading hours (gold, paginated over 2,000 settled markets, Oct 8 – Nov 9):**
91 windows on full weekdays, 69 on Fridays, 22 on Sundays, 0 on Saturdays —
the CME Globex week (Sun 18:00 ET open, Fri 17:00 ET close, daily 17:00–18:00 ET
break). This is the same session shape as energy, so the family's `futures_open`
pattern and a 16:45–18:30 ET halt window translate directly (see §3).

**Liquidity (live reads):** the market-list volume/OI fields return 0 (a Kalshi
list-endpoint quirk; the oil family reads the same zeros), so liquidity was read
from 1-minute market candlesticks instead: a sampled gold window carried ~41.7k
contracts open interest and ~20.6k volume in a single minute candle. Median
freeze-minute spread in the replay sample: **gold 1c, silver 1c, copper 3c** —
gold and silver quote as tightly as the oil family; copper is visibly wider.

## 2. Underlying feed — the same anchor works, and the basis grades in-range

The oil family forecasts Pyth settlement from Hyperliquid xyz perp candles
(free, live; Pyth is key-gated) and grades the perp-vs-Pyth basis as part of the
record (WTI 96.2% / Brent 97.8% / NatGas 94.2% direction match over 312 windows).
Hyperliquid's xyz dex lists **all five metals perps**: xyz:GOLD, xyz:SILVER,
xyz:COPPER, xyz:PLATINUM, xyz:PALLADIUM. Day volumes at probe time: silver
~$95M, gold ~$77M, copper ~$10.9M, platinum ~$1.4M, palladium ~$0.9M.

Direction-match of the HL tape's window direction vs Kalshi's settled result,
from the replay sample (§5): **gold 94.0%, silver 98.6%, copper 88.1%**.
Gold and silver sit inside the oil family's basis range; copper is the weak
tape (thinner book, industrial-metal intraday noise) and grades like it.

Settlement tracks Pyth *spot/index* feeds (Metal.Index.*), NOT CME GC/SI
futures — so the forecast must model the Pyth series, and the HL perp is the
free proxy for it, exactly the oil family's arrangement. Tick capture: HL
serves 1-minute candles (5,037 most recent ≈ 3.5 days) and the hub already
runs a per-minute tick recorder for the oil family (`fifteen_min_tape.py` →
`fifteen_min_ticks`); extending it to the metals series is the same mechanism,
so the offsets grid (minutes 1–14 live reads) is feasible from day one.

## 3. Model mirror — construction transfers; sessions need one honest change

Per metal, unchanged from `tradehub/engines/fifteen_min.py`:

- `P(up) = Phi( ln(price_now / price_at_open) / (sigma_1m * sqrt(minutes_left)) )`,
  sigma = trailing realized vol of 1-minute log returns (≥30 returns, 2bp floor),
  read from the HL xyz tape by `read_window`'s strict rules (missing open candle,
  stale tape, or thin sigma → skip the freeze; the method is never swapped).
- Forecaster specs beside the existing three in `journal/forecasters/fifteen_min.py`'s
  SERIES tuple: `gold-15m-v1`, `silver-15m-v1` (family started at v1 and sampled
  one window/hour before v2 went every-window; metals can start at the v2 cadence
  directly — every window, frozen ~5 minutes in by the same 5-minute runner).
- A `KalshiImplied` shadow row per forecast, same as the family (the market's own
  frozen read, graded beside the model).
- Series coins map: KXGOLD15M → xyz:GOLD, KXSILVER15M → xyz:SILVER, etc.

**Session/halt translation (the one real design decision):** metals trade the
Globex week above. The family's halt (no decisions on windows frozen 16:45–18:30
ET) exists because CME halts energy futures 17:00–18:00 ET while the perp tape
keeps trading. Metals halt at the same Globex hour (17:00–18:00 ET), so the
honest mirror is the **same halt window**, plus the family's `futures_open`
shape with metals' identical week. One difference to state in the preregistration:
gold trades actively in the Asian session where WTI is thin — session splits
(open/closed) must be computed per metal from its own record, never imported
from oil's.

## 4. Gate + evaluation design — same discipline, nothing imported

- **Bar: preregister 0.10 net of fee, the family's live gate, unchanged.**
  The family's evidence says the 5–10 point band is mostly model error on oil
  AND gas at the freeze; there is no metals evidence for a lower bar, and
  inventing one from oil's numbers would repeat the import error in the other
  direction. If a metals band study is ever wanted, it runs on the metals
  forward record the same way `research/fifteen_bar/` ran on oil's.
- **Calibration:** none at launch. The Nov 9 calibration study is the standing
  evidence — at a few hundred settled windows per series, calibration layers
  tax exactly the tail the gate trades. The live construction is the raw
  drift-scaled walk (the family's remainder-bucketed recalibration is a
  journal-side wrapper that ships only when its own walk-forward stop rule
  passes; metals forecasters would get the same wrapper treatment later, on
  their own record).
- **Record:** journal forecasts + settlements, a decisions table read
  (`fifteen_rule_decisions` pattern, stamped per series), the offsets table
  pattern for entry-time studies, and the **300 settled gated trades** go-live
  bar pattern — counted per the family's amended rule (gated record only, raw
  reconstruction reported beside it as control). PREREG_AT frozen before the
  first forward row; rows before it are replay, never evidence.
- **Hard lessons carried, explicitly:** (a) oil's minute-1 × 0.05 interaction is
  an OIL hypothesis — metals get no variant until a paired per-series timing
  study on metals' own offsets says so; (b) the gate is fee-netted from day one
  (the family's original fee-blind gate overstated its edge by ~1.75 pts at
  50c); (c) the market is near-parity on Brier in every series measured so
  far — the edge, if any, lives only in the gate's disagreement tail, so the
  verdict metric is the gated record, not the Brier gap.

## 5. First read — exploratory replay (same-sample caveats stated)

Method: the family's exact math in replay. HL xyz 1-minute candles (the only
tape history cheaply available, ~3.5 days) + Kalshi settled markets over the
same span; freeze read at elapsed minute 5 (remaining 10) using the candle
ending at elapsed 5; market quote = Kalshi's own 1-minute candlestick
yes_bid/yes_ask close at that minute; gate = family's `net_edges` at 0.10;
PnL per contract after the taker fee. `analyze.py` in this folder reproduces it.
This segment both suggests and would score any variant — it is a first read,
not evidence, exactly as the family's Nov 4–5 replay was labeled.

| Series | Windows | Model Brier | Market Brier | Gated n | Gated net/contract | Low95 | HL dir match | Median spread |
|---|---|---|---|---|---|---|---|---|
| Gold | 133 | 0.1657 | 0.1643 | 19 | **+13.5c** | −3.1c | 94.0% | 1c |
| Silver | 147 | 0.1842 | 0.1811 | 6 | −21.4c | −49.4c | 98.6% | 1c |
| Copper | 118 | 0.1957 | 0.1742 | 42 | +4.9c | −8.4c | 88.1% | 3c |

Read: Brier is near-parity everywhere (the market a hair ahead in all three —
the family's standing picture). Gold's gated cell is the only one shaped like
the oil family's live record (19 trades at a double-digit mean), but its
interval crosses zero: **not enough data, not a verdict**. Silver's gate
almost never fired (6 trades — its model rarely disagrees with the market by
10 net points at the freeze) and the few fires lost; that is a statement about
this 3.5-day sample, not about silver. Copper fired oftenest and earned
least per fire, with the worst tape basis and the widest spreads — the
profile of model error being harvested, the same signature as oil's [5,10)
band. Pooled across the three: 67 gated trades at ≈ +5.0c (derived from the
per-series means) — a number with no verdict attached.

Platinum/palladium: contracts, fees, and settlement verified (§1), but no
replay — HL day volumes ($1.4M / $0.9M) are ~1/60th of silver's, and the
family's strictness rule (a thin tape is a gap, never an approximation)
argues for journal-only observation first if they are included at all.

## 6. Build plan (phased, mirroring the family) + Kevin's decisions

**Phase 0 — preregistration (paper first, as always).** A spec in
`docs/superpowers/specs/` freezing: series set, forecaster ids (`gold-15m-v1`,
`silver-15m-v1`), the freeze cadence (every window, ~5 min in), the 0.10 net
bar, the Globex halt (16:45–18:30 ET freeze exclusion), PREREG_AT, the
300-gated-trade bar, and the no-imported-variants rule.

**Phase 1 — forecasters + record.** Add the two SERIES specs + coins to the
fifteen_min engine/forecaster maps; the existing 5-minute runner picks them
up (same invocation); extend the per-minute tick tape to the two series so
the offsets grid accrues from day one; decisions/offsets written by the
tracking pass generalized per series (the tables are keyed by series/target
already). Journal rows + KalshiImplied shadows flow automatically.

**Phase 2 — surfacing.** The fifteen-rule endpoint gains a `by_series` block
for the metals forecasters (the Nov 9 clarity overhaul's pattern), and the
Strategies page gains a "15-minute metals rule" entry in the same glance
format — record shown as the GATED forward record with the raw control beside
it, never the replay.

**Phase 3 — studies, only on the metals record.** Band study and paired
entry-timing study per series once the offsets accrue (~300+ settled windows
per series ≈ 4–5 trading days of tape; the gated bar takes far longer —
at gold's replay fire rate (~14% of windows) 300 gated trades is a
multi-month accrual, same as the family's).

**Decisions for Kevin:**
1. **Series set:** gold + silver as forecasters (recommended — tight spreads,
   in-range basis); copper / platinum / palladium as journal-only shadows, or
   excluded entirely? Copper's replay argues against giving it a gate.
2. **The bar:** 0.10 net (recommended, the family's live bar) — confirm no
   metals-specific bar is preregistered without metals evidence.
3. **Halt parity:** same 16:45–18:30 ET exclusion as oil (recommended —
   same Globex halt hour), to be frozen in the preregistration.
4. **Sequencing vs the oil shadow:** the metals record is a new family's
   forward record — it neither counts toward nor borrows from the oil
   family's 300-bar or the v2-oil-shadow promotion criterion. Confirm the
   records stay separate (recommended).

No production change was made by this scoping. Paper only, as always.
