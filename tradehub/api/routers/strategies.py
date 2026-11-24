"""Strategies page: the trials that are not 15-minute models (Kevin,
2026-11-24). One read-only GET that assembles one row per preregistered
shadow from its existing evaluator -- counts, a headline score and a
status only; no tickers, no positions, no order path. Each row is
fail-soft on its own: an unreadable store reads as "no public read yet".
The 15-minute shadows are not here; the page reads them off the
fifteen-rule board it already fetches."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from tradehub.api.dependencies import get_supabase

router = APIRouter()


def _row(id_, name, tests, needed, unit):
    return {"id": id_, "name": name, "tests": tests, "n": None, "needed": needed,
            "unit": unit, "score": None, "score_label": None,
            "status": "no_read", "note": None}


def _oil_v7(supa, row):
    from tradehub.journal.forecasters.oil_v7 import RV_VERSION

    data = (supa.table("journal_scores").select("n_settled")
            .eq("forecaster", "oil_wti_hourly").eq("forecaster_version", RV_VERSION)
            .execute().data) or []
    row["n"] = int(data[0].get("n_settled") or 0) if data else 0
    row["status"] = "recording"
    row["note"] = "Verdict on the paired Brier vs v4 at 300 settled or Jan 15, 2027"


def _leaps(supa, row):
    from tradehub import leaps_shadow as ls

    s = ls.trial_summary(ls._rows(supa), now=datetime.now(timezone.utc),
                         stored=ls._stored_verdicts(supa))
    gate = s["gate"]
    row["n"], row["needed"] = gate["pairs"], gate["needed"]
    row["status"] = {"killed": "killed", "pass": "eligible", "complete": "eligible"}.get(gate["state"], "recording")
    if s.get("mean_carry_drag_pct") is not None:
        row["score"], row["score_label"] = round(s["mean_carry_drag_pct"], 2), "carry drag %/yr"
    row["note"] = gate.get("reason")


def _band(supa, row):
    from tradehub.valuation import band_crossing as bc

    rows = (supa.table(bc.CROSSINGS).select("action, score_20").execute().data) or []
    f = bc.falsifier_summary(rows)
    row["n"], row["needed"] = f["graded"], f["gate"]
    row["score"], row["score_label"] = f["mean_score"], "mean +20d score"
    row["status"] = {"survived": "eligible", "shelved": "killed"}.get(f["status"], "recording")


def _watcher(supa, row):
    from tradehub import level_watcher as lw

    fams = (supa.table(lw.FAMILY_STATE).select("*").execute().data) or []
    row["n"] = max((int(f.get("graded_count") or 0) for f in fams), default=0)
    row["needed"] = lw.DEMOTION_GATE
    demoted = sum(1 for f in fams if f.get("demoted_at"))
    row["status"] = "killed" if fams and demoted == len(fams) else "recording"
    row["note"] = f"{len(fams)} rule famil{'y' if len(fams) == 1 else 'ies'}, {demoted} demoted; bar is per family"


def _valuation(supa, row):
    from tradehub.valuation import grading, verdict_store

    a = grading.authority_summary(verdict_store.all_grades(supa))
    row["n"], row["needed"] = a["relative_passes"], a["gate"]
    row["score"], row["score_label"] = a["pass_rate"], "pass rate"
    row["status"] = "eligible" if a["status"] == "authority_gate_met" else "recording"
    row["note"] = f"{a['graded_verdicts']} verdicts graded"


TRIALS = [
    ("oil-hourly-v7", "Hourly oil v7 (realised-vol spread)",
     "Does a 1-minute realised-vol spread forecast WTI hourly better than v4?", 300, "settled pairs", _oil_v7),
    ("leaps", "LEAPS shadow",
     "Do deep LEAPS deliver a share position's gains for less cash?", 4, "pairs", _leaps),
    ("band-crossing", "Band-crossing grader",
     "Do buys at the valuation band edges beat the market over 20 days?", 20, "graded entries", _band),
    ("level-watcher", "Level watcher",
     "Do price-level alerts call the next 5 days' move?", 20, "graded triggers", _watcher),
    ("valuation-debates", "Valuation debates",
     "Do the debate verdicts beat their peers over 20–60 days?", 40, "passing verdicts", _valuation),
]


@router.get("/api/strategies/trials", tags=["Strategies"])
def strategies_trials(supabase=Depends(get_supabase)) -> dict:
    out = []
    for id_, name, tests, needed, unit, fill in TRIALS:
        row = _row(id_, name, tests, needed, unit)
        if supabase is not None:
            try:
                fill(supabase, row)
            except Exception:  # noqa: BLE001 -- one bad store never hides the others
                row.update(_row(id_, name, tests, needed, unit))
        out.append(row)
    return {"trials": out}
