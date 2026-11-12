"""The auto-trader master switch (Kevin, 2026-11-12): TRADEHUB_AUTO_TRADER gates
both cron entrypoints that place idea orders -- the morning runner and the
protective-stop job. It defaults OFF: after the runner re-bought positions Kevin
had deliberately exited (stale sim-era weights), the auto-trader stays off until
he turns it back on. The per-book order switches are a different flow (Kevin's
own orders, the machine keys) and are not touched here."""

import pytest

from tradehub.portfolio import books
from tradehub.scripts import paper_orders_protect, paper_orders_run


@pytest.fixture(autouse=True)
def _no_local_env(monkeypatch):
    monkeypatch.setattr(paper_orders_run, "load_local_env", lambda: None)
    monkeypatch.setattr(paper_orders_protect, "load_local_env", lambda: None)


def test_switch_defaults_off(monkeypatch):
    monkeypatch.delenv("TRADEHUB_AUTO_TRADER", raising=False)
    assert books.auto_trader_enabled() is False


def test_switch_on_only_for_exact_on(monkeypatch):
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", "on")
    assert books.auto_trader_enabled() is True
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", '"on"')  # quoted, like the .env values
    assert books.auto_trader_enabled() is True
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", "off")
    assert books.auto_trader_enabled() is False
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", "yes")
    assert books.auto_trader_enabled() is False


def test_morning_runner_does_nothing_while_off(monkeypatch, capsys):
    monkeypatch.delenv("TRADEHUB_AUTO_TRADER", raising=False)

    def _boom():
        raise AssertionError("the disabled runner must not touch the database")

    monkeypatch.setattr(paper_orders_run, "get_client", _boom)
    assert paper_orders_run.main() == 0
    assert '"orders": "disabled"' in capsys.readouterr().out


def test_morning_runner_runs_both_books_when_on(monkeypatch):
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", "on")
    monkeypatch.setattr(paper_orders_run, "get_client", lambda: object())
    seen = []

    def _run(now, supa, book_name=None):
        seen.append(book_name)
        return {}, {}

    monkeypatch.setattr(paper_orders_run, "run", _run)
    assert paper_orders_run.main() == 0
    assert seen == books.names()


def test_protect_places_nothing_while_off(monkeypatch, capsys):
    monkeypatch.delenv("TRADEHUB_AUTO_TRADER", raising=False)
    monkeypatch.setattr(paper_orders_protect, "get_client", lambda: object())
    monkeypatch.setattr(paper_orders_protect, "check_fills", lambda now, supa: ({"checked": 3}, {}))

    def _boom(now, supa):
        raise AssertionError("the disabled protect job must not place or cancel")

    monkeypatch.setattr(paper_orders_protect, "run", _boom)
    assert paper_orders_protect.main() == 0
    assert '"protect": "disabled"' in capsys.readouterr().out


def test_protect_still_protects_when_on(monkeypatch):
    monkeypatch.setenv("TRADEHUB_AUTO_TRADER", "on")
    monkeypatch.setattr(paper_orders_protect, "get_client", lambda: object())
    monkeypatch.setattr(paper_orders_protect, "check_fills", lambda now, supa: ({}, {}))
    seen = []

    def _run(now, supa):
        seen.append(True)
        return {}, {}

    monkeypatch.setattr(paper_orders_protect, "run", _run)
    assert paper_orders_protect.main() == 0
    assert seen == [True]
