# Model review — Nov 9, 2026 (Claude, for Kevin and Muse)

Source: the live `/api/journal` scoreboard at 23:15 UTC. 175 scoreboard rows = 100 models and variants, 29
market-implied reference rows, 46 naive baselines. 53 models have 30 or more settled forecasts; 47 have fewer.
"Gap" below is our Brier score minus the Kalshi market's on the same forecasts: negative means we beat the market.
z = gap / its standard error. Stock ideas and the earnings-outlook work are not in this table and are not covered here.

Not checked: whether the standard errors account for forecasts made on the same day moving together. If they do not,
every z below is overstated.

## The headline
**On the Kalshi scoreboard, almost nothing beats the market price.** Of 53 measured models, 3 beat the Kalshi price;
2 of them are the same rain model. The other 50 are level with or worse than the market, 27 of them at z > 2. This
covers the forecast models only (not stock ideas or the earnings-outlook work), and a gap that is not significant is
"no difference shown", not proof of equality.

## What the table says, by family

| Family | Best row | Verdict |
|---|---|---|
| Weather: rain | `weather_rain` ens-v2.1: gap −0.021, z −2.6, +14¢ a simulated trade over 69. Its 25% blend: z −3.5. | The one statistically real skill in the hub. Held in SHADOW only because a calibration bucket has under 20 forecasts. |
| 15-minute: natural gas | `natgas_15m`: gap −0.0015, z −0.2, +8¢ a trade over 249. PROMOTED. | Accuracy not shown to differ from the market; the money comes from picking moments. Under-confident: says 65%, happens 72%; says 75%, happens 82%. |
| 15-minute: WTI, Brent | gap +0.006 (z +2.0), +0.003 | Slightly worse than the market. The trade rule's WTI/Brent profit is not backed by model skill. |
| Oil hourly (5 versions live) | v4: gap +0.003. v6 (newest): +0.006. v1, v2, v5: +0.022 to +0.024, z ≈ +10. | Six iterations have not beaten the market; the newest is worse than v4. |
| Crypto hourly | BTC gap +0.0015, ETH +0.0035, both z > 2 | 29,132 of BTC's 29,670 scored forecasts sit in the 90–100% bucket (far strikes that are never in doubt). About 540 were real calls. |
| Weather: high, low temps | gap +0.04 to +0.08, z +6 to +11 | Clearly worse than the market in every version, including the NBM variants. |
| Sports | All level or worse; the `+cal` variants are worse than the raw feed | The calibration step hurts on these sample sizes. |
| Daily oil, Brent, natural gas, gasoline | Brier 3 to 8 times the market's (skill −3.0 to −7.6) | Broken, not just unskilled. |
| ERCOT peak | gap +0.051, z +4.4 | Worse than the market. |

## Five structural findings
1. **The 134,212 "scored forecasts" headline is mostly easy strikes.** Crypto hourly alone is ~76,000 of them and
   ~98% are near-certain. Count contested forecasts (say 10–90%) instead; the honest number is a few thousand.
2. **The "cautious" variants hint at the answer, but do not measure it.** Blending 25% model with 75% market beats
   the raw model in nearly every family (rain is the exception: the raw model beats its own blend). That shows the raw
   models are over-weighted; it does not show the best weight is zero. Fit the weight per family on one period and
   check it on another.
3. **Profit without accuracy needs two checks.** natgas_15m makes money in simulation at market-level accuracy. That
   is a real timing edge (Kalshi's 15-minute quotes lag the futures), unfillable quotes, or luck over 249 trades. The
   minute tape started Nov 6 can test the fills (record the size on offer at the decision minute); the forward record
   with its 95% range tests the luck.
4. **Version sprawl is silent multiple testing.** Five oil-hourly versions and three weather-high versions all score on
   overlapping data. With 100 models, two or three at z < −2 are expected by luck alone; only the rain blend (z −3.5)
   clears that.
5. **47 models have under 30 settled forecasts** and add rows without adding evidence.

## What I would do
- **Promote rain to a real test.** Fix the bucket technicality (merge thin buckets for the gate), preregister a paper
  rule, and check how many rain markets Kalshi lists a day, since that caps what it can earn.
- **Run the fill check on the 15-minute family** before the 300-trade bar means anything, and recalibrate natgas_15m
  (it is under-confident, which costs trades).
- **Retire, keeping the record:** daily oil, Brent, natural gas and gasoline; weather high and low (all versions);
  sports `+cal`; oil-hourly v1, v2, v5; ERCOT. That removes about 25 rows and their compute.
- **One live version per model.** A new version replaces the old one on a stated date; the old one stops scoring.
- **Change the headline metric** to contested forecasts and "models beating the market", clustered by day.
- **Put new effort where the hub has its own information:** the earnings-call outlook parse, the Hormuz stress read
  (already widening the oil range in shadow), and the stock ideas. The price-only models have had their test.
