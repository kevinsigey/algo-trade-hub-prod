"""Verdict rendering end to end (stubbed supabase / price layer / LLM): the
stored record must carry the verdict, the JUDGE identity, BOTH controls
(band-rule baseline + proposer pick), the frozen peer state, the options
inputs, and the falsifier. Stale or unbanded sheets render nothing (spec
section 1: a stale sheet does not debate and does not render a verdict)."""
from datetime import datetime, timezone

import pandas as pd

from tradehub.valuation import verdicts

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


# -- a small fake of the supabase query builder, shaped like verdict_store's use
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self._c, self._t = client, table
        self._mode, self._payload = "select", None
        self._filters, self._orders, self._limit = [], [], None
        self._conflict = ""

    def select(self, _cols):
        return self

    def insert(self, row):
        self._mode, self._payload = "insert", row
        return self

    def upsert(self, row, on_conflict=""):
        self._mode, self._payload, self._conflict = "upsert", row, on_conflict
        return self

    def update(self, row):
        self._mode, self._payload = "update", row
        return self

    def eq(self, key, val):
        self._filters.append(lambda r: r.get(key) == val)
        return self

    def gte(self, key, val):
        self._filters.append(lambda r: (r.get(key) or "") >= val)
        return self

    def order(self, col, desc=False):
        self._orders.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _rows(self):
        return self._c.tables.setdefault(self._t, [])

    def execute(self):
        rows = self._rows()
        if self._mode == "insert":
            row = dict(self._payload)
            row["id"] = self._c.next_id(self._t)
            rows.append(row)
            return _Resp([dict(row)])
        if self._mode == "upsert":
            keys = [k.strip() for k in self._conflict.split(",") if k.strip()]
            for i, old in enumerate(rows):
                if all(old.get(k) == self._payload.get(k) for k in keys):
                    rows[i] = {**old, **self._payload}
                    return _Resp([dict(rows[i])])
            row = dict(self._payload)
            row["id"] = self._c.next_id(self._t)
            rows.append(row)
            return _Resp([dict(row)])
        if self._mode == "update":
            hit = []
            for row in rows:
                if all(f(row) for f in self._filters):
                    row.update(self._payload)
                    hit.append(dict(row))
            return _Resp(hit)
        out = [dict(r) for r in rows if all(f(r) for f in self._filters)]
        for col, desc in reversed(self._orders):
            out.sort(key=lambda r: (r.get(col) is None, r.get(col)),
                     reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]
        return _Resp(out)


class FakeClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self._ids: dict[str, int] = {}

    def next_id(self, table):
        self._ids[table] = self._ids.get(table, 0) + 1
        return self._ids[table]

    def table(self, name):
        return _Query(self, name)


# -- fixtures -----------------------------------------------------------------

def _sheet_row(**over):
    row = {
        "id": 41, "ticker": "AMGN", "tier": "watch", "status": "banded",
        "price": 460.42, "price_as_of": "2026-11-06",
        "peer_group": "biotechnology", "peer_multiple": 16.49,
        "peer_count": 7, "peer_basis": "industry_group",
        "anchor": {"metric": "eps_adjusted", "period": "FY2026",
                   "period_key": "FY2026", "low": 18.34, "high": 19.28,
                   "mid": 18.81, "point_guide": False, "consensus": 18.9,
                   "recorded_at": "2026-11-05T12:00:00+00:00",
                   "accession": "0000318154-26-000153"},
        "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92},
        "implied_eps": 27.92, "implied_revenue": None, "band_basis": "eps",
        "gap_range_widths": 9.69, "guidance_percentile": None,
        "baseline_verdict": "short_zone_strong", "stale": False,
        "falsifier": "Falsified if AMGN guides FY2026 EPS below 18.34 ...",
        "directions": {}, "fundamentals": {},
        "computed_at": "2026-11-08T04:00:00+00:00",
    }
    row.update(over)
    return row


class _DS:
    def prices(self, tickers, years=1):
        idx = pd.bdate_range("2026-11-02", periods=5)
        return pd.DataFrame({t: [100.0, 101.0, 102.0, 103.0, 460.42]
                             for t in tickers}, index=idx)

    def implied_move(self, _ticker):
        return 9.0


def _chat(system, user, *, schema=None):
    if "BULL RESEARCHER" in system:
        return "bull prose", "qwen-fake"
    if "BEAR RESEARCHER" in system:
        return "bear prose", "qwen-fake"
    return {
        "choices": [
            {"choice_id": "act_at_band_low", "label": "Act at the low band",
             "price": 272.18},
            {"choice_id": "act_at_band_mid", "label": "Act at the mid band",
             "price": 310.17},
            {"choice_id": "watch", "label": "Watch", "price": 460.42},
            {"choice_id": "pass", "label": "Pass", "price": 460.42},
        ],
        "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                           "direction_momentum": 0.15,
                           "options_expression": 0.1,
                           "falsifier_proximity": 0.2},
        "digest": "digest",
        "proposer_pick": {"choice_id": "act_at_band_mid",
                          "direction": "short", "probability": 0.62},
        "rationale": "the price implies more than the file",
    }, "qwen-fake"


def _client_with_sheet(**over):
    client = FakeClient()
    client.tables["valuation_fact_sheets"] = [_sheet_row(**over)]
    return client


# -- tests --------------------------------------------------------------------

def test_render_stores_verdict_with_judge_both_controls_and_frozen_peers():
    client = _client_with_sheet()
    result = verdicts.render_verdict(client, _DS(), "AMGN",
                                     trigger="on_demand", chat=_chat, now=NOW)
    assert result["status"] == "rendered"
    [row] = client.tables["valuation_verdicts"]
    assert row["judge"] == "free-ai-proposer"
    assert row["verdict"]["choice_id"] == "act_at_band_mid"
    assert row["verdict"]["direction"] == "short"
    assert row["baseline_verdict"] == "short_zone_strong"     # control 1
    assert row["proposer_pick"]["choice_id"] == "act_at_band_mid"  # control 2
    assert row["fact_sheet_id"] == 41
    members = {m["ticker"]: m for m in row["frozen_peers"]["members"]}
    assert members["GILD"]["price"] == 460.42  # frozen at render, from the DS
    assert row["options_inputs"]["expression"] == "debit_put_spread"
    assert row["falsifier"].startswith("Falsified if AMGN")
    assert row["target_price"] == 272.18  # short from the mid anchor -> bear


def test_stale_sheet_renders_no_verdict():
    client = _client_with_sheet(stale=True)
    result = verdicts.render_verdict(client, _DS(), "AMGN",
                                     trigger="on_demand", chat=_chat, now=NOW)
    assert result["status"] == "stale_sheet"
    assert not client.tables.get("valuation_verdicts")


def test_unbanded_sheet_renders_no_verdict():
    client = _client_with_sheet(status="no_full_year_guide", bands=None,
                                baseline_verdict="no_bands")
    result = verdicts.render_verdict(client, _DS(), "AMGN",
                                     trigger="on_demand", chat=_chat, now=NOW)
    assert result["status"] == "not_banded"
    assert not client.tables.get("valuation_verdicts")


def test_missing_sheet_is_a_plain_no():
    result = verdicts.render_verdict(FakeClient(), _DS(), "ZZZZ",
                                     trigger="on_demand", chat=_chat, now=NOW)
    assert result["status"] == "no_sheet"


def test_invented_packet_price_logs_a_void_verdict_not_a_decision():
    def bad_chat(system, user, *, schema=None):
        out = _chat(system, user, schema=schema)
        if isinstance(out[0], dict):
            packet = dict(out[0])
            packet["choices"] = [dict(c) for c in packet["choices"]]
            packet["choices"][0]["price"] = 1.0
            return packet, out[1]
        return out

    client = _client_with_sheet()
    result = verdicts.render_verdict(client, _DS(), "AMGN",
                                     trigger="on_demand", chat=bad_chat,
                                     now=NOW)
    assert result["status"] == "void"
    [row] = client.tables["valuation_verdicts"]
    assert row["status"] == "void" and row["verdict"] is None
    assert "void" in row["void_reason"].lower() or row["void_reason"]


def test_daily_cap_stops_renders():
    client = _client_with_sheet()
    for _ in range(verdicts.DAILY_CAP):
        verdicts.render_verdict(client, _DS(), "AMGN", trigger="refresh",
                                chat=_chat, now=NOW)
    result = verdicts.render_verdict(client, _DS(), "AMGN", trigger="refresh",
                                     chat=_chat, now=NOW)
    assert result["status"] == "cap_reached"
    assert len(client.tables["valuation_verdicts"]) == verdicts.DAILY_CAP
