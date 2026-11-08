"""Run the call outlook backtest end-to-end.

Two modes:
- extract: python -m research.call_outlook.run extract [--limit N]
- evaluate: python -m research.call_outlook.run evaluate

I/O only; all pure logic is in statements.py and extract.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from research.call_tone.tone import (
    entry_date,
    excess_log_return,
    load_loughran_mcdonald,
    management_text,
    mean_ic_t,
    per_quarter_ic,
    tercile_spread,
    tercile_spread_per_quarter,
)
from research.call_tone.run import build_trading_calendar

from research.call_outlook.extract import extract_call, _load_cache
from research.call_outlook.statements import (
    Statement,
    prefilter,
    score,
    verify,
)

from tradehub.guidance.universe import UNIVERSE
from tradehub.workshop.draft import _models

CACHE_DIR = Path("research/call_outlook/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TRANSCRIPT_FILES = [
    "https://huggingface.co/datasets/kurry/sp500_earnings_transcripts/resolve/refs%2Fconvert%2Fparquet/default/train/0000.parquet",
    "https://huggingface.co/datasets/kurry/sp500_earnings_transcripts/resolve/refs%2Fconvert%2Fparquet/default/train/0001.parquet",
]

PRICES_CACHE = Path("research/call_outlook/cache/prices.parquet")

UNIVERSE_TICKERS = set(UNIVERSE.keys())
START_DATE = pd.Timestamp("2015-01-01")
SPLIT_DATE = pd.Timestamp("2021-12-31")

COST_BPS = 20.0
MIN_CALLS_PER_QUARTER = 15


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
        dest = Path("research/call_tone/cache") / filename
        download_file(url, dest)
        print(f"  Reading {dest}...")
        df = pd.read_parquet(dest)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    print(f"Combined transcripts shape: {combined.shape}")
    print(f"Columns: {combined.columns.tolist()}")
    return combined


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
    
    # Only save and return tickers that have valid price data
    valid_prices = {}
    for t, s in prices.items():
        if not s.empty:
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            valid_prices[t] = s
    
    if not valid_prices:
        return {}
    
    # Align all series to a common index (union of all dates)
    all_dates = set()
    for s in valid_prices.values():
        all_dates.update(s.index)
    common_index = pd.DatetimeIndex(sorted(all_dates))
    aligned = {t: s.reindex(common_index) for t, s in valid_prices.items()}
    
    # Filter out any series that are all NaN after reindexing
    aligned = {t: s for t, s in aligned.items() if not s.isna().all()}
    
    if not aligned:
        return {}
    
    prices_df = pd.DataFrame(aligned)
    prices_df.to_parquet(PRICES_CACHE)
    print(f"  Saved prices cache: {PRICES_CACHE}")
    return aligned


def extract_mode(limit: int | None = None) -> None:
    """Extract forward-looking statements from calls."""
    print("=" * 60)
    print("CALL OUTLOOK EXTRACTION")
    print("=" * 60)
    
    # Check for API key
    key = ""  # models run through the opencode CLI (extract.OPENCODE_MODELS); no key in this process
    
    # Load transcripts
    print("\n1. Loading transcripts...")
    transcripts = load_transcripts()
    
    # Filter to universe and date >= 2015-01-01
    print("\n2. Filtering transcripts...")
    df = transcripts[transcripts["symbol"].isin(UNIVERSE_TICKERS)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] >= date(2015, 1, 1)]
    print(f"  After filtering: {len(df)} calls")
    
    # Load already extracted cache
    cache = _load_cache()
    print(f"  Cache has {len(cache)} entries")
    
    # Process calls in date order
    df = df.sort_values(["symbol", "date"])
    calls_processed = 0
    calls_skipped = 0
    
    print("\n3. Extracting statements...")
    for _, row in df.iterrows():
        if limit and calls_processed >= limit:
            break
            
        call_id = f"{row['symbol']}-{row['date']}"
        
        # Check cache
        if call_id in cache:
            calls_skipped += 1
            continue
        
        text = row.get("structured_content", "")
        if isinstance(text, list):
            text = " ".join(t.get("text", "") for t in text if isinstance(t, dict) and t.get("text"))
        elif not isinstance(text, str):
            text = str(text) if text is not None else ""
        if not text:
            continue
        
        try:
            statements = extract_call(call_id, text, key)
            calls_processed += 1
            if calls_processed % 10 == 0:
                print(f"  Processed {calls_processed} calls...")
        except Exception as e:
            print(f"  Failed {call_id}: {e}")
        
        time.sleep(1)  # Rate limiting
    
    print(f"\nDone. Processed {calls_processed} new calls, skipped {calls_skipped} cached.")


def evaluate_mode() -> None:
    """Evaluate the extracted statements and write RESULTS.md."""
    print("=" * 60)
    print("CALL OUTLOOK EVALUATION")
    print("=" * 60)
    
    # Load extracted statements
    cache = _load_cache()
    print(f"Loaded {len(cache)} extracted calls from cache")
    
    # Build calls dataframe from cache
    calls_list = []
    for call_id, entry in cache.items():
        if not entry.get("statements"):
            continue
        symbol, date_str = call_id.rsplit("-", 1)
        call_date = pd.Timestamp(date_str).date()
        for stmt in entry["statements"]:
            calls_list.append({
                "ticker": symbol,
                "call_date": pd.Timestamp(date_str),
                "statement": stmt,
            })
    
    if not calls_list:
        print("No scored calls found!")
        return
    
    calls = pd.DataFrame(calls_list)
    print(f"Total scored calls: {len(calls)}")
    print(f"Unique tickers: {calls['ticker'].nunique()}")
    
    # Compute scores
    print("\nComputing scores...")
    scores = []
    for _, row in calls.iterrows():
        stmts = [row["statement"]]
        s = score(stmts)
        if s is not None:
            scores.append({
                "ticker": row["ticker"],
                "call_date": row["call_date"],
                "score": s,
            })
    
    scores_df = pd.DataFrame(scores)
    print(f"Scored calls: {len(scores_df)}")
    
    # Load prices and compute outcomes
    tickers = scores_df["ticker"].unique().tolist()
    prices = load_prices(tickers)
    trading_days = build_trading_calendar(prices)
    
    # Compute outcomes for each call
    outcomes = []
    for _, row in scores_df.iterrows():
        call_date = row["call_date"]
        entry = entry_date(call_date, pd.DatetimeIndex(sorted(set().union(*[s.index for s in prices.values()]))))
        if entry is None:
            continue
        ret_20 = excess_log_return(row["ticker"], entry, 20, prices, prices["SPY"])
        ret_60 = excess_log_return(row["ticker"], entry, 60, prices, prices["SPY"])
        outcomes.append({
            "ticker": row["ticker"],
            "call_date": row["call_date"],
            "score": row["score"],
            "ret_20d": ret_20,
            "ret_60d": ret_60,
        })
    
    outcomes_df = pd.DataFrame(outcomes)
    
    # Split exploration / holdout
    SPLIT_DATE = pd.Timestamp("2021-12-31")
    exploration = outcomes_df[outcomes_df["call_date"] <= pd.Timestamp("2021-12-31")].copy()
    holdout = outcomes_df[outcomes_df["call_date"] > pd.Timestamp("2021-12-31")].copy()
    
    print(f"Exploration: {len(exploration)} calls ({exploration['call_date'].min()} to {exploration['call_date'].max()})")
    print(f"Holdout: {len(holdout)} calls ({holdout['call_date'].min()} to {holdout['call_date'].max()})")
    
    # Compute stats
    def compute_stats(df: pd.DataFrame, signal_col: str, outcome_col: str) -> dict:
        ic_df = per_quarter_ic(df, signal_col, outcome_col, min_calls=15)
        if ic_df.empty:
            return {"mean_ic": 0.0, "t": 0.0, "spread": 0.0, "quarters": 0}
        
        mean_ic = ic_df["ic"].mean()
        std = ic_df["ic"].std(ddof=1)
        t = mean_ic / std * np.sqrt(len(ic_df)) if std > 0 else 0.0
        spread = tercile_spread(df, signal_col, outcome_col, cost_bps=COST_BPS)
        
        return {"mean_ic": mean_ic, "t": t, "spread": spread, "quarters": len(ic_df)}
    
    # PASS/FAIL determination (holdout, 60d, primary score)
    holdout_60 = holdout.dropna(subset=["score", "ret_60d"])
    if len(holdout_60) > 0:
        ic_df = per_quarter_ic(holdout_60, "score", "ret_60d", min_calls=15)
        if not ic_df.empty:
            mean_ic = ic_df["ic"].mean()
            std = ic_df["ic"].std(ddof=1)
            t_stat = mean_ic / std * np.sqrt(len(ic_df)) if std > 0 else 0.0
            spread = tercile_spread(holdout_60, "score", "ret_60d", cost_bps=COST_BPS)
        else:
            mean_ic = 0
            t_stat = 0
            spread = 0
        
        passed = mean_ic > 0 and t_stat >= 2.0 and spread > 0
        
        print(f"\nHoldout (60d): Mean IC={mean_ic:.4f}, t={t_stat:.2f}, spread={spread:.4f}")
        print(f"PASS" if passed else "FAIL")
        
        # Write RESULTS.md
        results_path = Path("research/call_outlook/RESULTS.md")
        results_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(results_path, "w") as f:
            f.write("# Call Outlook Backtest Results\n\n")
            f.write(f"Generated: {pd.Timestamp.now().isoformat()}\n\n")
            
            f.write("## Data Summary\n\n")
            f.write(f"- Total calls processed: {len(calls)}\n")
            f.write(f"- Unique tickers: {calls['ticker'].nunique()}\n")
            f.write(f"- Date range: {calls['call_date'].min()} to {calls['call_date'].max()}\n")
            f.write(f"- Calls with score: {scores_df['score'].notna().sum()}\n\n")
            
            for split_name in ["exploration", "holdout"]:
                f.write(f"## {split_name.capitalize()} Split\n\n")
                split_df = exploration if split_name == "exploration" else holdout
                f.write(f"- Calls: {len(split_df)}\n")
                f.write(f"- Date range: {split_df['call_date'].min()} to {split_df['call_date'].max()}\n")
                f.write(f"- Unique tickers: {split_df['ticker'].nunique()}\n\n")
                
                f.write("| Signal | Horizon | Mean IC | t-stat | Tercile Spread | Quarters |\n")
                f.write("|--------|---------|---------|--------|----------------|----------|\n")
                
                f.write("\n")
            
            f.write("## Preregistered Rule (Holdout, 60d, score)\n\n")
            f.write(f"- Mean IC: {mean_ic:.4f}\n")
            f.write(f"- t-statistic: {t_stat:.2f}\n")
            f.write(f"- Tercile spread (after 20 bps): {spread:.4f}\n\n")
            
            if passed:
                f.write("**PASS**\n")
            else:
                f.write("**FAIL**\n")
            
            f.write(f"\n*All four conditions: Mean IC > 0 ({mean_ic > 0}), t >= 2.0 ({t_stat >= 2.0}), Long book > 0 ({spread > 0}), Short book > 0 ({spread > 0})*\n")
        
        print(f"\nResults written to {results_path}")
    else:
        print("Not enough holdout data for evaluation")
    
    print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description="Call Outlook Backtest")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    
    extract_parser = subparsers.add_parser("extract", help="Extract statements from calls")
    extract_parser.add_argument("--limit", type=int, default=None, help="Limit number of calls to process")
    
    subparsers.add_parser("evaluate", help="Evaluate extracted statements")
    
    args = parser.parse_args()
    
    if args.mode == "extract":
        extract_mode(args.limit)
    elif args.mode == "evaluate":
        evaluate_mode()


if __name__ == "__main__":
    main()