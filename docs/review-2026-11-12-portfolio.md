# Portfolio page review: Nov 12, 2026 (Claude, for Kevin and Muse)

This review combines Kevin's notes on the page with a pass over the live page at 1440×900 (main book, Nov 11, 7:02 PM CT
snapshot) and `market_sentiment_tool/src/pages/Portfolio.tsx` (1,222 lines) at b870759. The order form and the
Portfolio check only render for a signed-in admin, so I reviewed those two from the source.

## Bugs found on the live page (fix first; small)
1. **Sharpe shows −10.01 after 8 trading days.** The "after 1 month" guard counts curve snapshots (65), not days.
   Count distinct trading days and show the figure only from 20 of them.
2. **Today's movers lists GLD twice** (−$44 and −$44). Movers are built from per-idea slices, not tickers.
3. **The same problem shows elsewhere.**
   - Composition shows XLU and XLV three times each, and GLD and XLP twice each.
   - "Positions · 27" counts slices. There are 20 tickers.
   - The rows add up exactly to the $83,894 long value, so nothing is double-counted. One broker position is
     split across the ideas that hold it (XLU: 111 + 59 + 52 shares, same average price).
4. **"By idea · 8 ideas" sits over 16 rows** ("12 more ideas in the full view"). The header counts one thing and the
   table another.
5. **Recent orders shows "3/3 filled" with no symbol** for a multi-leg order (already known since Nov 9).
6. **Check:** "sell GLD 26/26 filled" at 2:45 PM, yet the 7:02 PM snapshot still holds 26 GLD. That is either a
   re-buy that should also be listed, or a stale position read.

**The data for the fix already exists.** `/api/portfolio` already returns `positions_aggregate`, the positions
grouped by ticker (`tradehub/portfolio/book.py`), and the page never reads it. Use it for positions, movers and
composition, and keep the per-idea slices for the By-idea view only.

## The redesign Kevin asked for
Today everything is one grid of twelve boxes, where each box is a summary that opens a full view. Replace it with a
fixed header and three tabs.

### Header (always visible, one row)
- Net liquidation value, as today.
- **Today, split at the 4:00 PM ET close.** For example: `Today −$1,161 (−1.2%) · After hours −$84 since 4:00 PM`
  with an "After hours" tag while extended trading is on.
  - The regular-session figure is the equity at the 4:00 PM snapshot minus the prior close.
  - The after-hours figure is now minus that 4:00 PM snapshot. Snapshots already run intraday.
  - The same split goes on each position: last trade against today's regular close, from the Alpaca snapshot.
- **Two benchmarks: SPY and QQQ**, both since start and today. For example: `−3.5% · SPY −0.0% · QQQ +x.x%`.
  - Needs a `qqq_price` column on the snapshots table (one migration, Kevin's go).
  - Fill the column for existing snapshots from daily bars.
  - Add `qqq_pct` to the curve and `qqq_return_pct` / `ahead_qqq_pts` to the scoreboard.
- **A warnings strip, which replaces the Portfolio check card.** It shows only what needs attention, as chips:
  - `XLU over cap 12.4% / 10%`, `Gold cluster 13% (flag 12%)`, `Breaker 1.2% of 4%`, `Staples 15% of invested`.
  - With nothing to report it reads `All within limits · last check PASS`.
  - Clicking it opens the current sleeve bars and member table in a drawer.
  - Today the card spans two columns and is one of the biggest things on the page while saying "ok" on most rows.

### Tab 1: Book (the default)
- **Composition, readable without scrolling.**
  - One full-width stacked bar of sectors, labelled inside: Staples 15 · Cash 13 · Broad market 10 …
  - A ticker treemap under it with one tile per ticker (sized by weight, coloured by today's %), so a bad day reads
    at a glance.
  - Keep the "By idea" toggle.
  - Drop the repeated legend: the bar is the legend.
- **Positions: the account as the broker holds it. No idea information at all** (Kevin, Nov 12).
  - One row per ticker, from `positions_aggregate`: ticker and name, shares, average price, weight bar, today
    (% and $, coloured), after-hours move, and open P&L as a bar that goes left or right of zero.
  - No idea tags or chips. Ideas live only in By idea.
  - Every column sorts. A "Heatmap" switch turns the table into the treemap.
  - **Live**: rows update as positions change (see "Live updates" below). A newly opened ticker appears, a fully
    closed one disappears, and a changed quantity or price updates in place with a brief highlight.
- **By idea: where the idea information lives, as expandable rows.**
  - One row per idea: value, weight against its set size, today, open P&L, realized P&L (closed trades from the A1
    attribution) and return %. Every column sorts.
  - Each row expands to the idea's own slice of each ticker. For example, Utilities + health care expands to
    `XLU 111 sh · $4,864 · today +$10 · open +$73` and `XLV 25 sh · …`.
  - A ticker held by several ideas appears under each of them with that idea's shares only, so the slices add up to
    the Positions row.
  - The header count matches the rows. Tested ideas and discretionary trades are totalled separately at the foot of
    the table.
  - It is fed by the same live refresh as Positions.
- **Today's movers** come from tickers, not slices.

### Tab 2: Performance (its own tab, much deeper)
- **Curve:** portfolio against SPY and QQQ over 1W / 1M / YTD / All, with a drawdown band under it.
- **Daily returns:** bars for each trading day against SPY and QQQ, with best and worst day.
- **Stats:**
  - Return, ahead of SPY, ahead of QQQ, volatility, max drawdown and its date.
  - Sharpe and beta to SPY, shown once there are 20 trading days.
  - Win rate, average win against average loss, profit factor, average holding time.
- **Where the return came from:** P&L by idea and by sector over the selected range (realized plus open), as a
  waterfall from start to now.
- **Tested against discretionary over time.** The split is the most honest number on the page, and today it is one
  line under closed trades.
- **Realized P&L by week** and the closed-trade list, sortable.

### Tab 3: Trade
- **The order ticket is open on the page, not behind a button.**
  - Two tabs inside it, **Single** and **Combo (spread)**, both always live.
  - Idea picker and intent as today.
  - The ticket stays put while you look at the rest of the tab.
- **Under the ticket:** staged orders, recent orders and closed trades, each a full list. They don't open in pop-ups.
- Manual actions (the to-do list from the order gates) stay at the top of this tab, not above the whole page.

## What stays
The account rail figures (cash, buying power, margin, realized and unrealized), the book switcher, the circuit-breaker
alert and the concentration warning all stay; the last two move into the warnings strip. Kevin called Net
liquidation value fine as it is.

## Live updates
Today the page reads `/api/portfolio` once on load (`hooks/usePaperPortfolio.ts`, one GET) and never again, so
nothing moves until a reload.
- Refetch every 30 seconds while the browser tab is visible. Pause it when the tab is hidden.
- Keep showing the last data while a refetch runs; never flash an empty book.
- Show "updated 12 s ago" in the header. If a refetch fails, keep the last data and mark it stale.
- Diff rows by ticker (Positions) and by idea and ticker (By idea), so rows update in place rather than redrawing.
- **Performance metrics refresh on the same 30-second cycle** (Kevin, Nov 12). Anything that moves with price
  moves with it:
  - Header: net liquidation value, today, after hours, and ahead of SPY and QQQ.
  - Performance tab: the curve's last point is live equity against live SPY and QQQ prices, appended to the stored
    snapshots and not written back. Return, ahead of each benchmark, drawdown (current and maximum), today's
    daily-return bar, and P&L by idea and by sector all recompute from that point.
  - Stats built on daily closes (volatility, Sharpe, beta, best and worst day) include today as a provisional day,
    marked "today provisional". Its value is fixed by the 4:00 PM ET snapshot and stays put after hours. The
    after-hours move is shown separately and never enters those figures.
  - Closed-trade figures (win rate, average win and loss, profit factor, realized by week) change only when a fill
    lands. Refetch them on the same cycle, but they will usually be unchanged.
  - Compute it all on the server in the same `/api/portfolio` response, so the header, Positions, By idea and
    Performance can never disagree with each other.
- Check the snapshot job's cadence. A 30-second page refresh shows nothing new if the server only re-reads the
  broker every few minutes. If it reads live from Alpaca on each request, rate-limit it on the server (for example,
  cache for 15 seconds).

## Build notes for Muse
- Split `Portfolio.tsx` into one file per tab plus the header (`pages/portfolio/`). It is already 1,222 lines, and
  three tabs inside it would make the file worse.
- Use `positions_aggregate` from the existing payload. The only backend changes are the QQQ column and fill, and the
  after-hours split.
- Keep the visitor view working. Signed out, the order ticket, warnings strip and idea targets are hidden, as today.
- The tab is in the URL (`?tab=performance`) so it can be linked. The default is Book.
- Check it at 1440×900: the header plus the Book tab's composition should fit without scrolling.
