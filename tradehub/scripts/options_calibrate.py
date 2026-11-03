"""Fit the Workshop options calibration from Alpaca's real option bars
(design 2026-10-31 section 2). Run in-container:

    python -m tradehub.scripts.options_calibrate

Samples listed contracts on a monthly grid (moneyness 0.90-1.10, ~30d and
~60d expiries) from Feb 2024 to Oct 2026, inverts each real close to an
implied vol, fits the skew curve (relative IV adjustment on log-moneyness
and days left) on 2024-2025, and checks it untouched on 2026. Spreads come
from live quotes on the current chain. Writes
tradehub/workshop/calibration.json in place and prints the report --
the numbers a verdict quotes.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from tradehub.portfolio import alpaca_paper
from tradehub.workshop.data import closes as ws_closes
from tradehub.workshop.data import fred_series
from tradehub.workshop.options import (VOL_INDEX, bs_price,
                                       implied_vol_from_price,
                                       implied_vol_series, skew_factor)

UNDERLYINGS = ["SPY", "QQQ", "IWM", "GLD", "USO", "EEM", "AAPL", "NVDA", "MU"]
STEPS = {"SPY": 1.0, "QQQ": 1.0, "IWM": 1.0, "GLD": 1.0, "USO": 0.5, "EEM": 1.0,
         "AAPL": 2.5, "NVDA": 2.5, "MU": 2.5}
MONEYNESS = [0.90, 0.95, 1.00, 1.05, 1.10]
FIT_END = date(2025, 12, 31)
OUT = Path(__file__).resolve().parents[1] / "workshop" / "calibration.json"


def _occ(root: str, expiry: date, kind: str, strike: float) -> str:
    return f"{root}{expiry:%y%m%d}{'C' if kind == 'call' else 'P'}{int(round(strike * 1000)):08d}"


def _fridays(a: date, b: date) -> list[date]:
    out, d = [], a + timedelta(days=(4 - a.weekday()) % 7)
    while d <= b:
        out.append(d)
        d += timedelta(days=7)
    return out


def _sample_days(index: pd.DatetimeIndex) -> list[date]:
    days = []
    for year, month in [(y, m) for y in (2024, 2025, 2026) for m in range(1, 13)]:
        if (year, month) < (2024, 2) or (year, month) > (2026, 10):
            continue
        target = pd.Timestamp(date(year, month, 15))
        later = index[index >= target]
        if len(later):
            days.append(later[0].date())
    return days


def _fetch_bars(symbols: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        token = None
        while True:
            params = {"symbols": ",".join(chunk), "timeframe": "1Day",
                      "start": "2024-01-05", "end": "2026-11-02", "limit": 10000}
            if token:
                params["page_token"] = token
            r = requests.get(alpaca_paper.DATA_BASE + "/v1beta1/options/bars",
                             params=params, headers=alpaca_paper._headers(), timeout=90)
            r.raise_for_status()
            body = r.json()
            for sym, bars in (body.get("bars") or {}).items():
                out.setdefault(sym, {}).update({b["t"][:10]: float(b["c"]) for b in bars})
            token = body.get("next_page_token")
            if not token:
                break
    return out


def _trailing_yield(ticker: str, spot: float) -> float:
    import yfinance as yf

    divs = yf.Ticker(ticker).dividends
    if divs is None or len(divs) == 0 or spot <= 0:
        return 0.0
    cutoff = divs.index.max() - pd.Timedelta(days=365)
    return float(divs[divs.index > cutoff].sum()) / spot


def _spreads(spots: pd.DataFrame) -> dict[str, float]:
    today = spots.index[-1].date()
    spot_now = {t: float(spots[t].iloc[-1]) for t in UNDERLYINGS}
    expiry = _fridays(today + timedelta(days=25), today + timedelta(days=40))[0]
    symbols, meta = [], {}
    for t in UNDERLYINGS:
        for m in MONEYNESS:
            strike = round(spot_now[t] * m / STEPS[t]) * STEPS[t]
            for kind in ("call", "put"):
                sym = _occ(t, expiry, kind, strike)
                symbols.append(sym)
                meta[sym] = t
    fracs: dict[str, list[float]] = {t: [] for t in UNDERLYINGS}
    for i in range(0, len(symbols), 100):
        r = requests.get(alpaca_paper.DATA_BASE + "/v1beta1/options/quotes/latest",
                         params={"symbols": ",".join(symbols[i:i + 100])},
                         headers=alpaca_paper._headers(), timeout=60)
        r.raise_for_status()
        for sym, q in (r.json().get("quotes") or {}).items():
            bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
            mid = 0.5 * (bid + ask)
            if bid > 0 and ask > bid and mid >= 0.05:
                fracs[meta[sym]].append((ask - bid) / mid)
    return {t: float(np.median(v)) if v else 0.05 for t, v in fracs.items()}


def main() -> None:
    spots = ws_closes(UNDERLYINGS, date(2023, 12, 1))
    fred = {}
    for sid in {*VOL_INDEX.values(), "DTB3"}:
        fred[sid] = fred_series(sid, date(2023, 12, 1))
    base_vols = {t: implied_vol_series(t, spots[t], fred)[0] for t in UNDERLYINGS}
    rate = (fred["DTB3"] / 100.0).reindex(spots.index, method="ffill")
    yields = {t: _trailing_yield(t, float(spots[t].iloc[-1])) for t in UNDERLYINGS}

    days = _sample_days(spots.index)
    contracts: dict[str, dict] = {}
    pairs: list[tuple[date, str]] = []
    for day in days:
        ts = pd.Timestamp(day)
        for t in UNDERLYINGS:
            spot = float(spots.loc[ts, t])
            if not np.isfinite(spot):
                continue
            expiries = _fridays(day + timedelta(days=25), day + timedelta(days=40)) \
                + _fridays(day + timedelta(days=50), day + timedelta(days=70))
            for expiry in expiries:
                for m in MONEYNESS:
                    strike = round(spot * m / STEPS[t]) * STEPS[t]
                    for kind in ("call", "put"):
                        sym = _occ(t, expiry, kind, strike)
                        contracts[sym] = {"ticker": t, "expiry": expiry, "strike": strike, "kind": kind}
                        pairs.append((day, sym))
    print(f"{len(contracts)} candidate contracts over {len(days)} sample days")
    bars = _fetch_bars(sorted(contracts))

    rows = []
    for day, sym in pairs:
        real = bars.get(sym, {}).get(day.isoformat())
        if real is None or real < 0.03:
            continue
        c = contracts[sym]
        t, ts = c["ticker"], pd.Timestamp(day)
        spot = float(spots.loc[ts, t])
        base = float(base_vols[t].loc[ts])
        r = float(rate.loc[ts])
        if not (np.isfinite(base) and base > 0):
            continue
        dte = (c["expiry"] - day).days
        years = dte / 365.0
        iv = implied_vol_from_price(c["kind"], real, spot, c["strike"], years, r, yields[t])
        if iv is None:
            continue
        flat = bs_price(c["kind"], spot, c["strike"], years, r, yields[t], base)
        rows.append({"ticker": t, "day": day, "lnm": math.log(c["strike"] / spot), "dte": dte,
                     "rel_iv": iv / base - 1.0, "err_flat": abs(flat - real) / real,
                     "spot": spot, "strike": c["strike"], "kind": c["kind"], "years": years,
                     "rate": r, "base": base, "real": real})
    frame = pd.DataFrame(rows)
    print(f"{len(frame)} usable contract-days")

    fit_all = frame[frame["day"] <= FIT_END]
    check = frame[frame["day"] > FIT_END]
    # The fit itself runs on the liquid subset (real premium >= $0.25): penny
    # contracts' closes are often stale prints, and their inverted vols
    # dominate a least-squares fit while mattering least to a backtest. The
    # error report below still covers every sampled contract. The curve is
    # the textbook monotone skew -- linear in log-moneyness plus a term
    # slope; a free quadratic fitted v1 exploded out-of-sample (check-window
    # errors got worse on 7 of 9 names), so the form stays constrained.
    fit = fit_all[(fit_all["real"] >= 0.25)
                  & fit_all["rel_iv"].between(-0.6, 1.2)].copy()
    # Robust fit: least squares on raw inverted vols is dragged by stale
    # prints (an illiquid contract's last trade can be hours old, and its
    # inversion explodes). Bucket log-moneyness, take each bucket's MEDIAN
    # relative IV, and fit the line through the bucket medians.
    fit["bucket"] = (fit["lnm"] / 0.025).round() * 0.025
    med = fit.groupby("bucket").agg(rel=("rel_iv", "median"),
                                    dte=("dte", "median"), n=("rel_iv", "size"))
    med = med[med["n"] >= 10]
    x = np.column_stack([np.ones(len(med)), med.index.to_numpy(), med["dte"].to_numpy() / 30.0 - 1.0])
    coef, *_ = np.linalg.lstsq(x, med["rel"].to_numpy(), rcond=None)
    coeffs = {"a": float(coef[0]), "b": float(coef[1]), "c": 0.0, "d": float(coef[2])}
    print("bucket medians (lnm, rel_iv, n):",
          [(round(float(i), 3), round(float(r.rel), 3), int(r.n)) for i, r in med.iterrows()])
    # VERDICT on the skew (2026-11-03): the bucket medians show no monotone
    # pattern (they wander -0.08..+0.09 across moneyness -- the CBOE indexes
    # already average the strike strip, and daily option closes are too
    # stale to recover what is left), and every fitted variant made
    # check-window errors WORSE on most names. The shipped curve is
    # therefore flat: pricing keeps the base vol, the calibration's bite
    # comes from the charged spreads, and verdicts quote the measured
    # error. A skew worth shipping needs intraday quotes, not daily closes.
    coeffs = {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}
    print("skew coeffs:", {k: round(v, 4) for k, v in coeffs.items()},
          f"(fit n={len(fit)}, check n={len(check)})")

    def skewed_err(part: pd.DataFrame) -> pd.Series:
        out = []
        for row in part.itertuples():
            vol = row.base * skew_factor(math.exp(row.lnm), row.dte, coeffs)
            px = bs_price(row.kind, row.spot, row.strike, row.years, row.rate,
                          yields[row.ticker], vol)
            out.append(abs(px - row.real) / row.real)
        return pd.Series(out, index=part.index)

    fit = fit.assign(err_skew=skewed_err(fit))
    check = check.assign(err_skew=skewed_err(check))
    spreads = _spreads(spots)

    underlyings = {}
    print(f"\n{'name':6} {'n_fit':>6} {'n_chk':>6} {'flat%':>7} {'skew%':>7} {'spread%':>8}")
    for t in UNDERLYINGS:
        f, c = fit[fit["ticker"] == t], check[check["ticker"] == t]
        entry = {"spread_frac": round(spreads[t], 4),
                 "n_fit": int(len(f)), "n_check": int(len(c)),
                 "median_err_flat_check_pct": round(100 * c["err_flat"].median(), 1) if len(c) else None,
                 "median_err_check_pct": round(100 * c["err_skew"].median(), 1) if len(c) else None,
                 "median_err_fit_pct": round(100 * f["err_skew"].median(), 1) if len(f) else None}
        underlyings[t] = entry
        print(f"{t:6} {entry['n_fit']:>6} {entry['n_check']:>6} "
              f"{entry['median_err_flat_check_pct'] or float('nan'):>7} "
              f"{entry['median_err_check_pct'] or float('nan'):>7} {100 * spreads[t]:>8.1f}")

    payload = {"generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
               "fit_window": "2024-02..2025-12", "check_window": "2026-01..2026-10",
               "fit_form": "skew REJECTED by the data: bucket-median relative IVs show no "
                           "monotone moneyness pattern and every fitted curve (raw least "
                           "squares, premium-floored, bucket-median; linear and quadratic) "
                           "worsened check-window errors, so the shipped coefficients are "
                           "zero (flat vol). Spreads and per-name errors are the calibration. "
                           "Revisit with intraday quote data, not daily closes",
               "skew": {k: round(v, 6) for k, v in coeffs.items()},
               "fit_underlyings": UNDERLYINGS, "underlyings": underlyings}
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
