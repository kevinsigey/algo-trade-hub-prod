/** Shapes served by /api/crypto/board and /api/crypto/sniper-verdict (phase-3 §5). */

export interface HourlyLine {
  closes_at: string;
  shape: "coin_flip" | "step";
  coin_flip_strike?: number;
  implied_pct?: number;
  one_sided?: boolean;
  bracket?: [number, number];
  strikes_quoted: number;
}

export interface QuarterLine {
  closes_at: string;
  floor: number;
  implied_pct: number;
  one_sided: boolean;
}

export interface CryptoBoard {
  generated_at: string;
  note: string;
  spots: Record<string, number | null>;
  hourly: Record<string, HourlyLine | null>;
  quarter: Record<string, QuarterLine | null>;
}

export interface AssetRecord {
  count: number;
  hit_rate: number | null;
  virtual_pnl_pct: number;
  brier_score: number | null;
}

export interface SniperVerdict {
  record: string;
  graded_on: string;
  worker: { first_row: string | null; last_row: string | null; stopped: string; venue: string };
  population: {
    archived_rows: number;
    by_status: Record<string, number>;
    grading_population: number;
    considered: number;
    dead_zone: number;
    dead_zone_share: number | null;
    graded: number;
  };
  overall: AssetRecord;
  by_asset: Record<string, AssetRecord>;
  buckets: Record<string, { count: number; hit_rate: number }>;
  price_source: string;
  method: string;
}

export const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;

// One money format and one CT timestamp style live in lib/format (§6);
// re-exported here so the page's imports stay in one place.
export { ctTime, usd } from "@/lib/format";
