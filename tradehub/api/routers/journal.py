"""Journal, scoreboard and track record routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from tradehub.api.schemas import (
    ShadowPerformanceResponse,
)
from tradehub.api.dependencies import get_supabase
from tradehub.engine_catalogue import engine_catalogue
from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses, table_missing
from tradehub.journal.legacy import journal_scores, merge_track_record
from tradehub.journal.scoring import headline as journal_headline
from tradehub.journal.standings import standings as journal_standings
from tradehub.journal.standings import verdict_sentence as journal_verdict_sentence
from tradehub.scoreboard import current_runs, market_comparison


from tradehub.api.shared import (
    _missing_table_message, _table_fault,
    _fetch_all,
)
from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

from tradehub.api.routers.desks import _target_day
router = APIRouter()


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 8: /api/shadow-performance
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/shadow-performance", response_model=ShadowPerformanceResponse, tags=["Shadow"])
async def get_shadow_performance(
    domain: str = Query("crypto", description="Domain to visualize; currently only crypto is supported"),
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
):
    try:
        return _api.build_shadow_timeline_response(domain=domain, hours=hours)
    except ValueError as exc:
        # The one failure that is about the request rather than the database: an unsupported domain.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # The shadow timeline reads signal_events, which 20260415090000 renames into place. That
        # migration was never applied to the live project, so a missing table is a 503 that names
        # it. Handing every exception to _table_fault is what makes that true for the APIError
        # postgREST actually raises, not just for the RuntimeError this used to catch.
        raise _table_fault("signal_events", exc)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/track-record (served via the service-role client, so the
# owner-only RLS on track_record never has to be opened to the anon key)
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/track-record", tags=["Track Record"])
async def get_track_record(supabase=Depends(get_supabase)):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = supabase.table("track_record").select("*").order("engine").execute()
    # One record per engine (v2 spec §4): an engine graded by the journal is served from its journal
    # scorecard, tagged `source: "journal"`; the rest keep their legacy rollup, tagged `source: "legacy"`.
    return merge_track_record(result.data or [], journal_scores(supabase))


# ════════════════════════════════════════════════════════════════════════════
# Prediction journal (v2 spec §3-§4, §11): precomputed scorecards and frozen forecasts.
# The frontend renders these numbers; it never recomputes them.
# ════════════════════════════════════════════════════════════════════════════
JOURNAL_PAGE_MAX = 500


@router.get("/api/journal", tags=["Journal"])
def get_journal(supabase=Depends(get_supabase)):
    """Every (forecaster, version) scorecard, ordered by forecaster, plus the precomputed headline.

    `standings` is the front page's "what we found": the best and worst forecaster, each with the
    interval its gap was measured on, and a lede assembled from those numbers. It is computed HERE
    rather than in the browser because comparing a gap against its standard error is an analytic
    judgement about whether a result is real, and the journal already owns that rule (migration
    20260428000017 exists precisely because a bare skill number reads as a result when it is noise).
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = _fetch_all(supabase, "journal_scores", lambda q: q.select("*"),
                          order=("forecaster", "forecaster_version"))
    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
        raise _table_fault("journal_scores", exc) from exc
    _annotate_retired(rows)
    # A missing or unapplied `journal_backtests` degrades standings to "not measured", the same rule
    # /api/journal/backtests follows: "no replay yet" is the true statement, and it is better than a
    # 500 that takes the front page down over a table the journal does not need to answer this.
    try:
        replays = _fetch_all(supabase, "journal_backtests", lambda q: q.select("*"),
                             order=("created_at", "id"))
    except Exception as exc:  # noqa: BLE001 - classified below
        if table_missing(exc, "journal_backtests"):
            replays = []
        else:
            raise _table_fault("journal_backtests", exc) from exc
    # Newest replay per (forecaster, version): ascending created_at, so the last row per pair is current.
    latest = {(r["forecaster"], r["forecaster_version"]): r for r in replays}
    rows_out = journal_standings(rows, list(latest.values()))
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "forecasters": rows,
        "headline": journal_headline(rows),
        "standings": {**rows_out, "verdict": journal_verdict_sentence(rows_out)},
        "retired_models": _retired_models(),
    }


def _annotate_retired(rows: list[dict]) -> None:
    """Label each scorecard row `retired` from the registry's RETIRED
    list (step 9: retired rows stay on the scoreboard, labeled, rather
    than silently reading as live models). Exact (forecaster, version)
    pairs, the same rows _retired_models counts. Fail-soft like it: if
    the registry won't load, rows keep no label at all -- an absent
    label is unknown, never a claim that nothing is retired."""
    try:
        from tradehub.journal.registry import RETIRED

        pairs = {(f.name, str(getattr(f, "version", "") or "")) for f in RETIRED}
    except Exception:  # noqa: BLE001
        log.exception("api: journal registry unreadable for retired labels")
        return
    for r in rows:
        r["retired"] = (r.get("forecaster"),
                        str(r.get("forecaster_version") or "")) in pairs


def _retired_models() -> int | None:
    """How many models the Nov 10 retirement stopped freezing (registry.RETIRED): real model rows
    only -- market (`kalshi_implied_*`) and baseline rows dropped, and a model's cautious, calibrated
    (`_cal`, `+cal`) and window (`+wNN`) copies counted once with it. Their records stay scored and
    public. None (unknown, never 0) if the registry won't load."""
    try:
        from tradehub.journal.registry import RETIRED

        models = set()
        for f in RETIRED:
            if f.name.startswith(("kalshi_implied_", "baseline_")):
                continue
            name = f.name.removesuffix("_cautious").removesuffix("_cal")
            version = re.sub(r"(\+w\d+|\+cal)+$", "", str(f.version))
            models.add((name, version))
        return len(models)
    except Exception:  # noqa: BLE001
        log.exception("api: journal registry unreadable")
        return None


@router.get("/api/journal/previews", tags=["Journal"])
def get_journal_previews(supabase=Depends(get_supabase)):
    """The next jobs and CPI releases as the models see them right now. Not locked, not scored."""
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = _fetch_all(supabase, "journal_previews", lambda q: q.select("*"), order=("close_at", "target"))
    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
        raise _table_fault("journal_previews", exc) from exc
    return {"as_of": datetime.now(timezone.utc).isoformat(), "previews": rows}


@router.get("/api/journal/feed", tags=["Journal"])
def get_journal_feed(forecaster: str, version: str, limit: int = 100, offset: int = 0,
                     supabase=Depends(get_supabase)):
    """Frozen forecasts for one forecaster (newest first) plus its calibration buckets.

    The `/api/kalshi-feed` shape, so downstream consumers read the journal the way the hub reads the
    predictors: frozen snapshots and calibration, never a recomputed number.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    if limit < 1 or limit > JOURNAL_PAGE_MAX or offset < 0:
        raise HTTPException(status_code=422, detail=f"limit must be 1..{JOURNAL_PAGE_MAX} and offset >= 0")
    try:
        rows = supabase.table("journal_forecasts").select("*") \
            .eq("forecaster", forecaster).eq("forecaster_version", version) \
            .order("id", desc=True).range(offset, offset + limit - 1).execute().data or []
        card = supabase.table("journal_scores").select("*") \
            .eq("forecaster", forecaster).eq("forecaster_version", version).limit(1).execute().data or []
    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
        raise _table_fault("journal_forecasts", exc) from exc
    score = card[0] if card else None
    return {
        "forecaster": forecaster,
        "forecaster_version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forecasts": [{k: r.get(k) for k in ("target", "probability", "market_prob", "frozen_at", "rebuilt",
                                             "source_hash")} for r in rows],
        "calibration": (score or {}).get("reliability", []),
        "gate_status": (score or {}).get("gate_status", DEFAULT_GATE_STATUS),
        "provisional": not bool((score or {}).get("calibration_ready")),
    }


@router.get("/api/journal/backtests", tags=["Journal"])
def get_journal_backtests(supabase=Depends(get_supabase)):
    """The latest walk-forward replay of each daily model: context, never counted toward a gate.

    A missing table (the migration is not applied yet) is an empty answer, the same rule the journal's
    other reads follow, because "no replay yet" is the true statement. The same is true one column in:
    `brier_diff`/`brier_diff_se` arrive with migration 017, which Kevin applies by hand, so a deployment
    can be serving this route for a while without them. The read asks for `*` and the response is built
    with `.get()`, which is what makes that degrade -- `*` is the only select shape PostgREST can answer
    without the column existing (naming it is a PGRST204 and the whole /journal page goes down over a
    missing error bar), and `.get()` turns the absent key into null, so the row still reads.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        # `created_at` first, `id` only to break a tie: `created_at` is the RUN'S OWN time, while `id`
        # is insertion order. Two runs that overlap can finish out of order, so the larger id can belong
        # to the older run -- and since the page prints `replayed <created_at>`, publishing that as the
        # latest would show stale numbers with a stale date as if both were current.
        rows = _fetch_all(supabase, "journal_backtests", lambda q: q.select("*"),
                          order=("created_at", "id"))
    except Exception as exc:  # noqa: BLE001 - classified below
        if table_missing(exc, "journal_backtests"):
            rows = []
        else:
            raise _table_fault("journal_backtests", exc) from exc
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:  # ascending created_at, so the last row per pair is the newest run
        latest[(row["forecaster"], row["forecaster_version"])] = row
    # The interval rides along with the Brier pair it belongs to, so a reader sees "we are better or
    # worse than the usual rate by X ± SE" rather than a skill with no error bar. It is deliberately not
    # an interval on `bss`: bss is a ratio, SE(bss) is not this number, and approximating one would be
    # publishing a guess as a measurement.
    keep = ("forecaster", "forecaster_version", "date_from", "date_to", "n", "brier", "brier_baseline",
            "brier_diff", "brier_diff_se", "bss", "by_year", "created_at")
    return {"as_of": datetime.now(timezone.utc).isoformat(), "counted": False,
            "backtests": [{k: r.get(k) for k in keep} for r in latest.values()]}


@router.get("/api/journal/series", tags=["Journal"])
def get_journal_series(supabase=Depends(get_supabase)):
    """Per-forecaster skill series over time: one entry per (forecaster, version) with a `points` list, one point per
    replay row (gap = brier_diff, se = its standard error), oldest first.

    Mirrors `/api/journal/backtests`: a missing `journal_backtests` table degrades to an empty
    answer (200), not a 500, and `brier_diff`/`brier_diff_se` arrive with migration 017 so they are
    read with `.get()` and stay null rather than 0.0 when the column does not exist yet. Points are
    ordered by `date_from` ascending.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = _fetch_all(supabase, "journal_backtests", lambda q: q.select("*"),
                          order=("created_at", "id"))
    except Exception as exc:  # noqa: BLE001 - classified below
        if table_missing(exc, "journal_backtests"):
            rows = []
        else:
            raise _table_fault("journal_backtests", exc) from exc
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r.get("forecaster"), r.get("forecaster_version"))
        grouped.setdefault(key, []).append({"date": r.get("date_from"), "gap": r.get("brier_diff"),
                                            "se": r.get("brier_diff_se"), "n": r.get("n")})
    series = [{"forecaster": f, "version": v, "points": sorted(pts, key=lambda p: str(p["date"]))}
              for (f, v), pts in sorted(grouped.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))]
    return {"series": series}


# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/journal/weather-panel", tags=["Journal"])
def get_weather_panel(supabase=Depends(get_supabase)):
    """Latest settled day's weather/ERCOT contracts: our probability vs Kalshi's, with outcome.

    Read-only: no new forecasting, no migration. Reads journal_forecasts + journal_settlements for
    weather_* and ercot_peak forecasters, groups by target, and returns only the latest settled day's
    contracts. Each contract carries our probability, Kalshi's implied probability, and the outcome.
    Missing figures are null, never 0.0.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    # Weather/ERCOT forecaster families - filter in the query so we don't read the whole table
    weather_forecasters = ["weather_high", "weather_low", "weather_rain", "ercot_peak"]
    try:
        forecasts = _fetch_all(supabase, "journal_forecasts",
                               lambda q: q.select("*").in_("forecaster", weather_forecasters),
                               order=("frozen_at",))
    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
        if table_missing(exc, "journal_forecasts"):
            forecasts = []
        else:
            raise _table_fault("journal_forecasts", exc) from exc
    try:
        settlements = _fetch_all(supabase, "journal_settlements", lambda q: q.select("*"),
                                 order=("settled_at",))
    except Exception as exc:  # noqa: BLE001 - classified by _table_fault
        if table_missing(exc, "journal_settlements"):
            settlements = []
        else:
            raise _table_fault("journal_settlements", exc) from exc

    # Group forecasts by target
    by_target: dict[str, dict[str, Any]] = {}
    for row in forecasts:
        target = row.get("target", "")
        if not target:
            continue
        if target not in by_target:
            by_target[target] = {"target": target, "forecaster": row.get("forecaster")}
        # A missing figure is None, never 0.0, and the contract is still listed: dropping it
        # would hide a contract the market settled.
        prob = row.get("probability")
        by_target[target]["our_prob"] = float(prob) if prob is not None else None
        by_target[target]["market_prob"] = row.get("market_prob")

    # Join settlements
    outcome_by_target: dict[str, int] = {}
    for s in settlements:
        outcome_by_target[s["target"]] = int(s["outcome"])

    settled_contracts: list[dict[str, Any]] = []
    for target, row in by_target.items():
        outcome = outcome_by_target.get(target)
        if outcome is None:
            continue  # only settled contracts
        row["outcome"] = outcome
        settled_contracts.append(row)

    if not settled_contracts:
        return {"as_of": datetime.now(timezone.utc).isoformat(), "contracts": []}

    # Find the latest settled day: group by the operating day parsed from the target
    from collections import defaultdict
    by_date: dict = defaultdict(list)
    for c in settled_contracts:
        day = _target_day(c["target"])
        if day is not None:
            by_date[day].append(c)

    if not by_date:
        return {"as_of": datetime.now(timezone.utc).isoformat(), "contracts": []}

    latest_date = max(by_date)                # a real date, so the latest is chronological
    latest_contracts = by_date[latest_date]

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "settled_date": latest_date.isoformat(),
        "contracts": latest_contracts,
    }


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/scoreboard — every engine's Brier beside the market's, and its
# distance to its own gate. Approved 2026-09-27 (spec section 9, approval 4).
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route added after it
# is shadowed and this endpoint would answer with the app shell.
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/scoreboard", tags=["Scoreboard"])
def get_scoreboard(supabase=Depends(get_supabase)):
    """Should I trust this engine? One row per engine and mode, from the current run.

    The route reads and hands over. It decides nothing.

    - The reduction is `current_runs` (`tradehub/scoreboard.py`), which is pure, so every rule
      that decides what appears is testable without a database. In particular the rule this
      endpoint exists to protect: a run whose `engine_version` carries a decision lead
      (`gas-v1-lead12h`) is an EXPERIMENT, and is excluded from the page rather than footnoted.
      The experiment stays in `backtest_runs` and stays reproducible from the CLI; presenting it
      as the engine's record would make the page wrong in the direction that flatters the engine.
    - The headline and the counts behind it are `market_comparison`, from the same module. The
      "is this engine ahead" threshold lives there, because a second copy of it here is how the
      page and the API start disagreeing with nothing downstream able to tell which one drifted.
    - Each row's `market_verdict` is `market_verdict`, also from that module, so the page renders
      a word rather than comparing ratios in TypeScript.
    - `MIN_SETTLED` is not named in this file. It rides on each row's `settled_distance` as the
      reviewer's floor, separately from the bar the gate itself stated, and the row says which
      one the verdict was made against.
    - `catalogue` is `engine_catalogue` (`tradehub/engine_catalogue.py`), also pure. It is the
      answer to "which engines does this product have, and what does each one claim to predict",
      and it joins that to the rows above rather than replacing them: an engine with no backtest
      run is in the response with `measured: false` rather than absent, because an absent engine
      reads as "this engine has nothing to show" and that is a claim nobody made. Its counts are
      here for the same reason the headline's are -- `engines_not_measured` is a subtraction on a
      set, and a page that does it at render time does it in a component.

    The one lookup this endpoint makes, and the one it does not:

    - `promotion_status` is `latest_gate_statuses` (`tradehub/gate_status.py`) -- the SAME
      function the scan uses, keyed on `(engine, engine_version)`, requiring the latest backtest
      for that exact version AND a `track_record` row to both say PROMOTED, and failing closed
      otherwise. `row["gate_status"]` is NOT that: it is what `check_promotion_gate` returned when
      the run was recorded (`tradehub/track_record.py:126`), which never consults `track_record`
      at all. So a run can carry `gate_status: "PROMOTED"` while the engine is not promoted, and
      rendering that under the word PROMOTED reads as a promotion to a human. Both travel, both
      labelled. The alternative -- a private reimplementation here -- is what that function's
      docstring exists to prevent, and the extra reads are the price of there being one answer
      about whether an edge is tradable rather than two.
    - The verdict is per `(engine, engine_version)` while a row is per `(engine, mode)`, so both
      rows of one engine carry the same verdict. That is the gate's own key, not a convenience.
    - **A failed lookup fails closed and is announced.** `SHADOW` is the safe direction -- it
      cannot make a non-tradable edge look tradable -- but a column of SHADOW badges that were
      never verified is still a claim, so `promotion_lookup_failed` says so and the page says it
      too. Same shape as the read failure below, applied to a read that is not the whole story.

    Two decisions in the read itself:

    - **The read is paged, with no cap.** PostgREST caps one response at 1000 rows, so a single
      `.execute()` silently truncates; and a cap is worse, because the cap and the reduction pull
      in opposite directions. `backtest_runs` grows by one row per recorded CLI run, so the 200
      newest are overwhelmingly gas: a monthly-cadence engine whose only recent run falls outside
      that window is not rendered slightly stale, it is ABSENT -- and an absent engine reads as
      "this engine has no settled contracts", which is a claim about the engine. The table is one
      row per recorded run rather than a growing event log, so paging it whole is cheap, and
      `runs_read` travels in the response so a truncation is visible if one is ever added.
    - **A read failure is a 503, never an empty scoreboard.** `_fetch_all` raises on the first
      failing page, including a later one, so a partial read cannot be mistaken for a complete
      one: either the whole ledger reduces or the page says it could not be read. The two are
      distinguishable in the body as well as in the status -- a failure carries `detail` and no
      `rows` at all, and a genuinely empty ledger returns 200 with `rows: []` and its own
      headline. One sentinel, one meaning.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        runs = _fetch_all(supabase, "backtest_runs", lambda q: q.select("*"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=_missing_table_message("backtest_runs", e))
    rows = current_runs(runs)

    # The shared lookup, asked once for the pairs this board actually has. The version is part of
    # the key and is dropped from neither side: a version that is not promoted must not inherit
    # another version's promotion.
    pairs = {(r["engine"], r["engine_version"]) for r in rows if r["engine"] and r["engine_version"]}
    promotion: dict[tuple[str, str], str] = {}
    promotion_lookup_failed = False
    if pairs:
        try:
            promotion = latest_gate_statuses(supabase, pairs)
        except Exception:
            # Failing closed, and saying so. Same handling as /api/jobs-scorecard below, for the
            # same reason: the rows are readable, so a failure here must not take the page down,
            # and must not be mistaken for a verdict.
            log.exception("api: scoreboard promotion-gate lookup failed")
            promotion_lookup_failed = True
    for row in rows:
        row["promotion_status"] = promotion.get(
            (row["engine"], row["engine_version"]), DEFAULT_GATE_STATUS
        )

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "runs_read": len(runs),
        "rows": rows,
        # True when the promotion verdict below could not be read. Every row then reads SHADOW,
        # which is the fail-closed default and NOT a measurement.
        "promotion_lookup_failed": promotion_lookup_failed,
        # Distinct engines, because `rows_*` below counts (engine, mode) pairs and one name under
        # two labels is what made a single number unable to say what it was counting.
        "engines": len({row["engine"] for row in rows}),
        **market_comparison(rows),
        # Built LAST, because each entry carries its rows whole and those rows have to carry
        # `promotion_status` -- an entry built before the loop above would ship a gate the board
        # does not show, which is a right number under the wrong label on a page about labels.
        "catalogue": engine_catalogue(rows),
    }
