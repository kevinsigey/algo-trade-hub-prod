"""File snapshots for slow read-only compositions (step 5, Nov 12).

The Health report took ~16s per request and the Macro/Weather
compositions 8-10s, all rebuilt live on every visit from data that
changes hourly. The hourly journal job now builds them once and writes
them here; the API serves the snapshot while it is fresh and falls back
to the live build when it is missing or stale, so a stopped job degrades
to today's behaviour, never to an error.

Same shape as the degree-days snapshot (tradehub/weather_demand.py): a
JSON envelope {built_at, payload} under /cache, overridable by env for
tests. Writes are atomic (tmp file + os.replace) so a reader never sees
a half-written snapshot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIR_ENV = "TRADEHUB_SNAPSHOT_DIR"
DEFAULT_DIR = "/cache"


def snapshot_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or DEFAULT_DIR)


def snapshot_path(name: str, dir: Path | None = None) -> Path:
    return (dir or snapshot_dir()) / f"{name}.json"


def write_snapshot(name: str, payload: Any, *, now: datetime | None = None,
                   dir: Path | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    path = snapshot_path(name, dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"built_at": now.isoformat(), "payload": payload}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(envelope, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_snapshot(name: str, *, max_age_seconds: float,
                  now: datetime | None = None,
                  dir: Path | None = None) -> dict | None:
    """The envelope {built_at, payload} when present and fresh, else None.

    Missing, corrupt, or stale all read as None -- the caller falls back
    to building live, exactly as before snapshots existed.
    """
    now = now or datetime.now(timezone.utc)
    try:
        envelope = json.loads(snapshot_path(name, dir).read_text(encoding="utf-8"))
        built_at = datetime.fromisoformat(str(envelope["built_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if built_at.tzinfo is None:
        built_at = built_at.replace(tzinfo=timezone.utc)
    if (now - built_at).total_seconds() > max_age_seconds:
        return None
    return envelope
