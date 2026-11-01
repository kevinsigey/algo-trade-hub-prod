"""Energy news tone as a Workshop condition source (phase-2 §5.1, Oct 12 plan module A).

One basket in v1: ENERGY, the Oct 12 plan's GDELT query set. The series is the daily
mean article tone from the GDELT DOC 2.1 API's timelinetone mode -- one request per
build, GDELT's own per-article tone averaged per day (the plan keeps VADER scoring of
headlines as a later cross-check; the tone GDELT publishes needs no model on the box).

Three facts about this source, all load-bearing:

* **The DOC API only covers a rolling ~3-month window.** A backtest reaching further
  back gets the months that exist and the engine's honest NOT ENOUGH DATA beyond
  them; history via the BigQuery GKG dataset is a later adapter behind this same
  function.
* **GDELT throttles hard** (one request per 5 seconds, shared-IP sensitive, plain
  text refusal instead of an HTTP error). So the series is CACHED on disk
  (TRADEHUB_GDELT_CACHE, default /cache/gdelt -- the shared volume): a day's build
  fetches at most once, and a refused refresh falls back to the cache rather than
  failing a run. With no cache and a refusal, the fetch raises with GDELT's own
  words -- a news rule that cannot read its series fails loudly, never silently
  trades on an empty one.
* **Publication lag**: the engine reads news series in its t-2 branch, like FRED --
  a day's tone is only complete after the day ends, so the conservative lag is the
  correct one.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

# The Oct 12 plan's energy query set (A1). OR'd terms must be parenthesised or the
# API rejects the query; sourcelang/sourcecountry per the plan.
BASKETS: dict[str, str] = {
    "ENERGY": '("natural gas" OR "Henry Hub" OR LNG OR OPEC OR "crude oil" OR EIA OR gasoline OR refinery)'
              " sourcelang:English sourcecountry:US",
}

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WINDOW_DAYS = 92  # the DOC rolling window, ~3 months; older asks return nothing
CACHE_ENV = "TRADEHUB_GDELT_CACHE"
DEFAULT_CACHE = "/cache/gdelt"


def _default_get_text(url: str) -> str:
    import requests
    resp = requests.get(url, timeout=60, headers={"User-Agent": "tradehub/1.0 (workshop news source)"})
    return resp.text


def fetch_timeline(query: str, start: date, end: date, *, get_text: Callable[[str], str] = _default_get_text) -> dict:
    """One timelinetone request. GDELT answers throttling in plain text with an HTTP
    200, so the text itself is checked before it is parsed."""
    url = (f"{DOC_URL}?query={requests_quote(query)}&mode=timelinetone&format=json"
           f"&startdatetime={start:%Y%m%d}000000&enddatetime={end:%Y%m%d}235959")
    text = get_text(url)
    if text.lstrip().startswith("Please limit requests"):
        raise RuntimeError(f"GDELT refused the request (throttled): {text.strip()[:120]}")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"GDELT answered something unparseable: {text.strip()[:120]!r}") from exc
    if not isinstance(payload, dict) or "timeline" not in payload:
        raise RuntimeError(f"GDELT answered without a timeline: {text.strip()[:120]!r}")
    return payload


def requests_quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


def parse_timeline(payload: dict) -> pd.Series:
    """The timeline's points as a daily mean tone series (buckets resampled to days,
    so the parser is right whatever granularity GDELT chose for the span)."""
    points = payload["timeline"][0]["data"] if payload.get("timeline") else []
    if not points:
        return pd.Series(dtype=float, name="tone")
    stamps = pd.to_datetime([p["date"] for p in points], utc=True).tz_convert(None).normalize()
    values = pd.Series([float(p["value"]) for p in points], index=stamps, name="tone")
    return values.groupby(level=0).mean().sort_index()


def _cache_path(cache_dir: Path, basket: str) -> Path:
    return cache_dir / f"{basket}.json"


def _read_cache(cache_dir: Path, basket: str) -> tuple[date | None, dict[str, float]]:
    try:
        raw = json.loads(_cache_path(cache_dir, basket).read_text(encoding="utf-8"))
        return date.fromisoformat(raw["fetched_on"]), {str(k): float(v) for k, v in raw["points"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return None, {}


def _write_cache(cache_dir: Path, basket: str, fetched_on: date, points: dict[str, float]) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_dir, basket).write_text(
            json.dumps({"fetched_on": fetched_on.isoformat(), "points": points}), encoding="utf-8")
    except OSError:
        pass  # the cache is an optimisation; a read-only box still gets its series


def news_tone_series(basket: str, start: date, *, get_text: Callable[[str], str] | None = None,
                     cache_dir: Path | None = None, today: date | None = None) -> pd.Series:
    """Daily mean GDELT tone for `basket` from `start`. Raises ValueError for an
    unknown basket and RuntimeError when GDELT refuses and no cache exists."""
    if basket not in BASKETS:
        raise ValueError(f"unknown news basket {basket!r}: known baskets are {', '.join(sorted(BASKETS))}")
    today = today or date.today()
    root = cache_dir if cache_dir is not None else Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE)
    fetched_on, points = _read_cache(root, basket)
    if fetched_on != today:
        fetch_from = max(start, today - timedelta(days=WINDOW_DAYS))
        try:
            fresh = parse_timeline(fetch_timeline(BASKETS[basket], fetch_from, today,
                                                  **({"get_text": get_text} if get_text else {})))
            for stamp, value in fresh.items():
                points[stamp.date().isoformat()] = float(value)
            _write_cache(root, basket, today, points)
        except Exception:
            if not points:
                raise
            # A refused refresh with a cache on disk: serve the cache. Its end date
            # is in the series itself, so a run can see how fresh what it read was.
    series = pd.Series({pd.Timestamp(day): tone for day, tone in points.items()}, name="tone", dtype=float)
    return series[series.index >= pd.Timestamp(start)].sort_index()
