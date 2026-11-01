"""Ask the host to re-run a batch job (phase-2 §4.3).

The API process cannot start host jobs: scan and settle run on the VPS under systemd
timers (`tradehub-scan` / `tradehub-settle`, via `bin/tradehub-job`). So a re-run is a
FILE, not a call: the API drops `<job>.json` into a watched directory on the shared
/cache volume, and a host watcher (predictor-hub vps-stack: `bin/tradehub-rerun`, one
systemd tick a minute) claims the file and starts the job. The file IS the audit
record -- it carries who asked and when, the watcher archives it under `done/` when it
claims it, and the run itself then lands in `scanner_runs` like every scheduled pass.

One pending request per job: a second ask while one is waiting returns the existing
request rather than stacking runs. A failed write is an error the caller sees, never
a request that silently never happened.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# The jobs with a host timer AND a run record -- the two the Health page tracks by name.
RERUNNABLE: tuple[str, ...] = ("scan", "settle")

RERUN_DIR_ENV = "TRADEHUB_RERUN_DIR"
DEFAULT_RERUN_DIR = "/cache/rerun"


class RerunUnavailable(RuntimeError):
    """The trigger could not be written (volume missing, permissions, disk)."""


def rerun_dir() -> Path:
    return Path(os.environ.get(RERUN_DIR_ENV) or DEFAULT_RERUN_DIR)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def pending(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """The outstanding requests, by job. A corrupt file reads as absent here; the
    watcher logs and archives it rather than the API guessing at its contents."""
    root = directory if directory is not None else rerun_dir()
    out: dict[str, dict[str, Any]] = {}
    for job in RERUNNABLE:
        data = _read(root / f"{job}.json")
        if data is not None:
            out[job] = data
    return out


def request_rerun(job: str, *, requested_by: str, now: datetime,
                  directory: Path | None = None) -> dict[str, Any]:
    """Drop the trigger file for `job`, or return the one already waiting.

    Returns {"status": "pending" | "already_pending", "job", "requested_by",
    "requested_at"}. Raises ValueError for a job that cannot be re-run and
    RerunUnavailable when the file cannot be written.
    """
    if job not in RERUNNABLE:
        raise ValueError(f"cannot re-run {job!r}: only {', '.join(RERUNNABLE)} have host timers")
    root = directory if directory is not None else rerun_dir()
    target = root / f"{job}.json"
    existing = _read(target)
    if existing is not None:
        return {"status": "already_pending", "job": job,
                "requested_by": existing.get("requested_by"),
                "requested_at": existing.get("requested_at")}
    record = {"job": job, "requested_by": requested_by, "requested_at": now.isoformat()}
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / f".{job}.json.tmp"
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(target)  # atomic: the watcher never reads a half-written trigger
    except OSError as exc:
        raise RerunUnavailable(f"could not write the re-run trigger in {root}: {exc}") from exc
    return {"status": "pending", **record}
