import { useEffect, useState } from "react";

import { adminJson, adminText, type AgentDebateCard, type AgentDebateFeed } from "@/lib/workshop";

/**
 * The TradingAgents debate cards + record line. Moved out of the Workshop page
 * (2026-11-02) when the debates got their own tab: a debate is an opinion panel
 * with a graded record, not a step in the idea pipeline, and the two sharing a
 * page invited exactly the confusion the chip exists to prevent.
 *
 * Visual pass (Kevin, 2026-11-02): the result leads. The decision is the card's
 * headline, the bull and bear cases sit side by side as opposing panels, the
 * four analysts are tiles, and the grades are chips -- the full text is all
 * still here, one glance lower. No strength score is drawn from the text:
 * the panels present the two cases, they do not measure them.
 */

function decisionClass(decision: string): string {
  const d = decision.toLowerCase();
  if (d.includes("buy") || d.includes("overweight")) return "border-emerald-400/50 bg-emerald-950/40 text-emerald-300";
  if (d.includes("sell") || d.includes("underweight")) return "border-rose-400/50 bg-rose-950/40 text-rose-300";
  return "border-slate-500/50 bg-slate-800/60 text-slate-200";
}

function gradeChip(label: string, g: AgentDebateCard["grades"][string]): { text: string; cls: string } {
  if (g === "pending") return { text: `${label} pending`, cls: "border-slate-700 text-slate-400" };
  const cls = g.outcome === "hit" ? "border-emerald-400/40 text-emerald-300" : g.outcome === "miss" ? "border-rose-400/40 text-rose-300" : "border-slate-600 text-slate-300";
  return { text: `${label} ${g.outcome} (${g.ret_pct >= 0 ? "+" : ""}${g.ret_pct.toFixed(1)}%)`, cls };
}

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
  const g5 = gradeChip("+5d", card.grades["+5d"]);
  const g20 = gradeChip("+20d", card.grades["+20d"]);
  return (
    <li>
      <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        {/* The verdict first: ticker, the decision as the headline, status flags, grades. */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xl font-bold tracking-tight text-white">{card.ticker}</span>
          <span className={`rounded-lg border px-3 py-1 text-base font-extrabold ${decisionClass(card.decision)}`}>{card.decision}</span>
          <span className="rounded-full border border-violet-400/40 px-2 py-0.5 text-xs font-semibold text-violet-300">{card.chip}</span>
          {card.stale && <span className="text-xs font-semibold text-amber-300">stale</span>}
          {card.historical_label && <span className="text-xs text-slate-400">{card.historical_label}</span>}
          {card.status !== "complete" && <span className="text-xs font-semibold text-rose-300">{card.status}{card.error ? `: ${card.error}` : ""}</span>}
          <span className="ml-auto flex flex-wrap gap-1.5">
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g5.cls}`}>{g5.text}</span>
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g20.cls}`}>{g20.text}</span>
          </span>
        </div>

        {/* Bull vs bear, side by side. */}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-emerald-900/60 bg-emerald-950/20 p-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-300">Bull case</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-200">{card.bull_case}</p>
          </div>
          <div className="rounded-lg border border-rose-900/60 bg-rose-950/20 p-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-rose-300">Bear case</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-200">{card.bear_case}</p>
          </div>
        </div>

        {/* The four analysts as tiles. */}
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(card.analyst_summaries).map(([k, v]) => (
            <div key={k} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">{k}</h3>
              <p className="mt-1 text-xs leading-relaxed text-slate-300">{v}</p>
            </div>
          ))}
        </div>

        {/* Trader and risk: the two voices that turn the debate into the decision. */}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-slate-800 p-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Trader</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">{card.trader_rationale}</p>
          </div>
          <div className="rounded-lg border border-slate-800 p-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Risk panel</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">{card.risk_verdict}</p>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>
            Run {card.run_at_ct.replace("T", " ").slice(0, 16)} CT · as of {card.as_of_date} · framework {card.framework_short} · {card.llm_model} · cost {typeof card.cost_usd === "number" ? `$${card.cost_usd.toFixed(2)}` : card.cost_usd}
          </span>
          <span>Inputs: {card.inputs_note}</span>
          {card.has_report && report === null && (
            <button type="button" className="text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white" disabled={busy} onClick={loadReport}>
              {busy ? "Loading…" : "Full report"}
            </button>
          )}
        </div>
        {report !== null && <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{report}</pre>}
      </article>
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
    r.graded === 0 || r.hit_rate === null ? "no graded runs yet" : `${(r.hit_rate * 100).toFixed(0)}% hits`;
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold text-white">The record</h2>
      <p className="mt-1 text-xs text-slate-400">Debate record (kept separate from every model statistic):</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="font-display text-3xl leading-none text-white tabular-nums">{rate(h5)}</div>
          <div className="mt-1 text-xs text-slate-400">+5d · {h5.graded} graded · {h5.no_calls} no-calls</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="font-display text-3xl leading-none text-white tabular-nums">{rate(h20)}</div>
          <div className="mt-1 text-xs text-slate-400">+20d · {h20.graded} graded · {h20.no_calls} no-calls</div>
        </div>
      </div>
      {feed.banner && <p className="mt-3 rounded-lg border border-amber-400/40 px-3 py-2 text-sm font-semibold text-amber-300">{feed.banner}</p>}
      <ul className="mt-4 space-y-4">
        {feed.cards.map((c) => <DebateCard key={c.run_id} card={c} />)}
      </ul>
    </section>
  );
}
