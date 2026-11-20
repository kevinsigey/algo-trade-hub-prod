"""Workshop and agent debates routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.workshop import store as workshop_store
from tradehub.workshop.data import UnknownSymbol
from tradehub.workshop.draft import DraftUnavailable
from tradehub.workshop.events import RELEASES, EventSpec
from tradehub.workshop.playbook import dropped_tickers as playbook_dropped
from tradehub.workshop.engine import analysis as workshop_analysis, tickers_for
from tradehub.portfolio.autotrade import option_structure_problems
from tradehub.workshop.playcheck import play_check as _play_check_math
from tradehub.workshop.data import NY
from tradehub.workshop.record import shadow_summary
from tradehub.workshop.spec import IdeaSpec, blank_spec


from tradehub.api.shared import (
    _fetch_all,
)
from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

from tradehub.api.routers.portfolio import _book_or_400
router = APIRouter()


# ── Trading HQ Workshop (step 2): Kevin-only. Plain words -> draft -> Kevin confirms -> run -> verdict. ──
class _DraftIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    free: bool = False  # skip the playbook: the AI writes the whole spec


class _IdeaIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    plain_words: str = Field(min_length=1, max_length=4000)
    # The search this idea is one trial of (A3, 2026-11-11). batch_trial is
    # optional: naming only the batch assigns the next trial in it.
    batch_id: str | None = Field(default=None, max_length=80)
    batch_trial: int | None = Field(default=None, ge=0)


class _RunIn(BaseModel):
    spec: IdeaSpec
    draft_model: str | None = None


def _fred_start(start: date) -> date:
    """FRED reads reach 3 years before the test start, so a lookback (max 756 trading days) is filled on day one."""
    return start - timedelta(days=3 * 366)


@router.post("/api/workshop/draft", tags=["Workshop"])
def workshop_draft(body: _DraftIn, _admin: dict = Depends(admin.require_admin)):
    d = None if body.free else _api.playbook_draft(body.text)  # a known play first; the AI only picks among the matches
    if d is not None:
        def play(x):
            return {"id": x.play.id, "name": x.play.name, "summary": x.play.summary, "source": x.play.source,
                    "why": list(x.why)}
        dropped = playbook_dropped(body.text, d.spec)
        return {"spec": d.spec.model_dump(mode="json"), "model": d.model, "play": play(d),
                "alternatives": [{**play(a), "spec": a.spec.model_dump(mode="json")} for a in d.alternatives],
                "dropped": dropped, "unexpressed": []}
    try:
        spec, model, dropped, unexpressed = _api.draft_spec(body.text)
    except DraftUnavailable as exc:
        return JSONResponse(status_code=424, content={"detail": str(exc), "reason": exc.reason,
                                                      "template": blank_spec()})
    return {"spec": spec.model_dump(mode="json"), "model": model, "play": None, "alternatives": [],
            "dropped": dropped, "unexpressed": unexpressed}


class _ImportIn(BaseModel):
    spec: dict[str, Any]
    requested: list[str] = []
    unexpressed: list[str] = []


@router.get("/api/workshop/tone", tags=["Workshop"])
def workshop_tone(_admin: dict = Depends(admin.require_admin)):
    """Every sector basket's current tone read (the Workshop tone panel):
    the latest completed day's GDELT tone and its trailing-60-day z -- the
    exact numbers the journal's sector tone rows freeze on. A basket that
    cannot be read (GDELT throttling, thin window) reports nulls, never an
    error: the panel shows the gap."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    from tradehub.journal.forecasters.news_tone import SECTORS, WINDOW_DAYS, tone_zscore
    from tradehub.workshop.news import news_tone_series

    today = _dt.now(_ZI("America/New_York")).date()
    sectors = []
    for sector, (basket, etf) in SECTORS.items():
        row = {"sector": sector, "basket": basket, "etf": etf,
               "tone_day": None, "tone": None, "z": None}
        try:
            found = tone_zscore(news_tone_series(basket, today - timedelta(days=WINDOW_DAYS + 40)), today)
        except Exception:  # noqa: BLE001 -- a GDELT outage is a gap in the panel, not a 500
            found = None
        if found is not None:
            z, tone_day, tone_value = found
            row.update(tone_day=tone_day.isoformat(), tone=round(tone_value, 3), z=round(z, 3))
        sectors.append(row)
    return {"as_of": today.isoformat(), "sectors": sectors}


@router.post("/api/workshop/draft/import", tags=["Workshop"])
def workshop_draft_import(body: _ImportIn, _admin: dict = Depends(admin.require_admin)):
    """The second drafting door (spec §2.2): a full spec drafted out-of-band -- in practice
    by Muse in a chat session with the conversation's full context -- is validated
    against the same generated contract and returned as a draft for the same confirm
    screen. Admin session only, and a draft is a draft: nothing runs until Kevin confirms
    it through the ordinary Workshop flow."""
    from pydantic import ValidationError

    from tradehub.workshop.draft import check_imported
    try:
        spec = IdeaSpec.model_validate(body.spec)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = "/".join(str(p) for p in first["loc"]) or "spec"
        raise HTTPException(422, detail=f"the spec does not fit the contract: {where}: {first['msg']}") from exc
    dropped, unexpressed = check_imported(spec, body.requested, body.unexpressed)
    return {"spec": spec.model_dump(mode="json"), "model": "import", "play": None, "alternatives": [],
            "dropped": dropped, "unexpressed": unexpressed}


@router.post("/api/workshop/ideas", tags=["Workshop"])
def workshop_create_idea(body: _IdeaIn, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    return workshop_store.create_idea(supabase, body.title, body.plain_words,
                                      batch_id=body.batch_id, batch_trial=body.batch_trial)


def _batch_for_run(supabase, found: dict) -> tuple[int, dict | None]:
    """(effective variations, batch stamp) for a run on this idea (A3,
    2026-11-11): the shuffle bar is raised by the trials in the idea's search,
    not by this idea's own reruns alone -- bar = 0.05 / max(own variation,
    batch size). An unbatched idea keeps its own count and gets no stamp."""
    own = len(found["runs"]) + 1
    info = workshop_store.batch_info(supabase, found["idea"])
    if not info:
        return own, None
    stamp = {"id": info["id"], "trial": info["trial"],
             "position": info["position"], "of": info["size"]}
    return max(own, info["size"]), stamp


@router.get("/api/agent-debates", tags=["Workshop"])
def agent_debates(_admin: dict = Depends(admin.require_admin)):
    """The TradingAgents debate feed (phase-2 §3.2): labelled cards + the debate record.
    Read-only and fenced -- this module has no path to orders, and debates are never
    model signals: the chip text rides on every card and on the payload itself.

    Failed runs are shown once, then deleted (Kevin, 2026-11-03): a failure
    already marked seen is removed before the feed is built; a fresh failure
    is marked seen as it is served. Cards also carry the market anchor stored
    at run time and a cached live price, so stated levels can be held against
    the tape."""
    from tradehub.agents import anchor as agents_anchor
    from tradehub.agents import payload as agents_payload, store as agents_store
    from tradehub.workshop.data import last_complete_day
    latest = last_complete_day(datetime.now(timezone.utc)).isoformat()
    runs = []
    for run in agents_store.list_runs():
        if run.status.startswith("failed"):
            if run.failure_seen:
                agents_store.delete_run(run.run_id)
                continue
            run = agents_store.mark_failure_seen(run)
        runs.append(run)
    live = agents_anchor.current_prices({r.ticker for r in runs if r.status == "complete"})
    return agents_payload.feed(runs, agents_store.load_grades(),
                               latest_session=latest, live=live)


class _DebateRunIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    force: bool = False  # rerun even inside the reuse window


# A debate is a daily-cadence read on a session: inside this window a rerun
# of the same ticker returns the existing debate instead of spending another
# panel (Kevin, 2026-11-03: replaced, not duplicated, unless real time has
# passed). force=True is the explicit override.
_DEBATE_REUSE_WINDOW = timedelta(hours=12)


_DEBATE_IN_FLIGHT: set[str] = set()
_DEBATE_LOCK = threading.Lock()


@router.post("/api/agent-debates/run", tags=["Workshop"], status_code=202)
def agent_debate_run(body: _DebateRunIn, _admin: dict = Depends(admin.require_admin)):
    """Start a debate from the page. A run takes minutes (an LLM panel), so it goes to a
    background thread; every outcome -- success, framework failure, the daily cap -- lands
    as a stored run record the feed then shows. One run per ticker at a time; the runner
    itself enforces the 10/day cap and the hub's debate quota."""
    from tradehub.agents import runner as agents_runner
    from tradehub.workshop.data import last_complete_day

    ticker = body.ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", ticker):
        raise HTTPException(status_code=422, detail="that does not look like a ticker")
    if not body.force:
        from tradehub.agents import store as agents_store

        now = datetime.now(timezone.utc)
        for run in agents_store.list_runs():  # newest first
            if run.ticker != ticker or run.status not in ("complete", "partial"):
                continue
            try:
                ran_at = datetime.fromisoformat(run.run_at_utc)
            except ValueError:
                break
            age = now - ran_at
            if age < _DEBATE_REUSE_WINDOW:
                return JSONResponse(status_code=200, content={
                    "reused": run.run_id, "ticker": ticker,
                    "age_hours": round(age.total_seconds() / 3600, 1)})
            break  # the newest is already outside the window; older ones are older
    with _DEBATE_LOCK:
        if ticker in _DEBATE_IN_FLIGHT:
            raise HTTPException(status_code=409, detail=f"a debate on {ticker} is already running")
        _DEBATE_IN_FLIGHT.add(ticker)

    def _go() -> None:
        try:
            latest = last_complete_day(datetime.now(timezone.utc)).isoformat()
            agents_runner.run_debate(ticker, latest_session=latest)
        finally:
            with _DEBATE_LOCK:
                _DEBATE_IN_FLIGHT.discard(ticker)

    threading.Thread(target=_go, daemon=True, name=f"debate-{ticker}").start()
    return {"started": ticker}


@router.get("/api/agent-debates/{run_id}/report", tags=["Workshop"])
def agent_debate_report(run_id: str, _admin: dict = Depends(admin.require_admin)):
    from tradehub.agents import store as agents_store
    text = agents_store.read_report(run_id)
    if text is None:
        raise HTTPException(404, detail="no such debate report")
    return Response(content=text, media_type="text/markdown")


@router.get("/api/workshop/ideas", tags=["Workshop"])
def workshop_list_ideas(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    rows = workshop_store.list_ideas(supabase)
    # The standing under the current bar rides along (A2, 2026-11-11): the
    # list chip reads verdict_now, with latest_verdict kept as the as-run
    # history. Ideas with no saved run have no standing yet (None).
    adjusted = _registry_view(supabase)["adjusted"]
    for r in rows:
        adj = adjusted.get(r["id"])
        r["verdict_now"] = adj["verdict_now"] if adj else None
    ideas = {i["id"]: i for i in supabase.table("ideas").select("*").execute().data or []}
    # Each idea's search standing rides along (A3, 2026-11-11): the list
    # shows "Trial N of M in <batch>" for generated and sibling ideas.
    batches = workshop_store.batch_map(list(ideas.values()))
    big = {a["idea_id"]: a for a in workshop_store.activations(supabase, "big")}
    for r in rows:
        r["batch"] = batches.get(r["id"])
        i = ideas.get(r["id"], {})
        r["live_at"] = i.get("live_at")
        r["tracked_at"] = i.get("tracked_at")
        r["killed_at"] = i.get("killed_at")
        r["auto_orders"] = i.get("auto_orders")
        r["size_pct"] = i.get("size_pct")
        a = big.get(r["id"]) or {}
        r["books"] = {"big": {"live_at": a.get("live_at"), "size_pct": a.get("size_pct"),
                              "auto_orders": bool(a.get("auto_orders")),
                              "killed_at": a.get("killed_at")}}
    return rows


def _found(supabase, idea_id: int) -> dict:
    found = workshop_store.get_idea(supabase, idea_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such idea")
    return found


def _shadow(supabase, idea: dict) -> dict:
    """The forward record, anchored to tracking until the idea goes live, then to the live run."""
    run_id = idea.get("live_run_id") or idea.get("tracked_run_id")
    start = idea.get("live_at") or idea.get("tracked_at")
    spec = IdeaSpec.model_validate(workshop_store.get_run(supabase, run_id)["spec"])
    start_day = datetime.fromisoformat(start).astimezone(NY).date()
    return shadow_summary(spec, workshop_store.shadow_days(supabase, idea["id"]), _api._today(), start_day)


@router.get("/api/workshop/ideas/{idea_id}", tags=["Workshop"])
def workshop_get_idea(idea_id: int, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    found = _found(supabase, idea_id)
    idea = found["idea"]
    # Each run's standing under the current bar, next to its as-run verdict
    # (A2, 2026-11-11): the stored verdict is history and never changes;
    # verdict_now is what the run is worth under today's bar.
    from tradehub.workshop import registry as _registry

    for r in found["runs"]:
        r.update(_registry.run_verdict_now(r))
    shadow = _shadow(supabase, idea) if (idea.get("live_at") or idea.get("tracked_at")) else None
    from tradehub.portfolio import books as _books
    from tradehub.portfolio.paper_orders import orders_enabled

    # Per-book live state (Kevin, 2026-11-02): main reads off the idea row (the record);
    # every other book reads its own activation. The panel renders one block per book.
    book_state = {"main": {"live_at": idea.get("live_at"), "size_pct": idea.get("size_pct"),
                           "auto_orders": bool(idea.get("auto_orders")),
                           "killed_at": idea.get("killed_at"), "gate": idea.get("gate"),
                           "orders_enabled": orders_enabled("main")}}
    for name in _books.names():
        if name == "main":
            continue
        act = workshop_store.activation(supabase, name, idea_id) or {}
        book_state[name] = {"live_at": act.get("live_at"), "size_pct": act.get("size_pct"),
                            "auto_orders": bool(act.get("auto_orders")),
                            "killed_at": act.get("killed_at"), "gate": act.get("gate"),
                            "orders_enabled": orders_enabled(name)}
    # The Spec F LEAPS shadow panel rides ideas tagged 'leaps-trial'
    # (idea 81; the trial state lives in leaps_shadow_pairs, not in the
    # share-basket lifecycle). Fail-soft: the panel never breaks the page.
    leaps_panel = None
    if "leaps-trial" in (idea.get("tags") or []):
        try:
            from tradehub import leaps_shadow as _leaps

            leaps_panel = _leaps.panel(supabase, idea)
        except Exception:  # noqa: BLE001
            leaps_panel = None
    return {**found, "tag": f"idea-{idea_id}-", "shadow": shadow, "orders_enabled": orders_enabled(),
            "books": book_state, "batch": workshop_store.batch_info(supabase, idea),
            "orders": workshop_store.order_log(supabase, idea_id, 50),
            "leaps": leaps_panel}


class _AutoIn(BaseModel):
    on: bool
    book: str = "main"


@router.post("/api/workshop/ideas/{idea_id}/auto", tags=["Workshop"])
def workshop_auto(idea_id: int, body: _AutoIn, user: dict = Depends(admin.require_admin),
                  supabase=Depends(get_supabase)):
    """Step 4: switch an idea's automatic PAPER orders on or off. On needs a live, unkilled idea."""
    if body.book != "main":
        _book_or_400(body.book)
        act = workshop_store.activation(supabase, body.book, idea_id)
        if body.on and (not act or not act.get("live_at") or act.get("killed_at")):
            raise HTTPException(status_code=409,
                                detail="only an idea live on that book and not killed there can trade")
        if not act:
            raise HTTPException(status_code=409, detail="the idea is not live on that book")
        if body.on:
            # The portfolio check rides the auto-on (Kevin, 2026-11-09):
            # enabling the auto-trader IS an activation, at the size and run
            # the book went live with.
            run = workshop_store.get_run(supabase, act["live_run_id"]) \
                if act.get("live_run_id") else None
            if run is not None:
                refusal = _portfolio_activation_check(
                    supabase, idea_id, run["spec"], float(act.get("size_pct") or 0), body.book)
                if refusal:
                    raise HTTPException(status_code=409, detail=refusal)
        return workshop_store.set_auto_book(supabase, body.book, idea_id, body.on,
                                            user.get("email", "admin"))
    idea = _found(supabase, idea_id)["idea"]
    if body.on and (not idea.get("live_at") or idea.get("killed_at")):
        raise HTTPException(status_code=409, detail="only a live idea that has not been killed can trade")
    if body.on:
        run = workshop_store.get_run(supabase, idea["live_run_id"]) \
            if idea.get("live_run_id") else None
        if run is not None:
            refusal = _portfolio_activation_check(
                supabase, idea_id, run["spec"], float(idea.get("size_pct") or 0), "main")
            if refusal:
                raise HTTPException(status_code=409, detail=refusal)
    return workshop_store.set_auto(supabase, idea_id, body.on, user.get("email", "admin"))


class _LiveIn(BaseModel):
    size_pct: float = Field(gt=0, le=100)
    # Kevin's deliberate gate override (first used 2026-11-02): bypasses ONLY
    # the 63-new-day wait. A claim that failed on new data, an oversize book,
    # an event study or a non-PASS run still refuse -- see workshop_go_live.
    override: bool = False
    override_note: str | None = Field(default=None, max_length=500)
    # Which book goes live (Kevin, 2026-11-02): the books are independent --
    # an idea can be live on either, both, or neither, at different sizes.
    book: str = "main"


class _LabelIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    idea_id: int | None = None


def _latest_saved_map(supabase) -> dict[int, dict]:
    """idea id -> its latest SAVED run row, hub-wide (save-by-choice: previews
    never set an idea's standing). One pass over idea_runs + idea_run_saves."""
    saved_ids = {s["run_id"] for s in _fetch_all(supabase, "idea_run_saves", lambda q: q.select("run_id"),
                                                 order=("run_id",))}
    latest: dict[int, dict] = {}
    for r in _fetch_all(supabase, "idea_runs", lambda q: q.select("id,idea_id,variation,verdict,result,spec")):
        if r["id"] not in saved_ids:
            continue
        cur = latest.get(r["idea_id"])
        if cur is None or r["id"] > cur["id"]:
            latest[r["idea_id"]] = r
    return latest


def _registry_view(supabase) -> dict:
    """The hub-wide standing (tradehub.workshop.registry): adjusted verdicts,
    ticker families and origins for every idea with a saved run, plus the
    registry size. Recomputed per call -- the tables are small."""
    from tradehub.workshop import registry

    latest = _api._latest_saved_map(supabase)
    holdings = {}
    for iid, r in latest.items():
        spec = r.get("spec") or {}
        holdings[iid] = set(spec.get("hold") or []) | set(spec.get("short") or [])
    screen_ids = {s["promoted_idea_id"] for s in
                  supabase.table("screens").select("promoted_idea_id").execute().data or []
                  if s.get("promoted_idea_id")}
    try:
        critics = {key: row.get("payload") for key, row in workshop_store.latest_critiques(supabase).items()}
    except Exception:  # noqa: BLE001 -- the critic is an overlay; its table missing never breaks the list
        critics = {}
    return {"adjusted": registry.adjusted(latest), "families": registry.families(holdings),
            "screen_ids": screen_ids, "critics": critics,
            "tests_total": len(supabase.table("idea_runs").select("id").execute().data or [])}


def _gate(supabase, idea_id: int, size_pct: float | None) -> tuple[dict, dict | None]:
    """The live-paper gate on the idea's latest SAVED run, recomputed from fresh prices
    every time it is asked. A preview run never reaches the gate (save-by-choice)."""
    runs = _found(supabase, idea_id)["runs"]
    saved = workshop_store.saved_only(runs)
    latest = saved[-1] if saved else None
    if latest is None and runs:
        return {"status": "fails", "new_days": 0, "needed": 0, "claim": None, "size_ok": None,
                "reasons": ["no saved run yet: previews don't count toward the gate -- save a run first"]}, None
    if latest is not None and (latest.get("spec") or {}).get("kind") == "event":
        return {"status": "fails", "new_days": 0, "needed": 0, "claim": None, "size_ok": None,
                "reasons": ["event studies are research only for now: they don't trade on paper"]}, None
    if latest is None or latest["verdict"] != "PASS":
        return {"status": "fails", "new_days": 0, "needed": 0, "claim": None, "size_ok": None,
                "reasons": ["the latest run did not PASS"]}, None
    adj = _registry_view(supabase)["adjusted"].get(idea_id)
    if adj is not None and adj["verdict_now"] != "PASS":
        why = []
        if adj["fdr_pass"] is False:
            why.append("its p-value does not survive the hub-wide FDR adjustment over every idea's test")
        if adj.get("p_ok") is False:
            why.append(f"its p-value of {adj['p']:.3f} is over the 0.01 standard")
        if adj["wf_ok"] is False:
            wf = (latest.get("result") or {}).get("walk_forward") or {}
            why.append(f"its claim held in only {wf.get('held')} of {wf.get('of')} walk-forward folds "
                       "(the standard is at least 3 of 4)")
        return {"status": "fails", "new_days": 0, "needed": 0, "claim": None, "size_ok": None,
                "reasons": ["the latest run's PASS no longer stands under the hub-wide standard "
                            "(Kevin, 2026-11-03): " + "; ".join(why)]}, latest
    spec = IdeaSpec.model_validate(latest["spec"])
    try:
        prices = _api.with_rule_bars(spec, _api.workshop_closes(tickers_for(spec), spec.start), spec.start,
                                bars_fn=_api.workshop_bars)
        fred = _api.rule_series(spec, _fred_start(spec.start), fred=_api.workshop_fred, analyst_fn=_api.workshop_analyst)
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    frame = _api.workshop_daily_frame(spec, prices, fred, _api.workshop_div_yields(spec, prices))
    return _api.gate_check(spec, frame, date.fromisoformat(latest["data_end"]), size_pct), latest


@router.get("/api/workshop/ideas/{idea_id}/gate", tags=["Workshop"])
def workshop_gate(idea_id: int, size_pct: float | None = Query(None, gt=0, le=100),
                  _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    return _gate(supabase, idea_id, size_pct)[0]


@router.get("/api/workshop/dune-series", tags=["Workshop"])
def workshop_dune_series(supabase=Depends(get_supabase)):
    """The Dune catalogue (crypto step 3): the on-chain series a Workshop rule
    can read (source "dune"), with their spans and freshness. Metadata only --
    the points themselves stay inside the engine."""
    from tradehub.workshop.dune import list_dune_series

    return {"series": list_dune_series(supa=supabase)}


class _TagsIn(BaseModel):
    tags: list[str]


@router.put("/api/workshop/ideas/{idea_id}/tags", tags=["Workshop"])
def workshop_tags(idea_id: int, body: _TagsIn, _admin: dict = Depends(admin.require_admin),
                  supabase=Depends(get_supabase)):
    _found(supabase, idea_id)
    _api._bust_ideas_cache()
    return workshop_store.set_tags(supabase, idea_id, body.tags)


@router.post("/api/workshop/ideas/{idea_id}/publish", tags=["Workshop"])
def workshop_publish(idea_id: int, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    _api._bust_ideas_cache()
    _found(supabase, idea_id)
    try:
        return workshop_store.publish(supabase, idea_id)
    except workshop_store.AlreadySet as exc:
        raise HTTPException(status_code=409, detail="already published") from exc


class _TrackIn(BaseModel):
    run_id: int | None = None


@router.post("/api/workshop/ideas/{idea_id}/track", tags=["Workshop"])
def workshop_track(idea_id: int, body: _TrackIn, _admin: dict = Depends(admin.require_admin),
                   supabase=Depends(get_supabase)):
    """Start the forward shadow record for a PASS run: observation only, no orders, no gate.
    Tracking is the step between a pass and going live -- the record that later feeds the gate."""
    _api._bust_ideas_cache()
    found = _found(supabase, idea_id)
    idea = found["idea"]
    if idea.get("tracked_at"):
        raise HTTPException(status_code=409, detail="already tracking")
    runs = found["runs"]
    if body.run_id is not None:
        run = next((r for r in runs if r["id"] == body.run_id), None)
        if run is not None and not run.get("saved_at"):
            raise HTTPException(status_code=409, detail="save the run first: previews can't be tracked")
    else:
        saved = workshop_store.saved_only(runs)
        run = saved[-1] if saved else None
    if run is None:
        raise HTTPException(status_code=409, detail="no run to track")
    if run["verdict"] != "PASS":
        raise HTTPException(status_code=409, detail="only a PASS run can be tracked")
    adj = _registry_view(supabase)["adjusted"].get(idea_id)
    if adj is not None and adj["verdict_now"] != "PASS":
        raise HTTPException(status_code=409,
                            detail="this run's PASS no longer stands under the hub-wide standard "
                                   "(FDR over all tests, p at or under 0.01, and 3 of 4 walk-forward folds)")
    if (run.get("spec") or {}).get("kind") == "event":
        raise HTTPException(status_code=409, detail="event studies are research only: they don't track forward")
    try:
        return workshop_store.track(supabase, idea_id, run["id"])
    except workshop_store.AlreadySet as exc:
        raise HTTPException(status_code=409, detail="already tracking") from exc


@router.post("/api/workshop/ideas/{idea_id}/live", tags=["Workshop"])
def workshop_go_live(idea_id: int, body: _LiveIn, _admin: dict = Depends(admin.require_admin),
                     supabase=Depends(get_supabase)):
    _api._bust_ideas_cache()
    if body.book != "main":
        _book_or_400(body.book)
        act = workshop_store.activation(supabase, body.book, idea_id)
        if act and act.get("live_at"):
            raise HTTPException(status_code=409, detail="already live on that book")
    elif _found(supabase, idea_id)["idea"].get("live_at"):
        raise HTTPException(status_code=409, detail="already live")
    gate, run = _gate(supabase, idea_id, body.size_pct)
    if gate["status"] != "ready":
        # The override covers the day-count wait and nothing else: the gate
        # must be WAITING (a "fails" -- the claim fell on new data, or the
        # saved PASS no longer meets the hub-wide standard -- is never
        # waivable, even with its checks unset), the run must exist, and the
        # size must have positively fit (CodeRabbit on #575).
        overridable = (run is not None and gate["status"] == "waiting"
                       and gate.get("size_ok") is True
                       and (gate.get("claim") or {}).get("holds") is not False)
        if not (body.override and overridable):
            raise HTTPException(status_code=409, detail="; ".join(gate["reasons"]) or "the gate is not clear")
        gate = {**gate, "status": "overridden",
                "override": {"by": "Kevin Sigey",
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "note": body.override_note or "63-day gate overridden on Kevin's explicit call",
                             "gate_status_was": gate["status"]}}
    if (run.get("spec") or {}).get("options"):
        check = _api._play_check(supabase, _found(supabase, idea_id)["idea"], run["spec"], body.size_pct, body.book)
        if not check.get("available"):  # can't size it against the book, so can't say it's safe
            raise HTTPException(status_code=409, detail=check.get("note") or "the book could not be read")
        if check.get("structure_problems"):
            raise HTTPException(status_code=409, detail=" ".join(check["structure_problems"]))
    # The portfolio check (Kevin, 2026-11-09): the last gate before any book
    # goes live on this idea -- a breach lands in the manual-actions queue with
    # the portfolio reason and refuses the activation.
    refusal = _portfolio_activation_check(supabase, idea_id, run["spec"], body.size_pct, body.book)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    if body.book != "main":
        return workshop_store.go_live_book(supabase, body.book, idea_id, run["id"],
                                           body.size_pct, gate)
    try:
        return workshop_store.go_live(supabase, idea_id, run["id"], body.size_pct, gate)
    except workshop_store.AlreadySet as exc:
        raise HTTPException(status_code=409, detail="already live") from exc


@router.post("/api/workshop/ideas/{idea_id}/kill", tags=["Workshop"])
def workshop_kill(idea_id: int, book: str = "main", _admin: dict = Depends(admin.require_admin),
                  supabase=Depends(get_supabase)):
    _api._bust_ideas_cache()
    if book != "main":
        _book_or_400(book)
        act = workshop_store.activation(supabase, book, idea_id)
        if not act or not act.get("live_at"):
            raise HTTPException(status_code=409, detail="only an idea live on that book can be killed there")
        if act.get("killed_at"):
            raise HTTPException(status_code=409, detail="already killed on that book")
        return workshop_store.kill_book(supabase, book, idea_id)
    if _found(supabase, idea_id)["idea"].get("killed_at"):
        raise HTTPException(status_code=409, detail="already killed")
    try:
        return workshop_store.kill(supabase, idea_id)
    except workshop_store.AlreadySet as exc:
        raise HTTPException(status_code=409, detail="already killed") from exc


@router.post("/api/workshop/labels", tags=["Workshop"])
def workshop_label(body: _LabelIn, user: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    if body.idea_id is not None and workshop_store.get_idea(supabase, body.idea_id) is None:
        raise HTTPException(status_code=422, detail=f"no idea {body.idea_id}")
    return workshop_store.add_label(supabase, body.order_id, body.idea_id, user.get("email", "admin"))


def _run_frame(supabase, idea_id: int, run_id: int):
    """A stored run's spec and its daily frame, recomputed from its spec and cut at the run's own data_end."""
    run = workshop_store.get_run(supabase, run_id)
    if run is None or run.get("idea_id") != idea_id:
        raise HTTPException(status_code=404, detail="no such run")
    if (run.get("spec") or {}).get("kind") == "event":
        raise HTTPException(status_code=422, detail="the deeper look is for rule ideas; an event study lists its events")
    spec = IdeaSpec.model_validate(run["spec"])
    try:
        prices = _api.with_rule_bars(spec, _api.workshop_closes(tickers_for(spec), spec.start), spec.start,
                                bars_fn=_api.workshop_bars)
        fred = _api.rule_series(spec, _fred_start(spec.start), fred=_api.workshop_fred, analyst_fn=_api.workshop_analyst)
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    end = (run.get("result") or {}).get("data_end")
    frame = _api.workshop_daily_frame(spec, prices, fred, _api.workshop_div_yields(spec, prices))
    if end:
        frame = frame[frame.index <= pd.Timestamp(end)]
    return spec, frame, prices, end, run.get("result") or {}


@router.get("/api/workshop/ideas/{idea_id}/runs/{run_id}/analysis", tags=["Workshop"])
def workshop_run_analysis(idea_id: int, run_id: int, _admin: dict = Depends(admin.require_admin),
                          supabase=Depends(get_supabase)):
    _, frame, _, end, stored = _run_frame(supabase, idea_id, run_id)
    curve = stored.get("curve") or []
    # Today's prices (dividend restatements, revised series) can differ from what the verdict judged: say by how much.
    drift = float(((1 + frame["ret"]).prod() - 1) * 100 - curve[-1]["idea"]) if curve and len(frame) else None
    return {**workshop_analysis(frame), "data_end": end, "drift_pts": drift}


@router.get("/api/workshop/ideas/{idea_id}/runs/{run_id}/daily.csv", tags=["Workshop"])
def workshop_run_csv(idea_id: int, run_id: int, _admin: dict = Depends(admin.require_admin),
                     supabase=Depends(get_supabase)):
    run = workshop_store.get_run(supabase, run_id)
    if run is not None and run.get("idea_id") == idea_id and (run.get("spec") or {}).get("kind") == "event":
        cols = ["date", "ticker", "surprise", "ar0", "car_1_3", "car_1_5", "car_1_10", "pre_5"]
        table = pd.DataFrame((run.get("result") or {}).get("events") or [], columns=cols)
        return Response(table.to_csv(index=False, float_format="%.6g"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="idea-{idea_id}-run-{run_id}-events.csv"'})
    spec, frame, prices, _, _ = _run_frame(supabase, idea_id, run_id)
    legs = list(dict.fromkeys(list(spec.hold) + list(spec.short) + ([spec.otherwise] if spec.otherwise != "CASH" else [])
                              + [spec.benchmark]))
    out = pd.DataFrame({"rule_on": frame["on"].astype(int),
                        "held": frame.get("held", frame["on"]).astype(int), "idea_ret": frame["ret"], "bench_ret": frame["bench"],
                        "spy_ret": frame["spy"], "exit": frame["exit"]}, index=frame.index)
    for t in legs:
        out[f"close_{t}"] = prices[t].reindex(frame.index)
    out.index = out.index.strftime("%Y-%m-%d")
    return Response(out.to_csv(index_label="date", float_format="%.8g"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="idea-{idea_id}-run-{run_id}-daily.csv"'})


@router.get("/api/workshop/tickers", tags=["Workshop"])
def workshop_tickers(symbols: str = Query(..., max_length=300), _admin: dict = Depends(admin.require_admin)):
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    if len(wanted) > 20:
        raise HTTPException(status_code=422, detail="at most 20 tickers")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:  # Yahoo's .info is slow; look them up side by side
        return dict(zip(wanted, pool.map(_api.workshop_ticker_info, wanted)))


class _EventRunIn(BaseModel):
    spec: EventSpec
    draft_model: str | None = None


@router.post("/api/workshop/ideas/{idea_id}/runs/{run_id}/save", tags=["Workshop"])
def workshop_save_run(idea_id: int, run_id: int, _admin: dict = Depends(admin.require_admin),
                      supabase=Depends(get_supabase)):
    """Save a preview run (save-by-choice, 2026-11-02): the run joins the record --
    public page, gate, tracking -- only once saved. Idempotent."""
    found = _found(supabase, idea_id)
    if not any(r["id"] == run_id for r in found["runs"]):
        raise HTTPException(status_code=404, detail="no such run")
    return workshop_store.save_run(supabase, run_id)


NOMINAL_BOOK_EQUITY = 100_000.0


def _play_check(supabase, idea: dict, spec_dict: dict, size_pct: float, book: str = "main",
                *, nominal: bool = False) -> dict:
    """The one-click play check (Kevin, 2026-11-02): read-only. The idea's target
    book at `size_pct` against the chosen paper book, with a cash verdict.
    Never stages or places anything.

    `nominal=True` (the public route, #579) never reads an account: the play is
    sized against a nominal all-cash book of NOMINAL_BOOK_EQUITY, so nothing
    about the paper accounts' equity, cash or holdings reaches an anonymous
    caller. The live-book check stays on the admin route."""
    if spec_dict.get("kind") == "event":
        raise HTTPException(status_code=409, detail="event studies are research only: there is no book to run")
    try:
        spec = IdeaSpec(**spec_dict)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"the run's spec no longer validates: {exc}") from exc
    try:
        prices_frame = _api.with_rule_bars(spec, _api.workshop_closes(tickers_for(spec), spec.start), spec.start,
                                      bars_fn=_api.workshop_bars)
        fred = _api.rule_series(spec, _fred_start(spec.start), fred=_api.workshop_fred, analyst_fn=_api.workshop_analyst)
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    weights, why = _api.target_and_reason(spec, prices_frame, fred, _api.workshop_div_yields(spec, prices_frame))
    prices = {t: float(prices_frame[t].dropna().iloc[-1]) for t in prices_frame.columns
              if t in prices_frame and len(prices_frame[t].dropna())}

    from tradehub.portfolio import service
    from tradehub.portfolio.books import BOOKS, resolve

    if nominal:
        book_name, book_label = "nominal", f"Nominal ${NOMINAL_BOOK_EQUITY:,.0f} cash book"
        book = {"as_of": None, "scoreboard": {"equity": NOMINAL_BOOK_EQUITY},
                "positions": [{"symbol": "Cash", "qty": None, "market_value": NOMINAL_BOOK_EQUITY, "idea": None}]}
    else:
        try:
            book_name = resolve(book)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        book_label = BOOKS[book_name]["label"]
        book = service.portfolio(supabase, book_name=book_name)
    if book.get("state") == "not_connected" or not book.get("positions"):
        return {"available": False, "size_pct": size_pct, "book": book_name,
                "book_label": book_label,
                "note": "No paper account is connected, so there is no book to check the play against."}
    equity = float(book["scoreboard"]["equity"])
    cash_row = next((r for r in book["positions"] if r["symbol"] == "Cash"), None)
    cash = float(cash_row["market_value"]) if cash_row else 0.0
    out = _play_check_math(weights=weights, why="" if why == "no data" else why, prices=prices,
                           equity=equity, cash=cash, positions=book["positions"], size_pct=size_pct,
                           own_title=idea["title"], otherwise=spec.otherwise,
                           legs=list(spec.hold) + list(spec.short))
    out.update({"available": True, "book": book_name, "book_label": book_label,
                "as_of": book.get("as_of"), "idea_id": idea["id"], "title": idea["title"],
                "options_legs": [leg.model_dump(mode="json") for leg in spec.options],
                "notes": ["Prices are latest closes, not live quotes."]})
    if any(r["target_value"] < 0 for r in out["rows"]):
        out["notes"].append("Short legs: borrow availability is not checked.")
    if spec.options:
        out["notes"].append("Option legs are model-priced and not in the share math.")
        # The rule may be out today; the structure is judged as if it were in.
        full = {t: 1 / len(spec.hold) for t in spec.hold}
        out["structure_problems"] = option_structure_problems(spec.options, full, size_pct, equity, prices)
    return out


def _portfolio_activation_check(supabase, idea_id: int, spec_dict: dict,
                                size_pct: float, book: str) -> str | None:
    """The portfolio check at activation time (Kevin, 2026-11-09): the same gate
    that guards machine orders, run on the activation's full envelope -- the
    blended target weights at `size_pct` of the book's equity, laid on top of the
    book as it stands (a fresh activation's conservative fiction: the check
    cannot assume the morning planner would first sell something else). Returns
    the refusal detail when the activation would breach a cap, None when it may
    proceed. A book that cannot be read proceeds with an "unavailable" event
    recorded -- placement is impossible on a disconnected account anyway, and
    the existing activation machinery has always degraded the same way.

    Options specs are noted, not gated, in v1: their book impact is the premium,
    already sized and structure-checked by the go-live play check; the share
    envelope says nothing honest about them."""
    from tradehub.portfolio import alpaca_paper, portfolio_check
    from tradehub.workshop.engine import _blend_weights

    try:
        spec = IdeaSpec(**spec_dict)
    except Exception:  # noqa: BLE001 -- endpoint validation owns the 422 for this
        return None
    if spec.options:
        portfolio_check.record_event(
            supabase, book, "activation", None,
            {"outcome": "pass",
             "detail": f"activation of idea {idea_id} carries option legs; the "
                       "portfolio check gates share envelopes in v1 and the "
                       "structure is sized by the go-live play check",
             "blocks": [], "warnings": []})
        return None
    idea_weights = {}
    if spec.hold:
        idea_weights.update({t: 1 / len(spec.hold) for t in spec.hold})
    if spec.short:
        idea_weights.update({t: -1 / len(spec.short) for t in spec.short})
    weights = _blend_weights(spec, idea_weights)
    try:
        account = alpaca_paper.paper_get("/v2/account", book=book) or {}
        equity = float(account.get("equity") or 0)
        if equity <= 0:
            raise ValueError("the account read back no equity")
    except Exception as exc:  # noqa: BLE001 -- stated, then the activation proceeds
        portfolio_check.record_event(
            supabase, book, "activation", None,
            {"outcome": "unavailable", "blocks": [], "warnings": [],
             "detail": f"portfolio check unavailable at activation of idea {idea_id}: "
                       f"the book could not be read ({type(exc).__name__})"})
        return None
    deltas = {t: w * (float(size_pct) / 100.0) * equity for t, w in weights.items()}
    block = portfolio_check.check_order(supabase, book, deltas, source="activation",
                                        idea_id=idea_id)
    if block["outcome"] == "block":
        reason = (f"portfolio check: idea {idea_id} at {size_pct:g}% of {book} "
                  f"would breach a cap -- {block['blocks'][0]['detail']}")
        workshop_store.add_manual_action(
            supabase, book, idea_id, "portfolio_check", None, reason)
        return reason
    return None


@router.get("/api/workshop/ideas/{idea_id}/play-check", tags=["Workshop"])
def workshop_play_check(idea_id: int, size_pct: float = Query(10, gt=0, le=100),
                        book: str = Query("main"),
                        _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """Play check on the Workshop's working spec: the newest run, saved or preview
    -- it is the spec on screen, and the check changes nothing either way."""
    found = _found(supabase, idea_id)
    if not found["runs"]:
        raise HTTPException(status_code=409, detail="no run yet: there is no spec to check")
    return _api._play_check(supabase, found["idea"], found["runs"][-1]["spec"], size_pct, book)


@router.post("/api/workshop/ideas/{idea_id}/event-runs", tags=["Workshop"])
def workshop_event_run(idea_id: int, body: _EventRunIn, _admin: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    """An event study (earnings, FOMC/CPI/jobs days, price gaps), judged like a rule idea but on events."""
    found = workshop_store.get_idea(supabase, idea_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such idea")
    spec = body.spec
    try:
        closes = _api.workshop_closes(list(dict.fromkeys(spec.tickers + [spec.benchmark])), spec.start - timedelta(days=30))
        if spec.event == "earnings":
            events = {t: _api.workshop_earnings(t) for t in spec.tickers}
        elif spec.event == "fomc":
            # The frozen statement table, never a FRED release list: release
            # 101's dates were every business day (spec 2026-11-08, Amendment 2).
            events = {"*": _api.workshop_fomc_times()}
        elif spec.event in RELEASES:
            events = {"*": _api.workshop_release_dates(RELEASES[spec.event])}
        else:
            events = {}
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    variation = len(found["runs"]) + 1
    eff_variations, batch_stamp = _batch_for_run(supabase, found)
    result = _api.run_event_test(spec, closes, events, variations=eff_variations, seed=idea_id * 1000 + variation)
    if batch_stamp:
        result = {**result, "batch": batch_stamp}
    return workshop_store.insert_run(supabase, idea_id, variation, spec.model_dump(mode="json"), body.draft_model,
                                     result)


def _run_autopsy(spec, prices, fred, div_yields, variation: int) -> dict:
    """The failure-pattern read for a run. A broken diagnosis never costs the run its verdict."""
    from tradehub.workshop import autopsy as autopsy_mod

    try:
        return autopsy_mod.autopsy(_api.workshop_daily_frame(spec, prices, fred, div_yields), hold=list(spec.hold),
                                   closes=prices, has_exits=spec.exits.any(), variation=variation)
    except Exception:  # noqa: BLE001
        log.exception("api: run autopsy failed")
        return {"status": "unavailable"}


@router.post("/api/workshop/ideas/{idea_id}/runs", tags=["Workshop"])
def workshop_run(idea_id: int, body: _RunIn, _admin: dict = Depends(admin.require_admin),
                 supabase=Depends(get_supabase)):
    found = workshop_store.get_idea(supabase, idea_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such idea")
    spec = body.spec
    if spec.claim_type == "event":
        # Event studies are declared with an EventSpec and run on the event-study
        # endpoint, where the event battery renders the verdict (spec 2026-11-08,
        # Amendment 2). An IdeaSpec has no event windows; grading it here would
        # use the wrong instrument. Overlay runs through this path like basket does.
        raise HTTPException(status_code=422,
                            detail="claim_type 'event' runs through the event-study endpoint "
                                   "(POST /api/workshop/ideas/{idea_id}/event-runs): an IdeaSpec "
                                   "has no event windows (spec 2026-11-08)")
    try:
        prices = _api.with_rule_bars(spec, _api.workshop_closes(tickers_for(spec), spec.start), spec.start,
                                bars_fn=_api.workshop_bars)
        fred = _api.rule_series(spec, _fred_start(spec.start), fred=_api.workshop_fred, analyst_fn=_api.workshop_analyst)
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    variation = len(found["runs"]) + 1
    eff_variations, batch_stamp = _batch_for_run(supabase, found)
    div_yields = _api.workshop_div_yields(spec, prices)
    result = _api.run_test(spec, prices, fred, variations=eff_variations, seed=idea_id * 1000 + variation,
                      div_yields=div_yields)
    if batch_stamp:
        result = {**result, "batch": batch_stamp}
    return workshop_store.insert_run(supabase, idea_id, variation, spec.model_dump(mode="json"), body.draft_model,
                                     {**result, "autopsy": _run_autopsy(spec, prices, fred, div_yields, variation)})


@router.post("/api/agent/interpret", tags=["Agent"])
def agent_interpret(body: dict, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """The new-idea check: strategy text -> the questions it leaves open and what the record
    already says. Stores nothing. An exact duplicate of a killed idea gets no draft."""
    from tradehub.agent.interpret import InterpretUnavailable, interpret
    from tradehub.agent.preflight import preflight

    try:
        spec, questions, model = interpret(str(body.get("text") or ""), body.get("context") or None)
    except InterpretUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        ledger = preflight(supabase, spec, _api._latest_saved_map(supabase))
    except Exception as exc:  # noqa: BLE001 -- the check informs; losing it never loses the draft
        log.exception("api: idea pre-flight failed")
        return {"spec": spec, "questions": questions, "model": model,
                "preflight": {"error": f"{type(exc).__name__}: {exc}"[:200]}}
    if ledger["duplicate_of_killed"] is not None:
        first = next(k for k in ledger["killed"] if k["exact"])
        questions = [f"This exact idea was killed (idea {first['idea_id']}): {first['reason']}. What's different this time?",
                     *questions]
        spec = None
    return {"spec": spec, "questions": questions, "model": model, "preflight": ledger}


@router.get("/api/workshop/dashboard", tags=["Workshop"])
def workshop_dashboard(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """The Workshop dashboard (Kevin, 2026-11-02: the page ballooned into flat
    lists -- totals up front, detail behind tabs). Idea and run totals from the
    record; fill totals from the same attribution the labels page uses (an
    order's tag, else the latest relabel); a fill NEEDS a label only when
    neither exists. Closed P&L is grouped by the idea each trade counts toward."""
    from tradehub.portfolio import book, service
    from tradehub.portfolio.alpaca_paper import AccountNotConnected
    from tradehub.screening import store as screen_store

    rows = workshop_store.list_ideas(supabase)
    ideas = {"total": len(rows), "live": 0, "live_big": 0, "tracking": 0,
             "published": 0, "draft": 0, "killed": 0}
    # Headline counts are standings under the current bar (A2, 2026-11-11);
    # the as-run counts ride along so the re-labelling is visible, not silent.
    adjusted = _registry_view(supabase)["adjusted"]
    verdicts: dict[str, int] = {}
    verdicts_as_run: dict[str, int] = {}
    for r in rows:
        if r.get("killed_at"):
            ideas["killed"] += 1
        elif r.get("live_at"):
            ideas["live"] += 1
        elif r.get("tracked_at"):
            ideas["tracking"] += 1
        elif r.get("published_at"):
            ideas["published"] += 1
        else:
            ideas["draft"] += 1
        if r.get("latest_verdict"):
            verdicts_as_run[r["latest_verdict"]] = verdicts_as_run.get(r["latest_verdict"], 0) + 1
            adj = adjusted.get(r["id"])
            now = adj["verdict_now"] if adj else r["latest_verdict"]
            verdicts[now] = verdicts.get(now, 0) + 1
    ideas["live_big"] = len({a["idea_id"] for a in workshop_store.activations(supabase, "big")
                             if a.get("live_at") and not a.get("killed_at")})
    all_runs = supabase.table("idea_runs").select("id,idea_id,verdict,created_at").execute().data or []
    saved_ids = {x["run_id"] for x in supabase.table("idea_run_saves").select("run_id").execute().data or []}
    titles = {r["id"]: r["title"] for r in rows}
    recent = sorted((r for r in all_runs if r["id"] in saved_ids),
                    key=lambda r: r.get("created_at") or "", reverse=True)[:8]
    runs = {"total": len(all_runs), "saved": len(saved_ids), "latest_verdicts": verdicts,
            "latest_verdicts_as_run": verdicts_as_run,
            "recent": [{"idea_id": r["idea_id"], "title": titles.get(r["idea_id"]),
                        "verdict": r["verdict"], "at": r.get("created_at")} for r in recent]}
    fills_payload: dict = {"state": "not_connected", "total": 0, "attributed": 0,
                           "needs_label": 0, "closed_pnl_by_idea": []}
    try:
        fills, client_ids = service.tagged_fills(supabase, public=False)
        history = workshop_store.label_history(supabase)

        def _needs_label(f) -> bool:
            # Decided already: a relabel row exists, the order's tag names an
            # idea, or the client id is one of the hub's own self-describing
            # prefixes (ext- machine orders, manual- hand orders). What is
            # left -- fills placed outside the hub, e.g. in the broker app --
            # is the residue that genuinely needs Kevin's label.
            if f.get("order_id") in history:
                return False
            cid = client_ids.get(f.get("order_id")) or ""
            return book.tag_id(cid) is None and not cid.startswith(("ext-", "manual-"))

        needs = sum(1 for f in fills if _needs_label(f))
        closed = service.closed(supabase)
        pnl: dict[str, dict] = {}
        for t in closed.get("trades", []):
            key = t.get("idea") or "Manual / mirror"
            slot = pnl.setdefault(key, {"idea": key, "pnl": 0.0, "trades": 0})
            slot["pnl"] += float(t.get("pnl") or 0)
            slot["trades"] += 1
        fills_payload = {"state": "live", "total": len(fills),
                         "attributed": sum(1 for f in fills if f.get("idea_id") is not None),
                         "needs_label": needs,
                         "closed_pnl_by_idea": sorted(pnl.values(), key=lambda x: x["pnl"], reverse=True)}
    except AccountNotConnected:
        pass
    screens = screen_store.list_screens(supabase)
    return {"ideas": ideas, "runs": runs, "fills": fills_payload,
            "screens": {"total": len(screens),
                        "promoted": sum(1 for x in screens if x.get("promoted_idea_id"))},
            "manual_actions_open": sum(len(workshop_store.manual_actions(supabase, b))
                                       for b in ("main", "big"))}


@router.get("/api/workshop/fills", tags=["Workshop"])
def workshop_fills(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """Kevin's paper fills, newest first, each with its idea and its full relabel history (tag first)."""
    from tradehub.portfolio import book, service
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    try:
        fills, client_ids = service.tagged_fills(supabase, public=False)
    except AccountNotConnected:
        return {"state": "not_connected", "fills": []}
    history = workshop_store.label_history(supabase)
    out = []
    for f in sorted(fills, key=lambda f: f["transaction_time"], reverse=True)[:200]:
        tag = client_ids.get(f.get("order_id")) or None
        prev, steps = book.tag_id(tag), []
        for h in history.get(f.get("order_id"), []):
            steps.append({"from": prev, "to": h["idea_id"], "by": h["by"], "at": h["at"]})
            prev = h["idea_id"]
        out.append({"order_id": f.get("order_id"), "symbol": f["symbol"], "side": f["side"], "qty": float(f["qty"]),
                    "price": float(f["price"]), "at": f["transaction_time"], "tag": tag, "idea_id": f["idea_id"],
                    "idea": f["idea"], "history": steps})
    return {"state": "live", "fills": out}
