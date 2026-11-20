"""Nightly screener warm-up (Kevin, 2026-11-03; widened Nov 2026).

Two passes over the full listed common-equity universe (~6-7k names — the
refreshed nasdaq_all list, which carries both Nasdaq Trader files, cut to
common shares):

1. The EDGAR bulk pass (edgar_bulk.load_bulk): one download of the SEC's
   companyfacts.zip writes every registry concept's rows into the cache
   for the whole universe. Cheap and complete — this is what lets EDGAR
   fields evaluate at universe scale instead of one API call per name.
2. The yfinance rotation: info / statements / earnings dates for one
   stale-first slice of the universe (TRADEHUB_SCREENING_WARM_SLICE names,
   default 1200). yfinance is unofficial and throttles unpredictably — it
   is the binding constraint, so the deep fields rotate: never-fetched
   names first, then the stalest, and the cache itself is the resumable
   state (a night that dies mid-slice has still warmed a prefix of the
   stalest names, and tomorrow's ordering starts from what is stale then).

The run prints the universe's coverage (fresh info / statements / EDGAR
shares) so a night's progress — and any stall — is visible in the cron log.
Runs after the daily universe refresh. Options chains stay excluded: their
cache TTL is 6h, so a nightly warm would expire before the evening, and
runs prefetch them concurrently on demand.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tradehub.screening import edgar_bulk
from tradehub.screening.sources import TTL, DataStore
from tradehub.screening.universes import resolve_universe

_KINDS = {"info", "statements", "earnings"}
_SLICE = int(os.environ.get("TRADEHUB_SCREENING_WARM_SLICE", "1200"))
_UNIVERSE = {"type": "common_equity",
             "base": {"type": "index", "index": "nasdaq_all"}}
# The companyfacts zip is ~1.4 GB: refuse the bulk pass rather than
# fill the disk (Claude's cleanup, 2026-11-17).
_MIN_FREE_BYTES = 2 * 1024**3


def fetch_bulk_zip(store: DataStore) -> Path | None:
    """Download the companyfacts zip for the bulk pass, hardened
    (Claude's cleanup, 2026-11-17): stale .part files left by a killed
    run are swept first, the download lands on a .part path and is
    renamed into place only when complete (a partial never sits at the
    real path), and the disk must hold the zip with headroom before a
    byte is fetched. None (with the reason printed) when the pass
    cannot run -- the caller still rotates."""
    root = Path(store.cache.root)
    for stale in root.glob("*.part"):
        stale.unlink(missing_ok=True)
    free = shutil.disk_usage(root).free
    if free < _MIN_FREE_BYTES:
        print(f"screening_warm: edgar bulk skipped: {free} bytes free "
              f"on {root}, need {_MIN_FREE_BYTES}")
        return None
    zip_path = root / "companyfacts.zip"
    part_path = root / "companyfacts.zip.part"
    edgar_bulk.download(edgar_bulk.ZIP_URL, part_path)
    part_path.replace(zip_path)
    return zip_path


def rotation_order(store: DataStore, tickers: list[str]) -> list[str]:
    """Stale-first by info-cache age: never-fetched names first, then
    expired entries stalest-first, then fresh entries oldest-first (the
    slice reaches them only once everything stale is warm)."""
    def priority(t: str):
        age = store.cache.age_hours(f"info|{t}")
        if age is None:
            return (0, 0.0, t)
        if age > TTL["info"]:
            return (1, -age, t)
        return (2, -age, t)

    return sorted(tickers, key=priority)


def coverage(store: DataStore, tickers: list[str]) -> dict:
    """The share of the universe with a fresh entry per data kind — the
    number the nightly log reports. EDGAR counts a name covered when any
    registry concept's rows entry is fresh."""
    n = len(tickers)
    if not n:
        return {"names": 0, "info": 0.0, "statements": 0.0, "edgar": 0.0}
    info = stmt = edgar = 0
    for t in tickers:
        if store.cache.get(f"info|{t}", TTL["info"]) is not None:
            info += 1
        if store.cache.get(f"stmt|{t}", TTL["statements"]) is not None:
            stmt += 1
        if any(store.cache.get(f"edgarrows|{t}|{c}", TTL["edgar"]) is not None
               for c in edgar_bulk.CONCEPTS):
            edgar += 1
    return {"names": n, "info": info / n, "statements": stmt / n,
            "edgar": edgar / n}


def main() -> None:
    store = DataStore()
    try:
        universe = resolve_universe(store, _UNIVERSE)
    except Exception as e:  # a missing refresh must not read as zero names
        print(f"screening_warm: universe unavailable: {e}")
        return
    print(f"screening_warm: universe {len(universe)} names")

    zip_path = None
    try:
        zip_path = fetch_bulk_zip(store)
        if zip_path is not None:
            counts = edgar_bulk.load_bulk(store, universe, zip_path=zip_path)
            print(f"screening_warm: edgar bulk {counts}")
    except Exception as e:  # fail-soft: the rotation still runs
        print(f"screening_warm: edgar bulk pass failed: {e}")
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)
        (Path(store.cache.root) / "companyfacts.zip.part").unlink(missing_ok=True)

    ordered = rotation_order(store, universe)
    slice_ = ordered[:_SLICE]
    store.warm(slice_, _KINDS)
    cov = coverage(store, universe)
    print(f"screening_warm: warmed slice {len(slice_)} of {len(universe)} "
          f"for {sorted(_KINDS)}; missing notes: {len(store.missing)}; "
          f"coverage info {cov['info']:.1%} statements "
          f"{cov['statements']:.1%} edgar {cov['edgar']:.1%}")


if __name__ == "__main__":
    main()
