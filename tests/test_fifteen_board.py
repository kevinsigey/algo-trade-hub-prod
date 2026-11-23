"""Tests for the Strategies redesign board (tradehub/fifteen_board.py).

The spec's required test is the account replay: a known win/loss
sequence gives a known balance, the depth cap applies, and bust is
detected. The rest pins the row assembly: per-series stats from a
model's trades, the paired deltas against the live rule, the progress
legs, and the board's sorting (best first, under-10-trades models last).
"""

from tradehub.fifteen_board import model_row, replay_account, sort_board


def _t(cost, pnl, ask_size=None, at="2026-11-18T15:05:00+00:00", target="kalshi:X-1"):
    return {"cost": cost, "pnl": pnl, "ask_size": ask_size, "frozen_at": at,
            "target": target, "side": "yes"}


def test_account_replay_known_sequence():
    # Start $20. Trade 1: stake $2 at cost 0.50 -> 4 contracts, pnl +0.40
    # each -> +$1.60, balance 21.60. Trade 2: stake $2.16 at cost 0.40 ->
    # 5 contracts, pnl -0.45 each -> -$2.25, balance 19.35.
    account = replay_account([_t(0.50, 0.40), _t(0.40, -0.45)])
    assert account["balance"] == 19.35
    assert account["bust"] is False
    assert account["curve"] == [20.0, 21.6, 19.35]
    assert account["drawdown"] == 2.25


def test_account_replay_depth_cap_applies():
    # Stake $2 at cost 0.25 would buy 8, but only 3 were on offer.
    account = replay_account([_t(0.25, 0.60, ask_size=3)])
    assert account["balance"] == 21.80   # 20 + 3 * 0.60


def test_account_replay_bust_when_one_contract_is_unaffordable():
    # Bust is balance < cost (Claude's review): the account always buys
    # at least one contract while it can afford one, so a run of
    # near-full losses at 0.90 walks it under 0.90 itself before it stops.
    account = replay_account([_t(0.90, -0.93) for _ in range(30)])
    assert account["bust"] is True
    assert account["balance"] < 0.90
    assert len(account["curve"]) < 31    # bust ends the replay early


def test_account_replay_zero_depth_skips_not_busts():
    # $20 with zero depth on trade one: the trade is skipped and the
    # replay carries on (Claude's review; the old code read this as bust).
    account = replay_account([_t(0.50, 0.40, ask_size=0), _t(0.50, 0.40)])
    assert account["bust"] is False
    assert account["trades_taken"] == 1
    assert account["balance"] == 21.60   # only the second trade ran: 4 contracts


def test_account_replay_buys_one_when_the_stake_alone_cannot(monkeypatch):
    # $8.90 at 90c: the 10% stake (0.89) cannot buy a contract, but the
    # balance can -- max(1, floor(stake / cost)) buys one (Claude's review).
    import tradehub.fifteen_board as board

    monkeypatch.setattr(board, "ACCOUNT_START", 8.90)
    account = replay_account([_t(0.90, 0.10)])
    assert account["bust"] is False
    assert account["balance"] == 9.00


def test_account_replay_busts_only_below_one_contracts_cost(monkeypatch):
    import tradehub.fifteen_board as board

    monkeypatch.setattr(board, "ACCOUNT_START", 0.50)
    account = replay_account([_t(0.90, 0.10)])
    assert account["bust"] is True
    assert account["trades_taken"] == 0


def test_model_row_stats_and_progress():
    trades = [_t(0.40, 0.50, at=f"2026-11-1{d}T15:05:00+00:00", target=f"kalshi:X-{d}")
              for d in range(5)]
    live = {t["target"]: 0.10 for t in trades}
    row = model_row("v-test", "Test", "KXWTI15M", trades, live, fill_short=2, needed=100)
    assert row["trades"] == 5 and row["net_cents"] == 50.0
    assert row["fill_short"] == 2
    assert row["progress"] == {"n": 5, "needed": 100,
                               "legs": {"n": False, "low95": True, "paired": True}}
    assert row["too_few"] is True
    assert row["account"]["balance"] > 20.0


def test_sort_board_best_first_too_few_last_cards_by_best_model():
    def row(v, net, n):
        return {"version": v, "net_cents": net, "trades": n, "too_few": n < 10}
    board = [
        {"series": "KXWTI15M", "commodity": "WTI",
         "models": [row("a", 5.0, 50), row("b", 40.0, 3), row("c", 9.0, 20)]},
        {"series": "KXBRENT15M", "commodity": "Brent",
         "models": [row("d", 12.0, 30)]},
    ]
    out = sort_board(board)
    wti = next(c for c in out if c["series"] == "KXWTI15M")
    assert [m["version"] for m in wti["models"]] == ["c", "a", "b"]  # 40c model last: too few
    assert out[0]["series"] == "KXBRENT15M"   # Brent's best (12) beats WTI's best proven (9)


def test_zero_cost_trade_is_never_counted_thin_and_does_not_crash():
    # demo_size divides by cost; the account replay skips cost <= 0, so the
    # size check must skip it too rather than raise (Claude's #568 review).
    from tradehub.fifteen_board import _attach_sizes, _too_thin
    fills = {("S", "c", 5): {"yes": 1}}
    trades = [{"series": "S", "close_time": "c", "offset": 5, "side": "yes", "cost": 0.0}]
    assert _attach_sizes(trades, fills) == 0
    assert trades[0]["ask_size"] == 1
    assert _too_thin(1, 0.0) is False and _too_thin(1, -0.1) is False
    assert _too_thin(1, 0.38) is True        # 1% of $500 at 38c is 13 contracts
    assert _too_thin(None, 0.38) is False    # unmeasured is not thin
