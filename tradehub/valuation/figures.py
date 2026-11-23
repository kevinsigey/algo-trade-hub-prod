"""The no-invented-figures guard (issue #586).

Port of predictor-hub's explainer/validate.py idea (`numbers_in`, `_pool`,
`_known`) with valuation's own rules: percent inputs written as `*_pct`,
fractions as probabilities, and whole-number years/counts always allowed.
Every number the debate writes must come from Exhibit A, the options inputs,
the frozen peers or the recorded context (and a decision rationale may also
cite the validated packet).

Ids, accessions, dates and the packet's own rationale are NOT number sources:
their digits would otherwise excuse any figure, or let an invented figure in
an echoed rationale support itself.
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(r"[-−+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
_SKIP_KEY = re.compile(
    r"(?:^id$|_id$|_at$|_as_of$|^ticker$|^accession$|^rationale$)")
_PCT_KEY = re.compile(r"(?:_pct$|percent|probability)")
_ALWAYS_ALLOWED_MAX = 10
_YEAR_MIN, _YEAR_MAX = 1990, 2100


def _candidates(token: str) -> list[tuple[float, float]]:
    """(value, rounding tolerance) readings of a written number: '23.4'
    covers 23.35-23.45; '62%' reads as either 0.62 or 62."""
    t = token.replace("−", "-").replace(",", "")
    pct = t.endswith("%")
    t = t.rstrip("%")
    decimals = len(t.split(".")[1]) if "." in t else 0
    v, tol = float(t), 0.5 * 10 ** -decimals
    if pct:
        return [(v / 100, tol / 100), (v, tol)]
    return [(v, tol)]


def numbers_in(text: str) -> set[float]:
    """Every figure a piece of prose writes, with a percent read both ways."""
    if not isinstance(text, str):
        return set()
    return {v for tok in _NUM_RE.findall(text) for v, _ in _candidates(tok)}


def _pool(sources) -> tuple[set[float], set[float]]:
    """(numbers, written percents) the prose may cite. Walks dicts, lists and
    markdown alike; ids, dates and rationales are left out so their digits
    cannot excuse an invented figure."""
    nums: set[float] = set()
    pcts: set[float] = set()

    def walk(node, key=""):
        if isinstance(node, bool) or node is None or _SKIP_KEY.search(key):
            return
        if isinstance(node, (int, float)):
            nums.add(float(node))
            if _PCT_KEY.search(key):
                pcts.add(float(node))
        elif isinstance(node, str):
            for tok in _NUM_RE.findall(node):
                v = float(tok.replace("−", "-").replace(",", "").rstrip("%"))
                nums.add(v)
                if tok.endswith("%"):
                    pcts.add(v)
                    nums.add(v / 100)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, key)

    walk(sources)
    return nums, pcts


def _known(token: str, nums: set[float], pcts: set[float]) -> bool:
    t = token.replace("−", "-").replace(",", "")
    pct = t.endswith("%")
    t = t.rstrip("%").lstrip("+-")
    decimals = len(t.split(".")[1]) if "." in t else 0
    tol = 0.5 * 10 ** -decimals
    v = float(t)
    if pct:
        # A percent is a fraction in the facts (0.12 -> 12%) or a percent
        # the facts wrote (implied_move_pct: 9.0 -> 9%); never a raw count.
        return (any(abs(v / 100 - p) <= tol / 100 + 1e-9
                    for p in nums if 0 <= p <= 1)
                or any(abs(v - q) <= tol + 1e-9 for q in pcts))
    if decimals == 0 and (0 <= v <= _ALWAYS_ALLOWED_MAX
                          or _YEAR_MIN <= v <= _YEAR_MAX):
        # Counts ("5-year median") and years need no source figure.
        return True
    if decimals == 0:
        # A whole number rounds a decimal (48 for 47.8) but is not a half
        # unit (46 does not stand for 45.5).
        return any((abs(v - abs(p)) < tol or v == abs(p)) for p in nums)
    return any(abs(v - abs(p)) <= tol + 1e-9 for p in nums)


def unsupported(text, sources) -> list[str]:
    """The written figures with no matching source number, sorted and unique."""
    if not isinstance(text, str) or not text:
        return []
    nums, pcts = _pool(sources)
    return sorted({tok for tok in _NUM_RE.findall(text)
                   if not _known(tok, nums, pcts)})
