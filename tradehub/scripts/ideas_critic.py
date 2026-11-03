"""Cron entrypoint: the weekly critic (self-improving loop piece 1).

For every live or tracking idea on both books, recompute the claim's own
statistic on the live shadow record, compare it with the latest saved run's
backtest verdict, and write one critique (PAUSE / HOLD / WATCH + reasons) onto
the idea's record. The critic only recommends -- it never pauses, kills or
resizes anything. Runs Sunday 23:00 UTC (early Sunday evening in Chicago).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.workshop import critic, data, store

CHECKS = "paper_order_checks"


def _units(supa) -> list[dict]:
    """The critique units: main-book live and tracking ideas (their lifecycle
    rows) plus every live big-book activation. Shadow days are the idea's one
    forward record; a book unit filters them to its own activation date."""
    units = []
    for idea in store.live_ideas(supa):
        units.append({"idea": idea, "book": "main", "run_id": idea["live_run_id"],
                      "since": idea["live_at"], "live": True})
    for idea in store.tracked_ideas(supa):
        units.append({"idea": idea, "book": "main", "run_id": idea["tracked_run_id"],
                      "since": idea["tracked_at"], "live": False})
    for act in store.activations(supa, "big"):
        if act.get("live_at") and not act.get("killed_at"):
            units.append({"idea": store.get_idea(supa, act["idea_id"]), "book": "big",
                          "run_id": act["live_run_id"], "since": act["live_at"], "live": True})
    return units


def _paper_block(supa, idea_id: int, book: str, since: str) -> dict:
    """The execution record since activation: what the runner sent and what the
    broker filled (paper_order_checks), kept apart from the strategy record."""
    orders = [o for o in supa.table(store.ORDERS).select("*").eq("idea_id", idea_id)
              .eq("book", book).execute().data if str(o.get("at") or "") >= since]
    sent = [o for o in orders if o.get("status") == "sent"]
    by_client = {o["client_order_id"]: o for o in sent}
    checks = [c for c in supa.table(CHECKS).select("*").eq("book", book).execute().data
              if c["client_order_id"] in by_client] if by_client else []
    filled = [c for c in checks if float(c.get("filled_qty") or 0) > 0]
    net = sum(float(c["filled_qty"]) * float(c["filled_avg_price"] or 0)
              * (1 if by_client[c["client_order_id"]]["side"] == "buy" else -1) for c in filled)
    return {"orders": len(orders), "sent": len(sent), "filled": len(filled),
            "fill_rate": round(len(filled) / len(sent), 2) if sent else None,
            "net_filled_usd": round(net, 2)}


def run(now: datetime, supa, *, closes=data.closes) -> tuple[dict, dict]:
    """(aggregate summary, {unit: error}). One unit failing never stops the
    others. The summary leads with counts and the worst degraders -- the
    per-idea detail lives on the ideas' own records, not in this report."""
    units = _units(supa)
    priors = store.latest_critiques(supa)
    all_rows = {u["idea"]["id"]: store.shadow_days(supa, u["idea"]["id"]) for u in units}
    regimes: dict = {}
    days = [r["day"] for rows in all_rows.values() for r in rows]
    if days:
        start = date.fromisoformat(min(days)) - timedelta(days=150)
        frame = closes(["SPY"], start)
        regimes = critic.regime_tags(frame["SPY"])

    written, failed = [], {}
    for unit in units:
        idea = unit["idea"]
        key = f"{idea['id']}:{unit['book']}"
        try:
            run_row = store.get_run(supa, unit["run_id"])
            result, spec = run_row["result"], run_row["spec"]
            unseen = (result.get("claim") or {}).get("unseen") or {}
            backtest = {"value": unseen.get("value"), "label": unseen.get("label"),
                        "holds": unseen.get("holds"), "verdict": result.get("verdict"),
                        "p": (result.get("shuffle") or {}).get("p"),
                        "walk_forward": result.get("walk_forward")}
            # Main-book units own the whole shadow record (it starts at their
            # anchor by construction); a big-book activation can postdate it.
            since_day = str(unit["since"])[:10]
            rows = [r for r in all_rows[idea["id"]]
                    if unit["book"] == "main" or r["day"] >= since_day]
            prior = (priors.get((idea["id"], unit["book"])) or {}).get("payload") or {}
            payload = critic.critique_payload(
                idea_id=idea["id"], book=unit["book"], at=now.isoformat(),
                kind=spec.get("claim"), backtest=backtest, rows=rows, regimes=regimes,
                paper=_paper_block(supa, idea["id"], unit["book"], str(unit["since"]))
                if unit["live"] else None,
                prior_dominant=(prior.get("conditions") or {}).get("dominant"))
            store.add_critique(supa, idea["id"], unit["book"], payload)
            written.append({"idea_id": idea["id"], "title": idea.get("title"),
                            "book": unit["book"], "recommendation": payload["recommendation"],
                            "degradation": payload["degradation"]})
        except Exception as exc:  # noqa: BLE001 -- reported, retried next week
            failed[key] = f"{type(exc).__name__}: {exc}"

    counts = {rec: sum(1 for w in written if w["recommendation"] == rec)
              for rec in ("PAUSE", "WATCH", "HOLD")}
    worst = sorted((w for w in written if w["degradation"] is not None),
                   key=lambda w: w["degradation"])[:5]
    return {"at": now.isoformat(), "units": len(written), "counts": counts, "worst": worst}, failed


def main() -> int:
    load_local_env()
    summary, failed = run(datetime.now(UTC), get_client())
    print(json.dumps({"critic": summary, "failed": failed}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
