# Product and portfolio review — Nov 9, 2026 (Claude, for Kevin and Muse)

Kevin asked for a fundamental look at every module: accuracy, relevance, ease of use, wordiness, visual clarity,
function, ability to find edge, automation, and how the hub reads as a portfolio piece. Reviewed on the live site as a
signed-out visitor (desktop 1360 px and phone 375 px) plus the codebase at `17d396b`. **Not reviewed:** Workshop,
Guidance, Screening, Deals, Agent debates, Health, Machine keys (admin login needed). A model-by-model review follows
separately.

## Headline
The hub's value is its honest scorekeeping, not a proven edge, and the site does not lead with that yet. Pitch it as
**a trading research lab that can't fool itself**: every forecast is locked before the event, every strategy has rules
fixed in advance, and failures stay on the record.

## Module by module (visitor view)

| Module | Verdict | Main problems |
|---|---|---|
| Overview | Weakest page | Four numbers, a "Coming up" heading over nothing, "not enough history" for movers. A visitor can't tell what the site is. |
| Portfolio | Strong | Sharpe −8.11 on a week of data is meaningless. The same ETF shows as several separate lines (XLV three times). |
| Trades and Orders | Fine | Multi-leg orders show "3/3 filled" with no symbol. |
| Strategies | Best page | The intro is three sentences where one would do. |
| Guidance, Workshop | Admin-only, but sit in the public "Trading" menu | A visitor clicks and meets "Admin only". Mark them with a lock or move them under Admin. |
| Ideas | Accurate but unreadable | Up to eight status chips per idea ("PASS · Gate overridden · Hindsight-selected · Critic WATCH…"). Ideas marked FAIL trade on the $1M book with no plain reason on the row. |
| Oil | Useful, mislabelled | Carries gold, silver and copper (Muse's Commodities rename covers this). The strike table shows "YES costs 0c" when nothing is quoted. One "Track record" box says "0 forecasts locked in" on a page with thousands. The hourly picker's own line says 26% hit against 40% predicted. |
| Hormuz | Most distinctive page | Long; the satellite finding (1.4 tankers a day against 48 a year ago) should lead. |
| Crypto | Clear since the redesign | Both hourly models are behind Kalshi's own price (skill −0.02, −0.04). |
| Macro, Weather | Slow | `/api/macro` 9.7 s, `/api/weather/map` 8.4 s, `/api/health` 15 s. Both pages still said "Loading…" after 6 s. |
| Sports | Clear | "No pick passed review today" is the usual state. |
| Model Tracker | The core asset | Totals had no thousands separators (136137). 161 models is too many to follow; 38 are measured. |
| Any unknown address | Blank page | No not-found route. |

## Can it find edge? (the site's own numbers, Nov 9)
- Forecast models: 1 of 38 measured models beats its baseline, over 134,207 scored forecasts.
- Stock book: −1.2 points against SPY after about a week; 33% of closed trades won; realized −$1,450.
- Kalshi gap tracker: closed at −$3,177 of a $10,000 pot (now paused, with a post-mortem).
- 15-minute oil and gas rule: the one promising result. 46 gated trades, +16.4¢ a contract, 61% wins. Natural gas is
  25 of the 46; the bar is 300.
- Automation is the strong side: orders, stops, grading, the guidance recorder and the circuit breaker run unattended.

## Personal app, public display, or multi-user
- Keep one site with two modes (it mostly exists): visitors read; the owner gets the admin tools.
- Not now: separate user accounts with their own books. It needs per-user broker keys and reads as investment advice.
- Later: the one feature with outside-user value is the Workshop (type an idea, get an honest backtest). It could open
  publicly with rate limits and no trading.

## What to tighten, in order
1. **A landing page for visitors**: what this is, three headline numbers, what's working, what failed, how it's built.
   A real domain (the address is a raw IP under sslip.io).
2. **Visitor-facing defects** (fixed in the PR that adds this file unless marked):
   - "Coming up" heading with nothing under it — fixed.
   - Unknown addresses render blank — fixed (not-found page).
   - Macro and Weather take 8–10 s — improved: repeat visits within 5 minutes are instant; the first visit after
     expiry still pays the full build (precompute it in the hourly job to finish this).
   - Tracker totals without commas — fixed.
   - Sharpe on under a month of days — fixed (shows "after 1 month").
   - Oil: "YES costs 0c" rows when unquoted, and the "0 forecasts locked in" box — **left for Muse** (Oil page is in
     the Commodities rename).
   - Strategies intro to one sentence; admin pages in the public menu — **left for Muse** (those files are mid-change).
   - `/api/health` 15 s — not touched.
3. **Words**: one-sentence page intros; one status and one line per idea.
4. **Pruning**: retire models that stay behind; move Weather, Sports and Macro to a "Lab archive"; lead with the
   15-minute rules, the stock book and the earnings-outlook work.
5. **Code health**: all 110 API routes live in one 4,410-line `tradehub/api/main.py`, and the last two days of history
   carry five "restore dropped hunks" repair commits against it. Splitting it into routers by area would stop that. The
   README still describes the old architecture (Vercel UI reading Supabase directly).

Scale, for the portfolio pitch: about 54,000 lines of Python, 21,000 of TypeScript, 283 test files, 71 migrations.

---

# Addendum, Nov 10: the admin pages (Claude)

Reviewed **from the source code, not the rendered pages** (I do not sign in as Kevin). Layout, spacing and real
data states are therefore unchecked; wording, structure, flow and the key-handling code are.

| Page | Verdict | Main problems |
|---|---|---|
| Workshop (list) | Good | One-sentence intro, clear empty states. Four tabs is right. |
| Workshop idea page | Most capable page in the hub, and the most crowded | One 1,496-line screen stacks the draft form, event study, option legs, portfolio blend, verdict tables, loss autopsy, lifecycle, tracking, the live gate, manual legs, the $1M book gate and a JSON import. The gate panel is written twice, once per book. |
| Screening | Good flow (words → filter cards → saved screen → tracked idea) | Headings show a literal `--` ("Filter library -- pick cards, nudge numbers"). Placeholders expose field names (`cash_per_debt`, "numerator field"). |
| Guidance | Useful, confusingly named | Four names for one thing: menu "Guidance", address `/valuation`, "valuation sheets", "fact sheets". The banner says "not trade recommendations" while the zones are called "buy zone" and "short zone". Three paragraphs, a legend and a snapshot line ("Unversioned legacy read…") sit above the first number. Ten columns. |
| Deals and IPOs | Skilled work, disconnected | The intro says "the paper apparatus" and "the paper's three rules" without saying which paper. Two prefilled cases (Tesla–SpaceX, Anthropic IPO). Nothing here is graded or feeds another page. |
| Agent debates | Honest, wordy | Three paragraphs before the ticker box. It says itself that it feeds no score, gate or order. The same debates also appear inside Guidance. |
| Health | Works | Its heading is uppercase italic, unlike every other page. The legend ends with an internal note ("The orderbooks timer has no history source and is not drawn"). `/api/health` took 15 s on Nov 9. |
| Machine keys | Sound | Keys are stored hashed, compared in constant time, shown once, capped per order and per day, rate-limited and logged. One fault: a new key defaults to the `orders:place` scope. Uses a different set of style classes from the rest of the site. |

## What to change, in order
1. **Machine keys: default a new key to no scopes** (or read-only), so placing orders is always a deliberate tick.
2. **Split the idea page into steps**: Draft → Verdict → Go live. Each exists already as a block; they only need
   tabs. Build the gate panel once and pass it the book.
3. **Guidance: one name, neutral zone words.** Call it Guidance everywhere, and rename the zones to "below
   guidance value / in line / above", which matches the "display only" banner.
4. **One intro sentence per page**, with the rest behind a "How this works" toggle (Debates, Guidance, Deals).
5. **One heading style.** Four are in use across these seven pages.
6. **Fold Agent debates into Guidance** and drop the separate page; move Deals to the lab archive unless it
   gets a graded record.

## For the portfolio question
Screening and the Workshop are the part of the hub a stranger could use: type an idea, see it tested against
unseen years with the bar raised for every retry. That is the piece to demo publicly (read-only examples first,
then rate-limited runs with no trading), ahead of any model page.
