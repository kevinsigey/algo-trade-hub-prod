"""Tests for the mirror-stop reconciler's planner (scripts/mirror_stops.py).

The planner is the safety of the tool: it diffs a desired stop list against the
positions that actually filled and the stops already resting, so a stop can never
become a fresh short, never double-cover a symbol, and never fight a stop Kevin
placed himself in the Alpaca app.
"""

from tradehub.scripts.mirror_stops import plan_stops

SPEC = [{"symbol": "XLE", "qty": 115, "stop_price": 65.55},
        {"symbol": "XOM", "qty": 49, "stop_price": 175.00},
        {"symbol": "META", "qty": 2, "stop_price": 500.0}]


def test_places_stops_sized_to_the_positions_held():
    to_place, skipped = plan_stops(SPEC, {"XLE": 115.0, "XOM": 30.0}, [])
    assert to_place == [{"symbol": "XLE", "qty": 115, "side": "sell", "stop_price": 65.55},
                        {"symbol": "XOM", "qty": 30, "side": "sell", "stop_price": 175.0}]
    assert [s["symbol"] for s, _ in skipped] == ["META"]  # not held: no stop, no short


def test_a_short_position_gets_a_buy_stop():
    to_place, _ = plan_stops([{"symbol": "AAPL", "qty": 12, "stop_price": 280.0}],
                             {"AAPL": -12.0}, [])
    assert to_place[0]["side"] == "buy" and to_place[0]["qty"] == 12


def test_a_resting_stop_at_the_same_price_is_not_duplicated():
    resting = [{"symbol": "XLE", "side": "sell", "type": "stop", "stop_price": "65.55", "qty": "80"}]
    to_place, skipped = plan_stops(SPEC[:1], {"XLE": 115.0}, resting)
    assert to_place[0]["qty"] == 35  # only the uncovered remainder
    resting_full = [{**resting[0], "qty": "115"}]
    to_place, skipped = plan_stops(SPEC[:1], {"XLE": 115.0}, resting_full)
    assert to_place == [] and "already resting" in skipped[0][1]


def test_a_resting_stop_at_a_different_price_does_not_count():
    resting = [{"symbol": "XLE", "side": "sell", "type": "stop", "stop_price": "60.00", "qty": "115"}]
    to_place, _ = plan_stops(SPEC[:1], {"XLE": 115.0}, resting)
    assert to_place[0]["qty"] == 115


def test_a_resting_limit_sell_is_not_a_stop():
    resting = [{"symbol": "XLE", "side": "sell", "type": "limit", "stop_price": None, "qty": "115"}]
    to_place, _ = plan_stops(SPEC[:1], {"XLE": 115.0}, resting)
    assert to_place[0]["qty"] == 115
