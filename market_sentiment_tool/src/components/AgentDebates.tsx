import { useEffect, useState } from "react";

import { adminJson, adminText, type AgentDebateCard, type AgentDebateFeed } from "@/lib/workshop";

/**
 * The TradingAgents debate cards + record line. Moved out of the Workshop page
 * (2026-11-02) when the debates got their own tab: a debate is an opinion panel
 * with a graded record, not a step in the idea pipeline, and the two sharing a
 * page invited exactly the confusion the chip exists to prevent.
 */
export function DebateCard({ card }: { card: AgentDebateCard }) {
  const [report, setReport] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const loadReport = () => {
    setBusy(true);
    adminText(`/api/agent-debates/${card.run_id}/report`)
      .then(setReport)
      .catch(() => setReport("The report could not be loaded."))
      .finally(() => setBusy(false));
  };
  const gradeText = (g: AgentDebateCard["grades"][string]) =>
    g === "pending" ? "pending" : `${g.outcome} (${g.ret_pct >= 0 ? "+" : ""}${g.ret_pct.toFixed(1)}%)`;
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-violet-400/40 px-2 py-0.5 text-xs font-semibold text-violet-300">{card.chip}</span>
        <span className="font-semibold text-white">{card.ticker}</span>
        <span className="rounded-full border border-slate-600 px-2 py-0.5 text-xs font-semibold text-slate-200">{card.decision}</span>
        {card.stale && <span className="text-xs font-semibold text-amber-300">stale</span>}
        {card.historical_label && <span className="text-xs text-slate-400">{card.historical_label}</span>}
        {card.status !== "complete" && <span className="text-xs font-semibold text-rose-300">{card.status}{card.error ? `: ${card.error}` : ""}</span>}
      </div>
      <p className="mt-1 text-xs text-slate-400">
        Run {card.run_at_ct.replace("T", " ").slice(0, 16)} CT · as of {card.as_of_date} · framework {card.framework_short} · {card.llm_model} · cost {typeof card.cost_usd === "number" ? `$${card.cost_usd.toFixed(2)}` : card.cost_usd}
      </p>
      <p className="mt-1 text-xs text-slate-400">Grades: +5d {gradeText(card.grades["+5d"])} · +20d {gradeText(card.grades["+20d"])}</p>
      <details className="mt-2 text-sm text-slate-300">
        <summary className="cursor-pointer text-slate-200">The debate</summary>
        <div className="mt-2 space-y-2">
          {Object.entries(card.analyst_summaries).map(([k, v]) => (
            <p key={k}><span className="font-semibold capitalize text-slate-100">{k}:</span> {v}</p>
          ))}
          <p><span className="font-semibold text-emerald-300">Bull:</span> {card.bull_case}</p>
          <p><span className="font-semibold text-rose-300">Bear:</span> {card.bear_case}</p>
          <p><span className="font-semibold text-slate-100">Trader:</span> {card.trader_rationale}</p>
          <p><span className="font-semibold text-slate-100">Risk:</span> {card.risk_verdict}</p>
          <p className="text-xs text-slate-500">Inputs: {card.inputs_note}</p>
          {card.has_report && report === null && (
            <button type="button" className="text-sm text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white" disabled={busy} onClick={loadReport}>
              {busy ? "Loading…" : "Full report"}
            </button>
          )}
          {report !== null && <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{report}</pre>}
        </div>
      </details>
    </li>
  );
}

export function DebateFeed({ refreshKey = 0 }: { refreshKey?: number }) {
  const [feed, setFeed] = useState<AgentDebateFeed | null>(null);
  useEffect(() => {
    adminJson<AgentDebateFeed>("/api/agent-debates").then(setFeed).catch(() => setFeed(null));
  }, [refreshKey]);
  if (!feed) return <p className="mt-3 text-sm text-slate-400">Loading the debate record…</p>;
  if (!feed.cards?.length) return <p className="mt-3 text-sm text-slate-400">No debates yet. Run the first one above.</p>;
  const { h5, h20 } = feed.record;
  const rate = (r: { graded: number; hit_rate: number | null }) =>
    r.graded === 0 || r.hit_rate === null ? "no graded runs yet" : `${r.graded} graded · ${(r.hit_rate * 100).toFixed(0)}% hits`;
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold text-white">The record</h2>
      <p className="mt-1 text-xs text-slate-400">
        Debate record (kept separate from every model statistic): +5d {rate(h5)}, {h5.no_calls} no-calls · +20d {rate(h20)}, {h20.no_calls} no-calls.
      </p>
      {feed.banner && <p className="mt-2 rounded-lg border border-amber-400/40 px-3 py-2 text-sm font-semibold text-amber-300">{feed.banner}</p>}
      <ul className="mt-2 divide-y divide-slate-800/80">
        {feed.cards.map((c) => <DebateCard key={c.run_id} card={c} />)}
      </ul>
    </section>
  );
}
