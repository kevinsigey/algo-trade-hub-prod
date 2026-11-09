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

## Phase B — revenue-guided band variant (bands where only revenue is guided)

Population: names with a usable full-year REVENUE guide but no EPS guide that
passes (the recorder's FY-revenue population: ADBE, AMT, GILD, LLY, NOW, PFE,
VRT, CRM, GEV, ...). The construction mirrors the EPS method term for term;
only the guided quantity and the multiple change.

- **Anchor.** Latest guided fiscal year's revenue guide: metric `revenue`,
  unit `usd` (the recorder stores dollar revenue only in base units under
  `usd`; growth-rate rows are `pct` — a different statement, never
  candidates). Segment rows share ticker and period with the consolidated
  guide, so selection works in recorded-time cohorts within the year, latest
  first: inside a cohort, the consolidated guide is the LARGEST midpoint
  among guard-passing candidates — a part never exceeds the whole, an
  accounting identity, not a fit — and a midpoint tie goes to the widest
  stated range (a range carries more than its own midpoint restated as a
  point). If a cohort yields no passing candidate, the next cohort is tried,
  mirroring the EPS candidate walk.
- **Guards.** The frozen magnitude bands under A3's basis-aware disjunction:
  consensus [0.4×, 2.5×] (period-compatible, as for EPS); the trailing
  reference is the latest fiscal-year revenue from EDGAR, band [0.3×, 2.0×];
  rejection requires failing every available reference. A trailing reference
  older than the frozen 550-day fundamentals gate is no reference at all
  (PFE's served FY2023 frame at a Nov-2026 compute is the stale-frame failure
  that gate exists for). low ≤ 0 rejects outright — BKNG's 0.0 row stays
  out, and KO's 5B segment row fails both references and stays out.
- **Multiple — Price/Sales, frozen.** Median over the SAME frozen peer
  groups of (last close × diluted weighted-average shares ÷ latest FY
  revenue), a member excluded on any missing input or a revenue as-of older
  than 550 days; ≥3 valid members, else the same sector widening as the EPS
  multiple. **EV/Sales is considered and deferred**: economically cleaner
  across leverage, but its net-debt inputs are the EDGAR layer's weakest —
  in the Nov 9, 2026 probe a 550-day freshness guard on cash/debt cut the
  biotech group 8→4 members, electrical components 6→4, heavy electrical
  2→1 (cash frames served at 2019/2022/2017 as-ofs), so EV/S medians would
  rest on half-groups or on stale balance sheets. Price/Sales needs only
  the price layer plus two concepts whose as-ofs print and gate cleanly.
  Recorded limitation: Price/Sales ignores leverage differences across
  peers; EV/Sales is the named v2 amendment once EDGAR frame selection is
  repaired. Shares are diluted weighted-average — the EPS method's own
  share basis.
- **Bands.** Per share: guided revenue × M ÷ the subject's diluted shares.
  bear = low end × 0.90 (the same frozen haircut), base = midpoint,
  bull = high end. Implied revenue at the live price = price × shares ÷ M;
  the gap is measured in revenue-range widths; a point guide reports
  gap = null with point_guide = true (Phase 0 precedent). Zone
  classification is the EPS classifier verbatim, reading implied revenue
  against the revenue guide's range.
- **Basis separation is hard.** Every fact sheet carries `band_basis`
  ('eps' | 'revenue'). An EPS anchor that passes always wins; the revenue
  path runs only when no EPS anchor passes. The two bases never mix on one
  sheet, and peer-relative grading families stay separate downstream.
- **Statuses unchanged.** A revenue candidate set that exists but fails its
  guards reads `guide_rejected`; a live revenue anchor and multiple with no
  share count on record reads `no_peer_multiple`, its falsifier saying the
  per-share multiple cannot be formed.

### Phase B implementation annex — two first-compute corrections (Nov 9, 2026)

The first production compute exposed two data-layer defects; the method
above is unchanged by either correction.

1. **"Latest FY revenue" means the filer's total revenue.** The EDGAR layer
   offers two revenue concepts, tried in order — but for lease-heavy filers
   the first (RevenueFromContractWithCustomerExcludingAssessedTax) is an
   ASC 606 sub-stream, not the total: the tower REITs served 0.94B / 0.22B /
   0.24B against true totals of ~10.5B / ~5.7B / ~2.7B, and a first-non-null
   pick built AMT's peer multiple out of sub-streams (95.4×). Rule: among
   the revenue concepts on record, the total is the LARGEST fiscal-year
   value — the same identity as the segment rule (a part never exceeds the
   whole) — and that value, with its as-of, is what both the peer multiple
   and the subject's trailing reference read.
2. **A2 completed: the compact `FY<yy>` year form.** The FY signal has
   always accepted "FY27"; the year extractor behind it only read
   four-digit years and spaced two-digit years, so a glued "FY27" (CRM's
   revenue guide) extracted no year and was invisible to anchor selection
   on both bases. The extractor now reads the FY-prefixed two-digit year.
   The standing rejects still reject: quarter forms are vetoed before year
   extraction, and out-of-window years ("FY30") fail the window.
