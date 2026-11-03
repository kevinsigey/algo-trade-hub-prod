"""Storage for the in-site agent's specs (phases 1-2, Kevin, 2026-11-03).

A spec row is the interpreter's StrategySpec as Kevin confirmed it, its
lifecycle state (draft -> shadow -> paper-eligible, or blocked), and the
accuracy gate's last outcome. The state machine lives in the API layer;
this module only reads and writes rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

TABLE = "agent_specs"
STATES = ("draft", "shadow", "paper-eligible", "blocked")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_spec(supa, title: str, spec: dict, questions: list) -> dict:
    row = {"title": title, "spec": spec, "questions": questions or [],
           "state": "draft", "gate": None}
    data = supa.table(TABLE).insert(row).execute().data
    return data[0] if data else row


def list_specs(supa) -> list[dict]:
    rows = supa.table(TABLE).select("*").order("id", desc=True).execute().data or []
    return rows


def get_spec(supa, spec_id: int) -> dict | None:
    rows = supa.table(TABLE).select("*").eq("id", spec_id).execute().data or []
    return rows[0] if rows else None


def update_spec(supa, spec_id: int, *, title: str | None = None, spec: dict | None = None,
                questions: list | None = None) -> dict | None:
    """Edit a spec. An edit invalidates the gate (the run described the old
    words), so the row returns to draft with the gate cleared -- the caller
    tells Kevin that is what happened."""
    patch: dict = {"updated_at": _now()}
    if title is not None:
        patch["title"] = title
    if spec is not None:
        patch["spec"] = spec
        patch["state"] = "draft"
        patch["gate"] = None
    if questions is not None:
        patch["questions"] = questions
    supa.table(TABLE).update(patch).eq("id", spec_id).execute()
    return get_spec(supa, spec_id)


def set_state(supa, spec_id: int, state: str, gate: dict | None = ...) -> dict | None:
    patch: dict = {"state": state, "updated_at": _now()}
    if gate is not ...:
        patch["gate"] = gate
    supa.table(TABLE).update(patch).eq("id", spec_id).execute()
    return get_spec(supa, spec_id)
