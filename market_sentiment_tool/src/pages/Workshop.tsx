import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { adminJson, adminText, verdictTone, type AgentDebateCard, type AgentDebateFeed, type FillRow, type Idea, type IdeaRow } from "@/lib/workshop";
import { SectorTonePanel } from "@/components/SectorTonePanel";

export const toneClass = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  flat: "border-slate-600/60 bg-slate-700/20 text-slate-300",
} as const;

/** Kevin's paper fills, each with the idea it counts toward. A relabel is appended; the order's tag is never erased. */
export function TradeLabels({ ideas }: { ideas: IdeaRow[] }) {
  const [fills, setFills] = useState<FillRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    adminJson<{ state: string; fills?: FillRow[] }>("/api/workshop/fills")
      .then((d) => setFills(d.fills ?? []))
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  const relabel = (order_id: string, value: string) =>
    adminJson("/api/workshop/labels", { method: "POST", body: JSON.stringify({ order_id, idea_id: value ? Number(value) : null }) })
      .then(load)
      .catch((e: Error) => setError(e.message));
  const title = (n: number | null) => (n == null ? "manual" : ideas.find((i) => i.id === n)?.title ?? `idea ${n}`);

  return (
    <>
      <h2 className="mt-12 text-lg font-semibold text-white">Trade labels</h2>
      <p className="mt-1 text-sm text-slate-400">Which idea each paper trade counts toward. Tagged orders label themselves.</p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {fills?.length === 0 && <p className="mt-3 text-sm text-slate-400">No paper trades yet.</p>}
      <ul className="mt-3 divide-y divide-slate-800/80">
        {fills?.map((f) => {
          const name = `${f.symbol} ${f.side} ${f.qty} on ${f.at.slice(0, 10)}`;
          return (
            <li key={f.order_id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
              <span className="font-mono text-slate-200">{name}</span>
              <span className="flex flex-wrap items-center gap-2">
                {f.history.length > 0 && <span className="text-xs text-slate-500">was {title(f.history[f.history.length - 1].from)}</span>}
                <select aria-label={`Idea for ${name}`} value={f.idea_id ?? ""} onChange={(e) => relabel(f.order_id, e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white">
                  <option value="">No idea yet (manual)</option>
                  {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
                </select>
              </span>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Kevin's Workshop: type an idea in plain words, then test it. Admin only (wrapped in RequireAdmin). */
export default function Workshop() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ideas, setIdeas] = useState<IdeaRow[] | null>(null);

  useEffect(() => {
    adminJson<IdeaRow[]>("/api/workshop/ideas")
      .then(setIdeas)
      .catch((e: Error) => setError(e.message));
  }, []);

  const start = async () => {
    const words = text.trim();
    if (!words) return;
    setBusy(true);
    setError(null);
    try {
      const title = words.length > 80 ? `${words.slice(0, 77)}…` : words;
      const idea = await adminJson<Idea>("/api/workshop/ideas", {
        method: "POST",
        body: JSON.stringify({ title: title.length < 3 ? `${title}…` : title, plain_words: words }),
      });
      navigate(`/workshop/${idea.id}?draft=1`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the idea");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Workshop</h1>
      <p className="mt-1 text-sm text-slate-400">An idea in plain words, tested against what it claims. Every verdict is kept, pass or fail.</p>

      <label htmlFor="idea" className="mt-8 block text-sm font-medium text-slate-300">
        Type an idea in plain words
      </label>
      <textarea
        id="idea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="Gold does better than stocks when rates are going up."
        className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none"
      />
      <button
        type="button"
        onClick={start}
        disabled={busy || !text.trim()}
        className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Turn into a test
      </button>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}

      <SectorTonePanel />

      <h2 className="mt-12 text-lg font-semibold text-white">Ideas</h2>
      {ideas === null && !error && <p className="mt-3 text-sm text-slate-400">Loading…</p>}
      {ideas?.length === 0 && <p className="mt-3 text-sm text-slate-400">No ideas yet.</p>}
      <ul className="mt-3 divide-y divide-slate-800/80">
        {ideas?.map((i) => (
          <li key={i.id}>
            <Link to={`/workshop/${i.id}`} className="flex items-center justify-between gap-3 py-3 hover:text-white">
              <span className="text-slate-200">{i.title}</span>
              <span className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
                {i.runs} {i.runs === 1 ? "run" : "runs"}
                <span className={`rounded-full border px-2 py-0.5 font-semibold ${toneClass[verdictTone(i.latest_verdict)]}`}>
                  {i.latest_verdict ?? "Not run"}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {ideas && <TradeLabels ideas={ideas} />}
      <DebateFeed />
    </div>
  );
}

function DebateCard({ card }: { card: AgentDebateCard }) {
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

function DebateFeed() {
  const [feed, setFeed] = useState<AgentDebateFeed | null>(null);
  useEffect(() => {
    adminJson<AgentDebateFeed>("/api/agent-debates").then(setFeed).catch(() => setFeed(null));
  }, []);
  if (!feed?.cards?.length) return null;
  const { h5, h20 } = feed.record;
  const rate = (r: { graded: number; hit_rate: number | null }) =>
    r.graded === 0 || r.hit_rate === null ? "no graded runs yet" : `${r.graded} graded · ${(r.hit_rate * 100).toFixed(0)}% hits`;
  return (
    <section className="mt-12">
      <h2 className="text-lg font-semibold text-white">Agent debates</h2>
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
