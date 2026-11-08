# Handover — Muse, Sun Nov 8, 2026

Claude is near its usage limit. Muse takes over everything below. Rules unchanged from
`docs/handover-2026-11-04-muse.md`: paper only; never read or print secrets or `/opt/stack/.env`; ask Kevin before prod,
credential or live-trading changes; failing test first; verify on the live site, not just green tests; merge pinned to
the head (`gh pr merge N --merge --match-head-commit <sha>`) after CodeRabbit (trigger it with a `@coderabbitai review`
comment); no paid Claude API anywhere; runtime model work uses free models only.

## Merged and live this weekend (Nov 6–7)
- #398 orders: a second idea skips a symbol another idea already traded the other way in the same run (Alpaca's
  "potential wash trade" 403). #400 single-leg option orders are re-priced at send time to the bid (sell) / ask (buy);
  the pre-open mid kept expiring (NVDA261204C00200000 close, Nov 5 and Nov 6). Both run first at the Mon Nov 9 12:30 UTC
  order run.
- #399 the 15-minute trade-rule record sits in a dropdown on Strategies.
- #401 Hormuz: PortWatch tanker transits compared with a year ago (0.86/day vs 50.2, −98%); blind AIS tiles say
  "Not visible live". #402 order layer gains stop_limit, extended-hours day/gtc limits (gtc still needs a sanctioned
  protective tag) and `can_short`; nothing calls them yet.
- Guidance recorder crontab installed by Kevin in the deploy user's crontab (weekdays: poll */15, extract at :05/:20/:35/:50
  under `flock`). First run Mon Nov 9; 35 filings were queued.

## Open PRs
- **#404** 15-min rule read-outs: `futures_open()` split (trading vs closed hours) and a distinct-window count. Read-outs
  only. Tests pass. Waiting on CodeRabbit, then merge and check `/api/oil/fifteen-rule` has `by_session`.
- **#403** research: earnings-call TONE backtest, preregistered, **FAIL** on 3,445 calls (holdout IC 0.005, t 0.14).
  Research files only. Merge after CodeRabbit. Branch `research/call-tone` also carries the outlook work below; merge
  #403 as is and open a separate PR for the outlook work when it has results.
- #172 (old study) — not ours, leave it.

## Check Monday
1. 12:30 UTC order run (`paper_orders` for 2026-11-09): no GLD "wash trade" manual action; any crossing shows as
   skipped "crossed with idea N's …"; the big-book NVDA/SPY option orders fill instead of expiring. Open manual actions
   16–18 (GLD, NVDA, SPY) can be resolved once they do.
2. Guidance recorder: `guidance_filings` rows leave `new`; `guidance_records` gain rows; spot-check quotes. Known noise:
   percentage growth parsed as EPS (DUK), prior ranges stored beside raises (GEV), results-table EPS (INTC).
3. 15-min rule: the forward record so far is 13 trades, all Friday Nov 6 evening after the CME close, about 7 separate
   windows. Do not call it promising until weekday (futures-open) trades accrue; #404 shows the split.

## The main open job: earnings-call outlook backtest (Kevin's priority)
Kevin wants a strategy that reads a call for real forward statements (margins, revenue, costs, tariffs, guidance
raised/cut) and trades long AND short, stocks and options, with exits, built on Strategy HQ doctrine:
`/Users/sigey/Downloads/strategy-hq-full-detail-spec.md` (trade the forward file, not the headline beat; species
routing: overshoot → bounce long, bleed → drift short, structural → no trade or defined risk; "generic drift
continuation" died in round 2, so test it before trusting it) and `/Users/sigey/Documents/IB Python Models`
(`relative-guidance`, `relative-forward-file`, `Studys/1_earnings_event_study.ipynb`).

Step 1 (in progress) is the preregistered test: `docs/superpowers/specs/2026-11-07-call-outlook-prereg.md` in worktree
`/Users/sigey/Documents/Projects.nosync/_wt/call-tone` (branch `research/call-tone`, head `44703f8`). Do not change
its rules; the Nov 8 amendment (guidance/capex topics, stated-comparison direction) was made before any result.

State: code is in `research/call_outlook/` (statements.py, extract.py, run.py; tests `tests/test_call_outlook.py`, 14
pass). Extraction goes through the opencode CLI (`opencode run -m openrouter/...`), which holds its own OpenRouter link.
The local shell `OPENROUTER_API_KEY` is dead (401); do not use it. Each run sits in a temp folder whose `opencode.json`
denies every permission and tool; transcripts are untrusted text, so keep that lockdown. The pilot's tags were checked by
hand and are good (directions come from stated comparisons; bare ranges are flat).

**The full run is NOT running.** Four shards were started Nov 8 and died with Claude's session before writing anything.
Restart them detached so they outlive the session (from the worktree root):

```bash
cd /Users/sigey/Documents/Projects.nosync/_wt/call-tone
for i in 0 1 2 3; do OUTLOOK_SHARD=$i/4 nohup /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m research.call_outlook.run extract > research/call_outlook/cache/run-$i.log 2>&1 & disown; done
```

It is resumable (per-shard `cache/extractions-{i}of4.jsonl`; all shards are read on resume). Pace was about 2.4 min a
call on one process; ~3,445 calls. Watch `grep -c Failed cache/run-*.log`; opencode-gateway models fail fast when their
daily pool is spent and OpenRouter models carry the run. If OpenRouter's free daily cap bites, it just resumes the next
day. Spot-check 10 calls' statements against their quotes after the first ~40.

When extraction is done: `python -m research.call_outlook.run evaluate` writes `research/call_outlook/RESULTS.md` with
PASS/FAIL per the spec (holdout 2022+, 60 days vs SPY, IC > 0, t ≥ 2, long book and short book each positive after
0.20%). Check `evaluate` on a handful of rows first (it was written by a free worker; the call-id date parse was already
wrong once and fixed). Report the result to Kevin as is.

Step 2, only after step 1: a preregistered species test combining the extracted forward file with the day-1 reaction
(overshoot → long +5 days; bleed, including beat + guide cut → short +20 days), stocks first, options only where the
implied move is mispriced. Then shadow, then paper. Needs historical EPS consensus for "beat" (not in the transcript
dataset; earnings_events.csv in the IB folder has 167 prints; Alpha Vantage EARNINGS has full history but no server key).

## Worker lessons from this weekend
- Free workers stop mid-task and report DONE; resend "continue" to the same session.
- One free worker faked results: on an OpenRouter 401 its code returned invented "[MOCK]" statements. Grep every worker
  diff for mock/fake/dummy/placeholder in non-test code.
- Another loosened a safety rule (gtc orders skipping the sanctioned-tag check). Read the diff, do not trust the report.
- Alternate OpenRouter and opencode models in `OC_MODELS` so one pool's limit costs one retry.
- Workers run from `/Users/sigey/Documents/Predictor-Phase34/scripts/oc-send.sh <ses_id> "<prompt>"` launched from
  `/Users/sigey/Documents/Projects.nosync`, `OC_NO_CR=1` for tasks that open no PR.

## Not reachable by Claude
Auto mode blocks Claude from ssh/crontab reads on the VPS; Kevin runs server commands himself. Write temp files to `~`,
not `/tmp` (a `/tmp/cron.bak` owned by another user exists).
