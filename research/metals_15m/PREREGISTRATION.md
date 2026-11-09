---
title: "Metals 15-minute (gold, silver, copper): preregistered forward record"
type: preregistration
domain: metals
status: frozen
settlement_source: Kalshi settlements via the journal (KXGOLD15M / KXSILVER15M / KXCOPPER15M)
tags: [fifteen-rule, metals, kalshi, preregistration, forward-record, entry-timing, edge-gate]
summary: "Frozen 2026-11-09; evaluation segment opens 2026-11-09T21:30:00Z. Forecasters gold-15m-v1 / silver-15m-v1 / copper-15m-v1: the oil family's drift-scaled random walk on Hyperliquid xyz tapes, every-window freeze by the 5-minute runner, gate 0.10 net of the taker fee from day one, halt parity 16:45-18:30 ET. Go-live bar per series: 300 settled gated forward trades with low95 > 0, raw reconstruction beside it as control. The record is fully separate from the oil family's. Copper's weak tape basis (88.1% direction match, 3c median spreads in the scoping replay) is a recorded risk. Full spec: docs/superpowers/specs/2026-11-09-metals-fifteen-prereg.md."
---

# Preregistration — metals 15-minute forward record (gold, silver, copper)

**Frozen:** 2026-11-09 (Kevin's authorization the same day; series set is
his explicit pick — gold + silver + copper). **Evaluation segment opens:**
`2026-11-09T21:30:00+00:00` — forecasts frozen before that instant never
count (the forecasters do not exist in production before this build
deploys; there is no metals replay segment in the record).

**The forecasters.** `gold_15m` (`gold-15m-v1`, KXGOLD15M, anchor
xyz:GOLD), `silver_15m` (`silver-15m-v1`, KXSILVER15M, xyz:SILVER),
`copper_15m` (`copper-15m-v1`, KXCOPPER15M, xyz:COPPER). Construction is
the oil family's, unchanged and shared in code: `P(up) = Φ( ln(S/S₀) /
(σ₁ₘ · √minutes_left) )`, σ₁ₘ from trailing 1-minute log returns (≥30
returns, 2bp floor), `read_window` strictness (missing open candle /
stale tape / thin σ → the freeze is skipped, the method never swapped).
Every window frozen ~5 minutes in by the existing 5-minute runner; a
`KalshiImplied` shadow row per forecast. **No calibration layer at
launch.**

**The gate.** The family's live gate in the family's code: at the freeze,
buy the side beating its price by **≥ 0.10 net of the taker fee**
(`0.07 · cost · (1 − cost)`; YES at `yes_ask`, NO at `1 − yes_bid`), one
hypothetical contract, hold to settlement. **Halt parity:** no decisions
on windows frozen 16:45–18:30 ET; session splits by the same
`futures_open` Globex week, computed per metal from its own record.
Every targeted window gets a persisted decision (buy, or skip with its
reason) and every settled window a per-offset track (minutes 0–15), in
the family's tables, stamped `gate_version = 'v1'`. Record-only: no
order path exists or may be added.

**Segmentation.** A separate family's record: it counts toward nothing
in the oil family (not the 300-bar, not the v2-oil shadow's promotion
criterion) and borrows nothing from it. **No imported variants** — oil's
minute-1 × 0.05 interaction is an oil hypothesis; metals variants only
from paired per-series studies on metals' own offsets.

**THE BAR (per series): 300 settled gated forward trades, low95 > 0** —
counted on the gated record exactly as the family's amended rule counts
(PR #424), the raw reconstruction reported beside it as control. A series
clears on its own numbers or not at all; clearing is a report, and any
go-live decision stays Kevin's.

**Copper's recorded risks:** Hyperliquid tape direction match 88.1% and
3¢ median freeze spreads in the scoping replay (gold 94.0% / 1¢, silver
98.6% / 1¢) — known weaknesses the forward record judges on the same
terms as the other two.

**Excluded:** platinum and palladium — not in this build even as journal
rows. Their inclusion later is its own preregistration.

**Horizon:** ~300 settled windows per series in ~4–5 trading days; 300
*gated* trades per series at replay fire rates is a multi-month accrual,
the oil family's own pace.
