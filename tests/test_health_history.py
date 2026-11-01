"""The Health heatmap grid (phase-3 §2): statuses only on evidence -- a gap
inside an active stretch is "silent"; a window edge or a quiet stretch makes
no claim; family cells carry their frozen counts; flags are annotations."""
from __future__ import annotations

from tradehub.health import build_history

DAYS = [f"2026-10-{d:02d}" for d in range(19, 32)] + ["2026-11-01"]  # 14 days


def _build(**over):
    args = dict(completed_runs=[], journal_days=set(), frozen_rows=[], diag_rows=[],
                cadences={"weather": "daily", "cpi_nowcast": "monthly"}, days_list=DAYS)
    args.update(over)
    return build_history(**args)


def _cells(row):
    return {c["date"]: c["status"] for c in row}


def test_timer_silent_only_for_a_gap_inside_an_active_stretch():
    runs = [("scan", d) for d in DAYS if d != "2026-10-25"]
    cells = _cells(_build(completed_runs=runs)["timers"]["scan"])
    assert cells["2026-10-25"] == "silent"          # neighbours ran, this day did not
    assert cells["2026-10-24"] == "ok"
    # A dead stretch at the window's start makes no claim either way.
    runs2 = [("scan", d) for d in DAYS[5:]]
    cells2 = _cells(_build(completed_runs=runs2)["timers"]["scan"])
    assert cells2["2026-10-20"] == "none" and cells2["2026-10-24"] == "ok"


def test_family_cells_carry_counts_and_daily_silence_only():
    frozen = [("weather", "2026-10-24")] * 12 + [("weather", "2026-10-26")] * 9
    hist = _build(frozen_rows=frozen)
    weather = {c["date"]: c for c in hist["families"]["weather"]}
    assert weather["2026-10-24"] == {"date": "2026-10-24", "status": "ok", "count": 12}
    assert weather["2026-10-25"]["status"] == "silent"   # daily family, gap in a stretch
    cpi = {c["date"]: c for c in hist["families"]["cpi_nowcast"]}
    assert all(c["status"] == "none" for c in cpi.values())  # monthly: no daily claim


def test_diagnostics_row_marks_flag_days_as_annotations():
    hist = _build(diag_rows=[("2026-10-28", ["labor_nowcast: pay_rev_3m: mostly_zero"])])
    row = {c["date"]: c for c in hist["diagnostics"]}
    assert row["2026-10-28"]["status"] == "flags"
    assert row["2026-10-28"]["flags"] == ["labor_nowcast: pay_rev_3m: mostly_zero"]
    assert row["2026-10-27"]["status"] == "none"
