"""The portfolio check (Kevin, 2026-11-09): a portfolio-level gate on ideas and orders.

The properties that matter: thesis caps block on the POST-TRADE book (a buy that pushes
GLD over its 12% cap refuses, naming the cap and the post-trade weight); exits always
pass (a sell that reduces an over-cap position is the cure, never a new breach); IBIT is
exit-only (any exposure-increasing IBIT order blocks, closes pass); the factor clusters
warn without blocking; the targets live in ONE editable config row, so changing a cap
changes the verdict with no code change; and the correlation readout comes from stored
sleeve series, never from a live price pull at order time.
"""
import pytest
from workshop_fake import DB

from tradehub.portfolio import portfolio_check as pc


def _book(positions: dict[str, float]) -> dict[str, dict]:
    """Symbol -> position row, from plain market values (the engine's input shape)."""
    return {s: {"qty": 0.0, "mv": float(mv)} for s, mv in positions.items()}


# A big-book-shaped invested book: $900k invested.
BIG = {
    "GLD": 117_000.0,   # 13.0% of invested: over its 12% cap already (the trim is working)
    "XLP": 50_000.0, "XLU": 50_000.0, "XLRE": 50_000.0, "XLV": 50_000.0,
    "VNQ": 50_000.0, "DBC": 50_000.0, "USO": 50_000.0,          # ballast at ~5.6% each
    "DLTR": 36_000.0, "DG": 36_000.0, "MO": 36_000.0, "WSM": 36_000.0,  # T2 ~4% each
    "SPY": 110_000.0, "VOO": 74_000.0,                         # index 20.4%
    "AAPL": 9_000.0, "NVDA": 9_000.0, "MSFT": 9_000.0,
    "AVGO": 9_000.0, "MU": 9_000.0, "TSM": 9_000.0,             # T8 6.0%
    "IBIT": 34_000.0,                                          # 3.8%
    "TXN": 9_000.0, "INTC": 8_000.0,                           # legacy chips
}
assert sum(BIG.values()) == 900_000.0


def evaluate(positions, deltas, **kw):
    return pc.evaluate(_book(positions), deltas, pc.DEFAULT_CONFIG, **kw)


# ── GLD: the name cap with a target (acceptance a) ─────────────────────────────

def test_a_gld_buy_that_pushes_over_its_cap_blocks_naming_cap_and_weight():
    out = evaluate(BIG, {"GLD": 5_000.0})
    assert out["outcome"] == "block"
    block = next(b for b in out["blocks"] if "GLD" in b["detail"])
    assert "12" in block["detail"]                      # the cap
    assert "13.5" in block["detail"]                    # the post-trade weight: 122k/905k


def test_a_gld_buy_from_under_the_cap_that_crosses_it_blocks():
    book = {**BIG, "GLD": 100_000.0}                    # 11.3% of 883k: under the cap
    out = evaluate(book, {"GLD": 10_000.0})             # -> 110k/893k = 12.3%
    assert out["outcome"] == "block"


def test_a_gld_sell_from_over_the_cap_passes_because_exits_always_pass():
    out = evaluate(BIG, {"GLD": -50_000.0})
    assert out["outcome"] != "block"
    assert out["weights"]["names"]["GLD"] < 12.0        # still over, but leaving


def test_a_small_gld_buy_under_the_cap_passes():
    book = {**BIG, "GLD": 90_000.0}                     # 10.1%
    out = evaluate(book, {"GLD": 5_000.0})              # -> 10.6%
    assert out["outcome"] == "pass"


# ── sleeve bands and caps ──────────────────────────────────────────────────────

def test_a_ballast_member_over_8_percent_blocks():
    out = evaluate(BIG, {"XLP": 25_000.0})              # 75k/925k = 8.1%
    assert out["outcome"] == "block"
    assert any("XLP" in b["detail"] and "8" in b["detail"] for b in out["blocks"])


def test_a_ballast_member_sold_below_the_2_percent_floor_blocks():
    book = {**BIG, "DBC": 20_000.0}                     # 2.2% of 870k
    out = evaluate(book, {"DBC": -5_000.0})             # -> 15k/865k = 1.7%: under the floor
    assert out["outcome"] == "block"
    assert any("DBC" in b["detail"] for b in out["blocks"])


# ── Kevin's ruling (2026-11-09): exits win over the member floor ──────────────

def test_an_exit_trim_below_the_floor_warns_and_does_not_block():
    book = {**BIG, "DBC": 20_000.0}                     # 2.2% of 870k
    out = evaluate(book, {"DBC": -5_000.0}, is_exit=True)   # -> 1.7%: under the floor
    assert out["outcome"] != "block"
    assert out["blocks"] == []
    warn = next(w for w in out["warnings"] if "DBC" in w["detail"])
    assert warn["rule"] == "member_floor_exit"
    assert "floor" in warn["detail"] and "exit" in warn["detail"]
    assert "Kevin's ruling" in warn["detail"]           # the warning names the ruling


def test_the_same_trim_without_exit_classification_still_blocks():
    book = {**BIG, "DBC": 20_000.0}
    out = evaluate(book, {"DBC": -5_000.0}, is_exit=False)
    assert out["outcome"] == "block"
    assert any(b["rule"] == "member_floor" for b in out["blocks"])


def test_exit_classification_downgrades_only_the_floor_never_a_cap():
    # is_exit is not a general pass: a delta that ADDS to an over-cap member
    # still blocks (the classifier upstream never calls such an order an exit;
    # the engine's cap rules are untouched by the ruling either way).
    out = evaluate(BIG, {"XLP": 25_000.0}, is_exit=True)    # 75k/925k = 8.1%
    assert out["outcome"] == "block"


def test_check_order_threads_the_exit_flag_and_defaults_to_blocking(monkeypatch):
    # The activation path calls check_order with no exit flag (main.py) and must
    # keep the shipped floor behavior; the machine door passes its classification.
    book = {**BIG, "DBC": 20_000.0}
    monkeypatch.setattr(pc, "positions_by_underlying", lambda book_name: _book(book))
    out = pc.check_order(None, "main", {"DBC": -5_000.0}, source="activation",
                         record=False)
    assert out["outcome"] == "block"
    out = pc.check_order(None, "main", {"DBC": -5_000.0}, source="machine_preflight",
                         record=False, is_exit=True)
    assert out["outcome"] != "block"
    assert any(w["rule"] == "member_floor_exit" for w in out["warnings"])


def test_a_ballast_member_bought_back_toward_the_band_passes():
    book = {**BIG, "DBC": 10_000.0}                     # 1.1%: under the floor already
    out = evaluate(book, {"DBC": 10_000.0})             # buying back toward the band
    assert out["outcome"] != "block"


def test_the_t8_sleeve_over_10_percent_blocks():
    out = evaluate(BIG, {"NVDA": 50_000.0})             # sleeve 104k/950k = 10.9% -> over
    assert out["outcome"] == "block"
    assert any("T8" in b["detail"] for b in out["blocks"])


def test_a_single_t8_name_over_5_percent_blocks_even_inside_the_sleeve_cap():
    book = {**BIG, "AAPL": 9_000.0, "NVDA": 9_000.0, "MSFT": 9_000.0,
            "AVGO": 9_000.0, "MU": 9_000.0, "TSM": 9_000.0}
    out = evaluate(book, {"AAPL": 40_000.0})            # AAPL 49k/940k = 5.2%; sleeve 10.0%
    assert out["outcome"] == "block"
    assert any("AAPL" in b["detail"] for b in out["blocks"])


def test_a_t2_name_over_5_percent_blocks():
    out = evaluate(BIG, {"DG": 12_000.0})               # 48k/912k = 5.3%
    assert out["outcome"] == "block"
    assert any("DG" in b["detail"] for b in out["blocks"])


def test_the_index_sleeve_over_25_percent_blocks():
    book = {**BIG, "SPY": 190_000.0, "VOO": 40_000.0}   # index 230k/946k = 24.3%
    out = evaluate(book, {"SPY": 40_000.0})             # -> 270k/986k = 27.4%
    assert out["outcome"] == "block"
    assert any("index" in b["detail"].lower() for b in out["blocks"])


def test_an_unassigned_name_over_5_percent_blocks_but_spy_is_not_a_single_name():
    out = evaluate(BIG, {"COIN": 50_000.0})             # 50k/950k = 5.3%, no sleeve
    assert out["outcome"] == "block"
    out = evaluate(BIG, {"SPY": 5_000.0})               # the index sleeve has its own cap
    assert out["outcome"] != "block"


# ── IBIT is exit-only ──────────────────────────────────────────────────────────

def test_an_ibit_buy_blocks_exit_only():
    out = evaluate(BIG, {"IBIT": 1_000.0})
    assert out["outcome"] == "block"
    assert any("IBIT" in b["detail"] and "exit-only" in b["detail"] for b in out["blocks"])


def test_an_ibit_sell_passes_exit_only():
    out = evaluate(BIG, {"IBIT": -10_000.0})
    assert out["outcome"] != "block"


def test_an_ibit_option_leg_that_adds_exposure_blocks_and_a_close_passes():
    out = evaluate(BIG, {"IBIT": 500.0})                # deltas are exposure, whatever the wrapper
    assert out["outcome"] == "block"
    out = evaluate(BIG, {"IBIT": -500.0})
    assert out["outcome"] != "block"


# ── factor stacking: warnings, never blocks ────────────────────────────────────

def test_a_cluster_rise_over_two_points_warns_without_blocking():
    book = {**BIG, "AAPL": 9_000.0, "NVDA": 9_000.0, "MSFT": 9_000.0,
            "AVGO": 9_000.0, "MU": 9_000.0, "TSM": 9_000.0,
            "TXN": 9_000.0, "INTC": 8_000.0}
    # AI complex is 71k/900k = 7.9%; a $30k TXN buy takes it to 101k/930k = 10.9% (+3.0 pts)
    # while staying inside every cap (TXN 4.2%, no sleeve cap on legacy chips).
    out = evaluate(book, {"TXN": 30_000.0})
    assert out["outcome"] == "warn"
    assert any("AI complex" in w["detail"] for w in out["warnings"])


def test_a_small_cluster_rise_does_not_warn():
    book = {**BIG, "GLD": 90_000.0}                     # gold under its flag, so only the rise can warn
    out = evaluate(book, {"TXN": 5_000.0})
    assert out["outcome"] == "pass"
    assert out["warnings"] == []


def test_gold_over_12_percent_warns_even_when_the_order_is_not_golds():
    # GLD drifts: a rates-trio sell shrinks invested and lifts gold's share over 12.
    book = {**BIG, "GLD": 115_000.0}                    # 12.8% already
    out = evaluate(book, {"XLU": -1_000.0})
    assert out["outcome"] != "block"                    # the sell adds no gold dollars
    assert any("gold" in w["detail"].lower() for w in out["warnings"])


# ── weights, thesis attribution, degenerate books ─────────────────────────────

def test_weights_are_percent_of_invested_post_trade():
    out = evaluate(BIG, {"XLP": 5_000.0})
    assert out["weights"]["invested"] == pytest.approx(905_000.0)
    assert out["weights"]["sleeves"]["t4_ballast"] == pytest.approx(
        (467_000.0 + 5_000.0) / 905_000.0 * 100, abs=0.01)
    assert out["weights"]["names"]["XLP"] == pytest.approx(55_000.0 / 905_000.0 * 100, abs=0.01)


def test_thesis_attribution_prefers_the_tag_then_the_symbol():
    out = evaluate(BIG, {"NVDA": 1_000.0}, tag="ai-tech-core")
    assert out["thesis"]["id"] == "t8_ai" and out["thesis"]["via"] == "tag"
    out = evaluate(BIG, {"NVDA": 1_000.0})
    assert out["thesis"]["id"] == "t8_ai" and out["thesis"]["via"] == "symbol"
    out = evaluate(BIG, {"COIN": 1_000.0})
    assert out["thesis"]["id"] is None


def test_a_book_under_the_minimum_invested_passes_with_the_reason_stated():
    out = evaluate({"SPY": 250.0}, {"SPY": 250.0})
    assert out["outcome"] == "pass"
    assert "invested" in out["detail"]


def test_an_empty_book_passes():
    out = evaluate({}, {"XLE": 2_000.0})
    assert out["outcome"] == "pass"


# ── the config is the law: editing it changes verdicts with no code change ────

def test_load_config_falls_back_to_the_seed_when_the_table_is_empty():
    cfg = pc.load_config(DB())
    assert cfg["name_overrides"]["GLD"]["max_pct"] == 12.0
    assert cfg["sleeves"]["t8_ai"]["sleeve_max_pct"] == 10.0


def test_load_config_reads_the_stored_row():
    db = DB()
    db.db["portfolio_targets"] = [{"scope": "global", "config": {
        "name_overrides": {"GLD": {"target_pct": 20.0, "max_pct": 25.0}}}}]
    cfg = pc.load_config(db)
    assert cfg["name_overrides"]["GLD"]["max_pct"] == 25.0
    # untouched sections still carry the seed, so a partial edit cannot drop a sleeve
    assert "GLD" in cfg["sleeves"]["t4_ballast"]["symbols"]


def test_a_config_edit_changes_the_verdict():
    cfg = pc.load_config(DB())
    cfg["name_overrides"]["GLD"]["max_pct"] = 20.0       # Kevin relaxes gold's cap
    out = pc.evaluate(_book(BIG), {"GLD": 5_000.0}, cfg)
    assert out["outcome"] != "block"                    # 13.5% is inside a 20% cap


# ── correlation readout from stored series ─────────────────────────────────────

def _series(points: int = 120):
    """A sleeve series and a book series that tracks it exactly (corr 1.0)."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    sleeve = [((start + timedelta(days=i)).isoformat(), 0.01 if i % 2 == 0 else -0.01)
              for i in range(points)]
    return {"t8_ai": sleeve, "__book__": list(sleeve)}


def test_correlation_reads_the_stored_series():
    out = evaluate(BIG, {"NVDA": 1_000.0}, series=_series())
    assert out["correlation"]["series"] == "t8_ai"
    assert out["correlation"]["corr"] == pytest.approx(1.0)
    assert out["correlation"]["days"] == 120


def test_correlation_is_null_with_a_note_when_no_series_is_stored():
    out = evaluate(BIG, {"NVDA": 1_000.0}, series={})
    assert out["correlation"]["corr"] is None
    assert out["correlation"]["note"]
