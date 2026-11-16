-- Portfolio check v6 cap remap (Kevin's ruling, 2026-11-16, expedited
-- ahead of thesis-tracker PR 5): the stored targets row is rewritten to
-- the Thesis v6 caps, mirroring portfolio_check.DEFAULT_CONFIG exactly
-- (the engine merges the row over its seed, and a merge cannot retire
-- a sleeve -- the row itself has to lose the T4 ballast sleeve).
--   * core (index) sleeve cap 25 -> 50 (pct of invested): the v6 core
--     target is 40-45 pct of the book; at the v6 10 pct cash floor,
--     50 pct of invested is 45 pct of the book. The 25 cap was the
--     wall that stopped the staged core fills on 2026-11-16.
--   * T4 ballast RETIRED (W18/T4 shelved with the Systematic sleeve):
--     its 2-8 member band and 2 pct floor are gone. XLU/XLV/XLP move
--     to the new Regime sleeve (member cap 20); XLRE/VNQ/DBC/USO and
--     GLD become unassigned (single-name rule; GLD keeps its override).
--   * Regime single names AEP/D/JPM hold the 5 pct single-name line
--     via name overrides inside the sleeve's 20 member band.
--   * Single-name 5 ex-index unchanged; exits unchanged (a block
--     fires only when an order deepens a breach).
-- Applied to the VPS-local database only, on Kevin's go of 2026-11-16;
-- the cloud project stays the frozen rollback copy.

insert into portfolio_targets (scope, config)
values ('global', $pc$
{
  "sleeves": {
    "regime": {
      "label": "Regime (v6)",
      "symbols": [
        "XLU",
        "XLV",
        "XLP",
        "XLF",
        "AEP",
        "D",
        "JPM",
        "BTAL",
        "KMLM",
        "UUP"
      ],
      "member_max_pct": 20.0
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
      "label": "Core beta (v6)",
      "symbols": [
        "SPY",
        "VOO"
      ],
      "sleeve_max_pct": 50.0
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
    },
    "AEP": {
      "max_pct": 5.0
    },
    "D": {
      "max_pct": 5.0
    },
    "JPM": {
      "max_pct": 5.0
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
on conflict (scope) do update
  set config = excluded.config, updated_at = now();
