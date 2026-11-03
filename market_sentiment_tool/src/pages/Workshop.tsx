import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { adminJson, verdictTone, type FillRow, type Idea, type IdeaRow } from "@/lib/workshop";
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
      <ul className="mt-3 space-y-2">
        {fills?.map((f) => {
          const name = `${f.symbol} ${f.side} ${f.qty} on ${f.at.slice(0, 10)}`;
          return (
            <li key={f.order_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 text-sm">
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

/** Where an idea stands in its lifecycle, as a chip beside the verdict. Drafts show no chip. */
export function LifecycleChip({ row }: { row: IdeaRow }) {
  const chip = row.killed_at
    ? { label: "Killed", cls: toneClass.bad }
    : row.live_at
      ? { label: "Live", cls: toneClass.ok }
      : row.tracked_at
        ? { label: "Tracking", cls: "border-sky-500/40 bg-sky-500/10 text-sky-300" }
        : row.published_at
          ? { label: "Published", cls: toneClass.flat }
          : null;
  if (!chip) return null;
  return <span className={`rounded-full border px-2 py-0.5 font-semibold ${chip.cls}`}>{chip.label}</span>;
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
      <ul className="mt-3 space-y-2">
        {ideas?.map((i) => (
          <li key={i.id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 hover:border-slate-600">
            <Link to={`/workshop/${i.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:text-white">
              <span className="text-slate-200">{i.title}</span>
              <span className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
                {i.runs} {i.runs === 1 ? "run" : "runs"}
                <LifecycleChip row={i} />
                <span className={`rounded-full border px-2 py-0.5 font-semibold ${toneClass[verdictTone(i.latest_verdict)]}`}>
                  {i.latest_verdict ?? "Not run"}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {ideas && <TradeLabels ideas={ideas} />}
      <p className="mt-12 text-sm text-slate-400">
        Looking for the TradingAgents panel? It has its own tab now:{" "}
        <Link to="/debates" className="text-violet-300 hover:underline">Agent debates</Link>{" "}
        — an opinion panel with a graded record, kept out of the idea pipeline on purpose.
      </p>
    </div>
  );
}
