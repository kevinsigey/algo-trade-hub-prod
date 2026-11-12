"""LEAPS gate fix (Kevin's call, 2026-11-11: keep the 80% bar constant and
change the delivery definition to match it).

Three changes to the Spec F gate:
1. Delivery is POOLED dollars: sum(leaps_pnl) / sum(share_pnl) over the
   cohort. The old mean of per-pair return ratios read ~3.0 for a
   perfectly tracking LEAPS (premium is a fraction of the share cash),
   so the 80% bar could only fire on near-total failure.
2. The cohort is judged only once every pair in it has at least 90 days
   of marks or is closed -- the old read annualized carry drag off a
   1-day floor and could fire the day the 4th pair opened.
3. The first verdict is STORED (leaps_trial_verdicts) by the nightly
   grade and never recomputed; the panel serves the stored verdict.
Fixtures only — no network."""
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_leaps_shadow import _gate_pair, _open_pair
from tests.workshop_fake import DB
from tradehub import leaps_shadow as leaps

NOW = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
OPENED = "2026-11-12T05:00:00+00:00"


def _marked(days, **over):
    """An open pair whose latest mark is `days` after it opened."""
    marked = (NOW + timedelta(days=days)).isoformat()
    pair = _open_pair(opened_at=OPENED, marked_at=marked, **over)
    return pair


# -- pooled delivery ----------------------------------------------------------

def test_pooled_delivery_weights_pairs_by_dollars_not_by_count():
    # Three small pairs deliver 0.99 each; one large pair delivers 0.70.
    # A mean of per-pair ratios reads (0.99*3 + 0.70)/4 = 0.92 (pass);
    # pooled dollars read 7297/10300 = 0.71 (kill). The gate must pool.
    rows = [_gate_pair(i, leaps_pnl=99.0, share_pnl=100.0) for i in range(1, 4)]
    rows.append(_gate_pair(4, leaps_pnl=7000.0, share_pnl=10000.0))
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["state"] == "killed" and "delivery" in s["gate"]["reason"]
    assert s["gate"]["mean_delta_delivered"] == pytest.approx(7297 / 10300)


def test_delivery_is_undefined_when_the_share_line_made_nothing():
    # sum(share_pnl) <= 0: a ratio would reward or punish the LEAPS line
    # for the share line's loss. The metric is absent, so the gate reads
    # insufficient_data -- never a pass, never a delivery kill.
    rows = [_gate_pair(i, leaps_pnl=-50.0, share_pnl=-100.0) for i in range(1, 5)]
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert s["gate"]["judged"] and s["gate"]["state"] == "insufficient_data"
    assert s["gate"]["mean_delta_delivered"] is None


def test_pair_delivery_is_none_when_the_share_line_lost_money():
    pair = _open_pair()
    patch = leaps.pair_marks(pair, leaps_mid=36.0, share_price=90.0,
                             marked_at=NOW + timedelta(days=182))
    assert patch["share_pnl"] < 0 and patch["leaps_pnl"] > 0
    assert patch["delta_delivered"] is None


# -- maturity: judged only at 90 days of marks or closed -----------------------

def test_cohort_is_not_judged_on_thin_marks():
    rows = [_marked(30, id=i, crossing_id=i, carry_drag_pct=9.0,
                    leaps_pnl=100.0, share_pnl=1000.0) for i in range(1, 5)]
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=40))
    assert not s["gate"]["judged"] and s["gate"]["state"] == "open"


def test_cohort_is_judged_once_marks_reach_90_days():
    rows = [_marked(95, id=i, crossing_id=i, carry_drag_pct=9.0,
                    leaps_pnl=100.0, share_pnl=1000.0) for i in range(1, 5)]
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=100))
    assert s["gate"]["judged"] and s["gate"]["state"] == "killed"


def test_one_immature_pair_holds_the_whole_cohort():
    rows = [_gate_pair(i) for i in range(1, 4)]            # closed = mature
    rows.append(_marked(10, id=4, crossing_id=4, carry_drag_pct=2.0,
                        leaps_pnl=900.0, share_pnl=1000.0))
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=20))
    assert not s["gate"]["judged"]


def test_twelve_month_cutoff_judges_a_short_cohort_once_mature():
    rows = [_gate_pair(i) for i in range(1, 3)]            # only 2 pairs ever
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=366))
    assert s["gate"]["judged"] and s["gate"]["state"] == "pass"
    assert s["gate"]["cohort_pairs"] == 2


# -- stored first verdict -------------------------------------------------------

_STORED_PASS = {"cohort": "first4", "state": "pass", "reason": None,
                "mean_carry_drag_pct": 2.0, "pooled_delta_delivered": 0.9,
                "cohort_pairs": 4, "judged_at": "2027-03-01T04:41:00+00:00"}


def test_a_stored_verdict_is_served_not_recomputed():
    rows = [_gate_pair(i, drag=9.0, leaps_pnl=100.0) for i in range(1, 5)]
    live = leaps.trial_summary(rows, now=NOW + timedelta(days=60))
    assert live["gate"]["state"] == "killed"               # the live read moved
    s = leaps.trial_summary(rows, now=NOW + timedelta(days=60),
                            stored={"first4": _STORED_PASS})
    assert s["gate"]["state"] == "pass" and s["gate"]["stored"] is True
    assert s["gate"]["judged_at"] == _STORED_PASS["judged_at"]


def test_persist_stores_the_first_verdict_and_never_a_second():
    db = DB()
    db.db["leaps_shadow_pairs"] = [_gate_pair(i) for i in range(1, 5)]
    out = leaps.persist_gate_verdicts(db, now=NOW + timedelta(days=60))
    assert out["stored"] == ["first4"]
    (row,) = db.db["leaps_trial_verdicts"]
    assert row["state"] == "pass" and row["cohort"] == "first4"
    assert row["pooled_delta_delivered"] == pytest.approx(0.9)

    for r in db.db["leaps_shadow_pairs"]:                  # the marks sink
        r["leaps_pnl"] = 100.0
    out = leaps.persist_gate_verdicts(db, now=NOW + timedelta(days=70))
    assert out["stored"] == []                             # nothing overwritten
    (row,) = db.db["leaps_trial_verdicts"]
    assert row["state"] == "pass"


def test_insufficient_data_is_not_stored_and_a_later_pass_is():
    # Night one: the share line lost money in total, so pooled delivery
    # is undefined and the gate reads insufficient_data. That read must
    # NOT be stored -- stored verdicts are never recomputed, so freezing
    # an insufficient_data would freeze the trial forever on no evidence.
    db = DB()
    db.db["leaps_shadow_pairs"] = [
        _gate_pair(i, leaps_pnl=-50.0, share_pnl=-100.0) for i in range(1, 5)]
    out = leaps.persist_gate_verdicts(db, now=NOW + timedelta(days=60))
    assert out["stored"] == []
    assert db.db.get("leaps_trial_verdicts", []) == []

    # A later night, with both metrics marked, judges a pass -- and
    # that pass is the verdict that gets stored.
    for r in db.db["leaps_shadow_pairs"]:
        r["leaps_pnl"] = 900.0
        r["share_pnl"] = 1000.0
    out = leaps.persist_gate_verdicts(db, now=NOW + timedelta(days=70))
    assert out["stored"] == ["first4"]
    (row,) = db.db["leaps_trial_verdicts"]
    assert row["state"] == "pass" and row["cohort"] == "first4"


def test_panel_serves_the_stored_verdict():
    db = DB()
    db.db["leaps_shadow_pairs"] = [_gate_pair(i, drag=9.0, leaps_pnl=100.0)
                                    for i in range(1, 5)]
    db.db["leaps_trial_verdicts"] = [dict(_STORED_PASS, idea_id=81)]
    panel = leaps.panel(db, {"id": 81})
    assert panel["summary"]["gate"]["state"] == "pass"
    assert panel["summary"]["gate"]["stored"] is True
