# Fifteen-minute rule: edge gate + entry-time tracking (amendment, 2026-11-08)

Amends the trade rule preregistered 2026-11-05 in `tradehub/oil_fifteen_rule.py`
(forward record from `PREREG_AT = 2026-11-07T00:00:00Z`). Kevin's direction,
2026-11-08: *"make it only trigger buys when the edge exists… over time we want
to know what the best entry time in the 15 mins or 1 hr should be, so rethink
how these metrics are being tracked."*

## What the audit found (2026-11-09, production data)

- The rule is a **read-time reconstruction** (`oil_fifteen_rule.record()`), not a
  runtime trigger: for each series it takes the first journal-frozen forecast of
  each window and applies `pick()` — buy YES when `p − yes_ask ≥ 0.10`, NO when
  `yes_bid − p ≥ 0.10`, quotes sane (`0.02 < yes_bid ≤ yes_ask < 0.98`), windows
  frozen 16:45–18:30 ET excluded. The freeze lands ~5 minutes into the window
  (elapsed 5 in 131 of 141 forward rows; the band is 1.5–13).
- The price paid is the frozen ask: YES at `yes_ask`, NO at `1 − yes_bid` (the
  NO ask implied by the YES bid; no separate NO book is recorded). PnL nets
  Kalshi's taker fee `0.07·cost·(1−cost)` once. **The 10-point gate is
  fee-blind**: the fee is charged in PnL but never in the gate. On the forward
  record at amendment time (30 settled buys, +5.0¢/contract), 6 buys had gross
  edge within the fee wedge above the bar and summed to −$1.15.
- Repeat buys on one window cannot stack: the journal's DB guard refuses a
  second forecast row per (forecaster, target) and `record()` takes the first.
  One buy per window per series by construction. But **no decision is ever
  persisted** — buys and skips alike are re-derived at read time, and a window
  that was evaluated but not bought (or never frozen) leaves no trace.
- Coverage: on weekdays the 5-minute runner freezes ~every window (Nov 6:
  96/96 per series); on the Nov 7–8 weekend both the journal and the
  independent tape recorder saw ~1 in 5 windows — Kalshi-side market
  availability, not a hub failure.
- A per-minute tape already exists: `fifteen_min_ticks` (since 2026-11-06,
  written by `scripts/fifteen_min_tape.py`) holds the live read — model prob,
  YES bid/ask, price, open price — at ~13.7 rows per forward window. It was
  never joined to outcomes or used by the rule. It is the raw material for the
  entry-time dataset below.

## The edge gate (frozen here)

For a side `s` with model probability `q` (`p` for YES, `1 − p` for NO) and
cost `c` (`yes_ask` for YES, `1 − yes_bid` for NO):

```
fee(c)      = 0.07 · c · (1 − c)          # Kalshi taker fee, the record's existing cost model
edge_net(s) = q − c − fee(c)
```

A buy fires iff the better side's `edge_net ≥ MIN_EDGE = 0.10`. The bar is
unchanged from the 2026-11-05 preregistration; what changes is that it is now
measured **net of the round-trip cost** instead of gross. The fee is charged
once, at entry; the contract settles at $1/$0 with no exit fee, so `fee(c)` is
the whole round-trip cost. The traded side is the side with the larger
`edge_net`. Quote sanity band and the 16:45–18:30 ET halt exclusion are
unchanged. One entry decision per window per series.

## What does not change

- The model (`*-15m-v2`), the freeze, the journal, and the raw record:
  `record()` keeps reconstructing the original gross-gate record exactly as
  before, and it keeps accruing. The 300-trade go-live bar still reads on that
  raw forward record. The gated record is reported **alongside** it (forward
  totals and the `by_session` split), never substituted for it.

## Decisions, persisted (new table `fifteen_rule_decisions`)

Every targeted window gets one decision row, written by the fifteen-minute
runner and upserted on `(series, target)` so passes never duplicate it:

- `action = "buy"`: side, cost, model prob, `edge_net` at the freeze.
- `action = "skip"` with `reason`:
  - `no_edge` — a frozen read and sane quotes, but the better side's net edge
    was under the bar (`best_edge_net` recorded);
  - `no_quote` — a frozen read whose quotes were missing or outside the band;
  - `halt` — frozen inside the 16:45–18:30 ET exclusion;
  - `no_prediction` — the window was targeted but no forecast was frozen, and
    the tape *could* have supported a read at the freeze moment;
  - `stale_tape` — no forecast, and the tape cannot support a read at the
    freeze moment (missing open candle, stale, or too thin), re-checked
    against the recorded 1-minute tape.
- `session` (`open`/`closed`, the `futures_open` split), settlement `outcome`
  and net `pnl` filled in once the window settles.

## Entry-time tracking (new table `fifteen_window_offsets`)

One row per (series, window, minute offset 0..15), written once the window has
settled, additively — the journal and tick tables are untouched:

- `prob_up` at that offset: the per-minute tape's live read where a tick
  captured it (`prob_source = "tick"`, with that minute's real `yes_bid` /
  `yes_ask`); otherwise recomputed from the 1-minute candle tape with the
  model's own read (`prob_source = "tape"`, quotes null).
- Where quotes exist: the gated `side`, `side_cost`, `edge_net` at that
  offset, and — once settled — the hypothetical net `pnl` of entering there.
- The underlying's `price` at the offset, at window settlement, and at
  window-open + 60 minutes, with `move_to_settle_bps` / `move_to_60m_bps`, so
  an entry minute can be scored on the contract and on the hour after it.

The API reports a per-offset aggregate (windows, priced windows, mean net
edge, hypothetical net/contract, win rate, mean moves) — the dataset that can
answer "which minute is the best entry" as it accrues.

## Read side

`/api/oil/fifteen-rule` keeps every existing field and adds `gate` (the
net-gated reconstruction: forward + by_session), `decisions` (persisted
decision counts by action/reason) and `offsets` (the per-offset aggregate).
All three fail soft to empty when their tables are unreadable, like the rest
of the endpoint. The Oil page panel shows the gated record beside the raw one
and the skipped-window counts; it does not hide the raw record.
