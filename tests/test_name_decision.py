"""Batch 2: the per-name decision view + the compact verdict chips.

One surface per name answers four questions — what we know (the fact
sheet), what the systems say (recorded screens, bands/zones, crossings,
print classification), the judgment (latest debate verdict + the band
falsifier standing), and what is missing (named gaps, never proxied).
The chips are the compact persistence read: name, date, verdict,
confidence, exhibit snapshot id, judge identity, one-line dissent."""
from tradehub.valuation import decisions
from tests.test_debate_candidates import _seeded


def _verdict_row(**over):
    row = {
        "id": 7, "ticker": "GILD", "rendered_at": "2026-11-10T06:00:00+00:00",
        "trigger": "conjunction", "status": "rendered",
        "judge": "free-ai-proposer", "proposer_model": "qwen-fake",
        "fact_sheet_id": 103, "snapshot_id": 3,
        "price": 95.0, "price_as_of": "2026-11-09",
        "bands": {"bear": 80.0, "base": 90.0, "bull": 100.0},
        "band_basis": "eps", "baseline_verdict": "buy_zone_strong",
        "verdict": {"choice_id": "act_at_band_mid", "direction": "long",
                    "probability": 0.58, "rationale": "guide supports it"},
        "proposer_pick": {"choice_id": "act_at_band_mid",
                          "direction": "long", "probability": 0.58},
        "bull_case": "The guide is conservative. More bull.",
        "bear_case": "The price already pays for the guide. More bear.",
        "falsifier": "Falsified if GILD cuts the FY guide.",
        "candidate_sources": {"zone": "buy_zone_strong"},
    }
    row.update(over)
    return row


def test_chips_are_compact_and_carry_judge_and_snapshot():
    c = _seeded()
    c.tables["valuation_verdicts"] = [_verdict_row()]
    chips = decisions.verdict_chips(c)
    chip = chips["GILD"]
    assert chip["choice_id"] == "act_at_band_mid"
    assert chip["direction"] == "long"
    assert chip["confidence"] == 0.58
    assert chip["judge"] == "free-ai-proposer"
    assert chip["snapshot_id"] == 3
    assert chip["rendered_at"].startswith("2026-11-10")
    # the dissent is the OTHER side's first line: a long verdict carries
    # the bear's opening objection
    assert chip["dissent"] == "The price already pays for the guide."


def test_chips_skip_voids_and_take_the_latest_render():
    c = _seeded()
    c.tables["valuation_verdicts"] = [
        _verdict_row(id=8, status="void", verdict=None,
                     rendered_at="2026-11-10T07:00:00+00:00"),
        _verdict_row(),
        _verdict_row(id=9, rendered_at="2026-11-09T07:00:00+00:00",
                     verdict={"choice_id": "pass", "direction": "none",
                              "probability": None, "rationale": "old"}),
    ]
    chips = decisions.verdict_chips(c)
    assert chips["GILD"]["verdict_id"] == 7  # latest RENDERED, not the void


def test_dissent_for_a_short_verdict_is_the_bulls_line():
    row = _verdict_row(verdict={"choice_id": "act_at_band_mid",
                                "direction": "short", "probability": 0.6,
                                "rationale": "rich"})
    assert decisions.dissent_line(row) == "The guide is conservative."


def test_decision_view_answers_all_four_questions():
    c = _seeded()
    c.tables["valuation_verdicts"] = [_verdict_row()]
    c.tables["band_crossings"] = [{
        "id": 1, "ticker": "GILD", "book": "main", "zone": "buy_zone_strong",
        "action": "starter", "score_20": None,
        "created_at": "2026-11-10T05:00:00+00:00", "snapshot_id": 3}]
    view = decisions.name_decision(c, "GILD")
    assert view["snapshot"]["id"] == 3
    know = view["know"]
    assert know["status"] == "banded" and know["bands"]["base"] == 90.0
    systems = view["systems"]
    assert systems["zone"] == "buy_zone_strong"
    assert systems["screens"][0]["screen_id"] == 6
    assert systems["screens"][0]["member_since"] == "2026-11-10"
    assert systems["print_classification"] == {
        "classification": "intact", "as_of": "2026-11-08"}
    assert systems["crossings"][0]["action"] == "starter"
    judgment = view["judgment"]
    assert judgment["verdict"]["confidence"] == 0.58
    assert judgment["verdict"]["judge"] == "free-ai-proposer"
    assert judgment["falsifier"] == "Falsified if GILD cuts the FY guide."
    assert judgment["crossings_graded"] == 0
    assert view["missing"] == []


def test_decision_view_names_its_gaps():
    c = _seeded()
    view = decisions.name_decision(c, "AMGN")
    gaps = " · ".join(view["missing"])
    assert "no debate verdict rendered yet" in gaps
    assert "not a member of any recorded screen" in gaps
    assert "no print classification on record" in gaps
    # ...while the same view still shows what IS known
    assert view["know"]["bands"] is not None
    assert view["judgment"]["verdict"] is None
    assert view["judgment"]["falsifier"]  # the sheet's falsifier stands


def test_decision_view_for_a_sheetless_screen_name():
    c = _seeded()
    view = decisions.name_decision(c, "MSFT")
    assert view["know"] is None
    assert "no guidance fact sheet on record" in " · ".join(view["missing"])
    assert view["systems"]["screens"]  # the screen record still answers


def test_decision_view_unknown_name_is_none():
    c = _seeded()
    assert decisions.name_decision(c, "ZZZZ") is None


def test_pending_candidate_is_named_not_a_verdict():
    c = _seeded()
    c.tables["debate_candidates"] = [{
        "id": 1, "ticker": "AMGN", "snapshot_id": 3,
        "candidate_class": "zone", "priority": 20, "state": "pending",
        "sources": {}, "computed_at": "2026-11-10T12:00:00+00:00"}]
    view = decisions.name_decision(c, "AMGN")
    assert view["judgment"]["verdict"] is None
    assert view["judgment"]["candidate"]["candidate_class"] == "zone"
    assert "debate candidate queued" in " · ".join(view["missing"])
