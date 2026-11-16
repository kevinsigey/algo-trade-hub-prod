"""The v6 sizing fork (spec Section 4), read at preflight time.

Schedule v2 units — premium base $5,000, top-tier $10,000; the same
figures read as risk-to-stop for share plays — apply ONLY while the
tracker's automatic grading is live: the grader's last successful run
fresh (< 26h). Stale, failed, or never-run grading drops the unit to
the $1,500 fallback automatically. No vote, no grace period: ungraded
size is the failure this rule exists to prevent.

The numbers live in tracker_config (one row, id 1, seeded by the
tracker migration); the freshness lives in tracker_health (stamped by
every grader run, success or failure). A missing row reads as the
migration's defaults with grading NOT fresh — the fallback is the
safe state.
"""
from __future__ import annotations

from datetime import datetime, timezone

CONFIG = "tracker_config"
HEALTH = "tracker_health"
FRESH_WITHIN_HOURS = 26.0

DEFAULTS = {"unit_v2_premium": 5000.0, "unit_v2_top": 10000.0,
            "unit_fallback": 1500.0, "play_kind_c_live": False,
            "cash_floor_pct": 10.0}


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(
            tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row(client, table: str) -> dict | None:
    try:
        rows = (client.table(table).select("*").eq("id", 1)
                .execute().data) or []
    except Exception:  # noqa: BLE001 -- an unreadable row reads as absent
        return None
    return rows[0] if rows else None


def load_config(client) -> dict:
    """tracker_config with the migration defaults filling any gap."""
    row = _row(client, CONFIG) or {}
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if row.get(key) is not None:
            out[key] = row[key]
    return out


def grader_fresh(client, *, now: datetime | None = None) -> bool:
    """True when the grader's last SUCCESSFUL run landed within the
    freshness window. A run that failed, a stamp that never landed, or
    an unparseable stamp all read as not fresh."""
    now = now or datetime.now(timezone.utc)
    health = _row(client, HEALTH)
    if not health or not health.get("last_grader_ok"):
        return False
    last = _parse(health.get("last_grader_run_at"))
    if last is None:
        return False
    age_hours = (now - last).total_seconds() / 3600
    return 0 <= age_hours < FRESH_WITHIN_HOURS


def governing_unit(client, *, top_tier: bool = False,
                   now: datetime | None = None) -> dict:
    """{unit, source, fresh} — the one number an event-lab order is
    sized against. `source` names which side of the fork set it, for
    the preflight check line and the audit trail."""
    config = load_config(client)
    fresh = grader_fresh(client, now=now)
    if fresh:
        unit = (config["unit_v2_top"] if top_tier
                else config["unit_v2_premium"])
        return {"unit": float(unit), "source": "schedule_v2",
                "fresh": True}
    return {"unit": float(config["unit_fallback"]), "source": "fallback",
            "fresh": False}
