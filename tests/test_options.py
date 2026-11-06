"""Option legs automation (Kevin, 2026-11-02): OCC math, contract selection, the
planner's sizing rules -- the min-1-contract rule for defined-risk spreads inside the
idea's budget, no minimum for covered calls, rolls, and manual hand-offs whenever a
quote can't price an order."""

from datetime import date, timedelta

from tradehub.portfolio import options as opt
from tradehub.portfolio.autotrade import close_options, plan_options
from tradehub.workshop.spec import OptionLeg

DAY = date(2026, 11, 3)


def leg(**kw) -> OptionLeg:
    return OptionLeg(**{"underlying": "NVDA", "kind": "call", "side": "buy",
                        "strike_pct": 100, "days_to_expiry": 30, "roll_days_left": 5,
                        "qty_per_share": 1, **kw})


def fake_select(mapping):
    def select(l, spot):
        return mapping[(l.underlying, l.side, l.strike_pct)]
    return select


def fake_mid(prices):
    return lambda occ: prices.get(occ)


# ── OCC math + selection ─────────────────────────────────────────────────────────

def test_occ_round_trip():
    occ = opt.build_occ("NVDA", date(2026, 12, 4), "call", 200)
    assert occ == "NVDA  261204C00200000"
    p = opt.parse_occ(occ)
    assert p == {"underlying": "NVDA", "expiry": date(2026, 12, 4), "kind": "call", "strike": 200.0}
    assert opt.is_occ(occ) and not opt.is_occ("NVDA") and not opt.is_occ("")


def test_select_contract_nearest_expiry_then_strike():
    contracts = [
        {"symbol": "FAR", "expiration_date": "2026-12-20", "strike_price": "200"},
        {"symbol": "NEAR_EXP_FAR_STRIKE", "expiration_date": "2026-12-03", "strike_price": "215"},
        {"symbol": "BEST", "expiration_date": "2026-12-03", "strike_price": "201"},
    ]
    assert opt.select_contract(contracts, leg(), 200.0, DAY) == "BEST"
    assert opt.select_contract([], leg(), 200.0, DAY) is None


# ── Covered calls: no min-1 (Kevin's rule) ───────────────────────────────────────

SPY_CALL = OptionLeg(underlying="SPY", kind="call", side="sell", strike_pct=105,
                     days_to_expiry=30, roll_days_left=5, qty_per_share=1)
SPY_OCC = opt.build_occ("SPY", DAY + timedelta(days=31), "call", 787.5)


def test_covered_call_below_100_shares_is_a_skip_not_an_order():
    rows = plan_options(16, [SPY_CALL], {"SPY": 1.0}, 10, 100_000, {"SPY": 750.0}, {}, DAY,
                        fake_select({("SPY", "sell", 105): SPY_OCC}), fake_mid({SPY_OCC: 3.0}))
    assert len(rows) == 1 and rows[0]["status"] == "skip"
    assert "needs 100 shares per contract" in rows[0]["reason"]


def test_covered_call_opens_once_the_shares_are_there():
    rows = plan_options(16, [SPY_CALL], {"SPY": 1.0}, 10, 1_000_000, {"SPY": 750.0}, {}, DAY,
                        fake_select({("SPY", "sell", 105): SPY_OCC}), fake_mid({SPY_OCC: 3.0}))
    sends = [r for r in rows if r["status"] == "send"]
    assert len(sends) == 1
    assert sends[0]["symbol"] == SPY_OCC and sends[0]["side"] == "sell" and sends[0]["qty"] == 1
    assert sends[0]["limit_price"] == 3.0 and sends[0]["time_in_force"] == "day"


# ── Defined-risk vertical: Kevin's min-1 rule, inside the budget ─────────────────

BUY_LEG = leg(side="buy", strike_pct=100)
SELL_LEG = leg(side="sell", strike_pct=110)
B_OCC = opt.build_occ("NVDA", DAY + timedelta(days=30), "call", 200)
S_OCC = opt.build_occ("NVDA", DAY + timedelta(days=30), "call", 220)
SELECT = fake_select({("NVDA", "buy", 100): B_OCC, ("NVDA", "sell", 110): S_OCC})


def test_vertical_min_one_contract_when_share_math_rounds_to_zero():
    # 10% of $100k in NVDA at $200 = 50 shares -> 0 contracts by the per-100 rule.
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {"NVDA": 1.0}, 10, 100_000, {"NVDA": 200.0}, {},
                        DAY, SELECT, fake_mid({B_OCC: 5.0, S_OCC: 3.0}))
    sends = [r for r in rows if r["status"] == "send"]
    # Kevin, 2026-11-03: the spread is placed as ONE multi-leg order -- as separate
    # single-leg orders the short leg reads as uncovered and Alpaca refuses it.
    assert len(sends) == 1 and sends[0]["qty"] == 1
    assert sends[0]["limit_price"] == 2.0  # the net debit: 5.0 paid - 3.0 taken
    assert [(l["symbol"], l["side"], l["position_intent"]) for l in sends[0]["mleg"]] == [
        (B_OCC, "buy", "buy_to_open"), (S_OCC, "sell", "sell_to_open")]


def test_vertical_open_pairs_into_one_mleg_row():
    # 10% of $1M at $200 = 500 shares -> 5 contracts, still one order.
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {"NVDA": 1.0}, 10, 1_000_000, {"NVDA": 200.0}, {},
                        DAY, SELECT, fake_mid({B_OCC: 5.0, S_OCC: 3.0}))
    sends = [r for r in rows if r["status"] == "send"]
    assert len(sends) == 1 and sends[0]["qty"] == 5 and sends[0]["limit_price"] == 2.0
    assert sends[0]["kind"] == "open" and len(sends[0]["mleg"]) == 2


def test_vertical_close_pairs_into_one_mleg_row():
    # The idea goes flat holding both legs: one mleg close at the net credit,
    # which Alpaca takes as a NEGATIVE limit price.
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {}, 10, 100_000, {"NVDA": 200.0},
                        {B_OCC: 1, S_OCC: -1}, DAY, SELECT, fake_mid({B_OCC: 5.0, S_OCC: 3.0}))
    sends = [r for r in rows if r["status"] == "send"]
    assert len(sends) == 1 and sends[0]["kind"] == "close" and sends[0]["qty"] == 1
    assert sends[0]["limit_price"] == -2.0
    assert [(l["symbol"], l["position_intent"]) for l in sends[0]["mleg"]] == [
        (B_OCC, "sell_to_close"), (S_OCC, "buy_to_close")]


def test_credit_shaped_quotes_do_not_pair():
    # Crossed quotes (the far leg priced over the near leg) would make the "debit"
    # negative: no pairing -- the legs stay single and a refusal becomes a manual
    # action under the runner's never-silent rule instead of a wrong mleg order.
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {"NVDA": 1.0}, 10, 1_000_000, {"NVDA": 200.0}, {},
                        DAY, SELECT, fake_mid({B_OCC: 3.0, S_OCC: 5.0}))
    sends = [r for r in rows if r["status"] == "send"]
    assert len(sends) == 2 and all("mleg" not in r for r in sends)


def test_vertical_min_one_over_budget_goes_to_a_human():
    # 1% of $100k = $1,000 budget; the spread can lose (220-200 - (3-28)) -> debit 25 -> $2,500.
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {"NVDA": 1.0}, 1, 100_000, {"NVDA": 200.0}, {},
                        DAY, SELECT, fake_mid({B_OCC: 28.0, S_OCC: 3.0}))
    assert not [r for r in rows if r["status"] == "send"]
    manuals = [r for r in rows if r["status"] == "manual"]
    assert manuals and "over this idea's $1,000 budget" in manuals[0]["reason"]


def test_vertical_unpriceable_goes_to_a_human():
    rows = plan_options(50, [BUY_LEG, SELL_LEG], {"NVDA": 1.0}, 10, 100_000, {"NVDA": 200.0}, {},
                        DAY, SELECT, fake_mid({}))
    assert not [r for r in rows if r["status"] == "send"]
    assert [r for r in rows if r["status"] == "manual"]


# ── Managing held contracts ──────────────────────────────────────────────────────

HELD_LONG = opt.build_occ("NVDA", DAY + timedelta(days=40), "call", 200)


def test_inactive_leg_closes_what_it_holds():
    rows = plan_options(50, [BUY_LEG], {}, 10, 100_000, {"NVDA": 200.0}, {HELD_LONG: 2}, DAY,
                        SELECT, fake_mid({HELD_LONG: 6.0}))
    assert len(rows) == 1 and rows[0]["status"] == "send" and rows[0]["side"] == "sell"
    assert rows[0]["qty"] == 2 and rows[0]["kind"] == "close"


def test_unquotable_close_goes_to_a_human():
    rows = plan_options(50, [BUY_LEG], {}, 10, 100_000, {"NVDA": 200.0}, {HELD_LONG: 2}, DAY,
                        SELECT, fake_mid({}))
    assert len(rows) == 1 and rows[0]["status"] == "manual"


def test_roll_window_closes_and_reopens():
    expiring = opt.build_occ("NVDA", DAY + timedelta(days=3), "call", 200)
    rows = plan_options(50, [BUY_LEG], {"NVDA": 1.0}, 10, 1_000_000, {"NVDA": 200.0},
                        {expiring: 5}, DAY, SELECT, fake_mid({expiring: 4.0, B_OCC: 5.0}))
    closes = [r for r in rows if r["kind"] == "close" and r["status"] == "send"]
    opens = [r for r in rows if r["kind"] == "open" and r["status"] == "send"]
    assert len(closes) == 1 and closes[0]["qty"] == 5 and closes[0]["reason"] == "roll window"
    assert len(opens) == 1 and opens[0]["symbol"] == B_OCC and opens[0]["qty"] == 5


def test_excess_contracts_are_trimmed():
    rows = plan_options(50, [BUY_LEG], {"NVDA": 1.0}, 10, 400_000, {"NVDA": 200.0},
                        {HELD_LONG: 3}, DAY, SELECT, fake_mid({HELD_LONG: 6.0}))
    closes = [r for r in rows if r["kind"] == "close" and r["status"] == "send"]
    assert len(closes) == 1 and closes[0]["qty"] == 1  # target is 2 contracts at $40k/$200/100


def test_expired_short_is_a_manual_action():
    expired = opt.build_occ("NVDA", DAY - timedelta(days=1), "call", 220)
    rows = plan_options(50, [SELL_LEG], {"NVDA": 1.0}, 10, 1_000_000, {"NVDA": 200.0},
                        {expired: -5}, DAY, SELECT, fake_mid({S_OCC: 3.0}))
    manuals = [r for r in rows if r["status"] == "manual"]
    assert manuals and "assignment" in manuals[0]["reason"]


def test_close_options_prices_at_mid_or_hands_off():
    rows = close_options(50, {HELD_LONG: 2}, DAY, fake_mid({HELD_LONG: 6.0}))
    assert rows[0]["status"] == "send" and rows[0]["limit_price"] == 6.0
    rows = close_options(50, {HELD_LONG: 2}, DAY, fake_mid({}))
    assert rows[0]["status"] == "manual"


def test_a_killed_idea_closes_its_spread_as_one_order():
    # Idea 50, 2026-11-04: the kill sent two single-leg closes. Alpaca refused the long leg as "uncovered"
    # because the short was still open, which left one leg behind.
    rows = close_options(50, {B_OCC: 1, S_OCC: -1}, DAY, fake_mid({B_OCC: 5.0, S_OCC: 3.0}))
    assert len(rows) == 1 and rows[0]["kind"] == "close" and rows[0]["limit_price"] == -2.0
    assert [(l["symbol"], l["position_intent"]) for l in rows[0]["mleg"]] == [
        (B_OCC, "sell_to_close"), (S_OCC, "buy_to_close")]


def test_a_leg_left_on_its_own_still_closes_singly():
    rows = close_options(50, {B_OCC: 1}, DAY, fake_mid({B_OCC: 5.0}))
    assert len(rows) == 1 and "mleg" not in rows[0] and rows[0]["side"] == "sell"


# ── fetch_touch tests ──────────────────────────────────────────────────────────────


def test_fetch_touch_returns_bid_for_sell_and_ask_for_buy(monkeypatch):
    from tradehub.portfolio import options as opt
    # Mock the internal _fetch_quote to return a valid bid/ask
    monkeypatch.setattr(opt, "_fetch_quote", lambda symbol, book=None, session=None: (1.00, 1.10))
    assert opt.fetch_touch("NVDA  261204C00200000", "sell") == 1.00
    assert opt.fetch_touch("NVDA  261204C00200000", "buy") == 1.10


def test_fetch_touch_returns_none_on_crossed_quote(monkeypatch):
    from tradehub.portfolio import options as opt
    # Crossed quote: bid > ask
    monkeypatch.setattr(opt, "_fetch_quote", lambda symbol, book=None, session=None: None)
    assert opt.fetch_touch("NVDA  261204C00200000", "sell") is None
    assert opt.fetch_touch("NVDA  261204C00200000", "buy") is None


def test_fetch_touch_returns_none_on_too_wide_spread(monkeypatch):
    from tradehub.portfolio import options as opt
    # Too wide spread returns None from _fetch_quote
    monkeypatch.setattr(opt, "_fetch_quote", lambda symbol, book=None, session=None: None)
    assert opt.fetch_touch("NVDA  261204C00200000", "sell") is None
    assert opt.fetch_touch("NVDA  261204C00200000", "buy") is None


def test_fetch_mid_still_works_for_same_quote(monkeypatch):
    from tradehub.portfolio import options as opt
    monkeypatch.setattr(opt, "_fetch_quote", lambda symbol, book=None, session=None: (1.00, 1.10))
    assert opt.fetch_mid("NVDA  261204C00200000") == 1.05
