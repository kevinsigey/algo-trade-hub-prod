"""NaN guards for the verdict path (found live 2026-11-12, A5 follow-up).

AMGN's implied-move read can come back NaN rather than "no data". Passed
through as a real number it (a) reads as "the implied move covers the
distance" in the options layer and (b) crashes verdict storage outright --
postgrest's JSON encoder refuses NaN, so a fully rendered verdict was
computed and then lost. Non-finite floats mean "no data" in both places:
the options layer records the name unevaluated, and verdict storage
converts any non-finite float anywhere in the row to None."""
import json
import math

from tradehub.valuation import options_layer, verdict_store

BANDS = {"bear": 272.18, "base": 310.17, "bull": 317.92}


class _Resp:
    def __init__(self, data):
        self.data = data


class _InsertQuery:
    def __init__(self, sink):
        self._sink = sink

    def insert(self, row):
        self._sink.append(row)
        return self

    def execute(self):
        return _Resp([dict(self._sink[-1], id=1)])


class _StubClient:
    def __init__(self):
        self.inserted = []

    def table(self, _name):
        return _InsertQuery(self.inserted)


class _Ds:
    def __init__(self, value):
        self._value = value

    def implied_move(self, _ticker):
        return self._value


def _sheet():
    return {"price": 250.0, "bands": BANDS, "baseline_verdict": "buy_zone"}


# -- options layer -----------------------------------------------------------

def test_nan_implied_move_is_unevaluated_not_a_number():
    out = options_layer.spread_inputs(price=250.0, bands=BANDS,
                                      zone="buy_zone",
                                      implied_move_pct=float("nan"))
    assert out["expression"] == "unevaluated"
    assert out["implied_move_pct"] is None
    assert out["underpriced"] is None


def test_infinite_implied_move_is_unevaluated():
    out = options_layer.spread_inputs(price=250.0, bands=BANDS,
                                      zone="buy_zone",
                                      implied_move_pct=float("inf"))
    assert out["expression"] == "unevaluated"
    assert out["implied_move_pct"] is None


def test_gather_coerces_a_nan_read_to_unevaluated():
    out = options_layer.gather(_Ds(float("nan")), "AMGN", _sheet())
    assert out["expression"] == "unevaluated"
    assert out["implied_move_pct"] is None


def test_gather_passes_a_finite_read_through():
    out = options_layer.gather(_Ds(5.0), "AMGN", _sheet())
    assert out["implied_move_pct"] == 5.0
    assert out["expression"] == "debit_call_spread"


# -- verdict storage -----------------------------------------------------------

def test_insert_verdict_converts_non_finite_floats_to_none():
    client = _StubClient()
    row = {"ticker": "AMGN", "price": 460.42,
           "options_inputs": {"implied_move_pct": float("nan"),
                              "distance_to_target_pct": 12.5},
           "frozen_peers": [{"multiple": float("inf")}, {"multiple": 16.49}],
           "target_price": float("-inf")}
    verdict_store.insert_verdict(client, row)
    stored = client.inserted[0]
    assert stored["options_inputs"]["implied_move_pct"] is None
    assert stored["options_inputs"]["distance_to_target_pct"] == 12.5
    assert stored["frozen_peers"][0]["multiple"] is None
    assert stored["frozen_peers"][1]["multiple"] == 16.49
    assert stored["target_price"] is None
    assert stored["price"] == 460.42
    # The stored row must survive a strict JSON encoding (postgrest's does).
    json.dumps(stored, allow_nan=False)


def test_insert_verdict_does_not_mutate_the_callers_row():
    client = _StubClient()
    row = {"ticker": "AMGN", "options_inputs": {"implied_move_pct": float("nan")}}
    verdict_store.insert_verdict(client, row)
    assert math.isnan(row["options_inputs"]["implied_move_pct"])
