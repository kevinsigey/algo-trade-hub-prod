-- Portfolio check (Kevin, 2026-11-09): the targets state, the check's audit
-- trail, and the stored sleeve return series. One engine
-- (tradehub.portfolio.portfolio_check) reads all three: the machine preflight
-- gate, idea activations, and the Portfolio page's card, so they can never
-- disagree. Service role only; no anon or authenticated access.
--
-- portfolio_targets is the ONE editable config: the check reads the 'global'
-- row at evaluation time, so changing a cap is an UPDATE here, never a deploy.
-- The seed mirrors portfolio_check.DEFAULT_CONFIG (the engine merges the row
-- over its seed, so a partial edit cannot drop a sleeve it didn't mention).
create table if not exists portfolio_targets (
  scope text primary key,
  config jsonb not null,
  updated_at timestamptz not null default now()
);

alter table portfolio_targets enable row level security;

create table if not exists portfolio_check_events (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  book text not null,
  source text not null,
  symbol text,
  outcome text,
  detail text,
  block jsonb
);

create index if not exists portfolio_check_events_book_idx
  on portfolio_check_events(book, at desc);

alter table portfolio_check_events enable row level security;

-- Sleeve and per-symbol daily return series (2y), refreshed weekly by
-- tradehub.scripts.portfolio_series_refresh. days is [[iso-date, ret], ...]
-- ascending; series_key is a sleeve id, 'sym:<SYMBOL>', or '__book__' (the
-- book's own series at refresh-time weights).
create table if not exists portfolio_series (
  book text not null,
  series_key text not null,
  days jsonb not null default '[]'::jsonb,
  refreshed_at timestamptz not null default now(),
  primary key (book, series_key)
);

alter table portfolio_series enable row level security;

insert into portfolio_targets (scope, config)
values ('global', $pc$
{
  "sleeves": {
    "t4_ballast": {
      "label": "T4 ballast (W18 core)",
      "symbols": [
        "GLD",
        "XLP",
        "XLU",
        "XLRE",
        "XLV",
        "VNQ",
        "DBC",
        "USO"
      ],
      "member_min_pct": 2.0,
      "member_max_pct": 8.0
    },
    "t2_kshape": {
      "label": "T2 K-shape carry",
      "symbols": [
        "DLTR",
        "DG",
        "MO",
        "WSM"
      ],
      "member_max_pct": 5.0
    },
    "t3_index": {
      "label": "T3 index",
      "symbols": [
        "SPY",
        "VOO"
      ],
      "sleeve_max_pct": 25.0
    },
    "t8_ai": {
      "label": "T8 AI winners core",
      "symbols": [
        "AAPL",
        "NVDA",
        "MSFT",
        "AVGO",
        "MU",
        "TSM"
      ],
      "sleeve_max_pct": 10.0,
      "equal_inside": true
    },
    "ibit": {
      "label": "IBIT BTC sleeve",
      "symbols": [
        "IBIT"
      ],
      "exit_only": true
    },
    "t7_legacy": {
      "label": "T7 legacy chips",
      "symbols": [
        "TXN",
        "INTC"
      ]
    }
  },
  "name_overrides": {
    "GLD": {
      "target_pct": 11.0,
      "max_pct": 12.0
    }
  },
  "single_name_max_pct": 5.0,
  "clusters": {
    "rates": {
      "label": "Rates factor",
      "symbols": [
        "XLU",
        "XLRE",
        "VNQ"
      ],
      "flag_symbols": [
        "GLD"
      ]
    },
    "ai_complex": {
      "label": "AI complex",
      "symbols": [
        "AAPL",
        "NVDA",
        "MSFT",
        "AVGO",
        "MU",
        "TSM",
        "TXN",
        "INTC"
      ]
    },
    "gold": {
      "label": "Gold",
      "symbols": [
        "GLD"
      ],
      "max_pct": 12.0
    }
  },
  "warn_cluster_rise_pts": 2.0,
  "tag_map": {
    "ai-tech-core": "t8_ai"
  },
  "min_invested_for_caps": 10000.0
}
$pc$::jsonb)
on conflict (scope) do nothing;
