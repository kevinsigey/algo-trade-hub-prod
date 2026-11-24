# Hub design rules (Kevin's, binding)

These are product requirements, not taste. **Every agent that touches `market_sentiment_tool/src/` reads this file first**, and every UI brief quotes the "Hard rules" section. CodeRabbit checks frontend PRs against it (`.coderabbit.yaml`). When Kevin states a new rule, add it here in the same PR, with the date and source.

## Hard rules

1. **Nothing overly scrolling.** No page is a long scroll of text or stacked sections. Every page and tab fits about one 1440×900 viewport at its default state. Detail lives behind a click (expand in place, or open a full view), never as more page. *(Kevin, Nov 3, Nov 13, Nov 16, Nov 24)*
2. **Dashboard, not document.** A section is a grid of cards or a compact list. Each card or row leads with **one number or a small chart**, plus a few quick stats. Click or Enter opens the full chart and table (`DashCard` → `FullView`, or an in-place expand). *(Kevin, Nov 13: "an actual dashboard ... no scrolling to read long lists")*
3. **Lists show at most 5 rows** on the page (`PeekRows`/`PEEK`). The rest sit behind "Show all", which opens a full view and never grows the page. Nothing is paginated away or dropped. *(Nov 13)*
4. **Aggregate first.** Totals, rates, verdict; per-item detail only on request, or when an item needs Kevin's action. *(Nov 3)*
5. **Lead with the live or biggest thing.** Live models get a clear, always-open graph at the top; shadows and trials go below. *(Nov 3, Nov 24)*
6. **Never silently cut detail.** When shortening a page, move detail behind a click or onto its own page. Don't delete it. *(Nov 3)*
7. **Change only what was asked.** A request to fix or extend a section is not a licence to redesign the page. If a bigger change seems right, propose it first. *(Nov 24, after #599)*
8. **Numbers first, little prose.** One-line descriptions; copy budget of about 60 words of visible prose per view (headings, paragraphs and summaries). Explanations go in tooltips (`hint`) or the full view. *(Oil page rule, Nov 3)*
9. **A missing figure is a dash or a word, never 0.** Never show stale or last-known data as live; stale data carries its as-of time. *(standing)*
10. **Charts:** labels never overlap (collision-checked); the legend is the chart where possible, with no repeated legends. *(Nov 3, Nov 12)*
11. **Phone width works.** At 375px there's no horizontal page scroll; grids collapse to one column; the hard rules above still hold. *(standing)*
12. **Money is labelled.** Anything real-money carries the rose REAL MONEY badge; account-derived dollars appear only for the signed-in admin. Public routes carry no account-derived figures. *(Nov 20, Nov 24)*

## Building blocks (reuse; don't reinvent)

- `DashCard`, `PeekRows`/`PEEK`, `Spark`, `MiniBars`, `Fig`, `Segments`, `FilterBox`: `src/pages/portfolio/shared.tsx`
- `FullView`, `Panel`: `src/components/Panel.tsx`
- Badges: `Chip`, `LiveChip`, `GateBadge` in `src/components/`
- Palette: Tailwind slate surfaces; emerald for positive and live; rose for negative and real money; amber for demo and warnings; sky for "recording" or neutral status. No new colours without a reason in the PR.
- The reference implementations are the Portfolio tabs (Book, Performance, Trade) and the Kalshi live book card.

## Review checklist (paste the results in the PR body)

- [ ] Default view fits 1440×900 without scrolling past one screen (screenshot attached).
- [ ] 375px: no horizontal scroll; still no long scroll (screenshot attached).
- [ ] Lists capped at 5 rows with "Show all".
- [ ] Every card or row opens to its full detail; nothing was dropped.
- [ ] Only the parts that were asked for changed.
- [ ] Missing values show "—"; no stale data presented as live.

## Sources

`docs/handover-deep-dive-2026-11-03.md` (presentation rules), `docs/handover-takeover-2026-11-03.md` (Oil page rules), `docs/review-2026-11-12-portfolio.md`, `docs/review-backlog-2026-11-12.md` rows 62 and 83, and Kevin's Nov 24 verdict on PR #599. Muse is adding the rules it holds (issue #524).
