"""A4 (review 2026-11-10): a quarterly figure recorded as a full-year guide
must not anchor a band. Three legs, each pinned on the production shapes:

- TMUS: a reported quarter's EPS (2.99, "Diluted EPS increased ... to $2.99
  per share") sat at 0.31x trailing TTM and passed the old 0.3x floor. The
  uncorroborated trailing floor is now 0.45x at band-build, and the same
  sentence is dropped at ingest as a reported result, not guidance.
- MRK: the filing check (EDGAR, accession 0001104659-26-090045, Merck 8-K
  Ex-99.1) shows 2.66-2.76 is a GENUINE full-year guide that newly includes
  $2.43/share of one-time acquisition charges -- not a quarterly misingest.
  So nothing rejects it: the anchor follows the latest recorded guide, and
  the sheet gains a step-change note naming both mids.
"""
from datetime import date, datetime, timezone

from tradehub.guidance import extract as gx
from tradehub.valuation import engine
from tradehub.valuation import run as val_run

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def rec(ticker="ACME", metric="eps_adjusted", period="FY2026", low=4.0,
        high=5.0, unit="usd_per_share", consensus=None, created="2026-11-01T00:00:00+00:00",
        consensus_period=None, evidence=""):
    return {"ticker": ticker, "metric": metric, "period": period, "low": low,
            "high": high, "unit": unit, "consensus": consensus,
            "consensus_period": consensus_period,
            "created_at": created, "accession": "0001", "evidence": evidence}


def sheet(records, **kw):
    kw.setdefault("peer_median_fwd_eps", 4.0)
    kw.setdefault("peer_count", 6)
    kw.setdefault("peer_basis", "industry_group")
    kw.setdefault("guided_peers", [])
    kw.setdefault("fundamentals", {})
    kw.setdefault("price_date", date(2026, 11, 7))
    return engine.build_fact_sheet(ticker=records[0]["ticker"], records=records,
                                   price=80.0, peer_multiple=20.0, now=NOW, **kw)


TMUS_FUND = {"eps_diluted": {"value": 9.5, "as_of": "2026-09-30"}}


# --- engine: the uncorroborated trailing floor ------------------------------

def test_tmus_reported_quarter_no_longer_anchors():
    s = sheet([rec(ticker="TMUS", metric="eps_gaap", period="2026",
                   low=2.99, high=2.99)], fundamentals=TMUS_FUND)
    assert s["status"] != "banded"
    assert any("trailing" in r and "0.45" in r for r in s["guard_rejections"])


def test_uncorroborated_guide_between_old_and_new_floor_rejected():
    s = sheet([rec(low=3.8, high=3.8)], fundamentals=TMUS_FUND)  # 0.40x
    assert s["status"] != "banded"


def test_uncorroborated_guide_above_the_new_floor_still_bands():
    s = sheet([rec(low=4.75, high=4.75)], fundamentals=TMUS_FUND)  # 0.50x
    assert s["status"] == "banded"


def test_corroborated_guide_below_the_floor_keeps_the_a3_escape():
    s = sheet([rec(low=3.0, high=3.0, consensus=3.05, consensus_period="0y")],
              fundamentals=TMUS_FUND)  # 0.32x trailing, own-basis consensus agrees
    assert s["status"] == "banded"
    assert not any("trailing" in r for r in s["guard_rejections"])


# --- MRK: the genuine charge-laden guide stands, and the sheet says so ------

def _mrk_records():
    return [
        rec(ticker="MRK", period="Full Year 2026", low=5.00, high=5.15,
            consensus=2.77993, consensus_period="0y",
            created="2026-02-04T00:00:00+00:00"),
        rec(ticker="MRK", period="Full Year 2026", low=5.04, high=5.16,
            consensus=2.77993, consensus_period="0y",
            created="2026-04-30T00:00:00+00:00"),
        rec(ticker="MRK", period="Full-Year 2026", low=2.66, high=2.76,
            consensus=2.77993, consensus_period="0y",
            created="2026-07-30T00:00:00+00:00"),
    ]


def test_mrk_anchor_follows_the_latest_recorded_guide():
    s = sheet(_mrk_records(), fundamentals={
        "eps_diluted": {"value": 7.28, "as_of": "2025-12-31"}})
    assert s["status"] == "banded"
    assert abs(s["anchor"]["mid"] - 2.71) < 1e-9


def test_ingest_notes_name_the_mrk_step_change():
    notes = val_run.ingest_notes(_mrk_records(), NOW)
    step = [n for n in notes if "step" in n]
    assert len(step) == 1
    assert "5.10" in step[0] and "2.71" in step[0]


def test_ingest_notes_silent_for_an_ordinary_revision():
    recs = [
        rec(period="Full Year 2026", low=5.00, high=5.15,
            created="2026-02-04T00:00:00+00:00"),
        rec(period="Full Year 2026", low=5.10, high=5.25,
            created="2026-04-30T00:00:00+00:00"),
    ]
    assert not any("step" in n for n in val_run.ingest_notes(recs, NOW))


# --- extract: reported results are not guidance ------------------------------

TMUS_TEXT = ("T-Mobile Reports Second Quarter Results. Diluted EPS increased "
             "5% year-over-year to $2.99 per share and included the impact "
             "of UScellular merger-related costs.")
MRK_TEXT = ("GAAP EPS was $2.04 for the quarter. The Company now expects "
            "full-year 2026 non-GAAP EPS to be between $2.66 and $2.76, "
            "including one-time charges. ACME increased its full-year EPS "
            "guidance to $5.20.")


def _eps_item(**over):
    base = {"period": "2026", "metric": "eps_gaap", "unit": "usd_per_share",
            "scale": "units", "low": 2.99, "high": 2.99,
            "evidence": ("Diluted EPS increased 5% year-over-year to $2.99 "
                         "per share and included the impact of UScellular "
                         "merger-related costs.")}
    base.update(over)
    return gx.GuidanceItem(**base)


def test_reported_result_reason_names_the_tmus_sentence():
    assert gx.reported_result_reason(_eps_item()) == "reported_result_not_guidance"


def test_verify_drops_reported_results_keeps_real_guidance():
    tmus = _eps_item()
    mrk_gaap = _eps_item(period="Full Year 2026", low=2.04, high=2.04,
                         evidence="GAAP EPS was $2.04 for the quarter.")
    mrk_guide = _eps_item(metric="eps_adjusted", period="Full-Year 2026",
                          low=2.66, high=2.76,
                          evidence=("The Company now expects full-year 2026 "
                                    "non-GAAP EPS to be between $2.66 and "
                                    "$2.76, including one-time charges."))
    raised = _eps_item(metric="eps_adjusted", period="Full Year 2026",
                       low=5.20, high=5.20,
                       evidence="ACME increased its full-year EPS guidance to $5.20.")
    text = TMUS_TEXT + " " + MRK_TEXT
    kept, dropped = gx.verify([tmus, mrk_gaap, mrk_guide, raised], text)
    assert kept == [mrk_guide, raised]
    assert dropped == 2
