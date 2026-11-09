"""Peer-group / universe tests (amended universe: S&P 500 watch tier + open
tier, guidance-gated — spec amendment Nov 8 2026 21:15 CT)."""
from tradehub.valuation import peers


def test_watch_tier_is_sp500():
    assert peers.in_watch_tier("AMGN") is True
    assert peers.in_watch_tier("CRWV") is False  # open tier only
    assert len(peers.SP500) >= 500


def test_hyperscalers_grouped_together():
    members = peers.group_members("hyperscalers")
    for t in ("MSFT", "GOOGL", "GOOG", "AMZN", "META", "ORCL"):
        assert t in members
    assert peers.peer_group("MSFT") == "hyperscalers"
    assert peers.peer_group("AAPL") != "hyperscalers"


def test_industry_groups_from_gics():
    assert peers.peer_group("AMGN") == "biotechnology"
    assert peers.peer_group("NVDA") == "semiconductors"
    assert peers.peer_group("SBUX") == "restaurants"
    assert peers.peer_group("DUK") == "utilities_regulated"
    assert "AMGN" in peers.group_members("biotechnology")


def test_open_tier_extras():
    assert peers.peer_group("CRWV") == "hyperscalers"
    assert peers.sector("AMGN") == "Health Care"
    assert peers.peer_group("ZZZZ_NOT_REAL") is None
