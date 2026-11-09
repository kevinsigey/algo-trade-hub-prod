# Valuation pipeline amendments — Nov 9, 2026 (Kevin: "Do both", 10:51 CT)

Amendments to the frozen Phase 0 method (valuation-bands preregistration,
implementation plan "Frozen method choices"). Each repair is justified on the
method's own intent, never tuned to a name's outcome. The frozen bands,
haircut, peer construction, and zone rules are untouched.

## Phase A — pipeline repair (recover genuine FY EPS guides already on record)

### A1. "±" guidance is a range statement (extractor)

The verbatim-evidence rule exists to keep invented numbers out of the record.
A guide stated as "X ± Y" or "X plus or minus Z%" IS a range: its bounds are
arithmetic on two numbers printed in the quote. The extractor therefore
expands it deterministically — center ± delta, or center × (1 ± pct) for the
percent form — and verification accepts the expanded bounds as values derived
from the verbatim center and delta in the same quote. No number enters the
record that is not printed or derived by this stated arithmetic from printed
numbers. Covers the "±" glyph, "+/-", and the spelled-out "plus or minus"
(the form NVDA actually prints). Fixes the blind spot that dropped Micron's
and Applied Materials' guides wholesale and landed NVIDIA's as a bare point.

### A2. Period phrasings the frozen method already names (anchor selection)

Frozen method item 2 defines a full-year guide as "full year / FY / year
ending / calendar year + a 4-digit year". The implementation's signal matcher
diverged from the method: it missed the hyphenated "full-year" (Abbott's
recorded period) and the bare "Calendar <year>" form (FedEx's). The matcher
is aligned to the method: hyphenated full-year and calendar-year phrasings
count as full-year signals. Every standing exclusion is unchanged — any
quarter token disqualifies, the year must sit in [now−1, now+2] (the 2030
growth-range row stays rejected), and unit/segment guards are untouched.

### A3. The magnitude guard judges a guide against its own basis (guards)

A magnitude guard can only judge a guide against a reference measured on the
same basis. The trailing reference is GAAP diluted EPS (EDGAR); the consensus
reference is the street's adjusted EPS — the same basis as an adjusted guide.
At companies whose GAAP EPS is structurally reduced by recurring charges and
amortization, the GAAP series is not evidence about the adjusted guide: the
two measure different things by construction (AbbVie: guide mid 13.97,
consensus 13.98, GAAP trailing ≈1.0). Amended rule: a trailing-band failure
is a rejection ONLY when the guide is not corroborated by its same-basis
reference — when a period-compatible consensus exists inside the frozen
[0.4×, 2.5×] consensus band, the trailing failure is excused as basis
divergence. The consensus check itself is unchanged (a guide failing its
own-basis reference is still rejected), as are the unit, positivity, and
ordering guards. Pinned regression: the KO noise row (guide 9.0 vs consensus
3.34, ratio 2.69) fails the consensus band — and its trailing band too — and
stays rejected. A guide with no consensus on record gets no excuse: the
trailing band governs alone, exactly as before.
