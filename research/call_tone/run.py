"""Run the call tone backtest end-to-end.

I/O only; all pure logic is in tone.py.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from research.call_tone.tone import (
    compute_tone_uncertainty,
    delta_tone,
    entry_date,
    excess_log_return,
    load_loughran_mcdonald,
    management_text,
    mean_ic_t,
    per_quarter_ic,
    tercile_spread,
    tercile_spread_per_quarter,
)

from tradehub.guidance.universe import UNIVERSE

CACHE_DIR = Path("research/call_tone/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TRANSCRIPT_FILES = [
    "https://huggingface.co/datasets/kurry/sp500_earnings_transcripts/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet",
    "https://huggingface.co/datasets/kurry/sp500_earnings_transcripts/resolve/refs%2Fconvert%2Fparquet/default/train/0001.parquet",
]

LM_DICT_URL = "https://sraf.nd.edu/assets/files/lm_master_dictionary_2023.csv"
# Alternative if above fails
LM_DICT_URL_ALT = "https://sraf.nd.edu/assets/files/lm_master_dictionary_2022.csv"

PRICES_CACHE = CACHE_DIR / "prices.parquet"
LM_DICT_CACHE = CACHE_DIR / "lm_master_dictionary.csv"

UNIVERSE_TICKERS = set(UNIVERSE.keys())
START_DATE = pd.Timestamp("2015-01-01")
SPLIT_DATE = pd.Timestamp("2021-12-31")

COST_BPS = 20.0
MIN_CALLS_PER_QUARTER = 15
MIN_PRIOR_CALLS = 4


def download_file(url: str, dest: Path, force: bool = False) -> None:
    """Download file with progress."""
    if dest.exists() and not force:
        print(f"  Using cached: {dest}")
        return
    print(f"  Downloading {url} -> {dest}")
    import requests
    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded / total * 100
                sys.stderr.write(f"\r  {pct:.1f}%")
                sys.stderr.flush()
    print(f"\n  Done: {dest}")


def load_transcripts() -> pd.DataFrame:
    """Load and combine transcript parquet files."""
    frames = []
    for i, url in enumerate(TRANSCRIPT_FILES):
        filename = f"{i:04d}.parquet"
        dest = CACHE_DIR / filename
        download_file(url, dest)
        print(f"  Reading {dest}...")
        df = pd.read_parquet(dest)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    print(f"Combined transcripts shape: {combined.shape}")
    print(f"Columns: {combined.columns.tolist()}")
    print(f"Sample row:")
    for col in combined.columns:
        val = combined.iloc[0][col]
        if isinstance(val, str):
            print(f"  {col}: {val[:100]}...")
        elif isinstance(val, list):
            print(f"  {col}: list of {len(val)} items")
        else:
            print(f"  {col}: {val}")
    return combined


def load_lm_dictionary() -> tuple[set[str], set[str], set[str]]:
    """Load Loughran-McDonald dictionary."""
    if not LM_DICT_CACHE.exists():
        for url in [LM_DICT_URL, LM_DICT_URL_ALT]:
            try:
                download_file(url, LM_DICT_CACHE)
                break
            except Exception as e:
                print(f"  Failed: {url} ({e})")
        else:
            raise RuntimeError("Could not download LM dictionary")
    pos, neg, unc = load_loughran_mcdonald(str(LM_DICT_CACHE))
    print(f"LM Dictionary: {len(pos)} positive, {len(neg)} negative, {len(unc)} uncertainty words")
    return pos, neg, unc


def load_prices(tickers: list[str]) -> dict[str, pd.Series]:
    """Load or download adjusted close prices for tickers + SPY."""
    all_tickers = list(set(tickers + ["SPY"]))
    
    if PRICES_CACHE.exists():
        print(f"  Loading prices from cache...")
        prices_df = pd.read_parquet(PRICES_CACHE)
        prices = {col: prices_df[col] for col in prices_df.columns}
        missing = [t for t in all_tickers if t not in prices]
        if not missing:
            return prices
        print(f"  Missing tickers: {missing}, downloading...")
    else:
        missing = all_tickers
        prices = {}
    
    for t in missing:
        try:
            print(f"  Downloading {t}...")
            data = yf.download(t, start="2010-01-01", progress=False, auto_adjust=True)
            if not data.empty and "Close" in data.columns:
                prices[t] = data["Close"].dropna()
        except Exception as e:
            print(f"  Failed {t}: {e}")
    
    if prices:
        prices_df = pd.DataFrame(prices)
        prices_df.to_parquet(PRICES_CACHE)
        print(f"  Saved prices cache: {PRICES_CACHE}")
    
    return prices


def build_trading_calendar(prices: dict[str, pd.Series]) -> pd.DatetimeIndex:
    """Build a unified trading calendar from all price series."""
    all_dates = set()
    for s in prices.values():
        all_dates.update(s.index)
    return pd.DatetimeIndex(sorted(all_dates))


def process_transcripts(
    df: pd.DataFrame,
    pos_set: set[str],
    neg_set: set[str],
    unc_set: set[str],
) -> pd.DataFrame:
    """Compute tone and uncertainty for each transcript."""
    print("  Filtering to universe and date >= 2015-01-01...")
    df = df[df["ticker"].isin(UNIVERSE_TICKERS)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] >= date(2015, 1, 1)]
    print(f"  After filtering: {len(df)} calls")
    
    print("  Computing tone and uncertainty...")
    results = []
    for idx, row in df.iterrows():
        if idx % 1000 == 0:
            print(f"    {idx}/{len(df)}")
        text = management_text(row["transcript"])
        tone, unc_share = compute_tone_uncertainty(text, pos_set, neg_set, unc_set)
        results.append({
            "ticker": row["ticker"],
            "call_date": pd.Timestamp(row["date"]),
            "tone": tone,
            "uncertainty_share": unc_share,
        })
    
    result_df = pd.DataFrame(results)
    return df.merge(result_df, left_index=True, right_index=True)


def compute_delta_tone(df: pd.DataFrame) -> pd.DataFrame:
    """Compute delta_tone = tone - mean of previous 4 calls for same ticker."""
    print("  Computing delta_tone...")
    df = df.sort_values(["ticker", "call_date"]).copy()
    df["tone_prior_4"] = df.groupby("ticker")["tone"].shift(1).rolling(4, min_periods=MIN_PRIOR_CALLS).mean()
    df["delta_tone"] = df["tone"] - df["tone_prior_4"]
    df = df.dropna(subset=["delta_tone"])
    print(f"  After delta_tone: {len(df)} calls (dropped {len(df[df['tone_prior_4'].isna()])} with <4 priors)")
    return df


def compute_outcomes(df: pd.DataFrame, prices: dict[str, pd.Series], trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Compute entry date and excess returns for 20d and 60d."""
    print("  Computing entry dates and excess returns...")
    results = []
    for _, row in df.iterrows():
        call_date = row["call_date"]
        entry = entry_date(call_date, trading_days)
        if entry is None:
            results.append({"entry_date": pd.NaT, "ret_20d": np.nan, "ret_60d": np.nan})
            continue
        
        ret_20 = excess_log_return(row["ticker"], entry, 20, prices, prices["SPY"])
        ret_60 = excess_log_return(row["ticker"], entry, 60, prices, prices["SPY"])
        results.append({"entry_date": entry, "ret_20d": ret_20, "ret_60d": ret_60})
    
    out = pd.DataFrame(results, index=df.index)
    return df.join(out)


def compute_stats(df: pd.DataFrame, signal_col: str, outcome_col: str, name: str) -> dict:
    """Compute per-quarter IC stats for a signal/outcome pair."""
    ic_df = per_quarter_ic(df, signal_col, outcome_col, MIN_CALLS_PER_QUARTER)
    if ic_df.empty:
        return {"name": name, "quarters": 0, "mean_ic": 0.0, "t": 0.0, "spread": 0.0}
    
    mean_ic, t_stat = mean_ic_t(ic_df["ic"])
    spread = tercile_spread(df, signal_col, outcome_col, COST_BPS)
    
    return {
        "name": name,
        "quarters": len(ic_df),
        "mean_ic": mean_ic,
        "t": t_stat,
        "spread": spread,
    }


def run():
    """Main entry point."""
    print("=" * 60)
    print("CALL TONE BACKTEST (preregistered)")
    print("=" * 60)
    
    # 1. Load transcripts
    print("\n1. Loading transcripts...")
    transcripts = load_transcripts()
    
    # 2. Load LM dictionary
    print("\n2. Loading Loughran-McDonald dictionary...")
    pos_set, neg_set, unc_set = load_lm_dictionary()
    
    # 3. Process transcripts
    print("\n3. Processing transcripts...")
    calls = process_transcripts(transcripts, pos_set, neg_set, unc_set)
    
    # 4. Compute delta_tone
    print("\n4. Computing delta_tone...")
    calls = compute_delta_tone(calls)
    
    # 5. Load prices
    print("\n5. Loading prices...")
    tickers = calls["ticker"].unique().tolist()
    prices = load_prices(tickers)
    trading_days = build_trading_calendar(prices)
    
    # 6. Compute outcomes
    print("\n6. Computing outcomes...")
    calls = compute_outcomes(calls, prices, trading_days)
    
    # 7. Split exploration / holdout
    print("\n7. Splitting exploration / holdout...")
    exploration = calls[calls["call_date"] <= SPLIT_DATE].copy()
    holdout = calls[calls["call_date"] > SPLIT_DATE].copy()
    print(f"  Exploration: {len(exploration)} calls ({exploration['call_date'].min()} to {exploration['call_date'].max()})")
    print(f"  Holdout: {len(holdout)} calls ({holdout['call_date'].min()} to {holdout['call_date'].max()})")
    
    # 8. Compute stats for each split, horizon, and signal
    print("\n8. Computing statistics...")
    
    signals = {
        "delta_tone": "delta_tone",
        "tone_level": "tone",
        "delta_uncertainty": "uncertainty_share",  # sign flipped later
    }
    
    outcomes = {
        "ret_60d": "ret_60d",
        "ret_20d": "ret_20d",
    }
    
    splits = {
        "exploration": exploration,
        "holdout": holdout,
    }
    
    all_results = {}
    
    for split_name, split_df in splits.items():
        print(f"\n  Split: {split_name} ({len(split_df)} calls)")
        split_results = {}
        
        for signal_name, signal_col in signals.items():
            for outcome_name, outcome_col in outcomes.items():
                key = f"{signal_name}_{outcome_name}"
                df = split_df.dropna(subset=[signal_col, outcome_col]).copy()
                
                # For delta_uncertainty, flip sign (more uncertainty -> lower return)
                if signal_name == "delta_uncertainty":
                    # We need prior uncertainty to compute delta
                    prior_unc = df.groupby("ticker")[signal_col].shift(1).rolling(4, min_periods=4).mean()
                    df["delta_unc"] = df[signal_col] - prior_unc
                    df = df.dropna(subset=["delta_unc"])
                    signal_col = "delta_unc"
                    if signal_col not in df.columns or df[signal_col].isna().all():
                        continue
                
                stats = compute_stats(df, signal_col, outcome_col, key)
                split_results[key] = stats
                print(f"    {key}: IC={stats['mean_ic']:.4f}, t={stats['t']:.2f}, spread={stats['spread']:.4f}, Q={stats['quarters']}")
        
        all_results[split_name] = split_results
    
    # 9. Write RESULTS.md
    print("\n9. Writing RESULTS.md...")
    results_path = Path("research/call_tone/RESULTS.md")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(results_path, "w") as f:
        f.write("# Call Tone Backtest Results\n\n")
        f.write(f"Generated: {pd.Timestamp.now().isoformat()}\n\n")
        
        f.write("## Data Summary\n\n")
        f.write(f"- Total calls processed: {len(calls)}\n")
        f.write(f"- Unique tickers: {calls['ticker'].nunique()}\n")
        f.write(f"- Date range: {calls['call_date'].min()} to {calls['call_date'].max()}\n")
        f.write(f"- Calls with delta_tone (>=4 priors): {calls['delta_tone'].notna().sum()}\n")
        f.write(f"- Speaker turns usable: {'Yes' if 'transcript' in transcripts.columns and isinstance(transcripts['transcript'].iloc[0], list) else 'No (whole transcript used)'}\n\n")
        
        for split_name in ["exploration", "holdout"]:
            f.write(f"## {split_name.capitalize()} Split\n\n")
            split_df = splits[split_name]
            f.write(f"- Calls: {len(split_df)}\n")
            f.write(f"- Date range: {split_df['call_date'].min()} to {split_df['call_date'].max()}\n")
            f.write(f"- Unique tickers: {split_df['ticker'].nunique()}\n\n")
            
            f.write("| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |\n")
            f.write("|--------|---------|---------|--------|----------------|----------|\n")
            
            for key, stats in all_results.get(split_name, {}).items():
                f.write(f"| {stats['name']} | {stats.get('horizon', '')} | {stats['mean_ic']:.4f} | {stats['t']:.2f} | {stats['spread']:.4f} | {stats['quarters']} |\n")
            
            f.write("\n")
        
        # PASS/FAIL determination
        holdout_60_delta = all_results.get("holdout", {}).get("delta_tone_ret_60d", {})
        mean_ic = holdout_60_delta.get("mean_ic", 0)
        t_stat = holdout_60_delta.get("t", 0)
        spread = holdout_60_delta.get("spread", 0)
        
        passed = mean_ic > 0 and t_stat >= 2.0 and spread > 0
        
        f.write("## Preregistered Rule (Holdout, 60d, delta_tone)\n\n")
        f.write(f"- Mean IC: {mean_ic:.4f}\n")
        f.write(f"- t-statistic: {t_stat:.2f}\n")
        f.write(f"- Tercile spread (after 20 bps): {spread:.4f}\n\n")
        
        if passed:
            f.write("**PASS**\n")
        else:
            f.write("**FAIL**\n")
        
        f.write(f"\n*All three conditions: Mean IC > 0 ({mean_ic > 0}), t >= 2.0 ({t_stat >= 2.0}), Spread > 0 ({spread > 0})*\n")
    
    print(f"\nResults written to {results_path}")
    print("\nDone!")


if __name__ == "__main__":
    run()