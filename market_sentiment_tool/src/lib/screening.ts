/** Screening (Part A3): types for the catalog, run payloads and saved screens. */

export interface CatalogFn {
  name: string;
  category: string;
  kind: string;
  params: Record<string, unknown>;
  returns: string;
  doc: string;
  source: string;
}

export interface Catalog {
  functions: CatalogFn[];
  universe_builders: string[];
  ops: { op: string; doc?: string }[];
}

export interface RunFooter {
  spec_name?: string;
  run_at?: string;
  universe_size?: number;
  universe_capped?: { cap: number; universe_size_full: number };
  survivors?: number;
  columns?: Record<string, { fn?: string; source?: string; as_of?: string }>;
  context?: Record<string, unknown>;
  missing?: { field: string; reason?: string }[];
  spec_echo?: Record<string, unknown>;
}

export interface RunPayload {
  columns: string[];
  rows: Record<string, unknown>[];
  footer: RunFooter;
}

export type ScreenSpec = Record<string, unknown>;
