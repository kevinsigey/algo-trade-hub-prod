# Guidance extraction: automatic provider cycling (2026-11-09)

Kevin's direction (2026-11-09): "can we have a way to automatically cycle the
free pool of agents between openrouter and opencode?" — and restart the
backfill extraction fleet that died in the 2026-11-09 06:10 UTC container
recreate with 237 filings stuck at `failed`, 233 of them pure OpenRouter 429s.

## The two pools

1. **openrouter** — the shipped direct route (`extract.ask_model`): OpenRouter's
   free roster with the hub's key. This is the pool that saturated.
2. **opencode** — the `opencode` CLI (pinned v1.19.5 in the image) running its
   gateway free models (`opencode/deepseek-v4.1-flash-free`,
   `opencode/glm-5.3-flash-free`, `opencode/mimo-v2.6-flash-free`), invoked the
   way the call-outlook extraction invokes it: a temp folder whose
   `opencode.json` denies every tool, prompt asks for the JSON object only.
   A genuinely separate quota from pool 1's key.

## Frozen rules

- **Attempt order is fixed**: openrouter first (it is the faster, structured
  route), opencode second. Within the opencode pool, gateway models are tried
  in roster order; the pool fails only when every model in it fails.
- **Failover, never hammering.** A pool error is classified:
  - *rate* (HTTP 429, quota/rate wording) → that pool cools down
    **RATE_COOLDOWN_S = 1800** and the filing fails over to the next pool.
  - *down* (5xx, connection error, timeout, CLI failure) → cooldown
    **DOWN_COOLDOWN_S = 600**. A missing CLI binary is a hard down: the pool
    is out for the life of the process (a binary does not appear mid-run).
  - *refused* (the pool answered but unusably: unparseable reply, empty
    content, content-filter refusal) → failover for this filing, **no
    cooldown** (the pool is healthy; the answer was not).
  401/403 from OpenRouter counts as *down* (a credential state, not a
  per-filing answer).
- **A filing is marked `failed` only after every available pool has genuinely
  refused it in that attempt cycle** (`AllProvidersRefused`; the filing's
  error text names each pool's refusal).
- **If no pool can be attempted at all** (all cooling down / hard down), the
  model call raises `PoolsUnavailable` and `extract.run()` **pauses**: the
  current and remaining filings stay `new`, the run returns its counts plus a
  `paused` detail. Nothing is failed, nothing is invented. A later cycle (the
  fleet driver's next round, the recorder's next cron) resumes.
- **No silent fabrication, ever** (standing rule): a provider error produces
  no record. Every record still passes the shipped verbatim `verify()`.
- **Provenance**: `guidance_records.model` now carries the pool prefix —
  `openrouter:<model>` or `opencode:<model>` — so which pool produced a
  record is in the data forever. (Existing rows keep their bare model names;
  the CEG row keeps `manual-verified-backfill`.)
- **Unchanged**: `run()`'s no-key gate (the hub key gates the run, as
  before), the fetch path, consensus, the store, and every guard. Cycling
  lives in the model callable `run()` already accepts:
  `guidance.providers.CyclingAsker`. The recorder cron
  (`scripts/guidance_extract.py`) and the backfill fleet driver both use it.

## Environment note (measured 2026-11-09, not assumed)

The production container holds **no opencode credential link**
(`opencode auth list`: 0 credentials) and the gateway free models did not
answer keyless within bounded probes (120 s / 210 s, two models) — the link
lives on Kevin's Mac and is not moved. So in production today pool 2 attempts
are bounded (subprocess timeout), classified *down*, cooled down, and logged;
the moment the image's environment carries a working opencode link, pool 2 is
live with no code change. The fleet therefore drains on pool 1's quota,
paced, until then.

## Production note (2026-11-09, same day)

First live round exposed an aggregation bug in CyclingAsker: ANY attempted
pool's failure was treated as a filing failure, so MU's filing was marked
failed on an OpenRouter 429 plus an opencode gateway timeout -- neither is a
refusal. The rule above is now enforced exactly: AllProvidersRefused requires
every pool attempted in the call AND every error a refusal; any rate limit,
outage, or cooling-skip raises PoolsUnavailable (pause). Two unit tests had
encoded the wrong semantics (429 + down expected a failure) and were corrected
with the code; three mixed-case tests pin the rule. MU's filing was restored
to `new`.
