-- Valuation bands Phase B (2026-11-09 amendment): revenue-guided bands.
-- Every fact sheet carries its band basis; the two bases never mix on one
-- sheet. Existing rows are all EPS-basis by construction, hence the default.
-- implied_revenue is the revenue-basis sibling of implied_eps (the revenue
-- the live price implies at the frozen peer Price/Sales multiple).
alter table valuation_fact_sheets
  add column if not exists band_basis text not null default 'eps'
    check (band_basis in ('eps', 'revenue')),
  add column if not exists implied_revenue numeric;
