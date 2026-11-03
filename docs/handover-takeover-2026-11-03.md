# Handover back to Claude Code — the Muse takeover, Nov 3, 2026

Kevin took the hub back from you on Nov 3 (~11:30 CT) and handed it to Muse
"until Claude's usage is back." It is back. This document is the return
handover: what Muse shipped, what it verified live, the designs Kevin
specifically wants you to look at, what is left, and every decision Muse
made for him along the way. The previous handover
(`docs/handover-deep-dive-2026-11-03.md` + `docs/superpowers/plans/2026-11-03-handover-remaining.md`)
is still the system map; this one only covers the takeover window and what
changed since.

**State of the world:** main is at PR #345, merge `9ab795403`. Every takeover
PR is deployed and verified live (workflow conclusion + TRADEHUB_TAG +
served-payload check — the standing standard, a merged PR is not a deployed
PR). Live tag at handover: `9ab7954037d`.

## Kevin's rules that governed the takeover (still in force)

- Paper only, never real money. Don't touch the Predictor repos.
- Never read or print secrets or /opt/stack/.env values. (VPS operational
  work was pre-approved by Kevin on Nov 3; secret VALUES stay unread.)
- Ask Kevin before any prod, credential, or live-trading change, including
  switching ideas on or off or resizing them. PASS-verdict changes were
  shown before/after first (done for item 3 — he approved the standard and
  the trim explicitly).
- Failing test first; check exit codes, not just totals lines.
- Verify on the live site before saying something works.
- One PR per handover item, merged pinned to its head commit.
- paper_orders / order_switches are append-only; every new table needs RLS.
- If the docs conflict with the code, trust the code and say so.

## What shipped (PRs #338–#345, all deployed + verified live)

- **#338** — Kevin's corrections recorded in the handover doc: the "mac
  scripts" machine key stays active on purpose; the four BLOCKERS keys are
  rotated (nothing left to ask); Idea 16 lives on the big book at 8%, off
  main; the Idea 16 covered-call watch rule (below).
- **#339** — Screener rebuild. Parallel warm (`DataStore.warm`), footer
  `data_as_of`, GET /api/screening/quote/{ticker}, nightly
  `screening_warm` (deploy crontab 11:35 UTC — systemd is root-owned, deploy
  has no sudo; crontab is the established route). Cold run 9.0s → 1.7s,
  proof warm: 518 tickers, 0 missing.
- **#340 + #341** — PASS rigor + the ideas trim. See design note 1; this is
  the biggest design in the set. Census: 53 tested · 31 passed · 20 failed ·
  2 NED (was 42 passed). 22 ideas killed (record kept, reversible;
  pre-state dump at `~/workspace/hub-finish/trim/trim-prestate-2026-11-03.json`
  on Muse's box). Ideas 50 + 56 came off the $1M book; big-book auto
  activations are now exactly [16, 47, 51, 54].
- **#342** — Options calibration. See design note 2.
- **#343** — IMF PortWatch ship flow on the Chokepoints monitor. See
  design note 3.
- **#344** — natgas_daily forecaster (KXNATGASD). See design note 4.
- **#345** — Item 6 smaller fixes: protect job covers Book 2; machine API
  helpers + reads book-aware; manual-action dedupe per idea; public
  /api/health trimmed with an admin-gated full report; the GDELT pacing
  fix (design note 5); Deals ESLint `no-explicit-any` 9 → 0 with real
  output interfaces. Also under item 6: **69 merged remote branches
  pruned** (criterion: compare ahead_by == 0, i.e. tip is an ancestor of
  main — provably lossless; main and feat/market-blend protected; 31
  branches kept, all carrying unmerged commits, mostly early-era
  trading-hq/sports/plan branches).

Item 1 of the old work list (verify the first `day` orders + the fill
check) could not complete on Nov 3 by construction: `paper_order_checks`
had 0 rows because the fill check (#335) merged after that day's 14:45 UTC
run. Its proof is tomorrow's runs — see the watch list.

## Designs Kevin wants you to look at specifically

### 1. The PASS registry (`tradehub/workshop/registry.py`, PR #340)

The verdict standard is now hub-wide, computed over every idea's latest
SAVED run, and lives in one module:

- **FDR bar**: Benjamini-Hochberg q=0.05 across all latest saved runs. (A
  hub-wide Bonferroni bar is mathematically impossible at 1,000
  permutations — 0.05/63 < the minimum achievable p — which is why FDR.)
- **Walk-forward**: the claim must have held in at least half the folds;
  a run with no walk-forward recorded does not pass (legacy runs demote).
- `verdict_of(holds, p, bar, wf)` in engine.py takes the wf block;
  events.py callers pass none (unchanged behavior there). A stored PASS
  that fails either check demotes to FAIL in `verdict_now`, with the
  reason surfaced (`fdr_pass`, `wf_ok` on the public idea payload).
- **Families**: union-find over shared hold+short tickers of latest saved
  runs. The "chip family" is 8 ideas {22, 28, 37, 47, 51, 54, 56, 58}
  under one "One bet · MU · TXN" header on the Ideas tab. Standing ideas
  lead; removed ones sit in a closed "Removed under the current standard"
  section — nothing was deleted.
- **Origins + hindsight flag**: lab / screen / manual provenance per idea;
  lab- and screen-origin ideas carry `hindsight_selected` (the
  screen-to-idea path selects on today's data — the deep-dive's warning
  is now a visible chip, not a fix).
- **Gate changes in the same PR**: the 63-day go-live wait is RETIRED (the
  claim is judged on whatever new data exists; only zero new data waits,
  `needed: 0`). The agent gate counts attempts per spec
  (variations=attempts, seed derived) so a blocked spec can't silently
  re-roll — the blocked→draft return path remains as Kevin's explicit
  override.
- **Kill-any-idea (PR #341)**: migration `20261103000004` (prod row 48)
  rewrote the `ideas_lifecycle_once` trigger WITHOUT the old live-only
  clause; set-once semantics otherwise preserved. The kill endpoint 409s
  only on already-killed.
- GET /api/ideas is cached behind a mutation fingerprint + 30s TTL
  (the 7.6s unauthenticated read from the deep-dive).
- Run records now stamp `result["registry"] = {test_number, tests_before}`
  at insert — every verdict can cite which test of how many it was.

When a new idea PASSes, it enters the FDR family automatically and can
demote others. That is intended; watch the census when the lab runs again.

### 2. Options calibration (`tradehub/workshop/calibration.json`, PR #342)

Built to the Oct 31 options design §2: IV inversion, a skew curve fitted to
Alpaca's real 2024–25 prices and checked on 2026, half the typical spread
charged on every option trade in `leg_returns`, and a shipped calibration
record that verdicts quote (median error + spread per underlying;
underlyings outside the set are labelled uncalibrated on the verdict).

**The decision to know about: the skew was REJECTED by the data.** Three
fits (pooled quadratic, linear on premium≥$0.25, robust bucket-median) all
made out-of-sample errors worse on 8–9 of 9 underlyings; bucket medians
show no monotone moneyness pattern in daily closes (the vol indexes
already average the strip, and daily closes are stale). Shipped
coefficients are ZERO with the reason recorded in calibration.json's
`fit_form`; the `skew_factor` machinery stays live in the pricing path
for a future intraday-quote fit. What bites today: charged spreads
(SPY 1.45% of premium … EEM 15.73%, half on opens and both roll sides)
and the quoted median errors (SPY 27.4% of premium, n=149; NVDA best at
7.7%). Regenerate monthly-ish with `tradehub/scripts/options_calibrate.py`
(4,129 usable contract-days last run). The design's early-exercise/
assignment item was NOT in scope and is untouched.

### 3. PortWatch ship flow (`tradehub/geo/portwatch.py`, PR #343)

- Source: IMF PortWatch `Daily_Chokepoints_Data` ArcGIS FeatureServer.
  Hormuz = **chokepoint6**, Bab el-Mandeb = **chokepoint4**; full daily
  series 2019 → 2026-10-25, published WEEKLY with a ~9-day lag. Terms:
  IMF data terms, attribution required (the UI carries it).
- **The endpoint is intermittently broken, not dead**: ~half of GETs
  return 400 "Invalid URL" or hang (this reproduces the deep-dive's
  finding); POST always times out. Production pattern: per-page retries
  with backoff + last-good cache file (`/cache/chokepoints/portwatch.json`,
  last 400 days kept). Daily pull via deploy crontab 11:47 UTC
  (`tradehub.scripts.portwatch_pull`); a failed fetch keeps that
  chokepoint's prior rows.
- `region_view` gains a fail-soft `flow` block; the Oil page shows a Ship
  flow strip (divs/spans only — the Oil copy budget). Only the hormuz
  slug is mapped (`PORTID_BY_SLUG`); Bab el-Mandeb data is verified in
  the cache pulls but the hub has no second region to display it on.
- First readings (through Oct 25): Hormuz tankers 0.86/day vs 1.0
  baseline (AIS-visible floor — reads essentially closed); Bab el-Mandeb
  9.57/day vs 8.5 (+12.6%).
- Deliberately NOT done: wiring flow into geo_events / the geo shadow.
  Source + baselines + display landed first; the shadow wiring is a
  separate, gated step (the shadow's 200-settled promotion rule applies).

### 4. Natural gas daily (`engines/natgas_daily.py` + `journal/forecasters/natgas_daily.py`, PR #344)

- KXNATGASD settles on the **Pyth NATGAS index at 17:00 ET** (verified
  from the series' own settlement sources; ~60 `greater` strikes, $0.005
  steps near the money). Construction is the hourly-WTI engine at a
  daily grain: Normal centred on the live **NG=F** print (`data/natgas.py`),
  sigma = trailing stdev of Kalshi's own settled DAILY changes counting
  only exactly-one-day-apart pairs, scaled by sqrt(minutes/1440);
  DECISION_LEAD 125 min so the hourly journal run freezes inside the
  window; stale print (>30 min) is a gap, never a forecast.
  GAS_RESOLUTION = 0.001 (the Pyth print's thousandths).
- Rows registered: `natgas_daily@natgas-v1`, kalshi_implied,
  persistence baseline, and the w25 cautious pin from day one.
- The futures-vs-index basis (NG=F anchor vs Pyth settlement) is stated
  in the engine docstring and left for the graded record to measure —
  the CL=F precedent.
- **NOT in v1, deliberately**: EIA weekly storage (needs a free EIA API
  key — Kevin's to register; a weekly level input, not a launch blocker)
  and the degree-day weather tilt (`/cache/degree-days.json` exists).
  Either returns as its own shadow row graded against v1.
- **First freeze expected Wed Nov 4 ~20:15 UTC** (the Nov 4 event).
  Verify a natgas_daily row lands in journal_forecasts; if it doesn't,
  the freeze window/lead is the first suspect.

### 5. Item-6 designs (PR #345)

- **Protect per book**: `paper_orders_protect.run()` now loops books like
  `check_fills` always did — per-book context, main reads idea rows,
  other books read activations (the morning runner's split), rows logged
  with the right `book`. Summary contract deliberately kept: main's
  entries flat, other books nested under their name.
- **Machine API**: `stop_capacity` / `broker_orders` take a book; the
  three machine READ endpoints accept `?book=` (422 unknown). Placement
  is UNCHANGED (main-only) on purpose — see design 6.
- **Health split**: public /api/health drops the `history` matrices
  (63.6KB → ~13.6KB); the full report is admin-gated at
  /api/health/full; the Health page fetches full (lazy admin-token
  import so public pages don't pull the supabase chain), the HQ strip
  stays on the public read.
- **GDELT pacing (the real bug behind the 11 Health problems)**: all 11
  sector news-tone families had frozen ZERO forecasts, ever. GDELT
  throttles unpaced multi-basket bursts; refusals fell back to an
  ever-staler cache until the newest tone day (Oct 27 on Nov 3) aged
  past the forecasters' 4-day staleness bound and every forecast became
  a by-design silent gap. `fetch_timeline` now paces process-wide (6s —
  GDELT asks 5) and retries a refusal once. The cache heals on the next
  refresh (full-window refetch). **Verify on Nov 4: the tone families
  should freeze in the morning journal runs for the first time.** If
  they still don't, the next suspect is GDELT refusing the VPS's shared
  egress IP outright — the refusal text names high-traffic users.

### 6. DESIGNED, NOT BUILT — the big-book machine key (Kevin's ask, Nov 3)

Kevin, in the Trading Thesis Testing chat (~1:22 PM): "can you make your
own key for the big book since ill be asking you to make trades?" Today a
machine key cannot name a book: key rows carry scopes + caps only and the
order route submits to the main book. (That is why Book 2's IBIT buy on
Nov 3 went the admin route while Book 1's filled through the machine API —
136 IBIT @ $43.86, sitting in Book 1 as a manual/blended position at ~6%.)

The specced build (agreed shape, sequenced after the Book 2 fix — which
is now done): add a `book` column to the machine keys (existing keys stay
bound to main), thread the key's book through order placement, portfolio
read, order read/cancel, and the stop-capacity fence; caps stay per key.
Item 6's book-aware helpers and `?book=` reads are the on-ramp, NOT the
build — placement still needs the key binding so one key can't reach
both books. When it lands, mint Muse's own key bound to the big book.
Until then, Book 2 machine trades route via the hub chat / admin route.

### 7. DESIGNED, NOT BUILT — the autopsy + bounded-iteration loop

Also from the Trading Thesis Testing chat (~2:08 PM, Kevin: "Hand the
autopsy + bounded-iteration spec to the hub chat"): a self-improving
research loop adapted from Ray Fu's public guide ("How to Build a
Self-Improving AI Trading Research Loop", raycfu.com) — research agents →
strategy code → hostile backtest → paper trading behind a code-level kill
switch → bounded weekly iteration, with an "autopsy" step that dissects
dead strategies before the next iteration. The full spec text was
addressed to the hub chat; it had not landed in this chat's transcript
when this handover was written, so treat this paragraph as a pointer:
get the spec from that chat before designing anything, and do not
improvise its details. It is a design review item, not a build order.

### 8. NOTE FROM KEVIN — make the next-hour predictor even easier to read

Kevin's words, added at his request as he handed the hub back: **try to
make the next-hour predictor even more easy to read.**

Context so this doesn't get over- or under-done: the Oil page's live hero
(the hourly WTI prediction: `oil_live.live_ladder`, the DirectionChart,
the lean banner) is already the design Kevin confirmed on Nov 3 — live
30s-polling hero, frozen record behind a dropdown, full ladder under
"All strikes". He is not asking for a new model or a redesign from zero;
he wants the existing predictor to read at a glance. Direction: one
unmissable headline read (which side of the market's level we're on, by
how much, in plain words), fewer competing numbers at the top level, the
"how to read this" affordance kept, and the standing rules intact —
chart labels never overlap (collision-checked), the Oil copy budget
(≤60 words across h1/h2/h3/p/summary elements; extra copy goes in
divs/spans), no infinite scrolling, detail behind dropdowns. The price
itself is still Yahoo's delayed CL=F tape (~10–15 min) until the Pyth
key exists (Kevin's open decision below) — the staleness caption stays
honest about that.

## Watch list — dated, in order

- **Wed Nov 4, 12:30 UTC** — first `day`-order paper run. Plans: main
  Idea 42; big Ideas 16 (8%), 47, 51, 54 (1% each). Ideas 50/56 are
  killed and must NOT appear. **Idea 16 watch rule (Kevin's, from #338):
  ~106 SPY shares, then the covered call — if the call is refused
  because the shares hadn't filled, check the next morning's run places
  it; if it doesn't, fix with a failing test first, so the call is only
  sent once the shares are held.**
- **Wed Nov 4, 14:45 UTC** — first fill check with real `day` orders:
  `paper_order_checks` gets its first rows (handover item 1's missing
  proof). The protect pass now also covers Book 2 (PR #345) — watch its
  first big-book pass.
- **Wed Nov 4, morning journal runs** — first-ever news-tone freezes
  expected (design 5). **~20:15 UTC** — first natgas freeze (design 4).
- **~Nov 8** — machine-order caps revisit (qty 100 / $25,000 / 50 per
  day), scheduled when the machine door opened.
- **Mon Nov 9, 15:00 CT** — Kozmino AIS coverage probe verdict. A cron
  (`kozmino-probe-verdict`) delivers it into Muse's hub chat; Kevin has
  asked twice to be flagged the result. It gates any Chokepoints v1.5
  (Pacific-Russia) build — do not start one before the verdict.
- Ongoing: geo shadow (oil_wti_hourly v2-geo) grading toward its
  200-settled paired-Brier gate (68 settled at Nov 3 ~01:00 CT; Kevin
  decides promotion; nothing auto-promotes). Oil ITM line record
  accumulating since Nov 3 (GET /api/oil/itm-record). ens-v2.1 weather
  promotion gate stands at ≥200 newly settled per family, paired Brier
  vs v1 and Kalshi, Kevin decides.

## Decisions Muse made for Kevin (his instruction: list them)

1. **Skew rejected** (design 2): three fits worsened out-of-sample
   errors; shipped zero coefficients with the machinery retained,
   rather than shipping a curve the data refused.
2. **Item 3 standard presentation**: Kevin approved "FDR + walk-forward
   ≥ half" and the trim before execution — but the CHOICE of which
   standard to present first (and the Bonferroni-impossibility
   explanation) was Muse's. The trim then executed exactly as approved.
3. **Item 6 scope**: protect/machine-reads/dedupe/health/GDELT/ESLint
   done; journal rollups, sector-limit enforcement, slippage and
   shadow-vs-fill measurement, the 76-except sweep, the api/main.py
   split, and the legacy-backend retirement deferred — slippage needs
   fills that only exist from Nov 4; the rest are design/decision-sized,
   not smaller-fixes-sized. The stale labor figure needed no fix: a
   Nov 1 PIT re-run had already superseded it (live scoreboard serves
   0.18234 vs 0.16903, n=383).
4. **Machine placement left main-only** in item 6 (design 6): reads went
   book-aware, placement waits for the key-binding build, per the
   sequencing Kevin set on Nov 3.
5. **natgas constants**: GAS_RESOLUTION 0.001 and DECISION_LEAD 125 min
   (design 4), and PortWatch display wired for the hormuz region only.
6. **Branch prune criterion + execution** (69 deleted): ahead_by == 0
   only; anything with unmerged commits was kept, including branches
   whose work shipped via other routes in the early era.

## Kevin's open decisions (do not act unasked)

- PR #172 (market-blend study) — still open, his call.
- The stray merge in the namesake repo `kevinsigey/algo-trade-hub`
  (ship.py slug accident, Nov 1) — revert or leave, his call.
- Legacy backend retirement (`market_sentiment_tool/backend`) — needs
  his explicit go as its own proposal.
- **Pyth API key** — Kevin chose "get a Pyth API key for a real-time
  print" on Nov 3 for the oil hero (Hermes needs a key; feed WTI1M
  `f2464139…`). His account to create; the key would land via
  `scripts/set-vps-secret.sh` as PYTH_API_KEY. It would ALSO serve the
  natgas live anchor (same settlement source family). The frozen
  journal record stays on CL=F regardless — only the live ladder
  switches.
- **EIA API key** — his free registration unlocks the natgas storage
  enhancement (design 4).
- Journal growth: DB is 238MB, ~22.7k journal rows/day (~4MB/day).
  Rollups/archival are a design call when he wants it.

## Working notes (the expensive lessons, so you don't re-pay them)

- Ship via `~/workspace/icons/ship.py`; repo slug is
  `kevinsigey/algo-trade-hub-prod` — copy it from the shipping clone's
  `git remote -v`, never from memory. ship.py merges internally, pinned
  to the head it created; a PUT merge can 405 while checks are
  "unstable" — read the PR state and retry when CI settles.
- Gates on the EXACT shipped tree, after the final edit: full pytest
  (check the exit code), full single-invocation vitest with
  TMPDIR=/home/hatch/workspace/.tmp (the 512MB /tmp tmpfs ENOSPCs),
  `tsc --noEmit -p tsconfig.app.json`, ruff F-select at the **9-error
  pre-existing baseline**. Follow-up edits after a gate invalidate it.
- Back-to-back PRs touching the same files from the same base can drop
  the earlier PR's hunks — marker-check every shared file on merged
  main. Rebuild graphify before shipping; remove the node_modules
  symlink first.
- Deploy verification is three-legged: workflow "Build and deploy Trade
  Hub" conclusion for the merge SHA + TRADEHUB_TAG in /opt/stack/.env +
  a served-payload marker. Background pollers have reported stale
  results before — verify from the tag and the payload.
- Worktrees from Muse's session live under `~/workspace/hub-finish/`
  (screener-wt, pass-wt, kill-wt, calib-wt, flow-wt, natgas-wt, fix-wt);
  branch them from a freshly fetched origin/main — `main-clone` there is
  STALE (its HEAD sat at #337 with an uncommitted handover-doc edit) and
  the `repo` clone carries uncommitted changes. One lane per worktree.
- Supabase SQL CLI: `~/workspace/custom-connectors/custom.legacy-supabase/bin/supabase-sql
  --project-ref wuhpbvgidnrrdndhkehl` with
  PYTHONPATH=/opt/muse/skills/custom-connector-setup/bin and NO_PROXY
  set; only the last statement's result returns; chunk long statements.
  Migrations are recorded in docs/superpowers/plans/migrations-applied.md
  (test-enforced); prod watermark is row 48
  (`20261103000004_kill_any_idea.sql`).
- VPS: deploy has docker but NO sudo; systemd units are root-owned, so
  new schedules go in deploy's crontab + docker exec (screening_warm
  11:35 UTC, portwatch_pull 11:47 UTC are the newest). Never
  wholesale-sync /opt/stack/compose.yml. Container file moves go via
  /opt/stack/volumes/tradehub-cache/ (= /cache), not docker cp.
- OpenRouter rejects a `models` array longer than 3 — every caller caps
  at [:3]. Gemini stays on the free tier (20 requests/day/model).
- Known-flaky under load (pass solo): App.shell route-change, one
  Portfolio order test, Workshop draft fallback + live-paper gate,
  CalibrationCurve, RequireAdmin menu, test_workshop_exits,
  Portfolio treemap-label race.
