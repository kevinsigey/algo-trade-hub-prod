"""Batch 2 candidate generation: debate candidates come from the RECORDED
screen runs + membership and the latest COMPLETED snapshot's band history
— never from ad-hoc builder runs. Classes: conjunctions (screen survivor x
directional band zone x recent print classification) first, strong zones,
recent entrants, then plain directional zones. A name that cannot debate
(not in the snapshot, unbanded, stale) is named in `excluded` with its
reason — never silently dropped, never proxied (scar tissue #8/#9)."""
from datetime import datetime, timezone

from tradehub.valuation import candidates
from tests.test_valuation_verdicts import FakeClient, _DS, _chat, _sheet_row

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _seeded() -> FakeClient:
    c = FakeClient()
    c.tables["valuation_snapshots"] = [{
        "id": 3, "computed_at": "2026-11-09T22:46:16+00:00",
        "completed_at": "2026-11-09T22:47:00+00:00",
        "sheet_count": 5, "banded_count": 3, "source": "valuation_run"}]
    sheets = [
        _sheet_row(ticker="AMGN", snapshot_id=3),
        _sheet_row(ticker="CVS", snapshot_id=3, price=85.17,
                   bands={"bear": 82.11, "base": 91.23, "bull": 91.23},
                   baseline_verdict="buy_zone"),
        _sheet_row(ticker="GILD", snapshot_id=3, price=95.0,
                   bands={"bear": 80.0, "base": 90.0, "bull": 100.0},
                   baseline_verdict="buy_zone_strong"),
        _sheet_row(ticker="NEUT", snapshot_id=3, price=50.0,
                   bands={"bear": 40.0, "base": 48.0, "bull": 55.0},
                   baseline_verdict="neutral"),
        _sheet_row(ticker="XYZ", snapshot_id=3, status="no_full_year_guide",
                   bands=None, baseline_verdict="no_bands"),
    ]
    for i, s in enumerate(sheets, start=1):
        s["id"] = 100 + i
    c.tables["valuation_fact_sheets"] = sheets
    hist = []
    for t, zone, bear, base, bull in (
            ("AMGN", "short_zone_strong", 272.18, 310.17, 317.92),
            ("CVS", "buy_zone", 82.11, 91.23, 91.23),
            ("GILD", "buy_zone_strong", 80.0, 90.0, 100.0),
            ("NEUT", "neutral", 40.0, 48.0, 55.0),
            ("XYZ", None, None, None, None)):
        hist.append({"snapshot_id": 3, "ticker": t, "zone": zone,
                     "band_basis": "eps", "guide_metric": "eps_adjusted",
                     "guide_low": 1.0, "guide_high": 2.0, "direction": "held",
                     "peer_multiple": 12.0, "bear": bear, "base": base,
                     "bull": bull, "price": 100.0,
                     "computed_at": "2026-11-09T22:46:16+00:00"})
    c.tables["valuation_band_history"] = hist
    c.tables["screens"] = [{
        "id": 6, "name": "Buffett quality (classic)",
        "spec": {"membership_diff": True},
        "last_run": {"survivors": ["GILD", "MSFT"],
                     "footer": {"run_at": "2026-11-10T05:04:00+00:00"}},
        "membership": {"tracked_since": "2026-11-10", "as_of": "2026-11-10",
                       "members": {"GILD": "2026-11-10",
                                   "MSFT": "2026-11-10"}},
        "membership_events": [
            {"ticker": "GILD", "kind": "entered", "date": "2026-11-09"}],
    }]
    c.tables["forward_file_classifications"] = [
        {"ticker": "GILD", "classification": "intact",
         "as_of": "2026-11-08"}]
    return c


def test_generation_classes_counts_and_priorities():
    c = _seeded()
    out = candidates.generate_candidates(c, now=NOW)
    assert out["snapshot"]["id"] == 3
    assert out["counts"] == {"entrants": 1, "zone_names": 3,
                             "conjunctions": 1, "held_conjunctions": 0,
                             "total": 3, "excluded": 3}
    by_ticker = {r["ticker"]: r for r in out["candidates"]}
    assert set(by_ticker) == {"AMGN", "CVS", "GILD"}
    # conjunction outranks a strong zone, which outranks a plain zone
    assert by_ticker["GILD"]["candidate_class"] == "conjunction"
    assert by_ticker["AMGN"]["candidate_class"] == "zone"
    assert by_ticker["CVS"]["candidate_class"] == "zone"
    assert (by_ticker["GILD"]["priority"] < by_ticker["AMGN"]["priority"]
            < by_ticker["CVS"]["priority"])
    assert by_ticker["GILD"]["sources"]["zone"] == "buy_zone_strong"
    assert by_ticker["GILD"]["sources"]["print_classification"] == {
        "classification": "intact", "as_of": "2026-11-08"}
    assert by_ticker["GILD"]["sources"]["entrants"][0]["screen_id"] == 6
    assert by_ticker["AMGN"]["sources"]["print_classification"] is None
    # persisted, stamped with the exhibit snapshot id (scar #9)
    rows = c.tables["debate_candidates"]
    assert len(rows) == 3
    assert all(r["snapshot_id"] == 3 and r["state"] == "pending"
               for r in rows)


def test_generation_is_idempotent_per_snapshot():
    c = _seeded()
    candidates.generate_candidates(c, now=NOW)
    out = candidates.generate_candidates(c, now=NOW)
    assert out["inserted"] == 0
    assert len(c.tables["debate_candidates"]) == 3


def test_unbanded_and_unsheeted_names_are_named_exclusions():
    c = _seeded()
    out = candidates.generate_candidates(c, now=NOW)
    reasons = {e["ticker"]: e["reason"] for e in out["excluded"]}
    # MSFT is a recorded screen member with no fact sheet in the snapshot;
    # XYZ has a sheet but no bands. Both named, neither debated.
    assert "MSFT" in reasons and "no fact sheet" in reasons["MSFT"]
    assert "XYZ" in reasons and "no bands" in reasons["XYZ"]


def test_neutral_zone_is_not_a_candidate():
    c = _seeded()
    out = candidates.generate_candidates(c, now=NOW)
    assert "NEUT" not in {r["ticker"] for r in out["candidates"]}


def test_no_completed_snapshot_generates_nothing():
    c = FakeClient()
    out = candidates.generate_candidates(c, now=NOW)
    assert out["snapshot"] is None and out["candidates"] == []


def test_old_entrant_event_is_membership_not_entrance():
    c = _seeded()
    c.tables["screens"][0]["membership_events"] = [
        {"ticker": "GILD", "kind": "entered", "date": "2026-08-01"}]
    out = candidates.generate_candidates(c, now=NOW)
    assert out["counts"]["entrants"] == 0
    gild = next(r for r in out["candidates"] if r["ticker"] == "GILD")
    # The conjunction is survivor x zone x recent print (the charter's
    # definition) — GILD still holds all three, so it stays a conjunction;
    # the stale entrance simply contributes no entrant context.
    assert gild["candidate_class"] == "conjunction"
    assert gild["sources"]["memberships"]
    assert gild["sources"]["entrants"] == []


def test_drain_renders_candidate_with_context_and_stamps():
    c = _seeded()
    candidates.generate_candidates(c, now=NOW)
    seen_users = []

    def chat(system, user, *, schema=None):
        seen_users.append(user)
        if schema is None:
            return _chat(system, user, schema=schema)
        # the structurer packet must price its choices off THIS name's
        # sheet (the shared _chat fixture is priced for AMGN) — read the
        # bands and price out of the exhibit text, like the model must
        import re

        bands = re.search(r"Bear ([\d,.]+) / Base ([\d,.]+) / Bull ([\d,.]+)",
                          user)
        price = re.search(r"price ([\d,.]+) as of", user)
        f = lambda s: float(s.replace(",", ""))
        bear, base = f(bands.group(1)), f(bands.group(2))
        px = f(price.group(1))
        return {
            "choices": [
                {"choice_id": "act_at_band_low", "label": "low", "price": bear},
                {"choice_id": "act_at_band_mid", "label": "mid", "price": base},
                {"choice_id": "watch", "label": "Watch", "price": px},
                {"choice_id": "pass", "label": "Pass", "price": px}],
            "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                               "direction_momentum": 0.15,
                               "options_expression": 0.1,
                               "falsifier_proximity": 0.2},
            "digest": "digest",
            "proposer_pick": {"choice_id": "watch", "direction": "none",
                              "probability": 0.5},
            "rationale": "context noted",
        }, "qwen-fake"

    results = candidates.run_candidate_debates(c, _DS(), chat=chat, now=NOW)
    rendered = {r["ticker"]: r for r in results if r["status"] == "rendered"}
    assert set(rendered) == {"GILD", "AMGN", "CVS"}
    rows = {r["ticker"]: r for r in c.tables["valuation_verdicts"]
            if r["status"] == "rendered"}
    gild = rows["GILD"]
    assert gild["trigger"] == "conjunction"
    assert gild["snapshot_id"] == 3
    assert gild["candidate_sources"]["print_classification"]["classification"] \
        == "intact"
    assert gild["candidate_sources"]["memberships"][0]["screen_id"] == 6
    assert rows["AMGN"]["trigger"] == "band_zone"
    # the recorded context rides into the debate as context (Exhibit A is
    # still the fact sheet; validation is untouched by it)
    assert any("Recorded context" in u and "Buffett quality" in u
               for u in seen_users)
    states = {r["ticker"]: r["state"] for r in c.tables["debate_candidates"]}
    assert states == {"GILD": "rendered", "AMGN": "rendered",
                      "CVS": "rendered"}


def test_drain_llm_down_leaves_candidates_pending_and_stores_nothing():
    from tradehub.valuation import llm as val_llm

    c = _seeded()
    candidates.generate_candidates(c, now=NOW)

    def down(system, user, *, schema=None):
        raise val_llm.LLMUnavailable("error", "both free legs down")

    results = candidates.run_candidate_debates(c, _DS(), chat=down, now=NOW)
    assert results and all(r["status"] == "llm_unavailable" for r in results)
    assert not c.tables.get("valuation_verdicts")
    assert all(r["state"] == "pending" for r in c.tables["debate_candidates"])


# ── held-thesis overlap: a ranking signal for conjunctions (thesis-chat
# Round 3 input) — recorded context only, generation still reads recorded
# screen runs + membership; held positions come through the hub's existing
# book reads (positions_fn, injected here).

def _positions(book):
    return {"GILD": 25.0} if book == "big" else {}


def test_held_conjunction_outranks_and_carries_context():
    c = _seeded()
    # CVS becomes a second conjunction: recorded survivor + recent print.
    c.tables["screens"][0]["last_run"]["survivors"].append("CVS")
    c.tables["screens"][0]["membership"]["members"]["CVS"] = "2026-11-10"
    c.tables["forward_file_classifications"].append(
        {"ticker": "CVS", "classification": "improved",
         "as_of": "2026-11-09"})
    out = candidates.generate_candidates(c, now=NOW, positions_fn=_positions)
    assert out["held_positions_unavailable"] is False
    assert out["counts"]["held_conjunctions"] == 1
    gild = next(r for r in out["candidates"] if r["ticker"] == "GILD")
    cvs = next(r for r in out["candidates"] if r["ticker"] == "CVS")
    assert gild["candidate_class"] == cvs["candidate_class"] == "conjunction"
    assert gild["priority"] < cvs["priority"]  # the held name drains first
    assert out["candidates"][0]["ticker"] == "GILD"
    assert gild["sources"]["held"]["books"] == ["big"]
    assert "held" not in cvs["sources"]


def test_positions_unavailable_falls_back_to_class_order():
    def boom(book):
        raise RuntimeError("paper api unreachable")

    c = _seeded()
    out = candidates.generate_candidates(c, now=NOW, positions_fn=boom)
    assert out["held_positions_unavailable"] is True
    gild = next(r for r in out["candidates"] if r["ticker"] == "GILD")
    assert gild["priority"] == 10  # plain conjunction priority, no boost
    assert "held" not in gild["sources"]
