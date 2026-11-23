"""Figures guard (issue #586): every number the debate writes must come from
its inputs — the exhibit, the options inputs, the frozen peers, or the
recorded context. Rounding to the precision written, percent/fraction and
whole-number years/counts are supported; invented figures are not."""
import pytest

from tradehub.valuation import figures


EXHIBIT = {
    "price": 460.42,
    "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92},
    "implied": {"eps": 27.92},
    "anchor": {"low": 18.34, "high": 19.28,
               "accession": "0000318154-26-000153"},
    "computed_at": "2026-11-08T04:00:00+00:00",
}


def test_numbers_in_extracts_figures_and_percent_fractions():
    nums = figures.numbers_in("Price 23.4, up 12% in FY2026")
    assert 23.4 in nums
    assert 12.0 in nums
    assert 0.12 in nums
    assert 2026 in nums


def test_a_figure_rounded_to_the_precision_written_is_supported():
    assert figures.unsupported("the bear band is 23.4",
                               [{"bands": {"bear": 23.41}}]) == []


def test_a_whole_number_rounds_a_decimal_but_not_a_half_unit():
    # 48 covers 47.8; 46 does not cover 45.5 (half a unit is not rounding).
    assert figures.unsupported("about 48 peers", [{"peer_count": 47.8}]) == []
    assert figures.unsupported("about 46 peers", [{"peer_count": 45.5}]) == ["46"]


def test_a_percent_matches_a_fraction_in_the_sources():
    assert figures.unsupported("a 12% chance", [{"probability": 0.12}]) == []


def test_a_percent_matches_a_percent_input():
    assert figures.unsupported("a 9% implied move",
                               [{"implied_move_pct": 9.0}]) == []


def test_an_invented_price_is_unsupported():
    assert figures.unsupported("fair value is 999.99", [EXHIBIT]) == ["999.99"]


def test_an_invented_percent_is_unsupported():
    assert figures.unsupported("upside of 87%", [EXHIBIT]) == ["87%"]


def test_years_and_small_counts_are_always_allowed():
    assert figures.unsupported("FY2026, a 5-year median across 3 peers",
                               [{}]) == []
    assert figures.unsupported("from 1990 through 2099", [{}]) == []


def test_ids_and_dates_are_not_source_numbers():
    assert figures.unsupported("accession 318154", [EXHIBIT]) == ["318154"]


def test_unsupported_is_unique_and_sorted():
    assert figures.unsupported("999.99 vs 23.4 and 999.99",
                               [{"x": 23.4}]) == ["999.99"]


@pytest.mark.parametrize("text", ["", None])
def test_empty_text_has_no_unsupported_figures(text):
    assert figures.unsupported(text, [EXHIBIT]) == []
