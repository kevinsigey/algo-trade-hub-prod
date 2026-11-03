"""The ledger pre-flight: what the record already says about a new idea, before it's drafted.

It informs and never blocks. The one exception sits in the route: an exact duplicate of a
killed idea gets no draft, with the reason it died. An idea's identity is what it holds and
its rule; size, title and dates are staging.
"""
from __future__ import annotations

import json

from tradehub.agent.gate import to_idea_spec
from tradehub.workshop import registry, store


def title_of(draft: dict) -> str:
    thesis = str(draft.get("thesis") or "").strip()
    return (thesis[:77] + "...") if len(thesis) > 80 else (thesis or "Untitled idea")


def _names(spec: dict) -> frozenset:
    return frozenset(spec.get("hold") or []) | frozenset(spec.get("short") or [])


def _canon(spec: dict) -> tuple:
    return (frozenset(spec.get("hold") or []), frozenset(spec.get("short") or []), spec.get("claim"),
            json.dumps(spec.get("when"), sort_keys=True), json.dumps(spec.get("exits") or None, sort_keys=True))


def _kill_reason(idea: dict, now: dict | None, stored: str | None, switches: list[dict]) -> str:
    if now and now["verdict_now"] != stored:
        why = [w for w, failed in (("the hub-wide FDR bar", now.get("fdr_pass") is False),
                                   ("walk-forward", now.get("wf_ok") is False)) if failed]
        return f"fails the current standard: {' and '.join(why) or 'the hub-wide bar'}"
    mine = [s for s in switches if s.get("idea_id") == idea["id"] and s.get("by")]
    if mine:
        return str(mine[-1]["by"])
    return f"killed on {str(idea.get('killed_at'))[:10]}"


def preflight(supa, draft: dict, latest: dict[int, dict]) -> dict:
    """`latest`: idea id -> its latest saved run. Reads ideas and switches; writes nothing."""
    idea_spec, note = to_idea_spec(draft, title_of(draft))
    universe = set(draft.get("universe") or [])
    holdings = {iid: set(_names(r.get("spec") or {})) for iid, r in latest.items()}
    family = registry.families({**holdings, -1: universe})[-1]
    members = [m for m in family["members"] if m != -1]
    adjusted = registry.adjusted(latest)
    ideas = {i["id"]: i for i in store._all_ideas(supa)} if latest else {}
    switches = supa.table(store.SWITCHES).select("*").order("id").execute().data if latest else []

    same_names = [m for m in members if holdings[m] == universe]
    exact = {m for m in same_names if idea_spec and _canon(latest[m].get("spec") or {}) == _canon(idea_spec)}
    values = [((((latest[m].get("result") or {}).get("claim") or {}).get("unseen") or {}).get("value"), m) for m in same_names]
    values = [(v, m) for v, m in values if v is not None]
    best = None
    if values:
        value, m = max(values)
        best = {"idea_id": m, "title": ideas.get(m, {}).get("title"), "value": value,
                "verdict": latest[m].get("verdict"), "verdict_now": adjusted[m]["verdict_now"]}
    killed = [{"idea_id": m, "title": ideas[m].get("title"), "exact": m in exact,
               "reason": _kill_reason(ideas[m], adjusted.get(m), latest[m].get("verdict"), switches)}
              for m in same_names if ideas.get(m, {}).get("killed_at")]
    return {"expressible": idea_spec is not None, "note": note,
            "family": {"size": len(members), "tickers": family["tickers"]},
            "prior_attempts": sum(int(latest[m].get("variation") or 1) for m in members),
            "best_prior": best, "killed": killed,
            "duplicate_of_killed": next((k["idea_id"] for k in killed if k["exact"]), None),
            "bar": {"ideas_tested": len(latest),
                    "standard": "the claim holds on unseen years, clears the hub-wide FDR bar (q=0.05), "
                                "and holds in at least half the walk-forward folds"}}
