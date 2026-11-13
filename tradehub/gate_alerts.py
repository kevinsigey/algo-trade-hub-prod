"""Gate-switch notifications on the existing watcher outbox.

Kevin (2026-11-12): when a model becomes promotion-eligible, is killed
by its stopping rule, or a live gate actually switches, he wants a pop
up naming which model and why -- the system should be leavable running.
The transport already exists: watcher_alerts rows with status 'pending'
are delivered by the level-watcher poller to the Trading Thesis
Testing chat. This writer is the only producer for kind 'gate_switch';
watch_id stays NULL (these are model events, not price watches).

Delivery is a notification, never an action: eligibility announced
here still waits for Kevin's word before any gate switches (see the
family preregistration).
"""

from __future__ import annotations

from typing import Any

ALERTS_TABLE = "watcher_alerts"
KIND = "gate_switch"


def _already_written(client, version: str, event: str) -> bool:
    rows = (client.table(ALERTS_TABLE).select("id,evidence")
            .eq("kind", KIND).execute().data) or []
    return any((r.get("evidence") or {}).get("version") == version
               and (r.get("evidence") or {}).get("event") == event
               for r in rows)


def write_gate_alert(client, *, family: str, version: str, event: str,
                     title: str, body: str,
                     evidence: dict[str, Any] | None = None) -> bool:
    """Insert one pending gate_switch alert, deduplicated on
    (version, event) across all rows ever written -- a transition is
    announced once, however often the scorer runs. Fail-soft: returns
    False instead of raising; a missed alert must never break scoring.
    """
    try:
        if _already_written(client, version, event):
            return False
        ev = dict(evidence or {})
        ev.update({"version": version, "event": event, "family": family})
        client.table(ALERTS_TABLE).insert({
            "kind": KIND, "watch_id": None, "family": family,
            "title": title, "body": body, "evidence": ev,
            "status": "pending",
        }).execute()
        return True
    except Exception:
        return False
