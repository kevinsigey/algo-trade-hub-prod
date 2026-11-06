-- Guidance recorder: earnings-release filings and the guidance items extracted from them.
-- Service role only; no anon or authenticated access.
create table if not exists guidance_filings (
  id bigint generated always as identity primary key,
  cik text not null,
  ticker text not null,
  accession text not null unique,
  form text,
  items text,
  filed_at timestamptz,
  doc_url text,
  status text not null default 'new' check (status in ('new', 'extracted', 'no_guidance', 'failed')),
  error text,
  dropped int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists guidance_records (
  id bigint generated always as identity primary key,
  accession text not null references guidance_filings(accession),
  ticker text not null,
  period text,
  metric text not null check (metric in ('revenue', 'eps_gaap', 'eps_adjusted', 'capex', 'operating_margin', 'other')),
  unit text check (unit in ('usd', 'usd_per_share', 'pct')),
  low numeric,
  high numeric,
  evidence text,
  consensus numeric,
  consensus_period text,
  consensus_source text,
  model text,
  created_at timestamptz not null default now()
);

create index if not exists guidance_filings_status_idx on guidance_filings(status);
create index if not exists guidance_records_ticker_idx on guidance_records(ticker);

alter table guidance_filings enable row level security;
alter table guidance_records enable row level security;
revoke all on guidance_filings from anon, authenticated;
revoke all on guidance_records from anon, authenticated;
