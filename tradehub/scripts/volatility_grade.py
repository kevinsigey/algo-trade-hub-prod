"""Grade the dark volatility layer (phase-2 §6.2) on the options-adjacent
underlyings the book actually trades.

Walk-forward coverage of GARCH / GJR / HAR-RV against the static incumbent on
~5 years of daily returns per symbol. Writes the grade JSON to the cache volume
(TRADEHUB_VOLATILITY_FILE, default /cache/volatility.json) and prints the table.
NOTHING consumes the result -- the layer stays dark until a candidate beats the
incumbent on coverage here and Kevin promotes it. Usage:
    python -m tradehub.scripts.volatility_grade [--symbols SPY XLE QQQ]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

from tradehub.data.yahoo_chart import fetch_chart
from tradehub.volatility import log_returns, walk_forward_grade

DEFAULT_SYMBOLS = ["SPY", "XLE", "QQQ"]
HISTORY_YEARS = 6


def grade_symbol(symbol: str, *, years: int = HISTORY_YEARS, today: date | None = None) -> dict:
    today = today or date.today()
    closes_by_date, _tz = fetch_chart(symbol, today - timedelta(days=365 * years + 30))
    closes = [closes_by_date[d] for d in sorted(closes_by_date) if d <= today]
    returns = log_returns(closes)
    grade = walk_forward_grade(returns, train=500, step=21)
    return {"symbol": symbol, "closes": len(closes), "grade": grade}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Walk-forward coverage grade for the dark volatility layer.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    args = parser.parse_args(argv)
    report = {"as_of": date.today().isoformat(), "symbols": {}}
    for symbol in args.symbols:
        result = grade_symbol(symbol)
        report["symbols"][symbol] = result
        grade = result["grade"]
        print(f"\n{symbol} ({result['closes']} closes, grade: {grade.get('status')})")
        if grade.get("status") != "ok":
            continue
        for name, row in grade["forecasters"].items():
            print(f"  {name:7s} cov80 {row['coverage_80']:.3f}  cov95 {row['coverage_95']:.3f}  "
                  f"err {row['coverage_error']:.3f}  width x{row['width_vs_static']}")
        print(f"  best on coverage: {grade['best_on_coverage']} (incumbent: static)")
    path = Path(os.environ.get("TRADEHUB_VOLATILITY_FILE") or "/cache/volatility.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
        print(f"\ngrade written to {path}")
    except OSError as exc:
        print(f"\ncould not write {path}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
