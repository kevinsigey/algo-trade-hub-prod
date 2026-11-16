# Preregistration — the Binance-tape gold shadow (v5-binance-gold-shadow)

Frozen 2026-11-14 (Kevin's ruling 2026-11-13 on the tape question, after the
tape-fit study of 2026-11-14, issue #524 comment 6884902749). Frozen BEFORE
the first row: only windows opening at or after PREREG_AT count toward
anything, and no row is written for an earlier window. This file is not
edited once a row exists.

    PREREG_AT = 2026-11-16T00:00:00+00:00

## The claim being tested

The 15-minute model's anchor tape is Hyperliquid's. The tape-fit study
(2026-11-14, paired on the same settled windows closing Nov 10–13 UTC,
implied outcome = the tape's close at close−1m against its close at
open−1m, the replay's own convention, against Kalshi's official result)
measured how often each tape's implied outcome matches the settlement:

- **Gold (n=263): Hyperliquid 93.92% [90.4, 96.2] vs Binance 98.10%
  [95.6, 99.2]** — Binance passes the cross-venue gate (agreement ≥ 95%
  and no worse than Hyperliquid minus 1 point). On the 19 windows where
  the two tapes disagree, Kalshi sides with Binance 15 to 4.
- Silver (98.4 vs 98.0) and WTI (98.58 vs 98.58) pass the gate as ties —
  no clear beat, so no build for them.
- Brent (Binance 93.68), gas (92.06, Hyperliquid better) and copper
  (86.23, both tapes failing) do not pass — no build for them.

Kevin's ruling (2026-11-13): where the study shows Binance clearly beats
Hyperliquid for a series, a NEW forecaster version may be built on the
Binance live tape as a preregistered shadow that can feed demo lanes;
v1 stays unchanged, and real money stays off. Gold is the one series
that qualifies. The claim: the same model, read off the tape that
matches settlement more often, should make better freeze-time decisions
on gold than v1 does on the same windows — measurably, on fresh windows,
paired against v1's own record.

## The variant (frozen)

For every targeted gold window (series KXGOLD15M only), reconstructed by
the 15-minute runner's record pass from v1's first frozen forecast:

- **The tape.** Binance USD-M futures 1-minute klines for XAUUSDT
  (public REST, no key), parsed exactly as the replay's Binance tape
  (open time → close). One fetch per record pass.
- **The read.** The model's own `read_window` (engines/fifteen_min),
  unchanged, evaluated at v1's freeze instant (`frozen_at` of gold v1's
  first frozen forecast) on the Binance tape: same open-candle
  strictness, same staleness rule, same sigma method, same freeze
  information set. Only the tape differs.
- **The gate.** The live rule's own `evaluate` (oil_fifteen_rule),
  unchanged, on the Binance read's probability with v1's frozen quotes
  (the payload's yes ask/bid — the market side is identical for both
  models; only the model's probability changes): same fee netting, same
  0.10 bar, same halt exclusion.
- **The rows.** One decision row per window in the shadow's own table
  (`fifteen_binance_decisions`, gate_version `v5-binance-gold-shadow`),
  carrying the Binance read's probability and sigma, v1's frozen
  probability, the decision and, once settled, the outcome and the
  rule's per-contract PnL. A window v1 never froze is a `no_prediction`
  skip; a Binance tape that cannot support the read at the freeze
  instant is a `stale_tape` skip. Both are recorded, never approximated.
- What stays fixed: the model formula, v1 and its tape, the fee math,
  the 0.10 bar, the halt exclusion, the live rule and its decisions,
  the blend, the volregime challenger and their frozen rows and
  scoring. None of them is modified by this build.

Rows are written by the runner's lookback reconstruction (the house
pattern for shadows): the Binance 1-minute klines are final once closed,
so the freeze-instant read is deterministic and reproducible after the
fact; nothing in the read uses information from after the freeze.

## Scoring (fresh segment only)

Fresh = window open at or after PREREG_AT. Trades are buys with a
settlement. low95 is the record's standing convention (mean − 1.96
standard errors). The paired delta is per window: shadow PnL − the live
rule's gold PnL on the same window (fifteen_rule_decisions, series
KXGOLD15M), a skip scoring 0, counted only where both rows exist and are
settled. Evaluated once a day on the 15-minute runner's first pass, one
row in `fifteen_binance_evals`. The evals row also carries a
day-clustered low95 (windows clustered by ET day): informational only,
added before any rows exist, not part of the promotion bar.

## Promotion bar (frozen, all required)

    n >= 100 fresh gold trades;
    shadow low95 > 0;
    paired delta (vs the live rule's gold decisions) low95 > 0

**This build contains no promotion path and no demo lane:** the evals
row records whether the bar is met, and nothing writes to any promotions
log, touches the live gate, or places an order. If the bar is ever met,
promotion — and any demo lane fed by this forecaster — is Kevin's word
and a separate commission.

## Stopping rule (frozen)

If the promotion bar is not met within 60 days of PREREG_AT
(2027-01-15 00:00 UTC) or by 300 fresh trades, whichever comes first,
the shadow is retired as a record: it stops counting toward promotion
and its rows stay as they are.

## Not in this build

No other series (silver and WTI tied; Brent, gas and copper failed the
gate). No change to v1, its tape or its record. No websocket feed — one
REST klines fetch per record pass. No page or endpoint: the record is
read from its tables until a surface is commissioned.

## Amendment 2026-11-16 — transport: websocket collector (Kevin's pick)

The frozen text above assumed one REST klines fetch per record pass.
On the shadow's first live day that proved impossible from the hub's
VPS: Binance's REST hosts (fapi.binance.com, api.binance.com) refuse
the egress with HTTP 451, the numbered mirrors redirect to the block
page, and the reachable Vision REST mirror serves spot markets only
(no XAUUSDT). The futures websocket host (fstream.binance.com) is
reachable. Kevin picked the live-read route on 2026-11-16 over the
alternatives (Vision daily-archive reads a day late; leaving the
shadow dark).

What changes: only the transport. A collector
(`tradehub/scripts/binance_ws_collect.py`, mirroring the AIS
consumer's shape) subscribes to Binance's own XAUUSDT 1-minute kline
stream and keeps the rolling tape in a cache file
(`tradehub/binance_tape.py`); the record pass reads the tape from the
cache at the same freeze instant, through the same `read_window`. At
collector start the cache is seeded from Binance Vision's daily
archive — the published archive of this same feed — so a cold start
begins with history. The reader raises on a missing or stale cache,
so a dead collector reads as a tape outage, never as data.

What does not change: the tape itself (Binance XAUUSDT 1-minute
closes, the (open time -> close) convention), the variant, the freeze
instant, the quotes, the bar, the scoring, the promotion bar, and the
stopping rule. The REST reader stays in the code for the replay
convention and in case the egress block lifts.
