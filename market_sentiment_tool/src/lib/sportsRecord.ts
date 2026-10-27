export type Sport = "nfl" | "cfb" | "nba" | "pl" | "f1";

export interface SportsRecordRow {
  sport: Sport;
  market: string;
  label: string;
  n: number | null;
  hit_rate: number | null;
  n_pre: number | null;
  hit_rate_pre: number | null;
  vs_market: number | null;
  note: string | null;
}

export interface SportsRecordSport {
  sport: Sport;
  status: "ok" | "unavailable";
  error?: string;
  rows: SportsRecordRow[];
}

export interface SportsRecordResponse {
  as_of: string;
  sports: SportsRecordSport[];
}

import { getJson } from "@/lib/getJson";

export function loadSportsRecord(): Promise<SportsRecordResponse> {
  return getJson<SportsRecordResponse>("/api/sports-record");
}
