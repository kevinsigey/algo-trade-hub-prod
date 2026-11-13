# Fifteen-minute v4 shadow family — preregistration

Frozen 2026-11-12 (Kevin's directive); **revised 2026-11-13, before
any counted data exists**, on Claude's forward-data analysis of the
original family and Kevin's per-commodity call (both on PR #518).
**PREREG_AT = 2026-11-14T00:00:00Z** (moved one day earlier on Kevin's Nov 13 call, before any row existed and before merge). Only settled windows
with `window_open >= PREREG_AT` count, for every candidate and every
leg of every criterion — the blend shadow's fresh-window convention.
Nothing in this file may be edited after PREREG_AT; a changed rule is
a new version beside these, never a rewrite.

## Why this family exists, and why it was revised before it started

The family was first drafted from the Step A0 replay's ablations
(Nov 9–12, candle-close quotes). Claude's review of PR #518 tested
the same dials on the **forward record** instead
(`fifteen_window_offsets`: real tick quotes, Nov 6–12, settled, one
trade per window, fee-netted), because the replay had not yet passed
its quote gate. The forward record contradicted one drafted candidate
outright and reshaped another:

| Rule (forward data) | Trades | ¢/trade | Positive days | Daily-total low95 |
|---|---|---|---|---|
| v1: minute 5, 10-point bar (the live gate) | 325 | +2.4 | 4/7 | −0.28 |
| edge ≥20 at minute 5 | 86 | +4.9 | 6/6 | +0.35 |
| copper at 20, rest live | 283 | +2.8 | 5/7 | +0.24 |
| minutes 11–13, 10-point bar | 742 | +6.7 | 6/7 | +3.34 |
| minutes 11–13, edge 10–20 | 548 | +5.1 | 6/6 | +2.03 |

Per series, ¢ per trade (10-point bar or more):

| Series | Min 5 | Min 11–13 | 11–13, edge 10–20 | 11–13, edge ≥20 |
|---|---|---|---|---|
| Natural gas | **+15.5** | +4.8 | +2.0 | +7.8 |
| WTI | −2.0 | +7.4 | +7.6 | +6.8 |
| Brent | −2.1 | +6.4 | +2.1 | +15.3 |
| Silver | +1.8 | +15.4 | +14.1 | +18.6 |
| Copper | −1.5 | −0.9 | −6.2 | +3.0 |
| Gold | −5.7 | −1.6 | −0.6 | −3.0 |

Consequences, all taken: the drafted late-band candidate (late +
10–20¢) was **dropped** — late with edge ≥20 beats it in 4 of 6
series, so its premise was a replay artefact. The drafted copper-bar
candidate barely moved the pooled result and was **dropped**. In
their places: a per-commodity rule (the right minute differs by
series, and pooling hides it — late timing hurts gas) and a no-gold
rule (gold is negative at every timing; excluding it is a clean,
single-dial test).

Everything here is in-sample: six or seven days, offsets correlated
within a window. That is exactly what the forward shadow is for.

## The candidates (frozen)

All four read off the forward offset track (`fifteen_window_offsets`).
A trade row already passed the live 10¢ fee-netted bar and the quote
band by construction. **One trade per window: the earliest row inside
the candidate's entry minutes for that series clearing its bar.**
Entry minutes are stated exactly per candidate; no candidate takes
entries outside its stated minutes.

| version | rule |
|---|---|
| `v4-edge20-shadow` | minute **5 only**, `edge_net >= 0.20`, all series |
| `v4-no-gold-shadow` | minute **5 only**, live 10¢ bar, all series **except gold** (gold never trades) |
| `v4-late-window-shadow` | minutes **11–13**, live 10¢ bar, all series |
| `v4-per-commodity-shadow` | per-series dials, table below |

`v4-per-commodity-shadow` dials (each series' best forward cell;
Kevin's call, 2026-11-13):

| Series | Entry minutes | Bar | Forward ¢/trade (Nov 6–12) |
|---|---|---|---|
| Natural gas | 5 | 10¢ | +15.5 |
| WTI | 11–13 | 10¢ | +7.4 |
| Brent | 11–13 | 10¢ | +6.4 |
| Silver | 11–13 | 10¢ | +15.4 |
| Copper | 11–13 | **20¢** | +3.0 |
| Gold | — | no trades | negative at every timing |

**Multiple-testing accounting, restated for the revised family:**
still four candidates at the same bar, stated as one family. The
per-commodity rule is the most snooped of the four — it picks the
best of roughly 6 cells per series from the same seven days — so its
in-sample numbers deserve the least trust and its forward shadow is
the real test. The other three are single dials.

## The fillability rule (frozen, late dials)

Late-minute fills are unproven: a offset row says the book showed an
edge at minute 11–13, not that the demo's order would have filled.
So a trade under a late dial (late-window, all series; per-commodity:
WTI, Brent, silver, copper) **counts only if the ask size for its
side at that minute, from `fifteen_min_ticks` (depth recorded since
Nov 11), is at least the demo's order size at that price** — the
demo's 1% rule at the family's starting terms:
`max(1, floor($500 × 0.01 / side_cost))` contracts
(`kalshi_demo.size_contracts` at its $500 start). A measured size
below that means the candidate does not trade that window. A minute
with no depth measurement is **fill-unknown**: the window leaves
scoring entirely (neither a counted trade nor a paired window) and
is reported in the `fill_unknown` count, never assumed filled. Depth
exists for every scored window in principle (scoring starts Nov 15,
depth since Nov 11); the in-sample figures above predate depth for
their first days and are "fill unknown" for Nov 6–10.

## Scoring and the bar (frozen)

Per candidate, over settled fresh windows:

- **own record**: its counted trades' pnl per contract — n, mean, and
  the day-clustered low95 (`fifteen_volregime.clustered_low95`,
  clusters (series, ET day)), pooled across series. The per-commodity
  candidate is additionally scored and reported **per series** (same
  three numbers per series it trades); the report carries the
  per-series breakdown for every candidate.
- **paired delta**: per window, candidate pnl (0 when it does not
  trade) minus **the live gate's own decision on the same grid: the
  `offset_min == 5` row's pnl when that row is a settled trade, else
  0** — over windows where either trades; mean and the same clustered
  low95. The gate freezes at minute 5, so the baseline is its minute-5
  row, never an earlier row it never took. This pairing is a grid
  reconstruction of the gate, labeled as such — the demo lane's
  realized record remains the final judge of any promotion.
- **Promotion-eligible** when ALL hold (the house criterion's shape —
  the oil shadow runs the same test at its own n = 150): n ≥ 100
  fresh counted trades; own low95 > 0; paired low95 > 0.
- **Killed** when 60 days pass from PREREG_AT or 300 fresh counted
  trades accrue without eligibility. **A kill is terminal**: the
  candidate stops being scored, no later alert fires for it, and its
  record stays readable.

Scoring is `tradehub/fifteen_candidates.py` (pure) driven by
`tradehub/scripts/fifteen_candidates_score.py`. No new tables.

## Notifications, and what "switch" means here

Kevin asked for two things on Nov 12: the shadow versions, and a
notification when models switch, so the system can be left running.
The notification half is built here: the scorer writes a
`gate_switch` row into the existing `watcher_alerts` outbox the first
time a candidate becomes promotion-eligible and the first time one is
killed (deduplicated on version + event; the existing 10-minute
poller delivers it to the Trading Thesis Testing chat, naming the
model and the numbers that tripped it).

The authority half is deliberately NOT automated in this
preregistration: eligibility fires the notification and a decision
request; **a live gate switch happens only on Kevin's word** — the
same standing rule as every other shadow in this system (oil, blend,
volregime all promote by decision, not by timer). If Kevin wants true
auto-switching, that is a one-line amendment to this section made
before PREREG_AT, in the open — not a behavior the code grows on its
own.

## What would change our minds

A candidate that clears the bar on the forward track earns a demo-lane
trial (Step B's second half — its own PR, and the demo-orders
unique-key migration needs Kevin's go through Claude first). A family
that produces no eligible candidate by the stopping rule is evidence
the 10¢ live gate is the wrong shape entirely, and the next family
should be designed from Step A's feature study rather than from
another round of bar-and-window dials.
