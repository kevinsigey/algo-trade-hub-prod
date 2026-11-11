"""Spec F LEAPS shadow trial — Workshop idea 81, family T8-LEAPS-1
(preregistered 2026-11-11; build spec
docs/spec-f-leaps-shadow-2026-11-11.md).

Shadow-first per Kevin's 2026-11-11 amendment: when a T8 name reaches a
stamped Guidance base band (a Spec C band_crossings row, zone bear/base,
action starter/add — the crossing engine has already enforced the guide
legs), the trial opens TWO shadow lines at the same moment: a deep-ITM
LEAPS line priced off the live chain at capture (never the hub's model
marks) and a share line at identical delta-notional. Both lines are
booked at delta-notional; the premium is its own field everywhere. This
module places no orders and has no path to them.

Nightly (tradehub/scripts/leaps_shadow_grade.py): intake consumes new
qualifying crossings (one open pair per ticker; repeats ride as events
on the open pair; unfillable triggers are recorded with their reason and
do not count), then grading refreshes marks and closes pairs on T8's
falsifiers — the name's band state exits (above_bull on the latest
stamped sheet) or its guide turns cut — at expiry (settled at intrinsic
from the final close), and at trial end (12 months from the first pair).

The frozen gate, read by trial_summary and never acted on: at the first
4 opened pairs (or 12 months), mean carry drag over 3.5%/yr of
delta-notional or mean delta delivery under 80% kills the vehicle; a
pass extends the trial to 8 pairs. Promotion to live capital is Kevin's
separate call.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

PAIRS = "leaps_shadow_pairs"
CROSSINGS = "band_crossings"
IDEA_ID = 81
TAG = "leaps-trial"

PREMIUM_CAP = 10_000.0
DELTA_LO, DELTA_HI, DELTA_TARGET = 0.75, 0.85, 0.80
EXPIRY_MIN, EXPIRY_MAX, EXPIRY_TARGET = 365, 550, 455
EXTRINSIC_MAX_SHARE = 0.15
MAX_SPREAD_PCT = 25.0               # the options plumbing's own tradability bar
ROLL_DTE = 180
DRAG_KILL_PCT = 3.5
DELIVERY_KILL = 0.80
GATE_PAIRS = 4
EXTENDED_PAIRS = 8
TRIAL_DAYS = 365


# ── pure: contract selection and sizing ──────────────────────────────────────

def bs_call_delta(spot: float, strike: float, iv: float, years: float) -> float:
    """Black-Scholes call delta (r = 0, no dividends) — the fallback when
    the snapshot carries an IV but no greeks."""
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / (iv * math.sqrt(years))
    return 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))


def _expiry_of(contract: dict) -> date:
    return date.fromisoformat(contract["expiration_date"])


def select_leaps(contracts: list[dict], snapshots: dict, spot: float, today: date,
                 quote_fn=None) -> tuple[dict | None, str | None]:
    """The Spec F contract for one trigger, or (None, reason).

    Expiry: listed calls 365–550 days out, nearest 455 (ties to the later
    expiry, the codebase convention). Strike: delta nearest 0.80 inside
    [0.75, 0.85] — snapshot greeks first, BS from the snapshot IV as the
    fallback. Entry at the ask; extrinsic over 15% of the ask vetoes the
    trigger."""
    in_window = [c for c in contracts
                 if EXPIRY_MIN <= (_expiry_of(c) - today).days <= EXPIRY_MAX]
    if not in_window:
        return None, "no_expiry_in_window"
    expiry = min({_expiry_of(c) for c in in_window},
                 key=lambda e: (abs((e - today).days - EXPIRY_TARGET),
                                -(e - today).days))
    years = (expiry - today).days / 365.0
    candidates = []
    for c in in_window:
        if _expiry_of(c) != expiry:
            continue
        snap = snapshots.get(c["symbol"]) or {}
        delta = snap.get("delta")
        if delta is None and snap.get("iv"):
            delta = bs_call_delta(spot, float(c["strike_price"]), float(snap["iv"]), years)
        if delta is None or not (DELTA_LO <= float(delta) <= DELTA_HI):
            continue
        candidates.append((abs(float(delta) - DELTA_TARGET), float(c["strike_price"]),
                           c, float(delta), snap))
    if not candidates:
        return None, "no_contract_in_delta_band"
    candidates.sort(key=lambda t: (t[0], t[1]))
    _, strike, contract, delta, snap = candidates[0]
    bid, ask = snap.get("bid"), snap.get("ask")
    if (bid is None or ask is None) and quote_fn is not None:
        quoted = quote_fn(contract["symbol"])
        if quoted is not None:
            bid, ask = quoted
    if bid is None or ask is None or float(bid) <= 0 or float(ask) <= 0 or float(ask) < float(bid):
        return None, "no_quote"
    bid, ask = float(bid), float(ask)
    mid = (bid + ask) / 2
    if mid <= 0 or (ask - bid) / mid * 100 > MAX_SPREAD_PCT:
        return None, "no_quote"
    extrinsic = ask - max(spot - strike, 0.0)
    if extrinsic > EXTRINSIC_MAX_SHARE * ask:
        return None, "extrinsic_over_cap"
    return {"occ_symbol": contract["symbol"], "strike": strike, "expiry": expiry,
            "bid": bid, "mid": mid, "ask": ask, "delta": delta,
            "iv": snap.get("iv"), "extrinsic": extrinsic}, None


def size_pair(ask: float, delta: float, spot: float,
              trigger_price: float) -> tuple[dict | None, str | None]:
    """Contracts under the $10k premium cap; the share line at identical
    delta-notional, entered at the crossing row's trigger price."""
    if ask * 100 > PREMIUM_CAP:
        return None, "single_contract_over_cap"
    contracts = max(1, int(PREMIUM_CAP // (ask * 100)))
    delta_notional = contracts * 100 * delta * spot
    return {"contracts": contracts, "premium_total": contracts * ask * 100,
            "delta_notional": delta_notional,
            "share_shares": delta_notional / trigger_price,
            "share_entry_price": trigger_price}, None


# ── pure: marks and the trial summary ────────────────────────────────────────

def _dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def pair_marks(pair: dict, *, leaps_mid: float | None, share_price: float | None,
               marked_at: datetime) -> dict:
    """The nightly mark patch for one open pair. A missing or too-wide
    quote leaves the LEAPS leg unmarked (null + stale) — never a
    fabricated number; P&L derived from it is left at its last value."""
    expiry = date.fromisoformat(str(pair["expiry"])[:10])
    dte = (expiry - marked_at.date()).days
    patch: dict = {"marked_at": marked_at.isoformat(), "dte": dte,
                   "roll_flag": dte <= ROLL_DTE}
    if share_price is not None:
        patch["share_price"] = share_price
        patch["share_pnl"] = (share_price - float(pair["share_entry_price"])) \
            * float(pair["share_shares"])
    if leaps_mid is None:
        patch["leaps_mid"] = None
        patch["mark_stale"] = True
        return patch
    patch["leaps_mid"] = leaps_mid
    patch["mark_stale"] = False
    contracts = int(pair["contracts"])
    leaps_pnl = (leaps_mid - float(pair["entry_ask"])) * contracts * 100
    patch["leaps_pnl"] = leaps_pnl
    if share_price is not None and patch.get("share_pnl") is not None:
        spot_now = share_price
        extrinsic_now = max(leaps_mid - max(spot_now - float(pair["strike"]), 0.0), 0.0)
        decay = float(pair["extrinsic_at_entry"]) * contracts * 100 - extrinsic_now * contracts * 100
        spread_paid = (float(pair["entry_ask"]) - float(pair["entry_mid"])) * contracts * 100
        years = max((_dt(marked_at) - _dt(pair["opened_at"])).days, 1) / 365.0
        patch["carry_drag_pct"] = (decay + spread_paid) / float(pair["delta_notional"]) / years * 100
        share_cash = float(pair["share_shares"]) * float(pair["share_entry_price"])
        share_ret = patch["share_pnl"] / share_cash if share_cash else 0.0
        leaps_ret = leaps_pnl / float(pair["premium_total"]) if pair["premium_total"] else 0.0
        patch["delta_delivered"] = (leaps_ret / share_ret) if share_ret != 0 else None
    return patch


def _cohort_read(cohort: list[dict]) -> dict:
    """One gate cohort's verdict inputs: the two frozen means over the
    cohort's rows that carry them."""
    drags = [float(r["carry_drag_pct"]) for r in cohort if r.get("carry_drag_pct") is not None]
    deliveries = [float(r["delta_delivered"]) for r in cohort
                  if r.get("delta_delivered") is not None]
    return {"mean_drag": sum(drags) / len(drags) if drags else None,
            "mean_delivery": sum(deliveries) / len(deliveries) if deliveries else None}


def _cohort_verdict(read: dict) -> tuple[str | None, str | None]:
    """(state, reason) for one judged cohort: a kill on either bar, an
    insufficient-data read when a metric the gate judges is missing (a
    gate never passes on absent evidence), else a pass."""
    if read["mean_drag"] is not None and read["mean_drag"] > DRAG_KILL_PCT:
        return "killed", (f"mean carry drag {read['mean_drag']:.2f}%/yr over the "
                          f"{DRAG_KILL_PCT}%/yr bar")
    if read["mean_delivery"] is not None and read["mean_delivery"] < DELIVERY_KILL:
        return "killed", (f"mean delta delivery {read['mean_delivery']:.2f} under "
                          f"the {DELIVERY_KILL:.0%} bar")
    if read["mean_drag"] is None or read["mean_delivery"] is None:
        return "insufficient_data", ("the gate's metrics are incomplete for this "
                                     "cohort — no verdict until both are marked")
    return "pass", None


def trial_summary(rows: list[dict], *, now: datetime) -> dict:
    """The frozen gate read over the trial's rows. A read, never an
    actor: promotion is Kevin's call.

    The gate judges a FROZEN cohort — the first GATE_PAIRS opened pairs,
    or every pair opened by the 12-month cutoff when fewer arrived — so
    a later pair can never rewrite the verdict. A pass extends the trial
    to EXTENDED_PAIRS; that extension cohort (pairs 5–8) is read
    separately under gate["extension"] and never mutates the first
    verdict."""
    opened = [r for r in rows if r.get("status") != "unfilled"]
    unfilled = [r for r in rows if r.get("status") == "unfilled"]
    opened.sort(key=lambda r: (_dt(r["opened_at"]), r.get("id") or 0))
    drags = [float(r["carry_drag_pct"]) for r in opened if r.get("carry_drag_pct") is not None]
    deliveries = [float(r["delta_delivered"]) for r in opened
                  if r.get("delta_delivered") is not None]
    premium_cash = sum(float(r["premium_total"] or 0) for r in opened)
    share_cash = sum(float(r["share_shares"] or 0) * float(r["share_entry_price"] or 0)
                     for r in opened)
    trial_start = _dt(opened[0]["opened_at"]) if opened else None
    months_hit = trial_start is not None and now >= trial_start + timedelta(days=TRIAL_DAYS)
    judged = len(opened) >= GATE_PAIRS or months_hit
    mean_drag = sum(drags) / len(drags) if drags else None
    mean_delivery = sum(deliveries) / len(deliveries) if deliveries else None
    gate: dict = {"state": "waiting", "judged": False, "pairs": len(opened),
                  "needed": GATE_PAIRS, "reason": None, "extension": None}
    if opened:
        gate["state"] = "open"
    if judged:
        gate["judged"] = True
        read = _cohort_read(opened[:GATE_PAIRS])
        gate["cohort_pairs"] = min(len(opened), GATE_PAIRS)
        gate["mean_carry_drag_pct"] = read["mean_drag"]
        gate["mean_delta_delivered"] = read["mean_delivery"]
        state, reason = _cohort_verdict(read)
        gate["state"], gate["reason"] = state, reason
        if state == "pass" and len(opened) >= EXTENDED_PAIRS:
            ext_state, ext_reason = _cohort_verdict(
                _cohort_read(opened[GATE_PAIRS:EXTENDED_PAIRS]))
            gate["extension"] = {"state": ext_state, "reason": ext_reason}
            if ext_state == "pass":
                gate["state"] = "complete"
    return {"pairs_opened": len(opened),
            "pairs_open": sum(1 for r in opened if r["status"] == "open"),
            "pairs_closed": sum(1 for r in opened if r["status"] in ("closed", "expired")),
            "unfilled": len(unfilled),
            "mean_carry_drag_pct": mean_drag,
            "mean_delta_delivered": mean_delivery,
            "premium_cash": premium_cash,
            "share_cash": share_cash,
            "premium_pct_of_share_cash": (premium_cash / share_cash * 100
                                          if share_cash else None),
            "trial_start": trial_start.isoformat() if trial_start else None,
            "gate": gate}


# ── store reads ──────────────────────────────────────────────────────────────

def _rows(client) -> list[dict]:
    return (client.table(PAIRS).select("*").eq("idea_id", IDEA_ID)
            .order("opened_at").execute().data) or []


def t8_symbols(client) -> set[str]:
    """The T8 sleeve's symbols, read live from the Portfolio Check
    config the way valuation/candidates.py reads it."""
    from tradehub.portfolio.portfolio_check import load_config

    config = load_config(client)
    sleeve = (config.get("sleeves") or {}).get("t8_ai") or {}
    return {str(s).upper() for s in sleeve.get("symbols") or []}


def panel(client, idea: dict) -> dict:
    """The idea page's Spec F payload: the trial summary, then the pairs
    and the unfilled triggers."""
    rows = _rows(client)
    return {"idea_id": idea["id"],
            "summary": trial_summary(rows, now=datetime.now(UTC)),
            "pairs": [r for r in rows if r.get("status") != "unfilled"],
            "unfilled": [r for r in rows if r.get("status") == "unfilled"]}


# ── intake ───────────────────────────────────────────────────────────────────

def _default_providers(today: date) -> dict:
    from tradehub.portfolio import alpaca_paper, options

    def contracts_fn(ticker, _today):
        return options.fetch_contracts_window(
            ticker, "call", _today + timedelta(days=EXPIRY_MIN),
            _today + timedelta(days=EXPIRY_MAX))

    def spot_fn(ticker):
        try:
            return float(alpaca_paper.latest_price(ticker))
        except Exception:  # noqa: BLE001 -- no price: the crossing price stands
            return None

    return {"contracts_fn": contracts_fn,
            "snapshots_fn": options.fetch_snapshots,
            "quote_fn": options.fetch_quote,
            "spot_fn": spot_fn,
            "t8_fn": t8_symbols}


def run_intake(client, *, now: datetime | None = None, contracts_fn=None,
               snapshots_fn=None, quote_fn=None, spot_fn=None, t8_fn=None) -> dict:
    """Consume qualifying crossings: open a pair, record an unfilled
    trigger, or log a repeat crossing as an event on the open pair.
    Idempotent — consumed crossing ids are never reprocessed."""
    now = now or datetime.now(UTC)
    today = now.date()
    defaults = _default_providers(today)
    contracts_fn = contracts_fn or defaults["contracts_fn"]
    snapshots_fn = snapshots_fn or defaults["snapshots_fn"]
    quote_fn = quote_fn or defaults["quote_fn"]
    spot_fn = spot_fn or defaults["spot_fn"]
    t8 = (t8_fn or defaults["t8_fn"])(client)

    rows = _rows(client)
    consumed = {r.get("crossing_id") for r in rows}
    open_by_ticker = {r["ticker"]: r for r in rows if r.get("status") == "open"}
    evented = {e.get("crossing_id") for r in rows
               for e in (r.get("events") or [])}
    opened_rows = [r for r in rows if r.get("status") != "unfilled"]
    trial_end = (min((_dt(r["opened_at"]) for r in opened_rows),
                     default=None))
    if trial_end is not None:
        trial_end = trial_end + timedelta(days=TRIAL_DAYS)
    crossings: list[dict] = []
    offset = 0
    while True:  # page past the consumed prefix; never just the oldest page
        page = (client.table(CROSSINGS).select("*").order("created_at")
                .range(offset, offset + 999).execute().data) or []
        crossings.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    out = {"opened": 0, "unfilled": 0, "events": 0, "errors": 0}
    for crossing in crossings:
        if crossing.get("zone") not in ("bear", "base"):
            continue
        if crossing.get("action") not in ("starter", "add"):
            continue
        ticker = str(crossing.get("ticker") or "").upper()
        if ticker not in t8 or crossing.get("id") in consumed \
                or crossing.get("id") in evented:
            continue  # already a pair's trigger, or already rode as an event
        if trial_end is not None and crossing.get("created_at") is not None \
                and _dt(crossing["created_at"]) > trial_end:
            continue  # fired after the trial closed; not a trial trigger
        if ticker in open_by_ticker:
            pair = open_by_ticker[ticker]
            if crossing["id"] not in evented:
                events = list(pair.get("events") or []) + [{
                    "type": "trigger", "crossing_id": crossing["id"],
                    "at": crossing.get("created_at"), "zone": crossing.get("zone"),
                    "action": crossing.get("action"), "book": crossing.get("book")}]
                client.table(PAIRS).update({"events": events}).eq("id", pair["id"]).execute()
                pair["events"] = events
                evented.add(crossing["id"])
                out["events"] += 1
            continue
        try:
            kind = _open_from_crossing(
                client, crossing, now=now, today=today,
                contracts_fn=contracts_fn, snapshots_fn=snapshots_fn,
                quote_fn=quote_fn, spot_fn=spot_fn, open_by_ticker=open_by_ticker)
        except Exception:  # noqa: BLE001 -- a failed read leaves the crossing
            out["errors"] += 1  # unconsumed; the next pass retries it
            continue
        out[kind] += 1
        consumed.add(crossing.get("id"))
    return out


def _open_from_crossing(client, crossing: dict, *, now: datetime, today: date,
                        contracts_fn, snapshots_fn, quote_fn, spot_fn,
                        open_by_ticker: dict) -> str:
    ticker = str(crossing["ticker"]).upper()
    trigger_price = float(crossing["price"])
    row: dict = {"idea_id": IDEA_ID, "crossing_id": crossing["id"], "ticker": ticker,
                 "opened_at": now.isoformat(), "status": "unfilled",
                 "snapshot_id": crossing.get("snapshot_id"),
                 "zone": crossing.get("zone"), "action": crossing.get("action"),
                 "bear": crossing.get("bear"), "base": crossing.get("base"),
                 "bull": crossing.get("bull"),
                 "guide_status": crossing.get("guide_status"),
                 "trigger_price": trigger_price, "events": []}
    spot = spot_fn(ticker) or trigger_price
    contracts = contracts_fn(ticker, today)
    symbols = [c["symbol"] for c in contracts]
    snapshots = snapshots_fn(symbols) if symbols else {}
    sel, reason = select_leaps(contracts, snapshots, spot, today, quote_fn=quote_fn)
    sized = None
    if sel is not None:
        sized, reason = size_pair(sel["ask"], sel["delta"], spot, trigger_price)
    if sel is None or sized is None:
        row["close_reason"] = reason
        client.table(PAIRS).insert(row).execute()
        return "unfilled"
    row.update({"status": "open", "occ_symbol": sel["occ_symbol"],
                "strike": sel["strike"], "expiry": sel["expiry"].isoformat(),
                "entry_bid": sel["bid"], "entry_mid": sel["mid"],
                "entry_ask": sel["ask"], "delta_at_entry": sel["delta"],
                "extrinsic_at_entry": sel["extrinsic"], "iv_at_entry": sel["iv"],
                "spot_at_entry": spot, **sized})
    try:
        inserted = client.table(PAIRS).insert(row).execute()
    except Exception:
        # A concurrent intake won the one-open-pair race for this ticker:
        # this crossing rides as an event on the pair that exists.
        rival = next((r for r in _rows(client)
                      if r["ticker"] == ticker and r.get("status") == "open"), None)
        if rival is None:
            raise
        events = list(rival.get("events") or []) + [{
            "type": "trigger", "crossing_id": crossing["id"],
            "at": crossing.get("created_at"), "zone": crossing.get("zone"),
            "action": crossing.get("action"), "book": crossing.get("book")}]
        client.table(PAIRS).update({"events": events}).eq("id", rival["id"]).execute()
        open_by_ticker[ticker] = rival
        return "events"
    saved = (inserted.data or [row])[0]
    open_by_ticker[ticker] = saved
    return "opened"


# ── grading ──────────────────────────────────────────────────────────────────

def run_grading(client, *, now: datetime | None = None, mid_fn=None,
                spot_fn=None, sheets_fn=None) -> dict:
    """One nightly pass over the open pairs: refresh marks, then close on
    expiry (intrinsic from the final close), on the name's band state
    exiting (above_bull on the latest stamped sheet), on its guide
    turning cut, or at trial end. The roll flag is set by the marks; a
    roll itself is Kevin's call, never automatic."""
    from tradehub.portfolio import alpaca_paper, options
    from tradehub.valuation import band_crossing
    from tradehub.valuation import store as valuation_store

    now = now or datetime.now(UTC)
    mid_fn = mid_fn or options.fetch_mid
    if spot_fn is None:
        def spot_fn(ticker):  # noqa: F811 -- the real read, fail-soft
            try:
                return float(alpaca_paper.latest_price(ticker))
            except Exception:  # noqa: BLE001
                return None
    sheets_fn = sheets_fn or (lambda c: valuation_store.latest_sheets(c))
    sheets = {s["ticker"]: s for s in sheets_fn(client)}
    rows = _rows(client)
    opened = [r for r in rows if r.get("status") != "unfilled"]
    trial_start = min((_dt(r["opened_at"]) for r in opened), default=None)
    out = {"marked": 0, "closed": 0}
    for pair in opened:
        if pair.get("status") != "open":
            continue
        price = spot_fn(pair["ticker"])
        expiry = date.fromisoformat(str(pair["expiry"])[:10])
        if now.date() >= expiry:
            final = price if price is not None else pair.get("share_price")
            patch = {"status": "expired", "close_reason": "expired",
                     "closed_at": now.isoformat(), "marked_at": now.isoformat(),
                     "dte": (expiry - now.date()).days, "roll_flag": True}
            if final is not None:
                value = max(final - float(pair["strike"]), 0.0) * int(pair["contracts"]) * 100
                patch["share_price"] = final
                patch["share_pnl"] = (final - float(pair["share_entry_price"])) \
                    * float(pair["share_shares"])
                patch["leaps_pnl"] = value - float(pair["premium_total"])
            client.table(PAIRS).update(patch).eq("id", pair["id"]).execute()
            out["closed"] += 1
            continue
        patch = pair_marks(pair, leaps_mid=mid_fn(pair["occ_symbol"]),
                           share_price=price, marked_at=now)
        sheet = sheets.get(pair["ticker"])
        reason = None
        if sheet is not None:
            if sheet.get("bands") and price is not None \
                    and band_crossing.zone_of(price, sheet["bands"]) == "above_bull":
                reason = "above_bull"
            elif band_crossing.guide_status_of(sheet)[0] == "cut":
                # The guide leg needs no price: a cut closes the pair even
                # on a night the spot read fails.
                reason = "guide_cut"
        if reason is None and trial_start is not None \
                and now >= trial_start + timedelta(days=TRIAL_DAYS):
            reason = "trial_end"
        if reason is not None:
            patch.update({"status": "closed", "close_reason": reason,
                          "closed_at": now.isoformat()})
            out["closed"] += 1
        client.table(PAIRS).update(patch).eq("id", pair["id"]).execute()
        out["marked"] += 1
    return out
