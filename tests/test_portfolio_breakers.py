from workshop_fake import DB

from tradehub.portfolio import breakers


def _limits(monkeypatch, daily="2", dd="10", suffix=""):
    monkeypatch.setenv(f"TRADEHUB_BREAKER_DAILY_LOSS_PCT{suffix}", daily)
    monkeypatch.setenv(f"TRADEHUB_BREAKER_MAX_DD_PCT{suffix}", dd)


def test_off_by_default_and_reads_nothing(monkeypatch):
    monkeypatch.delenv("TRADEHUB_BREAKER_DAILY_LOSS_PCT", raising=False)
    monkeypatch.delenv("TRADEHUB_BREAKER_MAX_DD_PCT", raising=False)
    def boom(*a, **k):
        raise AssertionError("no read when off")
    state = breakers.check(None, "main", read_account=boom, read_snapshots=boom)
    assert state["enabled"] is False and state["tripped"] is False


def test_daily_loss_trips_at_the_limit():
    state = breakers.evaluate(equity=98_000, last_equity=100_000, high_water=100_000, daily=2.0, drawdown=None)
    assert state["tripped"] is True and state["daily_loss_pct"] == 2.0 and "daily loss" in state["reasons"][0]
    assert breakers.evaluate(equity=98_100, last_equity=100_000, high_water=100_000, daily=2.0, drawdown=None)["tripped"] is False


def test_drawdown_trips_from_the_high_water_mark():
    state = breakers.evaluate(equity=90_000, last_equity=90_000, high_water=100_000, daily=None, drawdown=10.0)
    assert state["tripped"] is True and state["drawdown_pct"] == 10.0 and "drawdown" in state["reasons"][0]


def test_a_gain_is_not_a_loss():
    state = breakers.evaluate(equity=110_000, last_equity=100_000, high_water=100_000, daily=1.0, drawdown=1.0)
    assert state["tripped"] is False and state["daily_loss_pct"] == 0 and state["drawdown_pct"] == 0


def test_each_book_has_its_own_limits(monkeypatch):
    monkeypatch.delenv("TRADEHUB_BREAKER_DAILY_LOSS_PCT", raising=False)
    monkeypatch.delenv("TRADEHUB_BREAKER_MAX_DD_PCT", raising=False)
    _limits(monkeypatch, suffix="_BIG")
    assert breakers.limits("main") == (None, None)
    assert breakers.limits("big") == (2.0, 10.0)


def test_unreadable_account_fails_closed(monkeypatch):
    _limits(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("broker down")
    state = breakers.check(None, "main", read_account=boom, read_snapshots=lambda s, n: [])
    assert state["tripped"] is True and "could not be read" in state["reasons"][0]


def test_a_bad_limit_fails_closed(monkeypatch):
    _limits(monkeypatch, daily="lots")
    state = breakers.check(None, "main", read_account=lambda: {}, read_snapshots=lambda s, n: [])
    assert state["tripped"] is True and "TRADEHUB_BREAKER_DAILY_LOSS_PCT" in state["reasons"][0]


def test_check_uses_the_snapshots_high_water(monkeypatch):
    _limits(monkeypatch, daily="50", dd="5")
    account = {"account_number": "PA1", "equity": "94000", "last_equity": "94000"}
    state = breakers.check(None, "main", read_account=lambda: account,
                           read_snapshots=lambda s, n: [{"equity": 100_000}, {"equity": 96_000}])
    assert state["tripped"] is True and state["high_water"] == 100_000


def test_notice_is_raised_once_while_open():
    db = DB()
    state = {"tripped": True, "reasons": ["daily loss 3% is past the 2% limit"]}
    breakers.notify(db, "big", state)
    db.db["manual_actions"][0]["state"] = "open"  # the database's default
    breakers.notify(db, "big", state)
    assert len(db.db["manual_actions"]) == 1 and db.db["manual_actions"][0]["kind"] == "breaker"


def test_a_closing_order_is_told_apart_from_an_opening_one():
    assert breakers.closes_position("sell", 10, 10) is True
    assert breakers.closes_position("buy", 5, -10) is True
    assert breakers.closes_position("sell", 11, 10) is False  # flips short
    assert breakers.closes_position("buy", 1, 10) is False
    assert breakers.closes_position("sell", 1, 0) is False
