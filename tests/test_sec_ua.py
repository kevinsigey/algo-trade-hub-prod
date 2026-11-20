"""One SEC User-Agent helper (Claude's #559 fix round): every SEC
request in the hub is built by tradehub.sec_ua.sec_user_agent, the
contact comes from SEC_CONTACT_EMAIL, and an unset variable is a
clear failure in the download path -- never a silent placeholder
and never a literal in code."""

from __future__ import annotations

from pathlib import Path

import pytest

from tradehub.sec_ua import sec_user_agent

ROOT = Path(__file__).resolve().parents[1]


def test_the_helper_builds_the_agent_from_the_environment(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "sec-contact@example.com")
    assert sec_user_agent() == {
        "User-Agent": "algo-trade-hub research sec-contact@example.com"}


def test_the_helper_refuses_an_unset_contact(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="SEC_CONTACT_EMAIL"):
        sec_user_agent()


def test_the_helper_refuses_a_blank_contact(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "  ")
    with pytest.raises(RuntimeError, match="SEC_CONTACT_EMAIL"):
        sec_user_agent()


def test_no_literal_contact_email_anywhere_in_the_package():
    hits = [str(p) for p in (ROOT / "tradehub").rglob("*.py")
            if "sigeykevin@gmail.com" in p.read_text(errors="ignore")]
    assert hits == []


def test_the_download_path_fails_clearly_without_a_contact(
        tmp_path, monkeypatch):
    # edgar_bulk.download must raise the helper's error before any
    # network call when SEC_CONTACT_EMAIL is unset.
    import requests

    from tradehub.screening import edgar_bulk

    def boom(*a, **kw):
        raise AssertionError("network touched without a contact")

    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="SEC_CONTACT_EMAIL"):
        edgar_bulk.download("https://example.invalid/z.zip",
                            tmp_path / "z.zip")
