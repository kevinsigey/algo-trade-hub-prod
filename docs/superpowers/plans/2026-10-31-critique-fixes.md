# Critique fixes (2026-10-31): plan and handover

Source: Kevin's `algo-trade-hub-critique-2026-10-31.md` (a signed-in crawl plus a code read at main 56c4931).

## Already true or outdated (checked 2026-10-31 night; no work needed)

- **Paper account is on.** `TRADEHUB_PAPER_ORDERS` is on, the Alpaca keys are wired (rotated by Kevin today), and the paper-orders, protect and shadow timers are installed. Portfolio is "pre-start" only because Kevin reset it to $100k today. Idea 12 (1 XLE share) is the first auto order, Mon 2026-11-02.
- **Crypto endpoints work:** `/api/shadow-performance` and `/api/quarantine` return 200, not 503. The blank `/crypto` page is a frontend fault (lane L1).
- **Sports endpoint works:** `/api/sports-edges` serves 402 picks in 1-3 s. The endless spinner is a frontend fault (lane L1).
- **Earnings dates and windows:** event studies are live (#204).

## Lanes

Each lane is one PR and touches disjoint files. "Agent" lanes go to opencode workers using the briefs in `/Users/sigey/Documents/Projects.nosync/_wt/briefs/`.

| Lane | Owner | Critique items | Files |
|---|---|---|---|
| L1 Dead pages | agent (W1 session) | §2 /sports, /crypto, /models spinner; §5 loading/error states | `market_sentiment_tool/src/pages/SportsEdges.tsx`, `components/SportsRecord.tsx`, the crypto page, `pages/Models.tsx` |
| L2 Jobs page truth | agent (W2 session) | §3 unemployment "0k jobs" units, ties labelled "We were closer", "not scored" in the denominator, undefined ±95k | `pages/JobsNowcast.tsx`, `components/ReportDumbbells.tsx` (+ the jobs API only if a unit field is missing) |
| L3 Workshop baskets | agent (new session) | §1 5-name cap, silent truncation, draft lost on reload; roadmap 6 and 10 | `tradehub/workshop/spec.py`, `playbook.py`, `draft.py`, `pages/WorkshopIdea.tsx` |
| L4 Workshop verdict clarity | agent, after L3 merges | §3 marks with no legend; benchmark not a column; chart y-axis undefined | `pages/WorkshopIdea.tsx` |
| L5 Portfolio and Ideas wiring | agent, after L4 | §3 "Pre-start" vs "Live" label, as-of = snapshot time; §2/§4 link Portfolio and Workshop both ways; public Ideas shows "N tested · X passed" from the Workshop | `pages/Portfolio.tsx`, `lib/paperPortfolio.ts`, `pages/Ideas.tsx`, `/api/ideas` |
| L6 Small labels | agent | Weather "CITIES TODAY 89" → bands; one timestamp style (CT with date) on Health | `pages/Weather.tsx`, `pages/Health.tsx` |
| L7 Short borrow and slippage | Claude (engine) | roadmap 7: `borrow_bps_yr` charged daily on short legs, `slippage_bps` per switch separate from commission | `spec.py`, `engine.py` |
| L8 Spread / z-score rule | Claude | roadmap 8: a `spread` source (A vs B log ratio) with `zscore` and `percentile` measures | `spec.py`, `signals.py`, `engine.py` |
| L9 Walk-forward | Claude | roadmap 9: rolling folds alongside the single split; pre-IPO note when the start predates a listing | `engine.py` |
| L10 Health | agent | roadmap 19: Scan and Settle write a run record; Health shows them | the scan/settle jobs, `/api/health`, `pages/Health.tsx` |

## Kevin's calls (do not build without a yes)

- **Machine API keys and an order/intent endpoint** (roadmap 4). This is security-sensitive and a new order path.
- **Rotate the 4 keys** named in BLOCKERS (roadmap 2). Kevin does it himself with `scripts/set-vps-secret.sh NAME`.
- **Publish FAILs or not.** Publishing is Kevin's choice per idea; L5 only adds honest counts.
- **Prune the 93 remote branches; PRs #172 and #184** (#184 is gated on Kevin). Deleting branches can't be undone.
- **The labor scoreboard figure** (0.1792 vs 0.17391 in BLOCKERS). Recompute from the scoreboard job, not by hand. It needs a look at which run is stale.
- **Canonical scoreboard and home summary** (roadmap 11, 15, 16), **retiring the legacy backend** (18) and **rewriting the docs** (18). These are design work: brainstorm first.

## Review and merge rule (for whoever picks this up)

1. A worker opens a PR and asks CodeRabbit. Wait for CodeRabbit's review of the head commit.
2. Check `gh pr view N --json files,commits` and read the diff. Workers drop newlines (statements joined on one line) and skip tests, so read every changed line.
3. Run the gates on the branch in a worktree:
   - `.venv/bin/python -m pytest -q`
   - `ruff check --select F tradehub tests`
   - in `market_sentiment_tool`: `npx tsc --noEmit -p tsconfig.app.json`, `npx eslint .`, `VITE_SUPABASE_URL= VITE_SUPABASE_ANON_KEY= VITE_SUPABASE_PUBLISHABLE_KEY= npx vitest run`
4. Each fix needs a test that fails without it. Add any missing ones yourself rather than doing another worker round.
5. Merge with `/Users/sigey/Documents/Predictor-Phase34/gm2.sh algo-trade-hub-prod N`.
   - If CodeRabbit is rate-limited, Kevin allows a merge on self-review: `gh pr merge N --merge --match-head-commit <sha>`, plus a PR comment saying so.
   - Check the deploy run and the live bundle afterwards.
