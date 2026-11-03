import { adminJson } from "@/lib/workshop";

/** The in-site agent (phases 1-2): StrategySpec is the only thing the
 * interpreter's model may emit; the hub validates, stores, and gates it. */

export interface StrategySpec {
  thesis: string;
  catalysts?: string[];
  invalidation?: string[];
  universe: string[];
  entry: { rule: string; band_pct?: number | null };
  sizing: { kind: string; value: number; per_name_cap_pct?: number | null };
  stops: { kind: string; value?: number | null };
  exits: { take_profit_pct?: number | null; time_stop_days?: number | null };
  horizon: { terminal_date?: string | null };
  monitoring?: string[];
  scoring: { benchmark?: string; review_at?: string };
}

export interface AgentGate {
  expressible: boolean;
  note?: string;
  at?: string;
  verdict?: string;
  headline?: string;
  reason?: string | null;
  split_date?: string | null;
  data_start?: string | null;
  data_end?: string | null;
  claim_holds_unseen?: boolean | null;
  shuffle_p?: number | null;
  notes?: string[];
}

export type AgentState = "draft" | "shadow" | "paper-eligible" | "blocked";

export interface AgentSpecRow {
  id: number;
  title: string;
  spec: StrategySpec;
  questions: string[];
  state: AgentState;
  gate: AgentGate | null;
  created_at: string;
  updated_at: string;
}

export interface InterpretResult {
  spec: StrategySpec;
  questions: string[];
  model: string;
}

export const interpretText = (text: string) =>
  adminJson<InterpretResult>("/api/agent/interpret", { method: "POST", body: JSON.stringify({ text }) });

export const createAgentSpec = (spec: StrategySpec, questions: string[], title?: string) =>
  adminJson<AgentSpecRow>("/api/agent/specs", {
    method: "POST",
    body: JSON.stringify({ spec, questions, title }),
  });

export const listAgentSpecs = () =>
  adminJson<{ specs: AgentSpecRow[] }>("/api/agent/specs");

export const patchAgentSpec = (id: number, patch: { title?: string; spec?: StrategySpec }) =>
  adminJson<AgentSpecRow>(`/api/agent/specs/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

export const runAgentGate = (id: number) =>
  adminJson<AgentSpecRow>(`/api/agent/specs/${id}/gate`, { method: "POST" });

export const setAgentState = (id: number, state: AgentState) =>
  adminJson<AgentSpecRow>(`/api/agent/specs/${id}/state`, {
    method: "POST",
    body: JSON.stringify({ state }),
  });
