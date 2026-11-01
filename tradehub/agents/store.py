"""Run artifacts on disk: one folder per run (run.json + report.md) plus the grading
record. The only writes this package makes. Location: TRADEHUB_AGENTS_DIR when set
(point it at a persistent volume in production), else the package's data/ dir."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tradehub.agents.schema import GradeEntry, RunRecord

_PACKAGE_DATA = Path(__file__).parent / "data"


def data_dir() -> Path:
    raw = os.getenv("TRADEHUB_AGENTS_DIR", "").strip()
    return Path(raw) if raw else _PACKAGE_DATA


def runs_dir() -> Path:
    return data_dir() / "runs"


def save_run(record: RunRecord, report_md: str | None) -> Path:
    folder = runs_dir() / record.run_id
    folder.mkdir(parents=True, exist_ok=True)
    if report_md is not None:
        (folder / "report.md").write_text(report_md, encoding="utf-8")
        record = record.model_copy(update={"report_path": f"{record.run_id}/report.md"})
    (folder / "run.json").write_text(record.model_dump_json(indent=1), encoding="utf-8")
    return folder


def list_runs() -> list[RunRecord]:
    root = runs_dir()
    if not root.exists():
        return []
    out = []
    for folder in sorted(root.iterdir(), reverse=True):
        raw = folder / "run.json"
        if raw.exists():
            try:
                out.append(RunRecord.model_validate_json(raw.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 -- one corrupt artifact must not sink the feed
                continue
    return out


def read_report(run_id: str) -> str | None:
    if not run_id.replace("-", "").replace("_", "").isalnum():
        return None
    path = runs_dir() / run_id / "report.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _record_path() -> Path:
    return data_dir() / "debate_record.json"


def load_grades() -> list[GradeEntry]:
    path = _record_path()
    if not path.exists():
        return []
    return [GradeEntry.model_validate(g) for g in json.loads(path.read_text(encoding="utf-8"))]


def save_grades(grades: list[GradeEntry]) -> None:
    path = _record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([g.model_dump() for g in grades], indent=1), encoding="utf-8")


def upsert_grade(entry: GradeEntry) -> list[GradeEntry]:
    """Append or replace the (run_id, horizon) grade: re-grading a run corrects, never duplicates."""
    grades = [g for g in load_grades() if not (g.run_id == entry.run_id and g.horizon == entry.horizon)]
    grades.append(entry)
    save_grades(grades)
    return grades
