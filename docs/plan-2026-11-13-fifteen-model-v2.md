# 15-minute model v2: scoping (Claude, Nov 13; docs only)

Kevin (Nov 13): use long 1-minute history to train a better 15-minute model. This is the scope. It writes no code.
**The data source is pending Kevin's choice** (see "Data"), and nothing gets fetched until he picks one.

## Facts this rests on (checked Nov 13)
| Series | First settled market (Kalshi public API) | Settled to Nov 13 |
|---|---|---|
| KXWTI15M, KXGOLD15M, KXSILVER15M | 2026-07-31 18:15 UTC | 7,339 / 7,048 / 7,013 |
| KXNATGAS15M, KXCOPPER15M | 2026-08-27 20:45 UTC | 5,474 / 5,148 |
| KXBRENT15M | 2026-10-21 20:30 UTC | 1,595 |

- Markets settled before **2026-09-13** (Kalshi's historical cutoff) are served from the `/historical/...` endpoints.
  `kalshi_history.KalshiHistoryClient` already merges both.
- **Settlement rule:** YES if Pyth's 1-minute close at window end is at least Pyth's 1-minute close at window open.
  - Oil, gas, gold, silver and copper use PYTHOIL, NATGAS, GOLD, SILVER and COPPER respectively.
  - **Brent's first market used a fixed strike** (105.84) instead of the open close, so check Brent's strike rule per
    market.
- **Edge history therefore starts Jul 31, Aug 27 or Oct 21, 2026.** Anything older can only measure model accuracy, not edge.

## Data (pending Kevin)
| Source | Covers | 1-minute depth | Terms |
|---|---|---|---|
| Dukascopy bi5 | all 6 (CFDs) | 2003–2013 onward | Website ToU §3–4: automated access needs prior express written consent; no database building; personal and non-commercial use only. **Blocked until Kevin has written consent.** |
| Binance Vision USD-M perps | XAUUSDT (from 2025-12-11), XAGUSDT (2026-01-07), CLUSDT, BZUSDT, NATGASUSDT (2026-04-01), COPPERUSDT (2026-03-06); klines and aggTrades; daily files lag about 1 day | covers the whole Kalshi era for all 6 | CC BY-NC-SA 4.0 plus the Vision Dataset Terms (Aug 26, 2026). §4.1 allows backtesting only "for purely personal non-production research"; §4.2 bars use for "live proprietary trading execution". **Kevin decides whether this use fits.** |
| HistData.com | gold, silver, WTI, Brent (no gas, no copper) | about 2009 onward | No terms-of-use page; the FAQ says "no warranty… use the data at your own will and risk". Free downloads go through a web form; automated updates are a paid subscription. Timestamps are EST with no DST. |
| Hyperliquid archive (#517) | all 6 (the live anchor tape) | from Nov 9, accruing | already in use |

## 1. Target
- Predict exactly what the contract pays: `close(window end) ≥ close(window open)` on 1-minute closes, for windows
  aligned to :00/:15/:30/:45.
- **Synthetic windows** from any 1-minute tape reproduce the rule mechanically, back to the tape's start. They
  reproduce the **outcome** only to the extent the tape tracks Pyth.
- **Basis:** CFDs and perps are not Pyth, and Pyth's commodity feeds are not CME's front month.
  - Measure the basis on the overlap: the share of Kalshi-era windows whose synthetic outcome equals Kalshi's
    `result`, per series.
  - **Gate: ≥ 97% agreement**, or that tape is not used for that series. Ties (open = close) count as YES, as in the
    contract.

## 2. Features
Every feature uses only data at or before the entry minute.

| Feature | Note |
|---|---|
| **Current engine's `prob_up`** | always included, so v2 can only add to it |
| move so far / (σ·√elapsed), minutes left | the engine's own inputs |
| σ regime | `sigma_1m` against the series' trailing 10-day median (as in #513) |
| trend | the previous 1–3 windows' moves, and whether the current move agrees with them |
| ET hour, session (Asia, London, NY, post-settle), day of week | |
| scheduled events | the Step A calendar module (EIA, API, storage, CPI, jobs, FOMC) |
| cross-asset | moves from the same feed only (the other 5 series), plus a DXY proxy if the chosen source has one |

## 3. Models, simplest first
| | Model | What it adds over the one before |
|---|---|---|
| a | **Isotonic recalibration of the engine's `prob_up`, per series × entry minute** (Platt scaling if a cell has under 2k rows) | Fixes the engine's known shape errors (tails, σ floor) with no new inputs. It is cheapest and hardest to overfit, so **start here; if (a) can't beat the market after the fee, (b) and (c) need a strong reason to go ahead.** |
| b | Logistic regression on §2, with the engine's logit as an offset | Lets context (trend, events, hour) shift the probability, and stays readable through its coefficients |
| c | LightGBM (`lightgbm` is already in `pyproject.toml`, so no new dependency) | Interactions such as minute × regime × event. Only worth it if it beats (b) on held-out years |

`scikit-learn` is already a dependency and covers (a) and (b).

## 4. Evaluation, in two parts that answer different questions
**Part 1: long history, model accuracy only.** It cannot promote anything.
- Walk-forward by calendar year: train on all years before Y, test on Y, never shuffle across time.
- Report Brier and log-loss against the current engine on each held-out year, and calibration by entry minute.
- Regime stability: 2013–2019, 2020–2023 and 2024–2026 reported separately. A model that wins in only one regime is
  rejected.

**Part 2: edge era (Jul 31 onward). This is the only part that decides whether a model goes live.**
- Train only on data before each series' Kalshi start, then freeze.
- Score against **Kalshi's price after the fee** in two sources, side by side and never pooled:
  - the forward record (`fifteen_window_offsets`);
  - the A0 replay with the haircut (`REPLAY_HAIRCUT`, ask + 1¢).
- Report ¢ per trade, n, and the day-clustered low95 (`fifteen_volregime.clustered_low95`), each paired against the
  current engine on the same windows.
- The valid-candidate rule from Step A applies: replay and forward must agree in direction, and forward sets the size.
- Better accuracy is necessary but not sufficient. **The bar is edge against Kalshi's price.**

## 5. Path to live
1. A new forecaster version, `fifteen_min_v2`. It freezes alongside v1 (as `*-15m-v2` does) with its own
   `model_version`. **v1 is never changed in place.**
2. A preregistered shadow gate in `docs/superpowers/specs/` that fixes the artifact hash, series, entry minute and
   bar.
3. The same promotion bar as the v4 shadows: ≥ 100 fresh trades, low95 > 0, and a paired-delta low95 > 0. Kevin
   approves any switch.

## 6. Compute and storage
- **Size:** about 23 hours a day × 4 windows × 252 days ≈ 23k windows per series-year.
  - About 13 years × 6 series ≈ 1.8M windows, or about 25M (window, minute) rows over 14 entry minutes.
  - The four HistData series alone come to about 1.2M windows.
- **Where it runs:** locally. Isotonic and logistic fits take minutes; LightGBM takes under an hour on a laptop
  CPU. The VPS only loads the frozen artifact.
- **Artifacts:** `/cache/research/models/fifteen_min_v2/<version>/` holds the model, the feature list, the training
  date range and a sha256. The prereg cites the hash. **There is no retraining inside a version:** a refit is a new
  version with a new prereg, so nothing drifts silently.
- **Bars:** `/cache/research/<source>/<symbol>/<YYYY-MM-DD>.json`, one file per day, the same shape as the #517
  archive.

## 7. Risks and kill criteria
| Risk | Mitigation |
|---|---|
| Overfitting to old regimes | walk-forward by year, a three-regime check, and Part 2 alone decides |
| CFD or perp basis against Pyth | the ≥ 97% outcome-agreement gate per series |
| Survivorship and rolls | CFDs and perps don't roll, but their basis shifts at CME rolls; flag roll weeks as a feature and report them separately |
| Fee changes | the fee is a parameter in `oil_fifteen_rule.fee`; rerun Part 2 if Kalshi changes it |
| Data licence | no fetch until Kevin picks a source whose terms fit |

**Kill this line of work if any of these happen:**
- (a) recalibration shows no Part 2 paired low95 > 0 against v1 on the forward record, using the Kalshi-era data to
  date, and (b) does no better;
- Part 1 shows no Brier gain over the engine in at least 2 of 3 regimes;
- no source passes the basis gate for at least 3 series.
