"""Ideas routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
import threading
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from tradehub.api.dependencies import get_supabase
from tradehub.workshop import store as workshop_store
from tradehub.portfolio.sectors import idea_sector


from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

from tradehub.api.routers.workshop import _latest_saved_map, _play_check, _registry_view, _shadow
router = APIRouter()


@router.get("/api/ideas/{idea_id}/play-check", tags=["Ideas"])
def public_play_check(idea_id: int, size_pct: float = Query(10, gt=0, le=100),
                      book: str = Query("main"), supabase=Depends(get_supabase)):
    """Play check on the published record: the newest SAVED run's spec, and only
    for published ideas (private and missing look the same, as everywhere here)."""
    found = workshop_store.get_idea(supabase, idea_id)
    if found is None or not found["idea"].get("published_at"):
        raise HTTPException(status_code=404, detail="no such idea")
    saved = workshop_store.saved_only(found["runs"])
    if not saved:
        raise HTTPException(status_code=409, detail="no saved run to check")
    return _play_check(supabase, found["idea"], saved[-1]["spec"], size_pct, book)


# ── Trading HQ Ideas record (step 3): public, published ideas only, fails and kills included. ──
def _today() -> date:
    return date.today()


def _idea_kind(spec: dict | None) -> str:
    """The idea's type, for grouping the Ideas tab (Kevin, 2026-11-02): an event study,
    a long/short rule, a wrapped portfolio (core + idea share), or a long-only rule --
    read off the latest run's spec, the same place the claim comes from."""
    if not spec:
        return "long_only"
    if spec.get("kind") == "event":
        return "event"
    if spec.get("short"):
        return "long_short"
    if spec.get("portfolio"):
        return "wrapped"
    return "long_only"


def _public_idea(supabase, idea: dict, runs: list[dict], big_live: set[int] | None = None,
                 view: dict | None = None) -> dict:
    from tradehub.workshop import registry as _registry

    latest = runs[-1] if runs else None
    adj = (view or {}).get("adjusted", {}).get(idea["id"])
    fam = (view or {}).get("families", {}).get(idea["id"])
    origin = _registry.origin_of(idea, (view or {}).get("screen_ids", set())) if view else None
    status = "killed" if idea.get("killed_at") else "live" if idea.get("live_at") else \
        "tracking" if idea.get("tracked_at") else "backtest"
    live = None
    if idea.get("live_at") or idea.get("tracked_at"):
        live = _shadow(supabase, idea)
        if idea.get("killed_at"):
            live["state"] = "killed"  # the record ended on purpose; not stale
    # The card's result line (Kevin, 2026-11-02): the newest saved run's claim
    # outcome in words ("+25.8 pts/yr vs SPY"), so the best plays can be picked
    # from the list without opening each idea. Headline when the run stored no
    # claim object (event studies).
    result_line = None
    result_value = None
    result_p = None
    if latest:
        claim = (latest.get("result") or {}).get("claim") or {}
        # Stored claim shape: {built: {...}, unseen: {...}} for rule runs -- the
        # comparison that counts is the UNSEEN (out-of-sample) split's label.
        # Flat {label} for simpler results; headline only when neither exists.
        result_line = ((claim.get("unseen") or {}).get("label") or claim.get("label")
                       or (latest.get("result") or {}).get("headline"))
        # The numeric companions of the line (Kevin, 2026-11-02: performance is
        # the card's headline and the list must sort by it): the unseen claim
        # metric itself, and the permutation p the verdict was judged on.
        unseen = claim.get("unseen") or {}
        if isinstance(unseen.get("value"), (int, float)):
            result_value = float(unseen["value"])
        shuffle = (latest.get("result") or {}).get("shuffle") or {}
        if isinstance(shuffle.get("p"), (int, float)):
            result_p = float(shuffle["p"])
    return {"id": idea["id"], "title": idea["title"], "published_at": idea["published_at"],
            "claim": latest["spec"].get("claim") if latest else None, "result_line": result_line,
            "result_value": result_value, "result_p": result_p,
            "kind": _idea_kind(latest["spec"] if latest else None),
            "latest_verdict": latest["verdict"] if latest else None, "variations": len(runs), "status": status,
            # Standing under the hub-wide standard (Kevin, 2026-11-03): the
            # as-run verdict above never changes; verdict_now is what counts.
            "verdict_now": adj["verdict_now"] if adj else None,
            "fdr_pass": adj["fdr_pass"] if adj else None,
            "wf_ok": adj["wf_ok"] if adj else None,
            "p_ok": adj.get("p_ok") if adj else None,
            "family": fam, "origin": origin,
            "tags": idea.get("tags") or [],
            "sector": idea_sector(list((latest["spec"].get("hold") or []) + (latest["spec"].get("short") or []))
                                  if latest else (fam or {}).get("tickers") or []),
            "hindsight_selected": _registry.hindsight_selected(origin) if origin else False,
            "gate_overridden": bool((idea.get("gate") or {}).get("status") == "overridden")
            or idea["id"] in (view or {}).get("overridden_big", set()),
            "registry": {"test_number": ((latest.get("result") or {}).get("registry") or {}).get("test_number")
                         if latest else None,
                         "tests_total": (view or {}).get("tests_total")},
            "live_at": idea.get("live_at"), "tracked_at": idea.get("tracked_at"),
            "killed_at": idea.get("killed_at"), "live": live,
            # The weekly critic's latest word per book (loop piece 1): the full
            # payload, so the card chip and the detail view read the same record.
            "critic": {book: payload for book in ("main", "big")
                       if (payload := ((view or {}).get("critics") or {}).get((idea["id"], book)))},
            # Trading now: a paused or killed book doesn't count, so the card can't say Live for it.
            "live_books": (["main"] if idea.get("live_at") and not idea.get("killed_at") and idea.get("auto_orders") else [])
            + (["big"] if (idea["id"] in big_live if big_live is not None
                           else _big_activation_live(supabase, idea["id"])) else [])}


def _big_activation_live(supabase, idea_id: int) -> bool:
    act = workshop_store.activation(supabase, "big", idea_id)
    return bool(act and act.get("live_at") and not act.get("killed_at") and act.get("auto_orders"))


_IDEAS_CACHE: dict = {"at": 0.0, "payload": None, "fp": None}
_IDEAS_CACHE_TTL = 30.0
_IDEAS_REBUILD = threading.Lock()


def _bust_ideas_cache() -> None:
    _IDEAS_CACHE["payload"] = None


def _ideas_fingerprint(supabase) -> tuple:
    """A cheap mutation detector for the ideas cache: lifecycle timestamps,
    the newest run and the save count. Any write that changes what the list
    shows -- endpoint or direct -- changes the fingerprint."""
    ideas = supabase.table("ideas").select("id,published_at,live_at,killed_at,tracked_at,auto_orders").execute().data or []
    runs = supabase.table("idea_runs").select("id").execute().data or []
    saves = supabase.table("idea_run_saves").select("run_id").execute().data or []
    acts = supabase.table("book_activations").select("book,idea_id,live_at,killed_at,auto_orders").execute().data or []
    return (tuple(sorted((i["id"], i.get("published_at"), i.get("live_at"), i.get("killed_at"),
                          i.get("tracked_at"), bool(i.get("auto_orders"))) for i in ideas)),
            max((r["id"] for r in runs), default=0), len(saves),
            tuple(sorted((a["book"], a["idea_id"], a.get("live_at"), a.get("killed_at"), bool(a.get("auto_orders")))
                         for a in acts)))


@router.get("/api/ideas", tags=["Ideas"])
def get_ideas(supabase=Depends(get_supabase)):
    # The list took 7.6s uncached (an N+1 over every published idea, most of
    # it shadow-record math). Serve the built payload while a light
    # fingerprint says nothing changed, and never for more than the TTL --
    # the shadow summaries age even when nothing is written.
    fp = _ideas_fingerprint(supabase)
    if _IDEAS_CACHE["payload"] is not None and _IDEAS_CACHE["fp"] == fp:
        # Nothing was written: answer now, and if it has aged, rebuild for the next visitor.
        if time.time() - _IDEAS_CACHE["at"] >= _IDEAS_CACHE_TTL and _IDEAS_REBUILD.acquire(blocking=False):
            try:
                threading.Thread(target=_rebuild_ideas_in_background, args=(supabase, fp), daemon=True).start()
            except RuntimeError:  # the list we have is still the right answer
                _IDEAS_REBUILD.release()
                log.exception("api: could not start the ideas rebuild")
        return _IDEAS_CACHE["payload"]
    return _api._build_ideas(supabase, fp)


def _rebuild_ideas_in_background(supabase, fp: tuple) -> None:
    try:
        _api._build_ideas(supabase, fp)
    except Exception:  # noqa: BLE001 -- the page keeps the last good list; the next visit tries again
        log.exception("api: ideas rebuild failed")
    finally:
        _IDEAS_REBUILD.release()


def _build_ideas(supabase, fp: tuple) -> list[dict]:
    big_acts = workshop_store.activations(supabase, "big")
    big_live = {a["idea_id"] for a in big_acts if a.get("live_at") and not a.get("killed_at") and a.get("auto_orders")}
    view = _registry_view(supabase)
    view["overridden_big"] = {a["idea_id"] for a in big_acts
                              if (a.get("gate") or {}).get("status") == "overridden"}
    out = []
    for idea in workshop_store.published_ideas(supabase):
        row = _public_idea(supabase, idea, workshop_store.saved_only(workshop_store.get_idea(supabase, idea["id"])["runs"]),
                           big_live=big_live, view=view)
        if row["live"]:
            row["live"] = {k: v for k, v in row["live"].items() if k != "curve"}
        out.append(row)
    _IDEAS_CACHE.update(at=time.time(), payload=out, fp=fp)
    return out


@router.get("/api/ideas/summary", tags=["Ideas"])
def get_ideas_summary(supabase=Depends(get_supabase)):
    # Saved runs only, judged under the current hub-wide standard: the
    # record line counts standing now, not the verdict as first recorded.
    from tradehub.workshop import registry

    latest = _latest_saved_map(supabase)
    adj = registry.adjusted(latest)
    tested = passed = failed = not_enough = 0
    for entry in adj.values():
        tested += 1
        if entry["verdict_now"] == "PASS":
            passed += 1
        elif entry["verdict_now"] == "FAIL":
            failed += 1
        elif entry["verdict_now"] == "NOT ENOUGH DATA":
            not_enough += 1
    published = len(workshop_store.published_ideas(supabase))
    return {"tested": tested, "passed": passed, "failed": failed, "not_enough_data": not_enough, "published": published}


@router.get("/api/ideas/critic-summary", tags=["Ideas"])
def get_critic_summary(supabase=Depends(get_supabase)):
    """Aggregate-first (Kevin, 2026-11-03): the critic's counts by
    recommendation and the worst degraders. Per-idea detail lives on each
    idea's own record (the critic block of /api/ideas), not in this summary."""
    latest = workshop_store.latest_critiques(supabase)
    titles = {i["id"]: i["title"] for i in workshop_store.list_ideas(supabase)}
    counts = {"PAUSE": 0, "WATCH": 0, "HOLD": 0}
    rows = []
    for (idea_id, book), row in latest.items():
        payload = row.get("payload") or {}
        rec = payload.get("recommendation")
        if rec in counts:
            counts[rec] += 1
        rows.append({"idea_id": idea_id, "title": titles.get(idea_id), "book": book,
                     "recommendation": rec, "degradation": payload.get("degradation"),
                     "days": (payload.get("live") or {}).get("days"),
                     "at": payload.get("at")})
    from tradehub.workshop.critic import MIN_DAYS

    worst = sorted((r for r in rows if r["degradation"] is not None
                    and (r["days"] or 0) >= MIN_DAYS),
                   key=lambda r: r["degradation"])[:5]
    return {"counts": counts, "units": len(rows), "worst": worst,
            "at": max((r["at"] for r in rows if r["at"]), default=None)}


@router.get("/api/ideas/{idea_id}", tags=["Ideas"])
def get_idea_record(idea_id: int, supabase=Depends(get_supabase)):
    found = workshop_store.get_idea(supabase, idea_id)
    if found is None or not found["idea"].get("published_at"):
        raise HTTPException(status_code=404, detail="no such idea")  # private and missing look the same
    from tradehub.portfolio import service

    view = _registry_view(supabase)
    view["overridden_big"] = {a["idea_id"] for a in workshop_store.activations(supabase, "big")
                              if (a.get("gate") or {}).get("status") == "overridden"}
    row = _public_idea(supabase, found["idea"], workshop_store.saved_only(found["runs"]), view=view)
    row["plain_words"] = found["idea"]["plain_words"]
    row["shadow"] = row.pop("live")
    row["runs"] = [{"variation": r["variation"], "verdict": r["verdict"], "created_at": r["created_at"],
                    "headline": r["result"].get("headline"), "p": (r["result"].get("shuffle") or {}).get("p"),
                    "bar": (r["result"].get("shuffle") or {}).get("bar"), "claim": r["spec"].get("claim"),
                    # The full detail (Kevin, 2026-11-02): it was always in the stored
                    # result -- the record page just never carried it. The curve and the
                    # same evidence blocks the Workshop verdict card shows.
                    "detail": {"curve": r["result"].get("curve") or [],
                               "reason": r["result"].get("reason"), "variations": r["result"].get("variations"),
                               "claim": r["result"].get("claim"), "shuffle": r["result"].get("shuffle"),
                               "batch": r["result"].get("batch"),
                               "t_test": r["result"].get("t_test"), "periods": r["result"].get("periods"),
                               "walk_forward": r["result"].get("walk_forward"),
                               "context": r["result"].get("context") or [],
                               "data_start": r["result"].get("data_start"), "data_end": r["result"].get("data_end"),
                               "split_date": r["result"].get("split_date"),
                               "n_events": r["result"].get("n_events"), "per_ticker": r["result"].get("per_ticker"),
                               "notes": r["result"].get("notes")}}
                   for r in workshop_store.saved_only(found["runs"])]
    try:
        trades = service.closed(supabase)["trades"]
    except Exception:  # noqa: BLE001 -- trades are context; the record stands without them
        trades = []
    row["trades"] = [t for t in trades if t["idea"] == found["idea"]["title"]]
    return row
