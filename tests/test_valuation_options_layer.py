"""Options-layer inputs (spec section 3): implied move vs the distance to the
next band, on hand cases. Defined-risk debit spreads only, and only when the
implied move underprices the distance; otherwise stock expression or none.
Inputs only -- nothing here places or sizes anything."""
from tradehub.valuation import options_layer

BANDS = {"bear": 272.18, "base": 310.17, "bull": 317.92}


def test_short_zone_underpriced_gives_put_spread_at_band_strikes():
    out = options_layer.spread_inputs(price=460.42, bands=BANDS,
                                      zone="short_zone_strong",
                                      implied_move_pct=9.0)
    assert out["expression"] == "debit_put_spread"
    assert out["long_strike"] == 317.92   # the bull band: the band at the price
    assert out["short_strike"] == 310.17  # the base band: the target below
    assert out["underpriced"] is True
    # distance from the price down to the target band
    assert abs(out["distance_to_target_pct"] - (460.42 - 310.17) / 460.42 * 100) < 0.01


def test_short_zone_implied_move_covering_distance_is_stock_only():
    out = options_layer.spread_inputs(price=460.42, bands=BANDS,
                                      zone="short_zone_strong",
                                      implied_move_pct=40.0)
    assert out["expression"] == "stock_only"
    assert out["underpriced"] is False


def test_buy_zone_underpriced_gives_call_spread():
    out = options_layer.spread_inputs(price=250.0, bands=BANDS,
                                      zone="buy_zone_strong",
                                      implied_move_pct=10.0)
    assert out["expression"] == "debit_call_spread"
    assert out["long_strike"] == 272.18   # bear band
    assert out["short_strike"] == 310.17  # base band, the target above
    assert abs(out["distance_to_target_pct"] - (310.17 - 250.0) / 250.0 * 100) < 0.01


def test_price_between_bands_uses_enclosing_bands():
    out = options_layer.spread_inputs(price=290.0, bands=BANDS,
                                      zone="buy_zone", implied_move_pct=5.0)
    assert out["expression"] == "debit_call_spread"
    assert out["long_strike"] == 272.18
    assert out["short_strike"] == 310.17


def test_neutral_zone_has_no_options_expression():
    out = options_layer.spread_inputs(price=315.0, bands=BANDS,
                                      zone="neutral", implied_move_pct=3.0)
    assert out["expression"] == "none"
    assert out["long_strike"] is None and out["short_strike"] is None


def test_missing_implied_move_is_unevaluated_not_invented():
    out = options_layer.spread_inputs(price=250.0, bands=BANDS,
                                      zone="buy_zone", implied_move_pct=None)
    assert out["expression"] == "unevaluated"
    assert out["underpriced"] is None
    assert out["implied_move_pct"] is None


def test_no_bands_no_expression():
    out = options_layer.spread_inputs(price=250.0, bands=None,
                                      zone="no_bands", implied_move_pct=5.0)
    assert out["expression"] == "none"
