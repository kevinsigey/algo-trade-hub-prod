"""Pure functions for call tone analysis.

These functions contain no I/O and can be unit tested independently.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


# Tone formula constants
TONE_EPS = 1.0  # Added to denominator to avoid division by zero


def compute_tone(positive: int, negative: int) -> float:
    """Tone = (positive - negative) / (positive + negative + 1)."""
    return (positive - negative) / (positive + negative + TONE_EPS)


def compute_uncertainty_share(uncertainty: int, total_words: int) -> float:
    """Uncertainty share = uncertainty words / all words."""
    if total_words == 0:
        return 0.0
    return uncertainty / total_words


def count_words(text: str, word_set: set[str]) -> int:
    """Count occurrences of words from word_set in text (case-insensitive, whole words)."""
    if not text:
        return 0
    words = re.findall(r"\b[a-z']+\b", text.lower())
    return sum(1 for w in words if w in word_set)


def management_text(transcript) -> str:
    """Management's words only. Turns are {"speaker", "text"}; the dataset opens some calls with "Executives" /
    "Analysts" header turns that only list names. Management = the non-operator speakers of the prepared remarks
    (everyone who speaks before the operator opens Q&A); analysts never speak there. All their turns count,
    including Q&A answers. No usable turns -> the whole transcript (stated in the results)."""
    if isinstance(transcript, str):
        return transcript
    turns = [t for t in list(transcript) if isinstance(t, dict) and t.get("text")]
    turns = [t for t in turns if str(t.get("speaker", "")).strip().lower() not in ("executives", "analysts")]
    mgmt: set[str] = set()
    spoke = False
    for t in turns:
        who = str(t.get("speaker", "")).strip()
        if who.lower() == "operator":
            if spoke:
                break  # the operator opening Q&A
            continue
        mgmt.add(who)
        spoke = True
    words = [t["text"] for t in turns if str(t.get("speaker", "")).strip() in mgmt]
    return " ".join(words) if words else " ".join(t["text"] for t in turns)


def compute_tone_uncertainty(text: str, pos_set: set[str], neg_set: set[str], unc_set: set[str]) -> tuple[float, float]:
    """Compute tone and uncertainty share from text."""
    pos = count_words(text, pos_set)
    neg = count_words(text, neg_set)
    unc = count_words(text, unc_set)
    total = pos + neg + unc  # approximate total words from these three sets
    
    tone = compute_tone(pos, neg)
    unc_share = compute_uncertainty_share(unc, total) if total > 0 else 0.0
    return tone, unc_share


def delta_tone(current_tone: float, prior_tones: Sequence[float]) -> float | None:
    """Delta tone = current - mean of previous 4 calls. Returns None if fewer than 4 priors."""
    if len(prior_tones) < 4:
        return None
    return current_tone - np.mean(prior_tones[-4:])


def entry_date(call_date: date, trading_days: pd.DatetimeIndex) -> pd.Timestamp | None:
    """First trading day strictly after call_date."""
    after = trading_days[trading_days > pd.Timestamp(call_date)]
    if len(after) == 0:
        return None
    return after[0]


def excess_log_return(
    ticker: str,
    entry: pd.Timestamp,
    horizon: int,
    prices: dict[str, pd.Series],
    spy: pd.Series
) -> float | None:
    """Log return of ticker minus log return of SPY over horizon trading days from entry."""
    if ticker not in prices or entry not in prices[ticker].index:
        return None
    ticker_prices = prices[ticker]
    spy_prices = spy
    
    # Find entry position
    try:
        entry_pos = ticker_prices.index.get_loc(entry)
    except KeyError:
        return None
    
    if entry_pos + horizon >= len(ticker_prices):
        return None
    
    # Get entry and exit prices
    entry_price = ticker_prices.iloc[entry_pos]
    exit_price = ticker_prices.iloc[entry_pos + horizon]
    
    # SPY prices aligned to ticker dates
    spy_aligned = spy.reindex(ticker_prices.index, method="ffill")
    if entry not in spy_aligned.index or exit_price is None:
        return None
    spy_entry = spy_aligned.loc[entry]
    spy_exit = spy_aligned.iloc[entry_pos + horizon]
    
    if spy_entry is None or spy_exit is None or spy_entry == 0 or spy_exit == 0:
        return None
    
    ticker_ret = np.log(exit_price / entry_price)
    spy_ret = np.log(spy_exit / spy_entry)
    return ticker_ret - spy_ret


def per_quarter_ic(
    df: pd.DataFrame,
    signal_col: str,
    outcome_col: str,
    min_calls: int = 15
) -> pd.DataFrame:
    """Compute per-quarter Spearman IC between signal and outcome."""
    df = df.copy()
    df["quarter"] = df["call_date"].dt.to_period("Q")
    results = []
    for q, group in df.groupby("quarter"):
        if len(group) < min_calls:
            continue
        if group[signal_col].nunique() < 2 or group[outcome_col].nunique() < 2:
            continue
        rho, pval = spearmanr(group[signal_col], group[outcome_col])
        if np.isnan(rho):
            continue
        results.append({
            "quarter": q,
            "ic": rho,
            "pval": pval,
            "n_calls": len(group)
        })
    return pd.DataFrame(results)


def mean_ic_t(ics: pd.Series) -> tuple[float, float]:
    """Mean IC and t-statistic."""
    if len(ics) == 0:
        return 0.0, 0.0
    mean = ics.mean()
    if len(ics) == 1:
        return float(mean), 0.0
    std = ics.std(ddof=1)
    if np.isnan(std) or std < 1e-15:
        return float(mean), 0.0
    t = mean / std * np.sqrt(len(ics))
    return float(mean), float(t)


def tercile_spread(
    df: pd.DataFrame,
    signal_col: str,
    outcome_col: str,
    cost_bps: float = 20.0
) -> float:
    """Mean of (top third outcome - bottom third outcome) per quarter, minus cost."""
    df = df.copy()
    df["quarter"] = df["call_date"].dt.to_period("Q")
    spreads = []
    for _, group in df.groupby("quarter"):
        if len(group) < 3:
            continue
        group = group.sort_values(signal_col)
        n = len(group)
        third = n // 3
        if third == 0:
            continue
        bottom = group.head(third)[outcome_col].mean()
        top = group.tail(third)[outcome_col].mean()
        spreads.append(top - bottom)
    if not spreads:
        return 0.0
    return float(np.mean(spreads) - cost_bps / 10000.0)


def tercile_spread_per_quarter(
    df: pd.DataFrame,
    signal_col: str,
    outcome_col: str
) -> pd.Series:
    """Tercile spread per quarter (no cost subtracted)."""
    df = df.copy()
    df["quarter"] = df["call_date"].dt.to_period("Q")
    spreads = {}
    for q, group in df.groupby("quarter"):
        if len(group) < 3:
            continue
        group = group.sort_values(signal_col)
        n = len(group)
        third = n // 3
        if third == 0:
            continue
        bottom = group.head(third)[outcome_col].mean()
        top = group.tail(third)[outcome_col].mean()
        spreads[q] = top - bottom
    return pd.Series(spreads, name="spread")


def load_loughran_mcdonald(csv_path: str) -> tuple[set[str], set[str], set[str]]:
    """Load LM Master Dictionary and return Positive, Negative, Uncertainty word sets.
    
    Words with a nonzero year in their respective column are included.
    """
    df = pd.read_csv(csv_path)
    # Expected columns: Word, Positive, Negative, Uncertainty, etc.
    # The year columns have headers like "Positive", "Negative", "Uncertainty"
    # with values like "2018" or "" (empty)
    
    pos_col = "Positive" if "Positive" in df.columns else "Positiv"
    neg_col = "Negative" if "Negative" in df.columns else "Negativ"
    unc_col = "Uncertainty" if "Uncertainty" in df.columns else "Uncertain"
    
    pos = set()
    neg = set()
    unc = set()
    
    for _, row in df.iterrows():
        word = str(row.get("Word", "")).lower().strip()
        if not word:
            continue
        # Include if the year column is non-empty and not "0"
        if pos_col in row and pd.notna(row[pos_col]) and str(row[pos_col]).strip() not in ("", "0"):
            pos.add(word)
        if neg_col in row and pd.notna(row[neg_col]) and str(row[neg_col]).strip() not in ("", "0"):
            neg.add(word)
        if unc_col in row and pd.notna(row[unc_col]) and str(row[unc_col]).strip() not in ("", "0"):
            unc.add(word)
    
    return pos, neg, unc