import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { adminJson, verdictTone, type Idea, type IdeaRow } from "@/lib/workshop";

export const toneClass = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  flat: "border-slate-600/60 bg-slate-700/20 text-slate-300",
} as const;

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
    </div>
  );
}
